from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import auth, main
from backend.database import Base
from backend.models import Lead, SearchRun, WhatsAppInstance
from backend.services import lead_whatsapp_validation, whatsapp_validation


class FakeEvolutionResponse:
    def __init__(self, *, exists: bool | None = True, status_code: int = 200):
        self.status_code = status_code
        self._exists = exists

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict[str, Any]:
        return {"numbers": [{"exists": self._exists}]}


@dataclass(frozen=True)
class ApiContext:
    client: TestClient
    db: Session
    settings: SimpleNamespace


@pytest.fixture()
def api_context(monkeypatch: pytest.MonkeyPatch) -> Generator[ApiContext, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    settings = SimpleNamespace(
        database_url="sqlite://",
        app_username="cleiton.carvalho@automasoluct.com.br",
        app_password="test-password",
        session_secret="test-session-secret",
        session_cookie_secure=False,
        evolution_api_base_url="https://evolution.example.test",
        evolution_api_key="test-api-key",
        evolution_instance_name="sales-main",
        whatsapp_validation_timeout_seconds=5,
        whatsapp_batch_validation_delay_seconds=0,
        whatsapp_batch_validation_max_retries=0,
        whatsapp_batch_validation_max_consecutive_errors=5,
    )

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(lead_whatsapp_validation, "SessionLocal", testing_session_local)
    monkeypatch.setattr(lead_whatsapp_validation, "get_settings", lambda: settings)
    monkeypatch.setattr(whatsapp_validation, "get_settings", lambda: settings)
    whatsapp_validation._check_whatsapp_number.cache_clear()
    _reset_validation_progress()

    main.app.dependency_overrides[main.get_db] = override_get_db
    client = TestClient(main.app)
    client.cookies.set(auth.COOKIE_NAME, auth.create_session_token(settings.app_username))
    db = testing_session_local()

    try:
        yield ApiContext(client=client, db=db, settings=settings)
    finally:
        _wait_until_not_running()
        _reset_validation_progress()
        main.app.dependency_overrides.clear()
        client.close()
        db.close()


def test_validate_whatsapp_requires_auth(api_context: ApiContext) -> None:
    api_context.client.cookies.clear()

    response = api_context.client.post("/api/leads/validate-whatsapp", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "Não autenticado"


def test_validate_whatsapp_returns_400_when_not_configured(api_context: ApiContext) -> None:
    _seed_instance(api_context.db)
    api_context.settings.evolution_api_base_url = ""

    response = api_context.client.post("/api/leads/validate-whatsapp", json={})

    assert response.status_code == 400
    assert "não configurada" in response.json()["detail"]


def test_validate_whatsapp_returns_409_when_instance_is_not_connected(api_context: ApiContext) -> None:
    _seed_instance(api_context.db, status="disconnected")

    response = api_context.client.post("/api/leads/validate-whatsapp", json={})

    assert response.status_code == 409
    assert "não está conectada" in response.json()["detail"]


def test_validate_whatsapp_returns_409_when_job_is_already_running(api_context: ApiContext) -> None:
    _seed_instance(api_context.db)
    with lead_whatsapp_validation._progress_lock:
        lead_whatsapp_validation._job_active = True
        lead_whatsapp_validation._validation_progress = {
            "job_id": "running-job",
            "status": "running",
            "total": 10,
            "processed": 2,
            "valid": 1,
            "invalid": 0,
            "unknown": 1,
            "skipped": 0,
            "started_at": "2026-08-11T10:00:00+00:00",
            "finished_at": None,
            "error": None,
        }

    try:
        response = api_context.client.post("/api/leads/validate-whatsapp", json={})
    finally:
        _reset_validation_progress()

    assert response.status_code == 409
    assert response.json()["detail"]["job_id"] == "running-job"
    assert "em andamento" in response.json()["detail"]["message"]


def test_validate_whatsapp_starts_job_and_returns_selection_counts(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_instance(api_context.db)
    run = _seed_run(api_context.db)
    first = _seed_lead(api_context.db, run=run, phone="+55 11 99999-0000")
    second = _seed_lead(api_context.db, run=run, phone="+55 11 98888-0000")
    already_valid = _seed_lead(
        api_context.db,
        run=run,
        phone="+55 11 97777-0000",
        whatsapp_validated=True,
        whatsapp_validation_status="valid",
        whatsapp_validated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(whatsapp_validation.requests, "post", lambda *args, **kwargs: FakeEvolutionResponse())

    response = api_context.client.post(
        "/api/leads/validate-whatsapp",
        json={"lead_ids": [first.id, second.id, already_valid.id], "only_pending": False},
    )
    progress = _wait_for_job()
    api_context.db.expire_all()

    assert response.status_code == 202
    data = response.json()
    assert data["job_id"]
    assert data["status"] in {"running", "completed"}
    assert data["eligible_count"] == 3
    assert data["queued_count"] == 2
    assert data["skipped_count"] == 1
    assert progress["status"] == "completed"
    assert progress["total"] == 3
    assert progress["processed"] == 3
    assert progress["valid"] == 2
    assert progress["skipped"] == 1


def test_preview_gives_lead_ids_precedence_over_filters(api_context: ApiContext) -> None:
    selected_run = _seed_run(api_context.db, niche="Marketing", location="São Paulo")
    ignored_run = _seed_run(api_context.db, niche="Contabilidade", location="Lisboa")
    selected = _seed_lead(api_context.db, run=selected_run, name="Empresa Selecionada")
    _seed_lead(api_context.db, run=ignored_run, name="Empresa Filtro")

    response = api_context.client.post(
        "/api/leads/validate-whatsapp/preview",
        json={
            "lead_ids": [selected.id],
            "niche": "Contabilidade",
            "location": "Lisboa",
            "search": "Filtro",
            "only_pending": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 1
    assert data["eligible_now"] == 1


def test_preview_uses_server_side_filters_beyond_500_lead_listing_limit(api_context: ApiContext) -> None:
    run = _seed_run(api_context.db, niche="Bulk", location="Lisboa")
    api_context.db.add_all(
        [
            Lead(
                run_id=run.id,
                name=f"Filtro {index:03d}",
                address="Rua Augusta, Lisboa",
                phone="+55 11 99999-0000",
                website=None,
                email="",
            )
            for index in range(505)
        ]
    )
    api_context.db.commit()

    response = api_context.client.post(
        "/api/leads/validate-whatsapp/preview",
        json={"niche": "Bulk", "location": "Lisboa", "search": "Filtro", "only_pending": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 505
    assert data["eligible_now"] == 505


def test_preview_does_not_call_evolution_api(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _seed_run(api_context.db)
    lead = _seed_lead(api_context.db, run=run)

    def fail_post(*args, **kwargs) -> FakeEvolutionResponse:
        raise AssertionError("Preview não deve chamar a Evolution API.")

    monkeypatch.setattr(whatsapp_validation.requests, "post", fail_post)

    response = api_context.client.post(
        "/api/leads/validate-whatsapp/preview",
        json={"lead_ids": [lead.id], "only_pending": False},
    )

    assert response.status_code == 200
    assert response.json()["eligible_now"] == 1


def test_progress_returns_idle_zeros_when_no_job_ran(api_context: ApiContext) -> None:
    response = api_context.client.get("/api/leads/validate-whatsapp/progress")

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "",
        "status": "idle",
        "total": 0,
        "processed": 0,
        "valid": 0,
        "invalid": 0,
        "unknown": 0,
        "skipped": 0,
        "started_at": None,
        "finished_at": None,
        "error": None,
    }


def test_cancel_requests_cooperative_stop_and_final_progress_is_cancelled(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_instance(api_context.db)
    run = _seed_run(api_context.db)
    leads = [_seed_lead(api_context.db, run=run, phone=f"+55 11 99999-000{index}") for index in range(2)]
    request_started = threading.Event()
    release_request = threading.Event()

    def slow_post(*args, **kwargs) -> FakeEvolutionResponse:
        request_started.set()
        if not release_request.wait(timeout=2):
            raise AssertionError("A chamada fake da Evolution não foi liberada pelo teste.")
        return FakeEvolutionResponse()

    monkeypatch.setattr(whatsapp_validation.requests, "post", slow_post)

    start_response = api_context.client.post(
        "/api/leads/validate-whatsapp",
        json={"lead_ids": [lead.id for lead in leads], "only_pending": False},
    )
    assert start_response.status_code == 202
    assert request_started.wait(timeout=1)

    cancel_response = api_context.client.post("/api/leads/validate-whatsapp/cancel")
    release_request.set()
    progress = _wait_for_job()

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "running"
    assert progress["status"] == "cancelled"
    assert progress["processed"] == 1
    assert progress["valid"] == 1
    assert progress["error"] == "Validação de WhatsApp cancelada pelo usuário."


def test_list_leads_filters_by_never_validated_whatsapp_status(api_context: ApiContext) -> None:
    run = _seed_run(api_context.db)
    never = _seed_lead(api_context.db, run=run, name="Nunca Validado")
    _seed_lead(
        api_context.db,
        run=run,
        name="Já Validado",
        whatsapp_validated=True,
        whatsapp_validation_status="valid",
        whatsapp_validated_at=datetime.now(timezone.utc),
    )

    response = api_context.client.get("/api/leads?whatsapp_status=never")

    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "1"
    assert response.headers["X-Result-Limit"] == "500"
    data = response.json()
    assert [lead["id"] for lead in data] == [never.id]
    assert data[0]["whatsapp_validation_status"] is None
    assert data[0]["whatsapp_validated_at"] is None


def _seed_instance(db: Session, *, status: str = "connected") -> WhatsAppInstance:
    instance = WhatsAppInstance(
        name="sales-main",
        provider="evolution",
        status=status,
        evolution_instance_name="sales-main",
        connected_at=datetime.now(timezone.utc) if status == "connected" else None,
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


def _seed_run(db: Session, *, niche: str = "Marketing", location: str = "São Paulo") -> SearchRun:
    run = SearchRun(
        niche=niche,
        location=location,
        target_quantity=10,
        max_results=False,
        skip_without_website=False,
        validate_whatsapp=False,
        status="completed",
        message="Busca concluída.",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _seed_lead(
    db: Session,
    *,
    run: SearchRun,
    name: str | None = None,
    phone: str = "+55 11 99999-0000",
    whatsapp_validated: bool | None = None,
    whatsapp_validation_status: str | None = None,
    whatsapp_validated_at: datetime | None = None,
) -> Lead:
    lead = Lead(
        run_id=run.id,
        name=name or f"Empresa {time.monotonic_ns()}",
        address="Av. Paulista, 1000 - São Paulo, SP",
        phone=phone,
        website=None,
        email="",
        whatsapp_validated=whatsapp_validated,
        whatsapp_validation_status=whatsapp_validation_status,
        whatsapp_validated_at=whatsapp_validated_at,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _reset_validation_progress() -> None:
    with lead_whatsapp_validation._progress_lock:
        lead_whatsapp_validation._job_active = False
        lead_whatsapp_validation._cancel_requested = False
        lead_whatsapp_validation._validation_progress = lead_whatsapp_validation._idle_progress()


def _wait_until_not_running(timeout: float = 5) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        progress = lead_whatsapp_validation.get_validation_progress()
        if progress["status"] != "running":
            return progress
        time.sleep(0.01)
    return lead_whatsapp_validation.get_validation_progress()


def _wait_for_job(timeout: float = 5) -> dict[str, Any]:
    progress = _wait_until_not_running(timeout=timeout)
    if progress["status"] == "running":
        raise AssertionError("O job de validação não terminou dentro do tempo esperado.")
    return progress
