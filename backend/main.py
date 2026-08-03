import base64
import csv
import secrets
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.auth import clear_session_cookie, create_session_token, get_current_username, set_session_cookie
from backend.config import get_settings
from backend.database import get_db, init_db
from backend.models import (
    CrmLead,
    EmailCampaign,
    EmailCampaignTemplate,
    EmailSend,
    EmailTemplate,
    Lead,
    LeadList,
    SearchRun,
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
    LeadSiteInsightsEnrichmentResponse,
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
    UserRead,
    WhatsAppCampaignCreate,
    WhatsAppCampaignRead,
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
from backend.services.crm import CRM_STAGES, get_or_create_crm_lead, update_crm_stage
from backend.services.content_preview import fetch_content_preview
from backend.services.email_campaigns import (
    count_leads_for_list,
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
from backend.services.whatsapp_validation import is_whatsapp_validation_configured
from backend.services.whatsapp_ai_agent import DEFAULT_SYSTEM_PROMPT, get_or_create_ai_settings
from backend.services.whatsapp_campaigns import (
    resume_running_campaigns as resume_running_whatsapp_campaigns,
    start_campaign_scheduler as start_whatsapp_campaign_scheduler,
    submit_campaign_job as submit_whatsapp_campaign_job,
)
from backend.services.whatsapp_providers.evolution import EvolutionApiError, EvolutionProvider
from backend.services.whatsapp_webhooks import ingest_evolution_messages_upsert, is_evolution_messages_upsert_event
from backend.scrapers.maps_scraper import MapLead


settings = get_settings()
app = FastAPI(title="GmapScrap Web", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    resume_unfinished_search_runs()
    resume_running_email_campaigns()
    start_email_campaign_scheduler()
    resume_running_whatsapp_campaigns()
    start_whatsapp_campaign_scheduler()


def require_user(request: Request) -> str:
    return get_current_username(request)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_whatsapp_validation_available(validate_whatsapp: bool) -> None:
    if validate_whatsapp and not is_whatsapp_validation_configured():
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
    configured_secret = get_settings().evolution_webhook_secret.strip()
    if configured_secret:
        return configured_secret

    settings_row = db.get(WhatsAppWebhookSettings, 1)
    if settings_row:
        return settings_row.secret

    settings_row = WhatsAppWebhookSettings(id=1, secret=secrets.token_urlsafe(48))
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


def _crm_lead_read(db: Session, crm_lead: CrmLead) -> CrmLeadRead:
    lead = crm_lead.lead
    conversation, latest_message = _latest_whatsapp_context_for_lead(db, crm_lead.lead_id)

    return CrmLeadRead(
        id=crm_lead.id,
        lead_id=crm_lead.lead_id,
        stage=crm_lead.stage,
        qualification_notes=crm_lead.qualification_notes,
        score=crm_lead.score,
        updated_at=crm_lead.updated_at,
        lead_name=lead.name if lead else "",
        phone=lead.phone if lead else None,
        website=lead.website if lead else None,
        email=lead.email if lead else "",
        niche=lead.search_run.niche if lead and lead.search_run else "",
        location=lead.search_run.location if lead and lead.search_run else "",
        last_message=latest_message.content if latest_message else None,
        last_message_at=conversation.last_message_at if conversation else None,
        conversation_id=conversation.id if conversation else None,
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
    ensure_whatsapp_validation_available(payload.validate_whatsapp)
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
    ensure_whatsapp_validation_available(payload.validate_whatsapp)
    run = SearchRun(
        niche=payload.niche.strip(),
        location=payload.location.strip(),
        target_quantity=None if payload.max_results else payload.quantity,
        max_results=payload.max_results,
        skip_without_website=payload.skip_without_website,
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
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[Lead]:
    _ = username
    stmt = select(Lead).options(selectinload(Lead.search_run)).join(SearchRun).order_by(desc(Lead.created_at)).limit(500)

    if run_id:
        stmt = stmt.where(Lead.run_id == run_id)

    if niche:
        stmt = stmt.where(SearchRun.niche.ilike(f"%{niche.strip()}%"))

    if location:
        stmt = stmt.where(SearchRun.location.ilike(f"%{location.strip()}%"))

    return list(db.scalars(stmt).all())


@app.post("/api/leads/enrich-site-insights", response_model=LeadSiteInsightsEnrichmentResponse)
def enrich_existing_leads_site_insights(
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> LeadSiteInsightsEnrichmentResponse:
    _ = username
    eligible_ids = eligible_retroactive_site_insights_lead_ids(db)
    queued_count = submit_retroactive_site_insights_jobs(eligible_ids)
    status_value = "processing_started" if queued_count else "no_eligible_leads"
    return LeadSiteInsightsEnrichmentResponse(
        status=status_value,
        eligible_count=len(eligible_ids),
        queued_count=queued_count,
        location_inference=BRAZIL_LOCATION_INFERENCE,
    )


@app.post("/api/leads", response_model=LeadRead)
def create_manual_lead(
    payload: LeadCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> Lead:
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
    return lead


@app.patch("/api/leads/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> Lead:
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
    return lead


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


@app.get("/api/crm/leads", response_model=list[CrmLeadRead])
def list_crm_leads(
    stage: str | None = None,
    db: Session = Depends(get_db),
    username: str = Depends(require_user),
) -> list[CrmLeadRead]:
    _ = username
    normalized_stage = (stage or "").strip()
    if normalized_stage and normalized_stage not in CRM_STAGES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Estágio de CRM inválido")

    stmt = select(CrmLead).options(selectinload(CrmLead.lead).selectinload(Lead.search_run)).order_by(
        desc(CrmLead.updated_at),
        desc(CrmLead.id),
    )
    if normalized_stage:
        stmt = stmt.where(CrmLead.stage == normalized_stage)

    crm_leads = list(db.scalars(stmt).all())
    return [_crm_lead_read(db, crm_lead) for crm_lead in crm_leads]


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

    crm_lead = get_or_create_crm_lead(db, lead_id)
    payload_data = payload.model_dump(exclude_unset=True)

    if "stage" in payload_data and payload_data["stage"] is not None:
        next_stage = payload_data["stage"]
        if next_stage not in CRM_STAGES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Estágio de CRM inválido")
        crm_lead = update_crm_stage(db, lead_id, next_stage, changed_by="manual")

    if "qualification_notes" in payload_data:
        notes = payload_data["qualification_notes"]
        crm_lead.qualification_notes = notes.strip() if isinstance(notes, str) and notes.strip() else None

    db.commit()
    crm_lead = db.scalar(
        select(CrmLead)
        .options(selectinload(CrmLead.lead).selectinload(Lead.search_run))
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
        .options(selectinload(WhatsAppCampaign.lead_list), selectinload(WhatsAppCampaign.instance))
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
    setattr(lead_list, "lead_count", count_leads_for_list(db, lead_list))
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
    if not db.get(LeadList, payload.list_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista não encontrada")

    template_ids = [item.template_id for item in payload.templates]
    templates_found = db.scalar(select(func.count(EmailTemplate.id)).where(EmailTemplate.id.in_(template_ids))) or 0
    if templates_found != len(set(template_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Um ou mais templates não foram encontrados")

    data = payload.model_dump(exclude={"templates"})
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
    if not db.get(LeadList, payload.list_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lista não encontrada")

    template_ids = [item.template_id for item in payload.templates]
    templates_found = db.scalar(select(func.count(EmailTemplate.id)).where(EmailTemplate.id.in_(template_ids))) or 0
    if templates_found != len(set(template_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Um ou mais templates não foram encontrados")

    existing_sends = db.scalar(select(func.count(EmailSend.id)).where(EmailSend.campaign_id == campaign.id)) or 0
    current_template_ids = {item.template_id for item in campaign.templates}
    next_template_ids = set(template_ids)
    if existing_sends and (campaign.list_id != payload.list_id or current_template_ids != next_template_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Campanha com fila criada não pode trocar lista ou templates. Crie uma nova campanha para alterar a audiência.",
        )

    data = payload.model_dump(exclude={"templates"})
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
