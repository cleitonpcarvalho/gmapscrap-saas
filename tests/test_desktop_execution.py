import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from backend.scrapers.control import SearchCancelled, SearchControl
from backend.scrapers.maps_scraper import MapLead, ScrapeEvent
from desktop.api_client import ApiClientError, search_status
from desktop.worker import SearchWorker
from desktop.state import pending_search


@pytest.fixture(scope="module", autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def execution(monkeypatch):
    worker = SearchWorker("Livre", "Fortaleza", 10, False, skip_without_website=False)
    class Client:
        def __init__(self):
            self.session = self
            self.calls = []
            self.row = dict(id=17, niche="Livre", location="Fortaleza", status="running", scanned_count=0, saved_count=2)
            self.closed = False
        def close(self):
            self.closed = True
        def login(self):
            self.calls.append(("login",))
        def create_search(self, *args, **kwargs):
            self.calls.append(("create",))
            return dict(self.row)
        def update_search(self, run_id, **kwargs):
            assert run_id == 17
            self.calls.append(("update", kwargs))
            self.row.update({key: value for key, value in kwargs.items() if value is not None})
            return dict(self.row)
        def stop_search(self, run_id, **kwargs):
            return self.update_search(run_id, status="stopped", **kwargs)
        def ingest_lead(self, run_id, **kwargs):
            self.calls.append(("ingest", kwargs))
            self.row.update(scanned_count=kwargs["scanned"], saved_count=self.row["saved_count"] + 1)
            return dict(run=dict(self.row), message="Salvo")
    client = Client()
    monkeypatch.setattr("desktop.worker.GmapScrapApiClient.from_environment", lambda: client)
    results, finished = [], []
    worker.progress.connect(results.append)
    worker.finished.connect(lambda ok, message: finished.append((ok, message)))
    return worker, client, results, finished


def event(index=1, website=""):
    return ScrapeEvent("lead", index, "Encontrado", MapLead("Empresa", "Centro", "85999999999", website))


@pytest.mark.parametrize("action,status", [("pause", "paused"), ("stop", "stopped")])
def test_cancel_before_first_event_never_ingests_and_closes_generator(execution, monkeypatch, action, status):
    worker, client, results, finished = execution
    closed = []
    def scrape(*args, **kwargs):
        try:
            getattr(worker, action)()
            yield event()
        finally:
            closed.append(True)
    monkeypatch.setattr("desktop.worker.scrape_google_maps", scrape)
    worker.run()
    assert client.row["status"] == status
    assert client.row["saved_count"] == 2
    assert client.row["scanned_count"] == 0
    assert not any(call[0] == "ingest" for call in client.calls)
    assert closed == [True]
    assert not finished[0][0]
    assert client.closed
    assert pending_search() is None


def test_stop_during_email_enrichment_never_saves_or_advances_resume_cursor(execution, monkeypatch):
    worker, client, results, finished = execution
    monkeypatch.setattr("desktop.worker.scrape_google_maps", lambda *a, **k: iter([event(1, "https://example.test")]))
    def email(*args, **kwargs):
        worker.stop()
        return SimpleNamespace(email="hello@example.test")
    monkeypatch.setattr("desktop.worker.extract_email_from_site", email)
    worker.run()
    assert client.row["status"] == "stopped"
    assert client.row["scanned_count"] == 0
    assert client.row["saved_count"] == 2
    assert not any(call[0] == "ingest" for call in client.calls)


def test_stop_during_last_ingest_keeps_saved_lead_and_never_marks_completed(execution, monkeypatch):
    worker, client, results, finished = execution
    worker.quantity = 3
    original = client.ingest_lead
    def ingest(*args, **kwargs):
        response = original(*args, **kwargs)
        worker.stop()
        return response
    client.ingest_lead = ingest
    monkeypatch.setattr("desktop.worker.scrape_google_maps", lambda *a, **k: iter([event()]))
    worker.run()
    assert client.row["status"] == "stopped"
    assert client.row["saved_count"] == 3
    assert not finished[0][0]


def test_resume_reuses_run_and_cursor_without_creating_search(execution, monkeypatch):
    worker, client, results, finished = execution
    worker.resume_run_id, worker.start_index = 17, 8
    seen = {}
    def scrape(*a, **kw):
        seen.update(kw)
        yield ScrapeEvent("done", 7, "Fim")
    monkeypatch.setattr("desktop.worker.scrape_google_maps", scrape)
    worker.run()
    assert not any(call[0] == "create" for call in client.calls)
    assert client.calls[1][1]["status"] == "running"
    assert seen["start_index"] == 8
    assert client.row["scanned_count"] == 7
    assert finished[0][0]


def test_stop_paused_search_only_finalizes_existing_run(execution, monkeypatch):
    worker, client, results, finished = execution
    worker.resume_run_id, worker.finalize_only = 17, True
    worker.stop()
    monkeypatch.setattr("desktop.worker.scrape_google_maps", lambda *a, **kw: pytest.fail("Must not launch Chrome"))
    worker.run()
    assert client.calls == [("update", {"status": "stopped", "scanned_count": 0})]
    assert client.row["saved_count"] == 2
    assert not finished[0][0]


def test_stop_before_start_creates_no_remote_execution(execution):
    worker, client, results, finished = execution
    worker.stop()
    worker.run()
    assert client.calls == []
    assert not finished[0][0]


def test_stop_overrides_pause_and_selenium_error_during_cancellation(execution, monkeypatch):
    worker, client, results, finished = execution
    def scrape(*a, **kw):
        worker.pause()
        worker.stop()
        worker.pause()
        raise RuntimeError("browser closed")
    monkeypatch.setattr("desktop.worker.scrape_google_maps", scrape)
    worker.run()
    assert client.row["status"] == "stopped"
    assert not finished[0][0]


def test_failed_terminal_sync_is_durable_and_retryable(execution):
    worker, client, results, finished = execution
    worker.resume_run_id, worker.finalize_only = 17, True
    worker.stop()
    client.stop_search = lambda *a, **kw: (_ for _ in ()).throw(ApiClientError("offline"))
    worker.run()
    assert results[-1]["sync_pending"]
    assert pending_search()["status"] == "stopped"
    assert pending_search()["id"] == 17
    assert client.closed


def test_cancel_interrupts_waits_and_late_driver_is_cleaned(monkeypatch):
    control = SearchControl()
    calls = []
    monkeypatch.setattr("backend.scrapers.control.BrowserLease.close", lambda lease: calls.append(lease.driver))
    control.request("stopped")
    with pytest.raises(SearchCancelled):
        control.sleep(100)
    driver = object()
    with pytest.raises(SearchCancelled):
        control.attach(driver, object(), "/tmp/unused")
    assert calls == [driver]


def test_browser_cleanup_only_terminates_its_owned_process_tree(tmp_path):
    import subprocess
    import sys
    import psutil
    from backend.scrapers.control import BrowserLease
    script = """
import subprocess, sys, signal
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
def cleanup(*args):
    child.terminate()
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, cleanup)
print(child.pid, flush=True)
child.wait()
"""
    owned = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    child_id = int(owned.stdout.readline())
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    lease = BrowserLease(SimpleNamespace(process=owned), str(profile))
    # A broken quit() must still reap only this search's Chrome/driver processes.
    lease.driver = SimpleNamespace(quit=lambda: (_ for _ in ()).throw(RuntimeError("lost Selenium session")))
    try:
        lease.close()
        lease.close()
        assert lease.closed.wait(8)
        owned.wait(timeout=3)
        assert not psutil.pid_exists(child_id) or psutil.Process(child_id).status() == psutil.STATUS_ZOMBIE
        assert unrelated.poll() is None
        assert not profile.exists()
    finally:
        for proc in [owned, unrelated]:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=3)
        owned.stdout.close()


