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


def focus_picker(window):
    from PySide6.QtTest import QTest
    window.show()
    window.activateWindow()
    if QApplication.platformName() != "offscreen":
        assert QTest.qWaitForWindowActive(window, 5000)
    QApplication.processEvents()
    window._load_niche_suggestions([{"id": 1, "name": "Brindes"}, {"id": 2, "name": "Marketing"}, {"id": 3, "name": "Presentes"}])
    window.location_input.setFocus()
    QApplication.processEvents()
    QTest.mouseClick(window.niche_input, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    return window.niche_completer.popup()


def test_focus_and_click_show_all_niches_even_when_empty(window):
    from PySide6.QtTest import QTest
    popup = focus_picker(window)
    assert popup.isVisible()
    assert window.niche_completer.completionCount() == 3
    popup.hide()
    window.niche_input.setText("Outro texto")
    QTest.mouseClick(window.niche_input, Qt.MouseButton.LeftButton)
    assert window.niche_completer.completionCount() == 3
    assert window.niche_input.text() == "Outro texto"


def test_typing_filters_and_empty_input_shows_everything(window):
    from PySide6.QtTest import QTest
    popup = focus_picker(window)
    QTest.keyClicks(window.niche_input, "rke")
    assert window.niche_completer.completionCount() == 1
    assert window.niche_completer.currentCompletion() == "Marketing"
    for _ in range(3):
        QTest.keyClick(window.niche_input, Qt.Key.Key_Backspace)
    assert window.niche_completer.completionCount() == 3
    QTest.keyClicks(window.niche_input, "Novo nicho livre")
    assert window.niche_input.text() == "Novo nicho livre"
    assert not popup.isVisible()


def test_keyboard_selection_and_escape_close_popup(window):
    from PySide6.QtTest import QTest
    popup = focus_picker(window)
    QTest.keyClick(popup, Qt.Key.Key_Down)
    QTest.keyClick(popup, Qt.Key.Key_Return)
    assert window.niche_input.text() == "Brindes"
    assert not popup.isVisible()
    # The offscreen plugin deactivates the top-level window when its popup hides.
    window.activateWindow()
    if QApplication.platformName() != "offscreen":
        assert QTest.qWaitForWindowActive(window, 5000)
    QApplication.processEvents()
    QTest.mouseClick(window.niche_input, Qt.MouseButton.LeftButton)
    assert popup.isVisible()
    QTest.keyClick(popup, Qt.Key.Key_Escape)
    assert not popup.isVisible()


def test_mouse_selection_and_outside_click_close_popup(window):
    from PySide6.QtTest import QTest
    popup = focus_picker(window)
    index = popup.model().index(1, 0)
    QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton, pos=popup.visualRect(index).center())
    assert window.niche_input.text() == "Marketing"
    assert not popup.isVisible()
    window.activateWindow()
    if QApplication.platformName() != "offscreen":
        assert QTest.qWaitForWindowActive(window, 5000)
    QApplication.processEvents()
    QTest.mouseClick(window.niche_input, Qt.MouseButton.LeftButton)
    # Route through the native window so Qt's popup mouse grab sees the outside
    # click. Sending directly to QLineEdit bypasses that routing on Linux.
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton,
                     pos=window.location_input.mapTo(window, window.location_input.rect().center()))
    QApplication.processEvents()
    assert not popup.isVisible()


def test_paused_controls_resume_same_execution_and_allow_permanent_stop(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_start_worker", lambda *a, **kw: calls.append((a, kw)))
    window.current_run = dict(id=27, status="paused", niche="Livre", location="Fortaleza", scanned_count=9, saved_count=3)
    window._set_running(False)
    assert not window.start_button.isEnabled()
    assert window.pause_button.text() == "Retomar"
    assert window.stop_button.isEnabled()
    window.resume_search()
    assert calls[-1][1] == {"run_id": 27, "start_index": 10}
    calls.clear()
    window.stop_search()
    assert calls[-1][1] == {"run_id": 27, "finalize_only": True}


def test_busy_and_terminal_states_prevent_duplicate_or_stopped_resume(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_start_worker", lambda *a, **kw: calls.append(kw))
    window.current_run = dict(id=27, status="stopped")
    window.resume_search()
    assert calls == []
    window.thread = object()
    window.start_search()
    window.resume_search()
    assert calls == []
    window.thread = None


def test_unsynchronized_stop_blocks_new_search_and_offers_retry(window, monkeypatch):
    window.current_run = dict(id=27, status="stopped", sync_pending=True)
    window._set_running(False)
    assert not window.start_button.isEnabled()
    assert window.pause_button.text() == "Tentar sincronizar"
    calls = []
    monkeypatch.setattr(window, "_finalize_current", calls.append)
    window.handle_secondary_action()
    assert calls == ["stopped"]
    window.current_run = None


def test_execution_buttons_remain_visible_when_form_needs_scrolling(window):
    from PySide6.QtWidgets import QScrollArea
    window.resize(980, 680)
    window.show()
    QApplication.processEvents()
    scroll = window.findChild(QScrollArea)
    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0
    for button in (window.start_button, window.pause_button, window.stop_button):
        assert button.isVisible()
        assert button.height() >= 44
        assert not scroll.isAncestorOf(button)
