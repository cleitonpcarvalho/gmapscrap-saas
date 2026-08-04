from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main
from backend.database import Base
from backend.models import EmailCampaign, EmailSend, EmailTemplate, Lead, LeadList, SearchRun
from backend.schemas import LeadListCreate, LeadListUpdate, SearchCreate
from backend.scrapers.email_scraper import EmailResult
from backend.scrapers.maps_scraper import MapLead
from backend.services import email_campaigns, jobs, whatsapp_campaigns
from backend.services.whatsapp_validation import WhatsAppValidationResult


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


def seed_filter_leads(db: Session) -> None:
    run = SearchRun(
        niche="Marketing",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=True,
        status="completed",
        message="Busca concluída.",
    )
    db.add(run)
    db.flush()
    db.add_all(
        [
            Lead(
                run_id=run.id,
                name="Empresa Validada com Email",
                address="Av. Paulista, 1000 - São Paulo, SP",
                phone="(11) 99999-0000",
                website="https://validada.example",
                email="contato@validada.com.br",
                whatsapp_validated=True,
            ),
            Lead(
                run_id=run.id,
                name="Empresa Sem Validacao",
                address="Av. Paulista, 2000 - São Paulo, SP",
                phone="(11) 98888-0000",
                website="https://semvalidacao.example",
                email="contato@semvalidacao.com.br",
                whatsapp_validated=None,
            ),
            Lead(
                run_id=run.id,
                name="Empresa Validada sem Email",
                address="Av. Paulista, 3000 - São Paulo, SP",
                phone="(11) 97777-0000",
                website=None,
                email="",
                whatsapp_validated=True,
            ),
        ]
    )
    db.commit()


def seed_email_engagement_leads(db: Session) -> None:
    run = SearchRun(
        niche="Marketing",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=False,
        status="completed",
        message="Busca concluída.",
    )
    source_list = LeadList(name="Lista fonte", niche_filter="", location_filter="")
    template = EmailTemplate(
        name="Template engajamento",
        subject="Olá",
        html="<p>Olá</p>",
        text="Olá",
    )
    db.add_all([run, source_list, template])
    db.flush()
    campaign = EmailCampaign(name="Campanha anterior", list_id=source_list.id, status="completed")
    db.add(campaign)
    db.flush()

    leads = [
        Lead(
            run_id=run.id,
            name="Abriu Apenas",
            address="Av. Paulista, 1000 - São Paulo, SP",
            phone="",
            website="https://abriu.example",
            email="abriu@example.com",
        ),
        Lead(
            run_id=run.id,
            name="Clicou Apenas",
            address="Av. Paulista, 2000 - São Paulo, SP",
            phone="",
            website="https://clicou.example",
            email="clicou@example.com",
        ),
        Lead(
            run_id=run.id,
            name="Abriu e Clicou",
            address="Av. Paulista, 3000 - São Paulo, SP",
            phone="",
            website="https://ambos.example",
            email="ambos@example.com",
        ),
        Lead(
            run_id=run.id,
            name="Sem Engajamento",
            address="Av. Paulista, 4000 - São Paulo, SP",
            phone="",
            website="https://sem-engajamento.example",
            email="sem-engajamento@example.com",
        ),
    ]
    db.add_all(leads)
    db.flush()
    now = datetime.now(timezone.utc)
    db.add_all(
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
        ]
    )
    db.commit()


def test_lead_list_can_filter_only_whatsapp_validated_leads(db_session: Session) -> None:
    seed_filter_leads(db_session)

    lead_list = main.create_lead_list(
        LeadListCreate(
            name="WhatsApp validado",
            only_whatsapp_validated=True,
        ),
        db=db_session,
        username="test-user",
    )

    assert lead_list.only_whatsapp_validated is True
    assert lead_list.lead_count == 1

    whatsapp_leads = db_session.scalars(whatsapp_campaigns.lead_query_for_list(lead_list)).all()
    assert [lead.name for lead in whatsapp_leads] == [
        "Empresa Validada com Email",
        "Empresa Validada sem Email",
    ]

    updated = main.update_lead_list(
        lead_list.id,
        LeadListUpdate(name="Todos os leads", only_whatsapp_validated=False),
        db=db_session,
        username="test-user",
    )
    assert updated.only_whatsapp_validated is False


