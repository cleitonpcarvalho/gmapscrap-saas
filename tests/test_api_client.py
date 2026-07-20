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
