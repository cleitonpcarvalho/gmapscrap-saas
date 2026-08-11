from collections.abc import Generator
import time

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def _database_url() -> str | URL:
    if settings.db_host and settings.db_name and settings.db_user:
        query = {}
        if settings.db_sslmode:
            query["sslmode"] = settings.db_sslmode

        return URL.create(
            "postgresql+psycopg",
            username=settings.db_user,
            password=settings.db_password,
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            query=query,
        )

    if settings.database_url.startswith("postgresql://"):
        return settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    return settings.database_url


engine = create_engine(_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    from backend import models  # noqa: F401

    _wait_for_database()
    Base.metadata.create_all(bind=engine)
    _ensure_tag_tables()
    _ensure_whatsapp_crm_tables()
    _ensure_crm_lead_columns()
    _ensure_whatsapp_ai_settings_columns()
    _ensure_whatsapp_campaign_columns()
    _ensure_whatsapp_send_columns()
    _ensure_whatsapp_conversation_columns()
    _ensure_search_run_columns()
    _ensure_lead_columns()
    _ensure_lead_list_columns()
    _ensure_email_template_columns()
    _ensure_email_campaign_columns()
    _ensure_email_send_columns()


def _ensure_whatsapp_crm_tables() -> None:
    from backend.models import (
        CrmLead,
        CrmStageHistory,
        WhatsAppAiSettings,
        WhatsAppCampaign,
        WhatsAppCampaignTemplate,
        WhatsAppConversation,
        WhatsAppInstance,
        WhatsAppMessage,
        WhatsAppMessageTemplate,
        WhatsAppPortfolioItem,
        WhatsAppWebhookSettings,
        WhatsAppSend,
    )

    Base.metadata.create_all(
        bind=engine,
        tables=[
            WhatsAppInstance.__table__,
            WhatsAppMessageTemplate.__table__,
            WhatsAppCampaign.__table__,
            WhatsAppCampaignTemplate.__table__,
            WhatsAppSend.__table__,
            WhatsAppConversation.__table__,
            WhatsAppMessage.__table__,
            WhatsAppAiSettings.__table__,
            WhatsAppPortfolioItem.__table__,
            WhatsAppWebhookSettings.__table__,
            CrmLead.__table__,
            CrmStageHistory.__table__,
        ],
    )


def _ensure_tag_tables() -> None:
    from backend.models import LeadTag, Tag

    Base.metadata.create_all(bind=engine, tables=[Tag.__table__, LeadTag.__table__])

    inspector = inspect(engine)
    if "tags" not in inspector.get_table_names():
        return

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SET lock_timeout = '10s'"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_lower_name ON tags (lower(name))"))


def _ensure_crm_lead_columns() -> None:
    inspector = inspect(engine)
    if "crm_leads" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("crm_leads")}
    position_missing = "position" not in existing_columns

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SET lock_timeout = '10s'"))
        if position_missing:
            connection.execute(text("ALTER TABLE crm_leads ADD COLUMN position INTEGER"))
        _backfill_crm_lead_positions(connection, reset=position_missing)


def _backfill_crm_lead_positions(connection, *, reset: bool = False) -> None:
    if reset:
        rows = connection.execute(
            text("SELECT id, stage FROM crm_leads ORDER BY stage ASC, updated_at DESC, id DESC")
        ).mappings()
        positions_by_stage: dict[str, int] = {}
        for row in rows:
            stage = str(row["stage"])
            position = positions_by_stage.get(stage, 0)
            connection.execute(
                text("UPDATE crm_leads SET position = :position WHERE id = :id"),
                {"position": position, "id": row["id"]},
            )
            positions_by_stage[stage] = position + 1
        return

    stages = connection.execute(text("SELECT DISTINCT stage FROM crm_leads WHERE position IS NULL")).scalars()
    for stage in stages:
        max_position = connection.execute(
            text("SELECT MAX(position) FROM crm_leads WHERE stage = :stage AND position IS NOT NULL"),
            {"stage": stage},
        ).scalar()
        next_position = int(max_position) + 1 if max_position is not None else 0
        rows = connection.execute(
            text(
                "SELECT id FROM crm_leads "
                "WHERE stage = :stage AND position IS NULL "
                "ORDER BY updated_at DESC, id DESC"
            ),
            {"stage": stage},
        ).mappings()
        for row in rows:
            connection.execute(
                text("UPDATE crm_leads SET position = :position WHERE id = :id"),
                {"position": next_position, "id": row["id"]},
            )
            next_position += 1


