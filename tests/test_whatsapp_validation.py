from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import WhatsAppInstance
from backend.services import whatsapp_validation


class FakeWhatsAppValidationResponse:
    ok = True

    def json(self) -> dict[str, Any]:
        return {"numbers": [{"exists": True}]}


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return testing_session_local()


def test_whatsapp_validation_uses_database_instance_when_env_instance_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        whatsapp_validation,
        "get_settings",
        lambda: SimpleNamespace(
            evolution_api_base_url="https://evolution.example.test",
            evolution_api_key="test-api-key",
            evolution_instance_name="",
            whatsapp_validation_timeout_seconds=5,
        ),
    )

    db = _session()
    try:
        db.add(
            WhatsAppInstance(
                name="GmapScrap",
                provider="evolution",
                status="connected",
                evolution_instance_name="gmapscrap-prod",
                connected_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        assert whatsapp_validation.get_whatsapp_validation_instance_name(db) == "gmapscrap-prod"
        assert whatsapp_validation.is_whatsapp_validation_configured(db) is True
        assert whatsapp_validation.is_whatsapp_validation_configured() is False
    finally:
        db.close()


def test_validate_whatsapp_number_uses_resolved_instance_name(monkeypatch) -> None:
    calls: list[str] = []
    whatsapp_validation._check_whatsapp_number.cache_clear()

    monkeypatch.setattr(
        whatsapp_validation,
        "get_settings",
        lambda: SimpleNamespace(
            evolution_api_base_url="https://evolution.example.test",
            evolution_api_key="test-api-key",
            evolution_instance_name="",
            whatsapp_validation_timeout_seconds=5,
        ),
    )

    def fake_post(url: str, **kwargs) -> FakeWhatsAppValidationResponse:
        calls.append(url)
        assert kwargs["headers"]["apikey"] == "test-api-key"
        assert kwargs["json"] == {"numbers": ["+5511999999999"]}
        assert kwargs["timeout"] == 5
        return FakeWhatsAppValidationResponse()

    monkeypatch.setattr(whatsapp_validation.requests, "post", fake_post)

    result = whatsapp_validation.validate_whatsapp_number(
        "+55 11 99999-9999",
        instance_name="gmapscrap-prod",
    )

    assert result.is_valid is True
    assert calls == ["https://evolution.example.test/chat/whatsappNumbers/gmapscrap-prod"]
