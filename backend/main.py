import logging
import base64
import csv
import multiprocessing
import os
import secrets
import traceback
from datetime import datetime, timezone
from io import StringIO
from queue import Empty
from types import SimpleNamespace
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, selectinload

from backend.auth import clear_session_cookie, create_session_token, get_current_username, set_session_cookie
from backend.config import get_settings
from backend.database import get_db, init_db
from backend.models import (
    CrmFunnel,
    CrmFunnelStage,
    CrmLead,
    CrmStageHistory,
    EmailCampaign,
    EmailCampaignTemplate,
    EmailSend,
    EmailTemplate,
    Lead,
    LeadList,
    LeadTag,
    SearchRun,
    Tag,
    WhatsAppAiSettings,
    WhatsAppCampaign,
    WhatsAppCampaignTemplate,
    WhatsAppConversation,
    WhatsAppInstance,
    WhatsAppMessage,
    WhatsAppMessageTemplate,
    WhatsAppPortfolioItem,
    WhatsAppWebhookSettings,
    WhatsAppSend,
)
from backend.schemas import (
    AiTemplateGenerateRequest,
    AiTemplateGenerateResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    ContentPreviewRead,
    CrmFunnelCreate,
    CrmFunnelRead,
    CrmFunnelStageCreate,
    CrmFunnelStageRead,
    CrmFunnelStageReorderRequest,
    CrmFunnelStageUpdate,
    CrmFunnelUpdate,
    CrmLeadFunnelSummary,
    CrmLeadRead,
    CrmLeadUpdate,
    DesktopLeadIngestResponse,
    DesktopSearchLead,
    DesktopSearchUpdate,
    EmailCampaignCreate,
    EmailCampaignRead,
    EmailCampaignUpdate,
    EmailSendRead,
    EmailTemplateCreate,
    EmailTemplateRead,
    EmailTemplateUpdate,
    LeadCreate,
    LeadSiteInsightsEnrichmentRequest,
    LeadSiteInsightsEnrichmentResponse,
    LeadWhatsAppValidationPreview,
    LeadWhatsAppValidationProgress,
    LeadWhatsAppValidationRequest,
    LeadWhatsAppValidationResponse,
    LeadListCreate,
    LeadListRead,
    LeadListUpdate,
    LeadRead,
    LeadUpdate,
    LoginRequest,
    SearchCreate,
    SearchRunRead,
    SessionRead,
    SmtpConfigRead,
    SmtpConfigUpdate,
    SmtpTestRequest,
    StatsRead,
    TagCreate,
    TagDeleteResponse,
    TagRead,
    TagSummary,
    TagUpdate,
    LeadTagsBulkRequest,
    LeadTagsBulkResponse,
    LeadTagsRequest,
    UserRead,
    WhatsAppCampaignCreate,
    WhatsAppCampaignRead,
    WhatsAppCampaignUpdate,
    WhatsAppAiSettingsRead,
    WhatsAppAiSettingsUpdate,
    WhatsAppInstanceCreate,
    WhatsAppInstanceRead,
    WhatsAppInstanceStatusRead,
    WhatsAppMessageTemplateCreate,
    WhatsAppMessageTemplateRead,
    WhatsAppMessageTemplateUpdate,
    WhatsAppPortfolioItemCreate,
    WhatsAppPortfolioItemRead,
    WhatsAppQrCodeRead,
    WhatsAppTemplateGenerateRequest,
    WhatsAppTemplateGenerateResponse,
)
from backend.scrapers.email_scraper import normalize_site_url
from backend.services.crm import (
    CRM_STAGES,
    get_default_crm_funnel,
    get_or_create_crm_lead,
    move_crm_lead,
    normalize_funnel_stage_positions,
    normalize_stage_key,
)
from backend.services.content_preview import fetch_content_preview
from backend.services.email_campaigns import (
    mark_clicked,
    mark_opened,
    render_email,
    resume_running_campaigns as resume_running_email_campaigns,
    start_campaign_scheduler as start_email_campaign_scheduler,
    submit_campaign_job as submit_email_campaign_job,
)
from backend.services.email_delivery import get_or_create_smtp_config, send_email, send_test_email, update_smtp_config
from backend.services.email_validation import validate_email_address
from backend.services.ai_templates import generate_email_templates, generate_whatsapp_template_content
from backend.services.lead_lists import count_leads_for_list
from backend.services.jobs import (
    BRAZIL_LOCATION_INFERENCE,
    eligible_retroactive_site_insights_lead_ids,
    submit_retroactive_site_insights_jobs,
    create_search_run,
    resume_unfinished_search_runs,
    save_enriched_lead,
    save_scraped_lead,
    submit_search_job,
)
from backend.services.lead_whatsapp_validation import (
    cancel_validation_job,
    connected_validation_instance_name,
    get_validation_progress,
    prepare_lead_whatsapp_validation_selection,
    preview_lead_whatsapp_validation,
    start_lead_whatsapp_validation_job,
    validation_job_is_running,
)
from backend.services.whatsapp_validation import is_whatsapp_validation_configured
from backend.services.whatsapp_ai_agent import DEFAULT_SYSTEM_PROMPT, get_or_create_ai_settings
from backend.services.whatsapp_campaigns import (
    resume_running_campaigns as resume_running_whatsapp_campaigns,
    start_campaign_scheduler as start_whatsapp_campaign_scheduler,
    submit_campaign_job as submit_whatsapp_campaign_job,
)
from backend.services.whatsapp_instance_monitor import pause_running_campaigns_for_instance
from backend.services.whatsapp_providers.evolution import EvolutionApiError, EvolutionProvider
from backend.services.whatsapp_webhooks import ingest_evolution_messages_upsert, is_evolution_messages_upsert_event
from backend.scrapers.maps_scraper import MapLead


settings = get_settings()
app = FastAPI(title="GmapScrap Web", version="0.1.0")
logger = logging.getLogger(__name__)
STARTUP_MIGRATION_TIMEOUT_SECONDS = 60

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "X-Result-Limit"],
)


@app.on_event("startup")
def on_startup() -> None:
    migration_ok = _run_startup_migration_with_timeout(_startup_migration_timeout_seconds())
    if not migration_ok:
        logger.error(
            "Aplicação iniciada em modo degradado: migração inicial do banco falhou ou excedeu o tempo limite. "
            "Schedulers não foram iniciados."
        )
        return
    resume_unfinished_search_runs()
    resume_running_email_campaigns()
    start_email_campaign_scheduler()
    resume_running_whatsapp_campaigns()
    start_whatsapp_campaign_scheduler()


def _startup_migration_timeout_seconds() -> int:
    raw_value = os.getenv("GMAPSCRAP_STARTUP_MIGRATION_TIMEOUT_SECONDS", str(STARTUP_MIGRATION_TIMEOUT_SECONDS))
    try:
        return max(0, int(raw_value))
    except ValueError:
        logger.warning("GMAPSCRAP_STARTUP_MIGRATION_TIMEOUT_SECONDS inválido: %s", raw_value)
        return STARTUP_MIGRATION_TIMEOUT_SECONDS


def _startup_migration_worker(result_queue) -> None:
    try:
        init_db()
    except BaseException:
        result_queue.put(("error", traceback.format_exc()))
        raise
    result_queue.put(("ok", ""))


def _run_startup_migration_with_timeout(timeout_seconds: int) -> bool:
    if timeout_seconds <= 0:
        init_db()
        return True

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(target=_startup_migration_worker, args=(result_queue,), name="startup-db-migration")
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        result_queue.close()
        result_queue.join_thread()
        logger.error("Migração inicial do banco excedeu %ss e foi abortada.", timeout_seconds)
        return False

    try:
        status_value, detail = result_queue.get(timeout=1)
    except Empty:
        status_value, detail = ("ok" if process.exitcode == 0 else "error", "")
    finally:
        result_queue.close()
        result_queue.join_thread()

    if process.exitcode == 0 and status_value == "ok":
        return True

    if detail:
        logger.error("Migração inicial do banco falhou:\n%s", detail)
    else:
        logger.error("Migração inicial do banco falhou com exit code %s.", process.exitcode)
    return False


def require_user(request: Request) -> str:
    return get_current_username(request)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_whatsapp_validation_available(validate_whatsapp: bool, db: Session) -> None:
    if validate_whatsapp and not is_whatsapp_validation_configured(db):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Validação de WhatsApp não configurada no servidor.",
        )


def _raise_evolution_http_error(error: EvolutionApiError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from None


def _whatsapp_provider_id(instance: WhatsAppInstance) -> str:
    provider_id = (instance.evolution_instance_name or instance.name or "").strip()
    if not provider_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Instância local sem nome de instância Evolution.",
        )
    return provider_id


def _extract_evolution_instance_name(data: dict, fallback: str) -> str:
    instance = data.get("instance") if isinstance(data.get("instance"), dict) else {}
    value = instance.get("instanceName") or instance.get("name") or data.get("instanceName") or data.get("name")
    return str(value or fallback).strip()


def _extract_qrcode(data: dict) -> tuple[str, str, str, str | None]:
    qrcode = data.get("qrcode") if isinstance(data.get("qrcode"), dict) else {}
    base64_value = data.get("base64") or qrcode.get("base64") or qrcode.get("base64Image") or ""
    url = data.get("url") or qrcode.get("url") or qrcode.get("image") or ""
    code = data.get("code") or qrcode.get("code") or ""
    pairing_code = data.get("pairingCode") or qrcode.get("pairingCode")
    return str(base64_value or ""), str(url or ""), str(code or ""), str(pairing_code) if pairing_code else None


def _extract_provider_state(data: dict) -> str:
    instance = data.get("instance") if isinstance(data.get("instance"), dict) else {}
    state = instance.get("state") or instance.get("status") or data.get("state") or data.get("status") or ""
    return str(state or "").strip().lower()


def _status_from_provider_state(provider_state: str) -> str:
    if provider_state in {"open", "connected", "online"}:
        return "connected"
    if provider_state in {"connecting", "qrcode", "qr", "pairing", "starting", "created"}:
        return "connecting"
    return "disconnected"


def _find_provider_value(data, keys: set[str]) -> str:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and value:
                return str(value)
            nested = _find_provider_value(value, keys)
            if nested:
                return nested
    if isinstance(data, list):
        for item in data:
            nested = _find_provider_value(item, keys)
            if nested:
                return nested
    return ""


def _extract_phone_number(data: dict) -> str | None:
    raw_value = _find_provider_value(
        data,
        {"phoneNumber", "phone_number", "phone", "number", "owner", "ownerJid", "wuid"},
    )
    if not raw_value:
        return None
    value = raw_value.split("@", 1)[0].split(":", 1)[0].strip()
    return value or None


def _update_whatsapp_instance_status(instance: WhatsAppInstance, provider_response: dict) -> str:
    previous_status = instance.status
    provider_state = _extract_provider_state(provider_response)
    instance.status = _status_from_provider_state(provider_state)

    phone_number = _extract_phone_number(provider_response)
    if phone_number:
        instance.phone_number = phone_number

    if previous_status in {"connecting", "disconnected"} and instance.status == "connected":
        instance.connected_at = utc_now()

    return provider_state


def _evolution_webhook_url() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/whatsapp/webhook/evolution"


