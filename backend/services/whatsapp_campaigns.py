import json
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dt_time, timedelta, timezone
from threading import Lock, Thread
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import (
    Lead,
    LeadList,
    WhatsAppAiSettings,
    WhatsAppCampaign,
    WhatsAppCampaignTemplate,
    WhatsAppInstance,
    WhatsAppMessageTemplate,
    WhatsAppSend,
)
from backend.services.lead_lists import LIST_CHANNEL_WHATSAPP
from backend.services.lead_lists import lead_query_for_list as _lead_query_for_list
from backend.services.whatsapp_providers.evolution import EvolutionProvider
from backend.services.whatsapp_validation import normalize_phone_e164


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
campaign_executor = ThreadPoolExecutor(max_workers=1)
_active_campaign_ids: set[int] = set()
_active_campaign_ids_lock = Lock()
_scheduler_started = False
_scheduler_lock = Lock()
VARIABLE_PATTERN = re.compile(r"{\s*([a-zA-Z0-9_]+)\s*}")
SUCCESS_STATUSES = ("sent", "delivered", "read")
MESSAGE_MODE_TEMPLATE = "template"
MESSAGE_MODE_AI_PER_LEAD = "ai_per_lead"
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def submit_campaign_job(campaign_id: int) -> bool:
    with _active_campaign_ids_lock:
        if campaign_id in _active_campaign_ids:
            return False

        _active_campaign_ids.add(campaign_id)

    campaign_executor.submit(_run_campaign_and_release, campaign_id)
    return True


def _run_campaign_and_release(campaign_id: int) -> None:
    try:
        run_campaign(campaign_id)
    finally:
        with _active_campaign_ids_lock:
            _active_campaign_ids.discard(campaign_id)


def resume_running_campaigns() -> None:
    db = SessionLocal()
    try:
        campaign_ids = list(
            db.scalars(select(WhatsAppCampaign.id).where(WhatsAppCampaign.status == "running")).all()
        )
    finally:
        db.close()

    for campaign_id in campaign_ids:
        submit_campaign_job(campaign_id)


def start_campaign_scheduler(interval_seconds: int = 60) -> None:
    global _scheduler_started

    with _scheduler_lock:
        if _scheduler_started:
            return

        _scheduler_started = True

    thread = Thread(target=_campaign_scheduler_loop, args=(interval_seconds,), daemon=True)
    thread.start()


def _campaign_scheduler_loop(interval_seconds: int) -> None:
    while True:
        try:
            resume_running_campaigns()
        except Exception:
            pass

        time.sleep(interval_seconds)


def lead_query_for_list(lead_list: LeadList):
    return _lead_query_for_list(lead_list, LIST_CHANNEL_WHATSAPP)


def render_message(template: WhatsAppMessageTemplate, lead: Lead) -> str:
    variables = {
        "lead_name": lead.name,
        "nome_empresa": lead.name,
        "company_name": lead.name,
        "empresa": lead.name,
        "name": lead.name,
        "email": lead.email or "",
        "website": lead.website or "",
        "phone": lead.phone or "",
        "address": lead.address or "",
        "niche": lead.niche,
        "location": lead.location,
        "localidade": lead.location,
    }

    def replace(match: re.Match[str]) -> str:
        return variables.get(match.group(1), "")

    return VARIABLE_PATTERN.sub(replace, template.content or "")


def _ai_per_lead_json_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["content"],
        "properties": {
            "content": {"type": "string"},
        },
    }


def _extract_output_text(response_payload: dict) -> str:
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


def _services_description_for_campaign(db: Session) -> str:
    ai_settings = db.get(WhatsAppAiSettings, 1)
    return (ai_settings.services_description or "").strip() if ai_settings else ""


def _lead_detail(value: str | None) -> str:
    return str(value or "").strip() or "-"


