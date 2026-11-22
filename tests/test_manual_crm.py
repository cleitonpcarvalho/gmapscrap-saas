from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend import main, manual_crm
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import Base, get_db
from backend.models import CrmActivity, CrmFollowUp, CrmFunnel, CrmFunnelStage, CrmLead, CrmStageHistory, Lead, LeadTag, SearchRun, Tag
from backend.services.crm import get_default_crm_funnel, get_or_create_crm_lead, move_crm_lead
from backend.services.whatsapp_ai_agent import _apply_lead_tags, _apply_update_lead_stage_tool
from backend.services import whatsapp_webhooks


@pytest.fixture()
def context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        funnel = get_default_crm_funnel(db)
        other = CrmFunnel(name="Outro funil")
        db.add(other); db.flush()
        stage = CrmFunnelStage(funnel_id=other.id, key="new", label="Novo", position=0)
        run = SearchRun(niche="Brindes", location="Fortaleza", status="completed", saved_count=2)
        leads = [Lead(search_run=run, name=f"Empresa {i}", address="Fortaleza, CE", phone=f"+558599999000{i}", website=f"https://empresa{i}.example", email=f"vendas{i}@empresa.example") for i in range(2)]
        db.add_all([stage, *leads]); db.commit()
        app = FastAPI()
        app.include_router(manual_crm.router)
        app.add_api_route("/api/crm/funnels", main.list_crm_funnels, methods=["GET"])
        app.add_api_route("/api/crm/leads/{lead_id}", main.update_crm_lead, methods=["PATCH"])
        app.add_api_route("/api/leads/{lead_id}", main.delete_lead, methods=["DELETE"])
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            client.cookies.set(COOKIE_NAME, create_session_token(get_settings().app_username))
            yield client, db, funnel, other, leads
    engine.dispose()


def add(context, ids=None, funnel=None):
    client, db, default, _, leads = context
    funnel = funnel or default
    response = client.post("/api/crm/manual/cards", json={"lead_ids": ids or [leads[0].id], "funnel_id": funnel.id, "stage_id": funnel.stages[0].id})
    assert response.status_code == 200, response.text
    return response.json()


def detail(context, card_id):
    return context[0].get(f"/api/crm/manual/cards/{card_id}").json()


def test_bulk_membership_duplicate_safety_and_multiple_funnels(context):
    client, db, funnel, other, leads = context
    first = add(context, [item.id for item in leads])
    assert len(first["created_card_ids"]) == 2
    duplicate = add(context, [leads[0].id])
    assert duplicate == {"created_card_ids": [], "skipped_lead_ids": [leads[0].id]}
    second = add(context, [leads[0].id], other)
    assert len(second["created_card_ids"]) == 1
    assert db.scalar(select(func.count(CrmLead.id)).where(CrmLead.lead_id == leads[0].id)) == 2
    count = db.scalar(select(func.count(CrmLead.id)))
    invalid = client.post("/api/crm/manual/cards", json={"lead_ids": [leads[0].id, 99999], "funnel_id": other.id, "stage_id": other.stages[0].id})
    assert invalid.status_code == 404
    wrong_stage = client.post("/api/crm/manual/cards", json={"lead_ids": [leads[1].id], "funnel_id": other.id, "stage_id": funnel.stages[0].id})
    assert wrong_stage.status_code == 422
    assert db.scalar(select(func.count(CrmLead.id))) == count


def test_server_pagination_reaches_beyond_500_and_filters(context):
    client, db, _, _, leads = context
    db.add_all(Lead(search_run=leads[0].search_run, name=f"Empresa extra {i}", address="Centro") for i in range(530))
    db.commit()
    page = client.get("/api/crm/manual/leads?offset=510&limit=30").json()
    assert page["total"] == 532 and len(page["items"]) == 22
    first = client.get("/api/crm/manual/leads?offset=0&limit=30").json()
    ids = [first["items"][0]["id"], page["items"][-1]["id"]]
    assert len(add(context, ids)["created_card_ids"]) == 2
    assert client.get("/api/crm/manual/leads?q=%25").json()["total"] == 0
    assert client.get("/api/crm/manual/leads?niche=brindes&location=fortaleza").json()["total"] == 532
    assert client.get("/api/crm/manual/leads?limit=101").status_code == 422