def test_lead_list_filters_by_email_engagement_history(db_session: Session) -> None:
    seed_email_engagement_leads(db_session)

    opened_list = LeadList(
        name="Abriu",
        niche_filter="",
        location_filter="",
        only_email_opened=True,
        email_engagement_filter_mode="or",
    )
    clicked_list = LeadList(
        name="Clicou",
        niche_filter="",
        location_filter="",
        only_email_clicked=True,
        email_engagement_filter_mode="or",
    )
    engaged_or_list = LeadList(
        name="Abriu ou clicou",
        niche_filter="",
        location_filter="",
        only_email_opened=True,
        only_email_clicked=True,
        email_engagement_filter_mode="or",
    )
    engaged_and_list = LeadList(
        name="Abriu e clicou",
        niche_filter="",
        location_filter="",
        only_email_opened=True,
        only_email_clicked=True,
        email_engagement_filter_mode="and",
    )

    def names_for(lead_list: LeadList) -> list[str]:
        return sorted(lead.name for lead in db_session.scalars(email_campaigns.lead_query_for_list(lead_list)).all())

    assert names_for(opened_list) == ["Abriu Apenas", "Abriu e Clicou"]
    assert names_for(clicked_list) == ["Abriu e Clicou", "Clicou Apenas"]
    assert names_for(engaged_or_list) == ["Abriu Apenas", "Abriu e Clicou", "Clicou Apenas"]
    assert names_for(engaged_and_list) == ["Abriu e Clicou"]


