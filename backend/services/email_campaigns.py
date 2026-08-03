import html
import json
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dt_time, timedelta, timezone
from threading import Lock, Thread
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import (
    EmailCampaign,
    EmailCampaignTemplate,
    EmailSend,
    EmailTemplate,
    Lead,
    LeadEmailPreference,
    LeadList,
    SearchRun,
)
from backend.services.content_preview import fetch_content_preview
from backend.services.email_delivery import get_smtp_config, send_email


logger = logging.getLogger(__name__)
campaign_executor = ThreadPoolExecutor(max_workers=1)
_active_campaign_ids: set[int] = set()
_active_campaign_ids_lock = Lock()
_scheduler_started = False
_scheduler_lock = Lock()
VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
YOUTUBE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{6,}$")
LIST_FILTER_SEPARATOR = "||"
MESSAGE_MODE_AI_PER_LEAD = "ai_per_lead"
MESSAGE_MODE_TEMPLATE = "template"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _split_list_filter(value: str) -> list[str]:
    if not value:
        return []

    if LIST_FILTER_SEPARATOR in value:
        return [item.strip() for item in value.split(LIST_FILTER_SEPARATOR) if item.strip()]

    return [value.strip()] if value.strip() else []


def _opened_email_leads_stmt():
    return select(EmailSend.lead_id).where(or_(EmailSend.open_count > 0, EmailSend.opened_at.is_not(None)))


def _clicked_email_leads_stmt():
    return select(EmailSend.lead_id).where(or_(EmailSend.click_count > 0, EmailSend.clicked_at.is_not(None)))


def _apply_email_engagement_filter(stmt, lead_list: LeadList):
    if not lead_list.only_email_opened and not lead_list.only_email_clicked:
        return stmt

    opened_stmt = _opened_email_leads_stmt()
    clicked_stmt = _clicked_email_leads_stmt()

    if lead_list.only_email_opened and lead_list.only_email_clicked:
        if lead_list.email_engagement_filter_mode == "and":
            return stmt.where(Lead.id.in_(opened_stmt), Lead.id.in_(clicked_stmt))
        return stmt.where(or_(Lead.id.in_(opened_stmt), Lead.id.in_(clicked_stmt)))

    if lead_list.only_email_opened:
        return stmt.where(Lead.id.in_(opened_stmt))

    return stmt.where(Lead.id.in_(clicked_stmt))


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
            db.scalars(select(EmailCampaign.id).where(EmailCampaign.status == "running")).all()
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
    stmt = (
        select(Lead)
        .join(SearchRun)
        .options(selectinload(Lead.search_run))
        .where(Lead.email != "")
        .order_by(Lead.created_at)
    )

    niche_filters = _split_list_filter(lead_list.niche_filter)
    if niche_filters:
        stmt = stmt.where(or_(*(SearchRun.niche.ilike(f"%{value}%") for value in niche_filters)))

    location_filters = _split_list_filter(lead_list.location_filter)
    if location_filters:
        stmt = stmt.where(or_(*(SearchRun.location.ilike(f"%{value}%") for value in location_filters)))

    if lead_list.search_run_id:
        stmt = stmt.where(Lead.run_id == lead_list.search_run_id)

    if lead_list.only_whatsapp_validated:
        stmt = stmt.where(Lead.whatsapp_validated.is_(True))

    stmt = _apply_email_engagement_filter(stmt, lead_list)

    blocked_stmt = select(LeadEmailPreference.lead_id).where(LeadEmailPreference.do_not_contact.is_(True))
    stmt = stmt.where(~Lead.id.in_(blocked_stmt))

    if lead_list.only_never_emailed:
        sent_stmt = select(EmailSend.lead_id).where(EmailSend.status == "sent")
        stmt = stmt.where(~Lead.id.in_(sent_stmt))

    if lead_list.never_received_template_id:
        template_sent_stmt = select(EmailSend.lead_id).where(
            EmailSend.template_id == lead_list.never_received_template_id,
            EmailSend.status.in_(("pending", "sent")),
        )
        stmt = stmt.where(~Lead.id.in_(template_sent_stmt))

    return stmt


