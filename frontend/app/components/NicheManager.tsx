"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Edit3, Plus, RefreshCw, Search, Tags, Trash2, X } from "lucide-react";

export type Niche = { id: number; name: string; created_at: string };
export type NicheRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

type Props = {
  niches: Niche[];
  initialName?: string;
  variant?: "dialog" | "page";
  request: NicheRequest;
  onChange: (niches: Niche[]) => void;
  onSelect: (name: string) => void;
  onClose?: () => void;
};

export function NicheManager({ niches, initialName = "", variant = "dialog", request, onChange, onSelect, onClose }: Props) {
  const [name, setName] = useState(initialName);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<number | null>(null);
  const loadSequence = useRef(0);
  const isPage = variant === "page";
  const filtered = niches.filter((item) => item.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));

  const reload = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError("");
    try {
      const items = await request<Niche[]>("/api/niches");
      if (sequence === loadSequence.current) onChange(items);
    } catch (reason) {
      if (sequence === loadSequence.current) {
        setError(reason instanceof Error ? reason.message : "Não foi possível carregar os nichos. Tente atualizar a lista.");
      }
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [request, onChange]);

  useEffect(() => {
    void reload();
    return () => { loadSequence.current += 1; };
  }, [reload]);

  function resetEditor() {
    setName("");
    setEditingId(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const normalized = name.trim().replace(/\s+/g, " ");
    if (normalized.length < 2 || normalized.length > 255) {
      setError("Informe um nicho com 2 a 255 caracteres.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await request<Niche>(editingId === null ? "/api/niches" : `/api/niches/${editingId}`, {
        method: editingId === null ? "POST" : "PATCH",
        body: JSON.stringify({ name: normalized })
      });
      // Retain the successful change even when a later list refresh fails.
      onChange([...niches.filter((item) => item.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name)));
      if (!isPage) onSelect(saved.name);
      resetEditor();
      setMessage("Nicho salvo. As sugestões da web e do aplicativo usam este cadastro.");
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível salvar o nicho.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request(`/api/niches/${id}`, { method: "DELETE" });
      onChange(niches.filter((item) => item.id !== id));
      if (editingId === id) resetEditor();
      setDeleting(null);
      setMessage("Nicho excluído das sugestões. Os leads e o histórico foram preservados.");
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível excluir o nicho.");
    } finally {
      setBusy(false);
    }
  }

  const content = (
    <>
      {!isPage ? <div className="panel-heading">
        <h2 id="niche-manager-title">Gerenciar nichos</h2>
        <button aria-label="Fechar nichos" className="icon-button" disabled={busy} onClick={onClose} type="button"><X size={18} /></button>
      </div> : null}
      <p className="niche-intro">Organize os nichos usados nas sugestões da web e do aplicativo desktop. Alterações neste cadastro preservam os leads e o histórico de buscas.</p>
      {error ? <div className="notice danger" role="alert">{error}</div> : null}
      {message ? <div className="notice success" role="status">{message}</div> : null}
      <div className="niche-manager-grid">
        <section className="panel niche-editor" aria-labelledby="niche-editor-title">
          <div className="panel-heading">
            <div><p className="eyebrow">Cadastro</p><h2 id="niche-editor-title">{editingId === null ? "Novo nicho" : "Editar nicho"}</h2></div>
            {editingId === null ? <Plus size={20} /> : <Edit3 size={20} />}
          </div>
          <form className="search-form" onSubmit={save}>
            <label>
              Nome do nicho
              <input autoFocus={!isPage} required minLength={2} maxLength={255} value={name} onChange={(event) => setName(event.target.value)} disabled={busy || loading} placeholder="Ex.: Brindes" />
            </label>
            <p className="niche-helper">Use um nome claro. Espaços extras são removidos e nomes repetidos não são permitidos.</p>
            <div className="niche-form-actions">
              <button className="primary-button" disabled={busy || loading} type="submit">{busy ? "Salvando…" : editingId === null ? "Adicionar nicho" : "Salvar alterações"}</button>
              {editingId !== null ? <button className="secondary-button" disabled={busy} type="button" onClick={resetEditor}>Cancelar edição</button> : null}
            </div>
          </form>
        </section>
        <section className="panel niche-list-panel" aria-labelledby="niche-list-title" aria-busy={loading || busy}>
          <div className="panel-heading">
            <div><p className="eyebrow">Biblioteca</p><h2 id="niche-list-title">Nichos cadastrados</h2></div>
            <button className="secondary-button" type="button" disabled={loading || busy} onClick={() => void reload()}>
              <RefreshCw className={loading ? "spin" : undefined} size={16} /> Atualizar nichos
            </button>
          </div>
          <label className="niche-search">
            Buscar nichos
            <span><Search size={17} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Digite para filtrar" /></span>
          </label>
          <p className="niche-list-count" aria-live="polite">{loading ? "Carregando nichos…" : `${filtered.length} de ${niches.length} ${niches.length === 1 ? "nicho" : "nichos"}`}</p>
          <div className="niche-list">
            {!loading && niches.length === 0 ? <div className="niche-empty"><Tags size={28} /><strong>Nenhum nicho cadastrado</strong><p>Adicione o primeiro nicho para disponibilizá-lo nas sugestões.</p></div> : null}
            {!loading && niches.length > 0 && filtered.length === 0 ? <div className="niche-empty"><Search size={28} /><strong>Nenhum nicho encontrado</strong><p>Tente buscar por outra parte do nome.</p></div> : null}
            {filtered.map((item) => (
              <article className="niche-row" key={item.id}>
                <strong>{item.name}</strong>
                <div className="niche-row-actions">
                  <button type="button" className="secondary-button" disabled={busy} onClick={() => { onSelect(item.name); onClose?.(); }}>Usar na busca</button>
                  <button type="button" className="icon-button" aria-label={`Editar ${item.name}`} disabled={busy} onClick={() => { setEditingId(item.id); setName(item.name); setDeleting(null); setError(""); setMessage(""); }}><Edit3 size={16} /></button>
                  <button type="button" className="icon-button" aria-label={`Excluir ${item.name}`} disabled={busy} onClick={() => setDeleting(item.id)}><Trash2 size={16} /></button>
                </div>
                {deleting === item.id ? <div className="notice warning niche-delete-confirmation" role="alertdialog" aria-labelledby={`niche-delete-${item.id}`}>
                  <strong id={`niche-delete-${item.id}`}>Excluir “{item.name}” das sugestões?</strong>
                  <p>Os leads e as buscas anteriores continuam com seus nomes originais.</p>
                  <div className="niche-row-actions">
                    <button autoFocus type="button" className="secondary-button" disabled={busy} onClick={() => setDeleting(null)}>Cancelar exclusão</button>
                    <button type="button" className="danger-button" disabled={busy} onClick={() => void remove(item.id)}>Confirmar exclusão</button>
                  </div>
                </div> : null}
              </article>
            ))}
          </div>
        </section>
      </div>
    </>
  );

  if (isPage) return <section className="niche-management-page" aria-label="Gestão de nichos">{content}</section>;
  return <div className="modal-backdrop"><section className="edit-modal niche-manager-modal" role="dialog" aria-modal="true" aria-labelledby="niche-manager-title">{content}</section></div>;
}
