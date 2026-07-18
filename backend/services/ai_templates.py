import html
import json
import re
from datetime import datetime

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import EmailTemplate
from backend.schemas import AiTemplateGenerateRequest
from backend.services.template_seeds import DEFAULT_LOGO_URL


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
GENERIC_CONTEXT_TERMS = {"all", "todos", "todas", "any", "all niches", "all locations"}
EM_DASH_PATTERN = re.compile(r"\s*[\u2014\u2015]\s*")
SPACED_EN_DASH_PATTERN = re.compile(r"\s+\u2013\s+")


def _template_html(paragraphs: list[str], cta_paragraph: str) -> str:
    body = "\n".join(
        f'              <p style="font-size:16px;color:{{{{text_color}}}};line-height:1.7;margin:0 0 16px 0;">{html.escape(paragraph)}</p>'
        for paragraph in paragraphs
        if paragraph.strip()
    )
    safe_cta = html.escape(cta_paragraph.strip())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{{{content_title}}}}</title>
</head>
<body style="margin:0;padding:0;background-color:{{{{background_color}}}};font-family:Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:{{{{background_color}}}};padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <tr>
            <td style="background-color:{{{{primary_color}}}};padding:32px 40px;text-align:center;">
              <img src="{{{{logo_url}}}}" alt="Automa Soluct" height="64" style="display:block;margin:0 auto;" />
              <p style="color:#d7d7d7;font-size:13px;margin:12px 0 0 0;">Automation & Integrations</p>
            </td>
          </tr>
          <tr>
            <td style="padding:40px 40px 24px 40px;">
              <p style="font-size:16px;color:{{{{text_color}}}};margin:0 0 16px 0;">Hi {{{{lead_name}}}},</p>
{body}
              {{{{content_card_block}}}}
              <p style="font-size:16px;color:{{{{text_color}}}};line-height:1.7;margin:0 0 16px 0;">{safe_cta}</p>
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:10px 0 32px 0;">
                    <a href="{{{{get_in_touch_link}}}}" style="background-color:{{{{primary_color}}}};color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:6px;font-size:15px;font-weight:600;display:inline-block;">Get in touch</a>
                  </td>
                </tr>
              </table>
              <hr style="border:none;border-top:1px solid #eeeeee;margin:0 0 28px 0;" />
              <p style="font-size:13px;color:#888888;margin:0 0 12px 0;text-transform:uppercase;font-weight:600;">Get in touch</p>
              <p style="font-size:15px;color:{{{{text_color}}}};line-height:1.7;margin:0;">
                Cleiton Carvalho<br />
                Automation Specialist - Automa Soluct<br />
                <a href="https://automasoluct.com.br" style="color:{{{{primary_color}}}};text-decoration:none;">automasoluct.com.br</a>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 40px 40px 40px;border-top:1px solid #eeeeee;">
              <p style="margin:0;font-size:12px;color:#999999;line-height:1.6;">This is a low-volume content note from Automa Soluct. Reply 'remove' if you prefer not to receive future resources.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _plain_text(paragraphs: list[str], cta_paragraph: str) -> str:
    parts = ["Hi {{lead_name}},", *[paragraph.strip() for paragraph in paragraphs if paragraph.strip()]]
    parts.extend(
        [
            "{{content_title}}",
            "{{content_link}}",
            cta_paragraph.strip(),
            "Best,",
            "Cleiton Carvalho",
            "Automa Soluct",
        ]
    )
    return "\n\n".join(parts)


def _context_terms(value: str) -> list[str]:
    terms = [
        item.strip()
        for item in re.split(r"\|\||,|\n", value or "")
        if item.strip() and item.strip().lower() not in GENERIC_CONTEXT_TERMS
    ]
    return sorted(set(terms), key=len, reverse=True)


def _replace_context_terms(text: str, terms: list[str], placeholder: str) -> str:
    next_text = text or ""
    for term in terms:
        pattern = re.compile(rf"(?<!\{{)\b{re.escape(term)}\b(?!\}})", re.IGNORECASE)
        next_text = pattern.sub(placeholder, next_text)
    return next_text


def _enforce_dynamic_context(text: str, payload: AiTemplateGenerateRequest) -> str:
    next_text = _replace_context_terms(text, _context_terms(payload.niche), "{{niche}}")
    return _replace_context_terms(next_text, _context_terms(payload.location), "{{location}}")


def _avoid_ai_dashes(text: str) -> str:
    next_text = EM_DASH_PATTERN.sub(", ", text or "")
    next_text = SPACED_EN_DASH_PATTERN.sub(", ", next_text)
    return next_text.replace("\u2013", "-").replace(" ,", ",").strip()


def _unique_name(db: Session, base_name: str) -> str:
    name = base_name.strip()[:240] or f"AI Template {datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    candidate = name
    suffix = 2
    while db.scalar(select(EmailTemplate.id).where(EmailTemplate.name == candidate)):
        candidate = f"{name[:230]} {suffix}"
        suffix += 1
    return candidate


def _extract_output_text(response_payload: dict) -> str:
    if response_payload.get("output_text"):
        return str(response_payload["output_text"])

    chunks: list[str] = []
    for item in response_payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks)


