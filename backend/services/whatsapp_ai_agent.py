from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import (
    Lead,
    LeadTag,
    Tag,
    WhatsAppAiSettings,
    WhatsAppConversation,
    WhatsAppInstance,
    WhatsAppMessage,
    WhatsAppPortfolioItem,
)
from backend.services.crm import CRM_STAGES, update_crm_stage
from backend.services.whatsapp_providers.evolution import EvolutionProvider


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
RECENT_AI_REPLY_SECONDS = 10
AI_TAG_PROMPT_LIMIT = 30
AI_TOOL_NAMES = {"update_lead_stage", "apply_lead_tags"}
DEFAULT_SYSTEM_PROMPT = (
    "Você é um assistente comercial da Automa Soluct no WhatsApp. "
    "Converse de forma natural, educada e consultiva. "
    "Ajude o lead a entender como automações e integrações podem reduzir trabalho manual. "
    "Não prometa resultados garantidos e não invente informações."
)
SYSTEM_GUARDRAILS = (
    "Responda sempre em português do Brasil, de forma curta e natural para WhatsApp. "
    "Use no máximo 3 frases."
)
SALES_CONVERSATION_STRATEGY = (
    "Condução comercial:\n"
    "- Ao longo da conversa, entenda a dor, necessidade ou objetivo do lead antes de sugerir o próximo passo.\n"
    "- Mostre de forma objetiva como a expertise descrita em Sobre a empresa/serviços pode resolver essa dor.\n"
    "- Proponha ativamente uma reunião quando houver contexto suficiente; não espere passivamente o lead pedir.\n"
    "- Nunca trate de valores, preços, descontos, parcelas, formas de pagamento ou negociação comercial no WhatsApp. "
    "Quando isso aparecer, diga que os detalhes de investimento são tratados na reunião.\n"
    "- Se o lead demonstrar interesse real em marcar reunião, por exemplo dizendo \"sim\", \"pode ser\", "
    "\"vamos marcar\" ou equivalente, chame update_lead_stage com stage converted e responda confirmando que alguém "
    "vai entrar em contato para agendar. Não tente escolher data ou horário sozinho.\n"
    "- Se o lead demonstrar desinteresse claro, chame update_lead_stage com stage not_interested e responda de forma "
    "educada, breve e sem insistir."
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

    settings = WhatsAppAiSettings(
        id=1,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        services_description="",
        enabled=False,
        auto_apply_tags_enabled=False,
    )
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
    logger.info(
        "Processando IA WhatsApp: message_id=%s conversation_id=%s enabled=%s",
        inbound_message.id,
        conversation.id,
        ai_settings.enabled,
    )
    if not ai_settings.enabled:
        logger.info("IA WhatsApp desativada: message_id=%s conversation_id=%s", inbound_message.id, conversation.id)
        return {"status": "disabled"}

    if _has_recent_ai_reply(db, conversation.id) or _has_recent_unidentified_ai_reply(db, conversation):
        logger.info(
            "IA WhatsApp pulada pelo circuit breaker: message_id=%s conversation_id=%s sender_phone=%s",
            inbound_message.id,
            conversation.id,
            sender_phone,
        )
        return {"status": "skipped_recent_reply"}

    try:
        ai_response = generate_ai_response(db, conversation, ai_settings)
        logger.info(
            "Resposta OpenAI processada: message_id=%s conversation_id=%s text_len=%s tool_calls=%s",
            inbound_message.id,
            conversation.id,
            len(ai_response.text or ""),
            len(ai_response.tool_calls),
        )
        _apply_tool_calls(db, conversation, ai_response.tool_calls, ai_settings=ai_settings)
        response_text = ai_response.text.strip()
        if not response_text:
            logger.warning(
                "IA WhatsApp retornou resposta vazia: message_id=%s conversation_id=%s tool_calls=%s",
                inbound_message.id,
                conversation.id,
                len(ai_response.tool_calls),
            )
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
        logger.info(
            "Resposta automática WhatsApp enviada: message_id=%s conversation_id=%s outbound_id=%s",
            inbound_message.id,
            conversation.id,
            outbound_message.id,
        )
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

    payload = _post_openai_response(_openai_payload(db, conversation, ai_settings, include_tools=True))
    text = _extract_output_text(payload)
    tool_calls = _extract_tool_calls(payload)
    if not text and tool_calls:
        logger.warning(
            "OpenAI retornou apenas function_call para conversa %s; solicitando resposta final sem ferramentas.",
            conversation.id,
        )
        final_payload = _post_openai_response(_openai_payload(db, conversation, ai_settings, include_tools=False))
        text = _extract_output_text(final_payload)

    return AiResponse(text=text, tool_calls=tool_calls)


def _post_openai_response(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI retornou erro {response.status_code}: {response.text[:600]}")

    return response.json()


def _openai_payload(
    db: Session,
    conversation: WhatsAppConversation,
    ai_settings: WhatsAppAiSettings,
    *,
    include_tools: bool,
) -> dict[str, Any]:
    settings = get_settings()
    system_prompt = (ai_settings.system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    services_context = _services_context(ai_settings.services_description)
    portfolio_context = _portfolio_context(db)
    lead_context = _lead_context(conversation.lead)
    history = _conversation_history(db, conversation.id)
    available_tags, tags_truncated = _available_ai_tags_for_prompt(db) if include_tools and ai_settings.auto_apply_tags_enabled else ([], False)
    tag_context = _ai_tag_context(available_tags, tags_truncated)
    tool_instruction = _tool_instruction(include_tools, has_tag_tool=bool(available_tags))

    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n{SYSTEM_GUARDRAILS}\n\n{SALES_CONVERSATION_STRATEGY}\n\n"
                    f"{services_context}\n\n{portfolio_context}\n\n{tag_context}{tool_instruction}\n\n"
                    f"Contexto do lead:\n{lead_context}"
                ),
            },
            *history,
        ],
        "max_output_tokens": 450,
    }
    if include_tools:
        tools = [_update_lead_stage_tool_schema()]
        if available_tags:
            tools.append(_apply_lead_tags_tool_schema(available_tags))
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


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
        f"Insights do site: {lead.site_insights or '-'}",
        f"Nicho: {lead.niche or '-'}",
        f"Localidade: {lead.location or '-'}",
    ]
    return "\n".join(parts)


