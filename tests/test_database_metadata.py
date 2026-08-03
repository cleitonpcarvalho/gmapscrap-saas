from sqlalchemy import create_engine, inspect

from backend import models  # noqa: F401
from backend.database import Base


def test_create_all_creates_whatsapp_and_crm_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    tables = set(inspect(engine).get_table_names())

    assert {
        "whatsapp_instances",
        "whatsapp_message_templates",
        "whatsapp_campaigns",
        "whatsapp_campaign_templates",
        "whatsapp_sends",
        "whatsapp_conversations",
        "whatsapp_messages",
        "crm_leads",
        "crm_stage_history",
    }.issubset(tables)
