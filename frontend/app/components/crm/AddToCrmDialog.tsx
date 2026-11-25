"use client";
import { useEffect, useRef, useState } from "react";
import { ROOT, type Company, type Funnel, type Request } from "./types";
import { useDialog } from "./useDialog";
import { usePipelineSelection } from "./usePipelineSelection";

export function AddToCrmDialog({ request, initialIds = [], onClose, onAdded }: {
  request: Request; initialIds?: number[]; onClose: () => void; onAdded?: () => void;
}) {
  const [funnels, setFunnels] = useState<Funnel[] | null>(null);
  const [funnelId, setFunnelId, needsMetadata] = usePipelineSelection(funnels);
  const [stageId, setStageId] = useState(0);
  const [selected, setSelected] = useState(() => new Set([...new Set(initialIds.filter(id => Number.isInteger(id) && id > 0))].slice(0, 1000)));
  const [items, setItems] = useState<Company[]>([]);
  const [total, setTotal] = useState(0);
  const [available, setAvailable] = useState(0);
  const [matching, setMatching] = useState(0);
  const [showAdded, setShowAdded] = useState(false);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [niche, setNiche] = useState("");
  const [location, setLocation] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const operation = useRef(false);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [revision, setRevision] = useState(0);
  const [checkedFunnel, setCheckedFunnel] = useState(0);
  const [loadedQuery, setLoadedQuery] = useState("");
  const selectedSnapshot = useRef(selected);
  selectedSnapshot.current = selected;
  const currentFunnel = useRef(funnelId);
  currentFunnel.current = funnelId;
  const locked = busy || selecting;
  const eligibleSelection = funnelId > 0 && checkedFunnel === funnelId;
  const queryKey = JSON.stringify([funnelId, q, niche, location, offset, showAdded]);
  const pageLoading = loading || loadedQuery !== queryKey;
  const dialog = useDialog(onClose, locked);
  const funnel = funnels?.find(item => item.id === funnelId);
  useEffect(() => {
    let live = true;
    request<Funnel[]>("/api/crm/funnels").then(data => {
      if (!live) return;
      setFunnels([...data]);
    }).catch(err => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [request, retry]);
  useEffect(() => {
    if (!needsMetadata) return;
    let live = true;
    request<Funnel[]>("/api/crm/funnels").then(data => { if (live) setFunnels([...data]); })
      .catch(err => { if (live) setError(err instanceof Error ? err.message : "Falha ao atualizar funis."); });
    return () => { live = false; };
  }, [request, needsMetadata]);
  useEffect(() => { setStageId(funnel?.stages[0]?.id || 0); }, [funnel]);
  useEffect(() => {
    let live = true;
    setCheckedFunnel(0); setOffset(0);
    if (!funnelId) return;
    const ids = [...selectedSnapshot.current];
    if (!ids.length) { setCheckedFunnel(funnelId); return; }
    request<{ lead_ids: number[] }>(`${ROOT}/lead-eligibility`, {
      method: "POST", body: JSON.stringify({ funnel_id: funnelId, lead_ids: ids })
    }).then(result => {
      if (!live) return;
      const eligible = new Set(result.lead_ids);
      setSelected(current => new Set([...current].filter(id => eligible.has(id)))); setCheckedFunnel(funnelId);
      if (result.lead_ids.length < ids.length) setMessage(`${ids.length - result.lead_ids.length} seleções removidas: empresas já adicionadas a este funil ou indisponíveis.`);
    }).catch(err => { if (live) setError(err instanceof Error ? err.message : "Falha ao verificar a seleção."); });
    return () => { live = false; };
  }, [request, funnelId, retry, revision]);
  useEffect(() => { setMessage(""); }, [funnelId]);
  useEffect(() => {
    let live = true;
    if (!funnelId) return;
    setLoading(true); setError("");
    const params = new URLSearchParams({ q, niche, location, offset: String(offset), limit: "30", funnel_id: String(funnelId), show_added: String(showAdded) });
    request<{ items: Company[]; total: number; available_total: number; matching_total: number }>(`${ROOT}/leads?${params}`).then(data => {
      if (live) {
        if (offset > 0 && offset >= data.total) { setOffset(0); return; }
        setItems(data.items); setTotal(data.total); setAvailable(data.available_total); setMatching(data.matching_total); setLoadedQuery(queryKey);
        const imported = new Set(data.items.filter(item => item.already_in_pipeline).map(item => item.id));
        if (imported.size) setSelected(current => new Set([...current].filter(id => !imported.has(id))));
      }
    }).catch(err => { if (live) setError(err.message); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [request, q, niche, location, offset, retry, revision, funnelId, showAdded, queryKey]);
  async function selectAll() {
    if (operation.current || !eligibleSelection || pageLoading) return;
    operation.current = true; setSelecting(true); setError(""); setMessage("");
    try {
      const params = new URLSearchParams({ q, niche, location, funnel_id: String(funnelId) });
      const result = await request<{ lead_ids: number[]; total: number }>(`${ROOT}/lead-selection?${params}`);
      if (currentFunnel.current !== funnelId) return;
      const next = new Set(selected);
      for (const id of result.lead_ids) { if (next.size >= 1000) break; next.add(id); }
      setSelected(next);
      const remaining = result.total - result.lead_ids.filter(id => next.has(id)).length;
      setMessage(remaining > 0 ? "Limite de 1.000 seleções atingido. Nem todas as empresas deste filtro foram selecionadas; desmarque empresas para selecionar outras." : "Todas as empresas deste filtro foram selecionadas. Clique em Adicionar ao CRM para confirmar.");
    } catch (err) { if (currentFunnel.current === funnelId) setError(err instanceof Error ? err.message : "Falha ao selecionar empresas."); }
    finally { operation.current = false; setSelecting(false); }
  }
  async function submit() {
    if (operation.current || !eligibleSelection || pageLoading) return;
    operation.current = true;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await request<{ created_card_ids: number[]; skipped_lead_ids: number[] }>(`${ROOT}/cards`, {
        method: "POST", body: JSON.stringify({ lead_ids: [...selected], funnel_id: funnelId, stage_id: stageId })
      });
      setMessage(`${result.created_card_ids.length} cards adicionados; ${result.skipped_lead_ids.length} já estavam neste funil. Nenhum card existente foi alterado.`);
      setSelected(new Set()); setLoading(true); setRevision(value => value + 1); onAdded?.();
    } catch (err) { setError(err instanceof Error ? err.message : "Falha ao adicionar cards."); }
    finally { operation.current = false; setBusy(false); }
  }
  return <div className="modal-backdrop"><section ref={dialog} className="edit-modal manual-crm-picker" role="dialog" aria-modal="true" aria-label="Adicionar ao CRM">
    <div className="panel-heading"><h2>Adicionar ao CRM</h2><button type="button" className="secondary-button" onClick={onClose} disabled={locked}>Fechar</button></div>
    <p>Selecione empresas de qualquer página. A seleção permanece ao navegar e filtrar. Limite de 1.000 por inclusão.</p>
    {error && <div role="alert" className="notice danger">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>Tentar novamente</button></div>}
    {message && <div role="status" className="notice success">{message}</div>}
    <fieldset className="manual-crm-fields" disabled={locked}>
      <label>Funil<select value={funnelId} disabled={!funnelId || !funnels?.length} onChange={e => setFunnelId(Number(e.target.value))}>{!funnelId && <option value={0}>{funnels?.length ? "Validando funil…" : funnels === null ? "Carregando funis…" : "Nenhum funil disponível"}</option>}{funnels?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Estágio inicial<select value={stageId} onChange={e => setStageId(Number(e.target.value))}>{funnel?.stages.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      <label>Empresa<input value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} /></label>
      <label>Nicho<input list="registered-niches" value={niche} onChange={e => { setNiche(e.target.value); setOffset(0); }} /></label>
      <label>Localidade<input value={location} onChange={e => { setLocation(e.target.value); setOffset(0); }} /></label>
    </fieldset>
    <label className="checkbox-label"><input type="checkbox" disabled={locked} checked={showAdded} onChange={e => { setShowAdded(e.target.checked); setOffset(0); }} />Mostrar já adicionados</label>
    <p aria-live="polite">{selected.size} selecionados · {pageLoading ? "Atualizando disponibilidade…" : `${available} disponíveis de ${matching} empresas encontradas`}</p>
    {!eligibleSelection && funnelId > 0 && <p role="status">Verificando seleção para este funil…</p>}
    <div className="manual-crm-actions"><button className="secondary-button" type="button" disabled={locked || !eligibleSelection || pageLoading || selected.size >= 1000 || !available} onClick={() => void selectAll()}>{selecting ? "Selecionando…" : "Selecionar todos"}</button>
      <button className="secondary-button" type="button" disabled={locked || !eligibleSelection || !selected.size} onClick={() => { setSelected(new Set()); setMessage(""); }}>Desmarcar todos</button></div>
    {selecting && <p role="status">Selecionando empresas de todas as páginas…</p>}
    {!funnelId ? <p>Escolha um funil disponível para consultar empresas.</p> : pageLoading ? <p role="status">Carregando empresas…</p> : <div className="manual-crm-company-list">{items.map(item => <label key={item.id}>
      <input type="checkbox" aria-label={`Selecionar ${item.name}`} checked={!item.already_in_pipeline && selected.has(item.id)} disabled={locked || !eligibleSelection || item.already_in_pipeline || (!selected.has(item.id) && selected.size >= 1000)}
        onChange={e => setSelected(current => { const next = new Set(current); e.target.checked ? next.add(item.id) : next.delete(item.id); return next; })} />
      <span><strong>{item.name}</strong><small>{item.niche} · {item.location}</small>{item.already_in_pipeline && <small>Já adicionado a este funil</small>}</span>
    </label>)}{!items.length && <p>Nenhuma empresa encontrada.</p>}</div>}
    <div className="manual-crm-actions">
      <button type="button" className="secondary-button" disabled={locked || pageLoading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 30))}>Página anterior</button>
      <span>Página {Math.floor(offset / 30) + 1}</span>
      <button type="button" className="secondary-button" disabled={locked || pageLoading || offset + 30 >= total} onClick={() => setOffset(value => value + 30)}>Próxima página</button>
      <button type="button" className="primary-button" disabled={locked || !eligibleSelection || pageLoading || !selected.size || !funnel?.stages.some(item => item.id === stageId)} onClick={submit}>{busy ? "Adicionando…" : `Adicionar ${selected.size} ao CRM`}</button>
    </div>
  </section></div>;
}
