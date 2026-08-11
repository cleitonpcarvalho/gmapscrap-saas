from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import Lead, SearchRun, WhatsAppInstance
from backend.services.whatsapp_validation import (
    check_whatsapp_number_once,
    get_whatsapp_validation_instance_name,
    is_whatsapp_validation_configured,
    normalize_phone_e164,
)


VALIDATION_STATUS_VALID = "valid"
VALIDATION_STATUS_INVALID = "invalid"
VALIDATION_STATUS_UNKNOWN = "unknown"

REASON_API_ERROR = "api_error"
REASON_INVALID_NUMBER = "invalid_number"
REASON_NO_PHONE = "no_phone"
REASON_NOT_REGISTERED = "not_registered"

logger = logging.getLogger(__name__)
validation_executor = ThreadPoolExecutor(max_workers=1)
_progress_lock = Lock()
_job_active = False
_cancel_requested = False


@dataclass(frozen=True, slots=True)
class LeadWhatsAppValidationTarget:
    id: int
    phone: str
    address: str
    location: str
    should_skip: bool


@dataclass(frozen=True, slots=True)
class LeadWhatsAppValidationOutcome:
    whatsapp_validated: bool | None
    status: str
    reason: str | None
    api_called: bool = False
    api_failure: bool = False


@dataclass(frozen=True, slots=True)
class LeadWhatsAppValidationSelection:
    targets: tuple[LeadWhatsAppValidationTarget, ...]
    eligible_count: int
    queued_count: int
    skipped_count: int


@dataclass(frozen=True, slots=True)
class LeadWhatsAppValidationPreviewData:
    total_leads: int
    never_validated: int
    valid: int
    invalid: int
    unknown: int
    without_phone: int
    eligible_now: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _idle_progress(error: str | None = None) -> dict[str, Any]:
    return {
        "job_id": "",
        "status": "idle",
        "total": 0,
        "processed": 0,
        "valid": 0,
        "invalid": 0,
        "unknown": 0,
        "skipped": 0,
        "started_at": None,
        "finished_at": None,
        "error": error,
    }


_validation_progress: dict[str, Any] = _idle_progress()


def get_validation_progress() -> dict[str, Any]:
    """Return volatile in-memory progress for the current/last validation job.

    This progress is intentionally process-local and is lost on backend restart,
    matching the existing in-memory worker pattern used elsewhere in the project.
    """
    with _progress_lock:
        return dict(_validation_progress)


def resolve_lead_whatsapp_validation_targets(
    db: Session,
    *,
    lead_ids: Sequence[int] | None = None,
    run_id: int | None = None,
    niche: str | None = None,
    location: str | None = None,
    search: str | None = None,
    only_pending: bool | None = None,
    revalidate: bool = False,
    limit: int | None = None,
) -> list[LeadWhatsAppValidationTarget]:
    return list(
        prepare_lead_whatsapp_validation_selection(
            db,
            lead_ids=lead_ids,
            run_id=run_id,
            niche=niche,
            location=location,
            search=search,
            only_pending=only_pending,
            revalidate=revalidate,
            limit=limit,
        ).targets
    )


def prepare_lead_whatsapp_validation_selection(
    db: Session,
    *,
    lead_ids: Sequence[int] | None = None,
    run_id: int | None = None,
    niche: str | None = None,
    location: str | None = None,
    search: str | None = None,
    only_pending: bool | None = None,
    revalidate: bool = False,
    limit: int | None = None,
) -> LeadWhatsAppValidationSelection:
    explicit_ids = _unique_positive_ids(lead_ids) if lead_ids is not None else None
    raw_stmt = _lead_selection_stmt(
        lead_ids=explicit_ids,
        run_id=run_id,
        niche=niche,
        location=location,
        search=search,
    )

    if explicit_ids is not None:
        if not explicit_ids:
            return LeadWhatsAppValidationSelection(targets=(), eligible_count=0, queued_count=0, skipped_count=0)
        leads_by_id = {lead.id: lead for lead in db.scalars(raw_stmt).all()}
        raw_leads = [leads_by_id[lead_id] for lead_id in explicit_ids if lead_id in leads_by_id]
    else:
        raw_leads = list(db.scalars(raw_stmt).all())

    eligible_count = len(raw_leads)
    leads = _apply_pending_and_limit(
        raw_leads,
        only_pending=_effective_only_pending(
            explicit_ids=explicit_ids,
            run_id=run_id,
            niche=niche,
            location=location,
            search=search,
            only_pending=only_pending,
        ),
        limit=limit,
    )
    targets = tuple(_target_for_lead(lead, revalidate=revalidate) for lead in leads)
    queued_count = sum(1 for target in targets if _target_counts_as_queued(target))
    return LeadWhatsAppValidationSelection(
        targets=targets,
        eligible_count=eligible_count,
        queued_count=queued_count,
        skipped_count=max(0, eligible_count - queued_count),
    )


