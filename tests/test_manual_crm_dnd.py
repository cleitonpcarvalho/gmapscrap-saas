"""Manual board movement/order regressions against an isolated database."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from backend.models import CrmActivity, CrmFollowUp, CrmLead, CrmStageHistory, Lead
from test_manual_crm import context, add, detail


def ordered(client, funnel_id, stage_id):
    return [(row["id"], row["position"]) for row in client.get(f"/api/crm/manual/cards?funnel_id={funnel_id}").json() if row["stage_id"] == stage_id]


def test_stage_move_and_same_stage_reorder_preserve_commercial_data_and_neighbors(context):
    client, db, funnel, other, leads = context
    third = Lead(search_run=leads[0].search_run, name="Terceira empresa", address="Centro")
    db.add(third); db.commit()
    ids = add(context, [*map(lambda lead: lead.id, leads), third.id])["created_card_ids"]
    source, target = funnel.stages[:2]
    # Neighboring pipelines and all non-order business data must stay intact.
    other_id = client.post("/api/crm/manual/cards", json={"lead_ids":[leads[0].id], "funnel_id":other.id, "stage_id":other.stages[0].id}).json()["created_card_ids"][0]
    first = db.get(CrmLead, ids[0]); first.qualification_notes = "Nota histórica preservada"
    db.commit()
    version = detail(context, ids[0])["version"]
    response = client.patch(f"/api/crm/manual/cards/{ids[0]}", json={"version":version, "estimated_value":"3200.50", "currency":"USD", "sales_outcome":"won"})
    assert response.status_code == 200
    assert client.post(f"/api/crm/manual/cards/{ids[0]}/activities", json={"kind":"note", "body":"Atividade anterior"}).status_code == 201
    assert client.post(f"/api/crm/manual/cards/{ids[0]}/follow-ups", json={"title":"Reunião", "due_at":"2026-12-01T12:00:00Z"}).status_code == 201
    before = detail(context, ids[0]); other_before = detail(context, other_id)
    immutable = {name: list(db.execute(text(f"SELECT * FROM {name} ORDER BY id"))) for name in ["leads", "search_runs", "crm_follow_ups"]}
    moved = client.patch(f"/api/crm/manual/cards/{ids[0]}", json={"version":before["version"], "stage_id":target.id, "position":0})
    assert moved.status_code == 200, moved.text
    after = moved.json()
    for field in ["lead", "qualification_notes", "estimated_value", "currency", "sales_outcome", "lost_reason", "closed_at", "follow_ups", "managed_manually"]:
        assert after[field] == before[field]
    assert all(event in after["activities"] for event in before["activities"])
    assert after["stage_id"] == target.id and after["stage_label"] == target.label
    assert after["version"] > before["version"]
    assert len(after["stage_history"]) == len(before["stage_history"]) + 1
    assert ordered(client, funnel.id, source.id) == [(ids[1], 0), (ids[2], 1)]
    assert ordered(client, funnel.id, target.id) == [(ids[0], 0)]
    neighbor = detail(context, ids[2])
    reordered = client.patch(f"/api/crm/manual/cards/{ids[2]}", json={"version":neighbor["version"], "position":0})
    assert reordered.status_code == 200
    assert ordered(client, funnel.id, source.id) == [(ids[2], 0), (ids[1], 1)]
    assert reordered.json()["stage_history"] == neighbor["stage_history"]
    assert detail(context, other_id) == other_before
    for table, rows in immutable.items():
        assert list(db.execute(text(f"SELECT * FROM {table} ORDER BY id"))) == rows


def test_failed_validation_rolls_back_order_neighbors_and_activity_together(context):
    client, db, funnel, other, _ = context
    ids = add(context, [lead.id for lead in context[-1]])["created_card_ids"]
    before = [detail(context, item) for item in ids]
    payload = {"version":before[0]["version"], "stage_id":funnel.stages[1].id, "position":0, "sales_outcome":"lost", "lost_reason":" "}
    assert client.patch(f"/api/crm/manual/cards/{ids[0]}", json=payload).status_code == 422
    assert [detail(context, item) for item in ids] == before
    assert client.patch(f"/api/crm/manual/cards/{ids[0]}", json={"version":before[0]["version"], "stage_id":other.stages[0].id, "position":0}).status_code == 422
    assert [detail(context, item) for item in ids] == before


def test_duplicate_versioned_move_is_rejected_and_noop_does_not_append_events(context):
    client, db, funnel, _, _ = context
    ids = add(context, [lead.id for lead in context[-1]])["created_card_ids"]
    item = detail(context, ids[0])
    endpoint = f"/api/crm/manual/cards/{ids[0]}"
    noop = client.patch(endpoint, json={"version":item["version"], "stage_id":item["stage_id"], "position":0})
    assert noop.status_code == 200
    assert noop.json() == item
    payload = {"version":item["version"], "stage_id":funnel.stages[1].id, "position":0}
    assert client.patch(endpoint, json=payload).status_code == 200
    after = detail(context, ids[0])
    assert client.patch(endpoint, json=payload).status_code == 409
    assert detail(context, ids[0]) == after


def test_legacy_movement_does_not_assume_management_or_confirm_a_sale(context):
    client, db, funnel, _, _ = context
    card_id = add(context)["created_card_ids"][0]
    row = db.get(CrmLead, card_id)
    row.managed_manually = False; row.sales_outcome = None; row.qualification_notes = "Nota legada"
    db.commit()
    before = detail(context, card_id)
    won_stage = next(stage for stage in funnel.stages if stage.is_won)
    response = client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":before["version"], "stage_id":won_stage.id, "position":0})
    assert response.status_code == 200, response.text
    assert response.json()["managed_manually"] is False
    assert response.json()["sales_outcome"] is None
    assert response.json()["estimated_value"] is None
    assert response.json()["qualification_notes"] == "Nota legada"
    assert client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":response.json()["version"], "sales_outcome":"won", "estimated_value":"12"}).status_code == 409


@pytest.mark.parametrize("position", [-1, 1.5, None])
def test_invalid_order_is_rejected_without_mutation(context, position):
    client = context[0]
    card_id = add(context)["created_card_ids"][0]
    before = detail(context, card_id)
    assert client.patch(f"/api/crm/manual/cards/{card_id}", json={"version":before["version"], "position":position}).status_code == 422
    assert detail(context, card_id) == before
