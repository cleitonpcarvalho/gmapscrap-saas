from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend import main
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import Base, get_db
from backend.models import Lead, Niche, SearchRun
from backend.niches import router
from scripts.preview_lead_segment_correction import preview


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def client(db) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(get_settings().app_username))
        yield client


def test_niche_crud_and_search(client):
    created = client.post("/api/niches", json={"name": "  bRINDES   personalizados  "})
    assert created.status_code == 201
    item = created.json()
    assert item["name"] == "Brindes Personalizados"
    assert item["created_at"]
    assert client.get(f"/api/niches/{item['id']}").json() == item
    assert client.get("/api/niches", params={"q": "PERSONAL"}).json() == [item]
    assert client.get("/api/niches", params={"q": "%"}).json() == []
    assert client.get("/api/niches", params={"q": "_"}).json() == []
    assert client.patch(f"/api/niches/{item['id']}", json={"name": "Presentes"}).json()["name"] == "Presentes"
    assert client.delete(f"/api/niches/{item['id']}").json() == {"deleted": True}
    assert client.get("/api/niches").json() == []
    assert client.get(f"/api/niches/{item['id']}").status_code == 404


def test_duplicates_and_atomic_conflicts(client, db):
    first = client.post("/api/niches", json={"name": "Brindes"}).json()
    second = client.post("/api/niches", json={"name": "Presentes"}).json()
    assert client.post("/api/niches", json={"name": " BRINDES "}).status_code == 409
    assert client.patch(f"/api/niches/{second['id']}", json={"name": "brindes"}).status_code == 409
    assert client.get(f"/api/niches/{second['id']}").json()["name"] == "Presentes"
    # The database also rejects races or callers bypassing the API.
    db.add(Niche(name="brindes"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert client.get(f"/api/niches/{first['id']}").json()["name"] == "Brindes"


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"name": ""}, {"name": "  "}, {"name": "a"},
    {"name": "x" * 256}, {"name": 12}, {"name": "Brindes\n"}, {"name": "Brindes\x00"},
    {"name": "Brindes", "id": 1}])
def test_validation(client, payload):
    assert client.post("/api/niches", json=payload).status_code == 422
    assert client.patch("/api/niches/999", json=payload).status_code == 422


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/niches", None), ("GET", "/api/niches/1", None),
    ("POST", "/api/niches", {"name": "Brindes"}),
    ("PATCH", "/api/niches/1", {"name": "Brindes"}), ("DELETE", "/api/niches/1", None),
])
def test_all_niche_routes_require_authentication(client, method, path, payload):
    client.cookies.clear()
    assert client.request(method, path, json=payload).status_code == 401
    client.cookies.set(COOKIE_NAME, "invalid-token")
    assert client.request(method, path, json=payload).status_code == 401
    client.cookies.set(COOKIE_NAME, create_session_token("another-user"))
    assert client.request(method, path, json=payload).status_code == 401


def test_missing_niches(client):
    assert client.patch("/api/niches/999", json={"name": "Brindes"}).status_code == 404
    assert client.delete("/api/niches/999").status_code == 404


def test_registry_changes_preserve_every_lead_and_search_field(client, db):
    run = SearchRun(niche="Brindes", location="São José do Rio Preto", status="completed", saved_count=1)
    lead = Lead(search_run=run, name="Empresa", address="Centro", website=None)
    db.add(lead)
    db.commit()
    before_runs = db.execute(select(SearchRun.__table__)).all()
    before_leads = db.execute(select(Lead.__table__)).all()
    item = client.post("/api/niches", json={"name": "Brindes"}).json()
    client.patch(f"/api/niches/{item['id']}", json={"name": "Presentes"})
    client.delete(f"/api/niches/{item['id']}")
    assert db.execute(select(SearchRun.__table__)).all() == before_runs
    assert db.execute(select(Lead.__table__)).all() == before_leads
    assert lead.niche == "Brindes"


def test_existing_free_text_desktop_and_web_search_contracts(db, monkeypatch):
    # No app lifespan is run: startup includes database migrations and job resumption.
    from backend.services import jobs

    main.app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(jobs, "submit_search_job", lambda *args, **kwargs: None)
    client = TestClient(main.app)
    client.cookies.set(COOKIE_NAME, create_session_token(get_settings().app_username))
    try:
        for path in ("/api/searches", "/api/desktop/searches"):
            response = client.post(path, json={"niche": "nicho livre", "location": "São Paulo", "quantity": 10})
            assert response.status_code == 200
            run = response.json()
            assert run["niche"] == "Nicho Livre"
            assert run["location"] == "São Paulo"
            assert run["target_quantity"] == 10
            assert run["skip_without_website"] is True
            assert run["validate_whatsapp"] is False
        assert len(client.get("/api/searches").json()) == 2
        assert client.get("/api/niches").json() == []
    finally:
        client.close()
        main.app.dependency_overrides.clear()


def test_preview_uses_exact_intersection_and_never_writes(db):
    pairs = [("São José do Rio Preto", "Brindes"), ("Brindes", "São José do Rio Preto"),
             ("São José do Rio Preto", "Outra cidade"), ("Outro nicho", "Brindes"),
             ("São José do Rio Preto ", "Brindes")]
    for niche, location in pairs:
        run = SearchRun(niche=niche, location=location)
        db.add(Lead(search_run=run, name="Empresa", address="Centro"))
    db.commit()
    before_runs = db.execute(select(SearchRun.__table__)).all()
    before_leads = db.execute(select(Lead.__table__)).all()
    result = preview(db.connection())
    assert result["read_only"] is True
    assert result["affected_record_count"] == 1
    assert result["lead_ids"] == [1]
    assert result["search_run_ids"] == [1]
    assert db.execute(select(SearchRun.__table__)).all() == before_runs
    assert db.execute(select(Lead.__table__)).all() == before_leads
