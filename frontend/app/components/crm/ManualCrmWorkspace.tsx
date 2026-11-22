"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { AddToCrmDialog } from "./AddToCrmDialog";
import { ROOT, localDate, money, outcomeLabel, type Card, type FollowUp, type Funnel, type Request, type Stage } from "./types";
import { useDialog } from "./useDialog";

export function ManualCrmWorkspace({ request, onManageFunnels, configVersion = 0 }: { request: Request; onManageFunnels: () => void; configVersion?: number }) {
  const [funnels, setFunnels] = useState<Funnel[]>([]);
  const [funnelId, setFunnelId] = useState(0);
  const [cards, setCards] = useState<Card[]>([]);
  const [cardId, setCardId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [bucket, setBucket] = useState("overdue");
  const [follows, setFollows] = useState<FollowUp[]>([]);
  const refreshSequence = useRef(0);
  const funnel = funnels.find(item => item.id === funnelId);
  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    try {
      setError("");
      const meta = await request<Funnel[]>("/api/crm/funnels");
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      const [nextCards, nextFollows] = await Promise.all([
        funnelId ? request<Card[]>(`${ROOT}/cards?funnel_id=${funnelId}`) : Promise.resolve([]),
        request<FollowUp[]>(`${ROOT}/follow-ups?bucket=${bucket}&timezone_name=${encodeURIComponent(zone)}`)
      ]);
      if (sequence !== refreshSequence.current) return;
      setFunnels(meta); setFunnelId(current => meta.some(item => item.id === current) ? current : meta[0]?.id || 0);
      setCards(nextCards); setFollows(nextFollows);
    } catch (err) { if (sequence === refreshSequence.current) setError(err instanceof Error ? err.message : "Falha ao carregar CRM."); }
    finally { if (sequence === refreshSequence.current) setLoading(false); }
  }, [request, funnelId, bucket]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 60000);
    return () => { window.clearInterval(timer); refreshSequence.current += 1; };
  }, [refresh, configVersion]);
  return <section className="manual-crm-workspace">
    <div className="panel manual-crm-toolbar"><div><p className="eyebrow">Prospecção B2B</p><h2>CRM comercial</h2><p>Contatos e follow-ups manuais. A conexão com WhatsApp não é necessária.</p></div>
      <div className="manual-crm-actions"><label>Funil<select value={funnelId} onChange={e => { setCards([]); setFunnelId(Number(e.target.value)); }}>{funnels.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <button className="secondary-button" type="button" onClick={onManageFunnels}>Gerenciar funis</button><button className="secondary-button" type="button" onClick={() => void refresh()}>Atualizar CRM</button>
        <button className="primary-button" type="button" onClick={() => setAdding(true)}>Adicionar ao CRM</button></div></div>
    {error && <div className="notice danger" role="alert">{error}</div>}
    {loading && <p role="status">Carregando CRM…</p>}
    <section className="panel"><div className="panel-heading"><h2>Follow-ups</h2><label>Período<select value={bucket} onChange={e => setBucket(e.target.value)}><option value="overdue">Atrasados</option><option value="today">Hoje</option><option value="upcoming">Próximos</option></select></label></div>
      <p className="helper-text">Datas no seu fuso local. “Hoje” mostra os horários restantes; horários vencidos aparecem em “Atrasados”.</p>
      <div className="manual-crm-follow-list">{follows.map(item => <button className="secondary-button" type="button" key={item.id} onClick={() => setCardId(item.card_id)}><strong>{item.lead_name} · {item.title}</strong><span>{localDate(item.due_at)} · {item.funnel_name}</span></button>)}{!follows.length && <p>Nenhum follow-up neste período.</p>}</div>
    </section>
    <div className="crm-board" aria-label="Pipeline comercial">{funnel?.stages.map(stage => <section className="crm-column" key={stage.id}><div className="crm-column-heading"><h2>{stage.label}</h2><span>{cards.filter(item => item.stage_id === stage.id).length}</span></div>
      {cards.filter(item => item.stage_id === stage.id).map(item => <button className="crm-lead-card crm-lead-card-button" key={item.id} type="button" onClick={() => setCardId(item.id)}>
        <strong>{item.lead.name}</strong><span>{item.lead.niche} · {item.lead.location}</span><span>{item.lead.tags.map(tag => tag.name).join(" · ")}</span>
        <span>{money(item)}</span><span>{item.sales_outcome ? outcomeLabel(item.sales_outcome) : "Legado · venda não confirmada"}</span>
        {item.next_follow_up && <small className={Date.parse(item.next_follow_up.due_at) < Date.now() ? "manual-crm-overdue" : ""}>Próximo: {item.next_follow_up.title} · {localDate(item.next_follow_up.due_at)}</small>}
      </button>)}
    </section>)}</div>
    {!loading && !funnels.length && <p className="empty-state">Nenhum funil disponível. Cadastre um funil para começar.</p>}
    {adding && <AddToCrmDialog request={request} onClose={() => setAdding(false)} onAdded={() => void refresh()} />}
    {cardId !== null && <CrmLeadDetails cardId={cardId} request={request} stages={funnels.flatMap(item => item.stages)} onClose={() => setCardId(null)} onChanged={() => void refresh()} />}
  </section>;
}

