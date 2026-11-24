"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  DndContext, DragOverlay, KeyboardSensor, MouseSensor, TouchSensor, closestCorners, pointerWithin, rectIntersection,
  useDndContext, useDroppable, useSensor, useSensors,
  type CollisionDetection, type DragEndEvent, type DragOverEvent, type DragStartEvent
} from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { cardsInStage, moveCard } from "./board";
import { localDate, money, outcomeLabel, type Card, type Funnel, type Stage } from "./types";

const cardKey = (id: number) => `manual-card-${id}`;
const stageKey = (id: number) => `manual-stage-${id}`;

const collisionDetection: CollisionDetection = args => {
  const hits = args.pointerCoordinates ? pointerWithin(args) : rectIntersection(args);
  if (!args.pointerCoordinates && !hits.length) return closestCorners(args).slice(0, 1);
  const cards = hits.filter(hit => args.droppableContainers.find(container => container.id === hit.id)?.data.current?.type === "card");
  return cards.length ? cards : hits;
};

function DragLifecycle({ activeId, onIdle }: { activeId: number | null; onIdle: () => void }) {
  const { active } = useDndContext();
  // A very short mouse gesture can finish before dnd-kit's active snapshot is
  // committed. In that case it has no end event payload. Follow the actual
  // context too, so local feedback and the refresh guard cannot remain stuck.
  useEffect(() => {
    if (!active && activeId !== null) onIdle();
  });
  return null;
}

function CardContent({ card }: { card: Card }) {
  return <>
    <strong>{card.lead.name}</strong><span>{card.lead.niche} · {card.lead.location}</span>
    <span>{card.lead.tags.map(tag => tag.name).join(" · ")}</span>
    <span>{money(card)}</span><span>{card.sales_outcome ? outcomeLabel(card.sales_outcome) : "Legado · venda não confirmada"}</span>
    {card.next_follow_up && <small className={Date.parse(card.next_follow_up.due_at) < Date.now() ? "manual-crm-overdue" : ""}>Próximo: {card.next_follow_up.title} · {localDate(card.next_follow_up.due_at)}</small>}
  </>;
}

function SortableCard({ card, disabled, onOpen }: { card: Card; disabled: boolean; onOpen: () => void }) {
  const { setNodeRef, attributes, listeners, transform, transition, isDragging, isOver } = useSortable({
    id: cardKey(card.id), data: { type: "card", cardId: card.id, stageId: card.stage_id, funnelId: card.funnel_id }, disabled
  });
  const style: CSSProperties = {
    transform: transform ? `translate3d(${Math.round(transform.x)}px, ${Math.round(transform.y)}px, 0)` : undefined,
    transition
  };
  return <button ref={setNodeRef} style={style} type="button" disabled={disabled}
    data-card-id={card.id}
    className={`crm-lead-card crm-lead-card-button ${isDragging ? "is-dragging" : ""} ${isOver && !isDragging ? "manual-crm-card-target" : ""}`}
    {...attributes} {...listeners} aria-label={`Abrir ${card.lead.name}`} onClick={onOpen}>
    <CardContent card={card} />
  </button>;
}

function StageColumn({ stage, cards, active, over, disabled, children }: {
  stage: Stage; cards: Card[]; active: boolean; over: boolean; disabled: boolean; children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stageKey(stage.id), data: { type: "stage", stageId: stage.id, funnelId: stage.funnel_id }, disabled });
  return <section ref={setNodeRef} aria-label={`Estágio ${stage.label}`}
    data-stage-id={stage.id}
    className={`crm-column ${active ? "manual-crm-drop-ready" : ""} ${over || isOver ? "drag-over" : ""}`}>
    <div className="crm-column-heading"><h2>{stage.label}</h2><span>{cards.length}</span></div>
    <SortableContext items={cards.map(card => cardKey(card.id))} strategy={verticalListSortingStrategy}>
      <div className="crm-card-list">{children}{!cards.length && <p className="empty-state">{active ? "Solte o card aqui" : "Nenhum card neste estágio."}</p>}</div>
    </SortableContext>
  </section>;
}