def _ai_per_lead_prompt(campaign: WhatsAppCampaign, lead: Lead, services_description: str) -> str:
    return f"""
Gere uma mensagem individual de abordagem inicial para WhatsApp.

Objetivo da campanha:
{campaign.objective or "-"}

Sobre meus serviços:
{services_description or "-"}

Dados do lead:
- Empresa: {_lead_detail(lead.name)}
- Nicho: {_lead_detail(lead.niche)}
- Localidade: {_lead_detail(lead.location)}
- Site: {_lead_detail(lead.website)}
- Telefone: {_lead_detail(lead.phone)}
- Insights do site/negócio: {_lead_detail(lead.site_insights)}

Regras:
- Responda em português do Brasil.
- Gere o texto final da mensagem; não use variáveis de template.
- Comece com uma saudação breve e natural, como "Oi, tudo bem?", sem chamar a pessoa pelo nome da empresa.
- Use no máximo 4 frases curtas.
- Mencione algo específico do lead. Se houver insights do site/negócio, use um detalhe concreto desses insights.
- Se os insights estiverem vazios, use apenas empresa, nicho, localização ou site; não invente dores, problemas, tecnologias, nome de pessoa ou dados do site.
- Preserve o gancho específico do objetivo. Se mencionar desenvolvimento gratuito, condição especial ou "paga só se gostar", transforme isso em uma frase natural, como "desenvolvimento sem custo inicial" e "só segue se gostar/fizer sentido".
- Não negocie valores, preço fechado, contrato ou detalhes de pagamento na primeira mensagem.
- Não use frases robóticas ou comerciais demais, como "oferta imperdível", "garanta agora" ou "posso criar uma prévia sem compromisso".
- Não prometa resultado garantido.
- Não mencione scraping, automação de disparo, base de leads ou Google Maps.
- Não use markdown, título, assunto, assinatura longa, listas ou JSON no conteúdo.
- Retorne somente JSON compatível com o schema.
"""


def generate_ai_message_for_lead(db: Session, campaign: WhatsAppCampaign, lead: Lead) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY não está configurada no backend.")

    services_description = _services_description_for_campaign(db)
    request_payload = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": (
                    "Você escreve mensagens B2B curtas e individuais para WhatsApp em JSON estruturado. "
                    "A mensagem deve soar humana, pesquisada e respeitosa, usando dados reais do lead sem inventar."
                ),
            },
            {"role": "user", "content": _ai_per_lead_prompt(campaign, lead, services_description)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "whatsapp_campaign_message_generation",
                "strict": True,
                "schema": _ai_per_lead_json_schema(),
            }
        },
        "max_output_tokens": 350,
    }

    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json=request_payload,
        timeout=60,
    )
    if response.status_code >= 400:
        detail = response.text[:600]
        raise RuntimeError(f"OpenAI retornou erro {response.status_code}: {detail}")

    output_text = _extract_output_text(response.json())
    if not output_text:
        raise RuntimeError("A OpenAI não retornou conteúdo para o lead.")

    try:
        generated = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("A OpenAI retornou um JSON inválido para o lead.") from exc

    content = str(generated.get("content") or "").strip().strip('"')
    if not content:
        raise RuntimeError("A OpenAI retornou uma mensagem vazia para o lead.")
    return content


def _choose_template(campaign: WhatsAppCampaign) -> WhatsAppCampaignTemplate:
    choices = campaign.templates
    weights = [max(1, item.weight) for item in choices]
    return random.choices(choices, weights=weights, k=1)[0]


def _recipient_phone(lead: Lead) -> str:
    normalized = normalize_phone_e164(lead.phone or "", f"{lead.address or ''} {lead.location}")
    return normalized.lstrip("+") if normalized else ""


def ensure_campaign_queue(db: Session, campaign: WhatsAppCampaign) -> None:
    existing_count = db.scalar(select(func.count(WhatsAppSend.id)).where(WhatsAppSend.campaign_id == campaign.id)) or 0
    if existing_count:
        return

    lead_list = db.get(LeadList, campaign.list_id)
    if not lead_list:
        campaign.status = "paused"
        campaign.error = "Lista não encontrada."
        campaign.message = "Campanha pausada."
        db.commit()
        return

    if campaign.message_mode == MESSAGE_MODE_TEMPLATE and not campaign.templates:
        campaign.status = "paused"
        campaign.error = "Template de mensagem não configurado."
        campaign.message = "Campanha pausada."
        db.commit()
        return

    queued = 0
    leads = list(db.scalars(lead_query_for_list(lead_list)).all())
    for lead in leads:
        recipient_phone = _recipient_phone(lead)
        if not recipient_phone:
            continue

        campaign_template = _choose_template(campaign) if campaign.message_mode == MESSAGE_MODE_TEMPLATE else None
        db.add(
            WhatsAppSend(
                campaign_id=campaign.id,
                lead_id=lead.id,
                template_id=campaign_template.template_id if campaign_template else None,
                recipient_phone=recipient_phone,
                status="pending",
            )
        )
        queued += 1

    campaign.pending_count = queued
    campaign.message = f"{queued} leads na fila."
    db.commit()


