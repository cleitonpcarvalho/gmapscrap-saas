from __future__ import annotations

import json
import logging
from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from backend import main
from backend.database import Base
from backend.models import (
    CrmLead,
    CrmStageHistory,
    Lead,
    LeadTag,
    SearchRun,
    Tag,
    WhatsAppAiSettings,
    WhatsAppConversation,
    WhatsAppInstance,
    WhatsAppMessage,
    WhatsAppPortfolioItem,
)
from backend.schemas import WhatsAppPortfolioItemCreate
from backend.services import whatsapp_ai_agent


WEBHOOK_SECRET = "test-webhook-secret"


class FakeOpenAIResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

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

    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(evolution_webhook_secret=WEBHOOK_SECRET))
    monkeypatch.setattr(
        whatsapp_ai_agent,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-openai-key", openai_model="gpt-test"),
    )
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


def seed_lead_and_instance(db: Session, *, phone: str = "(11) 99999-0000") -> dict[str, int]:
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

    lead = Lead(
        run_id=run.id,
        name="Empresa Alfa",
        address="Av. Paulista, 1000 - São Paulo, SP",
        phone=phone,
        website=None,
        email="",
    )
    instance = WhatsAppInstance(
        name="sales-main",
        provider="evolution",
        status="connected",
        evolution_instance_name="sales-main",
    )
    db.add_all([lead, instance])
    db.commit()
    return {"lead_id": lead.id, "instance_id": instance.id}


def enable_ai(
    db: Session,
    *,
    system_prompt: str = "Atenda leads de forma breve.",
    services_description: str = "",
    auto_apply_tags_enabled: bool = False,
) -> None:
    db.add(
        WhatsAppAiSettings(
            id=1,
            system_prompt=system_prompt,
            services_description=services_description,
            enabled=True,
            auto_apply_tags_enabled=auto_apply_tags_enabled,
        )
    )
    db.commit()


def webhook_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/whatsapp/webhook/evolution",
            "headers": [(b"x-evolution-webhook-secret", WEBHOOK_SECRET.encode())],
        }
    )


def evolution_text_payload(
    *,
    message_id: str = "INBOUND_1",
    text: str = "Tenho interesse em automatizar meu atendimento.",
) -> dict[str, Any]:
    return {
        "event": "MESSAGES_UPSERT",
        "instance": "sales-main",
        "data": {
            "key": {
                "remoteJid": "5511999990000@s.whatsapp.net",
                "fromMe": False,
                "id": message_id,
            },
            "pushName": "John Doe",
            "message": {
                "conversation": text,
            },
            "messageType": "conversation",
            "messageTimestamp": 1709553296,
        },
        "sender": "5511999990000@s.whatsapp.net",
    }


