import re


LIST_FILTER_SEPARATOR = "||"

_ACRONYMS = {
    "ai": "AI",
    "api": "API",
    "b2b": "B2B",
    "b2c": "B2C",
    "crm": "CRM",
    "erp": "ERP",
    "hvac": "HVAC",
    "ia": "IA",
    "it": "IT",
    "ny": "NY",
    "nyc": "NYC",
    "ppc": "PPC",
    "ptac": "PTAC",
    "saas": "SaaS",
    "seo": "SEO",
    "uk": "UK",
    "us": "US",
    "usa": "USA",
}

_LOWERCASE_WORDS = {
    "a",
    "and",
    "as",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "for",
    "in",
    "na",
    "nas",
    "no",
    "nos",
    "of",
    "on",
    "the",
}


def _normalize_piece(piece: str, *, is_first: bool) -> str:
    lower = piece.lower()
    if lower in _ACRONYMS:
        return _ACRONYMS[lower]
    if lower in _LOWERCASE_WORDS and not is_first:
        return lower
    return f"{lower[:1].upper()}{lower[1:]}"


def _normalize_token(token: str, *, is_first: bool) -> str:
    if not any(character.isalnum() for character in token):
        return token

    parts = token.split("-")
    return "-".join(
        _normalize_piece(part, is_first=is_first and index == 0) if part else part
        for index, part in enumerate(parts)
    )


def normalize_label(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip())
    if not text:
        return ""

    return " ".join(_normalize_token(token, is_first=index == 0) for index, token in enumerate(text.split(" ")))


def normalize_list_filter(value: str) -> str:
    seen: set[str] = set()
    labels: list[str] = []

    for item in (value or "").split(LIST_FILTER_SEPARATOR):
        label = normalize_label(item)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            labels.append(label)

    return LIST_FILTER_SEPARATOR.join(sorted(labels, key=lambda label: label.casefold()))
