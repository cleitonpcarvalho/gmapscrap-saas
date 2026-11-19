"""Opt-in PostgreSQL tests. Use only a disposable GMAPSCRAP_TEST_POSTGRES_URL."""

import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from backend.database import Base
from backend.models import Lead, Niche, SearchRun

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def postgres():
    url = os.environ.get("GMAPSCRAP_TEST_POSTGRES_URL", "")
    if not url:
        pytest.skip("Set GMAPSCRAP_TEST_POSTGRES_URL to a disposable PostgreSQL database.")
    schema = f"niches_test_{uuid.uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine, schema, admin
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_script(engine, sql):
    # The checked-in scripts own their transactions, including intentional rollback.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql(sql, execution_options={"no_parameters": True})


@pytest.mark.postgres
def test_additive_migration_is_idempotent_and_secures_supabase_roles(postgres):
    engine, schema, _ = postgres
    with engine.begin() as connection:
        SearchRun.__table__.create(connection)
        Lead.__table__.create(connection)
        connection.execute(SearchRun.__table__.insert().values(id=1, niche="Brindes", location="Rio Preto"))
        connection.execute(Lead.__table__.insert().values(id=1, run_id=1, name="Empresa", address="Centro"))
        before_runs = connection.execute(select(SearchRun.__table__)).all()
        before_leads = connection.execute(select(Lead.__table__)).all()
        # Reproduce Supabase projects that grant new public tables to API roles.
        for role in ("anon", "authenticated"):
            if connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"), {"role": role}):
                connection.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT ALL ON TABLES TO "{role}"'))
                connection.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT ALL ON SEQUENCES TO "{role}"'))
    migration = (ROOT / "migrations/20261119_niches.sql").read_text().replace("public.", f'"{schema}".')
    run_script(engine, migration)
    run_script(engine, migration)
    with engine.begin() as connection:
        assert connection.execute(select(SearchRun.__table__)).all() == before_runs
        assert connection.execute(select(Lead.__table__)).all() == before_leads
        assert connection.scalar(text("SELECT relrowsecurity FROM pg_class WHERE oid = 'niches'::regclass")) is True
        connection.execute(Niche.__table__.insert().values(name="Brindes"))
        for role in ("anon", "authenticated"):
            if connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"), {"role": role}):
                assert not connection.scalar(text("SELECT has_table_privilege(:role, 'niches', 'SELECT')"), {"role": role})
                assert not connection.scalar(text("SELECT has_table_privilege(:role, 'niches', 'INSERT')"), {"role": role})


@pytest.mark.postgres
def test_startup_metadata_enforces_rls_even_if_sql_privileges_are_granted(postgres):
    engine, schema, admin = postgres
    role = f"niche_reader_{uuid.uuid4().hex}"
    Base.metadata.create_all(engine)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            connection.execute(text(f'GRANT ALL ON TABLE "{schema}".niches TO "{role}"'))
            connection.execute(text(f'GRANT ALL ON SEQUENCE "{schema}".niches_id_seq TO "{role}"'))
        with engine.begin() as connection:
            connection.execute(Niche.__table__.insert().values(name="Brindes"))
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            assert connection.execute(select(Niche.__table__)).all() == []
        with pytest.raises(DBAPIError, match="row-level security"):
            with engine.begin() as connection:
                connection.execute(text(f'SET LOCAL ROLE "{role}"'))
                connection.execute(Niche.__table__.insert().values(name="Denied"))
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{role}"'))
            connection.execute(text(f'DROP ROLE "{role}"'))


def seed_correction_data(engine):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for run_id, niche, location in [(39, "São José do Rio Preto", "Brindes"), (40, "São José do Rio Preto", "Brindes"),
            (41, "Brindes", "São José do Rio Preto"), (42, "São José do Rio Preto", "Outra cidade")]:
            connection.execute(SearchRun.__table__.insert().values(id=run_id, niche=niche, location=location, status="completed", saved_count=3))
        for lead_id in range(768, 776):
            run_id = 39 if lead_id <= 770 else 40 if lead_id <= 773 else 41 if lead_id == 774 else 42
            connection.execute(Lead.__table__.insert().values(id=lead_id, run_id=run_id, name=f"Empresa {lead_id}", address="Centro"))


@pytest.mark.postgres
def test_proposed_correction_rolls_back_by_default_and_changes_only_approved_fields(postgres):
    engine, _, _ = postgres
    seed_correction_data(engine)
    script = (ROOT / "scripts/lead_segment_correction_PROPOSED.sql").read_text()
    with engine.connect() as connection:
        before_runs = connection.execute(select(SearchRun.__table__).order_by(SearchRun.id)).mappings().all()
        before_leads = connection.execute(select(Lead.__table__).order_by(Lead.id)).all()
    run_script(engine, script)
    with engine.connect() as connection:
        assert connection.execute(select(SearchRun.__table__).order_by(SearchRun.id)).mappings().all() == before_runs
    # COMMIT is exercised exclusively against the disposable test database.
    run_script(engine, script.replace("ROLLBACK; -- Keep this default.", "COMMIT; -- Test database only."))
    with engine.connect() as connection:
        after_runs = connection.execute(select(SearchRun.__table__).order_by(SearchRun.id)).mappings().all()
        assert connection.execute(select(Lead.__table__).order_by(Lead.id)).all() == before_leads
    for before, after in zip(before_runs, after_runs):
        expected = dict(before)
        if before["id"] in (39, 40):
            expected.update(niche="Brindes", location="São José do Rio Preto")
        assert dict(after) == expected


@pytest.mark.postgres
def test_correction_refuses_changed_lead_membership(postgres):
    engine, _, _ = postgres
    seed_correction_data(engine)
    with engine.begin() as connection:
        connection.execute(Lead.__table__.insert().values(id=999, run_id=39, name="Novo lead", address="Centro"))
    script = (ROOT / "scripts/lead_segment_correction_PROPOSED.sql").read_text()
    with pytest.raises(DBAPIError, match="Lead set changed since preview"):
        run_script(engine, script)
    with engine.connect() as connection:
        assert connection.scalar(select(SearchRun.niche).where(SearchRun.id == 39)) == "São José do Rio Preto"
