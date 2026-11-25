import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AddToCrmDialog } from "../app/components/crm/AddToCrmDialog";
import { CrmLeadDetails } from "../app/components/crm/ManualCrmWorkspace";
import { CompanyEditor } from "../app/components/crm/CompanyEditor";
import type { Card, Company, Request } from "../app/components/crm/types";

const stages = [{id:1,funnel_id:1,key:"new",label:"Novo",color:"#ffffff",position:0}];
const funnels = [{id:1,name:"Comercial",stages}];
const company = (id: number): Company => ({
  id,name:`Empresa ${id}`,niche:"Brindes",location:"Fortaleza",address:"Centro",phone:"+5585999990000",email:"empresa@automasoluct.com.br",
  website:"https://automasoluct.com.br",call_url:"tel:+5585999990000",whatsapp_url:"https://wa.me/5585999990000",
  tags:[{id:1,name:"Prioridade",color:"#ffffff"}],
  provenance:{run_id:39,niche:"Brindes",location:"Fortaleza",created_at:"2026-11-19T12:00:00Z",status:"completed"},
  commercial_profile:{available:true,version:0,niche_override:null,location_override:null,contact_name:null,contact_phone:null,contact_email:null,
    contact_call_url:"",contact_whatsapp_url:"",contact_email_url:""}
});
const card = (): Card => ({id:10,lead:company(1),funnel_id:1,funnel_name:"Comercial",stage_id:1,stage_label:"Novo",stage_color:"#ffffff",managed_manually:true,
  qualification_notes:"Nota histórica",estimated_value:"123.45",currency:"BRL",sales_outcome:"open",lost_reason:null,closed_at:null,version:1,
  next_follow_up:null,activities:[],follow_ups:[],stage_history:[]});

describe("all-page bulk selection", () => {
  it("uses server filters, retains earlier selections and caps the union at 1,000 without adding automatically", async () => {
    const spy = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("funnels")) return funnels;
      if (path.endsWith("lead-eligibility")) return {lead_ids:JSON.parse(String(init?.body)).lead_ids};
      if (path.includes("lead-selection")) return {lead_ids:Array.from({length:1000},(_,i) => i+1),total:1050,limit:1000};
      if (init?.method === "POST") return {created_card_ids:[],skipped_lead_ids:[]};
      return {items:[company(1)],total:1050,available_total:1050,matching_total:1050};
    });
    render(<AddToCrmDialog request={spy as Request} initialIds={[2000]} onClose={vi.fn()} />);
    await screen.findByLabelText("Selecionar Empresa 1");
    fireEvent.change(screen.getByLabelText("Empresa"),{target:{value:"Empresa & B2B"}});
    fireEvent.change(screen.getByLabelText("Nicho"),{target:{value:"Serviços"}});
    fireEvent.change(screen.getByLabelText("Localidade"),{target:{value:"Recife"}});
    await waitFor(() => expect((screen.getByRole("button",{name:"Selecionar todos"}) as HTMLButtonElement).disabled).toBe(false));
    await userEvent.click(screen.getByRole("button",{name:"Selecionar todos"}));
    await screen.findByText(/1000 selecionados/);
    expect(screen.getByText(/Limite de 1.000 seleções atingido/)).toBeTruthy();
    const selectedPath = spy.mock.calls.find(([path]) => path.includes("lead-selection"))![0];
    const params = new URL(selectedPath,"http://localhost").searchParams;
    expect(Object.fromEntries(params)).toEqual({q:"Empresa & B2B",niche:"Serviços",location:"Recife",funnel_id:"1"});
    expect(spy.mock.calls.some(([path,init]) => path.endsWith("/cards") && init?.method)).toBe(false);
    await userEvent.click(screen.getByRole("button",{name:"Adicionar 1000 ao CRM"}));
    await screen.findByText(/0 cards adicionados/);
    const payload = JSON.parse(String(spy.mock.calls.find(([path,init]) => path.endsWith("/cards") && init?.method === "POST")![1]!.body));
    expect(payload.lead_ids).toHaveLength(1000);
    expect(payload.lead_ids).toContain(2000);
    expect(new Set(payload.lead_ids).size).toBe(1000);
  });

  it("retains selections on filter/page changes, selects all matching pages and deselects explicitly", async () => {
    const spy = vi.fn(async (path: string) => {
      if (path.endsWith("funnels")) return funnels;
      if (path.includes("lead-selection")) return {lead_ids:[1,31,61],total:3};
      const params = new URL(path,"http://localhost").searchParams;
      return {items:[company(params.get("offset") === "30" ? 31 : 1)],total:61,available_total:61,matching_total:61};
    });
    render(<AddToCrmDialog request={spy as Request} onClose={vi.fn()} />);
    await userEvent.click(await screen.findByLabelText("Selecionar Empresa 1"));
    await userEvent.click(screen.getByRole("button",{name:"Próxima página"}));
    await screen.findByLabelText("Selecionar Empresa 31");
    await userEvent.click(screen.getByRole("button",{name:"Selecionar todos"}));
    await screen.findByText(/3 selecionados/);
    expect((screen.getByLabelText("Selecionar Empresa 31") as HTMLInputElement).checked).toBe(true);
    fireEvent.change(screen.getByLabelText("Nicho"),{target:{value:"Outro filtro"}});
    await screen.findByLabelText("Selecionar Empresa 1");
    expect((screen.getByLabelText("Selecionar Empresa 1") as HTMLInputElement).checked).toBe(true);
    await userEvent.click(screen.getByRole("button",{name:"Desmarcar todos"}));
    expect(screen.getByText(/0 selecionados/)).toBeTruthy();
    expect((screen.getByLabelText("Selecionar Empresa 1") as HTMLInputElement).checked).toBe(false);
  });

  it("locks selection while loading and preserves it if the server selection fails", async () => {
    let fail: (reason: Error) => void = () => {};
    const spy = vi.fn(async (path: string, init?: RequestInit) => path.endsWith("funnels") ? funnels : path.endsWith("lead-eligibility")
      ? {lead_ids:JSON.parse(String(init?.body)).lead_ids} : path.includes("lead-selection")
      ? new Promise((_resolve,reject) => {fail=reject;}) : {items:[company(1)],total:2,available_total:2,matching_total:2});
    render(<AddToCrmDialog request={spy as Request} initialIds={[1]} onClose={vi.fn()} />);
    await screen.findByLabelText("Selecionar Empresa 1");
    await userEvent.click(screen.getByRole("button",{name:"Selecionar todos"}));
    expect(screen.getByText(/Selecionando empresas de todas/)).toBeTruthy();
    expect(screen.getByLabelText("Nicho").matches(":disabled")).toBe(true);
    expect((screen.getByRole("button",{name:"Adicionar 1 ao CRM"}) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => fail(Error("Falha de rede")));
    expect(screen.getByRole("alert").textContent).toContain("Falha de rede");
    expect(screen.getByText(/1 selecionados/)).toBeTruthy();
    expect((screen.getByLabelText("Selecionar Empresa 1") as HTMLInputElement).checked).toBe(true);
  });
});

