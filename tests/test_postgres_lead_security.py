"""Real PG17 security regressions; disposable localhost:55489 databases ONLY.

Set GMAPSCRAP_TEST_LEAD_SECURITY_URL to the dedicated security_admin cluster.
Optional GMAPSCRAP_TEST_POSTGREST_BIN enables real, localhost-only REST checks.
No production settings, Supabase keys or production endpoints are used by tests.
"""
import base64
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import main, manual_crm
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import Base, get_db
from backend.models import CrmActivity, CrmFollowUp, CrmLead, CrmStageHistory, Lead, LeadTag, SearchRun, Tag
from backend.scrapers.maps_scraper import MapLead
from backend.schemas import SearchRunRead
from backend.services.crm import get_default_crm_funnel
from backend.services.jobs import _save_row

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "migrations/20261124_lead_security.sql").read_text()
COMPANIES = ROOT / "migrations/20261124_crm_company_profiles.sql"
TABLES = ["leads", "search_runs", "lead_tags", "tags"]
SEQUENCES = ["leads_id_seq", "search_runs_id_seq", "tags_id_seq"]
pytestmark = pytest.mark.postgres


def run_script(engine, script=MIGRATION):
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        try:
            connection.exec_driver_sql(script, execution_options={"no_parameters": True})
        finally:
            connection.exec_driver_sql("ROLLBACK")


