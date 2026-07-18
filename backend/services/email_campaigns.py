import html
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dt_time, timedelta, timezone
from threading import Lock
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


campaign_executor = ThreadPoolExecutor(max_workers=1)
_active_campaign_ids: set[int] = set()
_active_campaign_ids_lock = Lock()
VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
YOUTUBE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{6,}$")
LIST_FILTER_SEPARATOR = "||"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _split_list_filter(value: str) -> list[str]:
    if not value:
        return []

    if LIST_FILTER_SEPARATOR in value:
        return [item.strip() for item in value.split(LIST_FILTER_SEPARATOR) if item.strip()]

    return [value.strip()] if value.strip() else []


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
        "website": lead.website,
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


def _inside_send_window(campaign: EmailCampaign) -> bool:
    try:
        campaign_timezone = ZoneInfo(campaign.timezone_name or "America/New_York")
    except ZoneInfoNotFoundError:
        campaign_timezone = ZoneInfo("America/New_York")

    now = datetime.now(campaign_timezone)
    allowed_days = {int(day) for day in campaign.send_days.split(",") if day.strip().isdigit()}
    if allowed_days and now.weekday() not in allowed_days:
        return False

    start = _parse_time(campaign.send_window_start)
    end = _parse_time(campaign.send_window_end)
    return start <= now.time() <= end


def _limit_reached(db: Session, campaign: EmailCampaign) -> str:
    now = _now()
    daily_since = now - timedelta(days=1)
    weekly_since = now - timedelta(days=7)
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
        return "Limite diário atingido."
    if weekly_sent >= campaign.weekly_limit:
        return "Limite semanal atingido."
    return ""


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
                campaign.status = "paused"
                campaign.message = "Pausada: fora da janela de envio."
                db.commit()
                return

            limit_message = _limit_reached(db, campaign)
            if limit_message:
                campaign.status = "paused"
                campaign.message = f"Pausada: {limit_message}"
                db.commit()
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
                subject, rendered_html, rendered_text = render_email(send.template, send.lead, campaign, send.id)
                send_email(config, send.recipient_email, subject, rendered_html, rendered_text)
                send.subject = subject
                send.status = "sent"
                send.sent_at = _now()
                send.error = None
                campaign.message = f"Enviado para {send.recipient_email}."
            except Exception as exc:
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
