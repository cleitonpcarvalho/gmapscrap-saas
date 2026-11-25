"""Local synthetic fixtures only; no SQL migration scripts are applied."""
import pytest
from sqlalchemy import func, select

from backend.models import CrmCompanyProfile, CrmLead, Lead, LeadTag, Tag
from test_manual_crm import add, context

ROOT = "/api/crm/manual"


@pytest.fixture
def populated(context):
    _, db, _, _, leads = context
    leads.extend(Lead(search_run=leads[0].search_run,name=f"Empresa extra {i}",address="Centro") for i in range(23))
    db.add_all(leads[2:]); db.commit()
    add(context,[item.id for item in leads[:10]])
    return context


def test_eligibility_filters_before_pagination_and_counts_25_minus_10(populated):
    client, db, funnel, _, leads = populated
    expected = [item.id for item in leads[10:]]
    page = client.get(ROOT+"/leads",params={"funnel_id":funnel.id,"limit":10}).json()
    assert page["total"] == page["available_total"] == 15
    assert page["matching_total"] == 25 and page["already_added_total"] == 10
    assert [item["id"] for item in page["items"]] == expected[:10]
    assert not any(item["already_in_pipeline"] for item in page["items"])
    second = client.get(ROOT+"/leads",params={"funnel_id":funnel.id,"limit":10,"offset":10}).json()
    assert [item["id"] for item in second["items"]] == expected[10:]
    shown = client.get(ROOT+"/leads",params={"funnel_id":funnel.id,"show_added":True,"limit":100}).json()
    assert shown["total"] == shown["matching_total"] == 25 and shown["available_total"] == 15
    assert [item["id"] for item in shown["items"] if item["already_in_pipeline"]] == [item.id for item in leads[:10]]
    assert db.scalar(select(func.count(CrmLead.id))) == 10


def test_bulk_selection_and_retained_selection_are_pipeline_specific(populated):
    client, db, funnel, other, leads = populated
    add(populated,[leads[0].id,leads[10].id],other)
    original_count = db.scalar(select(func.count(CrmLead.id)))
    a = client.get(ROOT+"/lead-selection",params={"funnel_id":funnel.id,"show_added":True}).json()
    b = client.get(ROOT+"/lead-selection",params={"funnel_id":other.id}).json()
    assert a["lead_ids"] == [item.id for item in leads[10:]] and a["total"] == 15
    assert b["lead_ids"] == [item.id for item in leads if item.id not in {leads[0].id,leads[10].id}]
    assert b["total"] == 23
    ids = [leads[0].id,leads[1].id,leads[10].id,leads[11].id,999999]
    first = client.post(ROOT+"/lead-eligibility",json={"funnel_id":funnel.id,"lead_ids":ids}).json()
    second = client.post(ROOT+"/lead-eligibility",json={"funnel_id":other.id,"lead_ids":ids}).json()
    assert first["lead_ids"] == [leads[10].id,leads[11].id]
    assert second["lead_ids"] == [leads[1].id,leads[11].id]
    assert db.scalar(select(func.count(CrmLead.id))) == original_count
    # A company in another pipeline is still eligible here; repeats are skipped.
    result = add(populated,[leads[10].id])
    assert len(result["created_card_ids"]) == 1
    assert add(populated,[leads[10].id])["skipped_lead_ids"] == [leads[10].id]
    assert db.scalar(select(func.count(CrmLead.id)).where(CrmLead.lead_id==leads[10].id)) == 2


def test_filters_use_commercial_overrides_tags_literal_matching_and_eligibility(populated):
    client, db, funnel, _, leads = populated
    tags = [Tag(name="Retornar"),Tag(name="Prioridade")]
    db.add_all(tags); db.flush()
    for lead in [leads[0],leads[10],leads[11]]:
        db.add(CrmCompanyProfile(lead_id=lead.id,niche_override="Comercial B2B",location_override="Recife"))
        db.add_all(LeadTag(lead_id=lead.id,tag_id=tag.id) for tag in tags)
    db.commit()
    params = [("q","Empresa"),("niche","Comercial"),("location","Recife"),("funnel_id",funnel.id),*(("tag_ids",tag.id) for tag in tags)]
    page = client.get(ROOT+"/leads",params=params).json()
    bulk = client.get(ROOT+"/lead-selection",params=params).json()
    assert page["matching_total"] == 3 and page["available_total"] == bulk["total"] == 2
    assert bulk["lead_ids"] == [item["id"] for item in page["items"]] == [leads[10].id,leads[11].id]
    assert all(item["provenance"]["niche"] == "Brindes" for item in page["items"])
    assert client.get(ROOT+"/leads",params={"funnel_id":funnel.id,"q":"%"}).json()["total"] == 0


def test_bulk_cap_is_applied_after_membership_filter(context):
    client, db, funnel, _, leads = context
    extra = [Lead(search_run=leads[0].search_run,name=f"Empresa {i+2}",address="Centro") for i in range(1120)]
    db.add_all(extra); db.commit()
    add(context,[item.id for item in [*leads,*extra[:18]]])
    result = client.get(ROOT+"/lead-selection",params={"funnel_id":funnel.id}).json()
    assert result["total"] == 1102 and len(result["lead_ids"]) == result["limit"] == 1000
    assert result["lead_ids"] == [item.id for item in extra[18:1018]]
    validated = client.post(ROOT+"/lead-eligibility",json={"funnel_id":funnel.id,"lead_ids":result["lead_ids"]})
    assert validated.status_code == 200 and validated.json()["lead_ids"] == result["lead_ids"]
    invalid = client.post(ROOT+"/lead-eligibility",json={"funnel_id":funnel.id,"lead_ids":list(range(1,1002))})
    assert invalid.status_code == 422


def test_validation_auth_and_legacy_compatibility(populated):
    client, _, funnel, _, leads = populated
    assert client.get(ROOT+"/leads").json()["total"] == 25  # Existing unscoped callers.
    assert client.get(ROOT+"/lead-selection").json()["total"] == 25
    assert client.post(ROOT+"/lead-eligibility",json={"funnel_id":funnel.id,"lead_ids":[]}).json() == {"lead_ids":[]}
    assert client.post(ROOT+"/lead-eligibility",json={"funnel_id":funnel.id,"lead_ids":[-1]}).status_code == 422
    for endpoint in ["/leads","/lead-selection"]:
        assert client.get(ROOT+endpoint,params={"funnel_id":99999}).status_code == 404
        assert client.get(ROOT+endpoint,params={"funnel_id":0}).status_code == 422
    assert client.post(ROOT+"/lead-eligibility",json={"funnel_id":99999,"lead_ids":[leads[0].id]}).status_code == 404
    client.cookies.clear()
    assert client.get(ROOT+"/leads",params={"funnel_id":funnel.id}).status_code == 401
    assert client.get(ROOT+"/lead-selection",params={"funnel_id":funnel.id}).status_code == 401
    assert client.post(ROOT+"/lead-eligibility",json={"funnel_id":funnel.id,"lead_ids":[leads[0].id]}).status_code == 401
