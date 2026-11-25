import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AddToCrmDialog } from "../app/components/crm/AddToCrmDialog";
import { ManualCrmWorkspace } from "../app/components/crm/ManualCrmWorkspace";
import { PIPELINE_STORAGE_KEY } from "../app/components/crm/usePipelineSelection";
import type { Company, Funnel, Request } from "../app/components/crm/types";

const funnels: Funnel[] = [1,2].map(id => ({id,name:`Funil ${id}`,stages:[{id:id*10,funnel_id:id,key:"new",label:`Novo ${id}`,color:"#fff",position:0}]}));
const company = (id: number): Company => ({id,name:`Empresa ${id}`,niche:"Brindes",location:"Fortaleza",address:"Centro",phone:"",email:"",website:"",call_url:"",whatsapp_url:"",tags:[],provenance:{run_id:1,niche:"Brindes",location:"Fortaleza",status:"completed",created_at:"2026-11-19T12:00:00Z"}});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes,no) => {resolve=yes;reject=no;});
  return {promise,resolve,reject};
}
function server({size=65, imported=new Map([[1,new Set([1,2])],[2,new Set([3])]])} = {}) {
  const leads = Array.from({length:size},(_,i) => company(i+1));
  const spy = vi.fn(async (path: string, init?: RequestInit): Promise<unknown> => {
    if (path === "/api/crm/funnels") return funnels;
    if (path.includes("/follow-ups?") || path.includes("/cards?")) return [];
    if (path.endsWith("/lead-eligibility")) {
      const body = JSON.parse(String(init!.body));
      return {lead_ids:body.lead_ids.filter((id: number) => id<=size && !imported.get(body.funnel_id)?.has(id))};
    }
    if (path.endsWith("/cards") && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      const existing = imported.get(body.funnel_id) || new Set<number>();
      const skipped = body.lead_ids.filter((id: number) => existing.has(id));
      const created = body.lead_ids.filter((id: number) => !existing.has(id));
      for (const id of created) existing.add(id);
      imported.set(body.funnel_id,existing);
      return {created_card_ids:created,skipped_lead_ids:skipped};
    }
    const params = new URL(path,"http://localhost").searchParams;
    const funnelId = Number(params.get("funnel_id"));
    const memberships = imported.get(funnelId) || new Set<number>();
    const matching = leads.filter(item => item.name.includes(params.get("q") || ""));
    const eligible = matching.filter(item => !memberships.has(item.id));
    if (path.includes("/lead-selection?")) return {lead_ids:eligible.slice(0,1000).map(item=>item.id),total:eligible.length,limit:1000};
    if (path.includes("/leads?")) {
      const shown = params.get("show_added") === "true" ? matching : eligible;
      const offset = Number(params.get("offset"));
      return {items:shown.slice(offset,offset+30).map(item=>({...item,already_in_pipeline:memberships.has(item.id)})),total:shown.length,
        matching_total:matching.length,available_total:eligible.length};
    }
    throw Error(`Unexpected request ${path}`);
  });
  return {spy,imported};
}
const mutations = (spy: ReturnType<typeof server>["spy"]) => spy.mock.calls.filter(([path,init]) => path.endsWith("/cards") && init?.method === "POST");

