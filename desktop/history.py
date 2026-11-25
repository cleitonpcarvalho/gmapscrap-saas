from PySide6.QtCore import QThread, Signal

from desktop.api_client import ApiClientError, GmapScrapApiClient


class HistoryWorker(QThread):
    loaded = Signal(list)
    failed = Signal(str)

    def run(self):
        client = None
        try:
            client = GmapScrapApiClient.from_environment()
            self.loaded.emit(client.list_searches())
        except ApiClientError as exc:
            self.failed.emit(str(exc))
        finally:
            if client:
                client.session.close()
