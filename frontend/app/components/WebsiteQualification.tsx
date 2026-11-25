"use client";
import { useEffect, useState } from "react";
import type { Request } from "./crm/types";

export type WebsiteResult = {
  normalized_website: string | null; site_availability: string; cms: string; cms_name: string | null;
  wordpress_status: string; blog_status: string; blog_url: string | null; total_posts: number | null;
  last_published_at: string | null; last_post_title: string | null; last_post_url: string | null;
  days_since_publication: number | null; priority: string; validation_status: string; checked_at: string;
  evidence: { source: string; reason: string; [key: string]: unknown }[]; errors: string[]; stale?: boolean;
};
type Job = { job_id: string; status: string; total: number; processed: number; failed: number; skipped?: number };
type Details = { result: WebsiteResult | null; job_id: string | null; status: string };
const ROOT = "/api/website-qualification";
const labels: Record<string,string> = {
  confirmed:"Confirmado", not_detected:"Não detectado", inconclusive:"Inconclusivo", detected:"Detectado",
  missing_verified:"Ausência verificada", accessible:"Acessível", unavailable:"Indisponível", blocked:"Bloqueado",
  HIGH:"Alta", MEDIUM:"Média", LOW:"Baixa", INCONCLUSIVE:"Inconclusiva", unknown:"Desconhecido", other:"Outro", validated:"Validado",
  robots_disallowed:"Inspeção não permitida pelo site", robots_unavailable:"Regras de inspeção indisponíveis",
  posts_api_inaccessible:"API de artigos inacessível", malformed_posts_api:"Resposta da API de artigos inválida",
  http_403:"Acesso bloqueado (403)", http_429:"Limite de acesso atingido (429)", tls_error:"Falha de certificado TLS",
  network_error:"Falha ou tempo limite de conexão", site_budget_exceeded:"Limite de inspeção atingido",
  external_blog_reference_not_crawled:"Referência a blog externo; publicação não verificada",
  wordpress_markers:"Indicadores WordPress no HTML", wordpress_api_namespace:"API pública WordPress identificada",
  wordpress_login_form:"Formulário público WordPress identificado", published_posts_exposed:"Artigos publicados na API pública",
  no_posts_exposed:"Nenhum artigo exposto pela API pública", verified_publication_date:"Data de publicação verificada",
  insufficient_blog_evidence:"Evidência insuficiente para concluir sobre o blog", platform_generator:"Plataforma identificada no HTML",
  complete_small_sitemap_no_blog_and_all_routes_absent:"Sitemap completo e navegação verificados sem evidência de blog"
};
const label = (value: string) => labels[value] || value;
function link(url: string | null, title: string) {
  if (!url || !/^https?:\/\//i.test(url)) return <span>Não disponível</span>;
  return <a href={url} target="_blank" rel="noreferrer">{title}</a>;
}

export function WebsiteQualification({ leadId, request, initial }: {leadId: number; request: Request; initial?: WebsiteResult | null}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Details>({result:initial || null,job_id:null,status:"idle"});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<Job | null>(null);
  useEffect(() => { if (!open && initial !== undefined) setData(current => ({...current,result:initial})); }, [initial,open]);
  useEffect(() => {
    if (!open) return;
    let stopped = false;
    async function load() {
      try {
        const next = await request<Details>(`${ROOT}/leads/${leadId}`);
        if (!stopped) setData(next);
        if (next.job_id) {
          const job = await request<Job>(`${ROOT}/jobs/${next.job_id}`);
          if (!stopped) setProgress(job);
        }
      } catch (err) { if (!stopped) setError(err instanceof Error ? err.message : "Falha ao consultar análise."); }
    }
    void load();
    const timer = window.setInterval(load, 2500);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [open, leadId, request]);
  async function analyze() {
    setBusy(true); setError("");
    try {
      const job = await request<Job>(`${ROOT}/leads/${leadId}/analyze`, {method:"POST"});
      setProgress(job); setData(current => ({...current,job_id:job.total ? job.job_id : null,status:job.status}));
    } catch (err) { setError(err instanceof Error ? err.message : "Falha ao iniciar análise."); }
    finally { setBusy(false); }
  }
  const result = data.result;
  const running = Boolean(data.job_id);
  return <section className="website-qualification" aria-label="Qualificação do site">
    <button className="secondary-button compact-button" type="button" onClick={() => setOpen(!open)} aria-expanded={open}>
      {result ? `Site: ${label(result.priority)} · ${result.cms_name || label(result.cms)}` : "Analisar site"}
    </button>
    {open && <div className="website-qualification-details">
      <h4>Site e blog</h4>
      <button type="button" className="secondary-button" disabled={busy || running} onClick={() => void analyze()}>
        {busy || running ? "Análise em andamento…" : result ? "Revalidar site" : "Analisar site agora"}
      </button>
      {error && <p role="alert">{error}</p>}
      {running && <p role="status">{progress ? `${progress.processed}/${progress.total}` : "Na fila"} · A análise não altera os dados da empresa.</p>}
      {result ? <>
        <p>Última verificação: {new Date(result.checked_at).toLocaleString()} · {label(result.validation_status)}</p>
        {result.stale && <p className="notice warning">O site foi alterado. Revalide para atualizar esta análise.</p>}
        <dl><dt>Site</dt><dd>{link(result.normalized_website, result.normalized_website || "Site")}</dd>
          <dt>Disponibilidade</dt><dd>{label(result.site_availability)}</dd><dt>CMS</dt><dd>{result.cms_name || label(result.cms)}</dd>
          <dt>WordPress</dt><dd>{label(result.wordpress_status)}</dd><dt>Blog</dt><dd>{label(result.blog_status)} · {link(result.blog_url,"Abrir blog")}</dd>
          <dt>Artigos publicados expostos</dt><dd>{result.total_posts ?? "Não disponível"}</dd>
          <dt>Última publicação verificada</dt><dd>{result.last_published_at ? new Date(result.last_published_at).toLocaleDateString() : "Não disponível"} · {result.last_post_title || "Título não disponível"} · {link(result.last_post_url,"Abrir artigo")}</dd>
          <dt>Dias sem publicação</dt><dd>{result.days_since_publication ?? "Não disponível"}</dd><dt>Prioridade</dt><dd>{label(result.priority)}</dd></dl>
        <details><summary>Evidências e limitações</summary><ul>{result.evidence.map((item,i) => <li key={i}>{label(item.reason)}{typeof item.date === "string" ? ` · ${item.date}` : ""}</li>)}</ul>
          {result.errors.length > 0 && <p>Limitações: {result.errors.map(label).join(", ")}</p>}
          <p>A inspeção pública é limitada. Datas de atualização do sitemap não são tratadas como publicação.</p></details>
      </> : <p>Sem análise anterior. Sites bloqueados ou sem evidência suficiente ficam inconclusivos.</p>}
    </div>}
  </section>;
}

export function BulkWebsiteQualification({ids, request}: {ids:number[]; request:Request}) {
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const id = window.localStorage.getItem("website-qualification-job");
    if (id) request<Job>(`${ROOT}/jobs/${id}`).then(setJob).catch(() => window.localStorage.removeItem("website-qualification-job"));
  }, [request]);
  useEffect(() => {
    if (!job || job.status === "completed") return;
    const timer = window.setInterval(() => {
      request<Job>(`${ROOT}/jobs/${job.job_id}`).then(setJob).catch(err => setError(err.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status, request]);
  const running = Boolean(job && job.status !== "completed");
  async function start() {
    setBusy(true); setError("");
    try {
      const next = await request<Job>(`${ROOT}/jobs`, {method:"POST",body:JSON.stringify({lead_ids:ids,revalidate:true})});
      setJob(next); window.localStorage.setItem("website-qualification-job", next.job_id);
    } catch (err) { setError(err instanceof Error ? err.message : "Falha ao iniciar análises."); }
    finally { setBusy(false); }
  }
  return <div><button className="secondary-button compact-button" type="button" disabled={busy || running || !ids.length || ids.length > 500} onClick={() => void start()}>
    {busy || running ? "Analisando sites…" : `Analisar sites (${ids.length})`}</button>
    {job && <p role="status">Sites: {job.processed}/{job.total} · {job.status === "completed" ? "Concluído" : "Em andamento"} · Falhas: {job.failed}{job.skipped ? ` · Já em análise: ${job.skipped}` : ""}</p>}
    {error && <p role="alert">{error}</p>}</div>;
}

export type QualificationFiltersValue = {cms:string;blog:string;priority:string;inactive_days:string};
export const emptyQualificationFilters:QualificationFiltersValue = {cms:"",blog:"",priority:"",inactive_days:""};
export function QualificationFilters({value,onChange}: {value:QualificationFiltersValue;onChange:(value:QualificationFiltersValue)=>void}) {
  return <div className="website-qualification-filters">
    {([ ["cms","CMS",["WordPress","other","unknown"]], ["blog","Blog",["detected","missing_verified","inconclusive"]],
        ["priority","Prioridade do site",["HIGH","MEDIUM","LOW","INCONCLUSIVE"]] ] as const).map(([key,title,options]) =>
      <label key={key}>{title}<select value={value[key]} onChange={e => onChange({...value,[key]:e.target.value})}><option value="">Todos</option>{options.map(option => <option key={option} value={option}>{label(option)}</option>)}</select></label>)}
    <label>Inatividade mínima (dias)<input type="number" min="0" max="36500" value={value.inactive_days} onChange={e => onChange({...value,inactive_days:e.target.value})}/></label>
  </div>;
}
