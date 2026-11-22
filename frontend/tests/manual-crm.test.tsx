import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AddToCrmDialog } from "../app/components/crm/AddToCrmDialog";
import { CrmLeadDetails, ManualCrmWorkspace } from "../app/components/crm/ManualCrmWorkspace";
import type { Card, Company, Request } from "../app/components/crm/types";
import Home from "../app/page";

const stages = [
  { id: 1, funnel_id: 1, key: "new", label: "Novo", color: "#ffffff", position: 0 },
  { id: 2, funnel_id: 1, key: "converted", label: "Convertido", color: "#ffffff", position: 1 }
];
const funnels = [{ id: 1, name: "Comercial", stages }];
const company = (id: number): Company => ({ id, name: `Empresa ${id}`, niche: "Brindes", location: "Fortaleza", address: "Centro", phone: "+5585999990000", email: "vendas@empresa.example", website: "https://empresa.example", call_url: "tel:+5585999990000", whatsapp_url: "https://wa.me/5585999990000", tags: [{ id:1,name:"Prioridade",color:"#ffffff" }], provenance: { run_id:39,niche:"Brindes",location:"Fortaleza",created_at:"2026-11-19T12:00:00Z",status:"completed" } });
const card = (): Card => ({ id:10,lead:company(1),funnel_id:1,funnel_name:"Comercial",stage_id:1,stage_label:"Novo",stage_color:"#ffffff",managed_manually:true,qualification_notes:"Nota histórica intacta",estimated_value:null,currency:"BRL",sales_outcome:"open",lost_reason:null,closed_at:null,version:1,next_follow_up:null,activities:[],follow_ups:[],stage_history:[{id:1,from_stage:"new",to_stage:"qualified",changed_by:"ai",changed_at:"2026-11-19T12:00:00Z"}] });

