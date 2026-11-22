"""Atomic stage/pipeline removal without detaching or replacing CRM cards."""
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.models import CrmActivity, CrmFunnel, CrmFunnelStage, CrmLead, CrmStageHistory


@contextmanager
def _transaction(db: Session):
    try:
        yield
        db.commit()
    except (IntegrityError, StaleDataError) as exc:
        db.rollback()
        raise HTTPException(409, "Os cards ou seus vínculos mudaram. Atualize o CRM e tente novamente.") from exc
    except OperationalError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) in {"40P01", "40001", "55P03"}:
            raise HTTPException(409, "Outra operação alterou o CRM. Atualize e tente novamente.") from exc
        raise
    except Exception:
        db.rollback()
        raise


def _lock_pipelines(db, ids):
    # Deterministic parent locks serialize opposite transfers and membership
    # inserts (including the manual bulk-add workflow and FK checks).
    pipelines = db.scalars(select(CrmFunnel).where(CrmFunnel.id.in_(set(ids)))
                          .order_by(CrmFunnel.id).with_for_update(of=CrmFunnel)).all()
    return {item.id: item for item in pipelines}


def _lock_cards_and_stages(db, pipeline_ids):
    # Lock cards before stages to allow an already-running card edit to finish.
    cards = list(db.scalars(select(CrmLead).where(CrmLead.funnel_id.in_(pipeline_ids))
                            .order_by(CrmLead.id).with_for_update(of=CrmLead)).all())
    stages = list(db.scalars(select(CrmFunnelStage).where(CrmFunnelStage.funnel_id.in_(pipeline_ids))
                             .order_by(CrmFunnelStage.id).with_for_update(of=CrmFunnelStage)).all())
    return cards, stages


def _stage_order(stage):
    return stage.position, stage.id


def _card_order(card):
    return card.position is None, card.position if card.position is not None else 0, card.id


def _transfer(db, card, pipeline, stage, position, actor):
    previous_pipeline = card.funnel
    previous_stage = card.stage_ref
    snapshot = {
        "from_funnel": {"id": previous_pipeline.id, "name": previous_pipeline.name},
        "to_funnel": {"id": pipeline.id, "name": pipeline.name},
        "from_stage": {"id": previous_stage.id, "key": previous_stage.key, "label": previous_stage.label},
        "to_stage": {"id": stage.id, "key": stage.key, "label": stage.label},
    }
    db.add(CrmStageHistory(crm_lead_id=card.id, from_stage=previous_stage.key,
                           to_stage=stage.key, from_stage_id=previous_stage.id,
                           to_stage_id=stage.id, changed_by="manual"))
    if card.managed_manually:
        db.add(CrmActivity(
            crm_lead_id=card.id, kind="system", actor=actor,
            created_at=datetime.now(timezone.utc), details=snapshot,
            body=f"Oportunidade transferida: {previous_pipeline.name} / {previous_stage.label} → {pipeline.name} / {stage.label}.",
        ))
    # Changing just *_id leaves loaded back_populates collections stale. Parent
    # deletion would then null the required FK. Synchronize both relationships.
    card.funnel = pipeline
    card.stage_ref = stage
    card.stage = stage.key
    card.position = position


def delete_pipeline(db: Session, pipeline_id: int, destination_id: int | None, *, actor: str) -> int:
    with _transaction(db):
        pipelines = _lock_pipelines(db, [pipeline_id] + ([destination_id] if destination_id is not None else []))
        source = pipelines.get(pipeline_id)
        if source is None:
            raise HTTPException(404, "Funil não encontrado")
        if source.is_default:
            raise HTTPException(409, "O funil padrão não pode ser excluído.")
        if destination_id == pipeline_id:
            raise HTTPException(422, "Escolha um funil de destino diferente.")
        destination = pipelines.get(destination_id)
        if destination_id is not None and destination is None:
            raise HTTPException(404, "Funil de destino não encontrado")
        cards, stages = _lock_cards_and_stages(db, list(pipelines))
        source_cards = [card for card in cards if card.funnel_id == source.id]
        if source_cards and destination is None:
            raise HTTPException(409, f"Este funil contém {len(source_cards)} cards. Informe um funil de destino para movê-los antes de excluir.")
        if source_cards:
            target_stages = sorted((stage for stage in stages if stage.funnel_id == destination.id), key=_stage_order)
            if not target_stages:
                raise HTTPException(409, "Funil de destino sem estágios.")
            target_cards = [card for card in cards if card.funnel_id == destination.id]
            occupied_leads = {card.lead_id for card in target_cards}
            conflicts = [card.lead_id for card in source_cards if card.lead_id in occupied_leads]
            if conflicts:
                # Never merge or discard either opportunity or its history.
                raise HTTPException(409, f"{len(conflicts)} leads já têm card no funil de destino. Resolva esses cards antes de mover.")
            by_key = {stage.key: stage for stage in target_stages}
            positions = {stage.id: max((card.position for card in target_cards
                                       if card.stage_id == stage.id and card.position is not None), default=-1) + 1
                         for stage in target_stages}
            for card in sorted(source_cards, key=lambda item: (_stage_order(item.stage_ref), _card_order(item))):
                next_stage = by_key.get(card.stage) or target_stages[0]
                _transfer(db, card, destination, next_stage, positions[next_stage.id], actor)
                positions[next_stage.id] += 1
            # Persist every move/history entry before cascading source stages.
            db.flush()
        db.delete(source)
        db.flush()
        return len(source_cards)


def delete_stage(db: Session, pipeline_id: int, stage_id: int, destination_id: int | None, *, actor: str) -> int:
    with _transaction(db):
        pipelines = _lock_pipelines(db, [pipeline_id])
        pipeline = pipelines.get(pipeline_id)
        if pipeline is None:
            raise HTTPException(404, "Estágio não encontrado")
        cards, stages = _lock_cards_and_stages(db, [pipeline_id])
        by_id = {stage.id: stage for stage in stages}
        source = by_id.get(stage_id)
        if source is None:
            raise HTTPException(404, "Estágio não encontrado")
        if len(stages) <= 1:
            raise HTTPException(409, "Todo funil precisa ter pelo menos um estágio.")
        if destination_id == stage_id:
            raise HTTPException(422, "Escolha um estágio de destino diferente.")
        destination = by_id.get(destination_id)
        if destination_id is not None and destination is None:
            raise HTTPException(404, "Estágio de destino não encontrado")
        source_cards = sorted((card for card in cards if card.stage_id == stage_id), key=_card_order)
        if source_cards and destination is None:
            raise HTTPException(409, f"Este estágio contém {len(source_cards)} cards. Informe um estágio de destino para movê-los antes de excluir.")
        if source_cards:
            position = max((card.position for card in cards if card.stage_id == destination.id
                            and card.position is not None), default=-1) + 1
            for card in source_cards:
                _transfer(db, card, pipeline, destination, position, actor)
                position += 1
            db.flush()
        # Removing the orphan also updates the loaded parent stage collection;
        # a later pipeline deletion in the same session must not delete it twice.
        pipeline.stages.remove(source)
        db.flush()
        # Close the stage-order gap; existing destination card order stays intact.
        for position, stage in enumerate(sorted((stage for stage in stages if stage.id != stage_id), key=_stage_order)):
            stage.position = position
        return len(source_cards)