@pytest.fixture
def secured_database():
    configured = os.environ.get("GMAPSCRAP_TEST_LEAD_SECURITY_URL", "")
    if not configured:
        pytest.skip("Use disposable security_admin PostgreSQL on localhost:55489")
    url = make_url(configured)
    assert url.host in {"localhost", "127.0.0.1"} and url.port == 55489
    assert url.username == "security_admin" and url.database == "postgres" and not url.query
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "gmapscrap_lead_security_test_" + uuid.uuid4().hex
    owner = None
    leaks = []
    try:
        with admin.connect() as c:
            assert c.scalar(text("SELECT current_user")) == "security_admin"
            assert int(c.scalar(text("SHOW server_version_num"))) >= 170000
            for role, flags in {
                "postgres": "NOLOGIN NOSUPERUSER BYPASSRLS CREATEROLE CREATEDB",
                "service_role": "NOLOGIN NOSUPERUSER BYPASSRLS",
                "anon": "NOLOGIN NOSUPERUSER NOBYPASSRLS",
                "authenticated": "NOLOGIN NOSUPERUSER NOBYPASSRLS",
                "authenticator": "LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS",
                "supabase_admin": "NOLOGIN NOSUPERUSER NOBYPASSRLS",
            }.items():
                if not c.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}):
                    c.exec_driver_sql(f'CREATE ROLE "{role}" {flags}')
            c.exec_driver_sql("GRANT anon,authenticated,service_role TO authenticator")
            c.exec_driver_sql(f'CREATE DATABASE "{name}" OWNER postgres')
        owner = create_engine(url.set(database=name).update_query_dict({"options": "-crole=postgres"}))
        with owner.begin() as c:
            c.exec_driver_sql("GRANT USAGE ON SCHEMA public TO anon,authenticated,service_role")
            for kind in ["TABLES", "SEQUENCES"]:
                c.exec_driver_sql(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON {kind} TO anon,authenticated,service_role")
        # Provider-owned defaults deliberately remain outside migration scope.
        database_admin = create_engine(url.set(database=name))
        with database_admin.begin() as c:
            for kind in ["TABLES", "SEQUENCES"]:
                c.exec_driver_sql(f"ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON {kind} TO anon,authenticated,service_role")
        Base.metadata.create_all(owner)
        with Session(owner) as db:
            funnel = get_default_crm_funnel(db)
            run = SearchRun(niche="Histórico original", location="Fortaleza", status="completed", saved_count=3)
            leads = [Lead(search_run=run, name=f"Empresa sintética {i}", address="Centro", phone="+5585999990000") for i in range(3)]
            tag = Tag(name="Histórica")
            db.add_all([*leads, tag]); db.flush()
            db.add(LeadTag(lead_id=leads[0].id, tag_id=tag.id))
            card = CrmLead(lead_id=leads[0].id, funnel_id=funnel.id, stage_id=funnel.stages[0].id,
                stage="new", position=0, managed_manually=True, qualification_notes="Preservar nota",
                estimated_value=Decimal("321.09"), sales_outcome="open")
            db.add(card); db.flush()
            db.add(CrmActivity(crm_lead_id=card.id, kind="note", body="Preservar atividade", actor="local"))
            db.add(CrmFollowUp(crm_lead_id=card.id, title="Preservar retorno", due_at=datetime(2026,12,1,tzinfo=timezone.utc)))
            db.add(CrmStageHistory(crm_lead_id=card.id, from_stage="responded", to_stage="new", changed_by="manual"))
            db.commit()
        with owner.begin() as c:
            for table in TABLES:
                col = "lead_id" if table == "lead_tags" else "id"
                c.exec_driver_sql(f"GRANT ALL ON public.{table} TO PUBLIC,anon,authenticated")
                c.exec_driver_sql(f"GRANT SELECT({col}),INSERT({col}),UPDATE({col}),REFERENCES({col}) ON public.{table} TO PUBLIC,anon,authenticated")
            for seq in SEQUENCES:
                c.exec_driver_sql(f"GRANT ALL ON SEQUENCE public.{seq} TO PUBLIC,anon,authenticated")
            c.exec_driver_sql("CREATE TABLE public.lead_security_unrelated(id serial PRIMARY KEY,label text)")
            c.exec_driver_sql("INSERT INTO public.lead_security_unrelated(label) VALUES ('preserve')")
        yield owner, database_admin, leaks
    finally:
        if owner:
            owner.dispose()
        if 'database_admin' in locals():
            database_admin.dispose()
        with admin.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            for role in leaks:
                c.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
        admin.dispose()


def fingerprints(engine):
    result = {}
    with engine.connect() as c:
        for name in c.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")):
            rows = sorted(value.encode() for value in c.scalars(text(f'SELECT to_jsonb(t)::text FROM public."{name}" t')))
            h = hashlib.sha256()
            for row in rows:
                h.update(len(row).to_bytes(8, "big")); h.update(row)
            result[name] = (len(rows), h.hexdigest())
    return result


def metadata(engine):
    with engine.connect() as c:
        return {
            "columns": c.execute(text("SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum")).all(),
            "constraints": c.execute(text("SELECT conrelid,conname,convalidated,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conrelid,conname")).all(),
            "indexes": c.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY indexname")).all(),
            "sequences": {name: c.execute(text(f'SELECT last_value,is_called FROM public."{name}"')).one() for name in c.scalars(text("SELECT sequencename FROM pg_sequences WHERE schemaname='public'"))},
            "objects": c.execute(text("SELECT relname,relowner,relrowsecurity,relforcerowsecurity,relacl::text FROM pg_class WHERE relnamespace='public'::regnamespace ORDER BY relname")).all(),
            "column_acls": c.execute(text("SELECT attrelid,attnum,attacl::text FROM pg_attribute WHERE attrelid IN (SELECT oid FROM pg_class WHERE relnamespace='public'::regnamespace) ORDER BY attrelid,attnum")).all(),
            "defaults": c.execute(text("SELECT pg_get_userbyid(defaclrole),defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY defaclrole,defaclnamespace,defaclobjtype")).all(),
            "roles": c.execute(text("SELECT rolname,rolsuper,rolbypassrls,rolinherit FROM pg_roles ORDER BY rolname")).all(),
        }


def assert_secured(engine):
    with engine.connect() as c:
        for table in TABLES:
            assert c.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:table)"), {"table": "public."+table}).one() == (True,False)
            for role in ["anon", "authenticated"]:
                p = {"role": role, "table": "public."+table}
                assert not c.scalar(text("SELECT has_table_privilege(:role,:table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')"), p)
                assert not c.scalar(text("SELECT has_any_column_privilege(:role,:table,'SELECT,INSERT,UPDATE,REFERENCES')"), p)
            for role in ["postgres", "service_role"]:
                for privilege in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
                    assert c.scalar(text("SELECT has_table_privilege(:role,:table,:privilege)"), {"role":role,"table":"public."+table,"privilege":privilege})
        for seq in SEQUENCES:
            for role in ["anon", "authenticated"]:
                assert not c.scalar(text("SELECT has_sequence_privilege(:role,:seq,'USAGE,SELECT,UPDATE')"), {"role":role,"seq":"public."+seq})