def test_legacy_notes_history_and_converted_are_preserved(context):
    client, db, funnel, _, leads = context
    legacy = get_or_create_crm_lead(db, leads[0].id, funnel_id=funnel.id, stage="converted")
    legacy.qualification_notes = "Anotação histórica"
    db.add(CrmStageHistory(crm_lead_id=legacy.id, from_stage="new", to_stage="converted", changed_by="ai"))
    db.commit()
    value = detail(context, legacy.id)
    assert value["sales_outcome"] is None and value["estimated_value"] is None
    assert not value["managed_manually"] and value["qualification_notes"] == "Anotação histórica"
    assert len(value["stage_history"]) == 1
    assert client.post(f"/api/crm/manual/cards/{legacy.id}/activities", json={"kind":"note", "body":"Nova"}).status_code == 409
    claimed = client.patch(f"/api/crm/manual/cards/{legacy.id}", json={"version": value["version"], "managed_manually": True}).json()
    assert claimed["sales_outcome"] == "open" and claimed["stage_id"] == legacy.stage_id
    assert claimed["qualification_notes"] == "Anotação histórica" and len(claimed["stage_history"]) == 1
    assert client.patch(f"/api/crm/leads/{leads[0].id}", json={"funnel_id":funnel.id,"qualification_notes":"Overwrite"}).status_code == 409
    assert detail(context, legacy.id)["qualification_notes"] == "Anotação histórica"


def test_activities_are_appended_and_contact_reads_never_record_sends(context):
    client, db, _, _, _ = context
    card_id = add(context)["created_card_ids"][0]
    baseline = detail(context, card_id)
    assert baseline["lead"]["whatsapp_url"].startswith("https://wa.me/")
    assert baseline["lead"]["call_url"].startswith("tel:")
    for kind in ["note", "call", "whatsapp", "meeting", "note"]:
        result = client.post(f"/api/crm/manual/cards/{card_id}/activities", json={"kind":kind,"body":f"Registro {kind}"})
        assert result.status_code == 201
        assert datetime.fromisoformat(result.json()["created_at"]).utcoffset().total_seconds() == 0
        assert result.json()["actor"] == get_settings().app_username
    current = detail(context, card_id)
    assert len(current["activities"]) == len(baseline["activities"]) + 5
    assert len(detail(context, card_id)["activities"]) == len(current["activities"])
    activity_id = current["activities"][0]["id"]
    assert client.patch(f"/api/crm/manual/cards/{card_id}/activities/{activity_id}", json={"body":"Replace"}).status_code == 404
    record = db.get(CrmActivity, activity_id)
    record.body = "Cannot replace"
    with pytest.raises(ValueError, match="append-only"):
        db.flush()
    db.rollback()
    assert db.get(CrmActivity, activity_id).body != "Cannot replace"


def test_follow_up_utc_buckets_reschedule_completion_and_versions(context, monkeypatch):
    client, db, funnel, _, _ = context
    monkeypatch.setattr(manual_crm, "now", lambda: datetime(2026,11,21,14,tzinfo=timezone.utc))
    card_id = add(context)["created_card_ids"][0]
    created = []
    for title, date in [("Atrasado","2026-11-21T10:00:00-03:00"),("Hoje","2026-11-21T12:00:00-03:00"),("Próximo","2026-11-22T00:00:00-03:00")]:
        response = client.post(f"/api/crm/manual/cards/{card_id}/follow-ups", json={"title":title,"due_at":date})
        assert response.status_code == 201, response.text
        created.append(response.json())
    assert datetime.fromisoformat(created[0]["due_at"]) == datetime(2026,11,21,13,tzinfo=timezone.utc)
    assert detail(context, card_id)["next_follow_up"]["id"] == created[0]["id"]
    for bucket, title in [("overdue","Atrasado"),("today","Hoje"),("upcoming","Próximo")]:
        result = client.get(f"/api/crm/manual/follow-ups?bucket={bucket}&timezone_name=America/Fortaleza")
        assert [row["title"] for row in result.json()] == [title]
    follow = created[0]
    changed = client.patch(f"/api/crm/manual/follow-ups/{follow['id']}", json={"action":"reschedule","version":follow["version"],"due_at":"2026-11-23T12:00:00Z"}).json()
    assert changed["version"] > follow["version"]
    assert client.patch(f"/api/crm/manual/follow-ups/{follow['id']}", json={"action":"complete","version":follow["version"]}).status_code == 409
    assert client.patch(f"/api/crm/manual/follow-ups/{follow['id']}", json={"action":"complete","version":changed["version"]}).json()["status"] == "completed"
    assert any(item["details"] and item["details"].get("previous_due_at") == "2026-11-21T13:00:00+00:00" and "reagendado" in item["body"] for item in detail(context, card_id)["activities"])
    assert client.post(f"/api/crm/manual/cards/{card_id}/follow-ups", json={"title":"No timezone","due_at":"2026-11-23T12:00:00"}).status_code == 422
    assert client.get("/api/crm/manual/follow-ups?timezone_name=Invalid/Zone").status_code == 422


