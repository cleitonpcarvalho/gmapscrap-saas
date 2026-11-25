import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import Base, get_db
from backend.models import Lead, Niche, SearchRun
from backend.niches import router
from scripts.preview_niche_import import main, preview


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_search(db, name, leads=0):
    run = SearchRun(niche=name, location="São Paulo", status="completed", saved_count=leads)
    db.add(run)
    for index in range(leads):
        db.add(Lead(search_run=run, name=f"Empresa {index}", address="Centro", website=None))
    db.commit()


def test_preview_normalizes_deduplicates_and_includes_empty_historical_runs(db):
    for name, count in [("  bRINDES   personalizados  ", 2), ("BRINDES PERSONALIZADOS", 1), ("Clínicas", 0)]:
        add_search(db, name, count)
    result = preview(db.connection())
    assert result["new_names"] == ["Brindes Personalizados", "Clínicas"]
    assert result["new_record_count"] == 2
    assert result["source_totals"] == {"search_runs": 3, "leads": 3, "registered_niches": 0,
        "distinct_raw_labels": 3, "distinct_valid_names": 2}
    assert result["candidates"][0]["search_run_count"] == 2
    assert result["candidates"][0]["lead_count"] == 3
    assert result["candidates"][1]["lead_count"] == 0
    assert result["read_only"] and result["requires_explicit_approval"]
    assert not result["import_executed"]


def test_preview_skips_existing_registry_names_without_renaming_them(db):
    db.add(Niche(name="BRINDES  PERSONALIZADOS"))
    db.commit()
    add_search(db, "brindes personalizados", 1)
    add_search(db, "Marketing")
    before = db.execute(select(Niche.__table__)).all()
    result = preview(db.connection())
    assert result["new_names"] == ["Marketing"]
    assert result["new_record_count"] == 1
    assert result["candidates"][0]["already_registered"] is True
    assert db.execute(select(Niche.__table__)).all() == before


@pytest.mark.parametrize("value", ["", " ", "x", "x" * 256, "Brindes\n", "Brindes\x00"])
def test_preview_rejects_values_that_the_existing_api_would_reject(db, value):
    add_search(db, value)
    result = preview(db.connection())
    assert result["new_record_count"] == 0
    assert result["rejected_source_names"][0]["raw_name"] == value


def test_preview_and_approved_test_import_via_existing_api_preserve_all_history_fields(db):
    add_search(db, " Brindes ", 2)
    add_search(db, "HVAC")
    before_searches = db.execute(select(SearchRun.__table__)).all()
    before_leads = db.execute(select(Lead.__table__)).all()
    proposed = preview(db.connection())
    assert db.scalars(select(Niche)).all() == []
    assert preview(db.connection())["new_names"] == proposed["new_names"]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(get_settings().app_username))
        # This simulates a separately approved import in SQLite only.
        for name in proposed["new_names"]:
            assert client.post("/api/niches", json={"name": name}).status_code == 201
        assert client.post("/api/niches", json={"name": " BRINDES "}).status_code == 409
        assert preview(db.connection())["new_record_count"] == 0
        assert [row["name"] for row in client.get("/api/niches").json()] == ["Brindes", "HVAC"]
    assert db.execute(select(SearchRun.__table__)).all() == before_searches
    assert db.execute(select(Lead.__table__)).all() == before_leads


def test_preview_cli_has_no_apply_option(monkeypatch, tmp_path):
    target = tmp_path / "preview.json"
    monkeypatch.setattr(sys, "argv", ["preview_niche_import.py", "--output", str(target), "--apply"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not target.exists()
