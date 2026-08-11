from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from backend import database, main
from backend.database import Base
from backend.models import (
    CrmFunnel,
    CrmFunnelStage,
    CrmLead,
    Lead,
    LeadList,
    SearchRun,
    WhatsAppCampaign,
    WhatsAppInstance,
    WhatsAppSend,
)
from backend.schemas import CrmFunnelCreate
from backend.services.crm import get_default_crm_funnel, get_or_create_crm_lead, update_crm_stage


WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture()
def db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(evolution_webhook_secret=WEBHOOK_SECRET))
    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()


def seed_lead(db: Session, *, phone: str = "+5511999990000") -> Lead:
    run = SearchRun(
        niche="ERP",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=False,
        status="completed",
        message="Done",
    )
    db.add(run)
    db.flush()
    lead = Lead(
        run_id=run.id,
        name="Lead Alpha",
        address="Av Paulista, 1000",
        phone=phone,
        website=None,
        email="lead@example.test",
    )
    db.add(lead)
    db.flush()
    return lead


def seed_custom_funnel(db: Session, name: str = "Funil B") -> tuple[CrmFunnel, CrmFunnelStage]:
    funnel = CrmFunnel(name=name, description="", is_default=False)
    db.add(funnel)
    db.flush()
    stage = CrmFunnelStage(
        funnel_id=funnel.id,
        key="first",
        label="Primeiro contato",
        color="#e0f2fe",
        position=0,
        is_won=False,
        is_lost=False,
    )
    db.add(stage)
    db.flush()
    return funnel, stage


def seed_lead_list(db: Session) -> LeadList:
    lead_list = LeadList(name="Lista WhatsApp", channel="whatsapp")
    db.add(lead_list)
    db.flush()
    return lead_list


def seed_instance(db: Session) -> WhatsAppInstance:
    instance = WhatsAppInstance(
        name="sales-main",
        provider="evolution",
        status="connected",
        evolution_instance_name="sales-main",
    )
    db.add(instance)
    db.flush()
    return instance


def webhook_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/whatsapp/webhook/evolution",
            "headers": [(b"x-evolution-webhook-secret", WEBHOOK_SECRET.encode())],
        }
    )


def evolution_text_payload() -> dict[str, Any]:
    return {
        "event": "MESSAGES_UPSERT",
        "instance": "sales-main",
        "data": {
            "key": {
                "remoteJid": "5511999990000@s.whatsapp.net",
                "fromMe": False,
                "id": "CRM_FUNNEL_REPLY_1",
            },
            "message": {"conversation": "Tenho interesse."},
            "messageType": "conversation",
            "messageTimestamp": 1709553296,
        },
    }


def test_migration_creates_default_funnel_and_backfills_existing_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE crm_leads (
                    id INTEGER PRIMARY KEY,
                    lead_id INTEGER NOT NULL UNIQUE,
                    stage VARCHAR(30) NOT NULL CHECK (stage IN ('new', 'responded', 'qualified', 'not_interested', 'converted')),
                    qualification_notes TEXT,
                    score INTEGER,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text("INSERT INTO crm_leads (id, lead_id, stage, updated_at) VALUES (1, 101, 'qualified', '2026-01-01')")
        )

    monkeypatch.setattr(database, "engine", engine)

    database._ensure_crm_lead_columns()

    with engine.begin() as connection:
        funnel = connection.execute(text("SELECT id, name, is_default FROM crm_funnels")).one()
        stages = connection.execute(text("SELECT key, label, is_won, is_lost FROM crm_funnel_stages ORDER BY position")).all()
        card = connection.execute(text("SELECT lead_id, funnel_id, stage_id, stage FROM crm_leads")).one()
        qualified_stage_id = connection.execute(
            text("SELECT id FROM crm_funnel_stages WHERE funnel_id = :funnel_id AND key = 'qualified'"),
            {"funnel_id": funnel.id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO crm_funnels (id, name, description, is_default) "
                "VALUES (99, 'Funil custom', '', 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO crm_funnel_stages (id, funnel_id, key, label, color, position, is_won, is_lost) "
                "VALUES (199, 99, 'custom_stage', 'Custom', '#e0f2fe', 0, 0, 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO crm_leads (id, lead_id, funnel_id, stage_id, stage, updated_at) "
                "VALUES (2, 101, 99, 199, 'custom_stage', '2026-01-02')"
            )
        )

    assert funnel.name == "Funil padrão"
    assert bool(funnel.is_default) is True
    assert [stage.key for stage in stages] == ["new", "responded", "qualified", "not_interested", "converted"]
    assert stages[3].is_lost
    assert stages[4].is_won
    assert card.funnel_id == funnel.id
    assert card.stage_id == qualified_stage_id
    assert card.stage == "qualified"


