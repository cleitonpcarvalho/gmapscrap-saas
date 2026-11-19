import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from desktop.app import MainWindow
from desktop.api_client import ApiClientError
from desktop.niches import NicheWorker


@pytest.fixture()
def window(monkeypatch):
    application = QApplication.instance() or QApplication([])
    # Constructor timers must never contact an external API in tests.
    monkeypatch.setattr(MainWindow, "refresh_history", lambda self: None)
    monkeypatch.setattr(MainWindow, "refresh_niches", lambda self: None)
    widget = MainWindow()
    yield widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def test_suggestions_match_substrings_case_insensitively_and_preserve_text(window):
    window.niche_input.setText("personal")
    window._load_niche_suggestions([
        {"id": 1, "name": "Brindes Personalizados"}, {"id": 2, "name": "Marketing"},
    ])
    completer = window.niche_completer
    completer.setCompletionPrefix("PERSONAL")
    assert completer.filterMode() == Qt.MatchFlag.MatchContains
    assert completer.completionCount() == 1
    assert completer.currentCompletion() == "Brindes Personalizados"
    assert window.niche_input.text() == "personal"
    window.niche_input.setText(completer.currentCompletion())
    assert not window.create_niche_button.isEnabled()
    window.niche_input.setText("Novo nicho")
    assert window.create_niche_button.isEnabled()
    window.niche_input.setText(" ")
    assert not window.create_niche_button.isEnabled()


def test_create_niche_updates_suggestions_without_starting_search(window):
    window._niche_created({"id": 1, "name": "Brindes"})
    assert window.niche_input.text() == "Brindes"
    assert window.niche_model.stringList() == ["Brindes"]
    assert window.thread is None
    assert window.current_run is None


@pytest.mark.parametrize("name", [None, "Brindes"])
def test_niche_worker_routes_requests_and_closes_session(monkeypatch, name):
    class Client:
        closed = False

        def __init__(self):
            self.session = self

        def list_niches(self):
            return [{"id": 1, "name": "Brindes"}]

        def create_niche(self, value):
            assert value == "Brindes"
            return {"id": 1, "name": value}

        def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr("desktop.niches.GmapScrapApiClient.from_environment", lambda: client)
    worker = NicheWorker(name=name)
    results = []
    worker.loaded.connect(results.append)
    worker.created.connect(results.append)
    worker.run()
    expected = [[{"id": 1, "name": "Brindes"}]] if name is None else [{"id": 1, "name": "Brindes"}]
    assert results == expected
    assert client.closed


def test_failed_suggestions_keep_free_text_search_available(window, monkeypatch):
    monkeypatch.setattr("desktop.niches.GmapScrapApiClient.from_environment", lambda: (_ for _ in ()).throw(ApiClientError("Offline")))
    worker = NicheWorker()
    failures = []
    worker.failed.connect(failures.append)
    worker.run()
    assert failures == ["Offline"]
    assert window.niche_input.isEnabled()
    assert window.start_button.isEnabled()