def count_leads_for_list(db: Session, lead_list: LeadList) -> int:
    leads = db.scalars(lead_query_for_list(lead_list)).all()
    return len(leads)


def _render(value: str, variables: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, "")

    return VARIABLE_PATTERN.sub(replace, value or "")


def _send_url(send_id: int, path: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}{path}/{send_id}"


def _youtube_video_id(url: str) -> str:
    if not url:
        return ""

    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.strip("/")

    if host == "youtu.be" and YOUTUBE_ID_PATTERN.match(path.split("/", 1)[0]):
        return path.split("/", 1)[0]

    if host in {"youtube.com", "m.youtube.com"}:
        query_video_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_video_id and YOUTUBE_ID_PATTERN.match(query_video_id):
            return query_video_id

        path_parts = path.split("/")
        if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts", "live"} and YOUTUBE_ID_PATTERN.match(path_parts[1]):
            return path_parts[1]

    return ""


def _youtube_thumbnail_url(url: str) -> str:
    video_id = _youtube_video_id(url)
    if not video_id:
        return ""
    return f"https://i.ytimg.com/vi/{video_id}/hq720.jpg"


def _content_thumbnail_url(url: str) -> str:
    youtube_thumbnail_url = _youtube_thumbnail_url(url)
    if youtube_thumbnail_url:
        return youtube_thumbnail_url

    try:
        return fetch_content_preview(url).image_url
    except Exception:
        return ""


def _mailto_link(contact_email: str, company_name: str) -> str:
    subject = quote("Automation and integration help")
    body = quote(
        f"Hi Cleiton,\n\nI saw your email about automation for {company_name or 'our company'} and would like to learn more.\n\n"
    )
    return f"mailto:{contact_email}?subject={subject}&body={body}"


def _content_card_block(content_link: str, thumbnail_url: str, content_title: str, primary_color: str) -> str:
    if not content_link:
        return ""

    safe_link = html.escape(content_link, quote=True)
    safe_title = html.escape(content_title or "Open the content")
    safe_primary_color = html.escape(primary_color or "#0a0a0a", quote=True)

    if thumbnail_url:
        safe_thumbnail = html.escape(thumbnail_url, quote=True)
        media = f"""
                      <img src="{safe_thumbnail}" alt="{safe_title}" width="520" style="display:block;width:100%;max-width:520px;height:auto;border-radius:8px;border:1px solid #eeeeee;" />
        """
    else:
        media = f"""
                      <span style="display:block;width:100%;max-width:520px;border:1px solid #eeeeee;border-radius:8px;padding:28px 24px;background-color:#f6f8f7;color:#222222;font-size:18px;line-height:1.45;font-weight:700;">{safe_title}</span>
        """

    return f"""
              <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px 0;">
                <tr>
                  <td align="center">
                    <a href="{safe_link}" target="_blank" rel="noopener noreferrer" style="display:block;text-decoration:none;color:inherit;">
{media}
                      <span style="display:inline-block;margin-top:12px;background-color:{safe_primary_color};color:#ffffff;border-radius:999px;padding:12px 18px;font-size:14px;font-weight:700;">Open the content</span>
                    </a>
                  </td>
                </tr>
              </table>
    """