def test_outcomes_values_conflicts_and_provenance_preservation(context):
    client, db, funnel, _, leads = context
    snapshots = {name:list(db.execute(text(f"SELECT * FROM {name} ORDER BY id"))) for name in ["leads","search_runs","crm_funnels","crm_funnel_stages"]}
    card_id = add(context)["created_card_ids"][0]
    version = detail(context, card_id)["version"]
    assert client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":version,"sales_outcome":"lost"}).status_code == 422
    assert client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":version,"sales_outcome":"won"}).status_code == 422
    response = client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":version,"estimated_value":"1250.25","currency":"USD","sales_outcome":"won"})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["sales_outcome"] == "won" and updated["closed_at"] and updated["estimated_value"] == "1250.25"
    assert client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":version,"estimated_value":"9"}).status_code == 409
    assert client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":updated["version"],"estimated_value":None}).status_code == 422
    lost = client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":updated["version"],"sales_outcome":"lost","lost_reason":"Sem orçamento"}).json()
    assert lost["lost_reason"] == "Sem orçamento"
    for name, rows in snapshots.items():
        assert list(db.execute(text(f"SELECT * FROM {name} ORDER BY id"))) == rows
    assert client.delete(f"/api/leads/{leads[0].id}").status_code == 409
    assert db.get(Lead, leads[0].id) is not None


def test_ai_cannot_change_manual_stage_notes_or_shared_tags(context):
    client, db, funnel, _, leads = context
    card_id = add(context)["created_card_ids"][0]
    item = db.get(CrmLead, card_id)
    item.qualification_notes = "Historical note"
    tag = Tag(name="AI tag")
    db.add(tag); db.commit()
    before = (item.stage_id, item.qualification_notes, item.version)
    move_crm_lead(db, leads[0].id, stage="converted", funnel_id=funnel.id, changed_by="ai", reason="AI overwrite")
    _apply_lead_tags(db, leads[0].id, [tag.name])
    db.commit()
    assert (item.stage_id, item.qualification_notes, item.version) == before
    assert db.scalar(select(func.count(LeadTag.lead_id))) == 0


def test_default_pipeline_customizations_survive_reads_and_startup_seeding(context):
    client, db, funnel, _, _ = context
    stage = funnel.stages[0]
    stage.label = "Personalizado"; stage.color = "#123456"; stage.position = 8
    stage.description = "Descrição comercial"
    db.commit()
    for _ in range(2):
        assert client.get("/api/crm/funnels").status_code == 200
        get_default_crm_funnel(db)
        db.commit()
        assert (stage.label, stage.color, stage.position, stage.description) == ("Personalizado","#123456",8,"Descrição comercial")
    removed = funnel.stages[1]
    removed_id = removed.id
    db.delete(removed); db.commit(); db.expire_all()
    get_default_crm_funnel(db); db.commit()
    assert db.get(CrmFunnelStage, removed_id) is None
    assert len(db.get(CrmFunnel, funnel.id).stages) == 4


