from collections.abc import Generator
import html
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main
from backend.database import Base
from backend.models import EmailCampaign, EmailCampaignTemplate, EmailSend, EmailTemplate, Lead, LeadList, SearchRun
from backend.schemas import EmailCampaignCreate
from backend.services import email_campaigns


class FakeOpenAiResponse:
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
    monkeypatch.setattr(email_campaigns, "SessionLocal", testing_session_local)
    monkeypatch.setattr(
        email_campaigns,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key="test-openai-key",
            openai_model="gpt-test",
            public_base_url="https://api.example.test",
            contact_email="cleiton@example.test",
        ),
    )
    monkeypatch.setattr(email_campaigns, "get_smtp_config", lambda db: SimpleNamespace(has_password=True))

    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()


def seed_email_campaign_records(db: Session) -> dict[str, int]:
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
    db.add(run)
    db.flush()

    lead = Lead(
        run_id=run.id,
        name="Empresa Alfa",
        address="Av. Paulista, 1000 - São Paulo, SP",
        phone="(11) 99577-9865",
        website="https://empresa-alfa.test",
        email="contato@empresa-alfa.test",
        site_insights="Site sem CTA claro e com poucas provas de confiança para quem chega pelo Google.",
    )
    lead_list = LeadList(name="Lista E-mail", niche_filter="", location_filter="")
    template = EmailTemplate(
        name="Template visual",
        subject="Conteúdo para {{company_name}}",
        html='<div style="background:{{background_color}};"><img src="{{logo_url}}" alt="Automa Soluct" />{{content_card_block}}</div>',
        text="Oi {{lead_name}}",
        content_title="Conteúdo base",
        content_link="",
        logo_url="https://assets.example.test/logo.png",
        primary_color="#008080",
        text_color="#222222",
        background_color="#f7fbfb",
    )
    db.add_all([lead, lead_list, template])
    db.commit()

    return {"lead_id": lead.id, "list_id": lead_list.id, "template_id": template.id, "run_id": run.id}


def test_email_campaign_endpoint_accepts_ai_mode_with_visual_template(db_session: Session) -> None:
    ids = seed_email_campaign_records(db_session)

    campaign = main.create_email_campaign(
        EmailCampaignCreate(
            name="Campanha IA e-mail",
            objective="vender sites para empresas sem site",
            message_mode="ai_per_lead",
            list_id=ids["list_id"],
            templates=[{"template_id": ids["template_id"], "weight": 1}],
            min_delay_seconds=1,
            max_delay_seconds=1,
        ),
        db=db_session,
        username="test-user",
    )

    assert campaign.status == "draft"
    assert campaign.message_mode == "ai_per_lead"
    assert campaign.objective == "vender sites para empresas sem site"
    assert campaign.template_ids == [ids["template_id"]]

    with pytest.raises(HTTPException) as exc_info:
        main.create_email_campaign(
            EmailCampaignCreate(
                name="Campanha sem objetivo",
                objective="",
                message_mode="ai_per_lead",
                list_id=ids["list_id"],
                templates=[{"template_id": ids["template_id"], "weight": 1}],
                min_delay_seconds=1,
                max_delay_seconds=1,
            ),
            db=db_session,
            username="test-user",
        )

    assert exc_info.value.status_code == 422
    assert "objetivo" in str(exc_info.value.detail).lower()


