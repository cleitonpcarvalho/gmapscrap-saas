from typing import Any

import requests

from backend.config import get_settings
from backend.services.whatsapp_providers.base import WhatsAppProvider


class EvolutionProvider(WhatsAppProvider):
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout_seconds: float | None = None):
        settings = get_settings()
        self.base_url = (base_url if base_url is not None else settings.evolution_api_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.evolution_api_key
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.whatsapp_validation_timeout_seconds
        )

    def create_instance(self, instance_name: str, *, phone_number: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "instanceName": instance_name,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS",
        }
        if phone_number:
            payload["number"] = phone_number

        return self._request("POST", "/instance/create", json=payload)

    def get_qr_code(self, instance_id: str) -> dict[str, Any]:
        return self._request("GET", f"/instance/connect/{instance_id}")

    def get_connection_status(self, instance_id: str) -> dict[str, Any]:
        return self._request("GET", f"/instance/connectionState/{instance_id}")

    def send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        raise NotImplementedError("Envio de texto via Evolution ainda não implementado.")

    def send_audio_message(self, instance_id: str, phone: str, audio_url: str) -> dict[str, Any]:
        raise NotImplementedError("Envio de audio via Evolution ainda não implementado.")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.base_url or not self.api_key:
            raise RuntimeError("Evolution API não configurada no backend.")

        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(kwargs.pop("headers", None)),
            timeout=self.timeout_seconds,
            **kwargs,
        )
        if response.status_code >= 400:
            detail = response.text[:600]
            raise RuntimeError(f"Evolution API retornou erro {response.status_code}: {detail}")

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Evolution API retornou uma resposta inválida.") from exc

        return data if isinstance(data, dict) else {"data": data}

    def _headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"apikey": self.api_key, "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        return headers
