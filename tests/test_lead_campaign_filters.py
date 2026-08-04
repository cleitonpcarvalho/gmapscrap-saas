from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main
from backend.database import Base
from backend.models import (
    EmailCampaign,
    EmailSend,
    EmailTemplate,
    Lead,
    LeadList,
    SearchRun,
    WhatsAppCampaign,
    WhatsAppConversation,
    WhatsAppInstance,
    WhatsAppMessage,
    WhatsAppSend,
)


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


def seed_leads(db: Session) -> list[Lead]:
    run = SearchRun(
        niche="Sapataria",
        location="São Paulo",
        target_quantity=20,
        max_results=False,
        skip_without_website=False,
        validate_whatsapp=False,
        status="completed",
        message="Busca concluída.",
    )
    db.add(run)
    db.flush()
    leads = [
        Lead(
            run_id=run.id,
            name=name,
            address="Av. Paulista, 1000 - São Paulo, SP",
            phone=f"(11) 99999-000{index}",
            website=None,
            email=f"lead{index}@example.test",
        )
        for index, name in enumerate(
            [
                "Lead Abriu",
                "Lead Clicou",
                "Lead Abriu e Clicou",
                "Lead Sem Engajamento",
                "Lead Outra Campanha",
                "Lead Sem Campanha",
            ],
            start=1,
        )
    ]
    db.add_all(leads)
    db.flush()
    return leads


def test_list_leads_filters_by_email_campaign_and_engagement(db_session: Session) -> None:
    leads = seed_leads(db_session)
    lead_list = LeadList(name="Lista e-mail", niche_filter="", location_filter="")
    template = EmailTemplate(name="Template", subject="Olá", html="<p>Olá</p>", text="Olá")
    db_session.add_all([lead_list, template])
    db_session.flush()
    campaign = EmailCampaign(name="Campanha Agosto", list_id=lead_list.id, status="completed")
    other_campaign = EmailCampaign(name="Campanha Julho", list_id=lead_list.id, status="completed")
    db_session.add_all([campaign, other_campaign])
    db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            EmailSend(
                campaign_id=campaign.id,
                lead_id=leads[0].id,
                template_id=template.id,
                recipient_email=leads[0].email,
                subject="Olá",
                status="sent",
                open_count=1,
                opened_at=now,
            ),
            EmailSend(
                campaign_id=campaign.id,
                lead_id=leads[1].id,
                template_id=template.id,
                recipient_email=leads[1].email,
                subject="Olá",
                status="sent",
                click_count=1,
                clicked_at=now,
            ),
            EmailSend(
                campaign_id=campaign.id,
                lead_id=leads[2].id,
                template_id=template.id,
                recipient_email=leads[2].email,
                subject="Olá",
                status="sent",
                open_count=1,
                click_count=1,
                opened_at=now,
                clicked_at=now,
            ),
            EmailSend(
                campaign_id=campaign.id,
                lead_id=leads[3].id,
                template_id=template.id,
                recipient_email=leads[3].email,
                subject="Olá",
                status="sent",
            ),
            EmailSend(
                campaign_id=other_campaign.id,
                lead_id=leads[4].id,
                template_id=template.id,
                recipient_email=leads[4].email,
                subject="Olá",
                status="sent",
                open_count=1,
                click_count=1,
                opened_at=now,
                clicked_at=now,
            ),
        ]
    )
    db_session.commit()

    campaign_leads = main.list_leads(email_campaign_id=campaign.id, db=db_session, username="test-user")
    opened_leads = main.list_leads(
        email_campaign_id=campaign.id,
        email_opened=True,
        db=db_session,
        username="test-user",
    )
    clicked_any_campaign = main.list_leads(email_clicked=True, db=db_session, username="test-user")
    opened_or_clicked = main.list_leads(
        email_campaign_id=campaign.id,
        email_opened=True,
        email_clicked=True,
        db=db_session,
        username="test-user",
    )

    assert sorted(lead.name for lead in campaign_leads) == [
        "Lead Abriu",
        "Lead Abriu e Clicou",
        "Lead Clicou",
        "Lead Sem Engajamento",
    ]
    assert sorted(lead.name for lead in opened_leads) == ["Lead Abriu", "Lead Abriu e Clicou"]
    assert sorted(lead.name for lead in clicked_any_campaign) == [
        "Lead Abriu e Clicou",
        "Lead Clicou",
        "Lead Outra Campanha",
    ]
    assert sorted(lead.name for lead in opened_or_clicked) == [
        "Lead Abriu",
        "Lead Abriu e Clicou",
        "Lead Clicou",
    ]


