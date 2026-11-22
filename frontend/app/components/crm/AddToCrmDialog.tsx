"use client";
import { useEffect, useState } from "react";
import { ROOT, type Company, type Funnel, type Request } from "./types";
import { useDialog } from "./useDialog";

export function AddToCrmDialog({ request, initialIds = [], onClose, onAdded }: {
  request: Request; initialIds?: number[]; onClose: () => void; onAdded?: () => void;
}) {
  const [funnels, setFunnels] = useState<Funnel[]>([]);
  const [funnelId, setFunnelId] = useState(0);
  const [stageId, setStageId] = useState(0);
  const [selected, setSelected] = useState(() => new Set(initialIds));
  const [items, setItems] = useState<Company[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [niche, setNiche] = useState("");
  const [location, setLocation] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const dialog = useDialog(onClose, busy);
  const funnel = funnels.find(item => item.id === funnelId);
  useEffect(() => {
    let live = true;
    request<Funnel[]>("/api/crm/funnels").then(data => {
      if (!live) return;
      setFunnels(data); setFunnelId(data[0]?.id || 0);
    }).catch(err => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [request, retry]);
  useEffect(() => { setStageId(funnel?.stages[0]?.id || 0); }, [funnel]);
  useEffect(() => {
    let live = true;
    setLoading(true); setError("");
    const params = new URLSearchParams({ q, niche, location, offset: String(offset), limit: "30" });
    request<{ items: Company[]; total: number }>(`${ROOT}/leads?${params}`).then(data => {
      if (live) { setItems(data.items); setTotal(data.total); }
    }).catch(err => { if (live) setError(err.message); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [request, q, niche, location, offset, retry]);
  async function submit() {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await request<{ created_card_ids: number[]; skipped_lead_ids: number[] }>(`${ROOT}/cards`, {
        method: "POST", body: JSON.stringify({ lead_ids: [...selected], funnel_id: funnelId, stage_id: stageId })
      });
      setMessage(`${result.created_card_ids.length} cards adicionados; ${result.skipped_lead_ids.length} já estavam neste funil. Nenhum card existente foi alterado.`);
      setSelected(new Set()); onAdded?.();
    } catch (err) { setError(err instanceof Error ? err.message : "Falha ao adicionar cards."); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop"><section ref={dialog} className="edit-modal manual-crm-picker" role="dialog" aria-modal="true" aria-label="Adicionar ao CRM">
    <div className="panel-heading"><h2>Adicionar ao CRM</h2><button type="button" className="secondary-button" onClick={onClose} disabled={busy}>Fechar</button></div>
    <p>Selecione empresas de qualquer página. A seleção permanece ao navegar e filtrar. Limite de 1.000 por inclusão.</p>
    {error && <div role="alert" className="notice danger">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>Tentar novamente</button></div>}
    {message && <div role="status" className="notice success">{message}</div>}
    <div className="manual-crm-fields">
      <label>Funil<select value={funnelId} onChange={e => setFunnelId(Number(e.target.value))}>{funnels.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Estágio inicial<select value={stageId} onChange={e => setStageId(Number(e.target.value))}>{funnel?.stages.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      <label>Empresa<input value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} /></label>
      <label>Nicho<input list="registered-niches" value={niche} onChange={e => { setNiche(e.target.value); setOffset(0); }} /></label>
      <label>Localidade<input value={location} onChange={e => { setLocation(e.target.value); setOffset(0); }} /></label>
    </div>
    <p>{selected.size} selecionados · {total} empresas encontradas <button className="link-button" type="button" onClick={() => setSelected(new Set())}>Limpar seleção</button></p>
    {loading ? <p role="status">Carregando empresas…</p> : <div className="manual-crm-company-list">{items.map(item => <label key={item.id}>
      <input type="checkbox" aria-label={`Selecionar ${item.name}`} checked={selected.has(item.id)} disabled={busy || (!selected.has(item.id) && selected.size >= 1000)}
        onChange={e => setSelected(current => { const next = new Set(current); e.target.checked ? next.add(item.id) : next.delete(item.id); return next; })} />
      <span><strong>{item.name}</strong><small>{item.niche} · {item.location}</small></span>
    </label>)}{!items.length && <p>Nenhuma empresa encontrada.</p>}</div>}
    <div className="manual-crm-actions">
      <button type="button" className="secondary-button" disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 30))}>Página anterior</button>
      <span>Página {Math.floor(offset / 30) + 1}</span>
      <button type="button" className="secondary-button" disabled={loading || offset + 30 >= total} onClick={() => setOffset(value => value + 30)}>Próxima página</button>
      <button type="button" className="primary-button" disabled={busy || !selected.size || !stageId} onClick={submit}>{busy ? "Adicionando…" : `Adicionar ${selected.size} ao CRM`}</button>
    </div>
  </section></div>;
}