def test_repeatability_preserves_all_rows_relationships_sequences_and_unrelated_metadata(secured_database):
    owner, _, _ = secured_database
    before, schema = fingerprints(owner), metadata(owner)
    for _ in range(2):
        run_script(owner)
        assert fingerprints(owner) == before
        assert_secured(owner)
        after = metadata(owner)
        for key in ["columns", "constraints", "indexes", "sequences", "roles"]:
            assert after[key] == schema[key]
        assert [r for r in after['objects'] if r.relname not in TABLES+SEQUENCES] == [r for r in schema['objects'] if r.relname not in TABLES+SEQUENCES]
        assert [r for r in after['defaults'] if r[0] != 'postgres'] == [r for r in schema['defaults'] if r[0] != 'postgres']
        if _ == 0:
            first = after
        else:
            assert after == first
    with owner.connect() as c:
        assert c.scalar(text("SELECT has_table_privilege('anon','public.lead_security_unrelated','SELECT')"))


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_api_roles_cannot_read_write_or_use_sequences(secured_database, role):
    owner, _, _ = secured_database
    run_script(owner)
    before, schema = fingerprints(owner), metadata(owner)
    statements = []
    for table in TABLES:
        col = "lead_id" if table == "lead_tags" else "id"
        statements += [f"SELECT {col} FROM public.{table}", f"INSERT INTO public.{table} DEFAULT VALUES",
            f"UPDATE public.{table} SET {col}={col} WHERE false", f"DELETE FROM public.{table} WHERE false", f"TRUNCATE public.{table}"]
    for seq in SEQUENCES:
        statements += [f"SELECT nextval('public.{seq}')", f"SELECT setval('public.{seq}',99999)", f"SELECT last_value FROM public.{seq}"]
    for statement in statements:
        with pytest.raises(DBAPIError) as error:
            with owner.begin() as c:
                c.exec_driver_sql(f'SET LOCAL ROLE "{role}"'); c.exec_driver_sql(statement)
        assert error.value.orig.sqlstate == "42501", statement
    assert fingerprints(owner) == before and metadata(owner) == schema


def test_new_postgres_objects_are_private_but_service_role_and_other_creators_preserved(secured_database):
    owner, _, _ = secured_database
    run_script(owner)
    with owner.begin() as c:
        c.exec_driver_sql("CREATE TABLE public.lead_security_future(id serial PRIMARY KEY)")
        for role in ["anon", "authenticated"]:
            assert not c.scalar(text("SELECT has_table_privilege(:role,'public.lead_security_future','SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')"), {"role":role})
            assert not c.scalar(text("SELECT has_sequence_privilege(:role,'public.lead_security_future_id_seq','USAGE,SELECT,UPDATE')"), {"role":role})
        assert c.scalar(text("SELECT has_table_privilege('service_role','public.lead_security_future','INSERT')"))
        assert c.scalar(text("SELECT has_sequence_privilege('service_role','public.lead_security_future_id_seq','USAGE')"))


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_rls_still_denies_rows_after_an_accidental_table_regrant(secured_database, role):
    owner, _, _ = secured_database
    run_script(owner)
    before = fingerprints(owner)
    with owner.begin() as c:
        c.exec_driver_sql(f'GRANT SELECT,INSERT ON public.tags TO "{role}"')
    with owner.begin() as c:
        c.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
        assert c.exec_driver_sql('SELECT * FROM public.tags').all() == []
    with pytest.raises(DBAPIError, match="row-level security"):
        with owner.begin() as c:
            c.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
            c.exec_driver_sql("INSERT INTO public.tags(id,name,color) VALUES(99999,'Forbidden','#ffffff')")
    run_script(owner)
    assert_secured(owner)
    assert fingerprints(owner) == before


