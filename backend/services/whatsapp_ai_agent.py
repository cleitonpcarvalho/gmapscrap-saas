from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import Lead, WhatsAppAiSettings, WhatsAppConversation, WhatsAppInstance, WhatsAppMessage
from backend.services.crm import CRM_STAGES, update_crm_stage
from backend.services.whatsapp_providers.evolution import EvolutionProvider


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
RECENT_AI_REPLY_SECONDS = 10
DEFAULT_SYSTEM_PROMPT = (
    "Você é um assistente comercial da Automa Soluct no WhatsApp. "
    "Converse de forma natural, educada e consultiva. "
    "Ajude o lead a entender como automações e integrações podem reduzir trabalho manual. "
    "Não prometa resultados garantidos e não invente informações."
)
SYSTEM_GUARDRAILS = (
    "Responda sempre em português do Brasil, de forma curta e natural para WhatsApp. "
    "Use no máximo 3 frases. "
    "Se identificar interesse, desinteresse ou avanço no funil, chame a function update_lead_stage. "
    "Mesmo quando chamar a function, também escreva a resposta que deve ser enviada ao usuário."
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AiResponse:
    text: str
    tool_calls: list[dict[str, Any]]


def get_or_create_ai_settings(db: Session) -> WhatsAppAiSettings:
    settings = db.get(WhatsAppAiSettings, 1)
    if settings:
        return settings

    settings = WhatsAppAiSettings(id=1, system_prompt=DEFAULT_SYSTEM_PROMPT, enabled=False)
    db.add(settings)
    db.flush()
    return settings


def handle_inbound_message(
    db: Session,
    conversation: WhatsAppConversation,
    inbound_message: WhatsAppMessage,
    *,
    sender_phone: str,
    provider: EvolutionProvider | None = None,
) -> dict[str, str]:
    ai_settings = get_or_create_ai_settings(db)
    if not ai_settings.enabled:
        return {"status": "disabled"}

    if _has_recent_ai_reply(db, conversation.id):
        return {"status": "skipped_recent_reply"}

    try:
        ai_response = generate_ai_response(db, conversation, ai_settings)
        _apply_tool_calls(db, conversation, ai_response.tool_calls)
        response_text = ai_response.text.strip()
        if not response_text:
            return {"status": "empty_response"}

        whatsapp_provider = provider or EvolutionProvider()
        instance_name = _provider_instance_name(conversation.instance)
        recipient_phone = _recipient_phone(sender_phone, conversation.lead)
        provider_response = whatsapp_provider.send_text_message(instance_name, recipient_phone, response_text)
        now = datetime.now(timezone.utc)
        outbound_message = WhatsAppMessage(
            conversation_id=conversation.id,
            direction="outbound",
            content=response_text,
            message_type="text",
            provider_message_id=_extract_provider_message_id(provider_response),
            created_at=now,
        )
        conversation.last_message_at = now
        db.add(outbound_message)
        db.flush()
        return {"status": "sent"}
    except Exception:
        logger.exception("Falha ao gerar ou enviar resposta automática de WhatsApp para mensagem %s", inbound_message.id)
        return {"status": "error"}


def generate_ai_response(
    db: Session,
    conversation: WhatsAppConversation,
    ai_settings: WhatsAppAiSettings,
) -> AiResponse:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY não está configurada no backend.")

    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json=_openai_payload(db, conversation, ai_settings),
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI retornou erro {response.status_code}: {response.text[:600]}")

    payload = response.json()
    return AiResponse(text=_extract_output_text(payload), tool_calls=_extract_tool_calls(payload))


def _openai_payload(db: Session, conversation: WhatsAppConversation, ai_settings: WhatsAppAiSettings) -> dict[str, Any]:
    settings = get_settings()
    system_prompt = (ai_settings.system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    lead_context = _lead_context(conversation.lead)
    history = _conversation_history(db, conversation.id)

    return {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": f"{system_prompt}\n\n{SYSTEM_GUARDRAILS}\n\nContexto do lead:\n{lead_context}",
            },
            *history,
        ],
        "tools": [_update_lead_stage_tool_schema()],
        "tool_choice": "auto",
        "max_output_tokens": 450,
    }


