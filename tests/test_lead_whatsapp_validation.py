from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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


@pytest.fixture()
def db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    settings = SimpleNamespace(
        evolution_api_base_url="https://evolution.example.test",
        evolution_api_key="test-api-key",
        evolution_instance_name="sales-main",
        whatsapp_validation_timeout_seconds=5,
        whatsapp_batch_validation_delay_seconds=0,
        whatsapp_batch_validation_max_retries=0,
        whatsapp_batch_validation_max_consecutive_errors=5,
    )
    monkeypatch.setattr(lead_whatsapp_validation, "SessionLocal", testing_session_local)
    monkeypatch.setattr(lead_whatsapp_validation, "get_settings", lambda: settings)
    monkeypatch.setattr(whatsapp_validation, "get_settings", lambda: settings)
    whatsapp_validation._check_whatsapp_number.cache_clear()

    db = testing_session_local()
    try:
        _seed_instance(db)
        yield db
    finally:
        db.close()


def test_saved_lead_with_valid_number_is_marked_valid(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = _seed_lead(db_session, phone="+55 11 99999-0000")
    monkeypatch.setattr(whatsapp_validation.requests, "post", lambda *args, **kwargs: FakeEvolutionResponse(exists=True))

    progress = _start_and_wait(lead_ids=[lead.id])
    db_session.expire_all()
    refreshed = db_session.get(Lead, lead.id)

    assert progress["status"] == "completed"
    assert progress["valid"] == 1
    assert refreshed is not None
    assert refreshed.whatsapp_validated is True
    assert refreshed.whatsapp_validation_status == "valid"
    assert refreshed.whatsapp_validation_reason is None
    assert refreshed.whatsapp_validated_at is not None


def test_saved_lead_without_whatsapp_is_marked_invalid(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = _seed_lead(db_session, phone="+55 11 99999-0000")
    monkeypatch.setattr(whatsapp_validation.requests, "post", lambda *args, **kwargs: FakeEvolutionResponse(exists=False))

    progress = _start_and_wait(lead_ids=[lead.id])
    db_session.expire_all()
    refreshed = db_session.get(Lead, lead.id)

    assert progress["status"] == "completed"
    assert progress["invalid"] == 1
    assert refreshed is not None
    assert refreshed.whatsapp_validated is False
    assert refreshed.whatsapp_validation_status == "invalid"
    assert refreshed.whatsapp_validation_reason == "not_registered"
    assert refreshed.whatsapp_validated_at is not None


def test_api_error_marks_lead_unknown_without_turning_it_false(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = _seed_lead(db_session, phone="+55 11 99999-0000")
    monkeypatch.setattr(whatsapp_validation.requests, "post", lambda *args, **kwargs: FakeEvolutionResponse(status_code=500))

    progress = _start_and_wait(lead_ids=[lead.id])
    db_session.expire_all()
    refreshed = db_session.get(Lead, lead.id)

    assert progress["status"] == "completed"
    assert progress["unknown"] == 1
    assert refreshed is not None
    assert refreshed.whatsapp_validated is None
    assert refreshed.whatsapp_validation_status == "unknown"
    assert refreshed.whatsapp_validation_reason == "api_error"
    assert refreshed.whatsapp_validated_at is not None


def test_lead_without_phone_is_unknown_no_phone_without_http_call(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = _seed_lead(db_session, phone="")

    def fail_post(*args, **kwargs) -> FakeEvolutionResponse:
        raise AssertionError("A Evolution API não deveria ser chamada para lead sem telefone.")

    monkeypatch.setattr(whatsapp_validation.requests, "post", fail_post)

    progress = _start_and_wait(lead_ids=[lead.id])
    db_session.expire_all()
    refreshed = db_session.get(Lead, lead.id)

    assert progress["status"] == "completed"
    assert progress["unknown"] == 1
    assert refreshed is not None
    assert refreshed.whatsapp_validated is None
    assert refreshed.whatsapp_validation_status == "unknown"
    assert refreshed.whatsapp_validation_reason == "no_phone"
    assert refreshed.whatsapp_validated_at is not None


def test_international_plus_34_number_is_normalized_without_default_region(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = _seed_lead(db_session, phone="+34 600 123 456", address="Rua A, Fortaleza, CE")
    captured_payloads: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs) -> FakeEvolutionResponse:
        captured_payloads.append(kwargs["json"])
        return FakeEvolutionResponse(exists=True)

    monkeypatch.setattr(whatsapp_validation.requests, "post", fake_post)

    _start_and_wait(lead_ids=[lead.id])

    assert whatsapp_validation.normalize_phone_e164("+34 600 123 456", "Fortaleza, CE") == "+34600123456"
    assert captured_payloads == [{"numbers": ["+34600123456"]}]


def test_revalidate_false_skips_already_validated_and_reprocesses_unknown(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated_at = datetime.now(timezone.utc)
    already_valid = _seed_lead(
        db_session,
        phone="+55 11 99999-0000",
        whatsapp_validated=True,
        whatsapp_validation_status="valid",
        whatsapp_validated_at=validated_at,
    )
    unknown = _seed_lead(
        db_session,
        phone="+55 11 98888-0000",
        whatsapp_validated=None,
        whatsapp_validation_status="unknown",
        whatsapp_validation_reason="api_error",
        whatsapp_validated_at=validated_at,
    )
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs) -> FakeEvolutionResponse:
        calls.append(kwargs["json"])
        return FakeEvolutionResponse(exists=True)

    monkeypatch.setattr(whatsapp_validation.requests, "post", fake_post)

    progress = _start_and_wait(lead_ids=[already_valid.id, unknown.id], revalidate=False)
    db_session.expire_all()
    refreshed_valid = db_session.get(Lead, already_valid.id)
    refreshed_unknown = db_session.get(Lead, unknown.id)

    assert progress["status"] == "completed"
    assert progress["processed"] == 2
    assert progress["skipped"] == 1
    assert progress["valid"] == 1
    assert calls == [{"numbers": ["+5511988880000"]}]
    assert refreshed_valid is not None
    assert refreshed_valid.whatsapp_validated is True
    assert refreshed_valid.whatsapp_validation_status == "valid"
    assert refreshed_unknown is not None
    assert refreshed_unknown.whatsapp_validated is True
    assert refreshed_unknown.whatsapp_validation_status == "valid"


def test_circuit_breaker_aborts_after_five_consecutive_api_errors(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leads = [_seed_lead(db_session, phone=f"+55 11 99999-000{index}") for index in range(6)]
    monkeypatch.setattr(whatsapp_validation.requests, "post", lambda *args, **kwargs: FakeEvolutionResponse(status_code=500))

    progress = _start_and_wait(lead_ids=[lead.id for lead in leads])
    db_session.expire_all()
    refreshed = [db_session.get(Lead, lead.id) for lead in leads]

    assert progress["status"] == "aborted"
    assert progress["processed"] == 5
    assert progress["unknown"] == 5
    assert "5 falhas consecutivas" in (progress["error"] or "")
    for lead in refreshed[:5]:
        assert lead is not None
        assert lead.whatsapp_validation_status == "unknown"
        assert lead.whatsapp_validation_reason == "api_error"
        assert lead.whatsapp_validated_at is not None
    assert refreshed[5] is not None
    assert refreshed[5].whatsapp_validation_status is None
    assert refreshed[5].whatsapp_validated_at is None


def test_revalidation_path_ignores_lru_cache(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = _seed_lead(db_session, phone="+55 11 99999-0000")
    responses = [FakeEvolutionResponse(exists=True), FakeEvolutionResponse(exists=False)]
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs) -> FakeEvolutionResponse:
        calls.append(kwargs["json"])
        return responses.pop(0)

    monkeypatch.setattr(whatsapp_validation.requests, "post", fake_post)

    cached = whatsapp_validation.validate_whatsapp_number("+55 11 99999-0000", instance_name="sales-main")
    assert cached.is_valid is True

    _start_and_wait(lead_ids=[lead.id], revalidate=True)
    db_session.expire_all()
    refreshed = db_session.get(Lead, lead.id)

    assert calls == [{"numbers": ["+5511999990000"]}, {"numbers": ["+5511999990000"]}]
    assert refreshed is not None
    assert refreshed.whatsapp_validated is False
    assert refreshed.whatsapp_validation_status == "invalid"


def _seed_instance(db: Session) -> None:
    db.add(
        WhatsAppInstance(
            name="sales-main",
            provider="evolution",
            status="connected",
            evolution_instance_name="sales-main",
            connected_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def _seed_lead(
    db: Session,
    *,
    phone: str,
    address: str = "Av. Paulista, 1000 - São Paulo, SP",
    whatsapp_validated: bool | None = None,
    whatsapp_validation_status: str | None = None,
    whatsapp_validation_reason: str | None = None,
    whatsapp_validated_at: datetime | None = None,
) -> Lead:
    run = db.query(SearchRun).first()
    if not run:
        run = SearchRun(
            niche="Marketing",
            location="São Paulo",
            target_quantity=10,
            max_results=False,
            skip_without_website=False,
            validate_whatsapp=False,
            status="completed",
            message="Busca concluída.",
        )
        db.add(run)
        db.flush()

    lead = Lead(
        run_id=run.id,
        name=f"Empresa {time.monotonic_ns()}",
        address=address,
        phone=phone,
        website=None,
        email="",
        whatsapp_validated=whatsapp_validated,
        whatsapp_validation_status=whatsapp_validation_status,
        whatsapp_validation_reason=whatsapp_validation_reason,
        whatsapp_validated_at=whatsapp_validated_at,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _start_and_wait(**kwargs) -> dict[str, Any]:
    lead_whatsapp_validation.start_lead_whatsapp_validation_job(**kwargs)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        progress = lead_whatsapp_validation.get_validation_progress()
        if progress["status"] != "running":
            return progress
        time.sleep(0.01)
    raise AssertionError("O job de validação não terminou dentro do tempo esperado.")