describe("manual prospecting CRM", () => {
  it("keeps selection across server pages and submits only IDs and the chosen pipeline/stage", async () => {
    const user = userEvent.setup();
    const spy = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/crm/funnels") return funnels;
      if (path.startsWith("/api/crm/manual/leads")) {
        const offset = new URL(path,"http://localhost").searchParams.get("offset");
        return { items:[company(offset === "0" ? 1 : 531)],total:532 };
      }
      if (init?.method === "POST") return { created_card_ids:[10,11],skipped_lead_ids:[] };
      throw Error(path);
    });
    render(<AddToCrmDialog request={spy as Request} onClose={vi.fn()} />);
    await user.click(await screen.findByLabelText("Selecionar Empresa 1"));
    await user.click(screen.getByRole("button",{name:"Próxima página"}));
    await user.click(await screen.findByLabelText("Selecionar Empresa 531"));
    await user.click(screen.getByRole("button",{name:"Página anterior"}));
    const first = await screen.findByLabelText("Selecionar Empresa 1") as HTMLInputElement;
    expect(first.checked).toBe(true);
    await user.click(screen.getByRole("button",{name:"Adicionar 2 ao CRM"}));
    await screen.findByText(/2 cards adicionados/);
    const mutation = spy.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(String(mutation[1]?.body))).toEqual({lead_ids:[1,531],funnel_id:1,stage_id:1});
    expect(spy.mock.calls.some(([path]) => path.includes("offset=30"))).toBe(true);
  });

  it("reports already registered cards without replacing them", async () => {
    const spy = vi.fn(async (path: string, init?: RequestInit) => init?.method === "POST" ? {created_card_ids:[],skipped_lead_ids:[1]} : path.endsWith("funnels") ? funnels : {items:[company(1)],total:1});
    render(<AddToCrmDialog request={spy as Request} initialIds={[1]} onClose={vi.fn()} />);
    await screen.findByText("Empresa 1");
    await userEvent.click(screen.getByRole("button",{name:"Adicionar 1 ao CRM"}));
    await screen.findByText(/0 cards adicionados; 1 já estavam/);
    expect(spy.mock.calls.filter(([, init]) => init?.method === "PATCH")).toHaveLength(0);
  });

  it("appends notes and retains legacy notes/history; opening contact links records nothing", async () => {
    const value = card();
    const spy = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const payload = JSON.parse(String(init.body));
        value.activities!.push({id:value.activities!.length+1,...payload,actor:"shared-login",created_at:"2026-11-21T12:00:00Z"});
        return {};
      }
      return structuredClone(value);
    });
    render(<CrmLeadDetails cardId={10} request={spy as Request} stages={stages} onClose={vi.fn()} onChanged={vi.fn()} />);
    await screen.findByText("Nota histórica intacta");
    expect(screen.getByText("new → qualified")).toBeTruthy();
    expect(screen.getByRole("link",{name:"Ligar"}).getAttribute("href")).toBe("tel:+5585999990000");
    fireEvent.click(screen.getByRole("link",{name:"Abrir WhatsApp"}));
    expect(spy.mock.calls.filter(([,init]) => init?.method)).toHaveLength(0);
    for (const body of ["Primeira nota", "Segunda nota"]) {
      fireEvent.change(screen.getByLabelText("Registro da interação"),{target:{value:body}});
      await userEvent.click(screen.getByRole("button",{name:"Registrar atividade"}));
      await screen.findByText(body);
    }
    expect(screen.getByText("Primeira nota")).toBeTruthy();
    expect(screen.getByText("Nota histórica intacta")).toBeTruthy();
    for (const [,init] of spy.mock.calls.filter(([,init]) => init?.method === "POST")) {
      expect(Object.keys(JSON.parse(String(init!.body))).sort()).toEqual(["body","kind"]);
    }
  });

  it("uses explicit outcomes and never confirms a legacy Convertido sale", async () => {
    const value = {...card(),managed_manually:false,stage_id:2,stage_label:"Convertido",sales_outcome:null};
    const spy = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "PATCH") Object.assign(value,{managed_manually:true,sales_outcome:"open",version:2});
      return structuredClone(value);
    });
    render(<CrmLeadDetails cardId={10} request={spy as Request} stages={stages} onClose={vi.fn()} onChanged={vi.fn()} />);
    await screen.findByText(/Card legado/);
    expect(screen.queryByLabelText("Resultado comercial")).toBeNull();
    await userEvent.click(screen.getByRole("button",{name:"Assumir gestão manual"}));
    const outcome = await screen.findByLabelText("Resultado comercial") as HTMLSelectElement;
    expect(outcome.value).toBe("open");
    expect((screen.getByLabelText("Estágio") as HTMLSelectElement).value).toBe("2");
    fireEvent.change(outcome,{target:{value:"lost"}});
    fireEvent.change(screen.getByLabelText("Motivo da perda"),{target:{value:"Sem orçamento"}});
    await userEvent.click(screen.getByRole("button",{name:"Salvar oportunidade"}));
    const payload = JSON.parse(String(spy.mock.calls.filter(([,init]) => init?.method === "PATCH").at(-1)![1]!.body));
    expect(payload.sales_outcome).toBe("lost"); expect(payload.lost_reason).toBe("Sem orçamento");
  });

  it("creates UTC follow-ups and submits versioned reschedule/complete actions", async () => {
    const value = card();
    value.follow_ups = [{id:1,card_id:10,title:"Retornar ligação",due_at:"2026-11-23T12:00:00Z",status:"pending",version:1}];
    const spy = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const payload = JSON.parse(String(init.body));
        Object.assign(value.follow_ups![0],{version:2,...(payload.action === "complete" ? {status:"completed"} : {due_at:payload.due_at})});
      }
      return structuredClone(value);
    });
    render(<CrmLeadDetails cardId={10} request={spy as Request} stages={stages} onClose={vi.fn()} onChanged={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button",{name:"Reagendar"}));
    fireEvent.change(screen.getByLabelText("Nova data local"),{target:{value:"2026-11-24T10:00"}});
    await userEvent.click(screen.getByRole("button",{name:"Salvar reagendamento"}));
    await waitFor(() => expect(screen.queryByLabelText("Nova data local")).toBeNull());
    await userEvent.click(screen.getByRole("button",{name:"Concluir"}));
    await waitFor(() => expect(screen.queryByRole("button",{name:"Concluir"})).toBeNull());
    const mutations = spy.mock.calls.filter(([,init]) => init?.method === "PATCH").map(([,init]) => JSON.parse(String(init!.body)));
    expect(mutations[0]).toEqual({version:1,action:"reschedule",due_at:new Date("2026-11-24T10:00").toISOString()});
    expect(mutations[1]).toEqual({version:2,action:"complete"});
    fireEvent.change(screen.getByLabelText("Próxima ação"),{target:{value:"Reunião"}});
    fireEvent.change(screen.getByLabelText("Data e hora local"),{target:{value:"2026-11-25T09:00"}});
    await userEvent.click(screen.getByRole("button",{name:"Agendar follow-up"}));
    expect(JSON.parse(String(spy.mock.calls.find(([,init]) => init?.method === "POST")![1]!.body)).due_at).toBe(new Date("2026-11-25T09:00").toISOString());
  });

  it("displays scheduled and previous follow-up dates in the local timezone in historical events", async () => {
    const value = card();
    const previous = "2026-11-23T12:00:00+00:00";
    const due = "2026-11-24T13:00:00+00:00";
    value.activities = [{id:1,kind:"system",body:"Follow-up reagendado: Retornar ligação.",actor:"shared-login",created_at:"2026-11-21T12:00:00Z",details:{previous_due_at:previous,due_at:due}}];
    render(<CrmLeadDetails cardId={10} request={(async () => structuredClone(value)) as Request} stages={stages} onClose={vi.fn()} onChanged={vi.fn()} />);
    const format = (date: string) => new Date(date).toLocaleString();
    const event = await screen.findByText(/Follow-up reagendado: Retornar ligação/);
    expect(event.textContent).toContain(`Data anterior: ${format(previous)}`);
    expect(event.textContent).toContain(`Data agendada: ${format(due)}`);
    expect(event.textContent).not.toContain("+00:00");
  });

  it("loads /crm with no Evolution/AI requests even if those services would fail", async () => {
    window.history.replaceState(null,"","/crm");
    const fetchMock = vi.fn(async (input: string | URL | globalThis.Request) => {
      const path = String(input);
      if (path.includes("/api/whatsapp")) throw Error("Evolution disconnected");
      let value: unknown = [];
      if (path.includes("/api/auth/session")) value={authenticated:true,username:"shared-login"};
      else if (path.includes("/api/stats")) value={total_leads:761,total_with_email:0,running_jobs:0,completed_jobs:30};
      else if (path.includes("/api/crm/funnels")) value=funnels;
      else if (path.includes("/api/crm/manual/cards")) value=[card()];
      return new Response(JSON.stringify(value),{status:200,headers:{"Content-Type":"application/json"}});
    });
    vi.stubGlobal("fetch",fetchMock);
    render(<Home />);
    await screen.findByText("Empresa 1");
    expect(screen.getByRole("heading",{name:"CRM comercial",level:1})).toBeTruthy();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/whatsapp"))).toBe(false);
  });
});
