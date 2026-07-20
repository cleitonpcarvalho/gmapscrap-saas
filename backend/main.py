import base64
import csv
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace

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
    EmailCampaign,
    EmailCampaignTemplate,
    EmailSend,
    EmailTemplate,
    Lead,
    LeadList,
    SearchRun,
)
from backend.schemas import (
    AiTemplateGenerateRequest,
    AiTemplateGenerateResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    ContentPreviewRead,
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
)
from backend.scrapers.email_scraper import normalize_site_url
from backend.services.content_preview import fetch_content_preview
from backend.services.email_campaigns import (
    count_leads_for_list,
    mark_clicked,
    mark_opened,
    render_email,
    resume_running_campaigns,
    start_campaign_scheduler,
    submit_campaign_job,
)
from backend.services.email_delivery import get_or_create_smtp_config, send_email, send_test_email, update_smtp_config
from backend.services.email_validation import validate_email_address
from backend.services.ai_templates import generate_email_templates
from backend.services.jobs import (
    create_search_run,
    resume_unfinished_search_runs,
    save_enriched_lead,
    save_scraped_lead,
    submit_search_job,
)
from backend.services.whatsapp_validation import is_whatsapp_validation_configured
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
    resume_running_campaigns()
    start_campaign_scheduler()


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
    submit_campaign_job(campaign.id)
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
    writer.writerow(["Nicho", "Localidade", "Nome", "Endereço", "Telefone", "Site", "Email"])

    stmt = select(Lead).options(selectinload(Lead.search_run)).order_by(desc(Lead.created_at))
    for lead in db.scalars(stmt).all():
        writer.writerow([lead.niche, lead.location, lead.name, lead.address, lead.phone, lead.website or "", lead.email])

    output.seek(0)
    headers = {"Content-Disposition": "attachment; filename=leads.csv"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)
