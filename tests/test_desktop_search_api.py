"""Isolated API tests. No app lifespan, production connection, or job submission."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url

from backend import main
from backend.auth import COOKIE_NAME, create_session_token
from backend.config import get_settings
from backend.database import Base, get_db
from backend.models import Lead, SearchRun
from backend.services import jobs


@pytest.fixture(params=["sqlite", "postgres"])
def api(tmp_path, monkeypatch, request):
    admin = None
    if request.param == "postgres":
        configured = os.getenv("GMAPSCRAP_TEST_POSTGRES_URL")
        if not configured:
            pytest.skip("Requires disposable PostgreSQL on local port 55488")
        url = make_url(configured)
        assert url.host == "127.0.0.1" and url.port == 55488
        name = "gmapscrap_desktop_test_" + uuid4().hex
        admin = create_engine(url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        engine = create_engine(url.set(database=name))
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'searches.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    def database():
        with Session(engine) as db:
            yield db
    main.app.dependency_overrides[get_db] = database
    # Never run lifespan/startup: it migrates DBs and resumes jobs.
    client = TestClient(main.app)
    client.cookies.set(COOKIE_NAME, create_session_token(get_settings().app_username))
    monkeypatch.setattr(main, "submit_search_job", lambda *a: pytest.fail("Desktop must not create a server worker"))
    yield client, engine
    client.close()
    main.app.dependency_overrides.clear()
    engine.dispose()
    if admin:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def create(client, key=None):
    return client.post("/api/desktop/searches", json=dict(niche="Nicho livre", location="Fortaleza", quantity=10, skip_without_website=False),
                       headers={"Idempotency-Key": key} if key else {})


def lead(client, run_id, name="Empresa", phone="85999999999"):
    return client.post(f"/api/desktop/searches/{run_id}/leads", json=dict(scanned=1, name=name, phone=phone))


def test_pause_resume_stop_preserve_leads_and_do_not_create_other_runs(api):
    client, engine = api
    run = create(client).json()
    run_id = run["id"]
    assert run["execution_source"] == "desktop"
    assert lead(client, run_id).status_code == 200
    base = f"/api/desktop/searches/{run_id}"
    paused = client.patch(base, json={"status": "paused"}).json()
    assert paused["status"] == "paused"
    assert paused["finished_at"] is None
    assert lead(client, run_id, "Late").status_code == 409
    resumed = client.patch(base, json={"status": "running"}).json()
    assert resumed["id"] == run_id
    assert resumed["saved_count"] == 1
    stopped = client.patch(base, json={"status": "stopped"}).json()
    assert stopped["status"] == "stopped"
    assert stopped["finished_at"] is not None
    assert stopped["saved_count"] == 1
    assert lead(client, run_id, "After Stop").status_code == 409
    for status in ("running", "paused", "completed", "failed"):
        assert client.patch(base, json={"status": status}).status_code == 409
    # Retrying Stop is idempotent; it cannot change counters, message or timestamp.
    assert client.patch(base, json={"status": "stopped", "scanned_count": 999, "skipped_delta": 9}).json() == stopped
    with Session(engine) as db:
        assert db.scalar(select(func.count(SearchRun.id))) == 1
        assert db.scalar(select(func.count(Lead.id))) == 1


def test_stop_while_paused_is_terminal_and_authenticated(api):
    client, _ = api
    run_id = create(client).json()["id"]
    base = f"/api/desktop/searches/{run_id}"
    client.patch(base, json={"status": "paused"})
    assert client.patch(base, json={"status": "stopped"}).json()["status"] == "stopped"
    client.cookies.clear()
    assert client.patch(base, json={"status": "stopped"}).status_code == 401
    assert lead(client, run_id).status_code == 401
    assert create(client).status_code == 401


@pytest.mark.parametrize("terminal", ["completed", "failed", "stopped"])
def test_terminal_runs_cannot_be_reopened_or_ingested(api, terminal):
    client, _ = api
    run_id = create(client).json()["id"]
    base = f"/api/desktop/searches/{run_id}"
    assert client.patch(base, json={"status": terminal}).status_code == 200
    assert client.patch(base, json={"status": "running"}).status_code == 409
    assert lead(client, run_id).status_code == 409


def test_web_controls_cannot_duplicate_desktop_execution(api):
    client, _ = api
    run_id = create(client).json()["id"]
    assert client.post(f"/api/searches/{run_id}/pause").status_code == 409
    client.patch(f"/api/desktop/searches/{run_id}", json={"status": "paused"})
    assert client.post(f"/api/searches/{run_id}/resume").status_code == 409


def test_idempotent_creation_and_startup_never_resubmit_desktop(api, monkeypatch):
    client, engine = api
    first = create(client, "execution-unique-key").json()
    assert create(client, "execution-unique-key").json()["id"] == first["id"]
    assert client.get("/api/desktop/searches/by-request/execution-unique-key").json()["id"] == first["id"]
    assert client.get("/api/desktop/searches/by-request/missing-key").status_code == 404
    monkeypatch.setattr(jobs, "SessionLocal", lambda: Session(engine))
    submitted = []
    monkeypatch.setattr(jobs, "submit_search_job", submitted.append)
    with Session(engine) as db:
        server = SearchRun(niche="Web", location="Fortaleza", status="queued")
        db.add(server)
        db.commit()
        server_id = server.id
    jobs.resume_unfinished_search_runs()
    assert submitted == [server_id]
    monkeypatch.setattr(jobs, "scrape_google_maps", lambda *a, **kw: pytest.fail("Desktop must stay local"))
    jobs.run_search_job(first["id"])


def test_stop_serializes_with_inflight_ingestion_and_blocks_every_late_write(api, monkeypatch):
    client, engine = api
    run_id = create(client).json()["id"]
    entered, release, stopping = Event(), Event(), Event()
    original = main.save_scraped_lead
    def saving(db, run, value):
        entered.set()
        assert release.wait(5)
        return original(db, run, value)
    monkeypatch.setattr(main, "save_scraped_lead", saving)
    def stop():
        stopping.set()
        return client.patch(f"/api/desktop/searches/{run_id}", json={"status": "stopped"})
    with ThreadPoolExecutor(2) as pool:
        ingestion = pool.submit(lead, client, run_id)
        assert entered.wait(5)
        stopped = pool.submit(stop)
        assert stopping.wait(5)
        assert not stopped.done()
        release.set()
        assert ingestion.result(timeout=5).status_code == 200
        assert stopped.result(timeout=5).json()["status"] == "stopped"
    assert lead(client, run_id, "late", "85888888888").status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count(Lead.id))) == 1
        assert db.get(SearchRun, run_id).saved_count == 1


def test_column_migration_is_repeatable_and_does_not_rewrite_existing_rows(tmp_path, monkeypatch):
    from backend import database
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE search_runs (id INTEGER PRIMARY KEY, niche VARCHAR(255), status VARCHAR(30))"))
        connection.execute(text("INSERT INTO search_runs VALUES (1, 'Existing niche', 'completed')"))
    monkeypatch.setattr(database, "engine", engine)
    database._ensure_search_run_columns()
    database._ensure_search_run_columns()
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM search_runs")).mappings().one()
        assert row["niche"] == "Existing niche"
        assert row["status"] == "completed"
        assert row["execution_source"] == "server"
        assert row["desktop_request_id"] is None
    engine.dispose()


def test_postgres_advisory_lock_survives_helper_commits(api):
    from backend.search_execution import desktop_execution_lock
    _, engine = api
    if engine.dialect.name != "postgresql":
        return
    key = 0x474D000000000000 + 17
    with Session(engine) as db:
        with desktop_execution_lock(db, 17):
            db.execute(text("SELECT 1"))
            db.commit()  # Lead helpers commit, but the execution lock must remain.
            with engine.begin() as independent_worker:
                assert not independent_worker.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
                assert independent_worker.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key + 1})
        with engine.begin() as independent_worker:
            assert independent_worker.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