def _get_or_create_evolution_webhook_secret(db: Session) -> str:
    # A linha em whatsapp_webhook_settings é a única fonte de verdade: uma vez criada, o
    # secret nunca deve mudar entre redeploys ou re-checagens de status. A env var
    # EVOLUTION_WEBHOOK_SECRET só é usada para semear a criação inicial (ex.: impor um
    # valor específico em um primeiro deploy); se ela sumir, mudar ou for reintroduzida
    # depois, isso não pode dessincronizar o secret já registrado na Evolution.
    settings_row = db.get(WhatsAppWebhookSettings, 1)
    if settings_row:
        return settings_row.secret

    seed_secret = get_settings().evolution_webhook_secret.strip()
    settings_row = WhatsAppWebhookSettings(id=1, secret=seed_secret or secrets.token_urlsafe(48))
    db.add(settings_row)
    db.flush()
    return settings_row.secret


def _configure_evolution_webhook(db: Session, provider: EvolutionProvider, instance: WhatsAppInstance) -> dict:
    instance_name = _whatsapp_provider_id(instance)
    return provider.set_webhook(
        instance_name,
        url=_evolution_webhook_url(),
        secret=_get_or_create_evolution_webhook_secret(db),
    )


def _validate_evolution_webhook_secret(request: Request, db: Session) -> None:
    expected_secret = _get_or_create_evolution_webhook_secret(db)
    provided_secret = (request.headers.get("x-evolution-webhook-secret") or "").strip()
    authorization = (request.headers.get("authorization") or "").strip()

    if not provided_secret and authorization.lower().startswith("bearer "):
        provided_secret = authorization[7:].strip()

    if not expected_secret or not provided_secret or not secrets.compare_digest(provided_secret, expected_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook Evolution não autorizado")


def _latest_whatsapp_context_for_lead(db: Session, lead_id: int) -> tuple[WhatsAppConversation | None, WhatsAppMessage | None]:
    conversation = db.scalar(
        select(WhatsAppConversation)
        .where(WhatsAppConversation.lead_id == lead_id)
        .order_by(desc(WhatsAppConversation.last_message_at), desc(WhatsAppConversation.created_at), desc(WhatsAppConversation.id))
        .limit(1)
    )
    if not conversation:
        return None, None

    message = db.scalar(
        select(WhatsAppMessage)
        .where(WhatsAppMessage.conversation_id == conversation.id)
        .order_by(desc(WhatsAppMessage.created_at), desc(WhatsAppMessage.id))
        .limit(1)
    )
    return conversation, message


def _unique_positive_ids(values: list[int] | None) -> list[int]:
    if not values or not isinstance(values, list):
        return []
    return list(dict.fromkeys(value for value in values if value > 0))


def _sorted_tags(tags: list[Tag] | None) -> list[Tag]:
    return sorted(tags or [], key=lambda tag: tag.name.lower())


def _lead_tag_summaries_by_lead_id(db: Session, lead_ids: list[int]) -> dict[int, list[TagSummary]]:
    normalized_lead_ids = _unique_positive_ids(lead_ids)
    if not normalized_lead_ids:
        return {}

    rows = db.execute(
        select(LeadTag.lead_id, LeadTag.origin, Tag.id, Tag.name, Tag.color)
        .join(Tag, Tag.id == LeadTag.tag_id)
        .where(LeadTag.lead_id.in_(normalized_lead_ids))
        .order_by(func.lower(Tag.name), Tag.id)
    ).all()
    summaries_by_lead_id: dict[int, list[TagSummary]] = {lead_id: [] for lead_id in normalized_lead_ids}
    for lead_id, origin, tag_id, name, color in rows:
        summaries_by_lead_id.setdefault(int(lead_id), []).append(
            TagSummary(
                id=int(tag_id),
                name=name,
                color=color,
                origin="ai" if origin == "ai" else "manual",
            )
        )
    return summaries_by_lead_id


def _lead_tag_summaries(db: Session, lead_id: int) -> list[TagSummary]:
    return _lead_tag_summaries_by_lead_id(db, [lead_id]).get(lead_id, [])


def _lead_read(db: Session, lead: Lead, tags: list[TagSummary] | None = None) -> LeadRead:
    return LeadRead(
        id=lead.id,
        run_id=lead.run_id,
        niche=lead.niche,
        location=lead.location,
        name=lead.name,
        address=lead.address,
        phone=lead.phone,
        website=lead.website,
        email=lead.email,
        site_insights=lead.site_insights,
        whatsapp_validated=lead.whatsapp_validated,
        whatsapp_validated_at=lead.whatsapp_validated_at,
        whatsapp_validation_status=lead.whatsapp_validation_status,
        validate_whatsapp=lead.validate_whatsapp,
        whatsapp_url=lead.whatsapp_url,
        tags=tags if tags is not None else _lead_tag_summaries(db, lead.id),
        created_at=lead.created_at,
    )


def _tag_read(tag: Tag, lead_count: int = 0) -> TagRead:
    return TagRead(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        origin="manual",
        description=tag.description,
        created_at=tag.created_at,
        lead_count=lead_count,
    )


def _apply_tag_filter(query, tag_ids: list[int], tag_filter_mode: str):
    if not tag_ids:
        return query

    if tag_filter_mode == "all":
        matching_leads = (
            select(LeadTag.lead_id)
            .where(LeadTag.tag_id.in_(tag_ids))
            .group_by(LeadTag.lead_id)
            .having(func.count(func.distinct(LeadTag.tag_id)) == len(tag_ids))
        )
        return query.where(Lead.id.in_(matching_leads))

    return query.where(Lead.id.in_(select(LeadTag.lead_id).where(LeadTag.tag_id.in_(tag_ids))))


def _load_lead_for_read(db: Session, lead_id: int) -> Lead | None:
    return db.scalar(
        select(Lead)
        .options(selectinload(Lead.search_run))
        .where(Lead.id == lead_id)
    )


def _find_tag_by_name(db: Session, name: str, *, exclude_id: int | None = None) -> Tag | None:
    stmt = select(Tag).where(func.lower(Tag.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Tag.id != exclude_id)
    return db.scalar(stmt)


def _existing_tag_ids(db: Session, tag_ids: list[int]) -> set[int]:
    if not tag_ids:
        return set()
    return set(db.scalars(select(Tag.id).where(Tag.id.in_(tag_ids))).all())


def _sorted_funnel_stages(stages: list[CrmFunnelStage] | None) -> list[CrmFunnelStage]:
    return sorted(stages or [], key=lambda stage: (stage.position, stage.id))


def _stage_card_counts(db: Session, funnel_id: int) -> dict[int, int]:
    rows = db.execute(
        select(CrmLead.stage_id, func.count(CrmLead.id))
        .where(CrmLead.funnel_id == funnel_id)
        .group_by(CrmLead.stage_id)
    ).all()
    return {int(stage_id): int(count or 0) for stage_id, count in rows if stage_id is not None}


def _funnel_card_count(db: Session, funnel_id: int) -> int:
    return int(db.scalar(select(func.count(CrmLead.id)).where(CrmLead.funnel_id == funnel_id)) or 0)


def _stage_read(stage: CrmFunnelStage, card_count: int = 0) -> CrmFunnelStageRead:
    return CrmFunnelStageRead(
        id=stage.id,
        funnel_id=stage.funnel_id,
        key=stage.key,
        label=stage.label,
        color=stage.color,
        description=stage.description,
        position=stage.position,
        is_won=stage.is_won,
        is_lost=stage.is_lost,
        card_count=card_count,
    )


def _funnel_read(db: Session, funnel: CrmFunnel) -> CrmFunnelRead:
    stage_counts = _stage_card_counts(db, funnel.id)
    return CrmFunnelRead(
        id=funnel.id,
        name=funnel.name,
        description=funnel.description,
        is_default=funnel.is_default,
        created_at=funnel.created_at,
        card_count=_funnel_card_count(db, funnel.id),
        stages=[_stage_read(stage, stage_counts.get(stage.id, 0)) for stage in _sorted_funnel_stages(funnel.stages)],
    )


def _find_funnel_by_name(db: Session, name: str, *, exclude_id: int | None = None) -> CrmFunnel | None:
    stmt = select(CrmFunnel).where(func.lower(CrmFunnel.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(CrmFunnel.id != exclude_id)
    return db.scalar(stmt)


def _find_stage_by_key(db: Session, funnel_id: int, key: str, *, exclude_id: int | None = None) -> CrmFunnelStage | None:
    stmt = select(CrmFunnelStage).where(CrmFunnelStage.funnel_id == funnel_id, CrmFunnelStage.key == key)
    if exclude_id is not None:
        stmt = stmt.where(CrmFunnelStage.id != exclude_id)
    return db.scalar(stmt)


def _next_stage_key(db: Session, funnel_id: int, label: str) -> str:
    base_key = normalize_stage_key(label)
    key = base_key
    suffix = 2
    while _find_stage_by_key(db, funnel_id, key):
        key = f"{base_key[:54]}_{suffix}"
        suffix += 1
    return key


def _crm_other_funnels(db: Session, crm_lead: CrmLead) -> list[CrmLeadFunnelSummary]:
    rows = db.scalars(
        select(CrmLead)
        .options(selectinload(CrmLead.funnel), selectinload(CrmLead.stage_ref))
        .where(CrmLead.lead_id == crm_lead.lead_id, CrmLead.id != crm_lead.id)
        .order_by(desc(CrmLead.updated_at), desc(CrmLead.id))
    ).all()
    return [
        CrmLeadFunnelSummary(
            id=row.funnel_id,
            name=row.funnel.name if row.funnel else "",
            stage=row.stage,
            stage_label=row.stage_ref.label if row.stage_ref else row.stage,
        )
        for row in rows
        if row.funnel_id
    ]


def _crm_lead_read(
    db: Session,
    crm_lead: CrmLead,
    tag_summaries_by_lead_id: dict[int, list[TagSummary]] | None = None,
) -> CrmLeadRead:
    lead = crm_lead.lead
    conversation, latest_message = _latest_whatsapp_context_for_lead(db, crm_lead.lead_id)
    stage_ref = crm_lead.stage_ref
    funnel = crm_lead.funnel

    return CrmLeadRead(
        id=crm_lead.id,
        lead_id=crm_lead.lead_id,
        funnel_id=crm_lead.funnel_id,
        funnel_name=funnel.name if funnel else "",
        stage_id=crm_lead.stage_id,
        stage=crm_lead.stage,
        stage_label=stage_ref.label if stage_ref else crm_lead.stage,
        stage_color=stage_ref.color if stage_ref else "#f3f4f6",
        qualification_notes=crm_lead.qualification_notes,
        score=crm_lead.score,
        position=crm_lead.position,
        updated_at=crm_lead.updated_at,
        lead_name=lead.name if lead else "",
        phone=lead.phone if lead else None,
        whatsapp_url=lead.whatsapp_url if lead else "",
        website=lead.website if lead else None,
        email=lead.email if lead else "",
        niche=lead.search_run.niche if lead and lead.search_run else "",
        location=lead.search_run.location if lead and lead.search_run else "",
        tags=tag_summaries_by_lead_id.get(lead.id, []) if lead and tag_summaries_by_lead_id is not None else (
            _lead_tag_summaries(db, lead.id) if lead else []
        ),
        last_message=latest_message.content if latest_message else None,
        last_message_at=conversation.last_message_at if conversation else None,
        conversation_id=conversation.id if conversation else None,
        other_funnels=_crm_other_funnels(db, crm_lead),
    )


def _count_saved_leads_for_run(db: Session, run_id: int) -> int:
    return int(db.scalar(select(func.count(Lead.id)).where(Lead.run_id == run_id)) or 0)


def _find_existing_desktop_lead(db: Session, run_id: int, lead: MapLead) -> Lead | None:
    raw_website = (lead.website or "").strip()
    website = normalize_site_url(raw_website) if raw_website else ""
    if website:
        return db.scalar(select(Lead).where(Lead.run_id == run_id, Lead.website == website))

    phone = (lead.phone or "").strip()
    name = (lead.name or "").strip()
    address = (lead.address or "").strip() or "Não encontrado"
    if not name:
        return None

    stmt = select(Lead).where(
        Lead.run_id == run_id,
        Lead.website.is_(None),
        Lead.name == name,
        Lead.address == address,
    )
    if phone:
        stmt = stmt.where(Lead.phone == phone)

    return db.scalar(stmt)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/email/open/{send_id}.png")
def track_email_open(send_id: int, db: Session = Depends(get_db)) -> Response:
    mark_opened(db, send_id)
    pixel = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=")
    return Response(content=pixel, media_type="image/png")


@app.get("/api/email/click/{send_id}")
def track_email_click(send_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    target_url = mark_clicked(db, send_id)
    return RedirectResponse(target_url or "https://www.automasoluct.com.br", status_code=302)


@app.post("/api/auth/login", response_model=UserRead)
def login(payload: LoginRequest, response: Response) -> UserRead:
    if payload.username != settings.app_username or payload.password != settings.app_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos")

    token = create_session_token(payload.username)
    set_session_cookie(response, token)
    return UserRead(username=payload.username)


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, str]:
    clear_session_cookie(response)
    return {"status": "ok"}


@app.get("/api/auth/me", response_model=UserRead)
def me(username: str = Depends(require_user)) -> UserRead:
    return UserRead(username=username)


@app.get("/api/auth/session", response_model=SessionRead)
def session(request: Request) -> SessionRead:
    try:
        username = get_current_username(request)
    except HTTPException:
        return SessionRead(authenticated=False)

    return SessionRead(authenticated=True, username=username)


@app.post("/api/searches", response_model=SearchRunRead)
def start_search(
    payload: SearchCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> SearchRun:
    _ = username
    ensure_whatsapp_validation_available(payload.validate_whatsapp, db)
    return create_search_run(db, payload)


@app.get("/api/searches", response_model=list[SearchRunRead])
def list_searches(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[SearchRun]:
    _ = username
    stmt = select(SearchRun).order_by(desc(SearchRun.created_at)).limit(50)
    return list(db.scalars(stmt).all())


@app.get("/api/searches/{run_id}", response_model=SearchRunRead)
def get_search(
    run_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> SearchRun:
    _ = username
    run = db.get(SearchRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Busca não encontrada")
    return run


@app.post("/api/desktop/searches", response_model=SearchRunRead)
def create_desktop_search(
    payload: SearchCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> SearchRun:
    _ = username
    ensure_whatsapp_validation_available(payload.validate_whatsapp, db)
    run = SearchRun(
        niche=payload.niche.strip(),
        location=payload.location.strip(),
        target_quantity=None if payload.max_results else payload.quantity,
        max_results=payload.max_results,
        skip_without_website=payload.skip_without_website,
        only_without_website=payload.only_without_website,
        validate_whatsapp=payload.validate_whatsapp,
        enrich_site_insights=payload.enrich_site_insights,
        status="running",
        message="Busca local iniciada no aplicativo desktop.",
        started_at=utc_now(),
        finished_at=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@app.patch("/api/desktop/searches/{run_id}", response_model=SearchRunRead)
def update_desktop_search(
    run_id: int,
    payload: DesktopSearchUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> SearchRun:
    _ = username
    run = db.get(SearchRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Busca não encontrada")

    if payload.scanned_count is not None:
        run.scanned_count = max(run.scanned_count, payload.scanned_count)

    if payload.skipped_delta:
        run.skipped_count += payload.skipped_delta

    if payload.message is not None:
        run.message = payload.message.strip()

    if payload.error is not None:
        run.error = payload.error.strip() or None

    if payload.status is not None:
        run.status = payload.status
        if payload.status in ("completed", "failed"):
            run.finished_at = utc_now()
        if payload.status == "failed" and not run.error:
            run.error = run.message or "Busca local falhou."

    db.commit()
    db.refresh(run)
    return run


@app.post("/api/desktop/searches/{run_id}/leads", response_model=DesktopLeadIngestResponse)
def ingest_desktop_lead(
    run_id: int,
    payload: DesktopSearchLead,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> DesktopLeadIngestResponse:
    _ = username
    run = db.get(SearchRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Busca não encontrada")

    if run.status not in ("queued", "running", "paused"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta busca já foi finalizada")

    lead = MapLead(
        name=payload.name.strip(),
        address=payload.address.strip() or "Não encontrado",
        phone=payload.phone.strip(),
        website=payload.website.strip(),
    )

    existing_lead = _find_existing_desktop_lead(db, run.id, lead)
    if existing_lead:
        run.status = "running"
        run.scanned_count = max(run.scanned_count, payload.scanned)
        run.saved_count = max(run.saved_count, _count_saved_leads_for_run(db, run.id))
        run.message = f"{lead.name} já estava salvo nesta execução."
        db.commit()
        db.refresh(run)
        return DesktopLeadIngestResponse(saved=True, message=run.message, run=run)

    run.status = "running"
    run.scanned_count = max(run.scanned_count, payload.scanned)
    run.message = f"Salvando {lead.name}..." if payload.email.strip() or not lead.website else f"Buscando e-mail em {lead.website}..."
    db.commit()

    if payload.email.strip():
        saved = save_enriched_lead(db, run, lead, payload.email)
    else:
        saved = save_scraped_lead(db, run, lead)
    run = db.get(SearchRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Busca não encontrada")

    if saved:
        run.saved_count += 1
        run.message = f"{lead.name} salvo."

    db.commit()
    db.refresh(run)
    return DesktopLeadIngestResponse(saved=saved, message=run.message, run=run)


@app.post("/api/searches/{run_id}/pause", response_model=SearchRunRead)
def pause_search(
    run_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> SearchRun:
    _ = username
    run = db.get(SearchRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Busca não encontrada")

    if run.status == "paused":
        return run

    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta busca não pode ser pausada")

    run.status = "paused"
    run.message = "Busca pausada."
    db.commit()
    db.refresh(run)
    return run


@app.post("/api/searches/{run_id}/resume", response_model=SearchRunRead)
def resume_search(
    run_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> SearchRun:
    _ = username
    run = db.get(SearchRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Busca não encontrada")

    if run.status != "paused":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta busca não está pausada")

    run.status = "running"
    run.message = "Retomando busca..."
    run.finished_at = None
    db.commit()
    submit_search_job(run.id)
    db.refresh(run)
    return run


@app.get("/api/leads", response_model=list[LeadRead])
def list_leads(
    run_id: int | None = None,
    niche: str | None = None,
    location: str | None = None,
    whatsapp_status: str | None = None,
    tag_ids: list[int] | None = Query(default=None),
    tag_filter_mode: str = "any",
    email_campaign_id: int | None = None,
    email_opened: bool = False,
    email_clicked: bool = False,
    whatsapp_campaign_id: int | None = None,
    whatsapp_replied: bool = False,
    response: Response = None,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[LeadRead]:
    _ = username
    allowed_whatsapp_statuses = {"valid", "invalid", "unknown", "never"}
    if whatsapp_status is not None and whatsapp_status not in allowed_whatsapp_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status de validação de WhatsApp inválido.",
        )
    normalized_tag_filter_mode = (tag_filter_mode or "any").strip().lower()
    if normalized_tag_filter_mode not in {"any", "all"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Modo de filtro por tags inválido. Use 'any' ou 'all'.",
        )
    normalized_tag_ids = _unique_positive_ids(tag_ids)

    def apply_filters(query):
        if run_id is not None:
            query = query.where(Lead.run_id == run_id)

        if niche:
            query = query.where(SearchRun.niche.ilike(f"%{niche.strip()}%"))

        if location:
            query = query.where(SearchRun.location.ilike(f"%{location.strip()}%"))

        if whatsapp_status == "never":
            query = query.where(Lead.whatsapp_validated_at.is_(None))
        elif whatsapp_status:
            query = query.where(Lead.whatsapp_validation_status == whatsapp_status)

        if email_campaign_id is not None:
            query = query.where(Lead.id.in_(select(EmailSend.lead_id).where(EmailSend.campaign_id == email_campaign_id)))

        if email_opened or email_clicked:
            email_engagement_conditions = []
            if email_opened:
                email_engagement_conditions.append(or_(EmailSend.open_count > 0, EmailSend.opened_at.is_not(None)))
            if email_clicked:
                email_engagement_conditions.append(or_(EmailSend.click_count > 0, EmailSend.clicked_at.is_not(None)))

            engaged_email_leads_stmt = select(EmailSend.lead_id).where(or_(*email_engagement_conditions))
            if email_campaign_id is not None:
                engaged_email_leads_stmt = engaged_email_leads_stmt.where(EmailSend.campaign_id == email_campaign_id)
            query = query.where(Lead.id.in_(engaged_email_leads_stmt))

        if whatsapp_campaign_id is not None:
            query = query.where(
                Lead.id.in_(select(WhatsAppSend.lead_id).where(WhatsAppSend.campaign_id == whatsapp_campaign_id))
            )

        if whatsapp_replied:
            sent_whatsapp_leads_stmt = select(WhatsAppSend.lead_id)
            if whatsapp_campaign_id is not None:
                sent_whatsapp_leads_stmt = sent_whatsapp_leads_stmt.where(
                    WhatsAppSend.campaign_id == whatsapp_campaign_id
                )
            replied_leads_stmt = (
                select(WhatsAppConversation.lead_id)
                .join(WhatsAppMessage, WhatsAppMessage.conversation_id == WhatsAppConversation.id)
                .where(
                    WhatsAppConversation.lead_id.is_not(None),
                    WhatsAppConversation.lead_id.in_(sent_whatsapp_leads_stmt),
                    WhatsAppMessage.direction == "inbound",
                )
            )
            query = query.where(Lead.id.in_(replied_leads_stmt))

        query = _apply_tag_filter(query, normalized_tag_ids, normalized_tag_filter_mode)

        return query

    stmt = apply_filters(
        select(Lead)
        .options(contains_eager(Lead.search_run))
        .join(SearchRun)
        .order_by(desc(Lead.created_at))
    )
    total_count = db.scalar(select(func.count()).select_from(apply_filters(select(Lead.id).join(SearchRun)).subquery())) or 0
    if response is not None:
        response.headers["X-Total-Count"] = str(total_count)
        response.headers["X-Result-Limit"] = "500"

    leads = list(db.scalars(stmt.limit(500)).all())
    tag_summaries_by_lead_id = _lead_tag_summaries_by_lead_id(db, [lead.id for lead in leads])
    return [_lead_read(db, lead, tag_summaries_by_lead_id.get(lead.id, [])) for lead in leads]


@app.post("/api/leads/enrich-site-insights", response_model=LeadSiteInsightsEnrichmentResponse)
def enrich_existing_leads_site_insights(
    payload: LeadSiteInsightsEnrichmentRequest | None = None,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadSiteInsightsEnrichmentResponse:
    _ = username
    requested_ids = payload.lead_ids if payload is not None and payload.lead_ids else None
    if requested_ids is not None:
        selected_ids = list(dict.fromkeys(lead_id for lead_id in requested_ids if lead_id > 0))
        selected_eligible_ids = set(
            db.scalars(
                select(Lead.id).where(
                    Lead.id.in_(selected_ids),
                    Lead.website.is_not(None),
                    Lead.website != "",
                    Lead.site_insights.is_(None),
                )
            ).all()
        )
        eligible_ids = [lead_id for lead_id in selected_ids if lead_id in selected_eligible_ids]
    else:
        eligible_ids = eligible_retroactive_site_insights_lead_ids(db)
    queued_count = submit_retroactive_site_insights_jobs(eligible_ids)
    status_value = "processing_started" if queued_count else "no_eligible_leads"
    return LeadSiteInsightsEnrichmentResponse(
        status=status_value,
        eligible_count=len(eligible_ids),
        queued_count=queued_count,
        location_inference=BRAZIL_LOCATION_INFERENCE,
    )


def _lead_whatsapp_validation_kwargs(payload: LeadWhatsAppValidationRequest) -> dict[str, Any]:
    return {
        "lead_ids": payload.lead_ids if payload.lead_ids else None,
        "niche": payload.niche,
        "location": payload.location,
        "search": payload.search,
        "only_pending": payload.only_pending,
        "revalidate": payload.revalidate,
        "limit": payload.limit,
    }


def _ensure_lead_whatsapp_validation_can_start(db: Session) -> None:
    if not is_whatsapp_validation_configured(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Validação de WhatsApp não configurada. Configure EVOLUTION_API_BASE_URL, "
                "EVOLUTION_API_KEY e uma instância Evolution conectada."
            ),
        )

    try:
        connected_validation_instance_name(db)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A instância do WhatsApp não está conectada. Conecte-a em Instâncias antes de validar.",
        ) from exc


def _running_validation_conflict() -> HTTPException:
    progress = get_validation_progress()
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": "Já existe uma validação de WhatsApp em andamento.",
            "job_id": progress.get("job_id") or "",
        },
    )


def _lead_whatsapp_validation_message(queued_count: int, eligible_count: int) -> str:
    if queued_count:
        return f"Validação de WhatsApp iniciada: {queued_count} de {eligible_count} leads entrarão na fila."
    if eligible_count:
        return "Nenhum lead elegível para validar agora com os critérios informados."
    return "Nenhum lead encontrado para os critérios informados."


@app.post(
    "/api/leads/validate-whatsapp",
    response_model=LeadWhatsAppValidationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_existing_leads_whatsapp_validation(
    payload: LeadWhatsAppValidationRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadWhatsAppValidationResponse:
    _ = username
    _ensure_lead_whatsapp_validation_can_start(db)
    if validation_job_is_running():
        raise _running_validation_conflict()

    kwargs = _lead_whatsapp_validation_kwargs(payload)
    selection = prepare_lead_whatsapp_validation_selection(db, **kwargs)
    try:
        progress = start_lead_whatsapp_validation_job(**kwargs)
    except RuntimeError as exc:
        if validation_job_is_running():
            raise _running_validation_conflict() from exc
        logger.exception("Falha ao iniciar validação de WhatsApp dos leads existentes")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao iniciar validação de WhatsApp dos leads existentes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível iniciar a validação de WhatsApp.",
        ) from exc

    return LeadWhatsAppValidationResponse(
        job_id=str(progress.get("job_id") or ""),
        status=str(progress.get("status") or "running"),
        eligible_count=selection.eligible_count,
        queued_count=selection.queued_count,
        skipped_count=selection.skipped_count,
        message=_lead_whatsapp_validation_message(selection.queued_count, selection.eligible_count),
    )


@app.get("/api/leads/validate-whatsapp/progress", response_model=LeadWhatsAppValidationProgress)
def get_existing_leads_whatsapp_validation_progress(
    username: str = Depends(require_user),
) -> dict[str, Any]:
    _ = username
    return get_validation_progress()


@app.post("/api/leads/validate-whatsapp/cancel", response_model=LeadWhatsAppValidationProgress)
def cancel_existing_leads_whatsapp_validation(
    username: str = Depends(require_user),
) -> dict[str, Any]:
    _ = username
    try:
        return cancel_validation_job()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/api/leads/validate-whatsapp/preview", response_model=LeadWhatsAppValidationPreview)
def preview_existing_leads_whatsapp_validation(
    payload: LeadWhatsAppValidationRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadWhatsAppValidationPreview:
    _ = username
    try:
        preview = preview_lead_whatsapp_validation(db, **_lead_whatsapp_validation_kwargs(payload))
    except Exception as exc:
        logger.exception("Falha ao pré-visualizar validação de WhatsApp dos leads existentes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível pré-visualizar a validação de WhatsApp.",
        ) from exc

    return LeadWhatsAppValidationPreview(
        total_leads=preview.total_leads,
        never_validated=preview.never_validated,
        valid=preview.valid,
        invalid=preview.invalid,
        unknown=preview.unknown,
        without_phone=preview.without_phone,
        eligible_now=preview.eligible_now,
    )


@app.post("/api/leads", response_model=LeadRead)
def create_manual_lead(
    payload: LeadCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadRead:
    _ = username
    raw_website = payload.website.strip()
    website = normalize_site_url(raw_website) if raw_website else ""
    if raw_website and not website:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Site inválido")

    if website and db.scalar(select(Lead).where(Lead.website == website)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um lead com esse site")

    email = payload.email.strip().lower()
    if email:
        validation = validate_email_address(email, website)
        if not validation.is_valid:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="E-mail inválido")
        email = validation.normalized_email

    niche = payload.niche.strip()
    location = payload.location.strip()
    now = utc_now()
    manual_message = "Leads cadastrados manualmente."
    run = db.scalar(
        select(SearchRun)
        .where(
            SearchRun.niche == niche,
            SearchRun.location == location,
            SearchRun.message == manual_message,
            SearchRun.status == "completed",
        )
        .order_by(desc(SearchRun.created_at))
    )

    if not run:
        run = SearchRun(
            niche=niche,
            location=location,
            target_quantity=None,
            max_results=True,
            status="completed",
            message=manual_message,
            scanned_count=0,
            saved_count=0,
            skipped_count=0,
            started_at=now,
            finished_at=now,
        )
        db.add(run)

    lead = Lead(
        search_run=run,
        name=payload.name.strip(),
        address=payload.address.strip() or "Não informado",
        phone=payload.phone.strip(),
        website=website or None,
        email=email,
    )
    run.scanned_count += 1
    run.saved_count += 1
    run.finished_at = now
    db.add(lead)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead duplicado") from None

    db.refresh(lead)
    return _lead_read(db, lead, [])


@app.patch("/api/leads/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadRead:
    _ = username
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado")

    data = payload.model_dump(exclude_unset=True)
    next_niche = data.pop("niche", None)
    next_location = data.pop("location", None)
    if "website" in data:
        raw_website = (data["website"] or "").strip()
        website = normalize_site_url(raw_website) if raw_website else ""
        if raw_website and not website:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Site inválido")

        existing = db.scalar(select(Lead).where(Lead.website == website, Lead.id != lead_id)) if website else None
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um lead com esse site")

        data["website"] = website or None

    if "email" in data:
        email = (data["email"] or "").strip().lower()
        if email:
            website_for_validation = data.get("website")
            if website_for_validation is None:
                website_for_validation = lead.website or ""
            validation = validate_email_address(email, str(website_for_validation or ""))
            if not validation.is_valid:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="E-mail inválido")
            data["email"] = validation.normalized_email
        else:
            data["email"] = ""

    if next_niche is not None or next_location is not None:
        niche = (next_niche if next_niche is not None else lead.niche).strip()
        location = (next_location if next_location is not None else lead.location).strip()
        if not niche or not location:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nicho e localidade são obrigatórios")

        if niche != lead.niche or location != lead.location:
            now = utc_now()
            manual_message = "Leads cadastrados manualmente."
            run = db.scalar(
                select(SearchRun)
                .where(
                    SearchRun.niche == niche,
                    SearchRun.location == location,
                    SearchRun.message == manual_message,
                    SearchRun.status == "completed",
                )
                .order_by(desc(SearchRun.created_at))
            )

            if not run:
                run = SearchRun(
                    niche=niche,
                    location=location,
                    target_quantity=None,
                    max_results=True,
                    status="completed",
                    message=manual_message,
                    scanned_count=0,
                    saved_count=0,
                    skipped_count=0,
                    started_at=now,
                    finished_at=now,
                )
                db.add(run)

            lead.search_run = run

    for field, value in data.items():
        setattr(lead, field, value.strip() if isinstance(value, str) else value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead duplicado") from None

    db.refresh(lead)
    loaded_lead = _load_lead_for_read(db, lead.id) or lead
    return _lead_read(db, loaded_lead)


@app.delete("/api/leads/{lead_id}")
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado")

    db.delete(lead)
    db.commit()
    return {"status": "ok"}


@app.post("/api/leads/bulk-delete", response_model=BulkDeleteResponse)
def bulk_delete_leads(
    payload: BulkDeleteRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> BulkDeleteResponse:
    _ = username
    unique_ids = sorted(set(payload.ids))
    leads = list(db.scalars(select(Lead).where(Lead.id.in_(unique_ids))).all())

    for lead in leads:
        db.delete(lead)

    db.commit()
    return BulkDeleteResponse(deleted=len(leads))


@app.get("/api/tags", response_model=list[TagRead])
def list_tags(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[TagRead]:
    _ = username
    rows = db.execute(
        select(Tag, func.count(LeadTag.lead_id))
        .outerjoin(LeadTag, LeadTag.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(func.lower(Tag.name))
    ).all()
    return [_tag_read(tag, int(lead_count or 0)) for tag, lead_count in rows]


@app.post("/api/tags", response_model=TagRead)
def create_tag(
    payload: TagCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> TagRead:
    _ = username
    if _find_tag_by_name(db, payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma tag com esse nome.")

    tag = Tag(name=payload.name, color=payload.color, description=payload.description)
    db.add(tag)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma tag com esse nome.") from None
    db.refresh(tag)
    return _tag_read(tag, 0)


@app.patch("/api/tags/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: int,
    payload: TagUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> TagRead:
    _ = username
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag não encontrada")

    payload_data = payload.model_dump(exclude_unset=True)
    if "name" in payload_data and payload_data["name"] is not None:
        if _find_tag_by_name(db, payload_data["name"], exclude_id=tag.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma tag com esse nome.")
        tag.name = payload_data["name"]
    if "color" in payload_data and payload_data["color"] is not None:
        tag.color = payload_data["color"]
    if "description" in payload_data:
        tag.description = payload_data["description"]

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma tag com esse nome.") from None

    db.refresh(tag)
    lead_count = db.scalar(select(func.count(LeadTag.lead_id)).where(LeadTag.tag_id == tag.id)) or 0
    return _tag_read(tag, int(lead_count))


@app.delete("/api/tags/{tag_id}", response_model=TagDeleteResponse)
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> TagDeleteResponse:
    _ = username
    tag_exists = db.scalar(select(Tag.id).where(Tag.id == tag_id))
    if tag_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag não encontrada")

    affected_leads = db.scalar(select(func.count(LeadTag.lead_id)).where(LeadTag.tag_id == tag_id)) or 0
    db.execute(delete(LeadTag).where(LeadTag.tag_id == tag_id))
    db.execute(delete(Tag).where(Tag.id == tag_id))
    db.commit()
    return TagDeleteResponse(deleted=True, affected_leads=int(affected_leads))


@app.post("/api/leads/{lead_id}/tags", response_model=LeadRead)
def add_tags_to_lead(
    lead_id: int,
    payload: LeadTagsRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadRead:
    _ = username
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado")

    tag_ids = _unique_positive_ids(payload.tag_ids)
    existing_tag_ids = _existing_tag_ids(db, tag_ids)
    if len(existing_tag_ids) != len(tag_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uma ou mais tags não foram encontradas")

    existing_pairs = set(
        db.execute(
            select(LeadTag.tag_id).where(
                LeadTag.lead_id == lead_id,
                LeadTag.tag_id.in_(tag_ids),
            )
        ).scalars()
    )
    for tag_id in tag_ids:
        if tag_id not in existing_pairs:
            db.add(LeadTag(lead_id=lead_id, tag_id=tag_id))

    db.commit()
    updated_lead = _load_lead_for_read(db, lead_id)
    if not updated_lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado")
    return _lead_read(db, updated_lead)


@app.delete("/api/leads/{lead_id}/tags/{tag_id}", response_model=LeadRead)
def remove_tag_from_lead(
    lead_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadRead:
    _ = username
    if not db.get(Lead, lead_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado")
    if not db.get(Tag, tag_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag não encontrada")

    db.execute(delete(LeadTag).where(LeadTag.lead_id == lead_id, LeadTag.tag_id == tag_id))
    db.commit()
    updated_lead = _load_lead_for_read(db, lead_id)
    if not updated_lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado")
    return _lead_read(db, updated_lead)


@app.post("/api/leads/tags/bulk", response_model=LeadTagsBulkResponse)
def bulk_update_lead_tags(
    payload: LeadTagsBulkRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadTagsBulkResponse:
    _ = username
    lead_ids = _unique_positive_ids(payload.lead_ids)
    tag_ids = _unique_positive_ids(payload.tag_ids)
    existing_lead_ids = set(db.scalars(select(Lead.id).where(Lead.id.in_(lead_ids))).all())
    existing_tag_ids = _existing_tag_ids(db, tag_ids)
    if len(existing_tag_ids) != len(tag_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uma ou mais tags não foram encontradas")

    changed = 0
    if payload.action == "add":
        existing_pairs = {
            (lead_id, tag_id)
            for lead_id, tag_id in db.execute(
                select(LeadTag.lead_id, LeadTag.tag_id).where(
                    LeadTag.lead_id.in_(existing_lead_ids),
                    LeadTag.tag_id.in_(existing_tag_ids),
                )
            ).all()
        }
        for lead_id in existing_lead_ids:
            for tag_id in existing_tag_ids:
                if (lead_id, tag_id) not in existing_pairs:
                    db.add(LeadTag(lead_id=lead_id, tag_id=tag_id))
                    changed += 1
    else:
        existing_pairs = db.execute(
            select(LeadTag.lead_id, LeadTag.tag_id).where(
                LeadTag.lead_id.in_(existing_lead_ids),
                LeadTag.tag_id.in_(existing_tag_ids),
            )
        ).all()
        changed = len(existing_pairs)
        db.execute(
            delete(LeadTag).where(
                LeadTag.lead_id.in_(existing_lead_ids),
                LeadTag.tag_id.in_(existing_tag_ids),
            )
        )

    db.commit()
    return LeadTagsBulkResponse(
        action=payload.action,
        matched_leads=len(existing_lead_ids),
        matched_tags=len(existing_tag_ids),
        changed_associations=changed,
    )


@app.post("/api/whatsapp/instances", response_model=WhatsAppInstanceRead)
def create_whatsapp_instance(
    payload: WhatsAppInstanceCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppInstance:
    _ = username
    instance = WhatsAppInstance(
        name=payload.name.strip(),
        provider="evolution",
        status="disconnected",
        phone_number=payload.phone_number.strip() if payload.phone_number else None,
    )
    db.add(instance)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma instância com esse nome") from None

    provider = EvolutionProvider()
    try:
        provider_response = provider.create_instance(instance.name, phone_number=instance.phone_number)
    except EvolutionApiError as exc:
        db.rollback()
        _raise_evolution_http_error(exc)

    instance.evolution_instance_name = _extract_evolution_instance_name(provider_response, instance.name)
    try:
        _configure_evolution_webhook(db, provider, instance)
    except EvolutionApiError as exc:
        db.rollback()
        _raise_evolution_http_error(exc)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Instância Evolution já cadastrada") from None

    db.refresh(instance)
    return instance


@app.get("/api/whatsapp/instances", response_model=list[WhatsAppInstanceRead])
def list_whatsapp_instances(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[WhatsAppInstance]:
    _ = username
    return list(db.scalars(select(WhatsAppInstance).order_by(desc(WhatsAppInstance.created_at))).all())


@app.get("/api/whatsapp/instances/{instance_id}/qrcode", response_model=WhatsAppQrCodeRead)
def get_whatsapp_instance_qrcode(
    instance_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppQrCodeRead:
    _ = username
    instance = db.get(WhatsAppInstance, instance_id)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instância de WhatsApp não encontrada")

    provider = EvolutionProvider()
    try:
        provider_response = provider.get_qr_code(_whatsapp_provider_id(instance))
    except EvolutionApiError as exc:
        _raise_evolution_http_error(exc)

    if instance.status == "disconnected":
        instance.status = "connecting"
        db.commit()
        db.refresh(instance)

    base64_value, qr_url, code, pairing_code = _extract_qrcode(provider_response)
    return WhatsAppQrCodeRead(
        id=instance.id,
        name=instance.name,
        evolution_instance_name=_whatsapp_provider_id(instance),
        base64=base64_value,
        url=qr_url,
        code=code,
        pairing_code=pairing_code,
        provider_response=provider_response,
    )


@app.get("/api/whatsapp/instances/{instance_id}/status", response_model=WhatsAppInstanceStatusRead)
def get_whatsapp_instance_status(
    instance_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppInstanceStatusRead:
    _ = username
    instance = db.get(WhatsAppInstance, instance_id)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instância de WhatsApp não encontrada")

    provider = EvolutionProvider()
    try:
        provider_response = provider.get_connection_status(_whatsapp_provider_id(instance))
    except EvolutionApiError as exc:
        _raise_evolution_http_error(exc)

    provider_state = _update_whatsapp_instance_status(instance, provider_response)
    if instance.status == "connected":
        try:
            _configure_evolution_webhook(db, provider, instance)
        except EvolutionApiError as exc:
            db.rollback()
            _raise_evolution_http_error(exc)
    else:
        pause_running_campaigns_for_instance(db, instance)
    db.commit()
    db.refresh(instance)
    return WhatsAppInstanceStatusRead(
        id=instance.id,
        name=instance.name,
        status=instance.status,
        phone_number=instance.phone_number,
        connected_at=instance.connected_at,
        provider_state=provider_state,
        provider_response=provider_response,
    )


@app.delete("/api/whatsapp/instances/{instance_id}")
def delete_whatsapp_instance(
    instance_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    instance = db.get(WhatsAppInstance, instance_id)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instância de WhatsApp não encontrada")

    if instance.provider != "evolution":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Provider ainda não suportado")

    provider = EvolutionProvider()
    try:
        provider.delete_instance(_whatsapp_provider_id(instance))
    except EvolutionApiError as exc:
        _raise_evolution_http_error(exc)

    db.delete(instance)
    db.commit()
    return {"status": "ok"}


@app.post("/api/whatsapp/webhook/evolution")
def receive_evolution_webhook(
    payload: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_evolution_webhook_secret(request, db)
    event = str(payload.get("event") or "")

    if not is_evolution_messages_upsert_event(event):
        return {"status": "ignored", "event": event}

    try:
        result = ingest_evolution_messages_upsert(db, payload)
        db.commit()
    except EvolutionApiError as exc:
        db.rollback()
        _raise_evolution_http_error(exc)
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return {"status": "ok", "event": event, **result}


@app.get("/api/whatsapp/ai-settings", response_model=WhatsAppAiSettingsRead)
def get_whatsapp_ai_settings(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppAiSettings:
    _ = username
    settings_row = get_or_create_ai_settings(db)
    db.commit()
    db.refresh(settings_row)
    return settings_row


@app.put("/api/whatsapp/ai-settings", response_model=WhatsAppAiSettingsRead)
def update_whatsapp_ai_settings(
    payload: WhatsAppAiSettingsUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppAiSettings:
    _ = username
    settings_row = get_or_create_ai_settings(db)
    payload_data = payload.model_dump(exclude_unset=True)

    if "system_prompt" in payload_data:
        system_prompt = payload_data["system_prompt"]
        settings_row.system_prompt = system_prompt.strip() if isinstance(system_prompt, str) and system_prompt.strip() else DEFAULT_SYSTEM_PROMPT
    if "services_description" in payload_data:
        services_description = payload_data["services_description"]
        settings_row.services_description = (
            services_description.strip()
            if isinstance(services_description, str) and services_description.strip()
            else ""
        )
    if "enabled" in payload_data and payload_data["enabled"] is not None:
        settings_row.enabled = bool(payload_data["enabled"])
    if "auto_apply_tags_enabled" in payload_data and payload_data["auto_apply_tags_enabled"] is not None:
        settings_row.auto_apply_tags_enabled = bool(payload_data["auto_apply_tags_enabled"])

    db.commit()
    db.refresh(settings_row)
    return settings_row


@app.get("/api/whatsapp/portfolio", response_model=list[WhatsAppPortfolioItemRead])
def list_whatsapp_portfolio(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[WhatsAppPortfolioItem]:
    _ = username
    return list(db.scalars(select(WhatsAppPortfolioItem).order_by(desc(WhatsAppPortfolioItem.created_at))).all())


@app.post("/api/whatsapp/portfolio", response_model=WhatsAppPortfolioItemRead)
def create_whatsapp_portfolio_item(
    payload: WhatsAppPortfolioItemCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppPortfolioItem:
    _ = username
    normalized_url = normalize_site_url(payload.url)
    if not normalized_url:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="URL de portfólio inválida")

    item = WhatsAppPortfolioItem(description=payload.description.strip(), url=normalized_url)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/whatsapp/portfolio/{item_id}")
def delete_whatsapp_portfolio_item(
    item_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    item = db.get(WhatsAppPortfolioItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item de portfólio não encontrado")

    db.delete(item)
    db.commit()
    return {"status": "ok"}


@app.get("/api/crm/funnels", response_model=list[CrmFunnelRead])
def list_crm_funnels(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[CrmFunnelRead]:
    _ = username
    get_default_crm_funnel(db)
    db.commit()
    funnels = list(
        db.scalars(
            select(CrmFunnel)
            .options(selectinload(CrmFunnel.stages))
            .order_by(desc(CrmFunnel.is_default), func.lower(CrmFunnel.name), CrmFunnel.id)
        ).all()
    )
    return [_funnel_read(db, funnel) for funnel in funnels]


@app.post("/api/crm/funnels", response_model=CrmFunnelRead)
def create_crm_funnel(
    payload: CrmFunnelCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> CrmFunnelRead:
    _ = username
    get_default_crm_funnel(db)
    if _find_funnel_by_name(db, payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um funil com esse nome.")

    funnel = CrmFunnel(name=payload.name, description=payload.description, is_default=False)
    db.add(funnel)
    db.flush()
    db.add(
        CrmFunnelStage(
            funnel_id=funnel.id,
            key="new",
            label="Novo",
            color="#f3f4f6",
            description="Lead recém-chegado, ainda sem resposta ou qualificação.",
            position=0,
            is_won=False,
            is_lost=False,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um funil com esse nome.") from None
    db.refresh(funnel)
    return _funnel_read(db, funnel)


@app.patch("/api/crm/funnels/{funnel_id}", response_model=CrmFunnelRead)
def update_crm_funnel(
    funnel_id: int,
    payload: CrmFunnelUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> CrmFunnelRead:
    _ = username
    funnel = db.scalar(select(CrmFunnel).options(selectinload(CrmFunnel.stages)).where(CrmFunnel.id == funnel_id))
    if not funnel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado")

    payload_data = payload.model_dump(exclude_unset=True)
    if "name" in payload_data and payload_data["name"] is not None:
        if _find_funnel_by_name(db, payload_data["name"], exclude_id=funnel.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um funil com esse nome.")
        funnel.name = payload_data["name"]
    if "description" in payload_data:
        funnel.description = payload_data["description"]

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um funil com esse nome.") from None
    db.refresh(funnel)
    return _funnel_read(db, funnel)


@app.delete("/api/crm/funnels/{funnel_id}")
def delete_crm_funnel(
    funnel_id: int,
    move_to_funnel_id: int | None = None,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, int | str]:
    _ = username
    funnel = db.scalar(select(CrmFunnel).options(selectinload(CrmFunnel.stages)).where(CrmFunnel.id == funnel_id))
    if not funnel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado")
    if funnel.is_default:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O funil padrão não pode ser excluído.")

    affected_cards = _funnel_card_count(db, funnel.id)
    if affected_cards and not move_to_funnel_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Este funil contém {affected_cards} cards. Informe um funil de destino para movê-los antes de excluir.",
        )

    moved_cards = 0
    if affected_cards:
        if move_to_funnel_id == funnel.id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Escolha um funil de destino diferente.")
        destination = db.scalar(
            select(CrmFunnel).options(selectinload(CrmFunnel.stages)).where(CrmFunnel.id == move_to_funnel_id)
        )
        if not destination:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil de destino não encontrado")
        destination_stages = _sorted_funnel_stages(destination.stages)
        if not destination_stages:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Funil de destino sem estágios.")

        source_cards = list(db.scalars(select(CrmLead).where(CrmLead.funnel_id == funnel.id)).all())
        existing_destination_leads = set(
            db.scalars(select(CrmLead.lead_id).where(CrmLead.funnel_id == destination.id)).all()
        )
        conflicting_leads = [card.lead_id for card in source_cards if card.lead_id in existing_destination_leads]
        if conflicting_leads:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{len(conflicting_leads)} leads já têm card no funil de destino. Resolva esses cards antes de mover.",
            )

        for card in source_cards:
            matching_stage = _find_stage_by_key(db, destination.id, card.stage)
            next_stage = matching_stage or destination_stages[0]
            previous_stage = card.stage
            previous_stage_id = card.stage_id
            card.funnel_id = destination.id
            card.stage_id = next_stage.id
            card.stage = next_stage.key
            db.add(
                CrmStageHistory(
                    crm_lead_id=card.id,
                    from_stage=previous_stage,
                    to_stage=next_stage.key,
                    from_stage_id=previous_stage_id,
                    to_stage_id=next_stage.id,
                    changed_by="manual",
                )
            )
            moved_cards += 1
        for stage in destination_stages:
            matching_cards = list(
                db.scalars(select(CrmLead).where(CrmLead.funnel_id == destination.id, CrmLead.stage_id == stage.id)).all()
            )
            for index, card in enumerate(sorted(matching_cards, key=lambda item: (item.position is None, item.position or 0, item.id))):
                card.position = index

    db.delete(funnel)
    db.commit()
    return {"status": "ok", "moved_cards": moved_cards}


@app.get("/api/crm/funnels/{funnel_id}/stages", response_model=list[CrmFunnelStageRead])
def list_crm_funnel_stages(
    funnel_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[CrmFunnelStageRead]:
    _ = username
    funnel = db.scalar(select(CrmFunnel).options(selectinload(CrmFunnel.stages)).where(CrmFunnel.id == funnel_id))
    if not funnel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado")
    stage_counts = _stage_card_counts(db, funnel.id)
    return [_stage_read(stage, stage_counts.get(stage.id, 0)) for stage in _sorted_funnel_stages(funnel.stages)]


@app.post("/api/crm/funnels/{funnel_id}/stages", response_model=CrmFunnelStageRead)
def create_crm_funnel_stage(
    funnel_id: int,
    payload: CrmFunnelStageCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> CrmFunnelStageRead:
    _ = username
    funnel = db.scalar(select(CrmFunnel).options(selectinload(CrmFunnel.stages)).where(CrmFunnel.id == funnel_id))
    if not funnel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado")
    if payload.is_won and payload.is_lost:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Um estágio não pode ser ganho e perdido ao mesmo tempo.")

    key = payload.key or _next_stage_key(db, funnel.id, payload.label)
    if _find_stage_by_key(db, funnel.id, key):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um estágio com essa chave neste funil.")

    position = len(funnel.stages)
    stage = CrmFunnelStage(
        funnel_id=funnel.id,
        key=key,
        label=payload.label,
        color=payload.color,
        description=payload.description,
        position=position,
        is_won=payload.is_won,
        is_lost=payload.is_lost,
    )
    db.add(stage)
    db.flush()
    if stage.is_won:
        db.execute(
            CrmFunnelStage.__table__.update()
            .where(CrmFunnelStage.funnel_id == funnel.id, CrmFunnelStage.id != stage.id)
            .values(is_won=False)
        )
    if stage.is_lost:
        db.execute(
            CrmFunnelStage.__table__.update()
            .where(CrmFunnelStage.funnel_id == funnel.id, CrmFunnelStage.id != stage.id)
            .values(is_lost=False)
        )
    db.commit()
    db.refresh(stage)
    return _stage_read(stage, 0)


@app.patch("/api/crm/funnels/{funnel_id}/stages", response_model=list[CrmFunnelStageRead])
def reorder_crm_funnel_stages(
    funnel_id: int,
    payload: CrmFunnelStageReorderRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[CrmFunnelStageRead]:
    _ = username
    funnel = db.scalar(select(CrmFunnel).options(selectinload(CrmFunnel.stages)).where(CrmFunnel.id == funnel_id))
    if not funnel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado")
    current_stage_ids = {stage.id for stage in funnel.stages}
    next_stage_ids = list(dict.fromkeys(payload.stage_ids))
    if set(next_stage_ids) != current_stage_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Envie todos os estágios do funil na nova ordem.")

    normalize_funnel_stage_positions(db, funnel.id, next_stage_ids)
    db.commit()
    db.refresh(funnel)
    stage_counts = _stage_card_counts(db, funnel.id)
    return [_stage_read(stage, stage_counts.get(stage.id, 0)) for stage in _sorted_funnel_stages(funnel.stages)]


@app.patch("/api/crm/funnels/{funnel_id}/stages/{stage_id}", response_model=CrmFunnelStageRead)
def update_crm_funnel_stage(
    funnel_id: int,
    stage_id: int,
    payload: CrmFunnelStageUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> CrmFunnelStageRead:
    _ = username
    funnel = db.scalar(select(CrmFunnel).options(selectinload(CrmFunnel.stages)).where(CrmFunnel.id == funnel_id))
    stage = db.get(CrmFunnelStage, stage_id)
    if not funnel or not stage or stage.funnel_id != funnel.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estágio não encontrado")

    payload_data = payload.model_dump(exclude_unset=True)
    next_key = payload_data.get("key")
    if next_key and next_key != stage.key:
        if funnel.is_default and stage.key in CRM_STAGES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="As chaves do funil padrão não podem ser alteradas.")
        if _find_stage_by_key(db, funnel.id, next_key, exclude_id=stage.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um estágio com essa chave neste funil.")
        stage.key = next_key
    if "label" in payload_data and payload_data["label"] is not None:
        stage.label = payload_data["label"]
    if "color" in payload_data and payload_data["color"] is not None:
        stage.color = payload_data["color"]
    if "description" in payload_data:
        stage.description = payload_data["description"]
    if "position" in payload_data and payload_data["position"] is not None:
        stage.position = payload_data["position"]
    if "is_won" in payload_data and payload_data["is_won"] is not None:
        stage.is_won = payload_data["is_won"]
    if "is_lost" in payload_data and payload_data["is_lost"] is not None:
        stage.is_lost = payload_data["is_lost"]
    if stage.is_won and stage.is_lost:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Um estágio não pode ser ganho e perdido ao mesmo tempo.")

    db.flush()
    if stage.is_won:
        db.execute(
            CrmFunnelStage.__table__.update()
            .where(CrmFunnelStage.funnel_id == funnel.id, CrmFunnelStage.id != stage.id)
            .values(is_won=False)
        )
    if stage.is_lost:
        db.execute(
            CrmFunnelStage.__table__.update()
            .where(CrmFunnelStage.funnel_id == funnel.id, CrmFunnelStage.id != stage.id)
            .values(is_lost=False)
        )
    db.execute(CrmLead.__table__.update().where(CrmLead.stage_id == stage.id).values(stage=stage.key))
    db.commit()
    db.refresh(stage)
    return _stage_read(stage, _stage_card_counts(db, funnel.id).get(stage.id, 0))


@app.delete("/api/crm/funnels/{funnel_id}/stages/{stage_id}")
def delete_crm_funnel_stage(
    funnel_id: int,
    stage_id: int,
    move_to_stage_id: int | None = None,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, int | str]:
    _ = username
    funnel = db.scalar(select(CrmFunnel).options(selectinload(CrmFunnel.stages)).where(CrmFunnel.id == funnel_id))
    stage = db.get(CrmFunnelStage, stage_id)
    if not funnel or not stage or stage.funnel_id != funnel.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estágio não encontrado")
    if len(funnel.stages) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Todo funil precisa ter pelo menos um estágio.")

    affected_cards = int(db.scalar(select(func.count(CrmLead.id)).where(CrmLead.stage_id == stage.id)) or 0)
    if affected_cards and not move_to_stage_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Este estágio contém {affected_cards} cards. Informe um estágio de destino para movê-los antes de excluir.",
        )

    moved_cards = 0
    destination = None
    if affected_cards:
        if move_to_stage_id == stage.id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Escolha um estágio de destino diferente.")
        destination = db.get(CrmFunnelStage, move_to_stage_id)
        if not destination or destination.funnel_id != funnel.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estágio de destino não encontrado")
        cards = list(db.scalars(select(CrmLead).where(CrmLead.stage_id == stage.id)).all())
        for card in cards:
            card.stage_id = destination.id
            card.stage = destination.key
            db.add(
                CrmStageHistory(
                    crm_lead_id=card.id,
                    from_stage=stage.key,
                    to_stage=destination.key,
                    from_stage_id=stage.id,
                    to_stage_id=destination.id,
                    changed_by="manual",
                )
            )
            moved_cards += 1

    db.delete(stage)
    db.flush()
    remaining_stage_ids = [item.id for item in _sorted_funnel_stages([item for item in funnel.stages if item.id != stage.id])]
    normalize_funnel_stage_positions(db, funnel.id, remaining_stage_ids)
    if destination:
        matching_cards = list(db.scalars(select(CrmLead).where(CrmLead.funnel_id == funnel.id, CrmLead.stage_id == destination.id)).all())
        for index, card in enumerate(sorted(matching_cards, key=lambda item: (item.position is None, item.position or 0, item.id))):
            card.position = index
    db.commit()
    return {"status": "ok", "moved_cards": moved_cards}


@app.get("/api/crm/leads", response_model=list[CrmLeadRead])
def list_crm_leads(
    stage: str | None = None,
    funnel_id: int | None = None,
    tag_ids: list[int] | None = Query(default=None),
    tag_filter_mode: str = "any",
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[CrmLeadRead]:
    _ = username
    funnel = get_default_crm_funnel(db) if funnel_id is None else db.get(CrmFunnel, funnel_id)
    if not funnel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado")
    normalized_stage = (stage or "").strip()
    stage_ref = _find_stage_by_key(db, funnel.id, normalized_stage) if normalized_stage else None
    if normalized_stage and not stage_ref:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Estágio de CRM inválido para este funil")
    normalized_tag_filter_mode = (tag_filter_mode or "any").strip().lower()
    if normalized_tag_filter_mode not in {"any", "all"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Modo de filtro por tags inválido. Use 'any' ou 'all'.",
        )
    normalized_tag_ids = _unique_positive_ids(tag_ids)

    stmt = (
        select(CrmLead)
        .options(
            selectinload(CrmLead.funnel),
            selectinload(CrmLead.stage_ref),
            selectinload(CrmLead.lead).selectinload(Lead.search_run),
        )
        .where(CrmLead.funnel_id == funnel.id)
        .order_by(
            CrmLead.stage_id.asc(),
            CrmLead.position.is_(None),
            CrmLead.position.asc(),
            desc(CrmLead.updated_at),
            desc(CrmLead.id),
        )
    )
    if stage_ref:
        stmt = stmt.where(CrmLead.stage_id == stage_ref.id)
    if normalized_tag_ids:
        if normalized_tag_filter_mode == "all":
            matching_leads = (
                select(LeadTag.lead_id)
                .where(LeadTag.tag_id.in_(normalized_tag_ids))
                .group_by(LeadTag.lead_id)
                .having(func.count(func.distinct(LeadTag.tag_id)) == len(normalized_tag_ids))
            )
            stmt = stmt.where(CrmLead.lead_id.in_(matching_leads))
        else:
            stmt = stmt.where(CrmLead.lead_id.in_(select(LeadTag.lead_id).where(LeadTag.tag_id.in_(normalized_tag_ids))))

    crm_leads = list(db.scalars(stmt).all())
    tag_summaries_by_lead_id = _lead_tag_summaries_by_lead_id(db, [crm_lead.lead_id for crm_lead in crm_leads])
    return [_crm_lead_read(db, crm_lead, tag_summaries_by_lead_id) for crm_lead in crm_leads]


@app.patch("/api/crm/leads/{lead_id}", response_model=CrmLeadRead)
def update_crm_lead(
    lead_id: int,
    payload: CrmLeadUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> CrmLeadRead:
    _ = username
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado")

    payload_data = payload.model_dump(exclude_unset=True)
    funnel_id = payload_data.get("funnel_id")
    try:
        crm_lead = get_or_create_crm_lead(db, lead_id, funnel_id=funnel_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    should_move = ("stage" in payload_data and payload_data["stage"] is not None) or (
        "position" in payload_data and payload_data["position"] is not None
    )
    if should_move:
        next_stage = payload_data.get("stage")
        try:
            crm_lead = move_crm_lead(
                db,
                lead_id,
                stage=next_stage,
                position=payload_data.get("position"),
                changed_by="manual",
                funnel_id=crm_lead.funnel_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if "qualification_notes" in payload_data:
        notes = payload_data["qualification_notes"]
        crm_lead.qualification_notes = notes.strip() if isinstance(notes, str) and notes.strip() else None

    db.commit()
    crm_lead = db.scalar(
        select(CrmLead)
        .options(
            selectinload(CrmLead.funnel),
            selectinload(CrmLead.stage_ref),
            selectinload(CrmLead.lead).selectinload(Lead.search_run),
        )
        .where(CrmLead.id == crm_lead.id)
    )
    if not crm_lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead de CRM não encontrado")
    return _crm_lead_read(db, crm_lead)


@app.get("/api/whatsapp/templates", response_model=list[WhatsAppMessageTemplateRead])
def list_whatsapp_templates(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[WhatsAppMessageTemplate]:
    _ = username
    return list(db.scalars(select(WhatsAppMessageTemplate).order_by(desc(WhatsAppMessageTemplate.created_at))).all())


@app.post("/api/whatsapp/templates", response_model=WhatsAppMessageTemplateRead)
def create_whatsapp_template(
    payload: WhatsAppMessageTemplateCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppMessageTemplate:
    _ = username
    template = WhatsAppMessageTemplate(
        name=payload.name.strip(),
        content=payload.content.strip(),
    )
    db.add(template)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um template WhatsApp com esse nome") from None
    db.refresh(template)
    return template


@app.post("/api/whatsapp/templates/generate", response_model=WhatsAppTemplateGenerateResponse)
def generate_ai_whatsapp_template(
    payload: WhatsAppTemplateGenerateRequest,
    username: str = Depends(require_user),
) -> WhatsAppTemplateGenerateResponse:
    _ = username
    try:
        content = generate_whatsapp_template_content(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    return WhatsAppTemplateGenerateResponse(content=content)


@app.patch("/api/whatsapp/templates/{template_id}", response_model=WhatsAppMessageTemplateRead)
def update_whatsapp_template(
    template_id: int,
    payload: WhatsAppMessageTemplateUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppMessageTemplate:
    _ = username
    template = db.get(WhatsAppMessageTemplate, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template WhatsApp não encontrado")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value.strip() if isinstance(value, str) else value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um template WhatsApp com esse nome") from None
    db.refresh(template)
    return template


@app.delete("/api/whatsapp/templates/{template_id}")
def delete_whatsapp_template(
    template_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    template = db.get(WhatsAppMessageTemplate, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template WhatsApp não encontrado")

    db.delete(template)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Template WhatsApp em uso por campanha") from None
    return {"status": "ok"}


@app.get("/api/whatsapp/campaigns", response_model=list[WhatsAppCampaignRead])
def list_whatsapp_campaigns(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[WhatsAppCampaign]:
    _ = username
    stmt = (
        select(WhatsAppCampaign)
        .options(
            selectinload(WhatsAppCampaign.lead_list),
            selectinload(WhatsAppCampaign.instance),
            selectinload(WhatsAppCampaign.funnel),
        )
        .order_by(desc(WhatsAppCampaign.created_at))
    )
    return list(db.scalars(stmt).all())


@app.post("/api/whatsapp/campaigns", response_model=WhatsAppCampaignRead)
def create_whatsapp_campaign(
    payload: WhatsAppCampaignCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppCampaign:
    _ = username
    if payload.min_delay_seconds > payload.max_delay_seconds:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Delay mínimo maior que o máximo")
    if not db.get(LeadList, payload.list_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista não encontrada")
    if not db.get(WhatsAppInstance, payload.instance_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instância de WhatsApp não encontrada")
    if payload.funnel_id is not None and not db.get(CrmFunnel, payload.funnel_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado")

    if payload.message_mode == "ai_per_lead" and not (payload.objective or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o objetivo da campanha para gerar mensagens individuais com IA",
        )

    template_ids = [item.template_id for item in payload.templates]
    if payload.message_mode == "template":
        if not template_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Escolha um template de mensagem")

        templates_found = db.scalar(
            select(func.count(WhatsAppMessageTemplate.id)).where(WhatsAppMessageTemplate.id.in_(template_ids))
        ) or 0
        if templates_found != len(set(template_ids)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Um ou mais templates não foram encontrados")

    data = payload.model_dump(exclude={"templates"})
    data["objective"] = (data.get("objective") or "").strip()
    campaign = WhatsAppCampaign(**data, status="draft", message="Campanha criada.")
    db.add(campaign)
    db.flush()

    if payload.message_mode == "template":
        for item in payload.templates:
            db.add(WhatsAppCampaignTemplate(campaign_id=campaign.id, template_id=item.template_id, weight=item.weight))

    db.commit()
    db.refresh(campaign)
    return campaign


@app.patch("/api/whatsapp/campaigns/{campaign_id}", response_model=WhatsAppCampaignRead)
def update_whatsapp_campaign(
    campaign_id: int,
    payload: WhatsAppCampaignUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppCampaign:
    _ = username
    campaign = db.get(WhatsAppCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada")
    if campaign.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pause a campanha antes de editar")
    if payload.min_delay_seconds > payload.max_delay_seconds:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Delay mínimo maior que o máximo")
    if not db.get(LeadList, payload.list_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista não encontrada")
    if not db.get(WhatsAppInstance, payload.instance_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instância de WhatsApp não encontrada")
    if payload.funnel_id is not None and not db.get(CrmFunnel, payload.funnel_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado")

    objective = (payload.objective or "").strip()
    if payload.message_mode == "ai_per_lead" and not objective:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o objetivo da campanha para gerar mensagens individuais com IA",
        )

    template_ids = [item.template_id for item in payload.templates]
    if payload.message_mode == "template":
        if not template_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Escolha um template de mensagem")

        templates_found = db.scalar(
            select(func.count(WhatsAppMessageTemplate.id)).where(WhatsAppMessageTemplate.id.in_(template_ids))
        ) or 0
        if templates_found != len(set(template_ids)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Um ou mais templates não foram encontrados")

    existing_sends = db.scalar(select(func.count(WhatsAppSend.id)).where(WhatsAppSend.campaign_id == campaign.id)) or 0
    current_template_ids = {item.template_id for item in campaign.templates}
    next_template_ids = set(template_ids)
    if existing_sends and (
        campaign.list_id != payload.list_id
        or campaign.funnel_id != payload.funnel_id
        or current_template_ids != next_template_ids
        or campaign.message_mode != payload.message_mode
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Campanha com fila criada não pode trocar lista, funil, templates ou modo de mensagem. Crie uma nova campanha para alterar a audiência.",
        )

    data = payload.model_dump(exclude={"templates"})
    data["objective"] = objective
    for field, value in data.items():
        setattr(campaign, field, value.strip() if isinstance(value, str) else value)

    if not existing_sends:
        db.execute(delete(WhatsAppCampaignTemplate).where(WhatsAppCampaignTemplate.campaign_id == campaign.id))
        if payload.message_mode == "template":
            for item in payload.templates:
                db.add(WhatsAppCampaignTemplate(campaign_id=campaign.id, template_id=item.template_id, weight=item.weight))

    campaign.message = "Campanha atualizada."
    campaign.error = None
    db.commit()
    db.refresh(campaign)
    return campaign


@app.post("/api/whatsapp/campaigns/{campaign_id}/start", response_model=WhatsAppCampaignRead)
def start_whatsapp_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppCampaign:
    _ = username
    campaign = db.get(WhatsAppCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada")
    if campaign.status not in ("draft", "paused"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta campanha não pode ser iniciada")

    instance = db.get(WhatsAppInstance, campaign.instance_id)
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instância de WhatsApp não encontrada")
    if instance.status != "connected":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conecte a instância antes de iniciar a campanha")

    campaign.status = "running"
    campaign.message = "Campanha iniciada."
    campaign.error = None
    campaign.finished_at = None
    db.commit()
    submit_whatsapp_campaign_job(campaign.id)
    db.refresh(campaign)
    return campaign


@app.post("/api/whatsapp/campaigns/{campaign_id}/pause", response_model=WhatsAppCampaignRead)
def pause_whatsapp_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> WhatsAppCampaign:
    _ = username
    campaign = db.get(WhatsAppCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada")
    if campaign.status != "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta campanha não está rodando")

    campaign.status = "paused"
    campaign.message = "Campanha pausada."
    db.commit()
    db.refresh(campaign)
    return campaign


@app.delete("/api/whatsapp/campaigns/{campaign_id}")
def delete_whatsapp_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    campaign = db.get(WhatsAppCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada")
    if campaign.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pause a campanha antes de excluir")

    db.execute(delete(WhatsAppSend).where(WhatsAppSend.campaign_id == campaign.id))
    db.delete(campaign)
    db.commit()
    return {"status": "ok"}


@app.get("/api/email/smtp", response_model=SmtpConfigRead)
def read_smtp_config(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
):
    _ = username
    return get_or_create_smtp_config(db)


@app.put("/api/email/smtp", response_model=SmtpConfigRead)
def save_smtp_config(
    payload: SmtpConfigUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
):
    _ = username
    data = payload.model_dump()
    if data["use_ssl"] and data["use_tls"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Use SSL ou TLS, não ambos.")
    return update_smtp_config(db, data)


@app.post("/api/email/smtp/test")
def test_smtp_config(
    payload: SmtpTestRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    config = get_or_create_smtp_config(db)
    try:
        if payload.template_id:
            template = db.get(EmailTemplate, payload.template_id)
            if not template:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado")

            lead = SimpleNamespace(
                name="BrightFlow Plumbing",
                email=payload.to_email,
                website="https://example-service.com",
                phone="+1 205-555-0198",
                address="120 Main St, Birmingham, AL",
                niche="plumbing",
                location="Alabama",
            )
            campaign = SimpleNamespace(content_title=template.content_title, content_link=template.content_link)
            subject, rendered_html, rendered_text = render_email(template, lead, campaign)
            send_email(config, payload.to_email, f"[TEST] {subject}", rendered_html, rendered_text)
        else:
            send_test_email(config, payload.to_email)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    return {"status": "ok"}


@app.get("/api/email/content-preview", response_model=ContentPreviewRead)
def get_content_preview(
    url: str,
    username: str = Depends(require_user),
) -> ContentPreviewRead:
    _ = username
    try:
        preview = fetch_content_preview(url)
    except Exception:
        preview = fetch_content_preview("")
    return ContentPreviewRead(url=preview.url, title=preview.title, image_url=preview.image_url)


@app.get("/api/email/templates", response_model=list[EmailTemplateRead])
def list_email_templates(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[EmailTemplate]:
    _ = username
    return list(db.scalars(select(EmailTemplate).order_by(desc(EmailTemplate.created_at))).all())


@app.post("/api/email/templates", response_model=EmailTemplateRead)
def create_email_template(
    payload: EmailTemplateCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> EmailTemplate:
    _ = username
    template = EmailTemplate(**payload.model_dump())
    db.add(template)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um template com esse nome") from None
    db.refresh(template)
    return template


@app.post("/api/email/templates/ai-generate", response_model=AiTemplateGenerateResponse)
def generate_ai_email_templates(
    payload: AiTemplateGenerateRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> AiTemplateGenerateResponse:
    _ = username
    try:
        templates = generate_email_templates(db, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    return AiTemplateGenerateResponse(templates=templates)


@app.patch("/api/email/templates/{template_id}", response_model=EmailTemplateRead)
def update_email_template(
    template_id: int,
    payload: EmailTemplateUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> EmailTemplate:
    _ = username
    template = db.get(EmailTemplate, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value.strip() if isinstance(value, str) else value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um template com esse nome") from None
    db.refresh(template)
    return template


@app.delete("/api/email/templates/{template_id}")
def delete_email_template(
    template_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    template = db.get(EmailTemplate, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado")

    db.delete(template)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Template em uso por campanha") from None
    return {"status": "ok"}


def _with_lead_count(db: Session, lead_list: LeadList) -> LeadList:
    setattr(lead_list, "lead_count", count_leads_for_list(db, lead_list, lead_list.channel))
    return lead_list


@app.get("/api/email/lists", response_model=list[LeadListRead])
def list_lead_lists(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[LeadList]:
    _ = username
    lists = list(db.scalars(select(LeadList).order_by(desc(LeadList.created_at))).all())
    return [_with_lead_count(db, item) for item in lists]


@app.post("/api/email/lists", response_model=LeadListRead)
def create_lead_list(
    payload: LeadListCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadList:
    _ = username
    lead_list = LeadList(**payload.model_dump())
    db.add(lead_list)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma lista com esse nome") from None
    db.refresh(lead_list)
    return _with_lead_count(db, lead_list)


@app.patch("/api/email/lists/{list_id}", response_model=LeadListRead)
def update_lead_list(
    list_id: int,
    payload: LeadListUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadList:
    _ = username
    lead_list = db.get(LeadList, list_id)
    if not lead_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista não encontrada")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lead_list, field, value.strip() if isinstance(value, str) else value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma lista com esse nome") from None
    db.refresh(lead_list)
    return _with_lead_count(db, lead_list)


@app.delete("/api/email/lists/{list_id}")
def delete_lead_list(
    list_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    lead_list = db.get(LeadList, list_id)
    if not lead_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista não encontrada")

    db.delete(lead_list)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lista em uso por campanha") from None
    return {"status": "ok"}


@app.get("/api/email/campaigns", response_model=list[EmailCampaignRead])
def list_email_campaigns(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[EmailCampaign]:
    _ = username
    stmt = select(EmailCampaign).options(selectinload(EmailCampaign.lead_list)).order_by(desc(EmailCampaign.created_at))
    return list(db.scalars(stmt).all())


@app.post("/api/email/campaigns", response_model=EmailCampaignRead)
def create_email_campaign(
    payload: EmailCampaignCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> EmailCampaign:
    _ = username
    if payload.min_delay_seconds > payload.max_delay_seconds:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Delay mínimo maior que o máximo")
    objective = (payload.objective or "").strip()
    if payload.message_mode == "ai_per_lead" and not objective:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o objetivo para gerar e-mails individuais com IA",
        )
    if not db.get(LeadList, payload.list_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista não encontrada")

    template_ids = [item.template_id for item in payload.templates]
    templates_found = db.scalar(select(func.count(EmailTemplate.id)).where(EmailTemplate.id.in_(template_ids))) or 0
    if templates_found != len(set(template_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Um ou mais templates não foram encontrados")

    data = payload.model_dump(exclude={"templates"})
    data["objective"] = objective
    campaign = EmailCampaign(**data, status="draft", message="Campanha criada.")
    db.add(campaign)
    db.flush()

    for item in payload.templates:
        db.add(EmailCampaignTemplate(campaign_id=campaign.id, template_id=item.template_id, weight=item.weight))

    db.commit()
    db.refresh(campaign)
    return campaign


@app.patch("/api/email/campaigns/{campaign_id}", response_model=EmailCampaignRead)
def update_email_campaign(
    campaign_id: int,
    payload: EmailCampaignUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> EmailCampaign:
    _ = username
    campaign = db.get(EmailCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada")
    if campaign.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pause a campanha antes de editar")
    if payload.min_delay_seconds > payload.max_delay_seconds:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Delay mínimo maior que o máximo")
    objective = (payload.objective or "").strip()
    if payload.message_mode == "ai_per_lead" and not objective:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o objetivo para gerar e-mails individuais com IA",
        )
    if not db.get(LeadList, payload.list_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista não encontrada")

    template_ids = [item.template_id for item in payload.templates]
    templates_found = db.scalar(select(func.count(EmailTemplate.id)).where(EmailTemplate.id.in_(template_ids))) or 0
    if templates_found != len(set(template_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Um ou mais templates não foram encontrados")

    existing_sends = db.scalar(select(func.count(EmailSend.id)).where(EmailSend.campaign_id == campaign.id)) or 0
    current_template_ids = {item.template_id for item in campaign.templates}
    next_template_ids = set(template_ids)
    if existing_sends and (
        campaign.list_id != payload.list_id
        or current_template_ids != next_template_ids
        or campaign.message_mode != payload.message_mode
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Campanha com fila criada não pode trocar lista, templates ou modo de mensagem. Crie uma nova campanha para alterar a audiência.",
        )

    data = payload.model_dump(exclude={"templates"})
    data["objective"] = objective
    for field, value in data.items():
        setattr(campaign, field, value.strip() if isinstance(value, str) else value)

    if not existing_sends:
        db.execute(delete(EmailCampaignTemplate).where(EmailCampaignTemplate.campaign_id == campaign.id))
        for item in payload.templates:
            db.add(EmailCampaignTemplate(campaign_id=campaign.id, template_id=item.template_id, weight=item.weight))

    campaign.message = "Campanha atualizada."
    campaign.error = None
    db.commit()
    db.refresh(campaign)
    return campaign


@app.post("/api/email/campaigns/{campaign_id}/start", response_model=EmailCampaignRead)
def start_email_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> EmailCampaign:
    _ = username
    campaign = db.get(EmailCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada")
    if campaign.status not in ("draft", "paused"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta campanha não pode ser iniciada")

    campaign.status = "running"
    campaign.message = "Campanha iniciada."
    campaign.error = None
    campaign.finished_at = None
    db.commit()
    submit_email_campaign_job(campaign.id)
    db.refresh(campaign)
    return campaign


@app.post("/api/email/campaigns/{campaign_id}/pause", response_model=EmailCampaignRead)
def pause_email_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> EmailCampaign:
    _ = username
    campaign = db.get(EmailCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada")
    if campaign.status != "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta campanha não está rodando")

    campaign.status = "paused"
    campaign.message = "Campanha pausada."
    db.commit()
    db.refresh(campaign)
    return campaign


@app.delete("/api/email/campaigns/{campaign_id}")
def delete_email_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> dict[str, str]:
    _ = username
    campaign = db.get(EmailCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada")
    if campaign.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pause a campanha antes de excluir")

    db.execute(delete(EmailSend).where(EmailSend.campaign_id == campaign.id))
    db.execute(delete(EmailCampaignTemplate).where(EmailCampaignTemplate.campaign_id == campaign.id))
    db.delete(campaign)
    db.commit()
    return {"status": "ok"}


@app.get("/api/email/sends", response_model=list[EmailSendRead])
def list_email_sends(
    campaign_id: int | None = None,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[EmailSend]:
    _ = username
    stmt = (
        select(EmailSend)
        .options(selectinload(EmailSend.campaign), selectinload(EmailSend.lead), selectinload(EmailSend.template))
        .order_by(desc(EmailSend.created_at))
        .limit(300)
    )
    if campaign_id:
        stmt = stmt.where(EmailSend.campaign_id == campaign_id)
    return list(db.scalars(stmt).all())


@app.get("/api/stats", response_model=StatsRead)
def stats(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> StatsRead:
    _ = username
    total_leads = db.scalar(select(func.count(Lead.id))) or 0
    total_with_email = db.scalar(select(func.count(Lead.id)).where(Lead.email != "")) or 0
    running_jobs = db.scalar(select(func.count(SearchRun.id)).where(SearchRun.status.in_(("queued", "running")))) or 0
    completed_jobs = db.scalar(select(func.count(SearchRun.id)).where(SearchRun.status == "completed")) or 0
    return StatsRead(
        total_leads=total_leads,
        total_with_email=total_with_email,
        running_jobs=running_jobs,
        completed_jobs=completed_jobs,
    )


@app.get("/api/leads/export.csv")
def export_leads(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> StreamingResponse:
    _ = username
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nicho", "Localidade", "Nome", "Endereço", "Telefone", "Site", "Email", "Insights do site"])

    stmt = select(Lead).options(selectinload(Lead.search_run)).order_by(desc(Lead.created_at))
    for lead in db.scalars(stmt).all():
        writer.writerow([
            lead.niche,
            lead.location,
            lead.name,
            lead.address,
            lead.phone,
            lead.website or "",
            lead.email,
            lead.site_insights or "",
        ])

    output.seek(0)
    headers = {"Content-Disposition": "attachment; filename=leads.csv"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)
