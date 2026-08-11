from sqlalchemy import create_engine, inspect, text

from backend import models  # noqa: F401
from backend import database
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
        "crm_funnels",
        "crm_funnel_stages",
        "crm_leads",
        "crm_stage_history",
        "tags",
        "lead_tags",
    }.issubset(tables)

    lead_columns = {column["name"] for column in inspector.get_columns("leads")}
    search_run_columns = {column["name"] for column in inspector.get_columns("search_runs")}
    lead_list_columns = {column["name"] for column in inspector.get_columns("lead_lists")}
    email_campaign_columns = {column["name"] for column in inspector.get_columns("email_campaigns")}
    email_send_columns = {column["name"] for column in inspector.get_columns("email_sends")}
    whatsapp_campaign_columns = {column["name"] for column in inspector.get_columns("whatsapp_campaigns")}
    crm_funnel_columns = {column["name"] for column in inspector.get_columns("crm_funnels")}
    crm_funnel_stage_columns = {column["name"] for column in inspector.get_columns("crm_funnel_stages")}
    crm_lead_columns = {column["name"] for column in inspector.get_columns("crm_leads")}
    crm_stage_history_columns = {column["name"] for column in inspector.get_columns("crm_stage_history")}
    tag_columns = {column["name"] for column in inspector.get_columns("tags")}
    lead_tag_columns = {column["name"] for column in inspector.get_columns("lead_tags")}

    assert {"id", "name", "description", "is_default", "created_at"}.issubset(crm_funnel_columns)
    assert {"id", "funnel_id", "key", "label", "color", "description", "position", "is_won", "is_lost"}.issubset(
        crm_funnel_stage_columns
    )
    assert {"funnel_id", "stage_id", "position"}.issubset(crm_lead_columns)
    assert {"from_stage_id", "to_stage_id"}.issubset(crm_stage_history_columns)
    assert "position" in crm_lead_columns
    assert {"id", "name", "color", "description", "created_at"}.issubset(tag_columns)
    assert {"lead_id", "tag_id", "origin", "created_at"}.issubset(lead_tag_columns)
    assert "whatsapp_validated" in lead_columns
    assert "whatsapp_validated_at" in lead_columns
    assert "whatsapp_validation_status" in lead_columns
    assert "whatsapp_validation_reason" in lead_columns
    assert "site_insights" in lead_columns
    assert "only_without_website" in search_run_columns
    assert "enrich_site_insights" in search_run_columns
    assert "only_whatsapp_validated" in lead_list_columns
    assert "only_email_opened" in lead_list_columns
    assert "only_email_clicked" in lead_list_columns
    assert "email_engagement_filter_mode" in lead_list_columns
    assert "channel" in lead_list_columns
    assert "message_mode" in email_campaign_columns
    assert "objective" in email_campaign_columns
    assert "language" in email_campaign_columns
    assert "language" in whatsapp_campaign_columns
    assert "funnel_id" in whatsapp_campaign_columns
    assert "auto_apply_tags_enabled" in {column["name"] for column in inspector.get_columns("whatsapp_ai_settings")}
    assert "generated_content" in email_send_columns


def test_ensure_crm_lead_columns_backfills_position_by_current_order(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE crm_leads (
                    id INTEGER PRIMARY KEY,
                    lead_id INTEGER NOT NULL,
                    stage VARCHAR(30) NOT NULL,
                    qualification_notes TEXT,
                    score INTEGER,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO crm_leads (id, lead_id, stage, updated_at)
                VALUES
                    (1, 101, 'new', '2026-01-01 10:00:00'),
                    (2, 102, 'new', '2026-01-03 10:00:00'),
                    (3, 103, 'new', '2026-01-02 10:00:00'),
                    (4, 201, 'qualified', '2026-01-01 10:00:00'),
                    (5, 202, 'qualified', '2026-01-04 10:00:00')
                """
            )
        )

    monkeypatch.setattr(database, "engine", engine)

    database._ensure_crm_lead_columns()

    inspector = inspect(engine)
    crm_lead_columns = {column["name"] for column in inspector.get_columns("crm_leads")}
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT lead_id, stage, position FROM crm_leads ORDER BY stage ASC, position ASC")
        ).all()

    assert "position" in crm_lead_columns
    assert rows == [
        (102, "new", 0),
        (103, "new", 1),
        (101, "new", 2),
        (202, "qualified", 0),
        (201, "qualified", 1),
    ]


def test_ensure_tag_tables_adds_and_backfills_lead_tag_origin(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE tags (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    color VARCHAR(7) NOT NULL DEFAULT '#e0f2fe',
                    description VARCHAR(500),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE lead_tags (
                    lead_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (lead_id, tag_id)
                )
                """
            )
        )
        connection.execute(text("INSERT INTO tags (id, name, color) VALUES (1, 'Manual', '#e0f2fe')"))
        connection.execute(text("INSERT INTO lead_tags (lead_id, tag_id) VALUES (10, 1)"))

    monkeypatch.setattr(database, "engine", engine)

    database._ensure_tag_tables()

    inspector = inspect(engine)
    lead_tag_columns = {column["name"] for column in inspector.get_columns("lead_tags")}
    with engine.connect() as connection:
        origin = connection.execute(text("SELECT origin FROM lead_tags WHERE lead_id = 10 AND tag_id = 1")).scalar_one()

    assert "origin" in lead_tag_columns
    assert origin == "manual"


def test_ensure_crm_funnel_tables_adds_stage_description(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE crm_funnels (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    description VARCHAR(500),
                    is_default BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE crm_funnel_stages (
                    id INTEGER NOT NULL PRIMARY KEY,
                    funnel_id INTEGER NOT NULL,
                    key VARCHAR(60) NOT NULL,
                    label VARCHAR(120) NOT NULL,
                    color VARCHAR(7) NOT NULL,
                    position INTEGER NOT NULL,
                    is_won BOOLEAN NOT NULL DEFAULT 0,
                    is_lost BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )

    monkeypatch.setattr(database, "engine", engine)

    database._ensure_crm_funnel_tables()

    inspector = inspect(engine)
    stage_columns = {column["name"] for column in inspector.get_columns("crm_funnel_stages")}
    with engine.connect() as connection:
        default_description = connection.execute(
            text("SELECT description FROM crm_funnel_stages WHERE key = 'qualified'")
        ).scalar_one()

    assert "description" in stage_columns
    assert default_description == "Lead demonstrou dor, necessidade ou encaixe claro com a oferta."