def test_email_campaign_runner_generates_ai_email_per_lead(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_email_campaign_records(db_session)
    campaign = EmailCampaign(
        name="Campanha IA e-mail",
        list_id=ids["list_id"],
        status="running",
        message_mode="ai_per_lead",
        objective="vender sites para empresas sem site, desenvolvimento gratuito, paga só se gostar",
        message="Campanha iniciada.",
        min_delay_seconds=1,
        max_delay_seconds=1,
        daily_limit=30,
        weekly_limit=150,
        send_window_start="00:00",
        send_window_end="23:59",
        timezone_name="America/Sao_Paulo",
        send_days="0,1,2,3,4,5,6",
    )
    db_session.add(campaign)
    db_session.flush()
    db_session.add(EmailCampaignTemplate(campaign_id=campaign.id, template_id=ids["template_id"], weight=1))
    db_session.commit()

    generated = {
        "subject": "Uma ideia para o site da Empresa Alfa",
        "content_title": "Um site mais claro para transformar visitas em conversas",
        "paragraphs": [
            "Vi que a Empresa Alfa atua com Marketing em São Paulo e que o site poderia deixar o próximo passo mais claro para quem chega pelo Google.",
            "Estou trabalhando com desenvolvimento sem custo inicial para empresas que querem testar uma presença digital melhor e só seguir se fizer sentido.",
        ],
        "cta": "Faz sentido eu te mostrar como isso poderia ficar para vocês?",
    }
    openai_payloads: list[dict[str, Any]] = []
    sent_payloads: list[dict[str, Any]] = []

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAiResponse:
        openai_payloads.append(kwargs["json"])
        return FakeOpenAiResponse(200, {"output_text": json.dumps(generated)})

    def fake_send_email(config: object, recipient: str, subject: str, html_body: str, text_body: str) -> None:
        sent_payloads.append(
            {
                "recipient": recipient,
                "subject": subject,
                "html": html_body,
                "text": text_body,
            }
        )

    monkeypatch.setattr(email_campaigns.requests, "post", fake_openai_post)
    monkeypatch.setattr(email_campaigns, "send_email", fake_send_email)
    monkeypatch.setattr(email_campaigns, "_sleep_with_pause_checks", lambda db, campaign_id, seconds: None)

    email_campaigns.run_campaign(campaign.id)

    db_session.expire_all()
    saved_campaign = db_session.get(EmailCampaign, campaign.id)
    send = db_session.scalars(select(EmailSend).where(EmailSend.campaign_id == campaign.id)).one()
    prompt = openai_payloads[0]["input"][1]["content"]
    saved_generated = json.loads(send.generated_content or "{}")

    assert saved_campaign is not None
    assert saved_campaign.status == "completed"
    assert saved_campaign.sent_count == 1
    assert send.status == "sent"
    assert send.subject == generated["subject"]
    assert saved_generated["content_title"] == generated["content_title"]
    assert "Site sem CTA claro" in prompt
    assert "desenvolvimento gratuito, paga só se gostar" in prompt
    assert sent_payloads[0]["recipient"] == "contato@empresa-alfa.test"
    assert sent_payloads[0]["subject"] == generated["subject"]
    assert "https://assets.example.test/logo.png" in sent_payloads[0]["html"]
    assert "#008080" in sent_payloads[0]["html"]
    assert generated["paragraphs"][0] in sent_payloads[0]["html"]
    assert generated["cta"] in sent_payloads[0]["text"]


@pytest.mark.parametrize(
    ("language", "expected_label", "expected_greeting"),
    [
        ("pt", "português do Brasil", "Oi, tudo bem?"),
        ("en", "inglês dos Estados Unidos", "Hi, how are you?"),
        ("es", "espanhol", "Hola, ¿cómo estás?"),
    ],
)
def test_ai_email_prompt_instructs_selected_language(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    expected_label: str,
    expected_greeting: str,
) -> None:
    ids = seed_email_campaign_records(db_session)
    campaign = EmailCampaign(
        name=f"Campanha IA ({language})",
        list_id=ids["list_id"],
        status="draft",
        message_mode="ai_per_lead",
        language=language,
        objective="vender sites para empresas sem site",
        message="Campanha criada.",
    )
    db_session.add(campaign)
    db_session.commit()
    lead = db_session.get(Lead, ids["lead_id"])
    assert lead is not None

    captured_payloads: list[dict[str, Any]] = []
    generated = {
        "subject": "Assunto",
        "content_title": "Título",
        "paragraphs": ["Parágrafo único."],
        "cta": "CTA",
    }

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAiResponse:
        captured_payloads.append(kwargs["json"])
        return FakeOpenAiResponse(200, {"output_text": json.dumps(generated)})

    monkeypatch.setattr(email_campaigns.requests, "post", fake_openai_post)

    email_campaigns.generate_ai_email_content_for_lead(campaign, lead)

    prompt = captured_payloads[0]["input"][1]["content"]
    assert f"inteiramente em {expected_label}" in prompt
    assert "Não escreva em português e traduza depois" in prompt

    template = EmailTemplate(
        name=f"Template {language}",
        subject="Assunto {{company_name}}",
        html="<div>{{content_card_block}}</div>",
        text="",
    )
    _, rendered_html, rendered_text = email_campaigns.render_generated_email(template, lead, campaign, generated)
    assert expected_greeting in rendered_html
    assert expected_greeting in rendered_text


@pytest.mark.parametrize(
    ("language", "expected_reply", "expected_contact_label", "expected_disclaimer"),
    [
        (
            "pt",
            "Responder",
            "Contato",
            "Este é um contato pontual da Automa Soluct para Empresa Alfa. Responda 'remover' se preferir não receber novas mensagens.",
        ),
        (
            "en",
            "Reply",
            "Contact",
            "This is a one-time message from Automa Soluct to Empresa Alfa. Reply 'remove' if you prefer not to receive future messages.",
        ),
        (
            "es",
            "Responder",
            "Contacto",
            "Este es un contacto puntual de Automa Soluct para Empresa Alfa. Responde 'eliminar' si prefieres no recibir más mensajes.",
        ),
    ],
)
def test_render_generated_email_localizes_fixed_footer(
    db_session: Session,
    language: str,
    expected_reply: str,
    expected_contact_label: str,
    expected_disclaimer: str,
) -> None:
    ids = seed_email_campaign_records(db_session)
    lead = db_session.get(Lead, ids["lead_id"])
    assert lead is not None
    campaign = EmailCampaign(
        name=f"Campanha IA rodape ({language})",
        list_id=ids["list_id"],
        status="draft",
        message_mode="ai_per_lead",
        language=language,
        objective="vender sites para empresas sem site",
        message="Campanha criada.",
    )
    generated = {
        "subject": "Subject line",
        "content_title": "Content title",
        "paragraphs": ["Paragraph one.", "Paragraph two."],
        "cta": "Call to action",
    }
    template = EmailTemplate(
        name=f"Template rodape {language}",
        subject="Assunto {{company_name}}",
        html="<div>{{content_card_block}}</div>",
        text="",
    )

    _, rendered_html, rendered_text = email_campaigns.render_generated_email(template, lead, campaign, generated)

    # Full render (subject already embedded via `generated["subject"]`, body and footer) is
    # checked entirely in the target language: reply button, "Contact" section label, and the
    # opt-out disclaimer, all interpolating the real lead/company name.
    assert f">{html.escape(expected_reply)}</a>" in rendered_html
    assert f">{html.escape(expected_contact_label)}</p>" in rendered_html
    assert html.escape(expected_disclaimer) in rendered_html
    assert f"{expected_reply}: cleiton@example.test" in rendered_text

    # The person's name/role and the brand name are proper nouns and stay fixed in every language.
    assert "Cleiton Carvalho" in rendered_html
    assert "Automation Specialist - Automa Soluct" in rendered_html
    assert "Automa Soluct" in rendered_text

    if language != "pt":
        # No Portuguese-only footer boilerplate should leak into an English/Spanish email.
        assert "Este é um contato pontual" not in rendered_html
        assert "Responda 'remover'" not in rendered_html
        assert ">Contato</p>" not in rendered_html


def test_email_campaign_runner_marks_ai_generation_failure_and_continues(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_email_campaign_records(db_session)
    first_lead = db_session.get(Lead, ids["lead_id"])
    assert first_lead is not None
    second_lead = Lead(
        run_id=ids["run_id"],
        name="Empresa Beta",
        address="Rua Augusta, 200 - São Paulo, SP",
        phone="(11) 91234-5678",
        website=None,
        email="contato@empresa-beta.test",
        site_insights=None,
    )
    campaign = EmailCampaign(
        name="Campanha IA com falha",
        list_id=ids["list_id"],
        status="running",
        message_mode="ai_per_lead",
        objective="vender sites para empresas sem site",
        message="Campanha iniciada.",
        min_delay_seconds=1,
        max_delay_seconds=1,
        daily_limit=30,
        weekly_limit=150,
        send_window_start="00:00",
        send_window_end="23:59",
        timezone_name="America/Sao_Paulo",
        send_days="0,1,2,3,4,5,6",
    )
    db_session.add_all([second_lead, campaign])
    db_session.flush()
    db_session.add(EmailCampaignTemplate(campaign_id=campaign.id, template_id=ids["template_id"], weight=1))
    db_session.commit()

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAiResponse:
        prompt = kwargs["json"]["input"][1]["content"]
        if "Empresa Alfa" in prompt:
            return FakeOpenAiResponse(500, {"error": "temporarily unavailable"}, text="temporarily unavailable")
        return FakeOpenAiResponse(
            200,
            {
                "output_text": json.dumps(
                    {
                        "subject": "Uma ideia para a Empresa Beta",
                        "content_title": "Presença digital para gerar mais conversas",
                        "paragraphs": ["Vi que vocês atuam com Marketing em São Paulo e queria compartilhar uma ideia simples."],
                        "cta": "Posso te explicar por e-mail?",
                    }
                )
            },
        )

    sent_payloads: list[dict[str, str]] = []

    def fake_send_email(config: object, recipient: str, subject: str, html_body: str, text_body: str) -> None:
        sent_payloads.append({"recipient": recipient, "subject": subject})

    monkeypatch.setattr(email_campaigns.requests, "post", fake_openai_post)
    monkeypatch.setattr(email_campaigns, "send_email", fake_send_email)
    monkeypatch.setattr(email_campaigns, "_sleep_with_pause_checks", lambda db, campaign_id, seconds: None)

    email_campaigns.run_campaign(campaign.id)

    db_session.expire_all()
    saved_campaign = db_session.get(EmailCampaign, campaign.id)
    sends = list(
        db_session.scalars(select(EmailSend).where(EmailSend.campaign_id == campaign.id).order_by(EmailSend.id)).all()
    )

    assert saved_campaign is not None
    assert saved_campaign.status == "completed"
    assert saved_campaign.sent_count == 1
    assert saved_campaign.failed_count == 1
    sends_by_lead_name = {send.lead.name: send for send in sends}
    assert sends_by_lead_name["Empresa Alfa"].status == "failed"
    assert sends_by_lead_name["Empresa Alfa"].generated_content is None
    assert "OpenAI retornou erro 500" in (sends_by_lead_name["Empresa Alfa"].error or "")
    assert sends_by_lead_name["Empresa Beta"].status == "sent"
    assert "Presença digital" in (sends_by_lead_name["Empresa Beta"].generated_content or "")
    assert sent_payloads == [{"recipient": "contato@empresa-beta.test", "subject": "Uma ideia para a Empresa Beta"}]