def test_migration_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE crm_leads (
                    id INTEGER PRIMARY KEY,
                    lead_id INTEGER NOT NULL,
                    stage VARCHAR(30) NOT NULL,
                    qualification_notes TEXT,
                    score INTEGER,
                    updated_at DATETIME
                )
                """
            )
        )

    monkeypatch.setattr(database, "engine", engine)

    database._ensure_crm_lead_columns()
    database._ensure_crm_lead_columns()

    with engine.connect() as connection:
        funnel_count = connection.execute(text("SELECT COUNT(*) FROM crm_funnels WHERE is_default = 1")).scalar_one()
        stage_count = connection.execute(text("SELECT COUNT(*) FROM crm_funnel_stages")).scalar_one()

    assert funnel_count == 1
    assert stage_count == 5


def test_lead_can_have_cards_in_two_funnels(db_session: Session) -> None:
    lead = seed_lead(db_session)
    custom_funnel, _ = seed_custom_funnel(db_session)

    default_card = get_or_create_crm_lead(db_session, lead.id)
    custom_card = get_or_create_crm_lead(db_session, lead.id, funnel_id=custom_funnel.id)
    db_session.commit()

    assert default_card.id != custom_card.id
    assert db_session.scalar(select(func.count(CrmLead.id)).where(CrmLead.lead_id == lead.id)) == 2


def test_update_crm_stage_string_still_works_for_ai(db_session: Session) -> None:
    lead = seed_lead(db_session)
    get_or_create_crm_lead(db_session, lead.id)

    result = update_crm_stage(db_session, lead.id, "qualified", changed_by="ai", reason="Cliente pediu proposta")
    db_session.commit()

    assert result.stage == "qualified"
    assert result.qualification_notes == "Cliente pediu proposta"


def test_update_crm_stage_missing_key_falls_back_without_error(db_session: Session) -> None:
    lead = seed_lead(db_session)
    funnel, first_stage = seed_custom_funnel(db_session)
    won_stage = CrmFunnelStage(
        funnel_id=funnel.id,
        key="ganho",
        label="Ganho",
        color="#dcf6e8",
        position=1,
        is_won=True,
        is_lost=False,
    )
    db_session.add(won_stage)
    db_session.flush()
    get_or_create_crm_lead(db_session, lead.id, funnel_id=funnel.id, stage=first_stage.key)

    result = update_crm_stage(db_session, lead.id, "converted", changed_by="ai")
    db_session.commit()

    assert result.stage == "ganho"


def test_cannot_delete_default_or_funnel_with_cards_without_destination(db_session: Session) -> None:
    lead = seed_lead(db_session)
    default_funnel = get_default_crm_funnel(db_session)
    custom_funnel, _ = seed_custom_funnel(db_session)
    get_or_create_crm_lead(db_session, lead.id, funnel_id=custom_funnel.id)
    db_session.commit()

    with pytest.raises(HTTPException) as default_exc:
        main.delete_crm_funnel(default_funnel.id, db=db_session, username="test-user")
    with pytest.raises(HTTPException) as cards_exc:
        main.delete_crm_funnel(custom_funnel.id, db=db_session, username="test-user")

    assert default_exc.value.status_code == 409
    assert "padrão" in str(default_exc.value.detail)
    assert cards_exc.value.status_code == 409
    assert "cards" in str(cards_exc.value.detail)


def test_replying_to_campaign_creates_card_in_campaign_funnel(db_session: Session) -> None:
    lead = seed_lead(db_session)
    get_or_create_crm_lead(db_session, lead.id)
    custom_funnel, _ = seed_custom_funnel(db_session)
    lead_list = seed_lead_list(db_session)
    instance = seed_instance(db_session)
    campaign = WhatsAppCampaign(
        name="Campanha Funil B",
        list_id=lead_list.id,
        instance_id=instance.id,
        funnel_id=custom_funnel.id,
        status="running",
        message="Rodando",
    )
    db_session.add(campaign)
    db_session.flush()
    db_session.add(
        WhatsAppSend(
            campaign_id=campaign.id,
            lead_id=lead.id,
            recipient_phone=lead.phone,
            status="sent",
        )
    )
    db_session.commit()

    response = main.receive_evolution_webhook(evolution_text_payload(), request=webhook_request(), db=db_session)

    cards = list(db_session.scalars(select(CrmLead).where(CrmLead.lead_id == lead.id)).all())
    assert response["status"] == "ok"
    assert {card.funnel_id for card in cards} == {get_default_crm_funnel(db_session).id, custom_funnel.id}
