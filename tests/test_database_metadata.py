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
        "whatsapp_portfolio_items",
        "whatsapp_webhook_settings",
        "crm_leads",
        "crm_stage_history",
    }.issubset(tables)

    lead_columns = {column["name"] for column in inspector.get_columns("leads")}
    search_run_columns = {column["name"] for column in inspector.get_columns("search_runs")}
    lead_list_columns = {column["name"] for column in inspector.get_columns("lead_lists")}
    email_campaign_columns = {column["name"] for column in inspector.get_columns("email_campaigns")}
    email_send_columns = {column["name"] for column in inspector.get_columns("email_sends")}

    assert "whatsapp_validated" in lead_columns
    assert "site_insights" in lead_columns
    assert "only_without_website" in search_run_columns
    assert "enrich_site_insights" in search_run_columns
    assert "only_whatsapp_validated" in lead_list_columns
    assert "only_email_opened" in lead_list_columns
    assert "only_email_clicked" in lead_list_columns
    assert "email_engagement_filter_mode" in lead_list_columns
    assert "message_mode" in email_campaign_columns
    assert "objective" in email_campaign_columns
    assert "generated_content" in email_send_columns
