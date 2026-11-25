"""Commercial board concurrency on the disposable LOCAL PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend import manual_crm
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import get_db
from backend.models import CrmFunnel, CrmFunnelStage, CrmLead, Lead
from test_postgres_crm_security import PHASE1, SECURITY, postgres, run_script

pytestmark = pytest.mark.postgres


@pytest.fixture
def board(postgres):
    run_script(postgres, PHASE1)
    run_script(postgres, SECURITY)
    with Session(postgres) as db:
        funnel = CrmFunnel(name="Pipeline DnD local")
        db.add(funnel); db.flush()
        stages = [CrmFunnelStage(funnel=funnel, key=f"stage{i}", label=f"Etapa {i}", position=i) for i in range(3)]
        db.add_all(stages); db.flush()
        leads = db.scalars(select(Lead).order_by(Lead.id).limit(3)).all()
        cards = [CrmLead(lead_id=lead.id, funnel=funnel, stage_ref=stages[0 if i < 2 else 1],
                         stage=stages[0 if i < 2 else 1].key, position=i if i < 2 else 0,
                         managed_manually=True, sales_outcome="open", qualification_notes="Nota comercial intacta") for i, lead in enumerate(leads)]
        db.add_all(cards); db.commit()
        values = dict(funnel=funnel.id, stages=[item.id for item in stages], cards=[item.id for item in cards])
    app = FastAPI(); app.include_router(manual_crm.router)
    def local_db():
        with Session(postgres) as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            yield db
    app.dependency_overrides[get_db] = local_db
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(get_settings().app_username))
        yield {**values, "client":client, "engine":postgres}


def get(board, card_id):
    return board["client"].get(f"/api/crm/manual/cards/{card_id}").json()


def move(board, card_id, stage_id, position, version):
    return board["client"].patch(f"/api/crm/manual/cards/{card_id}", json={"version":version, "stage_id":stage_id, "position":position})


def assert_consistent(board):
    rows = board["client"].get(f"/api/crm/manual/cards?funnel_id={board['funnel']}").json()
    assert len(rows) == len({row["id"] for row in rows}) == 3
    for stage_id in board["stages"]:
        stage_rows = [row for row in rows if row["stage_id"] == stage_id]
        assert [row["position"] for row in stage_rows] == list(range(len(stage_rows)))
        assert all(row["funnel_id"] == board["funnel"] for row in stage_rows)
    return rows


def test_concurrent_moves_into_same_stage_serialize_and_keep_contiguous_order(board):
    first, _, third = board["cards"]
    versions = {item:get(board, item)["version"] for item in [first, third]}
    barrier = Barrier(2)
    def moving(card_id):
        barrier.wait(timeout=5)
        return move(board, card_id, board["stages"][2], 0, versions[card_id])
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(moving, [first, third]))
    assert [result.status_code for result in results] == [200, 200], [result.text for result in results]
    rows = assert_consistent(board)
    assert {row["id"] for row in rows if row["stage_id"] == board["stages"][2]} == {first, third}
    assert all(row["qualification_notes"] == "Nota comercial intacta" for row in rows)


def test_concurrent_neighbor_reorder_rejects_stale_version_and_can_retry_safely(board):
    first, second, _ = board["cards"]
    versions = {item:get(board, item)["version"] for item in [first, second]}
    barrier = Barrier(2)
    def moving(card_id):
        barrier.wait(timeout=5)
        return move(board, card_id, board["stages"][2], 0, versions[card_id])
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(moving, [first, second]))
    assert any(response.status_code == 200 for response in results)
    assert all(response.status_code in {200, 409} for response in results), [response.text for response in results]
    assert_consistent(board)
    for card_id, response in zip([first, second], results):
        if response.status_code == 409:
            assert move(board, card_id, board["stages"][2], 1, get(board, card_id)["version"]).status_code == 200
    assert_consistent(board)


def test_move_retains_immutable_history_followups_value_and_explicit_lost_outcome(board):
    client = board["client"]; card_id = board["cards"][0]
    endpoint = f"/api/crm/manual/cards/{card_id}"
    before = get(board, card_id)
    assert client.patch(endpoint, json={"version":before["version"], "estimated_value":"1234.56", "currency":"USD", "sales_outcome":"lost", "lost_reason":"Retomar no próximo trimestre"}).status_code == 200
    assert client.post(endpoint+"/activities", json={"kind":"note", "body":"Histórico permanente"}).status_code == 201
    assert client.post(endpoint+"/follow-ups", json={"title":"Retornar contato", "due_at":"2026-12-01T12:00:00Z"}).status_code == 201
    before = get(board, card_id)
    result = move(board, card_id, board["stages"][1], 0, before["version"])
    assert result.status_code == 200, result.text
    after = result.json()
    for field in ["qualification_notes", "lead", "estimated_value", "currency", "sales_outcome", "lost_reason", "closed_at", "follow_ups"]:
        assert after[field] == before[field]
    assert all(item in after["activities"] for item in before["activities"])
    assert len(after["stage_history"]) == len(before["stage_history"]) + 1
    snapshot = get(board, card_id)
    invalid = client.patch(endpoint, json={"version":snapshot["version"], "stage_id":board["stages"][0], "position":1, "sales_outcome":"won", "estimated_value":None})
    assert invalid.status_code == 422
    assert get(board, card_id) == snapshot
    assert_consistent(board)