def preview_lead_whatsapp_validation(
    db: Session,
    *,
    lead_ids: Sequence[int] | None = None,
    run_id: int | None = None,
    niche: str | None = None,
    location: str | None = None,
    search: str | None = None,
    only_pending: bool | None = None,
    revalidate: bool = False,
    limit: int | None = None,
) -> LeadWhatsAppValidationPreviewData:
    explicit_ids = _unique_positive_ids(lead_ids) if lead_ids is not None else None
    raw_stmt = _lead_selection_stmt(
        lead_ids=explicit_ids,
        run_id=run_id,
        niche=niche,
        location=location,
        search=search,
    )
    if explicit_ids is not None and not explicit_ids:
        raw_leads: list[Lead] = []
    elif explicit_ids is not None:
        leads_by_id = {lead.id: lead for lead in db.scalars(raw_stmt).all()}
        raw_leads = [leads_by_id[lead_id] for lead_id in explicit_ids if lead_id in leads_by_id]
    else:
        raw_leads = list(db.scalars(raw_stmt).all())

    candidates = _apply_pending_and_limit(
        raw_leads,
        only_pending=_effective_only_pending(
            explicit_ids=explicit_ids,
            run_id=run_id,
            niche=niche,
            location=location,
            search=search,
            only_pending=only_pending,
        ),
        limit=limit,
    )
    targets = tuple(_target_for_lead(lead, revalidate=revalidate) for lead in candidates)

    return LeadWhatsAppValidationPreviewData(
        total_leads=len(raw_leads),
        never_validated=sum(1 for lead in raw_leads if lead.whatsapp_validated_at is None),
        valid=sum(1 for lead in raw_leads if lead.whatsapp_validation_status == VALIDATION_STATUS_VALID),
        invalid=sum(1 for lead in raw_leads if lead.whatsapp_validation_status == VALIDATION_STATUS_INVALID),
        unknown=sum(1 for lead in raw_leads if lead.whatsapp_validation_status == VALIDATION_STATUS_UNKNOWN),
        without_phone=sum(1 for lead in raw_leads if not (lead.phone or "").strip()),
        eligible_now=sum(1 for target in targets if _target_counts_as_queued(target)),
    )