def _ensure_whatsapp_conversation_columns() -> None:
    inspector = inspect(engine)
    if "whatsapp_conversations" not in inspector.get_table_names():
        return

    lead_id_column = next(
        (column for column in inspector.get_columns("whatsapp_conversations") if column["name"] == "lead_id"),
        None,
    )
    if not lead_id_column or lead_id_column.get("nullable", True):
        return

    try:
        with engine.begin() as connection:
            connection.execute(text("SET lock_timeout = '10s'"))
            connection.execute(text("ALTER TABLE whatsapp_conversations ALTER COLUMN lead_id DROP NOT NULL"))
    except SQLAlchemyError:
        return


def _ensure_whatsapp_ai_settings_columns() -> None:
    inspector = inspect(engine)
    if "whatsapp_ai_settings" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("whatsapp_ai_settings")}
    migrations = {
        "services_description": (
            "ALTER TABLE whatsapp_ai_settings "
            "ADD COLUMN services_description TEXT NOT NULL DEFAULT ''"
        ),
    }
    missing_migrations = {
        column_name: statement
        for column_name, statement in migrations.items()
        if column_name not in existing_columns
    }
    if not missing_migrations:
        return

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SET lock_timeout = '10s'"))
        for statement in missing_migrations.values():
            connection.execute(text(statement))


def _ensure_whatsapp_campaign_columns() -> None:
    inspector = inspect(engine)
    if "whatsapp_campaigns" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("whatsapp_campaigns")}
    migrations = {
        "objective": "ALTER TABLE whatsapp_campaigns ADD COLUMN objective TEXT NOT NULL DEFAULT ''",
        "message_mode": "ALTER TABLE whatsapp_campaigns ADD COLUMN message_mode VARCHAR(30) NOT NULL DEFAULT 'template'",
        "language": "ALTER TABLE whatsapp_campaigns ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'pt'",
    }
    missing_migrations = {
        column_name: statement
        for column_name, statement in migrations.items()
        if column_name not in existing_columns
    }
    if not missing_migrations:
        return

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SET lock_timeout = '10s'"))
        for statement in missing_migrations.values():
            connection.execute(text(statement))


def _ensure_whatsapp_send_columns() -> None:
    inspector = inspect(engine)
    if "whatsapp_sends" not in inspector.get_table_names():
        return

    columns = inspector.get_columns("whatsapp_sends")
    existing_columns = {column["name"] for column in columns}
    migrations = {
        "generated_content": "ALTER TABLE whatsapp_sends ADD COLUMN generated_content TEXT",
    }
    missing_migrations = {
        column_name: statement
        for column_name, statement in migrations.items()
        if column_name not in existing_columns
    }

    template_id_column = next((column for column in columns if column["name"] == "template_id"), None)
    should_drop_template_not_null = bool(template_id_column and not template_id_column.get("nullable", True))

    if not missing_migrations and not should_drop_template_not_null:
        return

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SET lock_timeout = '10s'"))
        for statement in missing_migrations.values():
            connection.execute(text(statement))
        if should_drop_template_not_null and engine.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE whatsapp_sends ALTER COLUMN template_id DROP NOT NULL"))


def _wait_for_database(max_attempts: int = 30, delay_seconds: int = 2) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except OperationalError:
            if attempt == max_attempts:
                raise
            time.sleep(delay_seconds)


