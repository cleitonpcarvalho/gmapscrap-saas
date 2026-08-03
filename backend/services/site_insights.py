from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup

from backend.config import get_settings
from backend.scrapers.email_scraper import fetch_html, find_support_page_urls, normalize_site_url


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_SITE_TEXT_CHARS = 12000
MAX_INSIGHTS_CHARS = 1200

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteContext:
    url: str
    text: str
    signals: dict[str, Any]


def extract_site_insights(
    website: str,
    *,
    business_name: str = "",
    niche: str = "",
    location: str = "",
) -> str | None:
    settings = get_settings()
    if not settings.openai_api_key:
        logger.info("OPENAI_API_KEY ausente; enriquecimento de site ignorado para %s", website)
        return None

    context = fetch_site_context(website)
    if not context or not context.text.strip():
        return None

    request_payload = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": (
                    "Você analisa páginas de empresas locais e gera um resumo curto, factual e útil para personalizar abordagem comercial."
                ),
            },
            {
                "role": "user",
                "content": _prompt(context, business_name=business_name, niche=niche, location=location),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "site_insights",
                "strict": True,
                "schema": _json_schema(),
            }
        },
        "max_output_tokens": 450,
    }

    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=45,
        )
        if response.status_code >= 400:
            logger.info("OpenAI retornou %s ao enriquecer site %s: %s", response.status_code, website, response.text[:300])
            return None

        output_text = _extract_output_text(response.json())
        if not output_text:
            return None

        data = json.loads(output_text)
    except (requests.RequestException, ValueError) as exc:
        logger.info("Falha ao enriquecer site %s: %s", website, exc)
        return None

    insights = _clean_insights(str(data.get("site_insights") or ""))
    return insights or None


def fetch_site_context(website: str) -> SiteContext | None:
    site = normalize_site_url(website)
    if not site:
        return None

    html_pages: list[tuple[str, str]] = []
    homepage_html = fetch_html(site)
    if homepage_html:
        html_pages.append((site, homepage_html))

    for url in find_support_page_urls(homepage_html, site)[:2]:
        html = fetch_html(url)
        if html:
            html_pages.append((url, html))

    text_parts = [_visible_text(html) for _, html in html_pages]
    text = _compact_text(" ".join(part for part in text_parts if part))
    if not text:
        return None

    return SiteContext(url=site, text=text[:MAX_SITE_TEXT_CHARS], signals=_site_signals(html_pages))


def _json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["site_insights"],
        "properties": {
            "site_insights": {"type": "string"},
        },
    }


def _prompt(context: SiteContext, *, business_name: str, niche: str, location: str) -> str:
    return f"""
Empresa: {business_name or "não informado"}
Nicho pesquisado: {niche or "não informado"}
Localidade pesquisada: {location or "não informado"}
Site: {context.url}
Sinais técnicos simples: {json.dumps(context.signals, ensure_ascii=False)}

Texto extraído do site:
{context.text}

Gere um resumo em português do Brasil, com 2 a 4 frases curtas, cobrindo:
- o que a empresa parece fazer;
- dores ou oportunidades observáveis no site, sem inventar fatos;
- se houver sinal técnico simples como ausência de viewport, formulário, loja, catálogo ou presença fraca de CTA, mencione com cuidado.

Não diga que foi feito scraping. Não critique de forma agressiva. Não inclua preço, valores ou promessa garantida.
Retorne apenas JSON compatível com o schema.
"""


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()
    return soup.get_text(" ", strip=True)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _site_signals(html_pages: list[tuple[str, str]]) -> dict[str, Any]:
    combined_html = "\n".join(html for _, html in html_pages)
    combined_text = _visible_text(combined_html).lower()
    soup = BeautifulSoup(combined_html or "", "html.parser")
    return {
        "has_mobile_viewport": bool(soup.find("meta", attrs={"name": re.compile("^viewport$", re.IGNORECASE)})),
        "has_contact_form": bool(soup.find("form")) or any(term in combined_text for term in ("formulário", "contact form", "quote request")),
        "has_online_store_terms": any(term in combined_text for term in ("cart", "checkout", "shop", "loja", "carrinho", "comprar")),
        "has_booking_terms": any(term in combined_text for term in ("booking", "appointment", "agendar", "schedule", "reserva")),
        "page_count_checked": len(html_pages),
    }


def _extract_output_text(response_payload: dict[str, Any]) -> str:
    if response_payload.get("output_text"):
        return str(response_payload["output_text"])

    chunks: list[str] = []
    for item in response_payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks)


def _clean_insights(value: str) -> str:
    text = _compact_text(value)
    return text[:MAX_INSIGHTS_CHARS].strip()
