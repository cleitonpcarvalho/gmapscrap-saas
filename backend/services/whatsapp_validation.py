from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import phonenumbers
import requests

from backend.config import get_settings
from backend.services.phone_region import infer_phone_region


@dataclass(frozen=True, slots=True)
class WhatsAppValidationResult:
    phone: str
    normalized_phone: str
    status: str
    reason: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"


def is_whatsapp_validation_configured() -> bool:
    settings = get_settings()
    return bool(settings.evolution_api_base_url and settings.evolution_api_key and settings.evolution_instance_name)


def validate_whatsapp_number(phone: str, address: str = "") -> WhatsAppValidationResult:
    normalized = normalize_phone_e164(phone, address)
    if not normalized:
        return WhatsAppValidationResult(phone=phone, normalized_phone="", status="invalid", reason="bad_phone")

    if not is_whatsapp_validation_configured():
        return WhatsAppValidationResult(
            phone=phone,
            normalized_phone=normalized,
            status="unknown",
            reason="whatsapp_validation_not_configured",
        )

    exists = _check_whatsapp_number(normalized)
    if exists is True:
        return WhatsAppValidationResult(phone=phone, normalized_phone=normalized, status="valid")
    if exists is False:
        return WhatsAppValidationResult(phone=phone, normalized_phone=normalized, status="invalid", reason="not_whatsapp")

    return WhatsAppValidationResult(phone=phone, normalized_phone=normalized, status="unknown", reason="api_error")


def normalize_phone_e164(phone: str, address: str = "") -> str:
    raw = (phone or "").strip()
    if not raw:
        return ""

    cleaned = re.sub(r"^(phone:tel:|tel:)", "", raw, flags=re.IGNORECASE)
    cleaned = cleaned.replace("\u202a", "").replace("\u202c", "")
    region = None if cleaned.startswith("+") else infer_phone_region(address)

    try:
        parsed = phonenumbers.parse(cleaned, region)
    except phonenumbers.NumberParseException:
        matches = list(phonenumbers.PhoneNumberMatcher(cleaned, region or "US"))
        if not matches:
            return ""
        parsed = matches[0].number

    if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
        return ""

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

@lru_cache(maxsize=4096)
def _check_whatsapp_number(normalized_phone: str) -> bool | None:
    settings = get_settings()
    base_url = settings.evolution_api_base_url.rstrip("/")
    instance = settings.evolution_instance_name.strip().strip("/")
    url = f"{base_url}/chat/whatsappNumbers/{instance}"

    try:
        response = requests.post(
            url,
            headers={"apikey": settings.evolution_api_key, "Content-Type": "application/json"},
            json={"numbers": [normalized_phone]},
            timeout=settings.whatsapp_validation_timeout_seconds,
        )
    except requests.RequestException:
        return None

    if not response.ok:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    numbers = data.get("numbers") if isinstance(data, dict) else data
    if not isinstance(numbers, list) or not numbers:
        return None

    first = numbers[0]
    if not isinstance(first, dict):
        return None

    exists = first.get("exists")
    return exists if isinstance(exists, bool) else None
