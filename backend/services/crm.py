from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.models import CrmLead, CrmStageHistory


CRM_STAGES = {"new", "responded", "qualified", "not_interested", "converted"}


def _ordered_crm_leads_for_stage(db: Session, stage: str) -> list[CrmLead]:
    return list(
        db.scalars(
            select(CrmLead)
            .where(CrmLead.stage == stage)
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
    stage: str,
    *,
    moving_lead: CrmLead | None = None,
    insert_at: int | None = None,
) -> None:
    stage_leads = _ordered_crm_leads_for_stage(db, stage)
    if moving_lead is not None:
        stage_leads = [lead for lead in stage_leads if lead.id != moving_lead.id]
        if insert_at is not None:
            target_index = max(0, min(insert_at, len(stage_leads)))
            stage_leads.insert(target_index, moving_lead)

    for index, lead in enumerate(stage_leads):
        lead.position = index


def get_or_create_crm_lead(db: Session, lead_id: int, *, stage: str = "new") -> CrmLead:
    if stage not in CRM_STAGES:
        raise ValueError(f"Estágio de CRM inválido: {stage}")

    crm_lead = db.scalar(select(CrmLead).where(CrmLead.lead_id == lead_id))
    if crm_lead:
        if crm_lead.position is None:
            _normalize_stage_positions(db, crm_lead.stage)
        return crm_lead

    crm_lead = CrmLead(lead_id=lead_id, stage=stage, position=0)
    db.add(crm_lead)
    db.flush()
    _normalize_stage_positions(db, stage, moving_lead=crm_lead, insert_at=0)
    return crm_lead


def move_crm_lead(
    db: Session,
    lead_id: int,
    *,
    stage: str | None = None,
    position: int | None = None,
    changed_by: str,
    reason: str | None = None,
) -> CrmLead:
    if stage is not None and stage not in CRM_STAGES:
        raise ValueError(f"Estágio de CRM inválido: {stage}")
    if changed_by not in {"ai", "manual"}:
        raise ValueError(f"Origem de alteração inválida: {changed_by}")

    crm_lead = get_or_create_crm_lead(db, lead_id)
    previous_stage = crm_lead.stage
    next_stage = stage or previous_stage

    if reason and reason.strip():
        crm_lead.qualification_notes = reason.strip()

    stage_changed = next_stage != previous_stage
    if stage_changed:
        crm_lead.stage = next_stage
        db.flush()
        db.add(
            CrmStageHistory(
                crm_lead_id=crm_lead.id,
                from_stage=previous_stage,
                to_stage=next_stage,
                changed_by=changed_by,
            )
        )

    should_reposition = position is not None or stage_changed or crm_lead.position is None
    if should_reposition:
        target_position = 0 if position is None else position
        if stage_changed:
            _normalize_stage_positions(db, previous_stage)
        _normalize_stage_positions(db, next_stage, moving_lead=crm_lead, insert_at=target_position)

    return crm_lead


def update_crm_stage(
    db: Session,
    lead_id: int,
    stage: str,
    *,
    changed_by: str,
    reason: str | None = None,
) -> CrmLead:
    return move_crm_lead(db, lead_id, stage=stage, changed_by=changed_by, reason=reason)
