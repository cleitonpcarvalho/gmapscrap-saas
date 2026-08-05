from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import LeadList, WhatsAppCampaign, WhatsAppInstance
from backend.services import whatsapp_instance_monitor
from backend.services.whatsapp_providers.evolution import EvolutionProvider


class FakeEvolutionResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture()
def db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def seed_instance_with_running_campaign(db: Session, *, instance_status: str = "connected") -> dict[str, int]:
    instance = WhatsAppInstance(
        name="sales-main",
        provider="evolution",
        status=instance_status,
        evolution_instance_name="sales-main",
    )
    lead_list = LeadList(name="Lista WhatsApp", niche_filter="", location_filter="")
    db.add_all([instance, lead_list])
    db.flush()

    campaign = WhatsAppCampaign(
        name="Lojas de Suplementos SP",
        list_id=lead_list.id,
        instance_id=instance.id,
        status="running",
    )
    db.add(campaign)
    db.commit()

    return {"instance_id": instance.id, "campaign_id": campaign.id}


def test_refresh_instance_status_pauses_running_campaigns_when_disconnected(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_instance_with_running_campaign(db_session, instance_status="connected")
    instance = db_session.get(WhatsAppInstance, ids["instance_id"])

    def fake_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        assert method == "GET"
        assert url.endswith("/instance/connectionState/sales-main")
        return FakeEvolutionResponse(200, {"instance": {"instanceName": "sales-main", "state": "close"}})

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)

    provider_state = whatsapp_instance_monitor.refresh_instance_status(db_session, instance, EvolutionProvider())
    db_session.commit()

    assert provider_state == "close"
    assert instance.status == "disconnected"

    campaign = db_session.get(WhatsAppCampaign, ids["campaign_id"])
    assert campaign.status == "paused"
    assert campaign.error == "Instância de WhatsApp desconectada."


def test_refresh_instance_status_keeps_campaign_running_when_still_connected(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_instance_with_running_campaign(db_session, instance_status="connected")
    instance = db_session.get(WhatsAppInstance, ids["instance_id"])

    def fake_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        return FakeEvolutionResponse(200, {"instance": {"instanceName": "sales-main", "state": "open"}})

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)

    whatsapp_instance_monitor.refresh_instance_status(db_session, instance, EvolutionProvider())
    db_session.commit()

    assert instance.status == "connected"
    campaign = db_session.get(WhatsAppCampaign, ids["campaign_id"])
    assert campaign.status == "running"


def test_refresh_instance_status_leaves_status_untouched_when_evolution_is_unreachable(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_instance_with_running_campaign(db_session, instance_status="connected")
    instance = db_session.get(WhatsAppInstance, ids["instance_id"])

    import requests

    def fake_request(method: str, url: str, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)

    provider_state = whatsapp_instance_monitor.refresh_instance_status(db_session, instance, EvolutionProvider())

    assert provider_state is None
    assert instance.status == "connected"

    campaign = db_session.get(WhatsAppCampaign, ids["campaign_id"])
    assert campaign.status == "running"


def test_refresh_all_instance_statuses_updates_every_instance(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_instance_with_running_campaign(db_session, instance_status="connected")

    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=db_session.get_bind())
    monkeypatch.setattr(whatsapp_instance_monitor, "SessionLocal", testing_session_local)

    def fake_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        return FakeEvolutionResponse(200, {"instance": {"instanceName": "sales-main", "state": "close"}})

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)

    whatsapp_instance_monitor.refresh_all_instance_statuses()

    instance = db_session.scalar(select(WhatsAppInstance).where(WhatsAppInstance.id == ids["instance_id"]))
    campaign = db_session.scalar(select(WhatsAppCampaign).where(WhatsAppCampaign.id == ids["campaign_id"]))
    assert instance.status == "disconnected"
    assert campaign.status == "paused"
