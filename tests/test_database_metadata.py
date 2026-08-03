from sqlalchemy import create_engine, inspect

from backend import models  # noqa: F401
from backend.database import Base


def test_create_all_creates_whatsapp_and_crm_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert {
        "whatsapp_instances",
        "whatsapp_message_templates",
        "whatsapp_campaigns",
        "whatsapp_campaign_templates",
        "whatsapp_sends",
        "whatsapp_conversations",
        "whatsapp_messages",
        "whatsapp_ai_settings",
        "whatsapp_webhook_settings",
        "crm_leads",
        "crm_stage_history",
    }.issubset(tables)

    lead_columns = {column["name"] for column in inspector.get_columns("leads")}
    lead_list_columns = {column["name"] for column in inspector.get_columns("lead_lists")}

    assert "whatsapp_validated" in lead_columns
    assert "only_whatsapp_validated" in lead_list_columns
