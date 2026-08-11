from __future__ import annotations

import logging
import re
from typing import Iterable

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from backend.models import CrmFunnel, CrmFunnelStage, CrmLead, CrmStageHistory


logger = logging.getLogger(__name__)

CRM_STAGES = {"new", "responded", "qualified", "not_interested", "converted"}

DEFAULT_CRM_FUNNEL_NAME = "Funil padrão"
DEFAULT_CRM_STAGE_DEFINITIONS = [
    {
        "key": "new",
        "label": "Novo",
        "color": "#f3f4f6",
        "description": "Lead recém-chegado, ainda sem resposta ou qualificação.",
        "position": 0,
        "is_won": False,
        "is_lost": False,
    },
    {
        "key": "responded",
        "label": "Respondeu",
        "color": "#dff7f1",
        "description": "Lead respondeu à abordagem, mas ainda não há qualificação suficiente.",
        "position": 1,
        "is_won": False,
        "is_lost": False,
    },
    {
        "key": "qualified",
        "label": "Qualificado",
        "color": "#dcf6e8",
        "description": "Lead demonstrou dor, necessidade ou encaixe claro com a oferta.",
        "position": 2,
        "is_won": False,
        "is_lost": False,
    },
    {
        "key": "not_interested",
        "label": "Sem interesse",
        "color": "#ffe4e6",
        "description": "Lead recusou a conversa, pediu para não seguir ou demonstrou desinteresse claro.",
        "position": 3,
        "is_won": False,
        "is_lost": True,
    },
    {
        "key": "converted",
        "label": "Convertido",
        "color": "#fff4ce",
        "description": "Lead aceitou avançar para reunião, fechamento ou próximo passo comercial concreto.",
        "position": 4,
        "is_won": True,
        "is_lost": False,
    },
]


def normalize_stage_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized[:60] or "stage"


def get_default_crm_funnel(db: Session) -> CrmFunnel:
    funnel = db.scalar(
        select(CrmFunnel)
        .options(selectinload(CrmFunnel.stages))
        .where(CrmFunnel.is_default.is_(True))
        .order_by(CrmFunnel.id)
    )
    if not funnel:
        funnel = db.scalar(
            select(CrmFunnel)
            .options(selectinload(CrmFunnel.stages))
            .where(func.lower(CrmFunnel.name) == DEFAULT_CRM_FUNNEL_NAME.lower())
            .order_by(CrmFunnel.id)
        )
        if funnel:
            funnel.is_default = True
        else:
            funnel = CrmFunnel(
                name=DEFAULT_CRM_FUNNEL_NAME,
                description="Funil padrão migrado dos estágios originais.",
                is_default=True,
            )
            db.add(funnel)
            db.flush()

    _ensure_default_stages(db, funnel)
    return funnel


def _ensure_default_stages(db: Session, funnel: CrmFunnel) -> None:
    existing_by_key = {stage.key: stage for stage in funnel.stages}
    for definition in DEFAULT_CRM_STAGE_DEFINITIONS:
        stage = existing_by_key.get(definition["key"])
        if stage:
            stage.label = definition["label"]
            stage.color = definition["color"]
            stage.description = definition["description"]
            stage.position = definition["position"]
            stage.is_won = definition["is_won"]
            stage.is_lost = definition["is_lost"]
            continue
        db.add(CrmFunnelStage(funnel_id=funnel.id, **definition))
    db.flush()
    db.refresh(funnel)


def _funnel_with_stages(db: Session, funnel_id: int | None) -> CrmFunnel:
    if funnel_id is None:
        return get_default_crm_funnel(db)

    funnel = db.scalar(
        select(CrmFunnel)
        .options(selectinload(CrmFunnel.stages))
        .where(CrmFunnel.id == funnel_id)
    )
    if not funnel:
        raise ValueError(f"Funil de CRM inválido: {funnel_id}")
    if not funnel.stages:
        raise ValueError("Funil de CRM sem estágios.")
    return funnel


def _ordered_stages(funnel: CrmFunnel) -> list[CrmFunnelStage]:
    return sorted(funnel.stages, key=lambda stage: (stage.position, stage.id))


def _stage_by_key(db: Session, funnel_id: int, key: str) -> CrmFunnelStage | None:
    return db.scalar(
        select(CrmFunnelStage)
        .where(CrmFunnelStage.funnel_id == funnel_id, CrmFunnelStage.key == key)
        .order_by(CrmFunnelStage.position, CrmFunnelStage.id)
    )