def test_email_scraper_does_not_request_another_page_after_cancel(monkeypatch):
    from backend.scrapers import email_scraper
    control = SearchControl()
    calls = []
    def fetch(url):
        calls.append(url)
        control.request("stopped")
        return '<a href="/contact">Contact</a>'
    monkeypatch.setattr(email_scraper, "fetch_html", fetch)
    with pytest.raises(SearchCancelled):
        email_scraper.extract_email_from_site("https://example.test", control=control)
    assert calls == ["https://example.test"]


def test_terminal_conflict_reconciles_authoritative_status(execution):
    worker, client, results, finished = execution
    worker.resume_run_id, worker.finalize_only = 17, True
    worker.stop()
    client.stop_search = lambda *a, **kw: (_ for _ in ()).throw(ApiClientError("already terminal", 409))
    client.get_search = lambda run_id: dict(id=run_id, status="stopped", message="Stopped elsewhere")
    worker.run()
    assert results[-1]["status"] == "stopped"
    assert not results[-1].get("sync_pending")
    assert pending_search() is None


def test_real_chrome_stop_reaps_browser_and_driver(monkeypatch):
    if os.getenv("GMAPSCRAP_TEST_CHROME") != "1":
        pytest.skip("Opt-in local Chrome integration")
    from pathlib import Path
    import psutil
    from backend.config import get_settings
    from backend.scrapers.maps_scraper import _create_driver
    get_settings.cache_clear()
    control = SearchControl()
    driver = _create_driver(control)
    profile = Path(driver._gmapscrap_profile_dir)
    parent = psutil.Process(driver.service.process.pid)
    processes = parent.children(recursive=True) + [parent]
    try:
        driver.get("data:text/html,<title>GmapScrap local regression</title><p>Local only</p>")
        assert driver.title == "GmapScrap local regression"
        control.request("stopped")
        with pytest.raises(SearchCancelled):
            driver.get("data:text/html,Must not scrape")
        control.close_browser()
        assert control.lease.closed.is_set()
        assert not profile.exists()
        assert not any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in processes)
    finally:
        control.close_browser()
        get_settings.cache_clear()


def test_lost_creation_reply_is_durable_and_never_creates_another_search(execution, monkeypatch):
    worker, client, results, finished = execution
    client.create_search = lambda *a, **kw: (_ for _ in ()).throw(ApiClientError("lost creation reply"))
    monkeypatch.setattr("desktop.worker.scrape_google_maps", lambda *a, **kw: pytest.fail("Creation not confirmed"))
    worker.run()
    pending = pending_search()
    assert pending["creation_uncertain"]
    assert pending["request_key"] == worker.request_key
    assert results[-1]["sync_pending"]
    assert "id" not in results[-1]
    assert not finished[0][0]


def test_creation_recovery_only_finalizes_the_original_run(execution, monkeypatch):
    worker, client, results, finished = execution
    worker.finalize_only = True
    worker.initial_run = dict(creation_uncertain=True, request_key="original-key", status="stopped")
    keys = []
    def recover(key):
        keys.append(key)
        return dict(client.row)
    client.get_created_search = recover
    worker.stop()
    monkeypatch.setattr("desktop.worker.scrape_google_maps", lambda *a, **kw: pytest.fail("Must not start a duplicate"))
    worker.run()
    assert keys == ["original-key"]
    assert client.calls == [("update", {"status": "stopped", "scanned_count": 0})]
    assert pending_search() is None