def refresh_campaign_counts(db: Session, campaign: WhatsAppCampaign) -> None:
    campaign.pending_count = db.scalar(
        select(func.count(WhatsAppSend.id)).where(
            WhatsAppSend.campaign_id == campaign.id,
            WhatsAppSend.status == "pending",
        )
    ) or 0
    campaign.sent_count = db.scalar(
        select(func.count(WhatsAppSend.id)).where(
            WhatsAppSend.campaign_id == campaign.id,
            WhatsAppSend.status == "sent",
        )
    ) or 0
    campaign.delivered_count = db.scalar(
        select(func.count(WhatsAppSend.id)).where(
            WhatsAppSend.campaign_id == campaign.id,
            WhatsAppSend.status == "delivered",
        )
    ) or 0
    campaign.read_count = db.scalar(
        select(func.count(WhatsAppSend.id)).where(
            WhatsAppSend.campaign_id == campaign.id,
            WhatsAppSend.status == "read",
        )
    ) or 0
    campaign.failed_count = db.scalar(
        select(func.count(WhatsAppSend.id)).where(
            WhatsAppSend.campaign_id == campaign.id,
            WhatsAppSend.status == "failed",
        )
    ) or 0


def _parse_time(value: str) -> dt_time:
    try:
        hour, minute = value.split(":", 1)
        return dt_time(int(hour), int(minute))
    except (TypeError, ValueError):
        return dt_time(9, 0)


def _campaign_timezone(campaign: WhatsAppCampaign) -> ZoneInfo:
    try:
        return ZoneInfo(campaign.timezone_name or "America/New_York")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")


def _allowed_send_days(campaign: WhatsAppCampaign) -> set[int]:
    return {int(day) for day in campaign.send_days.split(",") if day.strip().isdigit()}


def _inside_send_window(campaign: WhatsAppCampaign) -> bool:
    campaign_timezone = _campaign_timezone(campaign)
    now = datetime.now(campaign_timezone)
    allowed_days = _allowed_send_days(campaign)
    if allowed_days and now.weekday() not in allowed_days:
        return False

    start = _parse_time(campaign.send_window_start)
    end = _parse_time(campaign.send_window_end)
    return start <= now.time() <= end


def _next_send_window_start(campaign: WhatsAppCampaign, earliest: datetime | None = None) -> datetime | None:
    campaign_timezone = _campaign_timezone(campaign)
    now = earliest.astimezone(campaign_timezone) if earliest else datetime.now(campaign_timezone)
    allowed_days = _allowed_send_days(campaign)
    start = _parse_time(campaign.send_window_start)
    end = _parse_time(campaign.send_window_end)

    for offset in range(14):
        candidate_date = (now + timedelta(days=offset)).date()
        if allowed_days and candidate_date.weekday() not in allowed_days:
            continue

        candidate_start = datetime.combine(candidate_date, start, tzinfo=campaign_timezone)
        candidate_end = datetime.combine(candidate_date, end, tzinfo=campaign_timezone)
        if candidate_end < now:
            continue

        if candidate_start <= now <= candidate_end:
            return now

        return candidate_start

    return None


def _format_wait_until(value: datetime | None, campaign: WhatsAppCampaign) -> str:
    if value is None:
        return ""

    local_value = value.astimezone(_campaign_timezone(campaign))
    return f" Retoma em {local_value.strftime('%d/%m %H:%M')} ({campaign.timezone_name})."


def _wait_for_next_window(db: Session, campaign: WhatsAppCampaign, reason: str, next_time: datetime | None) -> None:
    campaign.message = f"Aguardando: {reason}.{_format_wait_until(next_time, campaign)}"
    campaign.error = None
    db.commit()


