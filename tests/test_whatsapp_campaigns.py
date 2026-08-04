from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main
from backend.database import Base
from backend.models import (
    Lead,
    LeadList,
    SearchRun,
    WhatsAppAiSettings,
    WhatsAppCampaign,
    WhatsAppCampaignTemplate,
    WhatsAppInstance,
    WhatsAppMessageTemplate,
    WhatsAppSend,
)
from backend.schemas import (
    WhatsAppCampaignCreate,
    WhatsAppCampaignUpdate,
    WhatsAppMessageTemplateCreate,
    WhatsAppMessageTemplateUpdate,
    WhatsAppTemplateGenerateRequest,
)
from backend.services import whatsapp_campaigns


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
    monkeypatch.setattr(whatsapp_campaigns, "SessionLocal", testing_session_local)
    monkeypatch.setattr(
        "backend.services.whatsapp_providers.evolution.get_settings",
        lambda: SimpleNamespace(
            evolution_api_base_url="https://evolution.example.test",
            evolution_api_key="test-api-key",
            whatsapp_validation_timeout_seconds=5,
        ),
    )
    monkeypatch.setattr(
        "backend.services.ai_templates.get_settings",
        lambda: SimpleNamespace(openai_api_key="test-openai-key", openai_model="gpt-test"),
    )
    monkeypatch.setattr(
        whatsapp_campaigns,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-openai-key", openai_model="gpt-test"),
    )

    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()


def seed_campaign_records(db: Session) -> dict[str, int]:
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
        website=None,
        email="",
    )
    lead_list = LeadList(name="Lista WhatsApp", niche_filter="", location_filter="")
    instance = WhatsAppInstance(
        name="sales-main",
        provider="evolution",
        status="connected",
        evolution_instance_name="sales-main",
    )
    template = WhatsAppMessageTemplate(name="Primeiro contato", content="Oi {nome_empresa}, tudo bem?")
    db.add_all([lead, lead_list, instance, template])
    db.commit()

    return {
        "lead_id": lead.id,
        "list_id": lead_list.id,
        "instance_id": instance.id,
        "template_id": template.id,
    }


