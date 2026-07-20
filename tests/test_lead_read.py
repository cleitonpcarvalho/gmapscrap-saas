from datetime import datetime, timezone

from backend.models import Lead, SearchRun
from backend.schemas import LeadRead


def _lead_for_run(validate_whatsapp: bool) -> Lead:
    run = SearchRun(
        id=1,
        niche="Marketing",
        location="São Paulo",
        target_quantity=10,
        max_results=False,
        skip_without_website=True,
        validate_whatsapp=validate_whatsapp,
        status="completed",
        message="Busca concluída.",
    )
    return Lead(
        id=1,
        run_id=1,
        search_run=run,
        name="Empresa",
        address="Av. Paulista, 1000 - São Paulo, SP",
        phone="(11) 99577-9865",
        website="https://example.com",
        email="contato@example.com",
        created_at=datetime.now(timezone.utc),
    )


def test_lead_read_includes_whatsapp_url_when_run_validated_whatsapp() -> None:
    result = LeadRead.model_validate(_lead_for_run(validate_whatsapp=True))

    assert result.validate_whatsapp is True
    assert result.whatsapp_url == "https://wa.me/5511995779865"


def test_lead_read_omits_whatsapp_url_when_run_did_not_validate_whatsapp() -> None:
    result = LeadRead.model_validate(_lead_for_run(validate_whatsapp=False))

    assert result.validate_whatsapp is False
    assert result.whatsapp_url == ""
