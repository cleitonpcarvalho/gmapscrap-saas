from types import SimpleNamespace
from typing import Any

import requests

from backend.services import site_insights


class FakeOpenAIResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def test_extract_site_insights_uses_site_content_and_openai(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_fetch_html(url: str) -> str:
        if url.endswith("/sobre"):
            return "<html><body><p>Atendemos clínicas locais com automação de agendamento.</p></body></html>"
        return (
            "<html><head><meta name='viewport' content='width=device-width'></head>"
            "<body><h1>Clínica Alfa</h1><p>Serviços de saúde e atendimento presencial.</p><form></form></body></html>"
        )

    def fake_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        captured["payload"] = kwargs["json"]
        return FakeOpenAIResponse(
            {
                "output_text": (
                    '{"site_insights":"A empresa parece atuar em saúde local. O site tem formulário, mas pode explorar melhor agendamento online."}'
                )
            }
        )

    monkeypatch.setattr(site_insights, "get_settings", lambda: SimpleNamespace(openai_api_key="key", openai_model="gpt-test"))
    monkeypatch.setattr(site_insights, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(site_insights, "find_support_page_urls", lambda html, site: [f"{site}/sobre"])
    monkeypatch.setattr(site_insights.requests, "post", fake_post)

    result = site_insights.extract_site_insights(
        "clinica.example",
        business_name="Clínica Alfa",
        niche="Clínicas",
        location="São Paulo",
    )

    assert result == "A empresa parece atuar em saúde local. O site tem formulário, mas pode explorar melhor agendamento online."
    assert captured["payload"]["model"] == "gpt-test"
    assert captured["payload"]["text"]["format"]["name"] == "site_insights"
    assert "Clínica Alfa" in captured["payload"]["input"][1]["content"]
    assert "has_mobile_viewport" in captured["payload"]["input"][1]["content"]


def test_extract_site_insights_returns_none_on_openai_error(monkeypatch) -> None:
    def fake_post(*args: Any, **kwargs: Any) -> FakeOpenAIResponse:
        raise requests.Timeout("timeout")

    monkeypatch.setattr(site_insights, "get_settings", lambda: SimpleNamespace(openai_api_key="key", openai_model="gpt-test"))
    monkeypatch.setattr(site_insights, "fetch_html", lambda url: "<html><body>Texto suficiente do site</body></html>")
    monkeypatch.setattr(site_insights, "find_support_page_urls", lambda html, site: [])
    monkeypatch.setattr(site_insights.requests, "post", fake_post)

    assert site_insights.extract_site_insights("https://empresa.example") is None
