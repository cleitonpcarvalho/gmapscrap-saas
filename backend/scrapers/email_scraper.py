import re
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
BLOCKED_EMAIL_PATTERN = re.compile(
    r"(2x|3x|logo|icon|sprite|wixpress|sentry|schema\.org|w3\.org|godaddy|"
    r"placeholder|@\d|example\.com|domain\.com|yourdomain|yourcompany|yoursite|"
    r"test\.com|email\.com|company\.com|sample\.com|mydomain)",
    re.IGNORECASE,
)
BLOCKED_EXT_PATTERN = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|ico)$", re.IGNORECASE)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class EmailResult:
    email: str = ""
    contact_url: str = ""
    checked_urls: tuple[str, ...] = ()


def normalize_site_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""

    if value.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
        return ""

    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = f"https://{value}"

    parsed = urlparse(value)
    host = (parsed.netloc or "").lower()
    if not host or "." not in host or any(char in host for char in (" ", "%", ",")):
        return ""

    if any(blocked in host for blocked in ("google.", "gstatic.", "ggpht.", "googleusercontent.")):
        return ""

    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{host}{path}"


def fetch_html(url: str) -> str:
    normalized = normalize_site_url(url)
    if not normalized:
        return ""

    try:
        response = requests.get(
            normalized,
            headers={"User-Agent": USER_AGENT},
            timeout=6,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""

    return response.text if isinstance(response.text, str) else ""


def _deobfuscate_email_text(text: str) -> str:
    return (
        text.replace(" [at] ", "@")
        .replace("[at]", "@")
        .replace(" (at) ", "@")
        .replace("(at)", "@")
        .replace(" [dot] ", ".")
        .replace("[dot]", ".")
        .replace(" (dot) ", ".")
        .replace("(dot)", ".")
    )


def _decode_cloudflare_emails(html: str) -> list[str]:
    emails: list[str] = []

    for encoded in re.findall(r'data-cfemail=["\']([0-9a-fA-F]+)["\']', html or ""):
        if len(encoded) < 4 or len(encoded) % 2:
            continue

        try:
            key = int(encoded[:2], 16)
            decoded = "".join(chr(int(encoded[index : index + 2], 16) ^ key) for index in range(2, len(encoded), 2))
        except ValueError:
            continue

        if EMAIL_REGEX.fullmatch(decoded):
            emails.append(decoded)

    return emails


def find_email(html: str) -> str:
    if not html:
        return ""

    soup_text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    text = _deobfuscate_email_text(unquote(f"{html} {soup_text}"))
    matches = [*_decode_cloudflare_emails(html), *EMAIL_REGEX.findall(text)]

    for match in matches:
        email = match.strip().strip(".,;:()[]{}<>").lower()
        if BLOCKED_EMAIL_PATTERN.search(email) or BLOCKED_EXT_PATTERN.search(email):
            continue
        return email

    return ""


def _same_site(candidate_url: str, base_url: str) -> bool:
    candidate_host = urlparse(candidate_url).netloc.lower().removeprefix("www.")
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    return candidate_host == base_host or candidate_host.endswith(f".{base_host}")


def _score_support_page(haystack: str) -> int:
    value = haystack.lower()
    scores = (
        (50, ("contact-us", "contactus", "fale-conosco", "faleconosco")),
        (45, ("contact", "contato", "contacts")),
        (35, ("about-us", "aboutus", "quem-somos", "quem somos", "sobre-nos", "sobre nos")),
        (30, ("about", "sobre", "empresa", "company")),
    )

    for score, keywords in scores:
        if any(keyword in value for keyword in keywords):
            return score

    return 0


def find_support_page_urls(html: str, base_url: str) -> list[str]:
    if not html or not base_url:
        return []

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        label = anchor.get_text(" ", strip=True).lower()
        haystack = f"{href} {label}".lower()
        score = _score_support_page(haystack)

        if not score:
            continue

        try:
            normalized = normalize_site_url(urljoin(base_url, href))
        except ValueError:
            continue

        if normalized and _same_site(normalized, base_url):
            candidates.append((score, normalized))

    for path, score in (
        ("/contact", 25),
        ("/contact-us", 25),
        ("/contacts", 22),
        ("/contato", 25),
        ("/fale-conosco", 25),
        ("/about", 18),
        ("/about-us", 18),
        ("/sobre", 18),
        ("/sobre-nos", 18),
        ("/quem-somos", 18),
    ):
        normalized = normalize_site_url(urljoin(base_url, path))
        if normalized:
            candidates.append((score, normalized))

    unique: dict[str, int] = {}
    for score, url in candidates:
        if url == base_url:
            continue
        unique[url] = max(unique.get(url, 0), score)

    return [url for url, _ in sorted(unique.items(), key=lambda item: item[1], reverse=True)]


def find_contact_url(html: str, base_url: str) -> str:
    urls = find_support_page_urls(html, base_url)
    return urls[0] if urls else ""


def extract_email_from_site(site_url: str) -> EmailResult:
    site = normalize_site_url(site_url)
    if not site:
        return EmailResult()

    checked_urls: list[str] = []
    html = fetch_html(site)
    checked_urls.append(site)

    email = find_email(html)
    if email:
        return EmailResult(email=email, contact_url=site, checked_urls=tuple(checked_urls))

    support_urls = find_support_page_urls(html, site)
    contact_url = support_urls[0] if support_urls else ""

    for url in support_urls[:10]:
        if url in checked_urls:
            continue

        checked_urls.append(url)
        email = find_email(fetch_html(url))
        if email:
            return EmailResult(email=email, contact_url=url, checked_urls=tuple(checked_urls))

    return EmailResult(email="", contact_url=contact_url, checked_urls=tuple(checked_urls))
