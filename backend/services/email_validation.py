from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

import dns.exception
import dns.resolver


EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)
BLOCKED_EXT_PATTERN = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|ico)$", re.IGNORECASE)
PLACEHOLDER_DOMAINS = {
    "domain.com",
    "email.com",
    "empresa.com",
    "example.com",
    "example.net",
    "example.org",
    "mydomain.com",
    "sample.com",
    "site.com",
    "test.com",
    "teste.com",
    "yourcompany.com",
    "yourdomain.com",
    "yoursite.com",
}
PLACEHOLDER_LOCAL_PARTS = {
    "email",
    "example",
    "exemplo",
    "jane",
    "jane.doe",
    "john",
    "john.doe",
    "name",
    "nome",
    "seu.email",
    "seuemail",
    "test",
    "teste",
    "user",
    "usuario",
    "username",
    "your.email",
    "youremail",
    "yourname",
}
NON_CONTACT_LOCAL_PARTS = {
    "abuse",
    "bounce",
    "mailer-daemon",
    "no-reply",
    "noreply",
    "postmaster",
}
PREFERRED_LOCAL_PARTS = {
    "atendimento",
    "comercial",
    "contact",
    "contato",
    "hello",
    "info",
    "office",
    "sales",
    "suporte",
}
FREE_EMAIL_DOMAINS = {
    "aol.com",
    "att.net",
    "bellsouth.net",
    "bol.com.br",
    "charter.net",
    "comcast.net",
    "cox.net",
    "earthlink.net",
    "frontier.com",
    "frontiernet.net",
    "gmx.com",
    "gmx.us",
    "gmail.com",
    "hotmail.com.br",
    "hotmail.com",
    "icloud.com",
    "ig.com.br",
    "live.com",
    "live.com.br",
    "mac.com",
    "mail.com",
    "me.com",
    "msn.com",
    "optonline.net",
    "outlook.com",
    "outlook.com.br",
    "proton.me",
    "protonmail.com",
    "roadrunner.com",
    "rocketmail.com",
    "rr.com",
    "sbcglobal.net",
    "spectrum.net",
    "terra.com.br",
    "uol.com.br",
    "verizon.net",
    "xfinity.com",
    "yahoo.com",
    "yahoo.com.br",
    "ymail.com",
    "zoho.com",
}


@dataclass(frozen=True, slots=True)
class EmailValidationResult:
    email: str
    normalized_email: str
    status: str
    reasons: tuple[str, ...]
    domain: str = ""
    has_mx: bool = False
    domain_matches_website: bool = False

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"


def validate_email_address(email: str, website: str = "", *, check_dns: bool = True) -> EmailValidationResult:
    normalized = _normalize_email(email)
    reasons: list[str] = []

    if not normalized:
        return EmailValidationResult(email=email, normalized_email="", status="invalid", reasons=("empty",))

    if len(normalized) > 254 or "@" not in normalized:
        return EmailValidationResult(email=email, normalized_email=normalized, status="invalid", reasons=("bad_format",))

    local_part, domain = normalized.rsplit("@", 1)
    domain = _normalize_domain(domain)
    if not local_part or not domain or len(local_part) > 64:
        reasons.append("bad_format")

    normalized = f"{local_part}@{domain}" if domain else normalized
    domain_matches_website = _domain_matches_website(domain, website)

    if not EMAIL_PATTERN.fullmatch(normalized):
        reasons.append("bad_format")

    if BLOCKED_EXT_PATTERN.search(normalized):
        reasons.append("asset_email")

    if _looks_like_placeholder(local_part, domain, normalized):
        reasons.append("placeholder")

    if local_part in NON_CONTACT_LOCAL_PARTS:
        reasons.append("non_contact_mailbox")

    if reasons:
        return EmailValidationResult(
            email=email,
            normalized_email=normalized,
            status="invalid",
            reasons=tuple(dict.fromkeys(reasons)),
            domain=domain,
            domain_matches_website=domain_matches_website,
        )

    has_mx = False
    if check_dns:
        mx_status = _mx_status(domain)
        if mx_status == "ok":
            has_mx = True
        elif mx_status in {"no_domain", "no_mx", "null_mx"}:
            return EmailValidationResult(
                email=email,
                normalized_email=normalized,
                status="invalid",
                reasons=(mx_status,),
                domain=domain,
                has_mx=False,
                domain_matches_website=domain_matches_website,
            )
        else:
            return EmailValidationResult(
                email=email,
                normalized_email=normalized,
                status="unknown",
                reasons=(mx_status,),
                domain=domain,
                has_mx=False,
                domain_matches_website=domain_matches_website,
            )

    return EmailValidationResult(
        email=email,
        normalized_email=normalized,
        status="valid",
        reasons=(),
        domain=domain,
        has_mx=has_mx,
        domain_matches_website=domain_matches_website,
    )


