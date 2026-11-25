import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WebsiteQualification, BulkWebsiteQualification, QualificationFilters, emptyQualificationFilters, type WebsiteResult } from "../app/components/WebsiteQualification";
import type { Request } from "../app/components/crm/types";

const result:WebsiteResult = {normalized_website:"https://company.example/",site_availability:"accessible",cms:"WordPress",cms_name:"WordPress",
  wordpress_status:"confirmed",blog_status:"detected",blog_url:"https://company.example/blog",total_posts:0,last_published_at:null,
  last_post_title:null,last_post_url:null,days_since_publication:null,priority:"HIGH",validation_status:"validated",checked_at:"2026-11-25T12:00:00Z",
  evidence:[{source:"wp_posts_api",reason:"no_posts_exposed"}],errors:[]};

describe("website qualification integration", () => {
  it("loads only when expanded, shows nulls and zero separately, and revalidates the existing lead", async () => {
    const request=vi.fn(async (_path:string,init?:RequestInit) => init?.method === "POST" ? {job_id:"job",status:"queued",total:1,processed:0,failed:0} : {result,job_id:null,status:"idle"});
    render(<WebsiteQualification leadId={42} request={request as Request} initial={result}/>);
    expect(request).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button",{name:"Site: Alta · WordPress"}));
    expect(await screen.findByText("0")).toBeTruthy();
    expect(screen.getAllByText("Não disponível").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByText("Evidências e limitações"));
    expect(screen.getByText("Nenhum artigo exposto pela API pública")).toBeTruthy();
    await userEvent.click(screen.getByRole("button",{name:"Revalidar site"}));
    expect(request).toHaveBeenCalledWith("/api/website-qualification/leads/42/analyze",{method:"POST"});
    expect((screen.getByRole("button",{name:"Análise em andamento…"}) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps prior evidence visible while a job is queued and flags stale websites", async () => {
    const request=vi.fn(async (path:string) => path.includes("/jobs/") ? {job_id:"active",status:"running",total:2,processed:1,failed:0} : {result:{...result,stale:true},job_id:"active",status:"running"});
    render(<WebsiteQualification leadId={1} request={request as Request}/>);
    await userEvent.click(screen.getByRole("button",{name:"Analisar site"}));
    expect(await screen.findByText(/O site foi alterado/)).toBeTruthy();
    expect(screen.getByText("Alta")).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("1/2"));
  });

  it("bulk analysis sends only the selected saved IDs and shows job progress/errors", async () => {
    window.localStorage.clear();
    const request=vi.fn(async () => ({job_id:"bulk",status:"completed",total:2,processed:2,failed:1}));
    render(<BulkWebsiteQualification ids={[29,40]} request={request as Request}/>);
    await userEvent.click(screen.getByRole("button",{name:"Analisar sites (2)"}));
    await screen.findByText(/Sites: 2\/2/);
    expect(request).toHaveBeenCalledWith("/api/website-qualification/jobs",{method:"POST",body:JSON.stringify({lead_ids:[29,40],revalidate:true})});
    expect(screen.getByRole("status").textContent).toContain("Falhas: 1");
    window.localStorage.clear();
  });

  it("offers CMS, blog, priority and inactivity filters without affecting CRM actions", () => {
    const onChange=vi.fn();
    render(<QualificationFilters value={emptyQualificationFilters} onChange={onChange}/>);
    fireEvent.change(screen.getByLabelText("CMS"),{target:{value:"WordPress"}});
    expect(onChange).toHaveBeenLastCalledWith({...emptyQualificationFilters,cms:"WordPress"});
    fireEvent.change(screen.getByLabelText("Prioridade do site"),{target:{value:"HIGH"}});
    expect(onChange).toHaveBeenLastCalledWith({...emptyQualificationFilters,priority:"HIGH"});
    fireEvent.change(screen.getByLabelText("Inatividade mínima (dias)"),{target:{value:"90"}});
    expect(onChange).toHaveBeenLastCalledWith({...emptyQualificationFilters,inactive_days:"90"});
  });
});
