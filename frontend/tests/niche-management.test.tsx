import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NicheManager, type Niche, type NicheRequest } from "../app/components/NicheManager";
import Home from "../app/page";

const first: Niche = { id: 1, name: "Brindes", created_at: "2026-11-19T18:00:00Z" };
const second: Niche = { id: 2, name: "Clínicas", created_at: first.created_at };

function setup(initial: Niche[] = [first, second], variant: "page" | "dialog" = "page") {
  let store = [...initial];
  const onSelect = vi.fn();
  const onClose = vi.fn();
  const request = vi.fn(async (path: string, init?: RequestInit): Promise<unknown> => {
    const method = init?.method || "GET";
    if (method === "GET") return [...store];
    if (method === "DELETE") { store = store.filter((item) => path !== `/api/niches/${item.id}`); return { deleted: true }; }
    const name = JSON.parse(String(init?.body)).name as string;
    const id = method === "PATCH" ? Number(path.split("/").at(-1)) : 3;
    const item = { id, name, created_at: first.created_at };
    store = [...store.filter((row) => row.id !== id), item];
    return item;
  });
  function Harness() {
    const [items, setItems] = useState(initial);
    return <><datalist id="registered-niches">{items.map((item) => <option key={item.id} value={item.name} />)}</datalist>
      <NicheManager variant={variant} niches={items} request={request as NicheRequest} onChange={setItems} onSelect={onSelect} onClose={onClose} />
    </>;
  }
  render(<Harness />);
  return { user: userEvent.setup(), request, onSelect, onClose };
}

async function ready() {
  await waitFor(() => expect((screen.getByRole("button", { name: "Atualizar nichos" }) as HTMLButtonElement).disabled).toBe(false));
}