@pytest.mark.parametrize("change,message", [
    ("CREATE POLICY unexpected ON leads FOR SELECT USING(true)", "existing lead RLS policies"),
    ("CREATE VIEW public.exposed_leads AS SELECT id FROM leads; GRANT SELECT ON public.exposed_leads TO anon", "exposed dependent view"),
    ("CREATE FUNCTION public.exposed_leads() RETURNS bigint LANGUAGE SQL SECURITY DEFINER AS 'SELECT count(*) FROM public.leads'", "SECURITY DEFINER"),
    ("ALTER TABLE public.leads FORCE ROW LEVEL SECURITY", "without FORCE RLS"),
    ("ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO anon", "global postgres"),
])
def test_unsafe_schema_or_global_defaults_abort_atomically(secured_database, change, message):
    owner, _, _ = secured_database
    with owner.begin() as c:
        c.exec_driver_sql(change)
    before, schema = fingerprints(owner), metadata(owner)
    with pytest.raises(DBAPIError, match=message):
        run_script(owner)
    assert fingerprints(owner) == before and metadata(owner) == schema


@pytest.mark.parametrize("grant", ["SELECT ON leads", "USAGE ON SEQUENCE leads_id_seq", "DEFAULTS"])
def test_inherited_access_aborts_and_restores_defaults_rls_and_all_acls(secured_database, grant):
    owner, admin, leaks = secured_database
    role = "lead_security_leak_" + uuid.uuid4().hex
    leaks.append(role)
    with admin.begin() as c:
        c.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')
        c.exec_driver_sql(f'GRANT "{role}" TO anon')
    with owner.begin() as c:
        statement = f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO "{role}"' if grant == "DEFAULTS" else f'GRANT {grant} TO "{role}"'
        c.exec_driver_sql(statement)
    before, schema = fingerprints(owner), metadata(owner)
    with pytest.raises(DBAPIError, match="inherited grants"):
        run_script(owner)
    assert fingerprints(owner) == before and metadata(owner) == schema


def test_renamed_owned_sequence_is_protected(secured_database):
    owner, _, _ = secured_database
    with owner.begin() as c:
        c.exec_driver_sql("ALTER SEQUENCE public.leads_id_seq RENAME TO unusual_lead_counter")
    before = fingerprints(owner)
    run_script(owner); run_script(owner)
    assert fingerprints(owner) == before
    with owner.connect() as c:
        assert not c.scalar(text("SELECT has_sequence_privilege('anon','public.unusual_lead_counter','USAGE,SELECT,UPDATE')"))
        assert c.scalar(text("SELECT has_sequence_privilege('service_role','public.unusual_lead_counter','USAGE')"))


def test_wrong_role_and_concurrent_run_leave_everything_unchanged(secured_database):
    owner, admin, _ = secured_database
    before, schema = fingerprints(owner), metadata(owner)
    with pytest.raises(DBAPIError, match="effective postgres owner"):
        run_script(admin)
    with admin.connect() as lock:
        lock.exec_driver_sql("SELECT pg_advisory_lock(hashtext('gmapscrap_lead_security_20261124'))")
        try:
            with pytest.raises(DBAPIError, match="already running"):
                run_script(owner)
        finally:
            lock.exec_driver_sql("SELECT pg_advisory_unlock(hashtext('gmapscrap_lead_security_20261124'))")
    assert fingerprints(owner) == before and metadata(owner) == schema


