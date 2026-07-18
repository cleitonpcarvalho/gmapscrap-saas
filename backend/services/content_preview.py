from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ContentPreview:
    url: str
    title: str = ""
    image_url: str = ""


def _is_http_url(value: str) -> bool:
    parsed = urlparse((value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str:
    for attr, value in selectors:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def _first_image(soup: BeautifulSoup) -> str:
    for selector in ("article img", "main img", ".post img", ".entry-content img", "img"):
        image = soup.select_one(selector)
        if not image:
            continue

        src = image.get("src") or image.get("data-src") or image.get("data-lazy-src")
        if src and not str(src).startswith("data:"):
            return str(src).strip()
    return ""


@lru_cache(maxsize=256)
def fetch_content_preview(url: str) -> ContentPreview:
    normalized_url = (url or "").strip()
    if not _is_http_url(normalized_url):
        return ContentPreview(url=normalized_url)

    response = requests.get(
        normalized_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=12,
        allow_redirects=True,
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "xml" not in content_type:
        return ContentPreview(url=response.url)

    soup = BeautifulSoup(response.text, "html.parser")
    title = _meta_content(
        soup,
        ("property", "og:title"),
        ("name", "twitter:title"),
        ("itemprop", "name"),
    )
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    image_url = _meta_content(
        soup,
        ("property", "og:image:secure_url"),
        ("property", "og:image"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
        ("itemprop", "image"),
    )
    if not image_url:
        image_url = _first_image(soup)

    if image_url:
        image_url = urljoin(response.url, image_url)

    return ContentPreview(url=response.url, title=title[:500], image_url=image_url[:1000])