def _services_context(services_description: str | None) -> str:
    description = str(services_description or "").strip()
    if not description:
        return (
            "Sobre a empresa/serviços: não há descrição adicional cadastrada. "
            "Nunca negocie, prometa ou confirme valores; quando o assunto for preço, diga que os detalhes de investimento são tratados na reunião."
        )

    return (
        f"Sobre a empresa/serviços:\n{description}\n\n"
        "Use essas informações para contextualizar a conversa. "
        "Nunca negocie, prometa ou confirme valores; quando o assunto for preço, diga que os detalhes de investimento são tratados na reunião."
    )


def _portfolio_context(db: Session) -> str:
    items = list(db.scalars(select(WhatsAppPortfolioItem).order_by(desc(WhatsAppPortfolioItem.created_at)).limit(10)).all())
    if not items:
        return "Portfólio: nenhum item cadastrado. Não invente cases, links ou exemplos de portfólio."

    portfolio_lines = "\n".join(f"- {item.description}: {item.url}" for item in items)
    return (
        "Portfólio disponível:\n"
        f"{portfolio_lines}\n\n"
        "Durante conversas de qualificação, você pode mencionar no máximo 1 item de portfólio relevante, "
        "somente se fizer sentido pelo assunto tratado. Não force portfólio em toda resposta. "
        "Nunca mencione portfólio no disparo inicial de campanha e não invente cases ou links."
    )


def _tool_instruction(include_tools: bool, *, has_tag_tool: bool) -> str:
    if not include_tools:
        return "Nesta chamada, não use ferramentas. Escreva apenas a resposta final que será enviada ao usuário."

    instruction = (
        "Se identificar interesse, desinteresse ou avanço no funil, chame a function update_lead_stage. "
        "Mesmo quando chamar uma function, também escreva a resposta que deve ser enviada ao usuário."
    )
    if has_tag_tool:
        instruction += (
            " Se a conversa trouxer evidência concreta de uma classificação disponível, chame apply_lead_tags "
            "usando somente os nomes listados em Tags disponíveis. Não crie tags, não chute categorias e não aplique "
            "tags por inferência fraca."
        )
    return instruction


def _available_ai_tags_for_prompt(db: Session) -> tuple[list[Tag], bool]:
    tags = list(
        db.scalars(
            select(Tag)
            .order_by(func.lower(Tag.name), Tag.id)
            .limit(AI_TAG_PROMPT_LIMIT + 1)
        ).all()
    )
    return tags[:AI_TAG_PROMPT_LIMIT], len(tags) > AI_TAG_PROMPT_LIMIT


def _ai_tag_context(tags: list[Tag], truncated: bool) -> str:
    if not tags:
        return ""

    tag_lines = []
    for tag in tags:
        description = (tag.description or "").strip()
        tag_lines.append(f"- {tag.name}: {description}" if description else f"- {tag.name}")
    tag_lines_text = "\n".join(tag_lines)

    suffix = (
        f"\nHá mais tags cadastradas, mas apenas as primeiras {AI_TAG_PROMPT_LIMIT} por ordem alfabética "
        "foram disponibilizadas nesta conversa; use somente as listadas abaixo."
        if truncated
        else ""
    )
    return (
        "Tags disponíveis para classificação automática:\n"
        f"{tag_lines_text}"
        f"{suffix}\n\n"
    )


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