def _stage_by_terminal_flag(db: Session, funnel_id: int, *, is_won: bool = False, is_lost: bool = False) -> CrmFunnelStage | None:
    stmt = select(CrmFunnelStage).where(CrmFunnelStage.funnel_id == funnel_id)
    if is_won:
        stmt = stmt.where(CrmFunnelStage.is_won.is_(True))
    if is_lost:
        stmt = stmt.where(CrmFunnelStage.is_lost.is_(True))
    return db.scalar(stmt.order_by(CrmFunnelStage.position, CrmFunnelStage.id))


def _first_stage(db: Session, funnel_id: int) -> CrmFunnelStage:
    stage = db.scalar(
        select(CrmFunnelStage)
        .where(CrmFunnelStage.funnel_id == funnel_id)
        .order_by(CrmFunnelStage.position, CrmFunnelStage.id)
    )
    if not stage:
        raise ValueError("Funil de CRM sem estágios.")
    return stage


def _resolve_stage(
    db: Session,
    funnel_id: int,
    requested_key: str | None,
    *,
    current_stage: CrmFunnelStage | None = None,
    allow_fallback: bool = True,
) -> CrmFunnelStage:
    key = normalize_stage_key(requested_key or "")
    exact = _stage_by_key(db, funnel_id, key) if key else None
    if exact:
        return exact

    if not allow_fallback:
        raise ValueError(f"Estágio de CRM inválido: {requested_key}")

    fallback = None
    if key == "converted":
        fallback = _stage_by_terminal_flag(db, funnel_id, is_won=True)
    elif key == "not_interested":
        fallback = _stage_by_terminal_flag(db, funnel_id, is_lost=True)

    if not fallback and current_stage:
        fallback = current_stage
    if not fallback:
        fallback = _first_stage(db, funnel_id)

    logger.warning(
        "Fallback de estágio CRM aplicado",
        extra={"funnel_id": funnel_id, "requested_stage": requested_key, "fallback_stage": fallback.key},
    )
    return fallback


def _sync_crm_lead_stage(db: Session, crm_lead: CrmLead) -> CrmLead:
    funnel = _funnel_with_stages(db, crm_lead.funnel_id)
    current_stage = None
    if crm_lead.stage_id:
        current_stage = db.get(CrmFunnelStage, crm_lead.stage_id)
        if current_stage and current_stage.funnel_id != funnel.id:
            current_stage = None

    stage_ref = current_stage or _resolve_stage(db, funnel.id, crm_lead.stage, allow_fallback=True)
    crm_lead.funnel_id = funnel.id
    crm_lead.stage_id = stage_ref.id
    crm_lead.stage = stage_ref.key
    db.flush()
    return crm_lead


def _ordered_crm_leads_for_stage(db: Session, funnel_id: int, stage_id: int) -> list[CrmLead]:
    return list(
        db.scalars(
            select(CrmLead)
            .where(CrmLead.funnel_id == funnel_id, CrmLead.stage_id == stage_id)
            .order_by(
                CrmLead.position.is_(None),
                CrmLead.position.asc(),
                desc(CrmLead.updated_at),
                desc(CrmLead.id),
            )
        ).all()
    )


def _normalize_stage_positions(
    db: Session,
    funnel_id: int,
    stage_id: int,
    *,
    moving_lead: CrmLead | None = None,
    insert_at: int | None = None,
) -> None:
    stage_leads = _ordered_crm_leads_for_stage(db, funnel_id, stage_id)
    if moving_lead is not None:
        stage_leads = [lead for lead in stage_leads if lead.id != moving_lead.id]
        if insert_at is not None:
            target_index = max(0, min(insert_at, len(stage_leads)))
            stage_leads.insert(target_index, moving_lead)

    for index, lead in enumerate(stage_leads):
        lead.position = index


def _existing_cards_for_lead(db: Session, lead_id: int) -> list[CrmLead]:
    return list(
        db.scalars(
            select(CrmLead)
            .options(selectinload(CrmLead.funnel), selectinload(CrmLead.stage_ref))
            .where(CrmLead.lead_id == lead_id)
            .order_by(desc(CrmLead.updated_at), desc(CrmLead.id))
        ).all()
    )


def _latest_existing_card_funnel_id(db: Session, lead_id: int) -> int | None:
    cards = _existing_cards_for_lead(db, lead_id)
    if not cards:
        return None
    if len(cards) > 1:
        logger.info(
            "Lead possui cards em múltiplos funis; usando o card CRM atualizado mais recentemente",
            extra={"lead_id": lead_id, "crm_lead_ids": [card.id for card in cards]},
        )
    return cards[0].funnel_id