export function CrmLeadDetails({ cardId, request, stages, onClose, onChanged }: {
  cardId: number; request: Request; stages: Stage[]; onClose: () => void; onChanged: () => void;
}) {
  const [data, setData] = useState<Card | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [body, setBody] = useState("");
  const [kind, setKind] = useState("note");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [rescheduling, setRescheduling] = useState<FollowUp | null>(null);
  const [newDue, setNewDue] = useState("");
  const close = () => {
    if ((body.trim() || title.trim() || newDue) && !window.confirm("Há um registro ou follow-up não salvo. Fechar mesmo assim?")) return;
    onClose();
  };
  const dialog = useDialog(close, busy);
  const load = useCallback(async () => {
    const next = await request<Card>(`${ROOT}/cards/${cardId}`); setData(next);
  }, [request, cardId]);
  useEffect(() => { void load().catch(err => setError(err.message)); }, [load]);
  async function mutate(path: string, method: string, payload: unknown, done?: () => void) {
    setBusy(true); setError("");
    try { await request(path, { method, body: JSON.stringify(payload) }); await load(); onChanged(); done?.(); }
    catch (err) { setError(err instanceof Error ? err.message : "Não foi possível salvar."); }
    finally { setBusy(false); }
  }
  const timeline = [
    ...(data?.activities || []).map(item => ({ key: `a${item.id}`, at: item.created_at,
      text: item.body + (item.details?.previous_due_at ? ` Data anterior: ${localDate(item.details.previous_due_at)}.` : "") +
        (item.details?.due_at ? ` Data agendada: ${localDate(item.details.due_at)}.` : ""),
      author: item.actor, kind: ({ note: "Nota", call: "Ligação", whatsapp: "Contato WhatsApp", meeting: "Reunião", system: "Registro" } as Record<string,string>)[item.kind] })),
    ...(data?.stage_history || []).map(item => ({ key: `s${item.id}`, at: item.changed_at, text: `${item.from_stage} → ${item.to_stage}`, author: item.changed_by === "ai" ? "IA (histórico)" : "Manual (histórico)", kind: "Mudança de estágio" }))
  ].sort((a,b) => Date.parse(b.at) - Date.parse(a.at));
  return <div className="modal-backdrop"><section ref={dialog} className="edit-modal manual-crm-details" role="dialog" aria-modal="true" aria-label="Detalhes comerciais do lead">
    <div className="panel-heading"><h2>{data?.lead.name || "Detalhes comerciais"}</h2><div className="manual-crm-actions"><button className="secondary-button" type="button" disabled={busy} onClick={() => { setError(""); void load().catch(err => setError(err.message)); }}>Atualizar detalhes</button><button className="secondary-button" type="button" disabled={busy} onClick={close}>Fechar</button></div></div>
    {error && <div className="notice danger" role="alert">{error}</div>}
    {!data ? <p role="status">Carregando detalhes…</p> : <>
      <div className="manual-crm-details-grid"><section className="manual-crm-section"><h3>Empresa e contato</h3><p>{data.lead.niche} · {data.lead.location}</p><p>{data.lead.address}</p><p>{data.lead.phone} · {data.lead.email}</p>
        <p>{data.lead.tags.length ? data.lead.tags.map(tag => <span className="lead-tag-pill" style={{ background: tag.color }} key={tag.id}>{tag.name}</span>) : "Sem tags"}</p>
        <div className="manual-crm-actions">{data.lead.call_url && <a className="secondary-button" href={data.lead.call_url}>Ligar</a>}{data.lead.whatsapp_url && <a className="secondary-button" href={data.lead.whatsapp_url} target="_blank" rel="noreferrer">Abrir WhatsApp</a>}{data.lead.email && <a className="secondary-button" href={`mailto:${data.lead.email}`}>Enviar e-mail</a>}{data.lead.website && <a className="secondary-button" href={data.lead.website} target="_blank" rel="noreferrer">Visitar site</a>}</div>
        <p className="helper-text">Abrir um contato não registra envio, ligação ou resposta. Registre a interação após realizá-la.</p>
        <details><summary>Origem da coleta</summary><p>Busca #{data.lead.provenance.run_id} · {data.lead.provenance.niche} · {data.lead.provenance.location}</p><p>{localDate(data.lead.provenance.created_at)} · {data.lead.provenance.status}</p><p>Dados de origem preservados; alterações comerciais não mudam a busca.</p></details>
      </section><section className="manual-crm-section"><h3>Oportunidade</h3><p>{data.funnel_name} · {data.stage_label}</p>
        {!data.managed_manually ? <><p>Card legado. “Convertido” não representa receita confirmada. Assumir a gestão manual preserva notas e histórico e inicia o resultado como aberto.</p><button className="primary-button" type="button" disabled={busy} onClick={() => void mutate(`${ROOT}/cards/${data.id}`, "PATCH", { version: data.version, managed_manually: true })}>Assumir gestão manual</button></> : <OpportunityForm key={`${data.id}-${data.version}`} data={data} stages={stages} busy={busy} onSave={payload => void mutate(`${ROOT}/cards/${data.id}`, "PATCH", payload)} />}
      </section></div>
      {data.qualification_notes && <section className="manual-crm-section"><h3>Notas anteriores preservadas</h3><p className="manual-crm-prewrap">{data.qualification_notes}</p><small>Registro legado, sem autoria ou data de criação individual disponíveis.</small></section>}
      <section className="manual-crm-section"><h3>Próximas ações</h3>
        {data.follow_ups?.map(item => <article className="manual-crm-follow-row" key={item.id}><div><strong>{item.title}</strong><p>{localDate(item.due_at)} · {({ pending: "Pendente", completed: "Concluído", cancelled: "Cancelado" } as Record<string,string>)[item.status]}</p></div>
          {item.status === "pending" && data.managed_manually && <div className="manual-crm-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void mutate(`${ROOT}/follow-ups/${item.id}`, "PATCH", { action: "complete", version: item.version })}>Concluir</button><button type="button" className="secondary-button" disabled={busy} onClick={() => { setRescheduling(item); setNewDue(""); }}>Reagendar</button><button type="button" className="secondary-button" disabled={busy} onClick={() => void mutate(`${ROOT}/follow-ups/${item.id}`, "PATCH", { action: "cancel", version: item.version })}>Cancelar follow-up</button></div>}
        </article>)}
        {rescheduling && <form className="manual-crm-fields" onSubmit={e => { e.preventDefault(); void mutate(`${ROOT}/follow-ups/${rescheduling.id}`, "PATCH", { action: "reschedule", version: rescheduling.version, due_at: new Date(newDue).toISOString() }, () => setRescheduling(null)); }}><label>Nova data local<input required type="datetime-local" value={newDue} onChange={e => setNewDue(e.target.value)} /></label><button className="primary-button" disabled={busy}>Salvar reagendamento</button><button className="secondary-button" type="button" onClick={() => setRescheduling(null)}>Voltar</button></form>}
        {data.managed_manually && <form className="manual-crm-fields" onSubmit={e => { e.preventDefault(); void mutate(`${ROOT}/cards/${data.id}/follow-ups`, "POST", { title, due_at: new Date(due).toISOString() }, () => { setTitle(""); setDue(""); }); }}><label>Próxima ação<input required maxLength={255} value={title} onChange={e => setTitle(e.target.value)} /></label><label>Data e hora local<input required type="datetime-local" value={due} onChange={e => setDue(e.target.value)} /></label><button className="primary-button" disabled={busy}>Agendar follow-up</button></form>}
      </section>
      <section className="manual-crm-section"><h3>Histórico de atividades</h3>
        {data.managed_manually && <form onSubmit={e => { e.preventDefault(); void mutate(`${ROOT}/cards/${data.id}/activities`, "POST", { kind, body }, () => setBody("")); }}><div className="manual-crm-fields"><label>Tipo de atividade<select value={kind} onChange={e => setKind(e.target.value)}><option value="note">Nota</option><option value="call">Ligação</option><option value="whatsapp">Contato WhatsApp</option><option value="meeting">Reunião</option></select></label><label>Registro da interação<textarea required maxLength={5000} value={body} onChange={e => setBody(e.target.value)} /></label></div><button className="primary-button" disabled={busy}>Registrar atividade</button><p className="helper-text">Novos registros são acrescentados à linha do tempo. Notas anteriores não são substituídas.</p></form>}
        <ol className="manual-crm-timeline">{timeline.map(item => <li key={item.key}><strong>{item.kind}</strong><p className="manual-crm-prewrap">{item.text}</p><small>{localDate(item.at)} · {item.author}</small></li>)}</ol>{!timeline.length && <p>Nenhuma atividade registrada.</p>}
      </section>
    </>}
  </section></div>;
}

function OpportunityForm({ data, stages, busy, onSave }: { data: Card; stages: Stage[]; busy: boolean; onSave: (payload: unknown) => void }) {
  const [stageId, setStageId] = useState(data.stage_id);
  const [value, setValue] = useState(data.estimated_value || "");
  const [currency, setCurrency] = useState(data.currency);
  const [outcome, setOutcome] = useState(data.sales_outcome || "open");
  const [reason, setReason] = useState(data.lost_reason || "");
  return <form onSubmit={e => { e.preventDefault(); onSave({ version: data.version, stage_id: stageId, estimated_value: value || null, currency, sales_outcome: outcome, lost_reason: outcome === "lost" ? reason : null }); }}>
    <div className="manual-crm-fields"><label>Estágio<select value={stageId} onChange={e => setStageId(Number(e.target.value))}>{stages.filter(item => item.funnel_id === data.funnel_id).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      <label>Valor estimado da proposta<input required={outcome === "won"} type="number" min="0" step="0.01" value={value} onChange={e => setValue(e.target.value)} /></label><label>Moeda<select value={currency} onChange={e => setCurrency(e.target.value)}>{["BRL","USD","EUR","GBP","CAD","AUD"].map(item => <option key={item}>{item}</option>)}</select></label>
      <label>Resultado comercial<select value={outcome} onChange={e => setOutcome(e.target.value as "open" | "won" | "lost")}><option value="open">Aberta</option><option value="won">Ganha</option><option value="lost">Perdida</option></select></label>
      {outcome === "lost" && <label>Motivo da perda<textarea required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label>}
    </div><button className="primary-button" disabled={busy}>Salvar oportunidade</button>
    <p className="helper-text">O resultado é confirmado manualmente e não é inferido do nome do estágio. Ações pendentes continuam visíveis até serem concluídas ou canceladas.</p>
  </form>;
}
