from __future__ import annotations

import re
import unicodedata


def infer_phone_region(context: str) -> str:
    normalized = _fold_text(context)
    if any(value in normalized for value in ("estados unidos", "united states", "eua", " usa")):
        return "US"

    if (
        any(value in normalized for value in _BRAZIL_CITY_MARKERS)
        or any(value in normalized for value in _BRAZIL_ADDRESS_MARKERS)
        or re.search(r"\b\d{5}-?\d{3}\b", normalized)
    ):
        return "BR"

    return "US"


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


_BRAZIL_CITY_MARKERS = (
    "sao paulo",
    "rio de janeiro",
    "belo horizonte",
    "brasilia",
    "fortaleza",
    "salvador",
    "curitiba",
    "recife",
    "porto alegre",
    "manaus",
    "belem",
    "goiania",
    "florianopolis",
    "vitoria",
    "campinas",
    "santos",
)

_BRAZIL_ADDRESS_MARKERS = (
    "brasil",
    "brazil",
    "cep",
    "r. ",
    "av. ",
    "rua ",
    "avenida ",
    " av ",
    " av. ",
    "alameda ",
    "travessa ",
    "praca ",
    "bairro",
    "jardim ",
    "centro",
)
