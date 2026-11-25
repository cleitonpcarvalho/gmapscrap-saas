"""Additive migration/security on disposable loopback databases only."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.models import Lead, WebsiteQualificationItem
from backend.services import website_qualification_jobs as jobs
from test_postgres_crm_security import postgres, PHASE1, SECURITY, run_script, data_snapshot
from scripts.production_migrations import QUALIFICATION_TABLES

MIGRATION=(Path(__file__).resolve().parents[1]/"migrations/20261125_website_qualification.sql").read_text()
pytestmark=pytest.mark.postgres


@pytest.fixture()
def pending(postgres):
    run_script(postgres,PHASE1); run_script(postgres,SECURITY)
    with postgres.begin() as c:
        for table in reversed(QUALIFICATION_TABLES): c.exec_driver_sql(f"DROP TABLE public.{table}")
    yield postgres


def test_additive_migration_preserves_every_existing_row_and_acl_and_denies_api(pending):
    before=data_snapshot(pending)
    with pending.connect() as c:
        defaults=c.exec_driver_sql("SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY oid").all()
        acls=c.exec_driver_sql("SELECT relname,relacl::text,relrowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace ORDER BY relname").all()
    for _ in range(2):
        run_script(pending,MIGRATION)
        after=data_snapshot(pending)
        for table in QUALIFICATION_TABLES: assert after.pop(table) == []
        assert after == before
        with pending.connect() as c:
            assert c.exec_driver_sql("SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY oid").all() == defaults
            current={r[0]:r for r in c.exec_driver_sql("SELECT relname,relacl::text,relrowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace")}
            assert all(current[r[0]] == r for r in acls)
            for table in QUALIFICATION_TABLES:
                assert c.scalar(text("SELECT relrowsecurity AND relowner=(SELECT oid FROM pg_roles WHERE rolname='postgres') FROM pg_class WHERE oid=to_regclass(:table)"),{"table":"public."+table})
                for role in ("anon","authenticated"):
                    assert not c.scalar(text("SELECT has_table_privilege(:role,to_regclass(:table),'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_any_column_privilege(:role,to_regclass(:table),'SELECT,INSERT,UPDATE,REFERENCES')"),{"table":"public."+table,"role":role})
    for role in ("anon","authenticated"):
        for table in QUALIFICATION_TABLES:
            with pytest.raises(DBAPIError):
                with pending.begin() as c:
                    c.exec_driver_sql(f"SET LOCAL ROLE {role}")
                    c.exec_driver_sql(f"SELECT * FROM public.{table}")


def test_existing_policy_stops_migration_for_review_without_data_changes(pending):
    run_script(pending,MIGRATION)
    with pending.begin() as c: c.exec_driver_sql("CREATE POLICY unexpected ON lead_website_qualifications FOR SELECT USING(true)")
    before=data_snapshot(pending)
    with pytest.raises(DBAPIError,match="Review website qualification"):
        run_script(pending,MIGRATION)
    assert data_snapshot(pending) == before


def test_concurrent_enqueue_has_exactly_one_active_claim_per_lead(pending):
    run_script(pending,MIGRATION)
    with Session(pending) as db: lead_id=db.scalar(select(Lead.id).order_by(Lead.id))
    barrier=Barrier(2)
    def enqueue(_):
        with Session(pending) as db:
            barrier.wait(timeout=5)
            return jobs.enqueue(db,[lead_id])
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(enqueue,range(2)))
    assert sorted(r["total"] for r in results) == [0,1]
    with Session(pending) as db:
        assert len(list(db.scalars(select(WebsiteQualificationItem).where(WebsiteQualificationItem.active_lead_id == lead_id)))) == 1
