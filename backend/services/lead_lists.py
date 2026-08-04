from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from backend.models import EmailSend, Lead, LeadEmailPreference, LeadList, SearchRun
from backend.services.text_normalization import LIST_FILTER_SEPARATOR

LIST_CHANNEL_EMAIL = "email"
LIST_CHANNEL_WHATSAPP = "whatsapp"
LIST_CHANNEL_BOTH = "both"
LIST_CHANNELS = (LIST_CHANNEL_EMAIL, LIST_CHANNEL_WHATSAPP, LIST_CHANNEL_BOTH)


def split_list_filter(value: str) -> list[str]:
    if not value:
        return []

    if LIST_FILTER_SEPARATOR in value:
        return [item.strip() for item in value.split(LIST_FILTER_SEPARATOR) if item.strip()]

    return [value.strip()] if value.strip() else []


def _opened_email_leads_stmt():
    return select(EmailSend.lead_id).where(or_(EmailSend.open_count > 0, EmailSend.opened_at.is_not(None)))


def _clicked_email_leads_stmt():
    return select(EmailSend.lead_id).where(or_(EmailSend.click_count > 0, EmailSend.clicked_at.is_not(None)))


def _apply_email_engagement_filter(stmt, lead_list: LeadList):
    if not lead_list.only_email_opened and not lead_list.only_email_clicked:
        return stmt

    opened_stmt = _opened_email_leads_stmt()
    clicked_stmt = _clicked_email_leads_stmt()

    if lead_list.only_email_opened and lead_list.only_email_clicked:
        if lead_list.email_engagement_filter_mode == "and":
            return stmt.where(Lead.id.in_(opened_stmt), Lead.id.in_(clicked_stmt))
        return stmt.where(or_(Lead.id.in_(opened_stmt), Lead.id.in_(clicked_stmt)))

    if lead_list.only_email_opened:
        return stmt.where(Lead.id.in_(opened_stmt))

    return stmt.where(Lead.id.in_(clicked_stmt))


def lead_query_for_list(lead_list: LeadList, channel: str):
    """Build the lead query for a lead_lists row, scoped to a send/count channel.

    `channel` controls which contact method is required and whether e-mail-only
    extras (engagement, do-not-contact, template history) apply — it is the
    context the query is used in (an email send, a WhatsApp send, or the count
    shown for a "both" list), not necessarily `lead_list.channel` itself.
    """
    stmt = (
        select(Lead)
        .join(SearchRun)
        .options(selectinload(Lead.search_run))
        .order_by(Lead.created_at)
    )

    if channel == LIST_CHANNEL_EMAIL:
        stmt = stmt.where(Lead.email != "")
    elif channel == LIST_CHANNEL_WHATSAPP:
        stmt = stmt.where(Lead.phone != "")

    niche_filters = split_list_filter(lead_list.niche_filter)
    if niche_filters:
        stmt = stmt.where(or_(*(SearchRun.niche.ilike(f"%{value}%") for value in niche_filters)))

    location_filters = split_list_filter(lead_list.location_filter)
    if location_filters:
        stmt = stmt.where(or_(*(SearchRun.location.ilike(f"%{value}%") for value in location_filters)))

    if lead_list.search_run_id:
        stmt = stmt.where(Lead.run_id == lead_list.search_run_id)

    if lead_list.only_whatsapp_validated:
        stmt = stmt.where(Lead.whatsapp_validated.is_(True))

    if channel == LIST_CHANNEL_EMAIL:
        stmt = _apply_email_engagement_filter(stmt, lead_list)

        blocked_stmt = select(LeadEmailPreference.lead_id).where(LeadEmailPreference.do_not_contact.is_(True))
        stmt = stmt.where(~Lead.id.in_(blocked_stmt))

        if lead_list.only_never_emailed:
            sent_stmt = select(EmailSend.lead_id).where(EmailSend.status == "sent")
            stmt = stmt.where(~Lead.id.in_(sent_stmt))

        if lead_list.never_received_template_id:
            template_sent_stmt = select(EmailSend.lead_id).where(
                EmailSend.template_id == lead_list.never_received_template_id,
                EmailSend.status.in_(("pending", "sent")),
            )
            stmt = stmt.where(~Lead.id.in_(template_sent_stmt))

    return stmt


def count_leads_for_list(db: Session, lead_list: LeadList, channel: str) -> int:
    return len(db.scalars(lead_query_for_list(lead_list, channel)).all())