def test_scraping_marks_saved_lead_as_whatsapp_validated(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SearchRun(
        niche="Marketing",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=False,
        validate_whatsapp=True,
        status="running",
        message="Validando WhatsApp.",
    )
    db_session.add(run)
    db_session.commit()

    monkeypatch.setattr(
        jobs,
        "validate_whatsapp_number",
        lambda phone, address="": WhatsAppValidationResult(
            phone=phone,
            normalized_phone="+5511999990000",
            status="valid",
        ),
    )

    saved = jobs.save_scraped_lead(
        db_session,
        run,
        MapLead(
            name="Empresa Validada",
            address="Av. Paulista, 1000 - São Paulo, SP",
            phone="(11) 99999-0000",
            website="",
        ),
    )

    assert saved is True
    lead = db_session.query(Lead).one()
    assert lead.whatsapp_validated is True


def test_search_create_only_without_website_disables_skip_without_website() -> None:
    payload = SearchCreate(
        niche="Marketing",
        location="São Paulo",
        quantity=10,
        skip_without_website=True,
        only_without_website=True,
    )

    assert payload.skip_without_website is False
    assert payload.only_without_website is True


def test_scraping_only_without_website_skips_lead_with_site(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SearchRun(
        niche="Marketing",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=False,
        only_without_website=True,
        validate_whatsapp=False,
        status="running",
        message="Buscando somente sem site.",
    )
    db_session.add(run)
    db_session.commit()

    def fail_extract_email(website: str) -> EmailResult:
        raise AssertionError(f"não deveria buscar e-mail para {website}")

    monkeypatch.setattr(jobs, "extract_email_from_site", fail_extract_email)

    saved = jobs.save_scraped_lead(
        db_session,
        run,
        MapLead(
            name="Empresa Com Site",
            address="Av. Paulista, 1000 - São Paulo, SP",
            phone="(11) 99999-0000",
            website="https://empresa.example",
        ),
    )

    assert saved is False
    assert db_session.query(Lead).count() == 0
    assert run.skipped_count == 1
    assert run.message == "Empresa Com Site ignorado: tem site."


def test_scraping_only_without_website_saves_lead_without_site(db_session: Session) -> None:
    run = SearchRun(
        niche="Marketing",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=False,
        only_without_website=True,
        validate_whatsapp=False,
        status="running",
        message="Buscando somente sem site.",
    )
    db_session.add(run)
    db_session.commit()

    saved = jobs.save_scraped_lead(
        db_session,
        run,
        MapLead(
            name="Empresa Sem Site",
            address="Av. Paulista, 1000 - São Paulo, SP",
            phone="(11) 99999-0000",
            website="",
        ),
    )

    assert saved is True
    lead = db_session.query(Lead).one()
    assert lead.name == "Empresa Sem Site"
    assert lead.website is None


def test_scraping_schedules_site_insights_when_enabled(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SearchRun(
        niche="Marketing",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=False,
        enrich_site_insights=True,
        status="running",
        message="Buscando.",
    )
    db_session.add(run)
    db_session.commit()
    scheduled: list[int] = []

    monkeypatch.setattr(jobs, "extract_email_from_site", lambda website: EmailResult(email="contato@example.com"))
    monkeypatch.setattr(jobs, "submit_site_insights_job", lambda lead_id: scheduled.append(lead_id))

    saved = jobs.save_scraped_lead(
        db_session,
        run,
        MapLead(
            name="Empresa Com Site",
            address="Av. Paulista, 1000 - São Paulo, SP",
            phone="(11) 99999-0000",
            website="https://empresa.example",
        ),
    )

    assert saved is True
    lead = db_session.query(Lead).one()
    assert scheduled == [lead.id]
    assert lead.site_insights is None


def test_site_insights_job_updates_lead_without_breaking_search(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = SearchRun(
        niche="Marketing",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=False,
        enrich_site_insights=True,
        status="running",
        message="Buscando.",
    )
    lead = Lead(
        search_run=run,
        name="Empresa Com Insight",
        address="Av. Paulista, 1000 - São Paulo, SP",
        phone="(11) 99999-0000",
        website="https://insight.example",
        email="contato@insight.example",
    )
    db_session.add(lead)
    db_session.commit()

    class NoCloseSessionProxy:
        def __getattr__(self, name: str):
            return getattr(db_session, name)

        def close(self) -> None:
            return None

    monkeypatch.setattr(jobs, "SessionLocal", NoCloseSessionProxy)
    monkeypatch.setattr(
        jobs,
        "extract_site_insights",
        lambda website, **kwargs: "Empresa atua em marketing e pode melhorar CTAs do site.",
    )

    jobs._run_site_insights_job(lead.id)

    db_session.refresh(lead)
    assert lead.site_insights == "Empresa atua em marketing e pode melhorar CTAs do site."


def test_retroactive_site_insights_endpoint_filters_brazil_whatsapp_and_missing_insights(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brazil_run = SearchRun(
        niche="Marketing",
        location="Fortaleza, CE",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=True,
        status="completed",
        message="Busca concluída.",
    )
    foreign_run = SearchRun(
        niche="Marketing",
        location="Miami, FL",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=True,
        status="completed",
        message="Busca concluída.",
    )
    db_session.add_all([brazil_run, foreign_run])
    db_session.flush()
    eligible = Lead(
        run_id=brazil_run.id,
        name="Empresa Elegível",
        address="Rua A, Fortaleza, CE",
        phone="(85) 99999-0000",
        website="https://elegivel.example",
        email="",
        whatsapp_validated=True,
    )
    db_session.add_all(
        [
            eligible,
            Lead(
                run_id=brazil_run.id,
                name="Empresa Sem WhatsApp",
                address="Rua B, Fortaleza, CE",
                phone="(85) 98888-0000",
                website="https://sem-whatsapp.example",
                email="",
                whatsapp_validated=None,
            ),
            Lead(
                run_id=brazil_run.id,
                name="Empresa Já Enriquecida",
                address="Rua C, Fortaleza, CE",
                phone="(85) 97777-0000",
                website="https://enriquecida.example",
                email="",
                whatsapp_validated=True,
                site_insights="Insight existente.",
            ),
            Lead(
                run_id=foreign_run.id,
                name="Empresa Fora do Brasil",
                address="100 Ocean Dr, Miami, FL",
                phone="+13055550000",
                website="https://miami.example",
                email="",
                whatsapp_validated=True,
            ),
            Lead(
                run_id=brazil_run.id,
                name="Empresa Sem Site",
                address="Rua D, Fortaleza, CE",
                phone="(85) 96666-0000",
                website=None,
                email="",
                whatsapp_validated=True,
            ),
        ]
    )
    db_session.commit()
    captured: dict[str, list[int]] = {}

    def fake_submit(lead_ids: list[int]) -> int:
        captured["lead_ids"] = lead_ids
        return len(lead_ids)

    monkeypatch.setattr(main, "submit_retroactive_site_insights_jobs", fake_submit)

    response = main.enrich_existing_leads_site_insights(db=db_session, username="test-user")

    assert response.status == "processing_started"
    assert response.eligible_count == 1
    assert response.queued_count == 1
    assert captured["lead_ids"] == [eligible.id]
    assert "SearchRun.location" in response.location_inference
