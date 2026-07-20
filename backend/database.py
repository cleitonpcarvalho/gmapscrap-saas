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
    _ensure_search_run_columns()
    _ensure_lead_columns()
    _ensure_email_template_columns()
    _ensure_email_campaign_columns()


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
        "validate_whatsapp": "ALTER TABLE search_runs ADD COLUMN validate_whatsapp BOOLEAN NOT NULL DEFAULT FALSE",
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

    website_column = next((column for column in inspector.get_columns("leads") if column["name"] == "website"), None)
    if not website_column or website_column.get("nullable", True):
        return

    try:
        with engine.begin() as connection:
            connection.execute(text("SET lock_timeout = '10s'"))
            connection.execute(text("ALTER TABLE leads ALTER COLUMN website DROP NOT NULL"))
    except SQLAlchemyError:
        return


def _ensure_email_campaign_columns() -> None:
    inspector = inspect(engine)
    if "email_campaigns" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("email_campaigns")}
    migrations = {
        "timezone_name": "ALTER TABLE email_campaigns ADD COLUMN timezone_name VARCHAR(80) NOT NULL DEFAULT 'America/New_York'",
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
