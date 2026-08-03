from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main
from backend.database import Base
from backend.schemas import WhatsAppInstanceCreate


class FakeEvolutionResponse:
    def __init__(self, status_code: int, payload: dict[str, Any], text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture()
def db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(
        "backend.services.whatsapp_providers.evolution.get_settings",
        lambda: SimpleNamespace(
            evolution_api_base_url="https://evolution.example.test",
            evolution_api_key="test-api-key",
            whatsapp_validation_timeout_seconds=5,
        ),
    )
    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()


def test_whatsapp_instance_lifecycle_endpoints(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        calls.append((method, url))
        if method == "POST" and url.endswith("/instance/create"):
            assert kwargs["json"]["instanceName"] == "sales-main"
            return FakeEvolutionResponse(201, {"instance": {"instanceName": "sales-main"}})
        if method == "GET" and url.endswith("/instance/connect/sales-main"):
            return FakeEvolutionResponse(
                200,
                {"base64": "data:image/png;base64,abc", "code": "2@example", "pairingCode": None},
            )
        if method == "GET" and url.endswith("/instance/connectionState/sales-main"):
            return FakeEvolutionResponse(
                200,
                {
                    "instance": {
                        "instanceName": "sales-main",
                        "state": "open",
                        "ownerJid": "5511999999999@s.whatsapp.net",
                    }
                },
            )
        if method == "DELETE" and url.endswith("/instance/delete/sales-main"):
            return FakeEvolutionResponse(200, {"status": "SUCCESS"})
        return FakeEvolutionResponse(500, {}, "unexpected request")

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)

    instance = main.create_whatsapp_instance(
        WhatsAppInstanceCreate(name="sales-main"),
        db=db_session,
        username="test-user",
    )
    assert instance.status == "disconnected"
    assert instance.evolution_instance_name == "sales-main"

    listed = main.list_whatsapp_instances(db=db_session, username="test-user")
    assert [item.name for item in listed] == ["sales-main"]

    qrcode = main.get_whatsapp_instance_qrcode(instance.id, db=db_session, username="test-user")
    assert qrcode.base64 == "data:image/png;base64,abc"
    assert qrcode.code == "2@example"

    current_status = main.get_whatsapp_instance_status(instance.id, db=db_session, username="test-user")
    assert current_status.provider_state == "open"
    assert current_status.status == "connected"
    assert current_status.phone_number == "5511999999999"
    assert current_status.connected_at

    deleted = main.delete_whatsapp_instance(instance.id, db=db_session, username="test-user")
    assert deleted == {"status": "ok"}

    listed_after_delete = main.list_whatsapp_instances(db=db_session, username="test-user")
    assert listed_after_delete == []
    assert calls == [
        ("POST", "https://evolution.example.test/instance/create"),
        ("GET", "https://evolution.example.test/instance/connect/sales-main"),
        ("GET", "https://evolution.example.test/instance/connectionState/sales-main"),
        ("DELETE", "https://evolution.example.test/instance/delete/sales-main"),
    ]


def test_whatsapp_status_returns_404_when_provider_instance_is_missing(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        if method == "POST" and url.endswith("/instance/create"):
            return FakeEvolutionResponse(201, {"instance": {"instanceName": "missing-instance"}})
        if method == "GET" and url.endswith("/instance/connectionState/missing-instance"):
            return FakeEvolutionResponse(404, {"message": "not found"}, "not found")
        return FakeEvolutionResponse(500, {}, "unexpected request")

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)

    instance = main.create_whatsapp_instance(
        WhatsAppInstanceCreate(name="missing-instance"),
        db=db_session,
        username="test-user",
    )

    with pytest.raises(HTTPException) as exc_info:
        main.get_whatsapp_instance_status(instance.id, db=db_session, username="test-user")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Instância Evolution não encontrada."


def test_whatsapp_create_returns_502_when_provider_is_unavailable(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        main.create_whatsapp_instance(
            WhatsAppInstanceCreate(name="offline-instance"),
            db=db_session,
            username="test-user",
        )

    assert exc_info.value.status_code == 502
    assert "Evolution API indisponível" in str(exc_info.value.detail)

    listed = main.list_whatsapp_instances(db=db_session, username="test-user")
    assert listed == []
