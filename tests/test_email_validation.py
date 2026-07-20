from backend.services.email_validation import select_best_email, validate_email_address
from backend.services.whatsapp_validation import normalize_phone_e164


def test_placeholder_email_is_invalid_without_dns_check() -> None:
    result = validate_email_address("john@smith.com", check_dns=False)

    assert result.status == "invalid"
    assert "placeholder" in result.reasons


def test_regular_email_can_validate_without_dns_check() -> None:
    result = validate_email_address("Contato@AutomaSoluct.com.br", "https://automasoluct.com.br", check_dns=False)

    assert result.status == "valid"
    assert result.normalized_email == "contato@automasoluct.com.br"
    assert result.domain_matches_website is True


def test_select_best_email_prefers_site_domain() -> None:
    result = select_best_email(
        ["empresa@gmail.com", "contato@empresa.com.br"],
        "https://empresa.com.br",
        check_dns=False,
    )

    assert result is not None
    assert result.normalized_email == "contato@empresa.com.br"


def test_phone_normalization_for_brazil() -> None:
    assert normalize_phone_e164("(85) 99999-9999", "Fortaleza, Ceara, Brasil") == "+5585999999999"


def test_phone_normalization_infers_brazil_from_sao_paulo_location() -> None:
    assert normalize_phone_e164("(11) 99999-9999", "São Paulo, SP") == "+5511999999999"


def test_phone_normalization_infers_brazil_from_cep() -> None:
    assert normalize_phone_e164("(11) 3333-4444", "Av. Paulista, 1000 - 01310-100") == "+551133334444"
