from __future__ import annotations

import base64
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from backend import main
from backend.database import Base
from backend.models import CrmLead, Lead, SearchRun, WhatsAppConversation, WhatsAppInstance, WhatsAppMessage
from backend.services import whatsapp_webhooks


WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture()
def db_session(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(evolution_webhook_secret=WEBHOOK_SECRET))
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


def evolution_text_payload(
    *,
    message_id: str = "3EB0C7B4E7A2B8E6D4F1",
    remote_jid: str = "5511999990000@s.whatsapp.net",
    text: str = "Hello, I need help with my order",
    timestamp: int = 1709553296,
) -> dict[str, Any]:
    return {
        "event": "MESSAGES_UPSERT",
        "instance": "sales-main",
        "data": {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": False,
                "id": message_id,
            },
            "pushName": "John Doe",
            "message": {
                "conversation": text,
            },
            "messageType": "conversation",
            "messageTimestamp": timestamp,
            "instanceId": "550e8400-e29b-41d4-a716-446655440000",
            "source": "ios",
        },
        "destination": "https://app.example.test/api/whatsapp/webhook/evolution",
        "date_time": "2026-03-04T12:34:56.789Z",
        "sender": remote_jid,
        "server_url": "https://evolution-api.com",
        "apikey": "B5F6E890D1234567890ABCDEF1234567",
    }


def evolution_audio_payload(
    *,
    message_id: str = "AUDIO_MESSAGE_1",
    remote_jid: str = "5511999990000@s.whatsapp.net",
) -> dict[str, Any]:
    payload = evolution_text_payload(message_id=message_id, remote_jid=remote_jid, text="")
    payload["data"]["message"] = {
        "audioMessage": {
            "mimetype": "audio/ogg; codecs=opus",
            "seconds": 4,
        }
    }
    payload["data"]["messageType"] = "audioMessage"
    return payload


def webhook_request(*, secret: str = WEBHOOK_SECRET) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/whatsapp/webhook/evolution",
            "headers": [(b"x-evolution-webhook-secret", secret.encode())],
        }
    )


def test_evolution_text_webhook_creates_conversation_and_matches_lead(
    db_session: Session,
) -> None:
    ids = seed_lead_and_instance(db_session)

    response = main.receive_evolution_webhook(evolution_text_payload(), request=webhook_request(), db=db_session)

    assert response == {"status": "ok", "event": "MESSAGES_UPSERT", "processed": 1, "ignored": 0}

    conversation = db_session.scalars(select(WhatsAppConversation)).one()
    message = db_session.scalars(select(WhatsAppMessage)).one()
    crm_lead = db_session.scalars(select(CrmLead)).one()

    assert conversation.lead_id == ids["lead_id"]
    assert conversation.instance_id == ids["instance_id"]
    assert message.conversation_id == conversation.id
    assert message.direction == "inbound"
    assert message.message_type == "text"
    assert message.content == "Hello, I need help with my order"
    assert message.provider_message_id == "3EB0C7B4E7A2B8E6D4F1"
    assert crm_lead.lead_id == ids["lead_id"]
    assert crm_lead.stage == "new"


def test_evolution_text_webhook_updates_existing_conversation(
    db_session: Session,
) -> None:
    ids = seed_lead_and_instance(db_session)
    conversation = WhatsAppConversation(
        lead_id=ids["lead_id"],
        instance_id=ids["instance_id"],
        status="needs_attention",
    )
    db_session.add(conversation)
    db_session.commit()
    conversation_id = conversation.id

    response = main.receive_evolution_webhook(
        evolution_text_payload(message_id="TEXT_2", text="Tenho interesse em conversar.", timestamp=1709553999),
        request=webhook_request(),
        db=db_session,
    )

    assert response["status"] == "ok"

    conversations_count = db_session.scalar(select(func.count(WhatsAppConversation.id)))
    conversation = db_session.get(WhatsAppConversation, conversation_id)
    message = db_session.scalars(select(WhatsAppMessage)).one()

    assert conversations_count == 1
    assert conversation is not None
    assert conversation.status == "open"
    assert conversation.last_message_at is not None
    assert message.conversation_id == conversation_id
    assert message.content == "Tenho interesse em conversar."


def test_evolution_text_webhook_unknown_lead_creates_null_lead_conversation(
    db_session: Session,
) -> None:
    seed_lead_and_instance(db_session, phone="(11) 91111-1111")

    response = main.receive_evolution_webhook(
        evolution_text_payload(message_id="UNKNOWN_LEAD_1", remote_jid="5588999990000@s.whatsapp.net"),
        request=webhook_request(),
        db=db_session,
    )

    assert response["status"] == "ok"

    conversation = db_session.scalars(select(WhatsAppConversation)).one()
    message = db_session.scalars(select(WhatsAppMessage)).one()

    assert conversation.lead_id is None
    assert message.conversation_id == conversation.id
    assert message.content == "Hello, I need help with my order"
    assert db_session.scalar(select(func.count(CrmLead.id))) == 0


def test_evolution_audio_webhook_downloads_and_transcribes_audio(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_lead_and_instance(db_session)

    captured: dict[str, Any] = {}

    def fake_get_media_base64(self, instance_id: str, message: dict[str, Any], *, convert_to_mp4: bool = False):
        captured["instance_id"] = instance_id
        captured["message_id"] = message["key"]["id"]
        captured["convert_to_mp4"] = convert_to_mp4
        return {
            "mediaType": "audioMessage",
            "mimetype": "audio/ogg; codecs=opus",
            "base64": base64.b64encode(b"fake-audio-bytes").decode(),
        }

    def fake_transcribe_audio_bytes(audio: bytes, *, filename: str, mime_type: str) -> str:
        captured["audio"] = audio
        captured["filename"] = filename
        captured["mime_type"] = mime_type
        return "Transcrição do áudio"

    monkeypatch.setattr(whatsapp_webhooks.EvolutionProvider, "get_media_base64", fake_get_media_base64)
    monkeypatch.setattr(whatsapp_webhooks, "transcribe_audio_bytes", fake_transcribe_audio_bytes)

    response = main.receive_evolution_webhook(evolution_audio_payload(), request=webhook_request(), db=db_session)

    assert response["status"] == "ok"

    message = db_session.scalars(select(WhatsAppMessage)).one()

    assert captured == {
        "instance_id": "sales-main",
        "message_id": "AUDIO_MESSAGE_1",
        "convert_to_mp4": False,
        "audio": b"fake-audio-bytes",
        "filename": "audio.ogg",
        "mime_type": "audio/ogg; codecs=opus",
    }
    assert message.message_type == "audio"
    assert message.content == "Transcrição do áudio"
    assert message.audio_transcript == "Transcrição do áudio"


def test_evolution_webhook_rejects_invalid_secret(
    db_session: Session,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        main.receive_evolution_webhook(evolution_text_payload(), request=webhook_request(secret="wrong-secret"), db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Webhook Evolution não autorizado"


def test_webhook_secret_stays_stable_once_persisted_even_if_env_var_changes(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_secret = main._get_or_create_evolution_webhook_secret(db_session)
    db_session.commit()
    assert first_secret == WEBHOOK_SECRET

    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(evolution_webhook_secret=""))
    assert main._get_or_create_evolution_webhook_secret(db_session) == first_secret

    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(evolution_webhook_secret="some-other-secret"))
    assert main._get_or_create_evolution_webhook_secret(db_session) == first_secret

    response = main.receive_evolution_webhook(
        evolution_text_payload(message_id="STABLE_SECRET_1"),
        request=webhook_request(secret=first_secret),
        db=db_session,
    )
    assert response["status"] == "ok"
