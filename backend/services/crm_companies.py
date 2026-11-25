"""Company-level commercial overrides; no provider calls or SearchRun writes."""
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import inspect, select

from backend.models import CrmCompanyProfile
from backend.services.email_validation import validate_email_address
from backend.services.whatsapp_validation import normalize_phone_e164


def profiles_available(db):
    return inspect(db.get_bind()).has_table(CrmCompanyProfile.__tablename__)


def load_profiles(db, lead_ids):
    if not profiles_available(db):
        return None
    return {item.lead_id: item for item in db.scalars(
        select(CrmCompanyProfile).where(CrmCompanyProfile.lead_id.in_(lead_ids))
    ).all()} if lead_ids else {}


def profile_read(profile, *, available):
    phone = profile.contact_phone if profile else None
    email = profile.contact_email if profile else None
    return {
        "available": available, "version": profile.version if profile else 0,
        "niche_override": profile.niche_override if profile else None,
        "location_override": profile.location_override if profile else None,
        "contact_name": profile.contact_name if profile else None,
        "contact_phone": phone, "contact_email": email,
        "contact_call_url": "tel:" + phone if phone else "",
        "contact_whatsapp_url": "https://wa.me/" + phone.lstrip("+") if phone else "",
        "contact_email_url": "mailto:" + quote(email, safe="@.+") if email else "",
    }


def update_profile(db, lead, payload):
    """Caller locks the Lead first, serializing first inserts and company edits."""
    available = profiles_available(db)
    if payload is not None and not available:
        raise HTTPException(503, "Aplique a migração de empresas do CRM antes de editar.")
    if not available:
        return
    profile = db.scalar(select(CrmCompanyProfile).where(CrmCompanyProfile.lead_id == lead.id)
                        .with_for_update().execution_options(populate_existing=True))
    if payload is None:
        # Legacy company edits invalidate an already-open commercial editor too.
        if profile:
            profile.version += 1
        else:
            db.add(CrmCompanyProfile(lead_id=lead.id))
        return
    if payload["version"] != (profile.version if profile else 0):
        raise HTTPException(409, "A empresa foi alterada. Atualize os detalhes antes de salvar.")
    values = {key: value or None for key, value in payload.items() if key != "version"}
    if values.get("contact_phone"):
        normalized = normalize_phone_e164(values["contact_phone"], f"{lead.address} {lead.location}")
        if not normalized:
            raise HTTPException(422, "Telefone do contato inválido. Informe o código do país e DDD.")
        values["contact_phone"] = normalized
    if values.get("contact_email"):
        validation = validate_email_address(values["contact_email"], check_dns=False)
        if not validation.is_valid:
            raise HTTPException(422, "E-mail do contato inválido.")
        values["contact_email"] = validation.normalized_email
    if profile is None:
        profile = CrmCompanyProfile(lead_id=lead.id)
        db.add(profile)
    else:
        profile.version += 1
    for key, value in values.items():
        setattr(profile, key, value)
