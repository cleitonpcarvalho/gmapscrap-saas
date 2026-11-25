"""Synthetic local company edits and server-side all-page selection."""
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from backend import main
from backend.models import CrmCompanyProfile, CrmLead, Lead, LeadTag, SearchRun, Tag
from backend.services.email_validation import validate_email_address
from test_manual_crm import add, context, detail


@pytest.fixture
def companies(context, monkeypatch):
    client = context[0]
    client.app.add_api_route("/api/leads/{lead_id}", main.update_lead, methods=["PATCH"])
    # Main company email keeps its production validation; deterministic local DNS.
    monkeypatch.setattr(main, "validate_email_address", lambda email, website: validate_email_address(email, website, check_dns=False))
    return context


def test_selection_across_all_pages_and_cap_has_no_side_effects(companies):
    client, db, _, _, leads = companies
    db.add_all(Lead(search_run=leads[0].search_run, name=f"Selecionável {i}", address="Centro") for i in range(1100))
    db.commit()
    before = db.scalar(select(func.count(CrmLead.id)))
    selected = client.get("/api/crm/manual/lead-selection?q=Selecionável&niche=BRINDES&location=fortaleza").json()
    assert selected["total"] == 1100 and selected["limit"] == 1000
    assert len(selected["lead_ids"]) == len(set(selected["lead_ids"])) == 1000
    page = client.get("/api/crm/manual/leads?q=Selecionável&offset=990&limit=30").json()
    assert selected["lead_ids"][-10:] == [item["id"] for item in page["items"][:10]]
    assert db.scalar(select(func.count(CrmLead.id))) == before
    assert client.get("/api/crm/manual/lead-selection?q=%25").json()["total"] == 0
    body = {"lead_ids": selected["lead_ids"], "funnel_id": companies[2].id, "stage_id": companies[2].stages[0].id}
    assert len(client.post("/api/crm/manual/cards", json=body).json()["created_card_ids"]) == 1000
    again = client.post("/api/crm/manual/cards", json=body).json()
    assert again["created_card_ids"] == [] and len(again["skipped_lead_ids"]) == 1000
    assert client.post("/api/crm/manual/cards", json={**body,"lead_ids":list(range(1,1002))}).status_code == 422


def test_company_edit_preserves_provenance_and_every_commercial_relationship(companies):
    client, db, _, other, leads = companies
    card_id = add(companies)["created_card_ids"][0]
    other_id = add(companies, funnel=other)["created_card_ids"][0]
    url = f"/api/crm/manual/cards/{card_id}"
    assert client.patch(url, json={"version":1,"estimated_value":"5432.10","currency":"BRL","sales_outcome":"lost","lost_reason":"Retomar depois"}).status_code == 200
    assert client.post(url+"/activities", json={"kind":"note","body":"Nota permanente"}).status_code == 201
    assert client.post(url+"/follow-ups", json={"title":"Retornar","due_at":"2026-12-10T12:00:00Z"}).status_code == 201
    tag = Tag(name="Prioridade"); db.add(tag); db.flush()
    db.add(LeadTag(lead_id=leads[0].id,tag_id=tag.id)); db.commit(); db.expire_all()
    before = detail(companies,card_id)
    run = leads[0].search_run
    run_before = {col.name:deepcopy(getattr(run,col.name)) for col in SearchRun.__table__.columns}
    response = client.patch(f"/api/leads/{leads[0].id}", json={
        "name":"Empresa revisada","phone":"+5585999887766","email":"VENDAS@automasoluct.com.br",
        "website":"https://automasoluct.com.br","address":"Rua comercial, Recife, PE",
        "commercial_profile":{"version":0,"niche_override":" Serviços B2B ","location_override":"Recife",
                              "contact_name":"Maria Silva","contact_phone":"+5585999776655","contact_email":"MARIA@automasoluct.com.br"}})
    assert response.status_code == 200, response.text
    after = detail(companies,card_id)
    assert after["lead"]["name"] == "Empresa revisada"
    assert after["lead"]["niche"] == "Serviços B2B" and after["lead"]["location"] == "Recife"
    assert after["lead"]["provenance"] == before["lead"]["provenance"]
    assert after["lead"]["tags"] == before["lead"]["tags"]
    for key in before.keys()-{"lead"}:
        assert after[key] == before[key], key
    db.refresh(run)
    assert {col.name:getattr(run,col.name) for col in SearchRun.__table__.columns} == run_before
    assert db.scalar(select(func.count(SearchRun.id))) == 1
    assert db.scalar(select(func.count(Lead.id))) == 2
    assert detail(companies,other_id)["lead"] == after["lead"]
    profile = after["lead"]["commercial_profile"]
    assert profile["contact_name"] == "Maria Silva" and profile["contact_email"] == "maria@automasoluct.com.br"
    assert profile["contact_call_url"] == "tel:+5585999776655"
    assert profile["contact_whatsapp_url"] == "https://wa.me/5585999776655"
    assert profile["contact_email_url"] == "mailto:maria@automasoluct.com.br"
    assert after["lead"]["phone"] != profile["contact_phone"]
    assert client.get("/api/crm/manual/lead-selection?niche=Serviços&location=Recife").json()["lead_ids"] == [leads[0].id]
    assert client.get("/api/crm/manual/leads?niche=Brindes").json()["total"] == 1