def test_whatsapp_campaign_endpoint_lifecycle(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_campaign_records(db_session)
    submitted: list[int] = []
    monkeypatch.setattr(main, "submit_whatsapp_campaign_job", lambda campaign_id: submitted.append(campaign_id) or True)

    campaign = main.create_whatsapp_campaign(
        WhatsAppCampaignCreate(
            name="Campanha WhatsApp",
            objective="Vender criação de site grátis, paga só se gostar.",
            list_id=ids["list_id"],
            instance_id=ids["instance_id"],
            templates=[{"template_id": ids["template_id"], "weight": 1}],
            min_delay_seconds=1,
            max_delay_seconds=1,
        ),
        db=db_session,
        username="test-user",
    )

    assert campaign.status == "draft"
    assert campaign.message_mode == "template"
    assert campaign.objective == "Vender criação de site grátis, paga só se gostar."
    assert campaign.template_ids == [ids["template_id"]]
    assert [item.id for item in main.list_whatsapp_campaigns(db=db_session, username="test-user")] == [campaign.id]

    started = main.start_whatsapp_campaign(campaign.id, db=db_session, username="test-user")
    assert started.status == "running"
    assert submitted == [campaign.id]

    paused = main.pause_whatsapp_campaign(campaign.id, db=db_session, username="test-user")
    assert paused.status == "paused"

    deleted = main.delete_whatsapp_campaign(campaign.id, db=db_session, username="test-user")
    assert deleted == {"status": "ok"}
    assert main.list_whatsapp_campaigns(db=db_session, username="test-user") == []


def test_update_whatsapp_campaign_can_change_template_before_sends_exist(db_session: Session) -> None:
    ids = seed_campaign_records(db_session)
    second_template = WhatsAppMessageTemplate(name="Segundo contato", content="Olá {nome_empresa}, tudo certo?")
    db_session.add(second_template)
    db_session.commit()

    campaign = main.create_whatsapp_campaign(
        WhatsAppCampaignCreate(
            name="Campanha WhatsApp",
            objective="Vender criação de site grátis, paga só se gostar.",
            list_id=ids["list_id"],
            instance_id=ids["instance_id"],
            templates=[{"template_id": ids["template_id"], "weight": 1}],
            min_delay_seconds=1,
            max_delay_seconds=1,
        ),
        db=db_session,
        username="test-user",
    )
    assert campaign.template_ids == [ids["template_id"]]

    updated = main.update_whatsapp_campaign(
        campaign.id,
        WhatsAppCampaignUpdate(
            name="Campanha WhatsApp",
            objective="Vender criação de site grátis, paga só se gostar.",
            list_id=ids["list_id"],
            instance_id=ids["instance_id"],
            templates=[{"template_id": second_template.id, "weight": 1}],
            min_delay_seconds=1,
            max_delay_seconds=1,
        ),
        db=db_session,
        username="test-user",
    )

    assert updated.template_ids == [second_template.id]
    assert updated.message == "Campanha atualizada."


def test_update_whatsapp_campaign_blocks_template_change_once_sends_exist(db_session: Session) -> None:
    ids = seed_campaign_records(db_session)
    second_template = WhatsAppMessageTemplate(name="Segundo contato", content="Olá {nome_empresa}, tudo certo?")
    db_session.add(second_template)
    db_session.commit()

    campaign = main.create_whatsapp_campaign(
        WhatsAppCampaignCreate(
            name="Campanha WhatsApp",
            objective="Vender criação de site grátis, paga só se gostar.",
            list_id=ids["list_id"],
            instance_id=ids["instance_id"],
            templates=[{"template_id": ids["template_id"], "weight": 1}],
            min_delay_seconds=1,
            max_delay_seconds=1,
        ),
        db=db_session,
        username="test-user",
    )
    db_session.add(
        WhatsAppSend(
            campaign_id=campaign.id,
            lead_id=ids["lead_id"],
            template_id=ids["template_id"],
            recipient_phone="5511995779865",
            status="pending",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        main.update_whatsapp_campaign(
            campaign.id,
            WhatsAppCampaignUpdate(
                name="Campanha WhatsApp",
                objective="Vender criação de site grátis, paga só se gostar.",
                list_id=ids["list_id"],
                instance_id=ids["instance_id"],
                templates=[{"template_id": second_template.id, "weight": 1}],
                min_delay_seconds=1,
                max_delay_seconds=1,
            ),
            db=db_session,
            username="test-user",
        )

    assert exc_info.value.status_code == 409

    # A field unrelated to audience (e.g. daily_limit) can still be edited once sends exist.
    updated = main.update_whatsapp_campaign(
        campaign.id,
        WhatsAppCampaignUpdate(
            name="Campanha WhatsApp",
            objective="Vender criação de site grátis, paga só se gostar.",
            list_id=ids["list_id"],
            instance_id=ids["instance_id"],
            templates=[{"template_id": ids["template_id"], "weight": 1}],
            daily_limit=5,
            min_delay_seconds=1,
            max_delay_seconds=1,
        ),
        db=db_session,
        username="test-user",
    )
    assert updated.daily_limit == 5
    assert updated.template_ids == [ids["template_id"]]


def test_whatsapp_ai_per_lead_campaign_can_be_created_without_template(db_session: Session) -> None:
    ids = seed_campaign_records(db_session)

    campaign = main.create_whatsapp_campaign(
        WhatsAppCampaignCreate(
            name="Campanha IA por lead",
            objective="vender sites para empresas sem site, desenvolvimento gratuito, paga só se gostar",
            message_mode="ai_per_lead",
            list_id=ids["list_id"],
            instance_id=ids["instance_id"],
            templates=[],
            min_delay_seconds=1,
            max_delay_seconds=1,
        ),
        db=db_session,
        username="test-user",
    )

    assert campaign.status == "draft"
    assert campaign.message_mode == "ai_per_lead"
    assert campaign.template_ids == []


def test_whatsapp_template_crud_endpoints(db_session: Session) -> None:
    created = main.create_whatsapp_template(
        WhatsAppMessageTemplateCreate(name="Boas-vindas", content="Oi {nome_empresa}, tudo bem?"),
        db=db_session,
        username="test-user",
    )

    listed = main.list_whatsapp_templates(db=db_session, username="test-user")
    assert [(template.id, template.name, template.content) for template in listed] == [
        (created.id, "Boas-vindas", "Oi {nome_empresa}, tudo bem?")
    ]

    updated = main.update_whatsapp_template(
        created.id,
        WhatsAppMessageTemplateUpdate(content="Olá {lead_name}, posso te ajudar?"),
        db=db_session,
        username="test-user",
    )
    assert updated.content == "Olá {lead_name}, posso te ajudar?"

    deleted = main.delete_whatsapp_template(created.id, db=db_session, username="test-user")
    assert deleted == {"status": "ok"}
    assert main.list_whatsapp_templates(db=db_session, username="test-user") == []


def test_whatsapp_template_generate_endpoint_uses_openai(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeEvolutionResponse:
        captured["payload"] = kwargs["json"]
        return FakeEvolutionResponse(
            200,
            {
                "output_text": (
                    '{"content":"Oi, tudo bem? Vi que a {nome_empresa} atua com {niche} em {location} e muitas empresas parecidas ainda perdem contatos por não terem um site claro. Estou oferecendo uma condição especial este mês: desenvolvimento sem custo inicial, e você só segue se gostar do resultado. Faz sentido eu te explicar rapidinho?"}'
                )
            },
        )

    monkeypatch.setattr("backend.services.ai_templates.requests.post", fake_openai_post)

    response = main.generate_ai_whatsapp_template(
        WhatsAppTemplateGenerateRequest(objective="vender criação de site grátis, paga só se gostar"),
        username="test-user",
    )

    assert response.content == (
        "Oi, tudo bem? Vi que a {nome_empresa} atua com {niche} em {location} e muitas empresas parecidas ainda perdem contatos por não terem um site claro. "
        "Estou oferecendo uma condição especial este mês: desenvolvimento sem custo inicial, e você só segue se gostar do resultado. "
        "Faz sentido eu te explicar rapidinho?"
    )
    assert captured["payload"]["model"] == "gpt-test"
    assert captured["payload"]["text"]["format"]["name"] == "whatsapp_template_generation"
    assert "Comece obrigatoriamente com uma saudação breve" in captured["payload"]["input"][1]["content"]
    assert "Não omita a oferta ou gancho específico" in captured["payload"]["input"][1]["content"]
    assert "Nunca repita a categoria do negócio duas vezes seguidas" in captured["payload"]["input"][1]["content"]
    assert "estava pesquisando no Google sobre" in captured["payload"]["input"][1]["content"]
    assert "desenvolvimento sem custo inicial" in captured["payload"]["input"][1]["content"]
    assert "sem fechar detalhes" in captured["payload"]["input"][1]["content"]
    assert "Não use {lead_name}" in captured["payload"]["input"][1]["content"]
    assert 'Evite aberturas como "Oi, {nome_empresa}!"' in captured["payload"]["input"][1]["content"]


def test_whatsapp_campaign_runner_sends_pending_messages(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_campaign_records(db_session)
    campaign = WhatsAppCampaign(
        name="Campanha WhatsApp",
        list_id=ids["list_id"],
        instance_id=ids["instance_id"],
        status="running",
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
    db_session.add(
        WhatsAppCampaignTemplate(campaign_id=campaign.id, template_id=ids["template_id"], weight=1)
    )
    db_session.commit()

    sent_payloads: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        sent_payloads.append({"method": method, "url": url, "json": kwargs["json"]})
        return FakeEvolutionResponse(200, {"key": {"id": "message-1"}, "status": "PENDING"})

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)
    monkeypatch.setattr(whatsapp_campaigns, "_sleep_with_pause_checks", lambda db, campaign_id, seconds: None)

    whatsapp_campaigns.run_campaign(campaign.id)

    db_session.expire_all()
    saved_campaign = db_session.get(WhatsAppCampaign, campaign.id)
    send = db_session.scalars(select(WhatsAppSend).where(WhatsAppSend.campaign_id == campaign.id)).one()

    assert saved_campaign is not None
    assert saved_campaign.status == "completed"
    assert saved_campaign.pending_count == 0
    assert saved_campaign.sent_count == 1
    assert send.status == "sent"
    assert send.recipient_phone == "5511995779865"
    assert send.provider_message_id == "message-1"
    assert send.sent_at is not None
    assert sent_payloads == [
        {
            "method": "POST",
            "url": "https://evolution.example.test/message/sendText/sales-main",
            "json": {
                "number": "5511995779865",
                "text": "Oi Empresa Alfa, tudo bem?",
            },
        }
    ]


def test_whatsapp_campaign_restart_after_pause_does_not_resend_already_sent_leads(
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
        status="completed",
        message="Busca concluída.",
    )
    db_session.add(run)
    db_session.flush()
    leads = [
        Lead(
            run_id=run.id,
            name=f"Empresa {index}",
            address="Av. Paulista, 1000 - São Paulo, SP",
            phone=f"(11) 9999{index}-000{index}",
            website=None,
            email="",
        )
        for index in range(1, 4)
    ]
    lead_list = LeadList(name="Lista WhatsApp pausa", niche_filter="", location_filter="")
    instance = WhatsAppInstance(
        name="sales-restart",
        provider="evolution",
        status="connected",
        evolution_instance_name="sales-restart",
    )
    template = WhatsAppMessageTemplate(name="Primeiro contato", content="Oi {nome_empresa}, tudo bem?")
    db_session.add_all([*leads, lead_list, instance, template])
    db_session.commit()

    campaign = WhatsAppCampaign(
        name="Campanha pausa e retomada",
        list_id=lead_list.id,
        instance_id=instance.id,
        status="running",
        message_mode="template",
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
    db_session.add(WhatsAppCampaignTemplate(campaign_id=campaign.id, template_id=template.id, weight=1))
    db_session.commit()

    sent_payloads: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        sent_payloads.append({"method": method, "url": url, "json": kwargs["json"]})
        return FakeEvolutionResponse(200, {"key": {"id": f"message-{len(sent_payloads)}"}, "status": "PENDING"})

    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_request)

    # Simulate a real "pause" clicked by the user right after the first message goes out:
    # the campaign status flips to "paused" during the post-send delay, causing the
    # in-progress run_campaign loop to stop (same code path _sleep_with_pause_checks
    # normally uses to detect a pause between sends).
    def fake_pause_after_first_send(db: Session, campaign_id: int, seconds: int) -> None:
        paused = db.get(WhatsAppCampaign, campaign_id)
        assert paused is not None
        paused.status = "paused"
        paused.message = "Campanha pausada."
        db.commit()

    monkeypatch.setattr(whatsapp_campaigns, "_sleep_with_pause_checks", fake_pause_after_first_send)

    whatsapp_campaigns.run_campaign(campaign.id)

    db_session.expire_all()
    paused_campaign = db_session.get(WhatsAppCampaign, campaign.id)
    assert paused_campaign is not None
    assert paused_campaign.status == "paused"
    sends_after_first_run = list(
        db_session.scalars(select(WhatsAppSend).where(WhatsAppSend.campaign_id == campaign.id)).all()
    )
    assert len(sends_after_first_run) == 3
    sent_after_first_run = [send for send in sends_after_first_run if send.status == "sent"]
    pending_after_first_run = [send for send in sends_after_first_run if send.status == "pending"]
    assert len(sent_after_first_run) == 1
    assert len(pending_after_first_run) == 2
    assert len(sent_payloads) == 1
    already_sent_recipient = sent_after_first_run[0].recipient_phone

    # Restart: flip the campaign back to "running" (what the /start endpoint does) and let
    # it run to completion this time.
    monkeypatch.setattr(whatsapp_campaigns, "_sleep_with_pause_checks", lambda db, campaign_id, seconds: None)
    paused_campaign.status = "running"
    db_session.commit()

    whatsapp_campaigns.run_campaign(campaign.id)

    db_session.expire_all()
    final_campaign = db_session.get(WhatsAppCampaign, campaign.id)
    final_sends = list(db_session.scalars(select(WhatsAppSend).where(WhatsAppSend.campaign_id == campaign.id)).all())

    assert final_campaign is not None
    assert final_campaign.status == "completed"
    assert len(final_sends) == 3
    assert all(send.status == "sent" for send in final_sends)

    # No duplicate: still exactly 3 provider calls total (one per lead), and the lead sent
    # before the pause was never called again after the restart.
    assert len(sent_payloads) == 3
    recipients_called = [payload["json"]["number"] for payload in sent_payloads]
    assert recipients_called.count(already_sent_recipient) == 1
    assert len(set(recipients_called)) == 3


def test_whatsapp_campaign_runner_generates_ai_message_per_lead(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_campaign_records(db_session)
    lead = db_session.get(Lead, ids["lead_id"])
    assert lead is not None
    lead.website = "https://empresa-alfa.test"
    lead.site_insights = "Site sem CTA claro e com poucas provas de confiança para quem chega pelo Google."
    db_session.add(
        WhatsAppAiSettings(
            id=1,
            system_prompt="",
            services_description="Criamos sites rápidos para empresas locais venderem melhor sem depender de trabalho manual.",
            enabled=False,
        )
    )
    campaign = WhatsAppCampaign(
        name="Campanha IA por lead",
        list_id=ids["list_id"],
        instance_id=ids["instance_id"],
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
    db_session.commit()

    generated_message = (
        "Oi, tudo bem? Vi que a Empresa Alfa atua com Marketing em São Paulo e que o site poderia ter um CTA mais claro para quem chega pelo Google. "
        "Estou trabalhando com uma condição de desenvolvimento sem custo inicial, e vocês só seguem se gostarem do resultado. "
        "Posso te explicar rapidinho?"
    )
    openai_payloads: list[dict[str, Any]] = []
    sent_payloads: list[dict[str, Any]] = []

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeEvolutionResponse:
        openai_payloads.append(kwargs["json"])
        return FakeEvolutionResponse(200, {"output_text": f'{{"content":"{generated_message}"}}'})

    def fake_evolution_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        sent_payloads.append({"method": method, "url": url, "json": kwargs["json"]})
        return FakeEvolutionResponse(200, {"key": {"id": "message-ai-1"}, "status": "PENDING"})

    monkeypatch.setattr(whatsapp_campaigns.requests, "post", fake_openai_post)
    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_evolution_request)
    monkeypatch.setattr(whatsapp_campaigns, "_sleep_with_pause_checks", lambda db, campaign_id, seconds: None)

    whatsapp_campaigns.run_campaign(campaign.id)

    db_session.expire_all()
    saved_campaign = db_session.get(WhatsAppCampaign, campaign.id)
    send = db_session.scalars(select(WhatsAppSend).where(WhatsAppSend.campaign_id == campaign.id)).one()
    prompt = openai_payloads[0]["input"][1]["content"]

    assert saved_campaign is not None
    assert saved_campaign.status == "completed"
    assert saved_campaign.sent_count == 1
    assert send.status == "sent"
    assert send.template_id is None
    assert send.generated_content == generated_message
    assert send.provider_message_id == "message-ai-1"
    assert "desenvolvimento gratuito, paga só se gostar" in prompt
    assert "Site sem CTA claro" in prompt
    assert "Criamos sites rápidos" in prompt
    assert "Nunca repita a categoria do negócio duas vezes seguidas" in prompt
    assert "estava pesquisando no Google sobre" in prompt
    assert sent_payloads == [
        {
            "method": "POST",
            "url": "https://evolution.example.test/message/sendText/sales-main",
            "json": {
                "number": "5511995779865",
                "text": generated_message,
            },
        }
    ]


@pytest.mark.parametrize(
    ("language", "expected_label", "expected_greeting"),
    [
        ("pt", "português do Brasil", "Oi, tudo bem?"),
        ("en", "inglês dos Estados Unidos", "Hi, how are you?"),
        ("es", "espanhol", "Hola, ¿cómo estás?"),
    ],
)
def test_ai_whatsapp_prompt_instructs_selected_language(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    expected_label: str,
    expected_greeting: str,
) -> None:
    ids = seed_campaign_records(db_session)
    lead = db_session.get(Lead, ids["lead_id"])
    assert lead is not None
    campaign = WhatsAppCampaign(
        name=f"Campanha IA ({language})",
        list_id=ids["list_id"],
        instance_id=ids["instance_id"],
        status="draft",
        message_mode="ai_per_lead",
        language=language,
        objective="vender sites para empresas sem site",
        message="Campanha criada.",
    )
    db_session.add(campaign)
    db_session.commit()

    captured_payloads: list[dict[str, Any]] = []

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeEvolutionResponse:
        captured_payloads.append(kwargs["json"])
        return FakeEvolutionResponse(200, {"output_text": '{"content":"mensagem gerada"}'})

    monkeypatch.setattr(whatsapp_campaigns.requests, "post", fake_openai_post)

    whatsapp_campaigns.generate_ai_message_for_lead(db_session, campaign, lead)

    prompt = captured_payloads[0]["input"][1]["content"]
    assert f"Escreva a mensagem inteira em {expected_label}" in prompt
    assert f'como "{expected_greeting}"' in prompt
    assert "Não escreva em português e traduza depois" in prompt


def test_whatsapp_campaign_runner_marks_ai_generation_failure_and_continues(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_campaign_records(db_session)
    first_lead = db_session.get(Lead, ids["lead_id"])
    assert first_lead is not None
    run_id = first_lead.run_id
    second_lead = Lead(
        run_id=run_id,
        name="Empresa Beta",
        address="Rua Augusta, 200 - São Paulo, SP",
        phone="(11) 91234-5678",
        website=None,
        email="",
    )
    db_session.add(second_lead)
    campaign = WhatsAppCampaign(
        name="Campanha IA com falha",
        list_id=ids["list_id"],
        instance_id=ids["instance_id"],
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
    db_session.add(campaign)
    db_session.commit()

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeEvolutionResponse:
        prompt = kwargs["json"]["input"][1]["content"]
        if "Empresa Alfa" in prompt:
            return FakeEvolutionResponse(500, {"error": "temporarily unavailable"}, text="temporarily unavailable")
        return FakeEvolutionResponse(
            200,
            {"output_text": '{"content":"Oi, tudo bem? Vi que a Empresa Beta atua com Marketing em São Paulo. Posso te explicar uma condição especial para criar um site?"}'},
        )

    sent_payloads: list[dict[str, Any]] = []

    def fake_evolution_request(method: str, url: str, **kwargs) -> FakeEvolutionResponse:
        sent_payloads.append({"method": method, "url": url, "json": kwargs["json"]})
        return FakeEvolutionResponse(200, {"key": {"id": "message-ai-2"}, "status": "PENDING"})

    monkeypatch.setattr(whatsapp_campaigns.requests, "post", fake_openai_post)
    monkeypatch.setattr("backend.services.whatsapp_providers.evolution.requests.request", fake_evolution_request)
    monkeypatch.setattr(whatsapp_campaigns, "_sleep_with_pause_checks", lambda db, campaign_id, seconds: None)

    whatsapp_campaigns.run_campaign(campaign.id)

    db_session.expire_all()
    saved_campaign = db_session.get(WhatsAppCampaign, campaign.id)
    sends = list(
        db_session.scalars(select(WhatsAppSend).where(WhatsAppSend.campaign_id == campaign.id).order_by(WhatsAppSend.id)).all()
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
    assert (
        sends_by_lead_name["Empresa Beta"].generated_content
        == "Oi, tudo bem? Vi que a Empresa Beta atua com Marketing em São Paulo. Posso te explicar uma condição especial para criar um site?"
    )
    assert len(sent_payloads) == 1
