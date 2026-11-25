"""Only disposable databases on local PostgreSQL port 55488 are accepted."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import main, manual_crm
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import get_db
from backend.models import CrmCompanyProfile, Lead
from test_postgres_crm_security import PHASE1, SECURITY, assert_secured, data_snapshot, postgres, run_script

pytestmark = pytest.mark.postgres
MIGRATION = (Path(__file__).resolve().parents[1] / "migrations/20261124_crm_company_profiles.sql").read_text()


@pytest.fixture
def companies(postgres):
    run_script(postgres, PHASE1)
    run_script(postgres, SECURITY)
    # Reconstruct an installed manual CRM before the new feature exists.
    with postgres.begin() as connection:
        connection.exec_driver_sql("DROP TABLE crm_company_profiles")
    yield postgres


def test_migration_preserves_all_existing_data_and_security_is_idempotent(companies):
    before = data_snapshot(companies)
    with companies.connect() as connection:
        defaults = connection.execute(text("SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY oid")).all()
    for _ in range(2):
        run_script(companies, MIGRATION)
        after = data_snapshot(companies)
        assert after.pop("crm_company_profiles") == []
        assert after == before
        assert_secured(companies)
        with companies.connect() as connection:
            assert connection.execute(text("SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY oid")).all() == defaults
            assert connection.scalar(text("SELECT relrowsecurity FROM pg_class WHERE oid='public.crm_company_profiles'::regclass"))
            assert not connection.scalar(text("SELECT EXISTS(SELECT FROM pg_policies WHERE schemaname='public' AND tablename='crm_company_profiles')"))
            for role in ["anon", "authenticated"]:
                params = {"role":role}
                assert not connection.scalar(text("SELECT has_table_privilege(:role,'public.crm_company_profiles','SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"),params)
                assert not connection.scalar(text("SELECT has_any_column_privilege(:role,'public.crm_company_profiles','SELECT,INSERT,UPDATE,REFERENCES')"),params)
            assert connection.scalar(text("SELECT has_table_privilege('postgres','public.crm_company_profiles','SELECT,INSERT,UPDATE,DELETE')"))
            assert connection.scalar(text("SELECT has_table_privilege('anon','public.crm_security_unrelated','SELECT')"))
    for role in ["anon", "authenticated"]:
        for sql in ["SELECT contact_name FROM public.crm_company_profiles", "UPDATE public.crm_company_profiles SET contact_name='unauthorized'", "DELETE FROM public.crm_company_profiles", "INSERT INTO public.crm_company_profiles(lead_id) VALUES (1)"]:
            with pytest.raises(DBAPIError):
                with companies.begin() as connection:
                    connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                    connection.exec_driver_sql(sql)


def test_existing_policy_requires_review_instead_of_silent_policy_changes(companies):
    run_script(companies, MIGRATION)
    with companies.begin() as connection:
        connection.exec_driver_sql("CREATE POLICY unexpected_policy ON crm_company_profiles FOR SELECT USING(true)")
    before = data_snapshot(companies)
    with pytest.raises(DBAPIError, match="Review company profile"):
        run_script(companies, MIGRATION)
    assert data_snapshot(companies) == before


def test_concurrent_first_company_edits_serialize_and_persist_after_reconnect(companies):
    run_script(companies, MIGRATION)
    app = FastAPI(); app.include_router(manual_crm.router)
    app.add_api_route("/api/leads/{lead_id}", main.update_lead, methods=["PATCH"])
    def local_db():
        with Session(companies) as db:
            db.execute(text("SET LOCAL lock_timeout='5s'"))
            yield db
    app.dependency_overrides[get_db] = local_db
    with Session(companies) as db:
        lead = db.scalar(select(Lead).order_by(Lead.id))
        lead_id, run_id, original_phone = lead.id, lead.run_id, lead.phone
        lead.whatsapp_validated = False
        db.commit()
    barrier = Barrier(2)
    def edit(name):
        with TestClient(app) as client:
            client.cookies.set(COOKIE_NAME,create_session_token(get_settings().app_username))
            barrier.wait(timeout=5)
            return client.patch(f"/api/leads/{lead_id}",json={"name":name,"commercial_profile":{
                "version":0,"niche_override":"Comercial B2B","location_override":"Recife",
                "contact_name":name,"contact_phone":"+5585999776655","contact_email":"contato@automasoluct.com.br"}})
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(edit,["Maria", "Joana"]))
    assert sorted(response.status_code for response in responses) == [200,409], [response.text for response in responses]
    with Session(companies) as db:
        lead = db.get(Lead,lead_id); profile = db.get(CrmCompanyProfile,lead_id)
        assert lead.run_id == run_id and lead.phone == original_phone
        assert lead.name == profile.contact_name and profile.version == 1
        assert profile.contact_email == "contato@automasoluct.com.br"
        assert profile.contact_phone == "+5585999776655"
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME,create_session_token(get_settings().app_username))
        company = client.get("/api/crm/manual/leads?niche=Comercial&location=Recife").json()["items"][0]
        assert company["commercial_profile"]["contact_whatsapp_url"] == "https://wa.me/5585999776655"
        assert company["provenance"]["run_id"] == run_id
        assert company["provenance"]["niche"] == "Brindes"