def render_email(template: EmailTemplate, lead: Lead, campaign: EmailCampaign, send_id: int | None = None) -> tuple[str, str, str]:
    settings = get_settings()
    content_title = template.content_title
    raw_content_link = template.content_link
    tracked_content_link = _send_url(send_id, "/api/email/click") if send_id and raw_content_link else raw_content_link
    thumbnail_url = _content_thumbnail_url(raw_content_link)
    company_name = lead.name
    get_in_touch_link = _mailto_link(settings.contact_email, company_name)

    variables = {
        "lead_name": f"team at {company_name}" if company_name else "there",
        "company_name": company_name,
        "name": company_name,
        "email": lead.email,
        "website": lead.website or "",
        "phone": lead.phone,
        "address": lead.address,
        "niche": lead.niche,
        "location": lead.location,
        "localidade": lead.location,
        "content_title": content_title,
        "content_link": tracked_content_link,
        "raw_content_link": raw_content_link,
        "content_thumbnail_url": thumbnail_url,
        "contact_email": settings.contact_email,
        "get_in_touch_link": get_in_touch_link,
        "logo_url": template.logo_url,
        "primary_color": template.primary_color,
        "text_color": template.text_color,
        "background_color": template.background_color,
    }

    escaped_variables = {key: html.escape(value or "") for key, value in variables.items()}
    content_card = _content_card_block(tracked_content_link, thumbnail_url, content_title, template.primary_color)
    escaped_variables["content_video_block"] = content_card
    escaped_variables["content_card_block"] = content_card
    subject = _render(template.subject, variables)
    rendered_html = _render(template.html, escaped_variables)
    rendered_text = _render(template.text, variables)

    if send_id:
        pixel = f'<img src="{_send_url(send_id, "/api/email/open")}.png" width="1" height="1" alt="" style="display:none" />'
        rendered_html = f"{rendered_html}\n{pixel}"

    return subject, rendered_html, rendered_text


def _extract_output_text(response_payload: dict) -> str:
    if response_payload.get("output_text"):
        return str(response_payload["output_text"])

    chunks: list[str] = []
    for item in response_payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks)


def _ai_email_json_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["subject", "content_title", "paragraphs", "cta"],
        "properties": {
            "subject": {"type": "string"},
            "content_title": {"type": "string"},
            "paragraphs": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 4,
            },
            "cta": {"type": "string"},
        },
    }


def _ai_email_prompt(campaign: EmailCampaign, lead: Lead) -> str:
    site_insights = (lead.site_insights or "").strip() or "Não disponível."
    return f"""
Gere o conteúdo textual individual de um e-mail comercial B2B.

Objetivo da campanha:
{campaign.objective}

Dados reais do lead:
- Empresa: {lead.name}
- E-mail: {lead.email}
- Telefone: {lead.phone}
- Site: {lead.website or "Não informado"}
- Nicho: {lead.niche or "Não informado"}
- Localização: {lead.location or "Não informada"}
- Endereço: {lead.address or "Não informado"}
- Insights do site/negócio: {site_insights}

Regras:
- Responda em português do Brasil.
- Retorne somente JSON compatível com o schema.
- Gere subject, content_title, paragraphs e cta.
- Não gere HTML, markdown, assinatura ou placeholders.
- Não inclua saudação nos parágrafos; o layout do e-mail já adiciona uma saudação neutra.
- Escreva de forma natural, pesquisada e consultiva, sem soar como disparo em massa.
- Use no máximo 4 parágrafos curtos.
- Cite algo específico do lead quando houver dado real. Priorize site_insights quando disponível.
- Se site_insights estiver indisponível, use apenas empresa, nicho, localização, site ou endereço; não invente problemas, tecnologias, desempenho, nome de pessoa ou dados do site.
- Preserve o gancho específico do objetivo. Se o objetivo citar uma oferta ou condição especial, mencione isso de forma leve.
- Não negocie valores, preço fechado, contrato ou formas de pagamento.
- Não prometa resultado garantido.
- Não mencione scraping, automação de disparo, base de leads ou Google Maps.
"""


def _normalize_ai_email_content(generated: dict) -> dict[str, object]:
    subject = str(generated.get("subject") or "").strip().strip('"')
    content_title = str(generated.get("content_title") or "").strip().strip('"')
    raw_paragraphs = generated.get("paragraphs") or []
    paragraphs = [
        str(paragraph).strip()
        for paragraph in raw_paragraphs
        if str(paragraph or "").strip()
    ]
    cta = str(generated.get("cta") or "").strip().strip('"')

    if not subject or not content_title or not paragraphs or not cta:
        raise RuntimeError("A OpenAI retornou conteúdo incompleto para o e-mail do lead.")

    return {
        "subject": subject[:500],
        "content_title": content_title[:500],
        "paragraphs": paragraphs[:4],
        "cta": cta,
    }