@pytest.mark.parametrize("privilege", ["UPDATE", "TRUNCATE", "MAINTAIN"])
def test_missing_trusted_privilege_aborts_without_silently_widening_access(secured_database, privilege):
    owner, _, _ = secured_database
    with owner.begin() as c:
        c.exec_driver_sql(f"REVOKE {privilege} ON public.leads FROM service_role")
    before, schema = fingerprints(owner), metadata(owner)
    with pytest.raises(DBAPIError, match="Expected backend service_role privilege "+privilege):
        run_script(owner)
    assert fingerprints(owner) == before and metadata(owner) == schema


def test_busy_table_aborts_and_rolls_back(secured_database):
    owner, admin, _ = secured_database
    before, schema = fingerprints(owner), metadata(owner)
    with admin.begin() as blocking:
        blocking.exec_driver_sql("LOCK TABLE public.leads IN ACCESS SHARE MODE")
        with pytest.raises(DBAPIError) as error:
            run_script(owner)
        assert error.value.orig.sqlstate == "55P03"
    assert fingerprints(owner) == before and metadata(owner) == schema


@pytest.mark.parametrize("role", ["postgres", "service_role"])
def test_backend_scraping_and_status_writes_remain_available(secured_database, role):
    owner, _, _ = secured_database
    run_script(owner)
    db_role = create_engine(owner.url.update_query_dict({"options":"-crole="+role}))
    try:
        with Session(db_role) as db:
            run = db.get(SearchRun, 1)
            assert _save_row(db, run, MapLead(name="Novo coletado",address="Centro",phone="+5585999990000",website="https://example.test/local"), "https://example.test/local", "")
            assert not _save_row(db, run, MapLead(name="Duplicado",address="Centro",phone="",website="https://example.test/local"), "https://example.test/local", "")
            assert len(db.scalars(select(Lead)).all()) == 4
            for state in ["paused", "running", "stopped"]:
                run.status = state; db.commit(); db.refresh(run)
                assert run.id == 1 and run.status == state
            assert run.niche == "Histórico original" and run.location == "Fortaleza"
    finally:
        db_role.dispose()


def test_crm_company_api_tags_and_search_history_remain_compatible(secured_database, monkeypatch):
    if not COMPANIES.is_file() or "commercial_profile" not in main.LeadUpdate.model_fields:
        pytest.skip("Optional pending company-profile feature is not present in this checkout")
    owner, _, _ = secured_database
    run_script(owner); run_script(owner, COMPANIES.read_text())
    app = FastAPI(); app.include_router(manual_crm.router)
    app.add_api_route("/api/leads/{lead_id}", main.update_lead, methods=["PATCH"])
    app.add_api_route("/api/searches/{run_id}", main.get_search, methods=["GET"], response_model=SearchRunRead)
    app.add_api_route("/api/searches/{run_id}/pause", main.pause_search, methods=["POST"], response_model=SearchRunRead)
    app.add_api_route("/api/searches/{run_id}/resume", main.resume_search, methods=["POST"], response_model=SearchRunRead)
    def local_db():
        with Session(owner) as db:
            yield db
    app.dependency_overrides[get_db] = local_db
    monkeypatch.setattr(main, "submit_search_job", lambda run_id: False)
    with owner.connect() as c:
        history = c.execute(text("SELECT to_jsonb(t)::text FROM search_runs t ORDER BY id")).all()
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME,create_session_token(get_settings().app_username))
        before = client.get("/api/crm/manual/cards/1").json()
        page = client.get("/api/crm/manual/leads",params={"tag_ids":1}).json()
        assert page['total'] == 1
        selected = client.get("/api/crm/manual/lead-selection",params={"funnel_id":1}).json()
        assert selected['total'] == 2 and len(selected['lead_ids']) == 2
        response = client.patch("/api/leads/1",json={"name":"Empresa revisada","commercial_profile":{"version":0,"niche_override":"Comercial","location_override":"Recife","contact_name":"Representante"}})
        assert response.status_code == 200, response.text
        after = client.get("/api/crm/manual/cards/1").json()
        assert after['lead']['provenance'] == before['lead']['provenance']
        assert after['lead']['tags'] == before['lead']['tags']
        for key in before.keys()-{'lead'}:
            assert before[key] == after[key]
        assert client.get("/api/searches/1").status_code == 200
        with owner.begin() as c:
            c.exec_driver_sql("UPDATE search_runs SET status='running' WHERE id=1")
        assert client.post("/api/searches/1/pause").json()['status'] == 'paused'
        assert client.post("/api/searches/1/resume").json()['status'] == 'running'
    with owner.connect() as c:
        # Lifecycle status legitimately changed; scraping provenance did not.
        assert c.execute(text("SELECT niche,location FROM search_runs WHERE id=1")).one() == ('Histórico original','Fortaleza')
        assert c.scalar(text("SELECT run_id FROM leads WHERE id=1")) == 1
        assert len(history) == c.scalar(text("SELECT count(*) FROM search_runs"))


