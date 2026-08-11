from __future__ import annotations

import base64
import binascii
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.models import Lead, WhatsAppCampaign, WhatsAppConversation, WhatsAppInstance, WhatsAppMessage, WhatsAppSend
from backend.services.whatsapp_ai_agent import handle_inbound_message
from backend.services.crm import get_or_create_crm_lead
from backend.services.openai_audio import transcribe_audio_bytes
from backend.services.whatsapp_providers.evolution import EvolutionApiError, EvolutionProvider
from backend.services.whatsapp_validation import normalize_phone_e164


MEDIA_PLACEHOLDERS = {
    "audio": "[audio]",
    "image": "[image]",
    "other": "[message]",
}

logger = logging.getLogger(__name__)


def is_evolution_messages_upsert_event(event: str) -> bool:
    normalized = str(event or "").replace(".", "_").replace("-", "_").upper()
    return normalized == "MESSAGES_UPSERT"


def ingest_evolution_messages_upsert(
    db: Session,
    payload: dict[str, Any],
    *,
    media_provider: EvolutionProvider | None = None,
    transcribe_audio: Callable[[bytes], str] | None = None,
) -> dict[str, int]:
    provider = media_provider or EvolutionProvider()
    processed = 0
    ignored = 0

    for data in _payload_messages(payload):
        key = _message_key(data)
        if key.get("fromMe") is True:
            ignored += 1
            continue

        remote_jid = _remote_jid(payload, data, key)
        if _is_non_contact_jid(remote_jid):
            ignored += 1
            continue

        provider_message_id = str(key.get("id") or data.get("id") or "").strip() or None
        if provider_message_id and db.scalar(
            select(WhatsAppMessage.id).where(WhatsAppMessage.provider_message_id == provider_message_id)
        ):
            ignored += 1
            continue

        instance_name = _instance_name(payload, data)
        instance = _get_or_create_instance(db, instance_name)
        sender_phone = _phone_from_jid(remote_jid)
        lead = _find_lead_by_phone(db, sender_phone)
        conversation = _get_or_create_conversation(db, instance, lead)
        if lead:
            campaign = _latest_whatsapp_campaign_for_lead(db, lead.id)
            get_or_create_crm_lead(db, lead.id, funnel_id=campaign.funnel_id if campaign else None)
        message_type = _message_type(data)
        message_created_at = _message_datetime(payload, data)
        audio_transcript = None

        if message_type == "audio":
            audio_bytes, mime_type = _audio_payload(provider, instance, data)
            audio_transcript = (
                transcribe_audio(audio_bytes)
                if transcribe_audio
                else transcribe_audio_bytes(audio_bytes, filename=_audio_filename(mime_type), mime_type=mime_type)
            )
            content = audio_transcript or MEDIA_PLACEHOLDERS["audio"]
        else:
            content = _message_text(data) or MEDIA_PLACEHOLDERS.get(message_type, MEDIA_PLACEHOLDERS["other"])

        conversation.last_message_at = message_created_at
        conversation.status = "open"
        inbound_message = WhatsAppMessage(
            conversation_id=conversation.id,
            direction="inbound",
            content=content,
            message_type=message_type,
            audio_transcript=audio_transcript,
            provider_message_id=provider_message_id,
            created_at=message_created_at,
        )
        db.add(inbound_message)
        db.flush()
        handle_inbound_message(db, conversation, inbound_message, sender_phone=sender_phone, provider=provider)
        processed += 1

    return {"processed": processed, "ignored": ignored}


def _payload_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _message_key(data: dict[str, Any]) -> dict[str, Any]:
    key = data.get("key")
    return key if isinstance(key, dict) else {}


def _instance_name(payload: dict[str, Any], data: dict[str, Any]) -> str:
    value = payload.get("instance") or data.get("instanceName") or data.get("instance")
    return str(value or "evolution-webhook").strip()


def _remote_jid(payload: dict[str, Any], data: dict[str, Any], key: dict[str, Any]) -> str:
    remote_jid = str(key.get("remoteJid") or data.get("remoteJid") or data.get("chatId") or "").strip()
    if "@lid" in remote_jid:
        remote_jid = str(
            key.get("remoteJidAlt")
            or key.get("participantAlt")
            or data.get("remoteJidAlt")
            or data.get("sender")
            or payload.get("sender")
            or remote_jid
        ).strip()
    return remote_jid or str(data.get("sender") or payload.get("sender") or "").strip()


def _is_non_contact_jid(remote_jid: str) -> bool:
    jid = str(remote_jid or "")
    return "@g.us" in jid or jid == "status@broadcast" or jid.endswith("@broadcast")


def _phone_from_jid(remote_jid: str) -> str:
    value = str(remote_jid or "").split("@", 1)[0].split(":", 1)[0]
    return _digits(value)


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _find_lead_by_phone(db: Session, sender_phone_digits: str) -> Lead | None:
    if not sender_phone_digits:
        return None

    leads = db.scalars(
        select(Lead)
        .options(selectinload(Lead.search_run))
        .where(Lead.phone.is_not(None), Lead.phone != "")
        .order_by(Lead.id)
    ).all()
    for lead in leads:
        normalized = normalize_phone_e164(lead.phone or "", f"{lead.address or ''} {lead.location or ''}")
        lead_digits = _digits(normalized) or _digits(lead.phone or "")
        if lead_digits == sender_phone_digits:
            return lead
    return None