def generate_ai_email_content_for_lead(campaign: EmailCampaign, lead: Lead) -> dict[str, object]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY não está configurada no backend.")

    request_payload = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": (
                    "Você escreve conteúdo textual individual para e-mails B2B em JSON estruturado. "
                    "Use somente dados reais do lead e mantenha tom humano, pesquisado e objetivo."
                ),
            },
            {"role": "user", "content": _ai_email_prompt(campaign, lead)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "email_campaign_message_generation",
                "strict": True,
                "schema": _ai_email_json_schema(),
            }
        },
        "max_output_tokens": 700,
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

    return _normalize_ai_email_content(generated)


def _serialize_generated_email_content(generated: dict[str, object]) -> str:
    return json.dumps(generated, ensure_ascii=False, separators=(",", ":"))


def render_generated_email(
    template: EmailTemplate,
    lead: Lead,
    campaign: EmailCampaign,
    generated: dict[str, object],
    send_id: int | None = None,
) -> tuple[str, str, str]:
    settings = get_settings()
    company_name = lead.name
    subject = str(generated["subject"])
    content_title = str(generated["content_title"])
    paragraphs = [str(paragraph) for paragraph in generated["paragraphs"]]
    cta = str(generated["cta"])
    get_in_touch_link = _mailto_link(settings.contact_email, company_name)

    safe_background = html.escape(template.background_color or "#f4f4f4", quote=True)
    safe_primary = html.escape(template.primary_color or "#0a0a0a", quote=True)
    safe_text = html.escape(template.text_color or "#333333", quote=True)
    safe_logo = html.escape(template.logo_url or "", quote=True)
    safe_title = html.escape(content_title)
    safe_cta = html.escape(cta)
    safe_get_in_touch = html.escape(get_in_touch_link, quote=True)
    safe_contact_email = html.escape(settings.contact_email)
    safe_company_name = html.escape(company_name or "")
    paragraph_html = "\n".join(
        f'              <p style="font-size:16px;color:{safe_text};line-height:1.7;margin:0 0 16px 0;">{html.escape(paragraph)}</p>'
        for paragraph in paragraphs
    )

    logo_block = (
        f'              <img src="{safe_logo}" alt="Automa Soluct" height="64" style="display:block;margin:0 auto;max-width:220px;" />'
        if safe_logo
        else '              <p style="color:#ffffff;font-size:22px;font-weight:700;margin:0;">Automa Soluct</p>'
    )
    rendered_html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background-color:{safe_background};font-family:Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:{safe_background};padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <tr>
            <td style="background-color:{safe_primary};padding:32px 40px;text-align:center;">
{logo_block}
              <p style="color:#d7d7d7;font-size:13px;margin:12px 0 0 0;">Automation & Integrations</p>
            </td>
          </tr>
          <tr>
            <td style="padding:40px 40px 24px 40px;">
              <p style="font-size:16px;color:{safe_text};margin:0 0 16px 0;">Oi, tudo bem?</p>
              <h1 style="font-size:24px;color:{safe_text};line-height:1.3;margin:0 0 20px 0;">{safe_title}</h1>
{paragraph_html}
              <p style="font-size:16px;color:{safe_text};line-height:1.7;margin:0 0 20px 0;">{safe_cta}</p>
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:10px 0 32px 0;">
                    <a href="{safe_get_in_touch}" style="background-color:{safe_primary};color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:6px;font-size:15px;font-weight:600;display:inline-block;">Responder</a>
                  </td>
                </tr>
              </table>
              <hr style="border:none;border-top:1px solid #eeeeee;margin:0 0 28px 0;" />
              <p style="font-size:13px;color:#888888;margin:0 0 12px 0;text-transform:uppercase;font-weight:600;">Contato</p>
              <p style="font-size:15px;color:{safe_text};line-height:1.7;margin:0;">
                Cleiton Carvalho<br />
                Automation Specialist - Automa Soluct<br />
                <a href="mailto:{safe_contact_email}" style="color:{safe_primary};text-decoration:none;">{safe_contact_email}</a>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 40px 40px 40px;border-top:1px solid #eeeeee;">
              <p style="margin:0;font-size:12px;color:#999999;line-height:1.6;">Este é um contato pontual da Automa Soluct para {safe_company_name}. Responda 'remover' se preferir não receber novas mensagens.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    if send_id:
        pixel = f'<img src="{_send_url(send_id, "/api/email/open")}.png" width="1" height="1" alt="" style="display:none" />'
        rendered_html = f"{rendered_html}\n{pixel}"

    rendered_text = "\n\n".join(
        [
            "Oi, tudo bem?",
            content_title,
            *paragraphs,
            cta,
            f"Responder: {settings.contact_email}",
            "Cleiton Carvalho",
            "Automa Soluct",
        ]
    )
    return subject, rendered_html, rendered_text


