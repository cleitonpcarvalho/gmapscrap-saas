"""Security-only migration tests. Destructive fixtures accept LOCAL port 55488 only."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import manual_crm
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import Base, get_db
from backend.models import CrmLead, CrmStageHistory, Lead, LeadTag, SearchRun, Tag
from backend.services.crm import get_default_crm_funnel

ROOT = Path(__file__).resolve().parents[1]
SECURITY = (ROOT / "migrations/20261121_crm_security.sql").read_text()
PHASE1 = (ROOT / "migrations/20261121_manual_crm_phase1.sql").read_text()
TABLES = ["crm_funnels","crm_funnel_stages","crm_leads","crm_stage_history"]
LEGACY_REF = "fa3871aa43fc38988112c8eafbd63b84ffb69b85"
pytestmark = pytest.mark.postgres


def run_script(engine, script):
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        try:
            connection.exec_driver_sql(script, execution_options={"no_parameters":True})
        finally:
            # An explicit BEGIN in a failed script must not poison the pool.
            connection.exec_driver_sql("ROLLBACK")


@pytest.fixture()
def postgres():
    configured = os.getenv("GMAPSCRAP_TEST_POSTGRES_URL", "")
    if not configured:
        pytest.skip("Set GMAPSCRAP_TEST_POSTGRES_URL to isolated local port 55488")
    url = make_url(configured)
    assert url.host in {"127.0.0.1","localhost"} and url.port == 55488
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "gmapscrap_crm_security_test_" + uuid.uuid4().hex
    engine = None
    try:
        with admin.connect() as connection:
            for role in ["postgres","anon","authenticated","service_role"]:
                if not connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:role"),{"role":role}):
                    connection.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS')
            assert not connection.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname='postgres'"))
            connection.exec_driver_sql(f'CREATE DATABASE "{name}" OWNER postgres')
        owner_url = url.set(database=name).update_query_dict({"options":"-crole=postgres"})
        engine = create_engine(owner_url)
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in {"crm_activities","crm_follow_ups"}])
        with Session(engine) as db:
            funnel = get_default_crm_funnel(db)
            run = SearchRun(niche="Brindes",location="Fortaleza",status="completed",saved_count=12)
            leads = [Lead(search_run=run,name=f"Empresa sintética {i}",address="Centro",phone=f"+5585999990{i:03d}") for i in range(12)]
            tag = Tag(name="Prioridade")
            db.add_all([*leads,tag]);db.flush()
            db.add(LeadTag(lead_id=leads[0].id,tag_id=tag.id))
            cards = [CrmLead(lead_id=lead.id,funnel_id=funnel.id,stage_id=funnel.stages[0].id,stage="new",position=i,qualification_notes=f"Nota histórica {i}" if i<4 else None) for i,lead in enumerate(leads[:9])]
            db.add_all(cards);db.flush()
            db.add_all(CrmStageHistory(crm_lead_id=cards[i].id,from_stage="responded",to_stage="new",changed_by="ai" if i<4 else "manual") for i in range(7))
            db.commit()
        with engine.begin() as connection:
            # Model fixtures first, then reconstruct the currently deployed schema.
            for column in ["managed_manually","estimated_value","currency","sales_outcome","lost_reason","closed_at","version"]:
                connection.exec_driver_sql(f'ALTER TABLE crm_leads DROP COLUMN "{column}" CASCADE')
            for kind in ["TABLES","SEQUENCES","FUNCTIONS"]:
                connection.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON {kind} TO anon,authenticated,service_role')
            connection.exec_driver_sql('GRANT USAGE ON SCHEMA public TO anon,authenticated,service_role')
            for table in TABLES:
                connection.exec_driver_sql(f'GRANT ALL ON TABLE public.{table} TO PUBLIC,anon,authenticated,service_role')
                connection.exec_driver_sql(f'GRANT SELECT(id),INSERT(id),UPDATE(id),REFERENCES(id) ON public.{table} TO PUBLIC,anon,authenticated')
                connection.exec_driver_sql(f'GRANT ALL ON SEQUENCE public.{table}_id_seq TO PUBLIC,anon,authenticated,service_role')
            connection.exec_driver_sql('CREATE TABLE public.crm_security_unrelated(id serial PRIMARY KEY,label text)')
            connection.exec_driver_sql("INSERT INTO public.crm_security_unrelated(label) VALUES ('unrelated preserved')")
            connection.exec_driver_sql("CREATE FUNCTION public.crm_security_unrelated_function() RETURNS integer LANGUAGE SQL AS 'SELECT 123'")
        yield engine
    finally:
        if engine: engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()


def data_snapshot(engine):
    with engine.connect() as c:
        names = c.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).all()
        return {name:sorted(c.scalars(text(f'SELECT to_jsonb(t)::text FROM public."{name}" t')).all()) for name in names}


def schema_snapshot(engine):
    with engine.connect() as c:
        return {
            "columns":c.execute(text("SELECT table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")).all(),
            "constraints":c.execute(text("SELECT conrelid,conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conrelid,conname")).all(),
            "indexes":c.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY indexname")).all(),
            "sequence_state":{name:c.execute(text(f'SELECT last_value,is_called FROM public."{name}"')).one() for name in c.scalars(text("SELECT sequencename FROM pg_sequences WHERE schemaname='public'")).all()},
            "default_acls":c.execute(text("SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY oid")).all(),
            "policies":c.execute(text("SELECT * FROM pg_policies WHERE schemaname='public' ORDER BY tablename,policyname")).all(),
        }


def permission_snapshot(engine):
    with engine.connect() as c:
        return {
            'relations':c.execute(text("SELECT relname,relrowsecurity,relforcerowsecurity,relacl::text FROM pg_class WHERE relnamespace='public'::regnamespace ORDER BY relname")).all(),
            'columns':c.execute(text("SELECT attrelid,attnum,attacl::text FROM pg_attribute WHERE attrelid IN (SELECT oid FROM pg_class WHERE relnamespace='public'::regnamespace) ORDER BY attrelid,attnum")).all(),
            'routines':c.execute(text("SELECT oid,proacl::text FROM pg_proc WHERE pronamespace='public'::regnamespace ORDER BY oid")).all(),
        }


def assert_secured(engine):
    with engine.connect() as c:
        for table in TABLES:
            assert c.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=cast(:table AS regclass)"),{"table":"public."+table}).one() == (True,False)
            for role in ["anon","authenticated"]:
                p={"role":role,"table":"public."+table,"sequence":"public."+table+"_id_seq"}
                assert not c.scalar(text("SELECT has_table_privilege(:role,:table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"),p)
                assert not c.scalar(text("SELECT has_any_column_privilege(:role,:table,'SELECT,INSERT,UPDATE,REFERENCES')"),p)
                assert not c.scalar(text("SELECT has_sequence_privilege(:role,:sequence,'USAGE,SELECT,UPDATE')"),p)
            assert c.scalar(text("SELECT has_table_privilege('postgres',:table,'SELECT,INSERT,UPDATE,DELETE')"),{"table":"public."+table})
            assert not c.scalar(text("SELECT EXISTS(SELECT FROM pg_class cl CROSS JOIN LATERAL aclexplode(cl.relacl) acl WHERE cl.oid=cast(:table AS regclass) AND acl.grantee=0)"),{"table":"public."+table})
            assert not c.scalar(text("SELECT EXISTS(SELECT FROM pg_attribute a CROSS JOIN LATERAL aclexplode(a.attacl) acl WHERE a.attrelid=cast(:table AS regclass) AND acl.grantee=0)"),{"table":"public."+table})


def test_security_migration_preserves_every_row_relationship_sequence_and_default_acl(postgres):
    before, metadata = data_snapshot(postgres),schema_snapshot(postgres)
    for _ in range(2):
        run_script(postgres, SECURITY)
        assert data_snapshot(postgres) == before
        assert schema_snapshot(postgres) == metadata
        assert_secured(postgres)
    with postgres.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM crm_leads")) == 9
        assert c.scalar(text("SELECT count(*) FROM crm_stage_history")) == 7
        assert c.scalar(text("SELECT count(*) FROM crm_leads WHERE qualification_notes IS NOT NULL")) == 4
        # Existing out-of-scope access and trusted service_role are not revoked.
        assert c.scalar(text("SELECT has_table_privilege('anon','public.crm_security_unrelated','SELECT')"))
        assert c.scalar(text("SELECT has_table_privilege('service_role','public.crm_leads','SELECT')"))


@pytest.mark.parametrize("role",["anon","authenticated"])
def test_browser_roles_cannot_read_write_truncate_reference_trigger_or_advance_crm_sequences(postgres,role):
    run_script(postgres, SECURITY)
    assert_secured(postgres)
    before, metadata = data_snapshot(postgres),schema_snapshot(postgres)
    for table in TABLES:
        statements = [f'SELECT id FROM public.{table}',f'INSERT INTO public.{table}(id) VALUES (99999)',
            f'UPDATE public.{table} SET id=id WHERE false',f'DELETE FROM public.{table} WHERE false',
            f'TRUNCATE public.{table}',f"SELECT nextval('public.{table}_id_seq')",f"SELECT setval('public.{table}_id_seq',99999)"]
        for statement in statements:
            with pytest.raises(DBAPIError) as error:
                with postgres.begin() as c:
                    c.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
                    c.exec_driver_sql(statement)
            assert error.value.orig.sqlstate == "42501",statement
    assert data_snapshot(postgres) == before
    assert schema_snapshot(postgres) == metadata
    # Even a later accidental table grant cannot bypass deny-by-default RLS.
    with postgres.begin() as c: c.exec_driver_sql(f'GRANT SELECT,INSERT ON crm_leads TO "{role}"')
    with postgres.begin() as c:
        c.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
        assert c.exec_driver_sql('SELECT * FROM crm_leads').all() == []
    with pytest.raises(DBAPIError,match="row-level security"):
        with postgres.begin() as c:
            c.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
            c.exec_driver_sql("INSERT INTO crm_leads(id,lead_id,funnel_id,stage_id,stage) SELECT 99999,12,1,1,'new'")
    run_script(postgres, SECURITY)
    assert_secured(postgres)


def test_related_rpc_trigger_and_transitive_functions_are_secured_without_body_changes(postgres):
    with postgres.begin() as c:
        c.exec_driver_sql("CREATE FUNCTION public.crm_security_count() RETURNS bigint LANGUAGE SQL SECURITY DEFINER SET search_path='' BEGIN ATOMIC SELECT count(*) FROM public.crm_leads; END")
        c.exec_driver_sql("CREATE FUNCTION public.crm_security_wrapper() RETURNS bigint LANGUAGE SQL SECURITY DEFINER BEGIN ATOMIC SELECT public.crm_security_count(); END")
        c.exec_driver_sql("CREATE FUNCTION public.crm_security_text_count() RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$BEGIN RETURN (SELECT count(*) FROM public.crm_leads); END$$")
        c.exec_driver_sql("CREATE FUNCTION public.crm_security_touch() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NEW; END$$")
        c.exec_driver_sql('CREATE TRIGGER crm_security_touch BEFORE UPDATE ON crm_leads FOR EACH ROW EXECUTE FUNCTION public.crm_security_touch()')
        before = c.execute(text("SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='public'::regnamespace ORDER BY proname")).all()
    run_script(postgres, SECURITY);run_script(postgres, SECURITY)
    with postgres.connect() as c:
        assert c.execute(text("SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='public'::regnamespace ORDER BY proname")).all() == before
        assert c.scalar(text('SELECT public.crm_security_wrapper()')) == 9
        assert c.scalar(text('SELECT public.crm_security_text_count()')) == 9
        for role in ["anon","authenticated"]:
            for fn in ["crm_security_count","crm_security_wrapper","crm_security_text_count","crm_security_touch"]:
                assert not c.scalar(text("SELECT has_function_privilege(:role,:fn,'EXECUTE')"),{"role":role,"fn":f"public.{fn}()"})
            assert c.scalar(text("SELECT has_function_privilege(:role,'public.crm_security_unrelated_function()','EXECUTE')"),{"role":role})
    with pytest.raises(DBAPIError) as error:
        with postgres.begin() as c:
            c.exec_driver_sql('SET LOCAL ROLE anon');c.exec_driver_sql('SELECT public.crm_security_wrapper()')
    assert error.value.orig.sqlstate == "42501"


def test_security_migration_discovers_renamed_sequences(postgres):
    with postgres.begin() as c:c.exec_driver_sql('ALTER SEQUENCE public.crm_leads_id_seq RENAME TO unusual_card_counter')
    before=schema_snapshot(postgres)
    run_script(postgres,SECURITY)
    assert schema_snapshot(postgres)==before
    with postgres.connect() as c:
        assert not c.scalar(text("SELECT has_sequence_privilege('anon','public.unusual_card_counter','USAGE,SELECT,UPDATE')"))
        assert c.scalar(text("SELECT has_sequence_privilege('postgres','public.unusual_card_counter','USAGE')"))


def test_inherited_grants_fail_closed_and_roll_back_all_security_changes(postgres):
    # This membership exists only in the disposable local cluster and is removed.
    admin=create_engine(postgres.url.difference_update_query(['options']))
    role='crm_security_reader_'+uuid.uuid4().hex
    with admin.begin() as c:c.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')
    try:
        with postgres.begin() as c:c.exec_driver_sql(f'GRANT SELECT ON crm_leads TO "{role}"')
        with admin.begin() as c:c.exec_driver_sql(f'GRANT "{role}" TO anon')
        before=permission_snapshot(postgres)
        with pytest.raises(DBAPIError,match="review inherited grants"):
            run_script(postgres,SECURITY)
        assert permission_snapshot(postgres)==before
    finally:
        with admin.begin() as c:c.exec_driver_sql(f'REVOKE "{role}" FROM anon')
        with postgres.begin() as c:c.exec_driver_sql(f'REVOKE ALL ON crm_leads FROM "{role}"')
        with admin.begin() as c:c.exec_driver_sql(f'DROP ROLE "{role}"')
        admin.dispose()


def test_wrong_execution_role_aborts_before_changing_permissions_or_data(postgres):
    admin=create_engine(postgres.url.difference_update_query(['options']))
    before,permissions=data_snapshot(postgres),permission_snapshot(postgres)
    try:
        with pytest.raises(DBAPIError,match='requires the existing effective postgres owner'):
            run_script(admin,SECURITY)
        assert data_snapshot(postgres)==before and permission_snapshot(postgres)==permissions
    finally:admin.dispose()


def test_exposed_dependent_views_abort_without_modifying_data_or_permissions(postgres):
    with postgres.begin() as c:
        c.exec_driver_sql('CREATE VIEW public.crm_security_exposed AS SELECT id,qualification_notes FROM public.crm_leads')
        c.exec_driver_sql('CREATE VIEW public.crm_security_nested AS SELECT * FROM public.crm_security_exposed')
    before,permissions=data_snapshot(postgres),permission_snapshot(postgres)
    with pytest.raises(DBAPIError,match="Review exposed dependent view"):
        run_script(postgres,SECURITY)
    assert data_snapshot(postgres)==before and permission_snapshot(postgres)==permissions


def test_existing_policies_require_review_instead_of_silently_enabling_them(postgres):
    with postgres.begin() as c:c.exec_driver_sql('CREATE POLICY unsafe_existing_policy ON crm_leads TO PUBLIC USING (true)')
    before,permissions=data_snapshot(postgres),permission_snapshot(postgres)
    with pytest.raises(DBAPIError,match='Review existing CRM RLS policies'):
        run_script(postgres,SECURITY)
    assert data_snapshot(postgres)==before and permission_snapshot(postgres)==permissions


def test_untracked_definer_rpc_requires_review_without_changing_function_privileges(postgres):
    with postgres.begin() as c:
        c.exec_driver_sql("CREATE FUNCTION public.crm_security_count() RETURNS bigint LANGUAGE SQL SECURITY DEFINER BEGIN ATOMIC SELECT count(*) FROM public.crm_leads; END")
        # PL/pgSQL function-to-function references need not have catalog deps.
        c.exec_driver_sql("CREATE FUNCTION public.untracked_rpc() RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER AS $$BEGIN RETURN public.crm_security_count(); END$$")
    before,permissions=data_snapshot(postgres),permission_snapshot(postgres)
    with pytest.raises(DBAPIError,match='Review unclassified browser-executable SECURITY DEFINER'):
        run_script(postgres,SECURITY)
    assert data_snapshot(postgres)==before and permission_snapshot(postgres)==permissions


@pytest.mark.parametrize("revision",[LEGACY_REF,"working-tree"])
@pytest.mark.parametrize("hardened",[False,True],ids=['baseline','secured'])
def test_existing_crm_http_api_compatibility_as_non_superuser_owner(postgres,revision,hardened,tmp_path):
    if hardened:run_script(postgres,SECURITY)
    if revision==LEGACY_REF:
        archive=subprocess.check_output(['git','archive',LEGACY_REF,'backend'],cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(tmp_path,filter='data')
        source=tmp_path
    else:
        run_script(postgres,PHASE1)
        if hardened:run_script(postgres,SECURITY)
        source=ROOT
    env={**os.environ,"PYTHONPATH":str(source),"PYTHONDONTWRITEBYTECODE":"1","DB_HOST":"","DB_NAME":"","DB_USER":"","DB_PASSWORD":"","DATABASE_URL":postgres.url.render_as_string(hide_password=False),"EVOLUTION_API_BASE_URL":"","EVOLUTION_API_KEY":"","OPENAI_API_KEY":""}
    result=subprocess.run([sys.executable,'-B',str(ROOT/'tests/crm_security_api_probe.py')],cwd=source,env=env,capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
    report=json.loads(result.stdout.strip().splitlines()[-1])
    assert report['legacy_crm_routes']==11 and report['original_notes_preserved']
    # The pinned deployed release reproduces the old defects. The working tree
    # must now complete both populated transfers, with and without hardening.
    assert report['existing_application_failures']==({
        'delete_populated_stage':'23502: stage_id becomes NULL',
        'delete_populated_pipeline':'23502: funnel_id becomes NULL',
    } if revision==LEGACY_REF else {})


def test_security_before_and_after_phase1_preserves_data_and_manual_workflows(postgres):
    run_script(postgres,SECURITY)
    run_script(postgres,PHASE1)
    # Phase 1 creates a new routine under Supabase's broad default function ACL.
    # A repeat security pass secures that optional helper without editing phase 1.
    with postgres.connect() as c:
        assert c.scalar(text("SELECT has_function_privilege('anon','public.gmapscrap_crm_activity_immutable()','EXECUTE')"))
    before,metadata=data_snapshot(postgres),schema_snapshot(postgres)
    run_script(postgres,SECURITY);run_script(postgres,SECURITY)
    assert data_snapshot(postgres)==before and schema_snapshot(postgres)==metadata
    with postgres.connect() as c:
        for role in ['anon','authenticated']:
            assert not c.scalar(text("SELECT has_function_privilege(:role,'public.gmapscrap_crm_activity_immutable()','EXECUTE')"),{'role':role})
    app=FastAPI();app.include_router(manual_crm.router)
    def local_db():
        with Session(postgres) as db:yield db
    app.dependency_overrides[get_db]=local_db
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME,create_session_token(get_settings().app_username))
        payload={'lead_ids':[12],'funnel_id':1,'stage_id':1}
        added=client.post('/api/crm/manual/cards',json=payload)
        assert added.status_code==200,added.text
        card_id=added.json()['created_card_ids'][0]
        assert client.post('/api/crm/manual/cards',json=payload).json()['skipped_lead_ids']==[12]
        assert client.post(f'/api/crm/manual/cards/{card_id}/activities',json={'kind':'note','body':'Nota permanente'}).status_code==201
        follow=client.post(f'/api/crm/manual/cards/{card_id}/follow-ups',json={'title':'Retornar','due_at':'2026-12-01T09:00:00-03:00'})
        assert follow.status_code==201,follow.text
        entry=follow.json()
        assert client.patch(f"/api/crm/manual/follow-ups/{entry['id']}",json={'action':'complete','version':entry['version']}).status_code==200
        card=client.get(f'/api/crm/manual/cards/{card_id}').json()
        won=client.patch(f'/api/crm/manual/cards/{card_id}',json={'version':card['version'],'estimated_value':'1234.56','sales_outcome':'won'})
        assert won.status_code==200,won.text
        assert won.json()['sales_outcome']=='won'
    with pytest.raises(DBAPIError,match='append-only'):
        with postgres.begin() as c:c.exec_driver_sql("UPDATE crm_activities SET body='changed'")
