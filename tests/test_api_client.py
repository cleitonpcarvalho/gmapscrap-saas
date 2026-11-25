import requests

from desktop.api_client import ApiConfig, GmapScrapApiClient


class DummyResponse:
    ok = True
    status_code = 200
    content = b"{}"

    def json(self) -> dict:
        return {}

    def close(self) -> None:
        pass


class ResetOnceSession:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = 0

    def request(self, *args, **kwargs) -> DummyResponse:
        self.calls += 1
        if self.calls == 1:
            raise requests.ConnectionError("Connection reset by peer")
        return DummyResponse()

    def close(self) -> None:
        self.closed += 1


def test_send_with_retries_closes_stale_connection_before_retry() -> None:
    client = GmapScrapApiClient(ApiConfig(base_url="https://api.example.test", username="user", password="pass"))
    session = ResetOnceSession()
    client.session = session  # type: ignore[assignment]

    response = client._send_with_retries("GET", "/api/health", timeout=1)

    assert response.ok is True
    assert session.calls == 2
    assert session.closed == 1


def test_create_search_sends_only_without_website_flag(monkeypatch) -> None:
    client = GmapScrapApiClient(ApiConfig(base_url="https://api.example.test", username="user", password="pass"))
    captured: dict = {}

    def fake_request(method: str, path: str, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"id": 1}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.create_search(
        "Marketing",
        "São Paulo",
        10,
        False,
        False,
        True,
        False,
        only_without_website=True,
    )

    assert result == {"id": 1}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/desktop/searches"
    assert captured["json"]["only_without_website"] is True


def test_niche_client_uses_shared_authenticated_api(monkeypatch) -> None:
    client = GmapScrapApiClient(ApiConfig(base_url="https://api.example.test", username="user", password="pass"))
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return [{"id": 1, "name": "Brindes"}] if method == "GET" else {"id": 1, "name": "Brindes"}

    monkeypatch.setattr(client, "_request", request)
    assert client.list_niches("brin")[0]["name"] == "Brindes"
    assert client.create_niche("Brindes")["id"] == 1
    assert calls == [
        ("GET", "/api/niches", {"params": {"q": "brin"}, "timeout": 20}),
        ("POST", "/api/niches", {"json": {"name": "Brindes"}, "timeout": 20}),
    ]


def test_stop_uses_legacy_terminal_fallback_only_for_validation_failure(monkeypatch):
    from desktop.api_client import ApiClientError, STOPPED_ERROR, search_status
    client = GmapScrapApiClient(ApiConfig("https://example.test", "u", "p"))
    calls = []
    def update(run_id, **kw):
        calls.append(kw)
        if kw["status"] == "stopped":
            raise ApiClientError("unsupported status", 422)
        return kw
    monkeypatch.setattr(client, "update_search", update)
    run = client.stop_search(1, scanned_count=7)
    assert [call["status"] for call in calls] == ["stopped", "failed"]
    assert run["error"] == STOPPED_ERROR
    assert search_status(run) == "stopped"
    assert run["scanned_count"] == 7


def test_stop_does_not_disguise_auth_or_network_errors(monkeypatch):
    import pytest
    from desktop.api_client import ApiClientError
    client = GmapScrapApiClient(ApiConfig("https://example.test", "u", "p"))
    monkeypatch.setattr(client, "update_search", lambda *a, **k: (_ for _ in ()).throw(ApiClientError("unauthorized", 401)))
    with pytest.raises(ApiClientError) as exc:
        client.stop_search(1)
    assert exc.value.status_code == 401


def test_creation_is_never_automatically_retried_on_legacy_api(monkeypatch):
    import pytest
    from desktop.api_client import ApiClientError
    client = GmapScrapApiClient(ApiConfig("https://example.test", "u", "p"))
    client._authenticated = True
    class Session:
        calls = 0
        def request(self, *a, **kw):
            self.calls += 1
            raise requests.ConnectionError("lost reply")
        def close(self):
            pass
    session = Session()
    client.session = session
    with pytest.raises(ApiClientError):
        client.create_search("Livre", "Fortaleza", 5, False, False, False)
    assert session.calls == 1