describe("company and prospect representative editor", () => {
  it("keeps the opening version across background reloads and explicitly clears overrides/contact fields", async () => {
    const original = company(1);
    original.niche="Comercial"; original.location="Recife";
    Object.assign(original.commercial_profile!,{version:3,niche_override:"Comercial",location_override:"Recife",contact_name:"Maria"});
    const save = vi.fn();
    const rendered = render(<CompanyEditor company={original} busy={false} onSave={save} onCancel={vi.fn()} />);
    for (const label of ["Nicho comercial","Localidade comercial","Nome do contato"]) {
      fireEvent.change(screen.getByLabelText(label),{target:{value:""}});
    }
    const reloaded = structuredClone(original); reloaded.commercial_profile!.version=4;
    rendered.rerender(<CompanyEditor company={reloaded} busy={false} onSave={save} onCancel={vi.fn()} />);
    await userEvent.click(screen.getByRole("button",{name:"Salvar empresa"}));
    expect(save).toHaveBeenCalledWith({commercial_profile:{version:3,niche_override:null,location_override:null,contact_name:null}});
  });

  it("uses the existing company API with safe commercial overrides and preserves opportunity data", async () => {
    const value = card();
    const before = structuredClone(value);
    const spy = vi.fn(async (path: string,init?: RequestInit) => {
      if (init?.method === "PATCH") {
        expect(path).toBe("/api/leads/1");
        const {commercial_profile,...fields} = JSON.parse(String(init.body));
        Object.assign(value.lead,fields,{niche:commercial_profile.niche_override,location:commercial_profile.location_override});
        Object.assign(value.lead.commercial_profile!,commercial_profile,{version:1});
        return {};
      }
      return structuredClone(value);
    });
    render(<CrmLeadDetails cardId={10} request={spy as Request} stages={stages} onClose={vi.fn()} onChanged={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button",{name:"Editar empresa"}));
    for (const [label,text] of [["Nome da empresa","Empresa revisada"],["Telefone principal","+5585999887766"],["E-mail principal","vendas@automasoluct.com.br"],["Site","https://novo.automasoluct.com.br"],["Endereço","Recife, PE"],["Nicho comercial","Serviços"],["Localidade comercial","Recife"],["Nome do contato","Maria"],["Telefone do contato","+5585999776655"],["E-mail do contato","maria@automasoluct.com.br"]]) {
      fireEvent.change(screen.getByLabelText(label),{target:{value:text}});
    }
    await userEvent.click(screen.getByRole("button",{name:"Salvar empresa"}));
    await waitFor(() => expect(screen.queryByRole("form",{name:"Editar empresa"})).toBeNull());
    const payload = JSON.parse(String(spy.mock.calls.find(([,init]) => init?.method === "PATCH")![1]!.body));
    expect(payload.niche).toBeUndefined(); expect(payload.location).toBeUndefined(); expect(payload.run_id).toBeUndefined();
    expect(payload.commercial_profile).toEqual({version:0,niche_override:"Serviços",location_override:"Recife",contact_name:"Maria",contact_phone:"+5585999776655",contact_email:"maria@automasoluct.com.br"});
    expect(payload.name).toBe("Empresa revisada");
    expect(value.lead.provenance).toEqual(before.lead.provenance);
    expect(value.lead.tags).toEqual(before.lead.tags);
    expect({...value,lead:before.lead}).toEqual(before);
  });

  it("keeps unsaved company fields on API errors and protects closing an open editor", async () => {
    const confirm = vi.spyOn(window,"confirm").mockReturnValue(false);
    const close = vi.fn();
    const spy = vi.fn(async (_path: string,init?: RequestInit) => {
      if (init?.method) throw Error("Empresa alterada em outra janela. Atualize os detalhes.");
      return card();
    });
    render(<CrmLeadDetails cardId={10} request={spy as Request} stages={stages} onClose={close} onChanged={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button",{name:"Editar empresa"}));
    fireEvent.change(screen.getByLabelText("Nome do contato"),{target:{value:"Maria"}});
    await userEvent.click(screen.getByRole("button",{name:"Salvar empresa"}));
    await screen.findByRole("alert");
    expect((screen.getByLabelText("Nome do contato") as HTMLInputElement).value).toBe("Maria");
    await userEvent.click(screen.getByRole("button",{name:"Fechar"}));
    expect(confirm).toHaveBeenCalled(); expect(close).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button",{name:"Cancelar edição"}));
    expect(screen.queryByLabelText("Nome do contato")).toBeNull();
    confirm.mockRestore();
  });

  it("renders direct representative actions separately from company contact without provider or mutation calls", async () => {
    const value = card();
    Object.assign(value.lead.commercial_profile!,{version:1,contact_name:"Maria",contact_phone:"+5585999776655",contact_email:"maria@automasoluct.com.br",
      contact_call_url:"tel:+5585999776655",contact_whatsapp_url:"https://wa.me/5585999776655",contact_email_url:"mailto:maria@automasoluct.com.br"});
    const spy = vi.fn(async () => structuredClone(value));
    render(<CrmLeadDetails cardId={10} request={spy as Request} stages={stages} onClose={vi.fn()} onChanged={vi.fn()} />);
    await screen.findByText("Maria");
    expect(screen.getByRole("link",{name:"Ligar para contato"}).getAttribute("href")).toBe("tel:+5585999776655");
    expect(screen.getByRole("link",{name:"WhatsApp do contato"}).getAttribute("href")).toBe("https://wa.me/5585999776655");
    expect(screen.getByRole("link",{name:"E-mail do contato"}).getAttribute("href")).toBe("mailto:maria@automasoluct.com.br");
    expect(screen.getByRole("link",{name:"Ligar"}).getAttribute("href")).toBe("tel:+5585999990000");
    expect(spy.mock.calls).toEqual([["/api/crm/manual/cards/10"]]);
  });

  it("disables editing with an explicit explanation before the migration is installed", async () => {
    const value = card(); value.lead.commercial_profile!.available=false;
    render(<CrmLeadDetails cardId={10} request={(async () => value) as Request} stages={stages} onClose={vi.fn()} onChanged={vi.fn()} />);
    const edit = await screen.findByRole("button",{name:"Editar empresa"}) as HTMLButtonElement;
    expect(edit.disabled).toBe(true);
    expect(screen.getByText(/Edição de empresa disponível após aplicar a migração/)).toBeTruthy();
  });
});