def _email_content_for_send(
    campaign: EmailCampaign,
    send: EmailSend,
) -> tuple[str, str, str]:
    if not send.template:
        raise RuntimeError("Template de e-mail não encontrado para este envio.")
    if not send.lead:
        raise RuntimeError("Lead não encontrado para este envio.")

    if campaign.message_mode == MESSAGE_MODE_AI_PER_LEAD:
        generated = generate_ai_email_content_for_lead(campaign, send.lead)
        send.generated_content = _serialize_generated_email_content(generated)
        return render_generated_email(send.template, send.lead, campaign, generated, send.id)

    send.generated_content = None
    return render_email(send.template, send.lead, campaign, send.id)


def _choose_template(campaign: EmailCampaign) -> EmailCampaignTemplate:
    choices = campaign.templates
    weights = [max(1, item.weight) for item in choices]
    return random.choices(choices, weights=weights, k=1)[0]


def ensure_campaign_queue(db: Session, campaign: EmailCampaign) -> None:
    existing_count = db.scalar(select(func.count(EmailSend.id)).where(EmailSend.campaign_id == campaign.id)) or 0
    if existing_count:
        return

    lead_list = db.get(LeadList, campaign.list_id)
    if not lead_list:
        campaign.status = "failed"
        campaign.error = "Lista não encontrada."
        db.commit()
        return

    leads = list(db.scalars(lead_query_for_list(lead_list)).all())
    for lead in leads:
        campaign_template = _choose_template(campaign)
        db.add(
            EmailSend(
                campaign_id=campaign.id,
                lead_id=lead.id,
                template_id=campaign_template.template_id,
                recipient_email=lead.email,
                status="pending",
            )
        )

    campaign.pending_count = len(leads)
    campaign.message = f"{len(leads)} leads na fila."
    db.commit()


def refresh_campaign_counts(db: Session, campaign: EmailCampaign) -> None:
    campaign.pending_count = db.scalar(
        select(func.count(EmailSend.id)).where(EmailSend.campaign_id == campaign.id, EmailSend.status == "pending")
    ) or 0
    campaign.sent_count = db.scalar(
        select(func.count(EmailSend.id)).where(EmailSend.campaign_id == campaign.id, EmailSend.status == "sent")
    ) or 0
    campaign.failed_count = db.scalar(
        select(func.count(EmailSend.id)).where(EmailSend.campaign_id == campaign.id, EmailSend.status == "failed")
    ) or 0


def _parse_time(value: str) -> dt_time:
    try:
        hour, minute = value.split(":", 1)
        return dt_time(int(hour), int(minute))
    except (TypeError, ValueError):
        return dt_time(9, 0)


def _campaign_timezone(campaign: EmailCampaign) -> ZoneInfo:
    try:
        return ZoneInfo(campaign.timezone_name or "America/New_York")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")


def _allowed_send_days(campaign: EmailCampaign) -> set[int]:
    return {int(day) for day in campaign.send_days.split(",") if day.strip().isdigit()}


def _inside_send_window(campaign: EmailCampaign) -> bool:
    campaign_timezone = _campaign_timezone(campaign)
    now = datetime.now(campaign_timezone)
    allowed_days = _allowed_send_days(campaign)
    if allowed_days and now.weekday() not in allowed_days:
        return False

    start = _parse_time(campaign.send_window_start)
    end = _parse_time(campaign.send_window_end)
    return start <= now.time() <= end