def _conversation_history(db: Session, conversation_id: int, limit: int = 20) -> list[dict[str, str]]:
    messages = list(
        db.scalars(
            select(WhatsAppMessage)
            .where(WhatsAppMessage.conversation_id == conversation_id)
            .order_by(desc(WhatsAppMessage.created_at), desc(WhatsAppMessage.id))
            .limit(limit)
        ).all()
    )
    return [
        {
            "role": "assistant" if message.direction == "outbound" else "user",
            "content": message.content or message.audio_transcript or "",
        }
        for message in reversed(messages)
        if (message.content or message.audio_transcript or "").strip()
    ]


def _lead_context(lead: Lead | None) -> str:
    if not lead:
        return "Lead ainda não identificado na base."

    parts = [
        f"Empresa: {lead.name}",
        f"Telefone: {lead.phone or '-'}",
        f"Site: {lead.website or '-'}",
        f"Nicho: {lead.niche or '-'}",
        f"Localidade: {lead.location or '-'}",
    ]
    return "\n".join(parts)


def _update_lead_stage_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "update_lead_stage",
        "description": "Atualiza o estágio do lead no CRM quando a conversa indicar mudança clara no funil.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["stage", "reason"],
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": ["new", "responded", "qualified", "not_interested", "converted"],
                    "description": "Novo estágio do lead no CRM.",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo curto para registrar nas notas de qualificação.",
                },
            },
        },
    }


def _extract_output_text(response_payload: dict[str, Any]) -> str:
    if response_payload.get("output_text"):
        return str(response_payload["output_text"]).strip()

    chunks: list[str] = []
    for item in response_payload.get("output", []):
        if not isinstance(item, dict):
            continue
        content_items = item.get("content") if isinstance(item.get("content"), list) else []
        for content in content_items:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks).strip()


def _extract_tool_calls(response_payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in response_payload.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call" and item.get("name") == "update_lead_stage":
            calls.append(item)
        for tool_call in item.get("tool_calls", []) if isinstance(item.get("tool_calls"), list) else []:
            if isinstance(tool_call, dict) and tool_call.get("name") == "update_lead_stage":
                calls.append(tool_call)
    return calls


def _apply_tool_calls(db: Session, conversation: WhatsAppConversation, tool_calls: list[dict[str, Any]]) -> None:
    if not tool_calls:
        return
    if not conversation.lead_id:
        logger.warning("IA solicitou atualização de CRM, mas conversa %s não possui lead vinculado.", conversation.id)
        return

    for tool_call in tool_calls:
        arguments = _tool_arguments(tool_call)
        stage = str(arguments.get("stage") or "").strip()
        reason = str(arguments.get("reason") or "").strip()
        if stage not in CRM_STAGES:
            logger.warning("IA solicitou estágio de CRM inválido para conversa %s: %s", conversation.id, stage)
            continue
        update_crm_stage(db, conversation.lead_id, stage, changed_by="ai", reason=reason)


def _tool_arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
    raw_arguments = tool_call.get("arguments") or tool_call.get("function", {}).get("arguments") or {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str) and raw_arguments.strip():
        try:
            data = json.loads(raw_arguments)
        except json.JSONDecodeError:
            logger.warning("OpenAI retornou argumentos inválidos para update_lead_stage: %s", raw_arguments[:300])
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _has_recent_ai_reply(db: Session, conversation_id: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=RECENT_AI_REPLY_SECONDS)
    return bool(
        db.scalar(
            select(WhatsAppMessage.id)
            .where(
                WhatsAppMessage.conversation_id == conversation_id,
                WhatsAppMessage.direction == "outbound",
                WhatsAppMessage.created_at >= cutoff,
            )
            .limit(1)
        )
    )


def _provider_instance_name(instance: WhatsAppInstance) -> str:
    return (instance.evolution_instance_name or instance.name or "").strip()


def _recipient_phone(sender_phone: str, lead: Lead | None) -> str:
    raw_phone = sender_phone or (lead.phone if lead else "") or ""
    return re.sub(r"\D+", "", raw_phone)


def _extract_provider_message_id(provider_response: dict[str, Any]) -> str | None:
    for key in ("key", "message", "data"):
        value = provider_response.get(key)
        if isinstance(value, dict):
            nested_id = value.get("id") or value.get("messageId") or value.get("message_id")
            if nested_id:
                return str(nested_id)

    for key in ("id", "messageId", "message_id"):
        if provider_response.get(key):
            return str(provider_response[key])

    return None