def select_best_email(candidates: list[str], website: str = "", *, check_dns: bool = True) -> EmailValidationResult | None:
    best: tuple[int, int, EmailValidationResult] | None = None
    seen: set[str] = set()

    for index, candidate in enumerate(candidates):
        result = validate_email_address(candidate, website, check_dns=check_dns)
        if result.normalized_email in seen:
            continue
        seen.add(result.normalized_email)

        if not result.is_valid:
            continue

        score = _email_score(result)
        if best is None or score > best[0]:
            best = (score, -index, result)

    return best[2] if best else None


def _normalize_email(email: str) -> str:
    value = (email or "").strip().strip(".,;:()[]{}<>").lower()
    return re.sub(r"\s+", "", value)


def _normalize_domain(domain: str) -> str:
    value = (domain or "").strip().strip(".").lower()
    if not value:
        return ""

    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def _looks_like_placeholder(local_part: str, domain: str, email: str) -> bool:
    if domain in PLACEHOLDER_DOMAINS:
        return True

    if email in {"john@smith.com", "jane@smith.com", "john.doe@smith.com"}:
        return True

    if local_part in PLACEHOLDER_LOCAL_PARTS and domain in {"smith.com", "company.com"}:
        return True

    if any(token in email for token in ("placeholder", "yourdomain", "yourcompany", "yoursite")):
        return True

    return False


def _domain_matches_website(email_domain: str, website: str) -> bool:
    site_domain = _site_domain(website)
    if not email_domain or not site_domain:
        return False

    return email_domain == site_domain or email_domain.endswith(f".{site_domain}")


def _site_domain(website: str) -> str:
    value = (website or "").strip()
    if not value:
        return ""

    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = f"https://{value}"

    parsed = urlparse(value)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    return host.split(":", 1)[0]


def _email_score(result: EmailValidationResult) -> int:
    local_part = result.normalized_email.split("@", 1)[0]
    score = 100

    if result.domain_matches_website:
        score += 40

    if local_part in PREFERRED_LOCAL_PARTS:
        score += 12

    if result.domain in FREE_EMAIL_DOMAINS:
        score -= 10

    return score


@lru_cache(maxsize=4096)
def _mx_status(domain: str) -> str:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4.0
    resolver.timeout = 2.0

    try:
        answers = resolver.resolve(domain, "MX")
    except dns.resolver.NXDOMAIN:
        return "no_domain"
    except dns.resolver.NoAnswer:
        return _address_fallback_status(resolver, domain)
    except dns.resolver.NoNameservers:
        return "dns_error"
    except dns.exception.Timeout:
        return "dns_timeout"
    except dns.exception.DNSException:
        return "dns_error"

    exchanges = [str(answer.exchange).rstrip(".") for answer in answers]
    if exchanges == [""]:
        return "null_mx"

    return "ok" if exchanges else "no_mx"


def _address_fallback_status(resolver: dns.resolver.Resolver, domain: str) -> str:
    for record_type in ("A", "AAAA"):
        try:
            resolver.resolve(domain, record_type)
            return "ok"
        except dns.resolver.NXDOMAIN:
            return "no_domain"
        except dns.resolver.NoAnswer:
            continue
        except dns.exception.Timeout:
            return "dns_timeout"
        except dns.exception.DNSException:
            return "dns_error"

    return "no_mx"