describe("pipeline-aware CRM imports", () => {
  it("defaults to available leads, shows exact counts, and labels/disables imported memberships when shown", async () => {
    const {spy} = server({size:25,imported:new Map([[1,new Set(Array.from({length:10},(_,i)=>i+1))]])});
    render(<AddToCrmDialog request={spy as Request} onClose={vi.fn()} />);
    await screen.findByText(/15 disponíveis de 25 empresas encontradas/);
    expect(screen.queryByLabelText("Selecionar Empresa 1")).toBeNull();
    expect((screen.getByLabelText("Mostrar já adicionados") as HTMLInputElement).checked).toBe(false);
    await userEvent.click(screen.getByLabelText("Mostrar já adicionados"));
    const imported = await screen.findByLabelText("Selecionar Empresa 1") as HTMLInputElement;
    expect(imported.disabled).toBe(true); expect(imported.checked).toBe(false);
    expect(screen.getAllByText("Já adicionado a este funil")).toHaveLength(10);
    expect((screen.getByLabelText("Selecionar Empresa 11") as HTMLInputElement).disabled).toBe(false);
    await userEvent.click(screen.getByRole("button",{name:"Selecionar todos"}));
    await screen.findByText(/15 selecionados/);
    expect(mutations(spy)).toHaveLength(0);
    await userEvent.click(screen.getByRole("button",{name:"Adicionar 15 ao CRM"}));
    await screen.findByText(/15 cards adicionados/);
    expect(JSON.parse(String(mutations(spy)[0][1]!.body)).lead_ids).toEqual(Array.from({length:15},(_,i)=>i+11));
    await screen.findByText(/0 disponíveis de 25 empresas encontradas/);
  });

  it("keeps selections across filtered pages and bulk-selects only eligible leads", async () => {
    const {spy} = server();
    render(<AddToCrmDialog request={spy as Request} onClose={vi.fn()} />);
    await userEvent.click(await screen.findByLabelText("Selecionar Empresa 3"));
    await userEvent.click(screen.getByRole("button",{name:"Próxima página"}));
    await userEvent.click(await screen.findByLabelText("Selecionar Empresa 33"));
    fireEvent.change(screen.getByLabelText("Empresa"),{target:{value:"Empresa 6"}});
    await screen.findByLabelText("Selecionar Empresa 60");
    await userEvent.click(screen.getByRole("button",{name:"Selecionar todos"}));
    await screen.findByText(/9 selecionados/); // Prior 3/33 plus 6 and 60..65.
    expect(mutations(spy)).toHaveLength(0);
    const selection = spy.mock.calls.find(([path])=>path.includes("/lead-selection?"))![0];
    expect(new URL(selection,"http://localhost").searchParams.get("funnel_id")).toBe("1");
    fireEvent.change(screen.getByLabelText("Empresa"),{target:{value:""}});
    await userEvent.click(await screen.findByRole("button",{name:"Selecionar todos"}));
    await screen.findByText(/63 selecionados/);
    expect((screen.getByLabelText("Selecionar Empresa 3") as HTMLInputElement).checked).toBe(true);
  });

  it("removes ineligible retained selections on pipeline switch and keeps eligible multi-pipeline leads", async () => {
    const {spy} = server();
    render(<AddToCrmDialog request={spy as Request} initialIds={[1,3,4]} onClose={vi.fn()} />);
    await screen.findByText(/2 selecionados/);
    expect((screen.getByLabelText("Selecionar Empresa 3") as HTMLInputElement).checked).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText("Funil"),"2");
    await screen.findByText(/1 selecionados/);
    expect((await screen.findByLabelText("Selecionar Empresa 4") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Selecionar Empresa 1") as HTMLInputElement).disabled).toBe(false);
    expect(screen.queryByLabelText("Selecionar Empresa 3")).toBeNull();
    expect(screen.getByText(/1 seleções removidas/)).toBeTruthy();
    await userEvent.click(screen.getByLabelText("Selecionar Empresa 1"));
    await userEvent.click(screen.getByRole("button",{name:"Adicionar 2 ao CRM"}));
    await screen.findByText(/2 cards adicionados/);
    expect(JSON.parse(String(mutations(spy)[0][1]!.body))).toEqual({lead_ids:[4,1],funnel_id:2,stage_id:20});
  });

  it("ignores a stale eligibility response after switching pipelines", async () => {
    const original = server();
    const oldCheck = deferred<{lead_ids:number[]}>();
    const spy = vi.fn(async(path:string,init?:RequestInit) => path.endsWith("lead-eligibility") && JSON.parse(String(init!.body)).funnel_id===1 ? oldCheck.promise : original.spy(path,init));
    render(<AddToCrmDialog request={spy as Request} initialIds={[3,4]} onClose={vi.fn()} />);
    await screen.findByLabelText("Selecionar Empresa 3");
    expect((screen.getByRole("button",{name:"Adicionar 2 ao CRM"}) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText("Funil"),"2");
    await screen.findByText(/1 selecionados/);
    await act(async()=>oldCheck.resolve({lead_ids:[3,4]}));
    expect(screen.getByText(/1 selecionados/)).toBeTruthy();
    expect((screen.getByLabelText("Selecionar Empresa 4") as HTMLInputElement).checked).toBe(true);
  });

  it("fails closed when retained-selection validation fails and can retry", async () => {
    const original=server(); let failed=true;
    const spy=vi.fn(async(path:string,init?:RequestInit)=>{
      if(path.endsWith("lead-eligibility") && failed) throw Error("Verificação indisponível");
      return original.spy(path,init);
    });
    render(<AddToCrmDialog request={spy as Request} initialIds={[3]} onClose={vi.fn()} />);
    await screen.findByText("Verificação indisponível");
    expect((screen.getByRole("button",{name:"Adicionar 1 ao CRM"}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button",{name:"Selecionar todos"}) as HTMLButtonElement).disabled).toBe(true);
    failed=false; await userEvent.click(screen.getByRole("button",{name:"Tentar novamente"}));
    await waitFor(()=>expect((screen.getByRole("button",{name:"Adicionar 1 ao CRM"}) as HTMLButtonElement).disabled).toBe(false));
    expect(mutations(original.spy)).toHaveLength(0);
  });
});

describe("remembered pipeline", () => {
  it("restores the saved choice without fetching or flashing the first pipeline", async () => {
    window.localStorage.setItem(PIPELINE_STORAGE_KEY,"2");
    const original=server(); const metadata=deferred<Funnel[]>();
    const spy=vi.fn(async(path:string,init?:RequestInit)=>path.endsWith("funnels")?metadata.promise:original.spy(path,init));
    render(<ManualCrmWorkspace request={spy as Request} onManageFunnels={vi.fn()} />);
    expect((screen.getByLabelText("Funil") as HTMLSelectElement).value).toBe("0");
    expect(screen.getByText("Carregando funis…")).toBeTruthy();
    expect(window.localStorage.getItem(PIPELINE_STORAGE_KEY)).toBe("2");
    await act(async()=>metadata.resolve(funnels));
    await screen.findByRole("region",{name:"Estágio Novo 2"});
    await waitFor(()=>expect(spy.mock.calls.some(([path])=>path.includes("cards?funnel_id=2"))).toBe(true));
    expect(spy.mock.calls.some(([path])=>path.includes("cards?funnel_id=1"))).toBe(false);
    expect((screen.getByLabelText("Funil") as HTMLSelectElement).value).toBe("2");
  });

  it("persists through unmount/navigation and synchronizes the board and open import modal", async () => {
    const {spy}=server();
    const props={request:spy as Request,onManageFunnels:vi.fn()};
    let rendered=render(<ManualCrmWorkspace {...props} />);
    await screen.findByRole("region",{name:"Estágio Novo 1"});
    await userEvent.selectOptions(screen.getByLabelText("Funil"),"2");
    await screen.findByRole("region",{name:"Estágio Novo 2"});
    expect(window.localStorage.getItem(PIPELINE_STORAGE_KEY)).toBe("2");
    rendered.unmount(); rendered=render(<ManualCrmWorkspace {...props} />);
    await screen.findByRole("region",{name:"Estágio Novo 2"});
    await userEvent.click(screen.getByRole("button",{name:"Adicionar ao CRM"}));
    const modal=await screen.findByRole("dialog",{name:"Adicionar ao CRM"});
    await waitFor(()=>expect((within(modal).getByLabelText("Funil") as HTMLSelectElement).value).toBe("2"));
    await userEvent.selectOptions(within(modal).getByLabelText("Funil"),"1");
    await waitFor(()=>expect(screen.getAllByLabelText("Funil").map(item=>(item as HTMLSelectElement).value)).toEqual(["1","1"]));
    expect(window.localStorage.getItem(PIPELINE_STORAGE_KEY)).toBe("1");
    await userEvent.click(within(modal).getByRole("button",{name:"Fechar"}));
    await screen.findByRole("region",{name:"Estágio Novo 1"});
  });

  it.each(["9999","corrupt","-1"])("falls back safely for a deleted/invalid saved value %s", async(saved)=>{
    window.localStorage.setItem(PIPELINE_STORAGE_KEY,saved);
    const {spy}=server(); render(<AddToCrmDialog request={spy as Request} onClose={vi.fn()} />);
    await screen.findByLabelText("Selecionar Empresa 3");
    expect((screen.getByLabelText("Funil") as HTMLSelectElement).value).toBe("1");
    expect(window.localStorage.getItem(PIPELINE_STORAGE_KEY)).toBe("1");
    expect(spy.mock.calls.some(([path])=>path.includes(`funnel_id=${saved}`))).toBe(false);
  });

  it("revalidates a deleted current pipeline after refreshing metadata", async()=>{
    window.localStorage.setItem(PIPELINE_STORAGE_KEY,"2");
    const original=server(); let remaining=funnels;
    const spy=vi.fn(async(path:string,init?:RequestInit)=>path.endsWith("funnels")?remaining:original.spy(path,init));
    render(<ManualCrmWorkspace request={spy as Request} onManageFunnels={vi.fn()} />);
    await screen.findByRole("region",{name:"Estágio Novo 2"});
    remaining=[funnels[0]];
    await userEvent.click(screen.getByRole("button",{name:"Atualizar CRM"}));
    await screen.findByRole("region",{name:"Estágio Novo 1"});
    expect(window.localStorage.getItem(PIPELINE_STORAGE_KEY)).toBe("1");
    expect(screen.queryByRole("region",{name:"Estágio Novo 2"})).toBeNull();
  });

  it.each([false,true])("does not let stale board metadata override the picker after pipeline deletion (empty=%s)",async(empty)=>{
    window.localStorage.setItem(PIPELINE_STORAGE_KEY,"2");
    const original=server(); let available=funnels;
    const third:Funnel={id:3,name:"Funil 3",stages:[{id:30,funnel_id:3,key:"new",label:"Novo 3",color:"#fff",position:0}]};
    const spy=vi.fn(async(path:string,init?:RequestInit)=>path.endsWith("funnels")?available:original.spy(path,init));
    render(<ManualCrmWorkspace request={spy as Request} onManageFunnels={vi.fn()} />);
    await screen.findByRole("region",{name:"Estágio Novo 2"});
    available=empty?[]:[third];
    await userEvent.click(screen.getByRole("button",{name:"Adicionar ao CRM"}));
    const modal=await screen.findByRole("dialog",{name:"Adicionar ao CRM"});
    await waitFor(()=>expect(screen.getAllByLabelText("Funil").map(item=>(item as HTMLSelectElement).value)).toEqual(empty?["0","0"]:["3","3"]));
    expect(window.localStorage.getItem(PIPELINE_STORAGE_KEY)).toBe(empty?null:"3");
    expect(spy.mock.calls.filter(([path])=>path.endsWith("funnels")).length).toBeLessThan(10);
    await userEvent.click(within(modal).getByRole("button",{name:"Fechar"}));
    if(empty) await screen.findByText("Nenhum funil disponível. Cadastre um funil para começar.");
    else await screen.findByRole("region",{name:"Estágio Novo 3"});
  });

  it("handles an empty pipeline list and unavailable localStorage without crashing", async()=>{
    const unavailable = vi.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw Error("Storage blocked");});
    const unwritable = vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw Error("Storage blocked");});
    const {spy}=server();
    const rendered=render(<AddToCrmDialog request={spy as Request} onClose={vi.fn()} />);
    await screen.findByLabelText("Selecionar Empresa 3");
    await userEvent.selectOptions(screen.getByLabelText("Funil"),"2");
    await screen.findByLabelText("Selecionar Empresa 1");
    expect((screen.getByLabelText("Funil") as HTMLSelectElement).value).toBe("2");
    rendered.unmount(); unavailable.mockRestore(); unwritable.mockRestore();
    render(<AddToCrmDialog request={(async()=>[]) as Request} onClose={vi.fn()} />);
    await screen.findByText("Nenhum funil disponível");
    expect((screen.getByLabelText("Funil") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole("button",{name:"Selecionar todos"}) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps selection usable when storage writes fail but reads still work", async()=>{
    window.localStorage.setItem(PIPELINE_STORAGE_KEY,"1");
    const {spy}=server();
    render(<AddToCrmDialog request={spy as Request} onClose={vi.fn()} />);
    await screen.findByLabelText("Selecionar Empresa 3");
    vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw Error("Quota exceeded");});
    await userEvent.selectOptions(screen.getByLabelText("Funil"),"2");
    await screen.findByLabelText("Selecionar Empresa 1");
    expect((screen.getByLabelText("Funil") as HTMLSelectElement).value).toBe("2");
    expect(window.localStorage.getItem(PIPELINE_STORAGE_KEY)).toBe("1");
  });

  it("synchronizes a pipeline change from another browser tab and ignores the old bulk response", async()=>{
    const original=server(); const bulk=deferred<{lead_ids:number[];total:number}>();
    const spy=vi.fn(async(path:string,init?:RequestInit)=>path.includes("/lead-selection?")?bulk.promise:original.spy(path,init));
    render(<AddToCrmDialog request={spy as Request} onClose={vi.fn()} />);
    await screen.findByLabelText("Selecionar Empresa 3");
    await userEvent.click(screen.getByRole("button",{name:"Selecionar todos"}));
    act(()=>{
      window.localStorage.setItem(PIPELINE_STORAGE_KEY,"2");
      window.dispatchEvent(new StorageEvent("storage",{key:PIPELINE_STORAGE_KEY,newValue:"2"}));
    });
    await screen.findByLabelText("Selecionar Empresa 1");
    await act(async()=>bulk.resolve({lead_ids:[3,4,5],total:3}));
    expect((screen.getByLabelText("Funil") as HTMLSelectElement).value).toBe("2");
    expect(screen.getByText(/0 selecionados/)).toBeTruthy();
    expect(mutations(original.spy)).toHaveLength(0);
  });
});
