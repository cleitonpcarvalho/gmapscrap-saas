from typing import Any

from backend.services.whatsapp_providers.base import WhatsAppProvider


class MetaCloudProvider(WhatsAppProvider):
    def create_instance(self, instance_name: str, *, phone_number: str | None = None) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud API ainda não implementada")

    def get_qr_code(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud API ainda não implementada")

    def get_connection_status(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud API ainda não implementada")

    def delete_instance(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud API ainda não implementada")

    def send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud API ainda não implementada")

    def send_audio_message(self, instance_id: str, phone: str, audio_url: str) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud API ainda não implementada")