def _latest_whatsapp_campaign_for_lead(db: Session, lead_id: int) -> WhatsAppCampaign | None:
    sends = list(
        db.scalars(
            select(WhatsAppSend)
            .options(selectinload(WhatsAppSend.campaign))
            .where(WhatsAppSend.lead_id == lead_id)
            .order_by(
                WhatsAppSend.sent_at.is_(None),
                desc(WhatsAppSend.sent_at),
                desc(WhatsAppSend.created_at),
                desc(WhatsAppSend.id),
            )
            .limit(5)
        ).all()
    )
    if not sends:
        return None

    campaign_ids = [send.campaign_id for send in sends if send.campaign_id]
    distinct_campaign_ids = list(dict.fromkeys(campaign_ids))
    if len(distinct_campaign_ids) > 1:
        logger.info(
            "Lead respondeu após envios de múltiplas campanhas WhatsApp; usando a campanha mais recente",
            extra={"lead_id": lead_id, "campaign_ids": distinct_campaign_ids},
        )
    return sends[0].campaign


def _get_or_create_instance(db: Session, instance_name: str) -> WhatsAppInstance:
    stmt = select(WhatsAppInstance).where(
        or_(
            WhatsAppInstance.evolution_instance_name == instance_name,
            WhatsAppInstance.name == instance_name,
        )
    )
    instance = db.scalar(stmt)
    if instance:
        return instance

    instance = WhatsAppInstance(
        name=instance_name,
        provider="evolution",
        status="connected",
        evolution_instance_name=instance_name,
        connected_at=datetime.now(timezone.utc),
    )
    db.add(instance)
    db.flush()
    return instance


def _get_or_create_conversation(
    db: Session,
    instance: WhatsAppInstance,
    lead: Lead | None,
) -> WhatsAppConversation:
    if lead:
        conversation = db.scalar(
            select(WhatsAppConversation).where(
                WhatsAppConversation.instance_id == instance.id,
                WhatsAppConversation.lead_id == lead.id,
            )
        )
        if conversation:
            return conversation

    conversation = WhatsAppConversation(
        lead_id=lead.id if lead else None,
        instance_id=instance.id,
        status="open",
    )
    db.add(conversation)
    db.flush()
    return conversation


def _message_dict(data: dict[str, Any]) -> dict[str, Any]:
    message = data.get("message")
    return message if isinstance(message, dict) else {}


def _message_type(data: dict[str, Any]) -> str:
    raw_type = str(data.get("messageType") or "").lower()
    message = _message_dict(data)

    if "audiomessage" in raw_type or "audioMessage" in message:
        return "audio"
    if "imagemessage" in raw_type or "imageMessage" in message:
        return "image"
    if raw_type in {"conversation", "extendedtextmessage"} or "conversation" in message or "extendedTextMessage" in message:
        return "text"
    return "other"


def _message_text(data: dict[str, Any]) -> str:
    message = _message_dict(data)
    nested_candidates = (
        ("extendedTextMessage", "text"),
        ("imageMessage", "caption"),
        ("videoMessage", "caption"),
        ("documentMessage", "caption"),
        ("audioMessage", "caption"),
    )
    if message.get("conversation"):
        return str(message["conversation"]).strip()
    for parent_key, text_key in nested_candidates:
        nested = message.get(parent_key)
        if isinstance(nested, dict) and nested.get(text_key):
            return str(nested[text_key]).strip()
    return ""


def _message_datetime(payload: dict[str, Any], data: dict[str, Any]) -> datetime:
    timestamp = data.get("messageTimestamp")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, timezone.utc)
    if isinstance(timestamp, str) and timestamp.isdigit():
        return datetime.fromtimestamp(int(timestamp), timezone.utc)

    raw_date = str(data.get("date_time") or payload.get("date_time") or "").strip()
    if raw_date:
        try:
            parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _audio_payload(provider: EvolutionProvider, instance: WhatsAppInstance, data: dict[str, Any]) -> tuple[bytes, str]:
    message = _message_dict(data)
    audio_message = message.get("audioMessage") if isinstance(message.get("audioMessage"), dict) else {}
    base64_value = _media_base64_from_payload(data)
    mime_type = str(audio_message.get("mimetype") or audio_message.get("mime_type") or "audio/ogg")

    if not base64_value:
        instance_name = instance.evolution_instance_name or instance.name
        try:
            media = provider.get_media_base64(instance_name, data)
        except EvolutionApiError:
            raise
        base64_value = _media_base64_from_payload(media)
        mime_type = str(media.get("mimetype") or media.get("mime_type") or mime_type)

    if not base64_value:
        raise RuntimeError("Evolution API não retornou o áudio em base64.")

    return _decode_base64_media(base64_value), mime_type


def _media_base64_from_payload(data: dict[str, Any]) -> str:
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    for source in (data, message):
        value = source.get("base64") if isinstance(source, dict) else None
        if value:
            return str(value)
    return ""


def _decode_base64_media(value: str) -> bytes:
    cleaned = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    try:
        return base64.b64decode(cleaned, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError("Evolution API retornou mídia em base64 inválida.") from exc


def _audio_filename(mime_type: str) -> str:
    extension_by_mime = {
        "audio/ogg": "ogg",
        "audio/opus": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/mp4": "mp4",
        "audio/m4a": "m4a",
        "audio/wav": "wav",
        "audio/webm": "webm",
    }
    clean_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    return f"audio.{extension_by_mime.get(clean_mime, 'ogg')}"