describe("dedicated niche manager", () => {
  it("filters the list by case-insensitive substring and distinguishes an empty result", async () => {
    const { user } = setup();
    await ready();
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Buscar nichos" }), "LÍN");
    expect(screen.getByRole("button", { name: "Editar Clínicas" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Editar Brindes" })).toBeNull();
    await user.clear(screen.getByRole("textbox", { name: "Buscar nichos" }));
    await user.type(screen.getByRole("textbox", { name: "Buscar nichos" }), "no match");
    expect(screen.getByText("Nenhum nicho encontrado")).toBeTruthy();
  });

  it("creates through the shared API, normalizes whitespace, and updates autocomplete without navigating away", async () => {
    const { user, request, onSelect } = setup([]);
    await ready();
    await user.type(screen.getByRole("textbox", { name: "Nome do nicho" }), "  Novos   Nichos  ");
    await user.click(screen.getByRole("button", { name: "Adicionar nicho" }));
    expect(request).toHaveBeenCalledWith("/api/niches", { method: "POST", body: JSON.stringify({ name: "Novos Nichos" }) });
    await screen.findByRole("button", { name: "Editar Novos Nichos" });
    expect(document.querySelector('datalist option[value="Novos Nichos"]')).toBeTruthy();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("edits the selected record only and keeps the registry in sync", async () => {
    const { user, request } = setup();
    await ready();
    await user.click(screen.getByRole("button", { name: "Editar Brindes" }));
    await user.clear(screen.getByRole("textbox", { name: "Nome do nicho" }));
    await user.type(screen.getByRole("textbox", { name: "Nome do nicho" }), "Presentes");
    await user.click(screen.getByRole("button", { name: "Salvar alterações" }));
    expect(request).toHaveBeenCalledWith("/api/niches/1", { method: "PATCH", body: JSON.stringify({ name: "Presentes" }) });
    await screen.findByRole("button", { name: "Editar Presentes" });
    expect(screen.getByRole("button", { name: "Editar Clínicas" })).toBeTruthy();
  });

  it("does not delete until confirmed and supports cancelling confirmation", async () => {
    const { user, request } = setup();
    await ready();
    await user.click(screen.getByRole("button", { name: "Excluir Brindes" }));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(request.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Cancelar exclusão" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Excluir Brindes" }));
    await user.click(screen.getByRole("button", { name: "Confirmar exclusão" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Editar Brindes" })).toBeNull());
    expect(request).toHaveBeenCalledWith("/api/niches/1", { method: "DELETE" });
    expect(document.querySelector('datalist option[value="Brindes"]')).toBeNull();
    expect(request.mock.calls.every(([path]) => path.startsWith("/api/niches"))).toBe(true);
  });

  it("preserves the editor and existing list when the API rejects a duplicate", async () => {
    const { user, request } = setup();
    await ready();
    request.mockRejectedValueOnce(new Error("Já existe um nicho com esse nome."));
    await user.type(screen.getByRole("textbox", { name: "Nome do nicho" }), "BRINDES");
    await user.click(screen.getByRole("button", { name: "Adicionar nicho" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Já existe");
    expect((screen.getByRole("textbox", { name: "Nome do nicho" }) as HTMLInputElement).value).toBe("BRINDES");
    expect(screen.getByRole("button", { name: "Editar Brindes" })).toBeTruthy();
  });

  it("retains a successful create if the subsequent refresh fails", async () => {
    const { user, request } = setup([]);
    await ready();
    request.mockResolvedValueOnce({ ...first, name: "Novo" }).mockRejectedValueOnce(new Error("Refresh failed"));
    await user.type(screen.getByRole("textbox", { name: "Nome do nicho" }), "Novo");
    await user.click(screen.getByRole("button", { name: "Adicionar nicho" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Refresh failed");
    expect(screen.getByRole("button", { name: "Editar Novo" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Nicho salvo");
  });

  it("keeps the quick manager usable and fills the search field after creation", async () => {
    const { user, onSelect, onClose } = setup([], "dialog");
    await ready();
    expect(screen.getByRole("dialog", { name: "Gerenciar nichos" })).toBeTruthy();
    await user.type(screen.getByRole("textbox", { name: "Nome do nicho" }), "Novo");
    await user.click(screen.getByRole("button", { name: "Adicionar nicho" }));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("Novo"));
    await user.click(screen.getByRole("button", { name: "Usar na busca" }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("niche page navigation and centralized search suggestions", () => {
  it("opens /nichos directly, places Nichos after Listas, and preserves free-text searches", async () => {
    window.history.replaceState(null, "", "/nichos");
    let registry = [first];
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      const path = new URL(String(url), window.location.origin).pathname;
      let data: unknown = [];
      if (path === "/api/auth/session") data = { authenticated: true, username: "local-test" };
      else if (path === "/api/stats") data = { total_leads: 0, total_with_email: 0, running_jobs: 0, completed_jobs: 0 };
      else if (path === "/api/niches") data = registry;
      else if (path === "/api/whatsapp/ai-settings" || path === "/api/email/smtp") data = {};
      else if (path === "/api/leads/validate-whatsapp/progress") data = { status: "idle" };
      return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json", "X-Total-Count": "0" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Home />);
    await screen.findByRole("heading", { name: "Nichos", level: 1 });
    const names = within(screen.getByRole("navigation")).getAllByRole("button").map((button) => button.textContent);
    expect(names[names.indexOf("Listas") + 1]).toBe("Nichos");
    expect(screen.getByRole("button", { name: "Nichos" }).getAttribute("aria-current")).toBe("page");
    await screen.findByRole("button", { name: "Editar Brindes" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Usar na busca" }));
    const input = screen.getByRole("combobox", { name: "Nicho" }) as HTMLInputElement;
    expect(input.value).toBe("Brindes");
    expect(input.getAttribute("list")).toBe("registered-niches");
    expect(document.querySelector('datalist option[value="Brindes"]')).toBeTruthy();
    await user.clear(input);
    await user.type(input, "Nicho livre não cadastrado");
    expect(input.value).toBe("Nicho livre não cadastrado");
    expect(window.location.hash).toBe("#busca");
    registry = [second];
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(document.querySelector('datalist option[value="Clínicas"]')).toBeTruthy());
    expect(input.value).toBe("Nicho livre não cadastrado");
  });
});