def test_stale_conflict_invalid_company_and_contact_edits_are_atomic(companies):
    client, db, _, _, leads = companies
    card_id = add(companies)["created_card_ids"][0]
    endpoint = f"/api/leads/{leads[0].id}"
    assert client.patch(endpoint,json={"commercial_profile":{"version":0,"contact_name":"Maria"}}).status_code == 200
    before = detail(companies,card_id)
    for payload, status in [
        ({"name":"Stale","commercial_profile":{"version":0,"contact_name":"Outra"}},409),
        ({"website":leads[1].website,"commercial_profile":{"version":1,"contact_name":"Outra"}},409),
        ({"name":" ","commercial_profile":{"version":1}},422),
        ({"name":None,"commercial_profile":{"version":1}},422),
        ({"website":"javascript:alert(1)","commercial_profile":{"version":1}},422),
        ({"email":"invalid","commercial_profile":{"version":1}},422),
        ({"name":"Inválida","commercial_profile":{"version":1,"contact_email":"invalid"}},422),
        ({"commercial_profile":{"version":1,"contact_phone":"123"}},422),
        ({"commercial_profile":{"version":1,"contact_name":"Maria\nBcc:"}},422),
        ({"niche":"Changed search","commercial_profile":{"version":1}},422),
        ({"location":"Changed search","commercial_profile":{"version":1}},422),
        ({"commercial_profile":{"version":1,"salesperson":"Maria"}},422),
    ]:
        response = client.patch(endpoint,json=payload)
        assert response.status_code == status, (payload,response.text)
        db.rollback(); db.expire_all()
        assert detail(companies,card_id) == before


def test_clear_contact_and_classifications_restores_source_not_search_run(companies):
    client, db, _, _, leads = companies
    card_id = add(companies)["created_card_ids"][0]
    endpoint = f"/api/leads/{leads[0].id}"
    assert client.patch(endpoint,json={"commercial_profile":{"version":0,"niche_override":"Comercial","location_override":"Recife","contact_phone":"+5585999776655"}}).status_code == 200
    assert client.patch(endpoint,json={"commercial_profile":{"version":1,"niche_override":None,"location_override":None,"contact_name":None,"contact_phone":None,"contact_email":None}}).status_code == 200
    value = detail(companies,card_id)["lead"]
    assert value["niche"] == value["provenance"]["niche"] == "Brindes"
    assert value["commercial_profile"]["contact_call_url"] == value["commercial_profile"]["contact_whatsapp_url"] == ""
    # Existing non-CRM clients retain the lead editor; they invalidate CRM versions.
    assert client.patch(endpoint,json={"name":"Editor legado"}).status_code == 200
    assert client.patch(endpoint,json={"name":"Stale","commercial_profile":{"version":2}}).status_code == 409


def test_contact_edit_never_calls_dns_or_whatsapp_providers_and_legacy_first_edit_invalidates_draft(companies, monkeypatch):
    client, db, _, _, leads = companies
    def forbidden(*args, **kwargs):
        raise AssertionError("Contact editing must not call external providers or DNS")
    monkeypatch.setattr("backend.services.email_validation._mx_status", forbidden)
    monkeypatch.setattr("backend.services.whatsapp_validation.requests.post", forbidden)
    endpoint = f"/api/leads/{leads[0].id}"
    assert client.patch(endpoint,json={"name":"Editor legado primeiro"}).status_code == 200
    assert client.patch(endpoint,json={"name":"Stale","commercial_profile":{"version":0}}).status_code == 409
    assert client.patch(endpoint,json={"commercial_profile":{"version":1,"contact_phone":"+5585999776655","contact_email":"maria@automasoluct.com.br"}}).status_code == 200


def test_bulk_selection_reuses_tag_any_filter_without_duplicates(companies):
    client, db, _, _, leads = companies
    tags = [Tag(name="Prioridade"),Tag(name="Retornar")]
    db.add_all(tags); db.flush()
    db.add_all(LeadTag(lead_id=leads[0].id,tag_id=tag.id) for tag in tags)
    db.commit()
    params = [("tag_ids",tag.id) for tag in tags]
    page = client.get("/api/crm/manual/leads",params=params).json()
    selected = client.get("/api/crm/manual/lead-selection",params=params).json()
    assert selected["lead_ids"] == [leads[0].id] == [item["id"] for item in page["items"]]
    assert selected["total"] == page["total"] == 1


def test_startup_does_not_automatically_create_commercial_tables(monkeypatch):
    from backend import database
    created = []
    monkeypatch.setattr(database.Base.metadata,"create_all",lambda **kwargs: created.extend(table.name for table in kwargs["tables"]))
    monkeypatch.setattr(database,"_wait_for_database",lambda: None)
    for name in vars(database):
        if name.startswith("_ensure_"):
            monkeypatch.setattr(database,name,lambda: None)
    database.init_db()
    assert "leads" in created
    assert not {"crm_activities","crm_follow_ups","crm_company_profiles"} & set(created)


def test_authenticated_access_and_missing_migration_fail_closed(companies):
    client, db, _, _, leads = companies
    card_id = add(companies)["created_card_ids"][0]
    client.cookies.clear()
    assert client.get("/api/crm/manual/lead-selection").status_code == 401
    assert client.patch(f"/api/leads/{leads[0].id}",json={"commercial_profile":{"version":0}}).status_code == 401
    from backend.auth import COOKIE_NAME, create_session_token
    from backend.config import get_settings
    client.cookies.set(COOKIE_NAME,create_session_token(get_settings().app_username))
    db.rollback(); CrmCompanyProfile.__table__.drop(db.get_bind())
    assert client.get("/api/crm/manual/lead-selection").status_code == 200
    assert detail(companies,card_id)["lead"]["commercial_profile"]["available"] is False
    response = client.patch(f"/api/leads/{leads[0].id}",json={"name":"Blocked","commercial_profile":{"version":0}})
    assert response.status_code == 503
    assert detail(companies,card_id)["lead"]["name"] == "Empresa 0"
