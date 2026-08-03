from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import CrmLead


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