def test_whatsapp_ai_generates_and_sends_reply(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_lead_and_instance(db_session)
    db_session.add(
        WhatsAppPortfolioItem(
            description="Site para clínica odontológica com agendamento",
            url="https://portfolio.example/clinica",
        )
    )
    db_session.commit()
    enable_ai(
        db_session,
        services_description="Automatizamos atendimento para clínicas e operações locais.",
    )
    captured: dict[str, Any] = {}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["openai_payload"] = kwargs["json"]
        return FakeOpenAIResponse({"output_text": "Claro! Posso te ajudar com isso por aqui."})

    def fake_send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        captured["send"] = {"instance_id": instance_id, "phone": phone, "text": text}
        return {"key": {"id": "OUTBOUND_AI_1"}}

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(whatsapp_ai_agent.EvolutionProvider, "send_text_message", fake_send_text_message)

    response = main.receive_evolution_webhook(evolution_text_payload(), request=webhook_request(), db=db_session)

    messages = list(db_session.scalars(select(WhatsAppMessage).order_by(WhatsAppMessage.id)).all())

    assert response["status"] == "ok"
    assert captured["send"] == {
        "instance_id": "sales-main",
        "phone": "5511999990000",
        "text": "Claro! Posso te ajudar com isso por aqui.",
    }
    system_content = captured["openai_payload"]["input"][0]["content"]
    assert captured["openai_payload"]["tools"][0]["name"] == "update_lead_stage"
    assert "Automatizamos atendimento para clínicas e operações locais." in system_content
    assert "detalhes de investimento são tratados na reunião" in system_content
    assert "Proponha ativamente uma reunião" in system_content
    assert "stage converted" in system_content
    assert "stage not_interested" in system_content
    assert "Site para clínica odontológica com agendamento" in system_content
    assert "no máximo 1 item de portfólio relevante" in system_content
    assert "Nunca mencione portfólio no disparo inicial" in system_content
    assert len(messages) == 2
    assert messages[0].direction == "inbound"
    assert messages[1].direction == "outbound"
    assert messages[1].content == "Claro! Posso te ajudar com isso por aqui."
    assert messages[1].provider_message_id == "OUTBOUND_AI_1"


def test_whatsapp_portfolio_crud_endpoints(db_session: Session) -> None:
    created = main.create_whatsapp_portfolio_item(
        WhatsAppPortfolioItemCreate(
            description="Site para restaurante com cardápio online",
            url="portfolio.example/restaurante",
        ),
        db=db_session,
        username="test-user",
    )

    assert created.description == "Site para restaurante com cardápio online"
    assert created.url == "https://portfolio.example/restaurante"
    assert [(item.id, item.description, item.url) for item in main.list_whatsapp_portfolio(db=db_session, username="test-user")] == [
        (created.id, "Site para restaurante com cardápio online", "https://portfolio.example/restaurante")
    ]

    assert main.delete_whatsapp_portfolio_item(created.id, db=db_session, username="test-user") == {"status": "ok"}
    assert main.list_whatsapp_portfolio(db=db_session, username="test-user") == []


def test_whatsapp_ai_function_call_updates_crm_stage_and_history(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_lead_and_instance(db_session)
    enable_ai(db_session)

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        return FakeOpenAIResponse(
            {
                "output_text": "Perfeito, vou registrar seu interesse e te orientar no próximo passo.",
                "output": [
                    {
                        "type": "function_call",
                        "name": "update_lead_stage",
                        "arguments": json.dumps(
                            {
                                "stage": "qualified",
                                "reason": "Lead demonstrou interesse em automatizar atendimento.",
                            }
                        ),
                    }
                ],
            }
        )

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(
        whatsapp_ai_agent.EvolutionProvider,
        "send_text_message",
        lambda self, instance_id, phone, text: {"key": {"id": "OUTBOUND_AI_2"}},
    )

    main.receive_evolution_webhook(evolution_text_payload(), request=webhook_request(), db=db_session)

    crm_lead = db_session.scalars(select(CrmLead)).one()
    history = db_session.scalars(select(CrmStageHistory)).one()

    assert crm_lead.lead_id == ids["lead_id"]
    assert crm_lead.stage == "qualified"
    assert crm_lead.qualification_notes == "Lead demonstrou interesse em automatizar atendimento."
    assert history.crm_lead_id == crm_lead.id
    assert history.from_stage == "new"
    assert history.to_stage == "qualified"
    assert history.changed_by == "ai"


def test_whatsapp_ai_applies_existing_tag_with_ai_origin(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_lead_and_instance(db_session)
    db_session.add(Tag(name="Usa ERP", color="#dff7f1", description="Lead mencionou uso de ERP."))
    db_session.commit()
    enable_ai(db_session, auto_apply_tags_enabled=True)
    captured: dict[str, Any] = {}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["openai_payload"] = kwargs["json"]
        return FakeOpenAIResponse(
            {
                "output_text": "Entendi. Essa integração com ERP faz sentido para o seu cenário.",
                "output": [
                    {
                        "type": "function_call",
                        "name": "apply_lead_tags",
                        "arguments": json.dumps(
                            {
                                "tags": ["usa erp"],
                                "reason": "Lead informou que usa ERP.",
                            }
                        ),
                    }
                ],
            }
        )

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(
        whatsapp_ai_agent.EvolutionProvider,
        "send_text_message",
        lambda self, instance_id, phone, text: {"key": {"id": "OUTBOUND_TAGGED"}},
    )

    main.receive_evolution_webhook(
        evolution_text_payload(text="Hoje usamos um ERP e queremos automatizar o atendimento."),
        request=webhook_request(),
        db=db_session,
    )

    association = db_session.scalars(select(LeadTag)).one()
    tools = captured["openai_payload"]["tools"]
    system_content = captured["openai_payload"]["input"][0]["content"]

    assert association.lead_id == ids["lead_id"]
    assert association.origin == "ai"
    assert [tool["name"] for tool in tools] == ["update_lead_stage", "apply_lead_tags"]
    assert tools[1]["parameters"]["properties"]["tags"]["items"]["enum"] == ["Usa ERP"]
    assert "Tags disponíveis para classificação automática" in system_content
    assert "- Usa ERP: Lead mencionou uso de ERP." in system_content


def test_whatsapp_ai_ignores_missing_tag_and_continues_service(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seed_lead_and_instance(db_session)
    db_session.add(Tag(name="Usa ERP", color="#dff7f1"))
    db_session.commit()
    enable_ai(db_session, auto_apply_tags_enabled=True)
    captured: dict[str, Any] = {}
    caplog.set_level(logging.WARNING, logger=whatsapp_ai_agent.__name__)

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        return FakeOpenAIResponse(
            {
                "output_text": "Certo, obrigado pelo contexto.",
                "output": [
                    {
                        "type": "function_call",
                        "name": "apply_lead_tags",
                        "arguments": json.dumps({"tags": ["Tag Fantasma"]}),
                    }
                ],
            }
        )

    def fake_send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        captured["send"] = {"instance_id": instance_id, "phone": phone, "text": text}
        return {"key": {"id": "OUTBOUND_MISSING_TAG"}}

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(whatsapp_ai_agent.EvolutionProvider, "send_text_message", fake_send_text_message)

    response = main.receive_evolution_webhook(evolution_text_payload(), request=webhook_request(), db=db_session)

    assert response["status"] == "ok"
    assert captured["send"]["text"] == "Certo, obrigado pelo contexto."
    assert db_session.scalars(select(LeadTag)).all() == []
    assert "IA solicitou tag inexistente ou indisponível" in caplog.text


def test_whatsapp_ai_tag_application_is_idempotent(db_session: Session) -> None:
    ids = seed_lead_and_instance(db_session)
    tag = Tag(name="Usa ERP", color="#dff7f1")
    db_session.add(tag)
    db_session.commit()
    enable_ai(db_session, auto_apply_tags_enabled=True)
    conversation = WhatsAppConversation(
        lead_id=ids["lead_id"],
        instance_id=ids["instance_id"],
        status="open",
        last_message_at=datetime.now(timezone.utc),
    )
    db_session.add(conversation)
    db_session.commit()
    settings = db_session.get(WhatsAppAiSettings, 1)
    assert settings is not None
    tool_call = {
        "type": "function_call",
        "name": "apply_lead_tags",
        "arguments": json.dumps({"tags": ["Usa ERP"]}),
    }

    whatsapp_ai_agent._apply_tool_calls(db_session, conversation, [tool_call], ai_settings=settings)
    whatsapp_ai_agent._apply_tool_calls(db_session, conversation, [tool_call], ai_settings=settings)
    db_session.commit()

    associations = db_session.scalars(select(LeadTag)).all()
    assert len(associations) == 1
    assert associations[0].lead_id == ids["lead_id"]
    assert associations[0].tag_id == tag.id
    assert associations[0].origin == "ai"


def test_whatsapp_ai_tag_tool_disabled_when_setting_is_off(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_lead_and_instance(db_session)
    db_session.add(Tag(name="Usa ERP", color="#dff7f1", description="Lead mencionou ERP."))
    db_session.commit()
    enable_ai(db_session, auto_apply_tags_enabled=False)
    captured: dict[str, Any] = {}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["openai_payload"] = kwargs["json"]
        return FakeOpenAIResponse({"output_text": "Perfeito, obrigado por explicar."})

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(
        whatsapp_ai_agent.EvolutionProvider,
        "send_text_message",
        lambda self, instance_id, phone, text: {"key": {"id": "OUTBOUND_TAGS_OFF"}},
    )

    main.receive_evolution_webhook(evolution_text_payload(), request=webhook_request(), db=db_session)

    system_content = captured["openai_payload"]["input"][0]["content"]
    assert [tool["name"] for tool in captured["openai_payload"]["tools"]] == ["update_lead_stage"]
    assert "Tags disponíveis para classificação automática" not in system_content
    assert "apply_lead_tags" not in system_content


def test_whatsapp_ai_tag_prompt_has_no_empty_section_when_no_tags(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_lead_and_instance(db_session)
    enable_ai(db_session, auto_apply_tags_enabled=True)
    captured: dict[str, Any] = {}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["openai_payload"] = kwargs["json"]
        return FakeOpenAIResponse({"output_text": "Oi! Posso ajudar."})

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(
        whatsapp_ai_agent.EvolutionProvider,
        "send_text_message",
        lambda self, instance_id, phone, text: {"key": {"id": "OUTBOUND_NO_TAGS"}},
    )

    main.receive_evolution_webhook(evolution_text_payload(text="oi"), request=webhook_request(), db=db_session)

    system_content = captured["openai_payload"]["input"][0]["content"]
    assert [tool["name"] for tool in captured["openai_payload"]["tools"]] == ["update_lead_stage"]
    assert "Tags disponíveis para classificação automática" not in system_content


def test_update_lead_stage_tool_schema_keeps_fixed_stage_keys() -> None:
    schema = whatsapp_ai_agent._update_lead_stage_tool_schema()

    assert schema["name"] == "update_lead_stage"
    assert schema["parameters"]["required"] == ["stage", "reason"]
    assert schema["parameters"]["properties"]["stage"]["enum"] == [
        "new",
        "responded",
        "qualified",
        "not_interested",
        "converted",
    ]


def test_whatsapp_ai_marks_converted_when_lead_accepts_meeting(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_lead_and_instance(db_session)
    enable_ai(db_session)
    captured: dict[str, Any] = {}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["openai_payload"] = kwargs["json"]
        return FakeOpenAIResponse(
            {
                "output_text": "Perfeito, vou pedir para alguém entrar em contato e combinar o melhor horário com você.",
                "output": [
                    {
                        "type": "function_call",
                        "name": "update_lead_stage",
                        "arguments": json.dumps(
                            {
                                "stage": "converted",
                                "reason": "Lead aceitou marcar uma reunião.",
                            }
                        ),
                    }
                ],
            }
        )

    def fake_send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        captured["send"] = {"instance_id": instance_id, "phone": phone, "text": text}
        return {"key": {"id": "OUTBOUND_CONVERTED"}}

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(whatsapp_ai_agent.EvolutionProvider, "send_text_message", fake_send_text_message)

    main.receive_evolution_webhook(
        evolution_text_payload(text="Sim, pode ser. Vamos marcar uma reunião."),
        request=webhook_request(),
        db=db_session,
    )

    crm_lead = db_session.scalars(select(CrmLead)).one()
    history = db_session.scalars(select(CrmStageHistory)).one()
    outbound = db_session.scalars(select(WhatsAppMessage).where(WhatsAppMessage.direction == "outbound")).one()

    assert crm_lead.lead_id == ids["lead_id"]
    assert crm_lead.stage == "converted"
    assert crm_lead.qualification_notes == "Lead aceitou marcar uma reunião."
    assert history.from_stage == "new"
    assert history.to_stage == "converted"
    assert history.changed_by == "ai"
    assert outbound.content == "Perfeito, vou pedir para alguém entrar em contato e combinar o melhor horário com você."
    assert captured["send"]["text"] == outbound.content
    assert "Não tente escolher data ou horário sozinho" in captured["openai_payload"]["input"][0]["content"]


def test_whatsapp_ai_marks_not_interested_without_insisting(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_lead_and_instance(db_session)
    enable_ai(db_session)
    captured: dict[str, Any] = {}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["openai_payload"] = kwargs["json"]
        return FakeOpenAIResponse(
            {
                "output_text": "Tudo bem, obrigado por responder. Fico à disposição se fizer sentido em outro momento.",
                "output": [
                    {
                        "type": "function_call",
                        "name": "update_lead_stage",
                        "arguments": json.dumps(
                            {
                                "stage": "not_interested",
                                "reason": "Lead recusou a conversa comercial.",
                            }
                        ),
                    }
                ],
            }
        )

    def fake_send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        captured["send"] = {"instance_id": instance_id, "phone": phone, "text": text}
        return {"key": {"id": "OUTBOUND_NOT_INTERESTED"}}

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(whatsapp_ai_agent.EvolutionProvider, "send_text_message", fake_send_text_message)

    main.receive_evolution_webhook(
        evolution_text_payload(text="Não tenho interesse, obrigado."),
        request=webhook_request(),
        db=db_session,
    )

    crm_lead = db_session.scalars(select(CrmLead)).one()
    history = db_session.scalars(select(CrmStageHistory)).one()
    outbound = db_session.scalars(select(WhatsAppMessage).where(WhatsAppMessage.direction == "outbound")).one()

    assert crm_lead.lead_id == ids["lead_id"]
    assert crm_lead.stage == "not_interested"
    assert crm_lead.qualification_notes == "Lead recusou a conversa comercial."
    assert history.from_stage == "new"
    assert history.to_stage == "not_interested"
    assert history.changed_by == "ai"
    assert outbound.content == "Tudo bem, obrigado por responder. Fico à disposição se fizer sentido em outro momento."
    assert captured["send"]["text"] == outbound.content
    assert "sem insistir" in captured["openai_payload"]["input"][0]["content"]


def test_whatsapp_ai_requests_final_text_when_openai_returns_only_function_call(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_lead_and_instance(db_session, phone="(11) 91111-1111")
    enable_ai(db_session)
    captured: dict[str, Any] = {"openai_payloads": []}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["openai_payloads"].append(kwargs["json"])
        if len(captured["openai_payloads"]) == 1:
            return FakeOpenAIResponse(
                {
                    "output": [
                        {
                            "type": "function_call",
                            "name": "update_lead_stage",
                            "arguments": json.dumps(
                                {
                                    "stage": "responded",
                                    "reason": "Lead enviou uma saudação.",
                                }
                            ),
                        }
                    ]
                }
            )
        return FakeOpenAIResponse({"output_text": "Oi! Tudo bem? Como posso te ajudar hoje?"})

    def fake_send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        captured["send"] = {"instance_id": instance_id, "phone": phone, "text": text}
        return {"key": {"id": "OUTBOUND_AI_FALLBACK"}}

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(whatsapp_ai_agent.EvolutionProvider, "send_text_message", fake_send_text_message)

    main.receive_evolution_webhook(evolution_text_payload(text="oi"), request=webhook_request(), db=db_session)

    outbound = db_session.scalars(select(WhatsAppMessage).where(WhatsAppMessage.direction == "outbound")).one()

    assert len(captured["openai_payloads"]) == 2
    assert captured["openai_payloads"][0]["tools"][0]["name"] == "update_lead_stage"
    assert "tools" not in captured["openai_payloads"][1]
    assert captured["send"] == {
        "instance_id": "sales-main",
        "phone": "5511999990000",
        "text": "Oi! Tudo bem? Como posso te ajudar hoje?",
    }
    assert outbound.content == "Oi! Tudo bem? Como posso te ajudar hoje?"
    assert outbound.provider_message_id == "OUTBOUND_AI_FALLBACK"
    assert db_session.scalar(select(func.count(CrmLead.id))) == 0


def test_whatsapp_ai_disabled_by_default_does_not_call_openai_or_send(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_lead_and_instance(db_session)

    def fail_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        raise AssertionError("OpenAI não deveria ser chamada com enabled=false")

    def fail_send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        raise AssertionError("Evolution não deveria enviar resposta com enabled=false")

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fail_openai_post)
    monkeypatch.setattr(whatsapp_ai_agent.EvolutionProvider, "send_text_message", fail_send_text_message)

    main.receive_evolution_webhook(evolution_text_payload(), request=webhook_request(), db=db_session)

    settings = db_session.get(WhatsAppAiSettings, 1)
    assert settings is not None
    assert settings.enabled is False
    assert db_session.scalar(select(func.count(WhatsAppMessage.id))) == 1


def test_whatsapp_ai_circuit_breaker_skips_duplicate_recent_reply(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_lead_and_instance(db_session)
    enable_ai(db_session)
    conversation = WhatsAppConversation(
        lead_id=ids["lead_id"],
        instance_id=ids["instance_id"],
        status="open",
        last_message_at=datetime.now(timezone.utc),
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        WhatsAppMessage(
            conversation_id=conversation.id,
            direction="outbound",
            content="Resposta automática recente.",
            message_type="text",
            provider_message_id="RECENT_OUTBOUND",
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    def fail_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        raise AssertionError("OpenAI não deveria ser chamada dentro do circuit breaker")

    def fail_send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        raise AssertionError("Evolution não deveria enviar dentro do circuit breaker")

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fail_openai_post)
    monkeypatch.setattr(whatsapp_ai_agent.EvolutionProvider, "send_text_message", fail_send_text_message)

    main.receive_evolution_webhook(
        evolution_text_payload(message_id="INBOUND_2", text="Mais uma pergunta rápida."),
        request=webhook_request(),
        db=db_session,
    )

    outbound_count = db_session.scalar(
        select(func.count(WhatsAppMessage.id)).where(WhatsAppMessage.direction == "outbound")
    )
    inbound_count = db_session.scalar(
        select(func.count(WhatsAppMessage.id)).where(WhatsAppMessage.direction == "inbound")
    )

    assert outbound_count == 1
    assert inbound_count == 1


def test_whatsapp_ai_circuit_breaker_skips_recent_unknown_sender_reply(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_lead_and_instance(db_session, phone="(11) 91111-1111")
    enable_ai(db_session)
    captured: dict[str, int] = {"openai_calls": 0, "send_calls": 0}

    def fake_openai_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["openai_calls"] += 1
        return FakeOpenAIResponse({"output_text": "Oi! Como posso ajudar?"})

    def fake_send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        captured["send_calls"] += 1
        return {"key": {"id": f"OUTBOUND_UNKNOWN_{captured['send_calls']}"}}

    monkeypatch.setattr(whatsapp_ai_agent.requests, "post", fake_openai_post)
    monkeypatch.setattr(whatsapp_ai_agent.EvolutionProvider, "send_text_message", fake_send_text_message)

    main.receive_evolution_webhook(
        evolution_text_payload(message_id="UNKNOWN_INBOUND_1", text="oi"),
        request=webhook_request(),
        db=db_session,
    )
    main.receive_evolution_webhook(
        evolution_text_payload(message_id="UNKNOWN_INBOUND_2", text="Seu numero nao esta autorizado."),
        request=webhook_request(),
        db=db_session,
    )

    outbound_count = db_session.scalar(
        select(func.count(WhatsAppMessage.id)).where(WhatsAppMessage.direction == "outbound")
    )
    inbound_count = db_session.scalar(
        select(func.count(WhatsAppMessage.id)).where(WhatsAppMessage.direction == "inbound")
    )
    conversation_count = db_session.scalar(select(func.count(WhatsAppConversation.id)))

    assert captured == {"openai_calls": 1, "send_calls": 1}
    assert outbound_count == 1
    assert inbound_count == 2
    assert conversation_count == 2