def _limit_status(db: Session, campaign: WhatsAppCampaign) -> tuple[str, datetime | None]:
    campaign_timezone = _campaign_timezone(campaign)
    now = datetime.now(campaign_timezone)
    daily_since = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    weekly_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    weekly_since = weekly_start.astimezone(timezone.utc)
    daily_sent = db.scalar(
        select(func.count(WhatsAppSend.id)).where(
            WhatsAppSend.campaign_id == campaign.id,
            WhatsAppSend.status.in_(SUCCESS_STATUSES),
            WhatsAppSend.sent_at >= daily_since,
        )
    ) or 0
    weekly_sent = db.scalar(
        select(func.count(WhatsAppSend.id)).where(
            WhatsAppSend.campaign_id == campaign.id,
            WhatsAppSend.status.in_(SUCCESS_STATUSES),
            WhatsAppSend.sent_at >= weekly_since,
        )
    ) or 0

    if daily_sent >= campaign.daily_limit:
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return "limite diário atingido", _next_send_window_start(campaign, tomorrow)
    if weekly_sent >= campaign.weekly_limit:
        next_week = (weekly_start + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return "limite semanal atingido", _next_send_window_start(campaign, next_week)
    return "", None


def _sleep_with_pause_checks(db: Session, campaign_id: int, seconds: int) -> None:
    for _ in range(seconds):
        campaign = db.get(WhatsAppCampaign, campaign_id)
        if not campaign or campaign.status != "running":
            return
        time.sleep(1)


def _provider_message_id(response: dict) -> str:
    key = response.get("key") if isinstance(response.get("key"), dict) else {}
    message = response.get("message") if isinstance(response.get("message"), dict) else {}
    value = key.get("id") or response.get("messageId") or response.get("id") or message.get("id")
    return str(value or "")


def _instance_provider_id(instance: WhatsAppInstance | None) -> str:
    if not instance:
        return ""
    return (instance.evolution_instance_name or instance.name or "").strip()


def _message_text_for_send(db: Session, campaign: WhatsAppCampaign, send: WhatsAppSend) -> str:
    if not send.lead:
        raise RuntimeError("Lead não encontrado para este envio.")

    if campaign.message_mode == MESSAGE_MODE_AI_PER_LEAD:
        generated_text = generate_ai_message_for_lead(db, campaign, send.lead)
        send.generated_content = generated_text
        return generated_text

    if not send.template:
        raise RuntimeError("Template de mensagem não encontrado para este envio.")
    return render_message(send.template, send.lead)


def run_campaign(campaign_id: int) -> None:
    db = SessionLocal()

    try:
        campaign = db.get(WhatsAppCampaign, campaign_id)
        if not campaign or campaign.status != "running":
            return

        campaign.started_at = campaign.started_at or _now()
        campaign.message = "Preparando fila de envio..."
        db.commit()
        ensure_campaign_queue(db, campaign)

        while True:
            campaign = db.get(WhatsAppCampaign, campaign_id)
            if not campaign or campaign.status != "running":
                return

            refresh_campaign_counts(db, campaign)
            if campaign.pending_count <= 0:
                campaign.status = "completed"
                campaign.finished_at = _now()
                campaign.message = "Campanha concluída."
                db.commit()
                return

            if not _inside_send_window(campaign):
                _wait_for_next_window(
                    db,
                    campaign,
                    "fora da janela de envio",
                    _next_send_window_start(campaign),
                )
                return

            limit_message, next_send_time = _limit_status(db, campaign)
            if limit_message:
                _wait_for_next_window(db, campaign, limit_message, next_send_time)
                return

            instance = db.get(WhatsAppInstance, campaign.instance_id)
            provider_instance_id = _instance_provider_id(instance)
            if not provider_instance_id:
                campaign.status = "paused"
                campaign.error = "Instância de WhatsApp não configurada."
                campaign.message = "Campanha pausada."
                db.commit()
                return

            send = db.scalars(
                select(WhatsAppSend)
                .options(
                    selectinload(WhatsAppSend.lead).selectinload(Lead.search_run),
                    selectinload(WhatsAppSend.template),
                )
                .where(WhatsAppSend.campaign_id == campaign.id, WhatsAppSend.status == "pending")
                .order_by(WhatsAppSend.created_at)
                .limit(1)
            ).first()

            if not send:
                refresh_campaign_counts(db, campaign)
                db.commit()
                continue

            try:
                rendered_text = _message_text_for_send(db, campaign, send)
                response = EvolutionProvider().send_text_message(
                    provider_instance_id,
                    send.recipient_phone,
                    rendered_text,
                )
                send.status = "sent"
                send.sent_at = _now()
                send.provider_message_id = _provider_message_id(response)
                send.error = None
                campaign.message = f"Enviado para {send.recipient_phone}."
            except Exception as exc:
                logger.exception("Falha no envio WhatsApp da campanha %s para o lead %s", campaign.id, send.lead_id)
                send.status = "failed"
                send.failed_at = _now()
                send.error = str(exc)
                campaign.message = f"Falha ao enviar para {send.recipient_phone}."

            refresh_campaign_counts(db, campaign)
            db.commit()

            delay = random.randint(campaign.min_delay_seconds, campaign.max_delay_seconds)
            _sleep_with_pause_checks(db, campaign.id, delay)
    finally:
        db.close()