def test_automation_keeps_neighboring_manual_cards_completely_unchanged(context):
    _, db, funnel, _, leads = context
    ids = add(context, [lead.id for lead in leads])["created_card_ids"]
    target = next(stage for stage in funnel.stages if stage.key == "qualified")
    second = db.get(CrmLead, ids[1])
    second.stage_id = target.id; second.stage = target.key; second.position = 0
    third = Lead(search_run=leads[0].search_run, name="Empresa automatizada", address="Centro")
    db.add(third); db.commit()
    def snapshot():
        return list(db.execute(text("SELECT * FROM crm_leads WHERE managed_manually = true ORDER BY id")))
    before = snapshot()
    # Webhook creation and AI movement both normalize legacy stage positions.
    legacy = get_or_create_crm_lead(db, third.id, funnel_id=funnel.id)
    db.commit()
    assert snapshot() == before
    assert legacy.position == 1
    move_crm_lead(db, third.id, stage="qualified", funnel_id=funnel.id, changed_by="ai")
    db.commit()
    assert snapshot() == before
    assert legacy.stage_id == target.id and legacy.position == 1


def test_webhook_keeps_manual_cards_unchanged_and_records_only_inbound_context(context, monkeypatch):
    client, db, _, _, leads = context
    card_id = add(context)["created_card_ids"][0]
    before = detail(context, card_id)
    monkeypatch.setattr(whatsapp_webhooks, "handle_inbound_message", lambda *args, **kwargs: None)
    result = whatsapp_webhooks.ingest_evolution_messages_upsert(db, {
        "instance":"test-manual-instance", "event":"messages.upsert", "data":{
            "key":{"id":"manual-inbound-1", "fromMe":False, "remoteJid":"5585999990000@s.whatsapp.net"},
            "message":{"conversation":"Olá"}, "messageTimestamp":1795262400
        }
    }, media_provider=object())
    db.commit()
    assert result["processed"] == 1
    assert detail(context, card_id) == before
    assert db.scalar(select(func.count(CrmLead.id))) == 1


def test_validation_rolls_back_stage_value_and_events_together(context):
    client, db, funnel, _, _ = context
    card_id = add(context)["created_card_ids"][0]
    before = detail(context, card_id)
    response = client.patch(f"/api/crm/manual/cards/{card_id}",json={"version":before["version"],"stage_id":funnel.stages[1].id,"estimated_value":"12.50","sales_outcome":"lost","lost_reason":" "})
    assert response.status_code == 422
    assert detail(context,card_id) == before


def test_follow_up_today_respects_local_midnight_at_dst_boundary(context, monkeypatch):
    client, db, _, _, _ = context
    monkeypatch.setattr(manual_crm,"now",lambda:datetime(2026,11,1,4,30,tzinfo=timezone.utc))
    card_id = add(context)["created_card_ids"][0]
    for title,date in [("Ainda hoje","2026-11-02T04:30:00Z"),("Amanhã","2026-11-02T05:00:00Z")]:
        assert client.post(f"/api/crm/manual/cards/{card_id}/follow-ups",json={"title":title,"due_at":date}).status_code == 201
    assert [item["title"] for item in client.get("/api/crm/manual/follow-ups?bucket=today&timezone_name=America/New_York").json()] == ["Ainda hoje"]
    assert [item["title"] for item in client.get("/api/crm/manual/follow-ups?bucket=upcoming&timezone_name=America/New_York").json()] == ["Amanhã"]


@pytest.mark.parametrize("method,path,payload", [
    ("GET","/leads",None), ("GET","/cards?funnel_id=1",None), ("GET","/cards/1",None),
    ("POST","/cards",{"lead_ids":[1],"funnel_id":1,"stage_id":1}),
    ("PATCH","/cards/1",{"version":1}), ("POST","/cards/1/activities",{"kind":"note","body":"No"}),
    ("POST","/cards/1/follow-ups",{"title":"No","due_at":"2026-12-01T12:00:00Z"}),
    ("PATCH","/follow-ups/1",{"version":1,"action":"complete"}), ("GET","/follow-ups",None)
])
def test_every_manual_route_requires_login(context, method, path, payload):
    client = context[0]
    client.cookies.clear()
    assert client.request(method, "/api/crm/manual"+path, json=payload).status_code == 401
