from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
import re
import time

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from selenium.common.exceptions import TimeoutException, WebDriverException

from backend.database import SessionLocal
from backend.models import Lead, SearchRun
from backend.schemas import SearchCreate
from backend.scrapers.email_scraper import extract_email_from_site, normalize_site_url
from backend.scrapers.maps_scraper import MapLead, ScrapeEvent, scrape_google_maps
from backend.services.email_validation import validate_email_address
from backend.services.whatsapp_validation import validate_whatsapp_number


executor = ThreadPoolExecutor(max_workers=2)
_active_run_ids: set[int] = set()
_active_run_ids_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_search_run(db: Session, payload: SearchCreate) -> SearchRun:
    run = SearchRun(
        niche=payload.niche.strip(),
        location=payload.location.strip(),
        target_quantity=None if payload.max_results else payload.quantity,
        max_results=payload.max_results,
        skip_without_website=payload.skip_without_website,
        validate_whatsapp=payload.validate_whatsapp,
        status="queued",
        message="Busca na fila",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    submit_search_job(run.id)
    return run


def submit_search_job(run_id: int) -> bool:
    with _active_run_ids_lock:
        if run_id in _active_run_ids:
            return False

        _active_run_ids.add(run_id)

    executor.submit(_run_search_job_and_release, run_id)
    return True


def _run_search_job_and_release(run_id: int) -> None:
    try:
        run_search_job(run_id)
    finally:
        with _active_run_ids_lock:
            _active_run_ids.discard(run_id)


def resume_unfinished_search_runs() -> None:
    db = SessionLocal()

    try:
        run_ids = list(
            db.scalars(select(SearchRun.id).where(SearchRun.status.in_(("queued", "running")))).all()
        )
    finally:
        db.close()

    for run_id in run_ids:
        submit_search_job(run_id)


def _website_exists(db: Session, website: str) -> bool:
    normalized = normalize_site_url(website)
    if not normalized:
        return False

    stmt = select(func.count(Lead.id)).where(Lead.website == normalized)
    return bool(db.scalar(stmt))


def _lead_without_website_exists(db: Session, lead: MapLead) -> bool:
    no_website_filter = or_(Lead.website.is_(None), Lead.website == "")
    phone = (lead.phone or "").strip()

    if phone:
        stmt = select(func.count(Lead.id)).where(no_website_filter, Lead.phone == phone)
        if db.scalar(stmt):
            return True

    name = (lead.name or "").strip().lower()
    address = (lead.address or "").strip()
    if not name:
        return False

    stmt = select(func.count(Lead.id)).where(
        no_website_filter,
        func.lower(Lead.name) == name,
        Lead.address == address,
    )
    return bool(db.scalar(stmt))


def _skip_lead(db: Session, run: SearchRun, lead_name: str, reason: str) -> bool:
    run.skipped_count += 1
    run.message = f"{lead_name} ignorado: {reason}."
    db.commit()
    return False


def _validate_whatsapp_or_skip(db: Session, run: SearchRun, lead: MapLead) -> bool:
    if not run.validate_whatsapp:
        return True

    result = validate_whatsapp_number(lead.phone, lead.address)
    if result.is_valid:
        return True

    if result.reason == "bad_phone":
        reason = "telefone inválido ou ausente para WhatsApp"
    elif result.reason == "not_whatsapp":
        reason = "telefone não tem WhatsApp"
    elif result.reason == "whatsapp_validation_not_configured":
        reason = "validação de WhatsApp não configurada"
    else:
        reason = "WhatsApp não confirmado"

    _skip_lead(db, run, lead.name, reason)
    return False


def _save_row(db: Session, run: SearchRun, lead: MapLead, website: str | None, email: str) -> bool:
    row = Lead(
        run_id=run.id,
        name=lead.name,
        address=lead.address,
        phone=lead.phone,
        website=website or None,
        email=email,
    )
    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        run = db.get(SearchRun, run.id)
        if run:
            run.skipped_count += 1
            run.message = f"{lead.name} ignorado: lead duplicado."
            db.commit()
        return False

    db.refresh(row)
    return True


def _save_lead(db: Session, run: SearchRun, lead: MapLead) -> bool:
    raw_website = (lead.website or "").strip()
    website = normalize_site_url(raw_website) if raw_website else ""

    if raw_website and not website:
        return _skip_lead(db, run, lead.name, "site inválido")

    if not website:
        if run.skip_without_website:
            return _skip_lead(db, run, lead.name, "sem site")

        if not _validate_whatsapp_or_skip(db, run, lead):
            return False

        if _lead_without_website_exists(db, lead):
            return _skip_lead(db, run, lead.name, "lead sem site duplicado")

        return _save_row(db, run, lead, None, "")

    if _website_exists(db, website):
        return _skip_lead(db, run, lead.name, "site duplicado")

    if not _validate_whatsapp_or_skip(db, run, lead):
        return False

    try:
        email_result = extract_email_from_site(website)
    except Exception:
        return _skip_lead(db, run, lead.name, "erro ao buscar e-mail")

    if not email_result.email:
        return _skip_lead(db, run, lead.name, "e-mail não encontrado ou inválido")

    return _save_row(db, run, lead, website, email_result.email)


def save_enriched_lead(db: Session, run: SearchRun, lead: MapLead, email: str) -> bool:
    raw_website = (lead.website or "").strip()
    website = normalize_site_url(raw_website) if raw_website else ""

    if raw_website and not website:
        return _skip_lead(db, run, lead.name, "site inválido")

    if not website and run.skip_without_website:
        return _skip_lead(db, run, lead.name, "sem site")

    if _website_exists(db, website):
        return _skip_lead(db, run, lead.name, "site duplicado")

    if not website and _lead_without_website_exists(db, lead):
        return _skip_lead(db, run, lead.name, "lead sem site duplicado")

    if not _validate_whatsapp_or_skip(db, run, lead):
        return False

    clean_email = (email or "").strip().lower()
    if not clean_email:
        if website:
            return _skip_lead(db, run, lead.name, "e-mail não encontrado")
        return _save_row(db, run, lead, None, "")

    validation = validate_email_address(clean_email, website)
    if not validation.is_valid:
        return _skip_lead(db, run, lead.name, "e-mail inválido")

    return _save_row(db, run, lead, website or None, validation.normalized_email)


def save_scraped_lead(db: Session, run: SearchRun, lead: MapLead) -> bool:
    return _save_lead(db, run, lead)


def _update_run_from_event(db: Session, run: SearchRun, event: ScrapeEvent) -> None:
    run.scanned_count = max(run.scanned_count, event.scanned)
    run.message = event.message

    if event.kind == "skip":
        run.skipped_count += 1

    db.commit()


def _wait_if_paused(db: Session, run_id: int) -> SearchRun | None:
    while True:
        run = db.get(SearchRun, run_id)
        if not run:
            return None

        if run.status != "paused":
            return run

        time.sleep(1)


def _format_search_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutException):
        return "Google Maps não carregou os resultados dentro do tempo limite."

    def clean_message(value: str) -> str:
        message = value.split("Stacktrace:", 1)[0]
        message = re.sub(r"^Message:\s*", "", message.strip(), flags=re.IGNORECASE)
        message = re.sub(r"\s+", " ", message).strip()
        return "" if message.lower() in {"message", "message:"} else message

    if isinstance(exc, WebDriverException):
        message = clean_message(getattr(exc, "msg", "") or str(exc))
        return message or "Google Maps não conseguiu completar a busca no navegador headless."

    message = clean_message(str(exc))
    return message or "Busca falhou por um erro inesperado."


