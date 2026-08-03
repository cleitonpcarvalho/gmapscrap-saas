import re
from typing import Any

import requests

from backend.config import get_settings
from backend.services.whatsapp_providers.base import WhatsAppProvider


CREATE_INSTANCE_TIMEOUT_SECONDS = 30


class EvolutionApiError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 502):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


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
            payload["number"] = _digits_only(phone_number)

        return self._request("POST", "/instance/create", json=payload, timeout=CREATE_INSTANCE_TIMEOUT_SECONDS)

    def get_qr_code(self, instance_id: str) -> dict[str, Any]:
        return self._request("GET", f"/instance/connect/{instance_id}")

    def get_connection_status(self, instance_id: str) -> dict[str, Any]:
        return self._request("GET", f"/instance/connectionState/{instance_id}")

    def set_webhook(self, instance_id: str, *, url: str, secret: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/webhook/set/{instance_id}",
            json={
                "webhook": {
                    "enabled": True,
                    "url": url,
                    "byEvents": False,
                    "base64": False,
                    "headers": {
                        "x-evolution-webhook-secret": secret,
                    },
                    "events": ["MESSAGES_UPSERT"],
                }
            },
        )

    def find_webhook(self, instance_id: str) -> dict[str, Any]:
        return self._request("GET", f"/webhook/find/{instance_id}")

    def delete_instance(self, instance_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/instance/delete/{instance_id}")

    def send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/message/sendText/{instance_id}",
            json={
                "number": phone,
                "textMessage": {"text": text},
            },
        )

    def send_audio_message(self, instance_id: str, phone: str, audio_url: str) -> dict[str, Any]:
        raise NotImplementedError("Envio de audio via Evolution ainda não implementado.")

    def get_media_base64(self, instance_id: str, message: dict[str, Any], *, convert_to_mp4: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/chat/getBase64FromMediaMessage/{instance_id}",
            json={
                "message": message,
                "convertToMp4": convert_to_mp4,
            },
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.base_url or not self.api_key:
            raise EvolutionApiError("Evolution API não configurada no backend.", status_code=422)

        request_timeout = kwargs.pop("timeout", self.timeout_seconds)
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(kwargs.pop("headers", None)),
                timeout=request_timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise EvolutionApiError(f"Evolution API indisponível: {exc}", status_code=502) from exc

        if response.status_code == 404:
            raise EvolutionApiError("Instância Evolution não encontrada.", status_code=404)
        if response.status_code >= 400:
            detail = response.text[:600]
            raise EvolutionApiError(f"Evolution API retornou erro {response.status_code}: {detail}", status_code=502)

        try:
            data = response.json()
        except ValueError as exc:
            raise EvolutionApiError("Evolution API retornou uma resposta inválida.", status_code=502) from exc

        return data if isinstance(data, dict) else {"data": data}

    def _headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"apikey": self.api_key, "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        return headers


def _digits_only(value: str) -> str:
    return re.sub(r"\D+", "", value or "")
