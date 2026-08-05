from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import WhatsAppCampaign, WhatsAppInstance
from backend.services.whatsapp_providers.evolution import EvolutionApiError, EvolutionProvider

logger = logging.getLogger(__name__)

DISCONNECTED_REASON = "Instância de WhatsApp desconectada."


def pause_running_campaigns_for_instance(db: Session, instance: WhatsAppInstance) -> int:
    """Pauses campaigns still marked as running against a disconnected instance so they
    stop accumulating failed sends until someone reconnects the instance and resumes them."""
    campaigns = list(
        db.scalars(
            select(WhatsAppCampaign).where(
                WhatsAppCampaign.instance_id == instance.id,
                WhatsAppCampaign.status == "running",
            )
        )
    )
    for campaign in campaigns:
        campaign.status = "paused"
        campaign.error = DISCONNECTED_REASON
        campaign.message = f"Campanha pausada automaticamente: {DISCONNECTED_REASON.lower()}"
    return len(campaigns)


def refresh_instance_status(db: Session, instance: WhatsAppInstance, provider: EvolutionProvider) -> str | None:
    """Asks the Evolution API directly for this instance's connection state and updates
    whatsapp_instances.status accordingly, instead of relying on whatever was last
    observed the last time someone opened the instances screen. Returns Evolution's raw
    provider_state, or None if Evolution could not be reached (status is left untouched
    rather than guessed from a failed request).
    """
    # Imported lazily (not at module level) to avoid a circular import: backend.main
    # imports the campaign scheduler that calls into this module at startup, and this
    # function reuses main's provider-state parsing so the periodic check and the
    # manual "check status" endpoint can never drift apart.
    from backend import main as backend_main

    provider_id = (instance.evolution_instance_name or instance.name or "").strip()
    if not provider_id:
        return None

    try:
        provider_response = provider.get_connection_status(provider_id)
    except EvolutionApiError:
        logger.warning(
            "Falha ao checar status automático da instância WhatsApp %s (id=%s) na Evolution",
            instance.name,
            instance.id,
        )
        return None

    provider_state = backend_main._update_whatsapp_instance_status(instance, provider_response)

    if instance.status != "connected":
        paused = pause_running_campaigns_for_instance(db, instance)
        if paused:
            logger.warning(
                "Instância WhatsApp %s (id=%s) está %s: %s campanha(s) pausada(s) automaticamente.",
                instance.name,
                instance.id,
                instance.status,
                paused,
            )

    return provider_state


def refresh_all_instance_statuses() -> None:
    """Periodic entry point: checks every WhatsApp instance against Evolution and
    persists the real status, run on the same interval loop as the campaign scheduler."""
    db = SessionLocal()
    try:
        instances = list(db.scalars(select(WhatsAppInstance)))
        if not instances:
            return

        provider = EvolutionProvider()
        for instance in instances:
            try:
                refresh_instance_status(db, instance, provider)
            except Exception:
                logger.exception(
                    "Erro inesperado ao atualizar status automático da instância WhatsApp %s", instance.id
                )
                db.rollback()

        db.commit()
    finally:
        db.close()
