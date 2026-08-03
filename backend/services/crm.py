from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import CrmLead, CrmStageHistory


CRM_STAGES = {"new", "responded", "qualified", "not_interested", "converted"}


def get_or_create_crm_lead(db: Session, lead_id: int, *, stage: str = "new") -> CrmLead:
    if stage not in CRM_STAGES:
        raise ValueError(f"Estágio de CRM inválido: {stage}")

    crm_lead = db.scalar(select(CrmLead).where(CrmLead.lead_id == lead_id))
    if crm_lead:
        return crm_lead

    crm_lead = CrmLead(lead_id=lead_id, stage=stage)
    db.add(crm_lead)
    db.flush()
    return crm_lead


def update_crm_stage(
    db: Session,
    lead_id: int,
    stage: str,
    *,
    changed_by: str,
    reason: str | None = None,
) -> CrmLead:
    if stage not in CRM_STAGES:
        raise ValueError(f"Estágio de CRM inválido: {stage}")
    if changed_by not in {"ai", "manual"}:
        raise ValueError(f"Origem de alteração inválida: {changed_by}")

    crm_lead = get_or_create_crm_lead(db, lead_id)
    if reason and reason.strip():
        crm_lead.qualification_notes = reason.strip()

    if stage != crm_lead.stage:
        previous_stage = crm_lead.stage
        crm_lead.stage = stage
        db.flush()
        db.add(
            CrmStageHistory(
                crm_lead_id=crm_lead.id,
                from_stage=previous_stage,
                to_stage=stage,
                changed_by=changed_by,
            )
        )

    return crm_lead
