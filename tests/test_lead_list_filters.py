from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main
from backend.database import Base
from backend.models import Lead, SearchRun
from backend.schemas import LeadListCreate, LeadListUpdate
from backend.scrapers.email_scraper import EmailResult
from backend.scrapers.maps_scraper import MapLead
from backend.services import jobs, whatsapp_campaigns
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
