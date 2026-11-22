"""Migration/security integration in a newly created disposable LOCAL database."""
import os
from pathlib import Path
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import database, manual_crm
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import Base, get_db
from backend.models import CrmFunnelStage, Lead, LeadTag, SearchRun, Tag
from backend.services.crm import get_default_crm_funnel


@pytest.mark.postgres
def test_versioned_manual_crm_migration_preservation_rls_and_immutable_history():
    configured = os.getenv("GMAPSCRAP_TEST_POSTGRES_URL", "")
    if not configured:
        pytest.skip("Requires an explicitly isolated local PostgreSQL test server")
    url = make_url(configured)
    # This test creates/drops a database; never accept a remote/prod destination.
    assert url.host in {"127.0.0.1", "localhost"} and url.port == 55488
    name = "gmapscrap_manual_test_" + uuid.uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
            connection.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF; IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF; END $$"))
        engine = create_engine(url.set(database=name))
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in {"crm_activities","crm_follow_ups"}])
        with Session(engine) as db:
            funnel = get_default_crm_funnel(db)
            stage = next(item for item in funnel.stages if item.key == "converted")
            stage.label = "Etapa personalizada"; stage.position = 12; stage.description = "Preservar"
            run = SearchRun(niche="Brindes",location="Fortaleza",status="completed",saved_count=2)
            first = Lead(search_run=run,name="Legado",address="Fortaleza",phone="+5585999990001")
            second = Lead(search_run=run,name="Novo",address="Fortaleza",phone="+5585999990002")
            tag = Tag(name="Prioridade")
            db.add_all([first,second,tag]); db.flush()
            db.add(LeadTag(lead_id=first.id,tag_id=tag.id))
            db.commit()
            funnel_id, stage_id, first_id, second_id = funnel.id, stage.id, first.id, second.id
        with engine.begin() as connection:
            # Reconstruct the pre-feature CRM table after fixture ORM work.
            for column in ["managed_manually","estimated_value","currency","sales_outcome","lost_reason","closed_at","version"]:
                connection.execute(text(f'ALTER TABLE crm_leads DROP COLUMN "{column}" CASCADE'))
            connection.execute(text("INSERT INTO crm_leads (lead_id,funnel_id,stage_id,stage,qualification_notes,position) VALUES (:lead,:funnel,:stage,'converted','Nota histórica',0)"),dict(lead=first_id,funnel=funnel_id,stage=stage_id))
            connection.execute(text("INSERT INTO crm_stage_history (crm_lead_id,from_stage,to_stage,changed_by) VALUES (1,'new','converted','ai')"))
        names = ["leads","search_runs","tags","lead_tags","crm_funnels","crm_funnel_stages","crm_stage_history"]
        def snapshots():
            with engine.connect() as connection:
                return {table:sorted(connection.scalars(text(f"SELECT to_jsonb(t)::text FROM public.{table} t")).all()) for table in names}
        before = snapshots()
        legacy_columns = "ARRAY['managed_manually','estimated_value','currency','sales_outcome','lost_reason','closed_at','version']"
        def legacy_card_snapshot():
            with engine.connect() as connection:
                return connection.scalar(text(f"SELECT (to_jsonb(t) - {legacy_columns})::text FROM crm_leads t WHERE id=1"))
        legacy_before = legacy_card_snapshot()
        migration = (Path(__file__).parents[1]/"migrations/20261121_manual_crm_phase1.sql").read_text()
        for _ in range(2):
            raw = engine.raw_connection()
            try:
                raw.driver_connection.autocommit = True
                raw.cursor().execute(migration)
            finally:
                raw.close()
            assert snapshots() == before
            assert legacy_card_snapshot() == legacy_before
        with engine.connect() as connection:
            legacy = connection.execute(text("SELECT managed_manually,sales_outcome,estimated_value,qualification_notes FROM crm_leads WHERE id=1")).one()
            assert tuple(legacy) == (False,None,None,"Nota histórica")
            for table in ["crm_activities","crm_follow_ups"]:
                assert connection.scalar(text("SELECT relrowsecurity FROM pg_class WHERE oid=cast(:table AS regclass)"),{"table":"public."+table})
                for role in ["anon","authenticated"]:
                    assert not connection.scalar(text("SELECT has_table_privilege(:role,:table,'SELECT,INSERT,UPDATE,DELETE')"),{"role":role,"table":"public."+table})
                    assert not connection.scalar(text("SELECT has_sequence_privilege(:role,:sequence,'USAGE')"),{"role":role,"sequence":f"public.{table}_id_seq"})
        # Startup seeding must preserve all custom stage fields as well.
        with engine.begin() as connection:
            database._ensure_default_crm_funnel_stages(connection,funnel_id)
        assert snapshots() == before
        assert legacy_card_snapshot() == legacy_before
        app = FastAPI(); app.include_router(manual_crm.router)
        def local_db():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = local_db
        with TestClient(app) as client:
            client.cookies.set(COOKIE_NAME,create_session_token(get_settings().app_username))
            added = client.post("/api/crm/manual/cards",json={"lead_ids":[second_id],"funnel_id":funnel_id,"stage_id":stage_id})
            assert added.status_code == 200, added.text
            card_id = added.json()["created_card_ids"][0]
            detail = client.get(f"/api/crm/manual/cards/{card_id}").json()
            assert detail["sales_outcome"] == "open"  # Even a won-flagged legacy stage is not revenue.
            note = client.post(f"/api/crm/manual/cards/{card_id}/activities",json={"kind":"note","body":"Nova nota permanente"})
            assert note.status_code == 201
            follow = client.post(f"/api/crm/manual/cards/{card_id}/follow-ups",json={"title":"Retornar","due_at":"2026-12-01T09:00:00-03:00"})
            assert follow.status_code == 201
            assert follow.json()["due_at"].startswith("2026-12-01T12:00:00")
        for statement in ["UPDATE crm_activities SET body='bad'", "DELETE FROM crm_activities", "TRUNCATE crm_activities"]:
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    connection.execute(text(statement))
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM leads WHERE id=:id"),{"id":second_id})
        assert snapshots() == before
        assert legacy_card_snapshot() == legacy_before
    finally:
        if engine:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