def test_real_rest_blocks_anonymous_and_authenticated_browsers(secured_database, tmp_path):
    binary = os.environ.get("GMAPSCRAP_TEST_POSTGREST_BIN", "")
    if not binary:
        pytest.skip("Set GMAPSCRAP_TEST_POSTGREST_BIN to run real isolated REST checks")
    owner, _, _ = secured_database
    secret = "gmapscrap-isolated-security-test-secret-not-production"
    def jwt(role):
        encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b'=')
        message = encode(b'{"alg":"HS256","typ":"JWT"}')+b'.'+encode(json.dumps({"role":role,"exp":int(time.time())+300}).encode())
        return (message+b'.'+encode(hmac.new(secret.encode(),message,hashlib.sha256).digest())).decode()
    env = {k:v for k,v in os.environ.items() if not k.startswith('PGRST_')}
    env.update(PGRST_DB_URI=f"postgresql://authenticator@127.0.0.1:55489/{owner.url.database}",
        PGRST_DB_ANON_ROLE="anon",PGRST_DB_SCHEMAS="public",PGRST_JWT_SECRET=secret,
        PGRST_SERVER_HOST="127.0.0.1",PGRST_SERVER_PORT="55490",PGRST_DB_POOL="2")
    with (tmp_path/'postgrest.log').open('wb') as log:
        process = subprocess.Popen([binary],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url="http://127.0.0.1:55490",timeout=10) as client:
                for _ in range(100):
                    assert process.poll() is None, (tmp_path/'postgrest.log').read_text()
                    try:
                        if client.get('/leads?select=id&limit=1').status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(.1)
                else:
                    pytest.fail('Isolated PostgREST did not start')
                before = fingerprints(owner)
                run_script(owner); run_script(owner)
                for role in [None,'anon','authenticated']:
                    headers = {} if role is None else {'Authorization':'Bearer '+jwt(role)}
                    for table in TABLES:
                        key = 'lead_id' if table == 'lead_tags' else 'id'
                        for method in ['GET','POST','PATCH','DELETE']:
                            response = client.request(method,'/'+table,params={key:'eq.1'},headers=headers,
                                json={key:99999} if method in ['POST','PATCH'] else None)
                            assert response.status_code in [401,403], (role,table,method,response.text)
                            assert response.json()['code'] == '42501'
                for table in TABLES:
                    assert client.get('/'+table+'?limit=1',headers={'Authorization':'Bearer '+jwt('service_role')}).status_code == 200
                assert fingerprints(owner) == before
        finally:
            process.terminate()
            process.wait(timeout=10)
