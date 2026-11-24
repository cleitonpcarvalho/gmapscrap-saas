"""Authenticated manual prospecting. Never calls providers, campaigns, or AI."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.exc import StaleDataError

from backend.auth import get_current_username
from backend.database import get_db
from backend.models import CrmActivity, CrmFollowUp, CrmFunnel, CrmFunnelStage, CrmLead, CrmStageHistory, Lead, LeadTag, SearchRun
from backend.services.crm import move_crm_lead
from backend.services.whatsapp_validation import normalize_phone_e164


Currency = Literal["BRL", "USD", "EUR", "GBP", "CAD", "AUD"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AddCards(Input):
    lead_ids: list[int] = Field(min_length=1, max_length=1000)
    funnel_id: int = Field(gt=0)
    stage_id: int = Field(gt=0)

    @field_validator("lead_ids")
    @classmethod
    def positive_ids(cls, value):
        if any(item <= 0 for item in value):
            raise ValueError("IDs de leads inválidos.")
        return list(dict.fromkeys(value))


class CardUpdate(Input):
    version: int = Field(ge=1)
    managed_manually: Literal[True] | None = None
    stage_id: int | None = Field(default=None, gt=0)
    position: int = Field(default=0, ge=0)
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)
    currency: Currency | None = None
    sales_outcome: Literal["open", "won", "lost"] | None = None
    lost_reason: str | None = Field(default=None, max_length=2000)


class ActivityCreate(Input):
    kind: Literal["note", "call", "whatsapp", "meeting"]
    body: str = Field(min_length=1, max_length=5000)


class FollowUpCreate(Input):
    title: str = Field(min_length=1, max_length=255)
    due_at: AwareDatetime


class FollowUpChange(Input):
    version: int = Field(ge=1)
    action: Literal["complete", "reschedule", "cancel"]
    due_at: AwareDatetime | None = None


def now():
    return datetime.now(timezone.utc)


def utc(value):
    # SQLite drops timezone information; PostgreSQL stores timestamptz.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def require_schema(db: Session = Depends(get_db)):
    inspector = inspect(db.get_bind())
    if not {"crm_activities", "crm_follow_ups"}.issubset(inspector.get_table_names()) or "managed_manually" not in {
        column["name"] for column in inspector.get_columns("crm_leads")
    }:
        raise HTTPException(503, "CRM manual indisponível: aplique a migração versionada antes de publicar o recurso.")


def guard_transaction(db: Session = Depends(get_db)):
    try:
        yield
    except (IntegrityError, StaleDataError):
        db.rollback()
        raise HTTPException(409, "Os dados mudaram. Atualize a tela e tente novamente.") from None
    except Exception:
        db.rollback()
        raise


router = APIRouter(prefix="/api/crm/manual", tags=["manual-crm"], dependencies=[Depends(get_current_username), Depends(require_schema), Depends(guard_transaction)])


def commit(db):
    try:
        db.commit()
    except (IntegrityError, StaleDataError):
        db.rollback()
        raise HTTPException(409, "Os dados mudaram. Atualize a tela e tente novamente.") from None


def card(db, card_id, *, lock=False):
    query = select(CrmLead).where(CrmLead.id == card_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        raise HTTPException(404, "Card não encontrado.")
    return item


def require_manual(item):
    if not item.managed_manually:
        raise HTTPException(409, "Assuma a gestão manual deste card antes de registrar alterações comerciais.")


def event(db, item, body, actor, kind="system", details=None):
    entry = CrmActivity(crm_lead_id=item.id, kind=kind, body=body, actor=actor, created_at=now(), details=details)
    db.add(entry)
    return entry


def follow_read(item):
    return {"id": item.id, "card_id": item.crm_lead_id, "title": item.title, "due_at": utc(item.due_at),
            "status": item.status, "version": item.version,
            "created_at": utc(item.created_at), "completed_at": utc(item.completed_at) if item.completed_at else None}


def lead_read(item):
    normalized = normalize_phone_e164(item.phone, f"{item.address} {item.location}")
    website = item.website or ""
    website = website if website.startswith(("https://", "http://")) else ("https://" + website if website else "")
    return {"id": item.id, "name": item.name, "address": item.address, "phone": item.phone, "email": item.email,
            "website": website, "niche": item.niche, "location": item.location,
            "call_url": "tel:" + normalized if normalized else "",
            "whatsapp_url": "https://wa.me/" + normalized.lstrip("+") if normalized else "",
            "tags": [{"id": tag.id, "name": tag.name, "color": tag.color} for tag in item.tags],
            "provenance": {"run_id": item.run_id, "niche": item.niche, "location": item.location,
                           "created_at": utc(item.search_run.created_at), "status": item.search_run.status}}


def card_read(item, next_follow=None):
    return {"id": item.id, "lead": lead_read(item.lead), "funnel_id": item.funnel_id,
            "funnel_name": item.funnel.name, "stage_id": item.stage_id, "stage_label": item.stage_ref.label,
            "stage_color": item.stage_ref.color, "managed_manually": item.managed_manually,
            "qualification_notes": item.qualification_notes, "estimated_value": str(item.estimated_value) if item.estimated_value is not None else None,
            "currency": item.currency, "sales_outcome": item.sales_outcome, "lost_reason": item.lost_reason,
            "closed_at": utc(item.closed_at) if item.closed_at else None, "version": item.version,
            "position": item.position, "next_follow_up": follow_read(next_follow) if next_follow else None}


@router.get("/leads")
def find_leads(q: str = Query(default="", max_length=255), niche: str = Query(default="", max_length=255),
               location: str = Query(default="", max_length=255), tag_ids: list[int] | None = Query(default=None),
               offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=100), db: Session = Depends(get_db)):
    query = select(Lead).join(SearchRun)
    if q.strip():
        query = query.where(Lead.name.icontains(q.strip(), autoescape=True))
    if niche.strip():
        query = query.where(SearchRun.niche.icontains(niche.strip(), autoescape=True))
    if location.strip():
        query = query.where(SearchRun.location.icontains(location.strip(), autoescape=True))
    if tag_ids:
        query = query.where(Lead.id.in_(select(LeadTag.lead_id).where(LeadTag.tag_id.in_(tag_ids))))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.options(selectinload(Lead.search_run), selectinload(Lead.tags)).order_by(Lead.id).offset(offset).limit(limit)).all()
    return {"items": [lead_read(item) for item in items], "total": total, "offset": offset, "limit": limit}


@router.post("/cards")
def add_cards(payload: AddCards, db: Session = Depends(get_db), actor: str = Depends(get_current_username)):
    # Serialize additions in a pipeline. The existing unique constraint is the
    # final protection against concurrent legacy/automation inserts.
    funnel = db.scalar(select(CrmFunnel).where(CrmFunnel.id == payload.funnel_id).with_for_update())
    stage = db.get(CrmFunnelStage, payload.stage_id)
    if not funnel or not stage or stage.funnel_id != funnel.id:
        raise HTTPException(422, "Escolha um estágio do funil selecionado.")
    found = set(db.scalars(select(Lead.id).where(Lead.id.in_(payload.lead_ids))).all())
    if found != set(payload.lead_ids):
        raise HTTPException(404, "Uma ou mais empresas não foram encontradas. Nenhum card foi adicionado.")
    existing = set(db.scalars(select(CrmLead.lead_id).where(CrmLead.funnel_id == funnel.id, CrmLead.lead_id.in_(payload.lead_ids))).all())
    last_position = db.scalar(select(func.max(CrmLead.position)).where(CrmLead.funnel_id == funnel.id, CrmLead.stage_id == stage.id))
    next_position = (last_position if last_position is not None else -1) + 1
    created = []
    for lead_id in payload.lead_ids:
        if lead_id in existing:
            continue
        item = CrmLead(lead_id=lead_id, funnel_id=funnel.id, stage_id=stage.id, stage=stage.key,
                       position=next_position, managed_manually=True, sales_outcome="open")
        db.add(item)
        db.flush()
        next_position += 1
        event(db, item, "Oportunidade adicionada manualmente ao CRM.", actor)
        created.append(item.id)
    commit(db)
    return {"created_card_ids": created, "skipped_lead_ids": sorted(existing)}


@router.get("/cards")
def list_cards(funnel_id: int = Query(gt=0), db: Session = Depends(get_db)):
    items = db.scalars(select(CrmLead).where(CrmLead.funnel_id == funnel_id).order_by(CrmLead.stage_id, CrmLead.position, CrmLead.id)).all()
    pending = db.scalars(select(CrmFollowUp).where(CrmFollowUp.crm_lead_id.in_([item.id for item in items]), CrmFollowUp.status == "pending")
                         .order_by(CrmFollowUp.due_at, CrmFollowUp.id)).all()
    next_by_card = {}
    for follow in pending:
        next_by_card.setdefault(follow.crm_lead_id, follow)
    return [card_read(item, next_by_card.get(item.id)) for item in items]


@router.get("/cards/{card_id}")
def get_card(card_id: int, db: Session = Depends(get_db)):
    item = card(db, card_id)
    follows = db.scalars(select(CrmFollowUp).where(CrmFollowUp.crm_lead_id == item.id).order_by(CrmFollowUp.due_at, CrmFollowUp.id)).all()
    result = card_read(item, next((follow for follow in follows if follow.status == "pending"), None))
    result["activities"] = [{"id": entry.id, "kind": entry.kind, "body": entry.body, "details": entry.details, "actor": entry.actor, "created_at": utc(entry.created_at)}
                            for entry in db.scalars(select(CrmActivity).where(CrmActivity.crm_lead_id == item.id).order_by(CrmActivity.created_at.desc(), CrmActivity.id.desc())).all()]
    result["stage_history"] = [{"id": entry.id, "from_stage": entry.from_stage, "to_stage": entry.to_stage,
                                "changed_by": entry.changed_by, "changed_at": utc(entry.changed_at)}
                               for entry in db.scalars(select(CrmStageHistory).where(CrmStageHistory.crm_lead_id == item.id).order_by(CrmStageHistory.changed_at, CrmStageHistory.id)).all()]
    result["follow_ups"] = [follow_read(follow) for follow in follows]
    return result


@router.patch("/cards/{card_id}")
def update_card(card_id: int, payload: CardUpdate, db: Session = Depends(get_db), actor: str = Depends(get_current_username)):
    values = payload.model_dump(exclude_unset=True)
    moving = "stage_id" in values or "position" in values
    if moving:
        # Match additions/transfers: pipeline first, then cards. Keep neighbor
        # position normalization and the version check in one transaction.
        pipeline_id = db.scalar(select(CrmLead.funnel_id).where(CrmLead.id == card_id))
        pipeline = db.scalar(select(CrmFunnel).where(CrmFunnel.id == pipeline_id).with_for_update()) if pipeline_id else None
        if pipeline is None:
            raise HTTPException(404, "Card ou funil não encontrado.")
    item = card(db, card_id, lock=True)
    if moving and item.funnel_id != pipeline_id:
        raise HTTPException(409, "O card mudou de funil. Atualize o CRM antes de mover.")
    if item.version != payload.version:
        raise HTTPException(409, "O card foi alterado. Atualize antes de salvar.")
    if not item.managed_manually:
        if values.get("managed_manually") is True:
            item.managed_manually = True
            item.sales_outcome = "open"
            event(db, item, "Gestão manual assumida. O estágio legado não confirma uma venda.", actor)
        elif set(values) - {"version", "stage_id", "position"}:
            require_manual(item)
        elif not moving:
            require_manual(item)
    if moving:
        stage = db.get(CrmFunnelStage, values.get("stage_id", item.stage_id))
        if not stage or stage.funnel_id != item.funnel_id:
            raise HTTPException(422, "Estágio inválido para este funil.")
        previous = item.stage_ref.label
        previous_stage_id, previous_position = item.stage_id, item.position
        move_crm_lead(db, item.lead_id, stage=stage.key, position=values.get("position"),
                      funnel_id=item.funnel_id, changed_by="manual")
        if stage.id != previous_stage_id:
            event(db, item, f"Estágio alterado: {previous} → {stage.label}.", actor)
        elif item.position != previous_position:
            event(db, item, f"Ordem alterada no estágio {stage.label}.", actor)
    for field in ["estimated_value", "currency"]:
        if field in values:
            if field == "currency" and values[field] is None:
                raise HTTPException(422, "Moeda obrigatória.")
            if getattr(item, field) != values[field]:
                previous = getattr(item, field)
                display = lambda value: "não informado" if value is None else (format(value, ".2f").replace(".", ",") if isinstance(value, Decimal) else str(value))
                event(db, item, f"{('Valor estimado' if field == 'estimated_value' else 'Moeda')} alterado: {display(previous)} → {display(values[field])}.", actor)
                setattr(item, field, values[field])
    if "sales_outcome" in values or "lost_reason" in values:
        outcome = values.get("sales_outcome", item.sales_outcome)
        reason = values.get("lost_reason", item.lost_reason)
        if outcome is None or (outcome == "lost" and not reason):
            raise HTTPException(422, "Informe o resultado e o motivo da perda, quando aplicável.")
        if outcome == "won" and item.estimated_value is None:
            raise HTTPException(422, "Informe o valor da proposta antes de confirmar a venda.")
        next_reason = reason if outcome == "lost" else None
        if outcome != item.sales_outcome or next_reason != item.lost_reason:
            label = {"open": "aberta", "won": "ganha", "lost": "perdida"}[outcome]
            event(db, item, f"Resultado comercial: oportunidade {label}." + (f" Motivo: {next_reason}" if next_reason else ""), actor)
        if outcome != item.sales_outcome:
            item.closed_at = now() if outcome != "open" else None
        item.sales_outcome = outcome
        item.lost_reason = next_reason
    if item.sales_outcome == "won" and item.estimated_value is None:
        raise HTTPException(422, "Uma venda confirmada precisa de valor informado.")
    commit(db)
    return get_card(card_id, db)


@router.post("/cards/{card_id}/activities", status_code=201)
def add_activity(card_id: int, payload: ActivityCreate, db: Session = Depends(get_db), actor: str = Depends(get_current_username)):
    item = card(db, card_id, lock=True)
    require_manual(item)
    entry = event(db, item, payload.body, actor, payload.kind)
    commit(db)
    return {"id": entry.id, "kind": entry.kind, "body": entry.body, "actor": entry.actor, "created_at": utc(entry.created_at)}


@router.post("/cards/{card_id}/follow-ups", status_code=201)
def add_follow_up(card_id: int, payload: FollowUpCreate, db: Session = Depends(get_db), actor: str = Depends(get_current_username)):
    item = card(db, card_id, lock=True)
    require_manual(item)
    follow = CrmFollowUp(crm_lead_id=item.id, title=payload.title, due_at=payload.due_at.astimezone(timezone.utc))
    db.add(follow)
    event(db, item, f"Follow-up agendado: {follow.title}.", actor, details={"due_at": follow.due_at.isoformat()})
    commit(db)
    return follow_read(follow)


@router.patch("/follow-ups/{follow_id}")
def change_follow_up(follow_id: int, payload: FollowUpChange, db: Session = Depends(get_db), actor: str = Depends(get_current_username)):
    follow = db.scalar(select(CrmFollowUp).where(CrmFollowUp.id == follow_id).with_for_update())
    if not follow:
        raise HTTPException(404, "Follow-up não encontrado.")
    item = card(db, follow.crm_lead_id)
    require_manual(item)
    if follow.version != payload.version or follow.status != "pending":
        raise HTTPException(409, "O follow-up já mudou. Atualize a tela.")
    if payload.action == "reschedule":
        if payload.due_at is None:
            raise HTTPException(422, "Informe a nova data com fuso horário.")
        previous = utc(follow.due_at)
        follow.due_at = payload.due_at.astimezone(timezone.utc)
        event(db, item, f"Follow-up reagendado: {follow.title}.", actor,
              details={"previous_due_at": previous.isoformat(), "due_at": follow.due_at.isoformat()})
    else:
        follow.status = "completed" if payload.action == "complete" else "cancelled"
        follow.completed_at = now() if payload.action == "complete" else None
        event(db, item, f"Follow-up {'concluído' if payload.action == 'complete' else 'cancelado'}: {follow.title}.", actor)
    commit(db)
    return follow_read(follow)


@router.get("/follow-ups")
def list_follow_ups(bucket: Literal["overdue", "today", "upcoming"] = "today", timezone_name: str = Query(default="UTC", max_length=100), db: Session = Depends(get_db)):
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Fuso horário inválido.") from None
    current = now()
    tomorrow = datetime.combine(current.astimezone(zone).date() + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    query = select(CrmFollowUp).where(CrmFollowUp.status == "pending")
    if bucket == "overdue":
        query = query.where(CrmFollowUp.due_at < current)
    elif bucket == "today":
        query = query.where(CrmFollowUp.due_at >= current, CrmFollowUp.due_at < tomorrow)
    else:
        query = query.where(CrmFollowUp.due_at >= tomorrow)
    result = []
    for follow in db.scalars(query.order_by(CrmFollowUp.due_at, CrmFollowUp.id)).all():
        item = card(db, follow.crm_lead_id)
        result.append({**follow_read(follow), "lead_name": item.lead.name, "funnel_name": item.funnel.name})
    return result