def get_or_create_crm_lead(db: Session, lead_id: int, *, funnel_id: int | None = None, stage: str = "new") -> CrmLead:
    funnel = _funnel_with_stages(db, funnel_id)
    stage_ref = _resolve_stage(db, funnel.id, stage, allow_fallback=True)

    crm_lead = db.scalar(select(CrmLead).where(CrmLead.lead_id == lead_id, CrmLead.funnel_id == funnel.id))
    if crm_lead:
        if crm_lead.position is None or crm_lead.stage_id is None:
            _sync_crm_lead_stage(db, crm_lead)
            _normalize_stage_positions(db, crm_lead.funnel_id, crm_lead.stage_id)
        return crm_lead

    legacy_crm_lead = db.scalar(select(CrmLead).where(CrmLead.lead_id == lead_id, CrmLead.funnel_id.is_(None)))
    if legacy_crm_lead:
        legacy_crm_lead.funnel_id = funnel.id
        legacy_crm_lead.stage_id = stage_ref.id
        legacy_crm_lead.stage = stage_ref.key
        if legacy_crm_lead.position is None:
            legacy_crm_lead.position = 0
        db.flush()
        _normalize_stage_positions(db, funnel.id, stage_ref.id, moving_lead=legacy_crm_lead, insert_at=legacy_crm_lead.position)
        return legacy_crm_lead

    crm_lead = CrmLead(lead_id=lead_id, funnel_id=funnel.id, stage_id=stage_ref.id, stage=stage_ref.key, position=0)
    db.add(crm_lead)
    db.flush()
    _normalize_stage_positions(db, funnel.id, stage_ref.id, moving_lead=crm_lead, insert_at=0)
    return crm_lead


def move_crm_lead(
    db: Session,
    lead_id: int,
    *,
    stage: str | None = None,
    position: int | None = None,
    changed_by: str,
    reason: str | None = None,
    funnel_id: int | None = None,
) -> CrmLead:
    if changed_by not in {"ai", "manual"}:
        raise ValueError(f"Origem de alteração inválida: {changed_by}")

    crm_lead = get_or_create_crm_lead(db, lead_id, funnel_id=funnel_id)
    crm_lead = _sync_crm_lead_stage(db, crm_lead)
    previous_stage_id = crm_lead.stage_id
    previous_stage_key = crm_lead.stage
    previous_stage_ref = db.get(CrmFunnelStage, previous_stage_id)
    next_stage_ref = previous_stage_ref
    if stage is not None:
        next_stage_ref = _resolve_stage(
            db,
            crm_lead.funnel_id,
            stage,
            current_stage=previous_stage_ref,
            allow_fallback=changed_by == "ai",
        )

    if not next_stage_ref:
        next_stage_ref = _first_stage(db, crm_lead.funnel_id)

    if reason and reason.strip():
        crm_lead.qualification_notes = reason.strip()

    stage_changed = next_stage_ref.id != previous_stage_id
    if stage_changed:
        crm_lead.stage_id = next_stage_ref.id
        crm_lead.stage = next_stage_ref.key
        db.flush()
        db.add(
            CrmStageHistory(
                crm_lead_id=crm_lead.id,
                from_stage=previous_stage_key,
                to_stage=next_stage_ref.key,
                from_stage_id=previous_stage_id,
                to_stage_id=next_stage_ref.id,
                changed_by=changed_by,
            )
        )

    should_reposition = position is not None or stage_changed or crm_lead.position is None
    if should_reposition:
        target_position = 0 if position is None else position
        if stage_changed:
            _normalize_stage_positions(db, crm_lead.funnel_id, previous_stage_id)
        _normalize_stage_positions(db, crm_lead.funnel_id, next_stage_ref.id, moving_lead=crm_lead, insert_at=target_position)

    return crm_lead


def update_crm_stage(
    db: Session,
    lead_id: int,
    stage: str,
    *,
    changed_by: str,
    reason: str | None = None,
) -> CrmLead:
    funnel_id = _latest_existing_card_funnel_id(db, lead_id)
    return move_crm_lead(db, lead_id, stage=stage, changed_by=changed_by, reason=reason, funnel_id=funnel_id)


def normalize_funnel_stage_positions(db: Session, funnel_id: int, stage_ids: Iterable[int]) -> None:
    for index, stage_id in enumerate(stage_ids):
        stage = db.get(CrmFunnelStage, stage_id)
        if stage and stage.funnel_id == funnel_id:
            stage.position = index
