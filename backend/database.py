from collections.abc import Generator
import time

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    from backend import models  # noqa: F401

    _wait_for_database()
    Base.metadata.create_all(bind=engine)
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
    }

    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
