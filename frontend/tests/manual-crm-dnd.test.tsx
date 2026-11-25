import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ManualCrmWorkspace } from "../app/components/crm/ManualCrmWorkspace";
import { cardsInStage, moveCard, validatePipeline } from "../app/components/crm/board";
import type { Card, Funnel, Request } from "../app/components/crm/types";

const stages = [
  { id: 1, funnel_id: 1, key: "new", label: "Novo", color: "#fff", position: 0 },
  { id: 2, funnel_id: 1, key: "qualified", label: "Qualificado", color: "#fff", position: 1 },
  { id: 3, funnel_id: 1, key: "won", label: "Ganho", color: "#fff", position: 2 }
];
const funnel: Funnel = { id: 1, name: "Comercial", stages };
const other: Funnel = { id: 2, name: "Outro funil", stages: [{ ...stages[0], id: 4, funnel_id: 2 }] };
function card(id: number, stageId = 1, position = 0): Card {
  return { id, funnel_id: 1, funnel_name: "Comercial", stage_id: stageId, stage_label: stages[stageId - 1].label,
    stage_color: "#fff", position, version: 1, managed_manually: true, qualification_notes: "Nota intacta",
    estimated_value: "1250.50", currency: "BRL", sales_outcome: "open", lost_reason: null, closed_at: null,
    lead: { id, name: `Empresa ${id}`, niche: "Brindes", location: "Fortaleza", address: "Centro", phone: "", email: "", website: "", call_url: "", whatsapp_url: "", tags: [], provenance: { run_id: 1, niche: "Brindes", location: "Fortaleza", status: "completed", created_at: "2026-11-22T12:00:00Z" } },
    next_follow_up: { id: 10 + id, card_id: id, title: "Retornar", due_at: "2026-12-01T12:00:00Z", status: "pending", version: 1 },
    activities: [{ id: 90, kind: "note", body: "Histórico preservado", actor: "manual", created_at: "2026-11-22T12:00:00Z" }], follow_ups: [], stage_history: [] };
}
const rect = (left: number, top: number, width: number, height: number) => ({ left, top, right: left + width, bottom: top + height, width, height, x: left, y: top, toJSON() { return {}; } });

beforeEach(() => {
  // jsdom has no layout. Give real dnd-kit sensors/sortables measurable columns
  // and cards; neither DndContext nor the mutation callback is mocked.
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.classList.contains("manual-crm-board") && this.style.width) return rect(0, 100, parseFloat(this.style.width), 700) as DOMRect;
    if (this.classList.contains("crm-drag-overlay")) {
      return document.querySelector<HTMLElement>("[data-card-id].is-dragging")!.getBoundingClientRect();
    }
    if (this.style.position === "fixed" && this.style.width && this.style.height) {
      return rect(parseFloat(this.style.left) || 0, parseFloat(this.style.top) || 0,
        parseFloat(this.style.width), parseFloat(this.style.height)) as DOMRect;
    }
    const column = this.closest<HTMLElement>("[data-stage-id]");
    const left = column ? (Number(column.dataset.stageId) - 1) * 280 : 0;
    if (this.dataset.stageId) return rect(left, 100, 250, 700) as DOMRect;
    if (this.dataset.cardId) {
      const group = [...column!.querySelectorAll("[data-card-id]")];
      return rect(left + 15, 150 + group.indexOf(this) * 140, 220, 120) as DOMRect;
    }
    return rect(0, 0, 1000, 1000) as DOMRect;
  });
  HTMLElement.prototype.scrollIntoView = vi.fn();
});

