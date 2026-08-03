from abc import ABC, abstractmethod
from typing import Any


class WhatsAppProvider(ABC):
    @abstractmethod
    def create_instance(self, instance_name: str, *, phone_number: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_qr_code(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_connection_status(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete_instance(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def send_text_message(self, instance_id: str, phone: str, text: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def send_audio_message(self, instance_id: str, phone: str, audio_url: str) -> dict[str, Any]:
        raise NotImplementedError