export function ManualCrmBoard({ funnel, cards, disabled, onOpen, onMove, onDraggingChange }: {
  funnel: Funnel; cards: Card[]; disabled: boolean; onOpen: (id: number) => void;
  onMove: (cardId: number, stageId: number, position: number) => Promise<void>;
  onDraggingChange: (active: boolean) => void;
}) {
  const [activeId, setActiveId] = useState<number | null>(null);
  const [overStage, setOverStage] = useState<number | null>(null);
  const board = useRef<HTMLDivElement>(null);
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  useEffect(() => () => onDraggingChange(false), [onDraggingChange]);
  const active = cards.find(card => card.id === activeId);
  const reset = useCallback(() => {
    setActiveId(null); setOverStage(null);
    onDraggingChange(false);
  }, [onDraggingChange]);
  const target = (over: DragOverEvent["over"], current: Card[]) => {
    const data = over?.data.current;
    if (!data || data.funnelId !== funnel.id) return null;
    const card = data.type === "card" ? current.find(card => card.id === data.cardId) : null;
    const stage = funnel.stages.find(stage => stage.id === (card?.stage_id ?? data.stageId));
    return stage ? { stage, card } : null;
  };
  function start(event: DragStartEvent) {
    const id = event.active.data.current?.cardId;
    if (disabled || !cards.some(card => card.id === id && card.funnel_id === funnel.id)) return;
    setActiveId(id); setOverStage(null); onDraggingChange(true);
  }
  function over(event: DragOverEvent) {
    setOverStage(target(event.over, cards)?.stage.id ?? null);
  }
  async function end(event: DragEndEvent) {
    const drop = target(event.over, cards);
    const moving = cards.find(card => card.id === event.active.data.current?.cardId);
    if (disabled || !drop || !moving) { reset(); return; }
    const group = cardsInStage(cards, drop.stage.id);
    let index = drop.card ? group.findIndex(card => card.id === drop.card!.id) : group.filter(card => card.id !== moving.id).length;
    if (drop.card && moving.stage_id !== drop.stage.id && event.over && event.active.rect.current.translated) {
      if (event.active.rect.current.translated.top > event.over.rect.top + event.over.rect.height / 2) index += 1;
    }
    const result = moveCard(cards, moving.id, drop.stage, index);
    reset();
    if (result) await onMove(moving.id, drop.stage.id, result.position);
  }
  const canScroll = useCallback((element: Element) => element === board.current, []);
  return <DndContext sensors={sensors} collisionDetection={collisionDetection}
    autoScroll={{ canScroll, threshold: { x: 0.15, y: 0.08 }, acceleration: 12 }}
    onDragStart={start} onDragOver={over} onDragCancel={reset} onDragEnd={end}
    accessibility={{ screenReaderInstructions: { draggable: "Pressione espaço para arrastar. Use as setas para escolher estágio e posição, espaço para soltar e Escape para cancelar." } }}>
    <DragLifecycle activeId={activeId} onIdle={reset} />
    <div className="crm-board manual-crm-board" ref={board} aria-label="Pipeline comercial" aria-busy={disabled}>
      {[...funnel.stages].sort((a, b) => a.position - b.position || a.id - b.id).map(stage => {
        const group = cardsInStage(cards, stage.id);
        return <StageColumn stage={stage} cards={group} active={activeId !== null} over={overStage === stage.id} disabled={disabled} key={stage.id}>
          {group.map(card => <SortableCard key={card.id} card={card} disabled={disabled} onOpen={() => onOpen(card.id)} />)}
        </StageColumn>;
      })}
    </div>
    <DragOverlay dropAnimation={null}>{active && <article className="crm-lead-card crm-drag-overlay manual-crm-drag-overlay" aria-hidden="true"><CardContent card={active} /></article>}</DragOverlay>
  </DndContext>;
}
