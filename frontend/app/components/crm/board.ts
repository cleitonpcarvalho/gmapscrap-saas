import type { Card, Funnel, Stage } from "./types";

export function cardsInStage(cards: Card[], stageId: number) {
  return cards.filter(card => card.stage_id === stageId).sort((a, b) =>
    (a.position ?? Number.MAX_SAFE_INTEGER) - (b.position ?? Number.MAX_SAFE_INTEGER) || a.id - b.id);
}

export function validatePipeline(cards: Card[], funnel: Funnel) {
  const ids = new Set<number>();
  const stages = new Set(funnel.stages.map(stage => stage.id));
  for (const card of cards) {
    if (ids.has(card.id) || card.funnel_id !== funnel.id || !stages.has(card.stage_id)) {
      throw new Error("O funil mudou durante a atualização. Atualize o CRM antes de mover os cards.");
    }
    ids.add(card.id);
  }
  return cards;
}

/** Change only stage/order; commercial details remain the original objects. */
export function moveCard(cards: Card[], cardId: number, stage: Stage, position: number) {
  const moving = cards.find(card => card.id === cardId);
  if (!moving || moving.funnel_id !== stage.funnel_id || !Number.isInteger(position) || position < 0) return null;
  const source = cardsInStage(cards, moving.stage_id);
  const target = cardsInStage(cards, stage.id).filter(card => card.id !== cardId);
  const bounded = Math.min(position, target.length);
  if (moving.stage_id === stage.id && source.findIndex(card => card.id === cardId) === bounded) return null;
  target.splice(bounded, 0, { ...moving, stage_id: stage.id, stage_label: stage.label, stage_color: stage.color });
  const updated = new Map<number, Card>();
  if (moving.stage_id !== stage.id) source.filter(card => card.id !== cardId).forEach((card, index) => updated.set(card.id, { ...card, position: index }));
  target.forEach((card, index) => updated.set(card.id, { ...card, position: index }));
  return { cards: cards.map(card => updated.get(card.id) || card), position: bounded };
}
