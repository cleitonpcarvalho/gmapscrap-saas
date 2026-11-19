from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from desktop.api_client import ApiClientError, GmapScrapApiClient


class NicheWorker(QThread):
    """Keep registry requests and retries off the UI thread."""

    loaded = Signal(list)
    created = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None, *, name: str | None = None):
        super().__init__(parent)
        self.name = name

    def run(self) -> None:
        client = None
        try:
            client = GmapScrapApiClient.from_environment()
            if self.name is None:
                self.loaded.emit(client.list_niches())
            else:
                self.created.emit(client.create_niche(self.name))
        except ApiClientError as exc:
            self.failed.emit(str(exc))
        finally:
            if client is not None:
                client.session.close()