def _next_send_window_start(campaign: EmailCampaign, earliest: datetime | None = None) -> datetime | None:
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


def _format_wait_until(value: datetime | None, campaign: EmailCampaign) -> str:
    if value is None:
        return ""

    local_value = value.astimezone(_campaign_timezone(campaign))
    return f" Retoma em {local_value.strftime('%d/%m %H:%M')} ({campaign.timezone_name})."


def _wait_for_next_window(db: Session, campaign: EmailCampaign, reason: str, next_time: datetime | None) -> None:
    campaign.message = f"Aguardando: {reason}.{_format_wait_until(next_time, campaign)}"
    campaign.error = None
    db.commit()


def _limit_status(db: Session, campaign: EmailCampaign) -> tuple[str, datetime | None]:
    campaign_timezone = _campaign_timezone(campaign)
    now = datetime.now(campaign_timezone)
    daily_since = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    weekly_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    weekly_since = weekly_start.astimezone(timezone.utc)
    daily_sent = db.scalar(
        select(func.count(EmailSend.id)).where(
            EmailSend.campaign_id == campaign.id,
            EmailSend.status == "sent",
            EmailSend.sent_at >= daily_since,
        )
    ) or 0
    weekly_sent = db.scalar(
        select(func.count(EmailSend.id)).where(
            EmailSend.campaign_id == campaign.id,
            EmailSend.status == "sent",
            EmailSend.sent_at >= weekly_since,
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
        campaign = db.get(EmailCampaign, campaign_id)
        if not campaign or campaign.status != "running":
            return
        time.sleep(1)


def run_campaign(campaign_id: int) -> None:
    db = SessionLocal()

    try:
        campaign = db.get(EmailCampaign, campaign_id)
        if not campaign or campaign.status != "running":
            return

        campaign.started_at = campaign.started_at or _now()
        campaign.message = "Preparando fila de envio..."
        db.commit()
        ensure_campaign_queue(db, campaign)

        while True:
            campaign = db.get(EmailCampaign, campaign_id)
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

            config = get_smtp_config(db)
            if not config or not config.has_password:
                campaign.status = "failed"
                campaign.error = "SMTP não configurado."
                campaign.message = "Campanha falhou."
                db.commit()
                return

            send = db.scalars(
                select(EmailSend)
                .options(
                    selectinload(EmailSend.lead).selectinload(Lead.search_run),
                    selectinload(EmailSend.template),
                )
                .where(EmailSend.campaign_id == campaign.id, EmailSend.status == "pending")
                .order_by(EmailSend.created_at)
                .limit(1)
            ).first()

            if not send:
                refresh_campaign_counts(db, campaign)
                db.commit()
                continue

            try:
                subject, rendered_html, rendered_text = _email_content_for_send(campaign, send)
                send_email(config, send.recipient_email, subject, rendered_html, rendered_text)
                send.subject = subject
                send.status = "sent"
                send.sent_at = _now()
                send.error = None
                campaign.message = f"Enviado para {send.recipient_email}."
            except Exception as exc:
                logger.exception("Falha no envio de e-mail da campanha %s para o lead %s", campaign.id, send.lead_id)
                send.status = "failed"
                send.error = str(exc)
                campaign.message = f"Falha ao enviar para {send.recipient_email}."

            refresh_campaign_counts(db, campaign)
            db.commit()

            delay = random.randint(campaign.min_delay_seconds, campaign.max_delay_seconds)
            _sleep_with_pause_checks(db, campaign.id, delay)
    finally:
        db.close()


def mark_opened(db: Session, send_id: int) -> None:
    send = db.get(EmailSend, send_id)
    if not send:
        return
    send.open_count += 1
    send.opened_at = send.opened_at or _now()
    db.commit()


def mark_clicked(db: Session, send_id: int) -> str:
    send = db.get(EmailSend, send_id)
    if not send:
        return ""

    template = db.get(EmailTemplate, send.template_id)
    target_url = template.content_link if template and template.content_link else ""

    send.click_count += 1
    send.clicked_at = send.clicked_at or _now()
    db.commit()
    return target_url