def start_lead_whatsapp_validation_job(
    *,
    lead_ids: Sequence[int] | None = None,
    run_id: int | None = None,
    niche: str | None = None,
    location: str | None = None,
    search: str | None = None,
    only_pending: bool | None = None,
    revalidate: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Start one sequential WhatsApp validation job for saved leads.

    The connected-instance preflight mirrors the guard in
    backend.main.start_whatsapp_campaign: the selected WhatsAppInstance must have
    status == "connected" before any background work is queued.

    Progress is volatile and kept only in memory; it is lost on process restart.
    """
    global _cancel_requested, _job_active, _validation_progress

    with _progress_lock:
        if _job_active:
            raise RuntimeError("Já existe uma validação de WhatsApp em andamento.")
        _job_active = True
        _cancel_requested = False

    try:
        db = SessionLocal()
        try:
            instance_name = connected_validation_instance_name(db)
            selection = prepare_lead_whatsapp_validation_selection(
                db,
                lead_ids=lead_ids,
                run_id=run_id,
                niche=niche,
                location=location,
                search=search,
                only_pending=only_pending,
                revalidate=revalidate,
                limit=limit,
            )
        finally:
            db.close()

        job_id = uuid.uuid4().hex
        with _progress_lock:
            _validation_progress = {
                "job_id": job_id,
                "status": "running",
                "total": len(selection.targets),
                "processed": 0,
                "valid": 0,
                "invalid": 0,
                "unknown": 0,
                "skipped": 0,
                "started_at": _iso_now(),
                "finished_at": None,
                "error": None,
            }

        if not selection.targets:
            _finish_job(job_id, "completed")
            _release_job()
            return get_validation_progress()

        validation_executor.submit(_run_validation_job_and_release, job_id, selection.targets, instance_name)
        return get_validation_progress()
    except Exception:
        with _progress_lock:
            _job_active = False
            _validation_progress = _idle_progress(error="Não foi possível iniciar a validação de WhatsApp.")
        raise


def cancel_validation_job() -> dict[str, Any]:
    """Request cooperative cancellation of the running validation job."""
    global _cancel_requested
    with _progress_lock:
        if not _job_active or _validation_progress.get("status") != "running":
            raise RuntimeError("Não há validação de WhatsApp em andamento.")
        _cancel_requested = True
        return dict(_validation_progress)


def validation_job_is_running() -> bool:
    with _progress_lock:
        return bool(_job_active and _validation_progress.get("status") == "running")


def _unique_positive_ids(lead_ids: Sequence[int] | None) -> list[int]:
    if lead_ids is None:
        return []
    return list(dict.fromkeys(lead_id for lead_id in lead_ids if lead_id > 0))


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _lead_selection_stmt(
    *,
    lead_ids: Sequence[int] | None = None,
    run_id: int | None = None,
    niche: str | None = None,
    location: str | None = None,
    search: str | None = None,
):
    stmt = (
        select(Lead)
        .join(SearchRun)
        .options(selectinload(Lead.search_run))
        .order_by(Lead.created_at, Lead.id)
    )

    if lead_ids is not None:
        return stmt.where(Lead.id.in_(lead_ids))
    if run_id is not None:
        stmt = stmt.where(Lead.run_id == run_id)
    if niche:
        stmt = stmt.where(SearchRun.niche.ilike(f"%{niche.strip()}%"))
    if location:
        stmt = stmt.where(SearchRun.location.ilike(f"%{location.strip()}%"))
    if search:
        stmt = stmt.where(Lead.name.ilike(f"%{search.strip()}%"))
    return stmt


def _effective_only_pending(
    *,
    explicit_ids: Sequence[int] | None,
    run_id: int | None,
    niche: str | None,
    location: str | None,
    search: str | None,
    only_pending: bool | None,
) -> bool:
    if only_pending is not None:
        return only_pending
    has_filters = bool(explicit_ids is not None or run_id or _clean(niche) or _clean(location) or _clean(search))
    return not has_filters


def _apply_pending_and_limit(leads: list[Lead], *, only_pending: bool, limit: int | None) -> list[Lead]:
    selected = [lead for lead in leads if lead.whatsapp_validated_at is None] if only_pending else leads
    if limit is not None:
        selected = selected[: max(0, limit)]
    return selected


def _target_for_lead(lead: Lead, *, revalidate: bool) -> LeadWhatsAppValidationTarget:
    should_skip = (
        not revalidate
        and lead.whatsapp_validated_at is not None
        and lead.whatsapp_validation_status != VALIDATION_STATUS_UNKNOWN
    )
    return LeadWhatsAppValidationTarget(
        id=lead.id,
        phone=lead.phone or "",
        address=lead.address or "",
        location=lead.location,
        should_skip=should_skip,
    )


def _target_counts_as_queued(target: LeadWhatsAppValidationTarget) -> bool:
    return not target.should_skip and bool(target.phone.strip())


def connected_validation_instance_name(db: Session) -> str:
    """Return the configured Evolution instance if it is connected.

    This mirrors backend.main.start_whatsapp_campaign's safety check: a local
    WhatsAppInstance must exist for the resolved Evolution name and have
    status == "connected" before work is started.
    """
    if not is_whatsapp_validation_configured(db):
        raise RuntimeError("Validação de WhatsApp não configurada no servidor.")

    instance_name = get_whatsapp_validation_instance_name(db)
    instance = db.scalar(
        select(WhatsAppInstance)
        .where(
            WhatsAppInstance.provider == "evolution",
            or_(
                WhatsAppInstance.evolution_instance_name == instance_name,
                WhatsAppInstance.name == instance_name,
            ),
        )
        .order_by(
            (WhatsAppInstance.status == "connected").desc(),
            desc(WhatsAppInstance.connected_at),
            desc(WhatsAppInstance.created_at),
        )
        .limit(1)
    )
    if not instance:
        raise RuntimeError("Instância de WhatsApp não encontrada no banco.")
    if instance.status != "connected":
        raise RuntimeError("Conecte a instância de WhatsApp antes de iniciar a validação.")
    return instance_name


def _run_validation_job_and_release(
    job_id: str,
    targets: tuple[LeadWhatsAppValidationTarget, ...],
    instance_name: str,
) -> None:
    try:
        _run_validation_job(job_id, targets, instance_name)
    except Exception:
        logger.exception("Falha ao validar WhatsApp dos leads existentes")
        _finish_job(job_id, "aborted", error="Validação de WhatsApp abortada por erro inesperado.")
    finally:
        _release_job()


def _run_validation_job(
    job_id: str,
    targets: tuple[LeadWhatsAppValidationTarget, ...],
    instance_name: str,
) -> None:
    settings = get_settings()
    delay_seconds = max(0.0, float(settings.whatsapp_batch_validation_delay_seconds))
    max_consecutive_errors = max(1, int(settings.whatsapp_batch_validation_max_consecutive_errors))
    consecutive_api_errors = 0

    for index, target in enumerate(targets):
        if _should_cancel():
            _finish_job(job_id, "cancelled", error="Validação de WhatsApp cancelada pelo usuário.")
            return

        if target.should_skip:
            _increment_progress(job_id, processed=1, skipped=1)
            continue

        outcome = _validate_target(target, instance_name)
        written = _write_validation_result(
            target.id,
            whatsapp_validated=outcome.whatsapp_validated,
            status_value=outcome.status,
            reason=outcome.reason,
            validated_at=_now(),
        )
        if not written:
            _increment_progress(job_id, processed=1, skipped=1)
            continue

        _increment_progress(job_id, processed=1, **{outcome.status: 1})

        if outcome.api_failure:
            consecutive_api_errors += 1
            if consecutive_api_errors >= max_consecutive_errors:
                _finish_job(
                    job_id,
                    "aborted",
                    error=(
                        "Validação abortada após "
                        f"{max_consecutive_errors} falhas consecutivas da Evolution API."
                    ),
                )
                return
        elif outcome.api_called:
            consecutive_api_errors = 0

        if outcome.api_called and delay_seconds and index < len(targets) - 1:
            time.sleep(delay_seconds)

    _finish_job(job_id, "completed")


def _should_cancel() -> bool:
    with _progress_lock:
        return bool(_cancel_requested)


def _validate_target(target: LeadWhatsAppValidationTarget, instance_name: str) -> LeadWhatsAppValidationOutcome:
    phone = target.phone.strip()
    if not phone:
        return LeadWhatsAppValidationOutcome(None, VALIDATION_STATUS_UNKNOWN, REASON_NO_PHONE)

    normalized = normalize_phone_e164(phone, f"{target.address} {target.location}")
    if not normalized:
        return LeadWhatsAppValidationOutcome(None, VALIDATION_STATUS_UNKNOWN, REASON_INVALID_NUMBER)

    settings = get_settings()
    max_retries = max(0, int(settings.whatsapp_batch_validation_max_retries))
    backoff_seconds = 3.0

    for attempt in range(max_retries + 1):
        check_result = check_whatsapp_number_once(normalized, instance_name)
        if check_result.exists is True:
            return LeadWhatsAppValidationOutcome(True, VALIDATION_STATUS_VALID, None, api_called=True)
        if check_result.exists is False:
            return LeadWhatsAppValidationOutcome(
                False,
                VALIDATION_STATUS_INVALID,
                REASON_NOT_REGISTERED,
                api_called=True,
            )

        if not check_result.retryable or attempt >= max_retries:
            break

        time.sleep(backoff_seconds)
        backoff_seconds *= 2

    return LeadWhatsAppValidationOutcome(
        None,
        VALIDATION_STATUS_UNKNOWN,
        REASON_API_ERROR,
        api_called=True,
        api_failure=True,
    )


def _write_validation_result(
    lead_id: int,
    *,
    whatsapp_validated: bool | None,
    status_value: str,
    reason: str | None,
    validated_at: datetime,
) -> bool:
    db = SessionLocal()
    try:
        lead = db.get(Lead, lead_id)
        if not lead:
            return False

        lead.whatsapp_validated = whatsapp_validated
        lead.whatsapp_validation_status = status_value
        lead.whatsapp_validation_reason = reason
        lead.whatsapp_validated_at = validated_at
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _increment_progress(job_id: str, **increments: int) -> None:
    with _progress_lock:
        if _validation_progress.get("job_id") != job_id:
            return
        for key, value in increments.items():
            _validation_progress[key] = int(_validation_progress.get(key, 0)) + value


def _finish_job(job_id: str, status_value: str, error: str | None = None) -> None:
    with _progress_lock:
        if _validation_progress.get("job_id") != job_id:
            return
        _validation_progress["status"] = status_value
        _validation_progress["finished_at"] = _iso_now()
        _validation_progress["error"] = error


def _release_job() -> None:
    global _job_active
    with _progress_lock:
        _job_active = False