function setup(initial = [card(1), card(2, 1, 1)], after = initial) {
  let server = initial;
  let patch: ((init: RequestInit) => Promise<Card>) | undefined;
  let read: (() => Promise<Card[]>) | undefined;
  const spy = vi.fn(async (path: string, init?: RequestInit): Promise<unknown> => {
    if (path === "/api/crm/funnels") return [funnel, other];
    if (path.includes("follow-ups?")) return [];
    if (init?.method === "PATCH") {
      if (patch) return patch(init);
      server = after;
      return server.find(item => path.endsWith(`/${item.id}`))!;
    }
    if (path.includes("cards?funnel_id=2")) return [];
    if (path.includes("cards?")) return read ? read() : structuredClone(server);
    throw Error(`Unexpected API call: ${path}`);
  });
  render(<ManualCrmWorkspace request={spy as Request} onManageFunnels={vi.fn()} />);
  return { spy, setServer: (values: Card[]) => { server = values; }, setPatch: (callback: typeof patch) => { patch = callback; }, setRead: (callback: typeof read) => { read = callback; } };
}
const buttons = (label: string) => within(screen.getByRole("region", { name: `Estágio ${label}` })).queryAllByRole("button").map(item => item.getAttribute("aria-label"));
async function drag(name: string, arrows: string) {
  const user = userEvent.setup();
  const button = await screen.findByRole("button", { name: `Abrir ${name}` });
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
  button.focus();
  await user.keyboard("[Space]");
  await waitFor(() => expect(document.querySelector(".crm-drag-overlay")).not.toBeNull());
  if (arrows) await user.keyboard(arrows);
  return user;
}
const patches = (spy: ReturnType<typeof vi.fn>) => spy.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "PATCH");
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("commercial drag-and-drop", () => {
  it("clears feedback and resumes refresh after a gesture ends before the sensor commits", async () => {
    const { spy } = setup([card(1)]);
    const button = await screen.findByRole("button", { name: "Abrir Empresa 1" });
    act(() => {
      fireEvent.mouseDown(button, { button: 0, buttons: 1, clientX: 50, clientY: 180 });
      fireEvent.mouseMove(document, { buttons: 1, clientX: 320, clientY: 180 });
      fireEvent.mouseUp(document, { button: 0, buttons: 0, clientX: 320, clientY: 180 });
    });
    await waitFor(() => expect(document.querySelector(".manual-crm-drop-ready")).toBeNull());
    expect(document.querySelector(".crm-drag-overlay")).toBeNull();
    const before = spy.mock.calls.length;
    // dnd-kit suppresses clicks for 50 ms after a mouse drag so the release
    // cannot open a card. A subsequent user click happens after that window.
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 60)); });
    await userEvent.click(screen.getByRole("button", { name: "Atualizar CRM" }));
    await waitFor(() => expect(spy.mock.calls.length).toBeGreaterThan(before));
  });

  it("moves with the mouse without opening the details dialog after dropping", async () => {
    const { spy } = setup([card(1)], [{ ...card(1, 2), version: 2 }]);
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: "Abrir Empresa 1" });
    await user.pointer([{ keys: "[MouseLeft>]", target: button, coords: { clientX: 50, clientY: 180 } },
      { target: button, coords: { clientX: 100, clientY: 180 } },
      { target: screen.getByRole("region", { name: "Estágio Qualificado" }), coords: { clientX: 320, clientY: 180 } }]);
    expect(document.querySelector(".crm-drag-overlay")).not.toBeNull();
    await user.pointer({ keys: "[/MouseLeft]", coords: { clientX: 320, clientY: 180 } });
    await screen.findByText("Card atualizado.");
    expect(patches(spy)).toHaveLength(1);
    expect(buttons("Qualificado")).toEqual(["Abrir Empresa 1"]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("auto-scrolls horizontally near an edge while dragging and cancels without an update", async () => {
    const { spy } = setup([card(1)]);
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: "Abrir Empresa 1" });
    const board = screen.getByLabelText("Pipeline comercial");
    board.style.width = "500px"; board.style.overflowX = "auto";
    Object.defineProperties(board, { clientWidth: { value: 500 }, scrollWidth: { value: 1500 }, clientHeight: { value: 700 }, scrollHeight: { value: 700 } });
    board.scrollBy = vi.fn((x?: number | ScrollToOptions) => { board.scrollLeft += typeof x === "number" ? x : x?.left || 0; });
    await user.pointer([{ keys: "[MouseLeft>]", target: button, coords: { clientX: 50, clientY: 300 } },
      { target: button, coords: { clientX: 100, clientY: 300 } },
      { target: board, coords: { clientX: 495, clientY: 300 } }]);
    await waitFor(() => expect(board.scrollLeft).toBeGreaterThan(0));
    expect(board.scrollBy).toHaveBeenCalled();
    await user.keyboard("[Escape]");
    await user.pointer({ keys: "[/MouseLeft]" });
    expect(patches(spy)).toHaveLength(0);
  });

  it("moves to an empty stage through the existing versioned API, preserving commercial fields", async () => {
    const first = card(1);
    const updated = { ...first, stage_id: 2, stage_label: "Qualificado", position: 0, version: 2 };
    const { spy } = setup([first], [updated]);
    const user = await drag("Empresa 1", "[ArrowRight]");
    expect(screen.getByRole("region", { name: "Estágio Qualificado" }).classList.contains("drag-over")).toBe(true);
    await user.keyboard("[Space]");
    await screen.findByText("Card atualizado.");
    expect(buttons("Novo")).toEqual([]);
    expect(buttons("Qualificado")).toEqual(["Abrir Empresa 1"]);
    const calls = patches(spy);
    expect(calls).toHaveLength(1);
    expect(calls[0][0]).toBe("/api/crm/manual/cards/1");
    expect(JSON.parse(String(calls[0][1]!.body))).toEqual({ version: 1, stage_id: 2, position: 0 });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("reorders within the same stage and uses canonical neighbor versions on the next move", async () => {
    const { spy } = setup([card(1), card(2, 1, 1)], [{ ...card(2), version: 2 }, { ...card(1, 1, 1), version: 2 }]);
    const user = await drag("Empresa 1", "[ArrowDown]");
    await user.keyboard("[Space]");
    await screen.findByText("Card atualizado.");
    expect(buttons("Novo")).toEqual(["Abrir Empresa 2", "Abrir Empresa 1"]);
    expect(JSON.parse(String(patches(spy)[0][1]!.body))).toEqual({ version: 1, stage_id: 1, position: 1 });
    const next = await drag("Empresa 2", "[ArrowRight]");
    await next.keyboard("[Space]");
    await waitFor(() => expect(patches(spy)).toHaveLength(2));
    expect(JSON.parse(String(patches(spy)[1][1]!.body)).version).toBe(2);
  });

  it("cancels a drag and ignores a drop in the original position", async () => {
    const { spy } = setup();
    const user = await drag("Empresa 1", "[ArrowRight]");
    await user.keyboard("[Escape]");
    expect(buttons("Novo")).toEqual(["Abrir Empresa 1", "Abrir Empresa 2"]);
    expect(patches(spy)).toHaveLength(0);
    const again = await drag("Empresa 1", "");
    await again.keyboard("[Space]");
    expect(patches(spy)).toHaveLength(0);
    expect(document.querySelector(".crm-drag-overlay")).toBeNull();
  });

  it.each(["API indisponível", "O card foi alterado. Atualize antes de salvar."])("rolls back failed or conflicting moves: %s", async failure => {
    const { spy, setPatch } = setup();
    setPatch(async () => { throw Error(failure); });
    const user = await drag("Empresa 1", "[ArrowRight]");
    await user.keyboard("[Space]");
    expect((await screen.findByRole("alert")).textContent).toContain(failure);
    expect(buttons("Novo")).toEqual(["Abrir Empresa 1", "Abrir Empresa 2"]);
    expect(buttons("Qualificado")).toEqual([]);
    expect(patches(spy)).toHaveLength(1);
    expect((screen.getByRole("button", { name: "Abrir Empresa 1" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "Atualizar CRM" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Abrir Empresa 1" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("shows the optimistic move but blocks duplicate updates until reconciliation finishes", async () => {
    const { spy, setPatch, setServer } = setup([card(1)]);
    const pending = deferred<Card>();
    const updated = { ...card(1, 2), version: 2 };
    setPatch(() => pending.promise);
    const user = await drag("Empresa 1", "[ArrowRight]");
    await user.keyboard("[Space]");
    await screen.findByText("Salvando movimento…");
    expect(buttons("Qualificado")).toEqual(["Abrir Empresa 1"]);
    expect((screen.getByLabelText("Funil") as HTMLSelectElement).disabled).toBe(true);
    const button = screen.getByRole("button", { name: "Abrir Empresa 1" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    button.focus(); await user.keyboard("[Space][ArrowRight][Space]");
    expect(patches(spy)).toHaveLength(1);
    setServer([updated]);
    await act(async () => pending.resolve(updated));
    await screen.findByText("Card atualizado.");
    expect(buttons("Qualificado")).toEqual(["Abrir Empresa 1"]);
  });

  it("keeps a committed move when the follow-up read fails and requires a fresh pipeline", async () => {
    const { setPatch, setRead } = setup([card(1)]);
    const updated = { ...card(1, 2), version: 2 };
    await screen.findByRole("button", { name: "Abrir Empresa 1" });
    setPatch(async () => updated);
    setRead(async () => { throw Error("read unavailable"); });
    const user = await drag("Empresa 1", "[ArrowRight]");
    await user.keyboard("[Space]");
    expect((await screen.findByRole("alert")).textContent).toContain("Movimento salvo");
    expect(buttons("Novo")).toEqual([]);
    expect(buttons("Qualificado")).toEqual(["Abrir Empresa 1"]);
    setRead(async () => [updated]);
    await user.click(screen.getByRole("button", { name: "Atualizar CRM" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Abrir Empresa 1" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("discards a refresh already in flight and does not poll during a gesture", async () => {
    const { spy, setRead } = setup();
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "Abrir Empresa 1" });
    const pending = deferred<Card[]>();
    setRead(() => pending.promise);
    await user.click(screen.getByRole("button", { name: "Atualizar CRM" }));
    const count = spy.mock.calls.length;
    const gesture = await drag("Empresa 1", "[ArrowRight]");
    await user.click(screen.getByRole("button", { name: "Atualizar CRM" }));
    expect(spy.mock.calls.length).toBe(count);
    await act(async () => pending.resolve([]));
    expect(buttons("Novo")).toEqual(["Abrir Empresa 1", "Abrir Empresa 2"]);
    await gesture.keyboard("[Escape]");
  });

  it("never installs an old pipeline response after switching pipelines", async () => {
    const { setRead } = setup();
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "Abrir Empresa 1" });
    const pending = deferred<Card[]>();
    setRead(() => pending.promise);
    await user.click(screen.getByRole("button", { name: "Atualizar CRM" }));
    await user.selectOptions(screen.getByLabelText("Funil"), "2");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Abrir Empresa 1" })).toBeNull());
    await act(async () => pending.resolve([card(1)]));
    expect(screen.queryByRole("button", { name: "Abrir Empresa 1" })).toBeNull();
    expect(screen.getByRole("region", { name: "Estágio Novo" }).getAttribute("data-stage-id")).toBe("4");
  });
});

describe("pipeline move planning", () => {
  it("keeps all commercial data and compacts source/destination order without mutating inputs", () => {
    const source = [card(1), card(2, 1, 1), card(3, 2, 0), card(4, 2, 1)];
    const before = structuredClone(source);
    const result = moveCard(source, 2, stages[1], 1)!;
    expect(cardsInStage(result.cards, 1).map(item => [item.id, item.position])).toEqual([[1, 0]]);
    expect(cardsInStage(result.cards, 2).map(item => [item.id, item.position])).toEqual([[3, 0], [2, 1], [4, 2]]);
    const moved = result.cards.find(item => item.id === 2)!;
    for (const field of ["qualification_notes", "activities", "follow_ups", "next_follow_up", "estimated_value", "sales_outcome", "version"] as const) expect(moved[field]).toBe(source[1][field]);
    expect(source).toEqual(before);
  });
  it("rejects foreign stages, invalid indices, duplicate cards and cross-pipeline responses", () => {
    const values = [card(1)];
    expect(moveCard(values, 1, other.stages[0], 0)).toBeNull();
    expect(moveCard(values, 1, stages[1], -1)).toBeNull();
    expect(moveCard(values, 1, stages[1], NaN)).toBeNull();
    expect(() => validatePipeline([...values, ...values], funnel)).toThrow();
    expect(() => validatePipeline([{ ...card(1), funnel_id: 2 }], funnel)).toThrow();
    expect(() => validatePipeline([{ ...card(1), stage_id: 4 }], funnel)).toThrow();
  });
});