def run_search_job(run_id: int) -> None:
    db = SessionLocal()

    try:
        run = db.get(SearchRun, run_id)
        if not run:
            return

        if run.status not in ("queued", "running", "paused"):
            return

        run = _wait_if_paused(db, run_id)
        if not run:
            return

        run.status = "running"
        run.started_at = run.started_at or _now()
        run.finished_at = None
        run.message = "Abrindo Google Maps em modo headless..."
        db.commit()

        target_quantity = run.target_quantity
        start_index = max(1, run.scanned_count + 1)

        for event in scrape_google_maps(
            run.niche,
            run.location,
            start_index=start_index,
            skip_without_website=run.skip_without_website,
        ):
            run = _wait_if_paused(db, run_id)
            if not run:
                return

            if run.status != "running":
                return

            if event.kind == "done":
                run.message = event.message
                run.scanned_count = max(run.scanned_count, event.scanned)
                db.commit()
                break

            if event.kind == "skip" or event.lead is None:
                _update_run_from_event(db, run, event)
                continue

            run = _wait_if_paused(db, run_id)
            if not run:
                return

            run.scanned_count = max(run.scanned_count, event.scanned)
            run.message = f"Buscando e-mail em {event.lead.website}..." if event.lead.website else f"Salvando {event.lead.name} sem site..."
            db.commit()

            saved = _save_lead(db, run, event.lead)
            run = db.get(SearchRun, run_id)
            if not run:
                return

            if saved:
                run.saved_count += 1
                run.message = f"{event.lead.name} salvo."

            db.commit()

            run = _wait_if_paused(db, run_id)
            if not run:
                return

            if target_quantity and run.saved_count >= target_quantity:
                run.message = "Quantidade solicitada concluída."
                db.commit()
                break

        run = db.get(SearchRun, run_id)
        if run:
            if run.status == "paused":
                return

            run.status = "completed"
            run.finished_at = _now()
            if not run.message:
                run.message = "Busca concluída."
            db.commit()
    except Exception as exc:
        run = db.get(SearchRun, run_id)
        if run:
            error_message = _format_search_error(exc)
            run.status = "failed"
            run.error = error_message
            run.message = error_message
            run.finished_at = _now()
            db.commit()
    finally:
        db.close()