def _apply_lead_tags_tool_schema(tags: list[Tag]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": "apply_lead_tags",
        "description": (
            "Aplica tags já existentes ao lead quando a conversa trouxer evidência concreta. "
            "Não cria tags novas."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tags"],
            "properties": {
                "tags": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {
                        "type": "string",
                        "enum": [tag.name for tag in tags],
                    },
                    "description": "Nomes exatos das tags disponíveis que devem ser aplicadas.",
                },
                "reason": {
                    "type": "string",
                    "description": "Evidência curta na conversa que justifica as tags.",
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
        if item.get("type") == "function_call" and item.get("name") in AI_TOOL_NAMES:
            calls.append(item)
        for tool_call in item.get("tool_calls", []) if isinstance(item.get("tool_calls"), list) else []:
            if isinstance(tool_call, dict) and tool_call.get("name") in AI_TOOL_NAMES:
                calls.append(tool_call)
    return calls


def _apply_tool_calls(
    db: Session,
    conversation: WhatsAppConversation,
    tool_calls: list[dict[str, Any]],
    *,
    ai_settings: WhatsAppAiSettings | None = None,
) -> None:
    if not tool_calls:
        return
    if not conversation.lead_id:
        logger.warning("IA solicitou ferramenta, mas conversa %s não possui lead vinculado.", conversation.id)
        return

    settings = ai_settings or get_or_create_ai_settings(db)
    for tool_call in tool_calls:
        tool_name = _tool_name(tool_call)
        arguments = _tool_arguments(tool_call)
        if tool_name == "update_lead_stage":
            _apply_update_lead_stage_tool(db, conversation, arguments)
            continue
        if tool_name == "apply_lead_tags":
            if not settings.auto_apply_tags_enabled:
                logger.warning("IA solicitou tags, mas aplicação automática está desativada para conversa %s.", conversation.id)
                continue
            _apply_lead_tags_tool(db, conversation, arguments)
            continue
        logger.warning("IA solicitou ferramenta desconhecida para conversa %s: %s", conversation.id, tool_name)


def _apply_update_lead_stage_tool(db: Session, conversation: WhatsAppConversation, arguments: dict[str, Any]) -> None:
    stage = str(arguments.get("stage") or "").strip()
    reason = str(arguments.get("reason") or "").strip()
    if stage not in CRM_STAGES:
        logger.warning("IA solicitou estágio de CRM inválido para conversa %s: %s", conversation.id, stage)
        return
    update_crm_stage(db, conversation.lead_id, stage, changed_by="ai", reason=reason)


def _apply_lead_tags_tool(db: Session, conversation: WhatsAppConversation, arguments: dict[str, Any]) -> None:
    tag_names = _requested_tag_names(arguments)
    if not tag_names:
        return

    try:
        _apply_lead_tags(db, conversation.lead_id, tag_names)
    except Exception:
        logger.exception("Falha ao aplicar tags por IA para lead %s na conversa %s.", conversation.lead_id, conversation.id)


def _requested_tag_names(arguments: dict[str, Any]) -> list[str]:
    raw_tags = arguments.get("tags") or arguments.get("tag_names") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    if not isinstance(raw_tags, list):
        return []

    tag_names: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        name = str(item or "").strip()
        normalized = _normalize_tag_name(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        tag_names.append(name)
    return tag_names


def _apply_lead_tags(db: Session, lead_id: int, tag_names: list[str]) -> None:
    available_tags, _ = _available_ai_tags_for_prompt(db)
    tags_by_normalized_name = {_normalize_tag_name(tag.name): tag for tag in available_tags}
    requested_tags: list[Tag] = []
    seen_tag_ids: set[int] = set()

    for tag_name in tag_names:
        tag = tags_by_normalized_name.get(_normalize_tag_name(tag_name))
        if not tag:
            logger.warning("IA solicitou tag inexistente ou indisponível para lead %s: %s", lead_id, tag_name)
            continue
        if tag.id in seen_tag_ids:
            continue
        seen_tag_ids.add(tag.id)
        requested_tags.append(tag)

    if not requested_tags:
        return

    existing_tag_ids = set(
        db.scalars(
            select(LeadTag.tag_id).where(
                LeadTag.lead_id == lead_id,
                LeadTag.tag_id.in_([tag.id for tag in requested_tags]),
            )
        ).all()
    )
    for tag in requested_tags:
        if tag.id in existing_tag_ids:
            continue
        db.add(LeadTag(lead_id=lead_id, tag_id=tag.id, origin="ai"))
    db.flush()


def _normalize_tag_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_only = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(ascii_only.split())


def _tool_name(tool_call: dict[str, Any]) -> str:
    function_payload = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    return str(tool_call.get("name") or function_payload.get("name") or "").strip()


def _tool_arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
    function_payload = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    raw_arguments = tool_call.get("arguments") or function_payload.get("arguments") or {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str) and raw_arguments.strip():
        try:
            data = json.loads(raw_arguments)
        except json.JSONDecodeError:
            logger.warning("OpenAI retornou argumentos inválidos para ferramenta de IA: %s", raw_arguments[:300])
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


def _has_recent_unidentified_ai_reply(db: Session, conversation: WhatsAppConversation) -> bool:
    if conversation.lead_id:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=RECENT_AI_REPLY_SECONDS)
    return bool(
        db.scalar(
            select(WhatsAppMessage.id)
            .join(WhatsAppConversation, WhatsAppConversation.id == WhatsAppMessage.conversation_id)
            .where(
                WhatsAppConversation.instance_id == conversation.instance_id,
                WhatsAppConversation.lead_id.is_(None),
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
