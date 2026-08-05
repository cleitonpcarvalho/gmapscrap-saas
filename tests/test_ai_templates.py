import json
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import EmailTemplate
from backend.schemas import AiTemplateGenerateRequest
from backend.services import ai_templates
from backend.services.ai_templates import EMAIL_CHROME_TEXTS, EMAIL_LANGUAGE_LABELS


class FakeOpenAiResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture()
def db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(
        ai_templates,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-openai-key", openai_model="gpt-test"),
    )

    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()


def _payload(language: str, **overrides: Any) -> AiTemplateGenerateRequest:
    data = {
        "mode": "single",
        "count": 1,
        "campaign_name": f"Campanha {language}",
        "language": language,
    }
    data.update(overrides)
    return AiTemplateGenerateRequest(**data)


def test_ai_template_language_field_rejects_free_text() -> None:
    with pytest.raises(ValidationError):
        AiTemplateGenerateRequest(language="English")


@pytest.mark.parametrize(
    ("language", "expected_label", "expected_greeting"),
    [
        ("pt", "Portuguese (Brazil)", "Olá"),
        ("en", "English (United States)", "Hi"),
        ("es", "Spanish", "Hola"),
    ],
)
def test_generate_email_templates_prompt_instructs_selected_language(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    expected_label: str,
    expected_greeting: str,
) -> None:
    captured_payloads: list[dict[str, Any]] = []
    generated = {
        "templates": [
            {
                "name": "Template",
                "subject": "Subject",
                "content_title": "{{content_title}}",
                "paragraphs": ["Paragraph."],
                "cta_paragraph": "CTA.",
            }
        ]
    }

    def fake_post(*args: Any, **kwargs: Any) -> FakeOpenAiResponse:
        captured_payloads.append(kwargs["json"])
        return FakeOpenAiResponse(200, {"output_text": json.dumps(generated)})

    monkeypatch.setattr(ai_templates.requests, "post", fake_post)

    ai_templates.generate_email_templates(db_session, _payload(language))

    prompt = captured_payloads[0]["input"][1]["content"]
    assert f"Target language: {expected_label}." in prompt
    assert f"must be written entirely in {expected_label}" in prompt
    assert f'adds "{expected_greeting} ' in prompt


@pytest.mark.parametrize("language", ["pt", "en", "es"])
def test_generate_email_templates_localizes_chrome_fields(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
) -> None:
    generated = {
        "templates": [
            {
                "name": f"Template {language}",
                "subject": "Custom subject {{company_name}}",
                "content_title": "{{content_title}}",
                "paragraphs": ["First paragraph.", "Second paragraph."],
                "cta_paragraph": "Custom CTA.",
            }
        ]
    }

    monkeypatch.setattr(
        ai_templates.requests, "post", lambda *a, **k: FakeOpenAiResponse(200, {"output_text": json.dumps(generated)})
    )

    [template] = ai_templates.generate_email_templates(db_session, _payload(language))
    chrome = EMAIL_CHROME_TEXTS[language]

    assert template.content_button_text == chrome["content_button"]
    assert template.contact_mailto_subject == chrome["mailto_subject"]
    assert template.contact_mailto_body == chrome["mailto_body"]
    assert f'{chrome["greeting"]} {{{{lead_name}}}},' in template.html
    assert chrome["tagline"] in template.html
    assert chrome["get_in_touch"] in template.html
    assert chrome["sign_off"] in template.text
    assert chrome["disclaimer"] in template.html
    assert chrome["job_title"] in template.html
    assert f'<html lang="{chrome["html_lang"]}">' in template.html
    assert "Custom subject {{company_name}}" == template.subject
    assert "First paragraph." in template.html
    assert "Custom CTA." in template.html

    # Nothing from the other two languages' fixed chrome should leak in.
    for other_language, other_chrome in EMAIL_CHROME_TEXTS.items():
        if other_language == language:
            continue
        assert other_chrome["tagline"] not in template.html
        assert other_chrome["get_in_touch"] not in template.html
        assert other_chrome["disclaimer"] not in template.html
        assert other_chrome["content_button"] != template.content_button_text
        if other_chrome["job_title"] != chrome["job_title"]:
            assert other_chrome["job_title"] not in template.html


@pytest.mark.parametrize("language", ["pt", "en", "es"])
def test_generate_email_templates_falls_back_to_localized_defaults_when_ai_omits_fields(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
) -> None:
    generated = {
        "templates": [
            {
                "name": "",
                "subject": "",
                "content_title": "",
                "paragraphs": [],
                "cta_paragraph": "",
            }
        ]
    }

    monkeypatch.setattr(
        ai_templates.requests, "post", lambda *a, **k: FakeOpenAiResponse(200, {"output_text": json.dumps(generated)})
    )

    [template] = ai_templates.generate_email_templates(db_session, _payload(language))
    chrome = EMAIL_CHROME_TEXTS[language]

    assert template.subject == chrome["fallback_subject"]
    assert chrome["fallback_paragraph"] in template.html
    assert chrome["fallback_cta"] in template.html

    # The subject fallback must use the real {{variable}} syntax (double braces), not a
    # literal "{company_name}" that the render pipeline would never substitute.
    assert "{{company_name}}" in template.subject
    assert "{company_name}" not in template.subject.replace("{{company_name}}", "")


def test_email_language_labels_and_chrome_cover_all_three_languages() -> None:
    assert set(EMAIL_LANGUAGE_LABELS) == {"pt", "en", "es"}
    assert set(EMAIL_CHROME_TEXTS) == {"pt", "en", "es"}
    for language, chrome in EMAIL_CHROME_TEXTS.items():
        for key in ("greeting", "tagline", "get_in_touch", "sign_off", "disclaimer", "content_button", "mailto_subject", "mailto_body", "fallback_subject", "fallback_paragraph", "fallback_cta", "job_title", "html_lang"):
            assert chrome[key], f"{language}.{key} should not be empty"