def test_list_leads_filters_by_whatsapp_campaign_and_replies(db_session: Session) -> None:
    leads = seed_leads(db_session)
    lead_list = LeadList(name="Lista WhatsApp", niche_filter="", location_filter="")
    instance = WhatsAppInstance(
        name="Instância principal",
        provider="evolution",
        status="connected",
        evolution_instance_name="instancia-principal",
    )
    db_session.add_all([lead_list, instance])
    db_session.flush()
    campaign = WhatsAppCampaign(
        name="Campanha WhatsApp Agosto",
        list_id=lead_list.id,
        instance_id=instance.id,
        status="completed",
    )
    other_campaign = WhatsAppCampaign(
        name="Campanha WhatsApp Julho",
        list_id=lead_list.id,
        instance_id=instance.id,
        status="completed",
    )
    db_session.add_all([campaign, other_campaign])
    db_session.flush()
    db_session.add_all(
        [
            WhatsAppSend(
                campaign_id=campaign.id,
                lead_id=leads[0].id,
                recipient_phone=leads[0].phone or "",
                status="sent",
            ),
            WhatsAppSend(
                campaign_id=campaign.id,
                lead_id=leads[1].id,
                recipient_phone=leads[1].phone or "",
                status="sent",
            ),
            WhatsAppSend(
                campaign_id=other_campaign.id,
                lead_id=leads[4].id,
                recipient_phone=leads[4].phone or "",
                status="sent",
            ),
        ]
    )
    db_session.flush()
    replied_conversation = WhatsAppConversation(
        lead_id=leads[0].id,
        instance_id=instance.id,
        status="open",
        last_message_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    other_replied_conversation = WhatsAppConversation(
        lead_id=leads[4].id,
        instance_id=instance.id,
        status="open",
        last_message_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )
    no_campaign_conversation = WhatsAppConversation(
        lead_id=leads[5].id,
        instance_id=instance.id,
        status="open",
        last_message_at=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add_all([replied_conversation, other_replied_conversation, no_campaign_conversation])
    db_session.flush()
    db_session.add_all(
        [
            WhatsAppMessage(
                conversation_id=replied_conversation.id,
                direction="inbound",
                content="Tenho interesse",
                message_type="text",
            ),
            WhatsAppMessage(
                conversation_id=other_replied_conversation.id,
                direction="inbound",
                content="Pode mandar mais informações",
                message_type="text",
            ),
            WhatsAppMessage(
                conversation_id=no_campaign_conversation.id,
                direction="inbound",
                content="Mensagem avulsa",
                message_type="text",
            ),
        ]
    )
    db_session.commit()

    campaign_leads = main.list_leads(whatsapp_campaign_id=campaign.id, db=db_session, username="test-user")
    replied_any_campaign = main.list_leads(whatsapp_replied=True, db=db_session, username="test-user")
    replied_campaign_leads = main.list_leads(
        whatsapp_campaign_id=campaign.id,
        whatsapp_replied=True,
        db=db_session,
        username="test-user",
    )

    assert sorted(lead.name for lead in campaign_leads) == ["Lead Abriu", "Lead Clicou"]
    assert sorted(lead.name for lead in replied_any_campaign) == ["Lead Abriu", "Lead Outra Campanha"]
    assert [lead.name for lead in replied_campaign_leads] == ["Lead Abriu"]
