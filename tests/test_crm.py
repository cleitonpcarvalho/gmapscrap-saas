from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main
from backend.database import Base
from backend.models import CrmLead, CrmStageHistory, Lead, SearchRun, WhatsAppConversation, WhatsAppInstance, WhatsAppMessage
from backend.schemas import CrmLeadUpdate


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()


def seed_lead(db: Session, *, name: str = "Lead Alpha", phone: str = "+5511999990000") -> Lead:
    run = SearchRun(
        niche="Dental Clinics",
        location="Sao Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=True,
        status="completed",
        message="Done",
    )
    db.add(run)
    db.flush()

    lead = Lead(
        run_id=run.id,
        name=name,
        address="Av Paulista, 1000",
        phone=phone,
        website=None,
        email="contact@example.test",
    )
    db.add(lead)
    db.flush()
    return lead


def test_list_crm_leads_filters_by_stage_and_includes_latest_message(db_session: Session) -> None:
    qualified_lead = seed_lead(db_session, name="Qualified Lead")
    new_lead = seed_lead(db_session, name="New Lead", phone="+5511888880000")
    instance = WhatsAppInstance(
        name="sales-main",
        provider="evolution",
        status="connected",
        evolution_instance_name="sales-main",
    )
    db_session.add(instance)
    db_session.flush()

    db_session.add_all(
        [
            CrmLead(lead_id=qualified_lead.id, stage="qualified", qualification_notes="Ready"),
            CrmLead(lead_id=new_lead.id, stage="new"),
        ]
    )
    db_session.flush()
    conversation = WhatsAppConversation(
        lead_id=qualified_lead.id,
        instance_id=instance.id,
        status="open",
        last_message_at=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        WhatsAppMessage(
            conversation_id=conversation.id,
            direction="inbound",
            content="I want to talk to sales",
            message_type="text",
            provider_message_id="MSG_1",
            created_at=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    result = main.list_crm_leads(stage="qualified", db=db_session, username="test-user")

    assert len(result) == 1
    assert result[0].lead_id == qualified_lead.id
    assert result[0].stage == "qualified"
    assert result[0].lead_name == "Qualified Lead"
    assert result[0].phone == "+5511999990000"
    assert result[0].niche == "Dental Clinics"
    assert result[0].last_message == "I want to talk to sales"
    assert result[0].conversation_id == conversation.id


def test_list_crm_leads_orders_by_position(db_session: Session) -> None:
    first_lead = seed_lead(db_session, name="First Lead")
    second_lead = seed_lead(db_session, name="Second Lead", phone="+5511888880000")
    third_lead = seed_lead(db_session, name="Third Lead", phone="+5511777770000")
    db_session.add_all(
        [
            CrmLead(lead_id=first_lead.id, stage="new", position=2),
            CrmLead(lead_id=second_lead.id, stage="new", position=0),
            CrmLead(lead_id=third_lead.id, stage="new", position=1),
        ]
    )
    db_session.commit()

    result = main.list_crm_leads(stage="new", db=db_session, username="test-user")

    assert [lead.lead_id for lead in result] == [second_lead.id, third_lead.id, first_lead.id]
    assert [lead.position for lead in result] == [0, 1, 2]


def test_update_crm_lead_stage_creates_manual_history(db_session: Session) -> None:
    lead = seed_lead(db_session)
    crm_lead = CrmLead(lead_id=lead.id, stage="new")
    db_session.add(crm_lead)
    db_session.commit()

    result = main.update_crm_lead(
        lead.id,
        CrmLeadUpdate(stage="qualified", qualification_notes="Budget confirmed"),
        db=db_session,
        username="test-user",
    )

    history = db_session.scalars(select(CrmStageHistory)).one()
    db_session.refresh(crm_lead)

    assert result.stage == "qualified"
    assert result.qualification_notes == "Budget confirmed"
    assert crm_lead.stage == "qualified"
    assert history.crm_lead_id == crm_lead.id
    assert history.from_stage == "new"
    assert history.to_stage == "qualified"
    assert history.changed_by == "manual"


def test_update_crm_lead_accepts_stage_and_position_together(db_session: Session) -> None:
    source_first = seed_lead(db_session, name="Source First")
    moving_lead = seed_lead(db_session, name="Moving Lead", phone="+5511888880000")
    target_first = seed_lead(db_session, name="Target First", phone="+5511777770000")
    target_second = seed_lead(db_session, name="Target Second", phone="+5511666660000")
    db_session.add_all(
        [
            CrmLead(lead_id=source_first.id, stage="new", position=0),
            CrmLead(lead_id=moving_lead.id, stage="new", position=1),
            CrmLead(lead_id=target_first.id, stage="qualified", position=0),
            CrmLead(lead_id=target_second.id, stage="qualified", position=1),
        ]
    )
    db_session.commit()

    result = main.update_crm_lead(
        moving_lead.id,
        CrmLeadUpdate(stage="qualified", position=1),
        db=db_session,
        username="test-user",
    )

    history = db_session.scalars(select(CrmStageHistory)).one()
    crm_rows = list(db_session.scalars(select(CrmLead)).all())
    positions = {(row.lead_id, row.stage): row.position for row in crm_rows}

    assert result.stage == "qualified"
    assert result.position == 1
    assert positions[(source_first.id, "new")] == 0
    assert positions[(target_first.id, "qualified")] == 0
    assert positions[(moving_lead.id, "qualified")] == 1
    assert positions[(target_second.id, "qualified")] == 2
    assert history.from_stage == "new"
    assert history.to_stage == "qualified"
    assert history.changed_by == "manual"


def test_update_crm_lead_creates_crm_record_when_missing(db_session: Session) -> None:
    lead = seed_lead(db_session)
    db_session.commit()

    result = main.update_crm_lead(
        lead.id,
        CrmLeadUpdate(qualification_notes="First manual note"),
        db=db_session,
        username="test-user",
    )

    crm_lead = db_session.scalars(select(CrmLead)).one()
    assert result.stage == "new"
    assert result.qualification_notes == "First manual note"
    assert crm_lead.lead_id == lead.id
    assert db_session.scalars(select(CrmStageHistory)).all() == []


def test_list_crm_leads_rejects_invalid_stage(db_session: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        main.list_crm_leads(stage="bad-stage", db=db_session, username="test-user")

    assert exc_info.value.status_code == 422
