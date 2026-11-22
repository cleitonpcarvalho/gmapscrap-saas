"""HTTP compatibility probe for disposable local databases, also usable by old code."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import main
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import engine, get_db
from backend.models import CrmLead, Lead
from backend.services.crm import move_crm_lead


def run_probe():
    assert engine.url.host in {"127.0.0.1", "localhost"} and engine.url.port == 55488
    assert engine.url.database.startswith("gmapscrap_crm_security_test_")
    app = FastAPI()
    routes = [
        ("GET", "/api/crm/funnels", "list_crm_funnels"),
        ("POST", "/api/crm/funnels", "create_crm_funnel"),
        ("PATCH", "/api/crm/funnels/{funnel_id}", "update_crm_funnel"),
        ("DELETE", "/api/crm/funnels/{funnel_id}", "delete_crm_funnel"),
        ("GET", "/api/crm/funnels/{funnel_id}/stages", "list_crm_funnel_stages"),
        ("POST", "/api/crm/funnels/{funnel_id}/stages", "create_crm_funnel_stage"),
        ("PATCH", "/api/crm/funnels/{funnel_id}/stages", "reorder_crm_funnel_stages"),
        ("PATCH", "/api/crm/funnels/{funnel_id}/stages/{stage_id}", "update_crm_funnel_stage"),
        ("DELETE", "/api/crm/funnels/{funnel_id}/stages/{stage_id}", "delete_crm_funnel_stage"),
        ("GET", "/api/crm/leads", "list_crm_leads"),
        ("PATCH", "/api/crm/leads/{lead_id}", "update_crm_lead"),
    ]
    for method, path, name in routes:
        app.add_api_route(path, getattr(main, name), methods=[method])

    def local_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = local_db
    existing_failures = {}

    def request(client, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == 200, (method, path, response.status_code, response.text)
        return response.json()

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == "postgres"
        assert not connection.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"))
        original_notes = connection.execute(text("SELECT id,qualification_notes FROM crm_leads ORDER BY id")).all()
        lead_id = connection.scalar(text("SELECT max(id) FROM leads"))

    with TestClient(app) as client:
        assert client.get("/api/crm/funnels").status_code == 401
        client.cookies.set(COOKIE_NAME, create_session_token(get_settings().app_username))
        funnels = request(client, "GET", "/api/crm/funnels")
        default = next(f for f in funnels if f["is_default"])
        assert len(request(client, "GET", "/api/crm/leads")) == 9
        first = request(client, "POST", "/api/crm/funnels", json={"name":"Security probe A"})
        second = request(client, "POST", "/api/crm/funnels", json={"name":"Security probe B"})
        request(client, "PATCH", f"/api/crm/funnels/{first['id']}", json={"name":"Security probe renamed"})
        initial = first["stages"][0]
        path = f"/api/crm/funnels/{first['id']}/stages"
        middle = request(client, "POST", path, json={"key":"contacted","label":"Contactado"})
        last = request(client, "POST", path, json={"key":"proposal","label":"Proposta"})
        updated = request(client, "PATCH", path+f"/{middle['id']}", json={"label":"Contato manual","color":"#123456"})
        assert updated["color"] == "#123456"
        request(client, "PATCH", path, json={"stage_ids":[initial["id"],last["id"],middle["id"]]})
        assert len(request(client, "GET", path)) == 3
        card_path = f"/api/crm/leads/{lead_id}"
        card = request(client, "PATCH", card_path, json={"funnel_id":first["id"],"stage":"contacted","qualification_notes":"Nota do teste HTTP"})
        again = request(client, "PATCH", card_path, json={"funnel_id":first["id"],"stage":"contacted"})
        assert again["id"] == card["id"]
        other = request(client, "PATCH", card_path, json={"funnel_id":second["id"],"stage":"new"})
        assert other["id"] != card["id"]
        listed = request(client, "GET", f"/api/crm/leads?funnel_id={first['id']}")
        assert listed[0]["qualification_notes"] == "Nota do teste HTTP"
        request(client, "PATCH", card_path, json={"funnel_id":first["id"],"stage":"proposal","position":0})
        try:
            removed = request(client, "DELETE", path+f"/{last['id']}?move_to_stage_id={initial['id']}")
            assert removed["moved_cards"] == 1
        except IntegrityError as error:
            # Baseline application bug: loaded relationship nulls the moved FK.
            assert error.orig.sqlstate == '23502' and 'stage_id' in str(error.orig)
            existing_failures['delete_populated_stage']='23502: stage_id becomes NULL'
            preserved=request(client,"GET",f"/api/crm/leads?funnel_id={first['id']}")
            assert preserved[0]['id']==card['id'] and preserved[0]['stage']=='proposal'
            request(client,"PATCH",card_path,json={'funnel_id':first['id'],'stage':initial['key']})
            request(client,"DELETE",path+f"/{last['id']}")
        request(client, "DELETE", path+f"/{middle['id']}")
        assert client.delete(f"/api/crm/funnels/{default['id']}").status_code == 409
        assert client.delete(f"/api/crm/funnels/{first['id']}").status_code == 409
        assert client.delete(f"/api/crm/funnels/{first['id']}?move_to_funnel_id={second['id']}").status_code == 409
        # Delete/move into an empty pipeline; the card and its history survive.
        destination = request(client, "POST", "/api/crm/funnels", json={"name":"Security probe destination"})
        try:
            removed = request(client, "DELETE", f"/api/crm/funnels/{first['id']}?move_to_funnel_id={destination['id']}")
            assert removed["moved_cards"] == 1
            moved = request(client, "GET", f"/api/crm/leads?funnel_id={destination['id']}")
        except IntegrityError as error:
            assert error.orig.sqlstate == '23502' and 'funnel_id' in str(error.orig)
            existing_failures['delete_populated_pipeline']='23502: funnel_id becomes NULL'
            moved=request(client,"GET",f"/api/crm/leads?funnel_id={first['id']}")
        assert moved[0]["id"] == card["id"] and moved[0]["qualification_notes"] == "Nota do teste HTTP"
        empty = request(client, "POST", "/api/crm/funnels", json={"name":"Security probe empty"})
        request(client, "DELETE", f"/api/crm/funnels/{empty['id']}")

    with Session(engine) as db:
        # AI writes still use the trusted backend, without external provider calls.
        moved = move_crm_lead(db, lead_id, funnel_id=second["id"], stage="new", changed_by="ai", reason="AI fixture note")
        db.commit()
        assert moved.qualification_notes == "AI fixture note"
        assert db.get(Lead, lead_id) is not None
        for card_id, notes in original_notes:
            assert db.get(CrmLead, card_id).qualification_notes == notes
        assert db.scalar(text("SELECT count(*) FROM crm_stage_history")) >= 7
    return {"legacy_crm_routes":len(routes),"non_superuser_non_bypass_owner":True,"authenticated_http_checks":True,"ai_backend_write":True,"original_notes_preserved":True,"existing_application_failures":existing_failures}


if __name__ == "__main__":
    print(json.dumps(run_probe()))