def _json_schema() -> dict:
    template_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "subject", "content_title", "paragraphs", "cta_paragraph"],
        "properties": {
            "name": {"type": "string"},
            "subject": {"type": "string"},
            "content_title": {"type": "string"},
            "paragraphs": {
                "type": "array",
                "items": {"type": "string"},
            },
            "cta_paragraph": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["templates"],
        "properties": {
            "templates": {
                "type": "array",
                "items": template_schema,
            }
        },
    }


def _prompt(payload: AiTemplateGenerateRequest) -> str:
    count = 1 if payload.mode == "single" else payload.count
    return f"""
Generate {count} email template(s) for Automa Soluct.

Context:
- Automa Soluct provides automation and integration services for local service businesses.
- The email is low-pressure and content-led, not spammy and not aggressively salesy.
- Language: {payload.language}
- Selected niche context for strategy only: {payload.niche or "all niches"}
- Selected location context for strategy only: {payload.location or "all locations"}
- Objective: {payload.objective}
- Tone: {payload.tone}
- Content title: {payload.content_title or "{{content_title}}"}
- Content link type: YouTube video or blog post
- Desired CTA: {payload.call_to_action}

Rules:
- Use the greeting placeholder context naturally, but do not include the greeting itself. The system adds "Hi {{{{lead_name}}}},".
- Use "{{{{content_title}}}}" exactly where the content title should appear.
- Never write literal niche names or literal location names in subject or body copy.
- If you refer to the lead's industry, use "{{{{niche}}}}" exactly.
- If you refer to the lead's market or region, use "{{{{location}}}}" exactly.
- Company/name context must stay dynamic through the system greeting; do not invent company names.
- Do not include raw URLs, markdown links, bracketed placeholders, or standalone link lines.
- Do not write button labels. The system inserts the content card and CTA buttons automatically.
- Do not promise guaranteed results.
- Do not mention scraping or Google Maps.
- For sequences, make each email feel connected but not repetitive.
- Never use U+2014 em dash or U+2015 horizontal bar in any subject, title, paragraph, or CTA.
- Do not use long dashes as comma or parenthetical punctuation. Use commas, periods, colons, semicolons, or parentheses instead.
- Normal ASCII hyphens inside compound words are allowed when grammatically needed.
- Return only the JSON that matches the schema.
"""


def generate_email_templates(db: Session, payload: AiTemplateGenerateRequest) -> list[EmailTemplate]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY não está configurada no backend.")

    count = 1 if payload.mode == "single" else payload.count
    request_payload = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You write concise, compliant B2B email templates as structured JSON. "
                    "Do not use U+2014 em dash or U+2015 horizontal bar in generated email copy."
                ),
            },
            {"role": "user", "content": _prompt(payload)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "email_template_generation",
                "strict": True,
                "schema": _json_schema(),
            }
        },
    }

    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json=request_payload,
        timeout=90,
    )
    if response.status_code >= 400:
        detail = response.text[:600]
        raise RuntimeError(f"OpenAI retornou erro {response.status_code}: {detail}")

    output_text = _extract_output_text(response.json())
    if not output_text:
        raise RuntimeError("A OpenAI não retornou conteúdo.")

    try:
        generated = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("A OpenAI retornou um JSON inválido.") from exc

    templates_data = generated.get("templates", [])[:count]
    saved_templates: list[EmailTemplate] = []
    for index, item in enumerate(templates_data, start=1):
        paragraphs = [
            _avoid_ai_dashes(_enforce_dynamic_context(str(paragraph).strip(), payload))
            for paragraph in item.get("paragraphs", [])
            if str(paragraph).strip()
        ]
        if not paragraphs:
            paragraphs = [
                "I wanted to share a practical resource that may help your team reduce manual work and keep follow-ups organized.",
            ]

        cta_paragraph = _avoid_ai_dashes(
            _enforce_dynamic_context(str(item.get("cta_paragraph") or payload.call_to_action).strip(), payload)
        )
        base_name = _avoid_ai_dashes(str(item.get("name") or f"{payload.campaign_name or 'AI Campaign'} Email {index}"))
        content_title = _avoid_ai_dashes(str(payload.content_title or item.get("content_title") or "{{content_title}}").strip())
        subject = _avoid_ai_dashes(_enforce_dynamic_context(
            str(item.get("subject") or f"Useful automation resource for {{company_name}}").strip(),
            payload,
        ))

        template = EmailTemplate(
            name=_unique_name(db, base_name),
            subject=subject[:500],
            html=_template_html(paragraphs, cta_paragraph),
            text=_plain_text(paragraphs, cta_paragraph),
            content_title=content_title[:500],
            content_link=payload.content_link.strip(),
            logo_url=payload.logo_url.strip() or DEFAULT_LOGO_URL,
            primary_color=payload.primary_color or "#0a0a0a",
            text_color=payload.text_color or "#333333",
            background_color=payload.background_color or "#f4f4f4",
        )
        db.add(template)
        saved_templates.append(template)

    db.commit()
    for template in saved_templates:
        db.refresh(template)
    return saved_templates