def _ensure_email_template_columns() -> None:
    inspector = inspect(engine)
    if "email_templates" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("email_templates")}
    migrations = {
        "logo_url": "ALTER TABLE email_templates ADD COLUMN logo_url VARCHAR(1000) NOT NULL DEFAULT ''",
        "primary_color": "ALTER TABLE email_templates ADD COLUMN primary_color VARCHAR(20) NOT NULL DEFAULT '#0a0a0a'",
        "text_color": "ALTER TABLE email_templates ADD COLUMN text_color VARCHAR(20) NOT NULL DEFAULT '#333333'",
        "background_color": "ALTER TABLE email_templates ADD COLUMN background_color VARCHAR(20) NOT NULL DEFAULT '#f4f4f4'",
        "content_button_text": (
            "ALTER TABLE email_templates ADD COLUMN content_button_text VARCHAR(200) "
            "NOT NULL DEFAULT 'Open the content'"
        ),
        "contact_mailto_subject": (
            "ALTER TABLE email_templates ADD COLUMN contact_mailto_subject VARCHAR(300) "
            "NOT NULL DEFAULT 'Automation and integration help'"
        ),
        "contact_mailto_body": (
            "ALTER TABLE email_templates ADD COLUMN contact_mailto_body TEXT "
            "NOT NULL DEFAULT 'Hi Cleiton, I saw your email about automation for {{company_name}} "
            "and would like to learn more.'"
        ),
    }

    with engine.begin() as connection:
        connection.execute(text("SET lock_timeout = '10s'"))
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_search_run_columns() -> None:
    inspector = inspect(engine)
    if "search_runs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("search_runs")}
    migrations = {
        "skip_without_website": "ALTER TABLE search_runs ADD COLUMN skip_without_website BOOLEAN NOT NULL DEFAULT TRUE",
        "only_without_website": "ALTER TABLE search_runs ADD COLUMN only_without_website BOOLEAN NOT NULL DEFAULT FALSE",
        "validate_whatsapp": "ALTER TABLE search_runs ADD COLUMN validate_whatsapp BOOLEAN NOT NULL DEFAULT FALSE",
        "enrich_site_insights": "ALTER TABLE search_runs ADD COLUMN enrich_site_insights BOOLEAN NOT NULL DEFAULT FALSE",
    }

    with engine.begin() as connection:
        connection.execute(text("SET lock_timeout = '10s'"))
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_lead_columns() -> None:
    inspector = inspect(engine)
    if "leads" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("leads")}

    try:
        with engine.begin() as connection:
            connection.execute(text("SET lock_timeout = '10s'"))
            if "whatsapp_validated" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN whatsapp_validated BOOLEAN"))
                connection.execute(
                    text(
                        "UPDATE leads "
                        "SET whatsapp_validated = TRUE "
                        "FROM search_runs "
                        "WHERE leads.run_id = search_runs.id "
                        "AND search_runs.validate_whatsapp = TRUE "
                        "AND leads.whatsapp_validated IS NULL"
                    )
                )
            if "whatsapp_validated_at" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_validated_at TIMESTAMP WITH TIME ZONE"))
            if "whatsapp_validation_status" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_validation_status VARCHAR(30)"))
            if "whatsapp_validation_reason" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_validation_reason VARCHAR(80)"))
            connection.execute(
                text(
                    "UPDATE leads "
                    "SET whatsapp_validation_status = 'valid', "
                    "whatsapp_validated_at = COALESCE(whatsapp_validated_at, created_at) "
                    "WHERE whatsapp_validated = TRUE "
                    "AND (whatsapp_validation_status IS NULL OR whatsapp_validated_at IS NULL)"
                )
            )
            if "site_insights" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN site_insights TEXT"))

            website_column = next((column for column in inspector.get_columns("leads") if column["name"] == "website"), None)
            if website_column and not website_column.get("nullable", True):
                connection.execute(text("ALTER TABLE leads ALTER COLUMN website DROP NOT NULL"))
    except SQLAlchemyError:
        return


def _ensure_lead_list_columns() -> None:
    inspector = inspect(engine)
    if "lead_lists" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("lead_lists")}
    migrations = {
        "only_whatsapp_validated": (
            "ALTER TABLE lead_lists ADD COLUMN only_whatsapp_validated BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        "only_email_opened": (
            "ALTER TABLE lead_lists ADD COLUMN only_email_opened BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        "only_email_clicked": (
            "ALTER TABLE lead_lists ADD COLUMN only_email_clicked BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        "email_engagement_filter_mode": (
            "ALTER TABLE lead_lists ADD COLUMN email_engagement_filter_mode VARCHAR(10) NOT NULL DEFAULT 'or'"
        ),
        "channel": (
            "ALTER TABLE lead_lists ADD COLUMN channel VARCHAR(10) NOT NULL DEFAULT 'both'"
        ),
    }

    with engine.begin() as connection:
        connection.execute(text("SET lock_timeout = '10s'"))
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_email_campaign_columns() -> None:
    inspector = inspect(engine)
    if "email_campaigns" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("email_campaigns")}
    migrations = {
        "timezone_name": "ALTER TABLE email_campaigns ADD COLUMN timezone_name VARCHAR(80) NOT NULL DEFAULT 'America/New_York'",
        "objective": "ALTER TABLE email_campaigns ADD COLUMN objective TEXT NOT NULL DEFAULT ''",
        "message_mode": "ALTER TABLE email_campaigns ADD COLUMN message_mode VARCHAR(30) NOT NULL DEFAULT 'template'",
        "language": "ALTER TABLE email_campaigns ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'pt'",
    }

    with engine.begin() as connection:
        connection.execute(text("SET lock_timeout = '10s'"))
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_email_send_columns() -> None:
    inspector = inspect(engine)
    if "email_sends" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("email_sends")}
    migrations = {
        "generated_content": "ALTER TABLE email_sends ADD COLUMN generated_content TEXT",
    }

    with engine.begin() as connection:
        connection.execute(text("SET lock_timeout = '10s'"))
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
