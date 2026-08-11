from __future__ import annotations

import inspect as py_inspect
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from backend import database


def _postgres_test_url() -> str:
    url = os.getenv("GMAPSCRAP_TEST_POSTGRES_URL", "").strip()
    if not url and os.getenv("RUN_POSTGRES_MIGRATION_TESTS") == "1":
        url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url if url.startswith("postgresql+psycopg://") else ""


def test_default_funnel_insert_does_not_depend_on_sqlite_lastrowid() -> None:
    source = py_inspect.getsource(database._ensure_default_crm_funnel)

    assert "lastrowid" not in source
    assert "RETURNING id" in source


@pytest.mark.postgres
def test_crm_funnel_migration_runs_against_real_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    postgres_url = _postgres_test_url()
    if not postgres_url:
        pytest.skip("Defina GMAPSCRAP_TEST_POSTGRES_URL para rodar este teste contra PostgreSQL real.")

    schema_name = f"crm_migration_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(postgres_url)
    test_engine = None

    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    except OperationalError as exc:
        admin_engine.dispose()
        pytest.skip(f"PostgreSQL indisponível para teste de migração: {exc}")

    try:
        test_engine = create_engine(postgres_url, connect_args={"options": f"-csearch_path={schema_name}"})
        legacy_stages = ["new", "responded", "qualified", "not_interested", "converted"]
        with test_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE crm_funnels (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(120) NOT NULL,
                        description VARCHAR(500),
                        is_default BOOLEAN NOT NULL DEFAULT false,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE crm_funnel_stages (
                        id SERIAL PRIMARY KEY,
                        funnel_id INTEGER NOT NULL REFERENCES crm_funnels(id) ON DELETE CASCADE,
                        key VARCHAR(60) NOT NULL,
                        label VARCHAR(120) NOT NULL,
                        color VARCHAR(7) NOT NULL,
                        position INTEGER NOT NULL,
                        is_won BOOLEAN NOT NULL DEFAULT false,
                        is_lost BOOLEAN NOT NULL DEFAULT false
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE crm_leads (
                        id INTEGER PRIMARY KEY,
                        lead_id INTEGER NOT NULL,
                        stage VARCHAR(30) NOT NULL,
                        qualification_notes TEXT,
                        score INTEGER,
                        updated_at TIMESTAMP,
                        position INTEGER,
                        CONSTRAINT legacy_unique_lead_only_weird_name UNIQUE (lead_id),
                        CONSTRAINT legacy_stage_check_weird_name
                            CHECK (stage IN ('new', 'responded', 'qualified', 'not_interested', 'converted'))
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE crm_stage_history (
                        id INTEGER PRIMARY KEY,
                        crm_lead_id INTEGER NOT NULL,
                        from_stage VARCHAR(30) NOT NULL,
                        to_stage VARCHAR(30) NOT NULL,
                        changed_at TIMESTAMP,
                        changed_by VARCHAR(20) NOT NULL,
                        CONSTRAINT legacy_history_from_stage_check_weird_name
                            CHECK (from_stage IN ('new', 'responded', 'qualified', 'not_interested', 'converted')),
                        CONSTRAINT legacy_history_to_stage_check_weird_name
                            CHECK (to_stage IN ('new', 'responded', 'qualified', 'not_interested', 'converted')),
                        CONSTRAINT ck_crm_stage_history_changed_by CHECK (changed_by IN ('ai', 'manual'))
                    )
                    """
                )
            )
            for index in range(9):
                connection.execute(
                    text(
                        "INSERT INTO crm_leads (id, lead_id, stage, updated_at, position) "
                        "VALUES (:id, :lead_id, :stage, :updated_at, :position)"
                    ),
                    {
                        "id": index + 1,
                        "lead_id": 501 + index,
                        "stage": legacy_stages[index % len(legacy_stages)],
                        "updated_at": f"2026-01-{index + 1:02d}",
                        "position": index,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO crm_stage_history (id, crm_lead_id, from_stage, to_stage, changed_at, changed_by) "
                    "VALUES (1, 1, 'new', 'qualified', '2026-01-01', 'manual')"
                )
            )

        monkeypatch.setattr(database, "engine", test_engine)

        database._ensure_crm_lead_columns()
        database._ensure_crm_lead_columns()

        with test_engine.begin() as connection:
            default_funnel = connection.execute(
                text("SELECT id, name FROM crm_funnels WHERE is_default IS TRUE")
            ).mappings().one()
            default_stages = connection.execute(
                text(
                    "SELECT key, label, is_won, is_lost "
                    "FROM crm_funnel_stages WHERE funnel_id = :funnel_id ORDER BY position"
                ),
                {"funnel_id": default_funnel["id"]},
            ).mappings().all()
            cards = connection.execute(
                text("SELECT lead_id, funnel_id, stage_id, stage FROM crm_leads ORDER BY id")
            ).mappings().all()
            history = connection.execute(
                text("SELECT from_stage_id, to_stage_id FROM crm_stage_history WHERE id = 1")
            ).mappings().one()

            assert default_funnel["name"] == database.DEFAULT_CRM_FUNNEL_NAME
            assert [stage["key"] for stage in default_stages] == ["new", "responded", "qualified", "not_interested", "converted"]
            assert default_stages[3]["is_lost"] is True
            assert default_stages[4]["is_won"] is True
            assert len(cards) == 9
            assert {card["lead_id"] for card in cards} == set(range(501, 510))
            assert all(card["funnel_id"] == default_funnel["id"] for card in cards)
            assert all(card["stage_id"] is not None for card in cards)
            assert history["from_stage_id"] is not None
            assert history["to_stage_id"] is not None

            custom_funnel_id = connection.execute(
                text(
                    "INSERT INTO crm_funnels (name, description, is_default) "
                    "VALUES ('Funil customizado', '', false) RETURNING id"
                )
            ).scalar_one()
            custom_stage_id = connection.execute(
                text(
                    "INSERT INTO crm_funnel_stages "
                    "(funnel_id, key, label, color, position, is_won, is_lost) "
                    "VALUES (:funnel_id, 'custom_stage', 'Custom', '#e0f2fe', 0, false, false) "
                    "RETURNING id"
                ),
                {"funnel_id": custom_funnel_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO crm_leads (id, lead_id, funnel_id, stage_id, stage, updated_at) "
                    "VALUES (100, 501, :funnel_id, :stage_id, 'custom_stage', '2026-01-10')"
                ),
                {"funnel_id": custom_funnel_id, "stage_id": custom_stage_id},
            )
            card_count = connection.execute(text("SELECT COUNT(*) FROM crm_leads WHERE lead_id = 501")).scalar_one()
            default_count = connection.execute(text("SELECT COUNT(*) FROM crm_funnels WHERE is_default IS TRUE")).scalar_one()
            stage_count = connection.execute(text("SELECT COUNT(*) FROM crm_funnel_stages")).scalar_one()

        assert card_count == 2
        assert default_count == 1
        assert stage_count == 6
    finally:
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()
