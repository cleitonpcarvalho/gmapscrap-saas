"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Edit3, Trash2, X } from "lucide-react";

export type Niche = { id: number; name: string; created_at: string };

export function NicheManager({ niches, initialName, request, onChange, onSelect, onClose }: {
  niches: Niche[];
  initialName: string;
  request: <T>(path: string, init?: RequestInit) => Promise<T>;
  onChange: (niches: Niche[]) => void;
  onSelect: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<number | null>(null);

  async function reload() {
    onChange(await request<Niche[]>("/api/niches"));
  }

  useEffect(() => {
    reload().catch((reason) => setError(reason instanceof Error ? reason.message : "Não foi possível carregar os nichos."));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await request<Niche>(editingId === null ? "/api/niches" : `/api/niches/${editingId}`, {
        method: editingId === null ? "POST" : "PATCH",
        body: JSON.stringify({ name })
      });
      // Keep a successful mutation visible even if the subsequent refresh fails.
      onChange([...niches.filter((item) => item.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name)));
      onSelect(saved.name);
      setName("");
      setEditingId(null);
      setMessage("Nicho salvo.");
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
      if (editingId === id) { setEditingId(null); setName(""); }
      setDeleting(null);
      setMessage("Nicho excluído.");
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível excluir o nicho.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="edit-modal tag-manager-modal" role="dialog" aria-modal="true" aria-labelledby="niche-manager-title">
        <div className="panel-heading">
          <h2 id="niche-manager-title">Gerenciar nichos</h2>
          <button aria-label="Fechar nichos" className="icon-button" disabled={busy} onClick={onClose} type="button"><X size={18} /></button>
        </div>
        <p className="modal-helper">Os nichos ficam disponíveis como sugestões nas buscas. Alterações no cadastro preservam os leads e o histórico.</p>
        {error ? <div className="notice danger" role="alert">{error}</div> : null}
        {message ? <div className="notice success" role="status">{message}</div> : null}
        <form className="search-form" onSubmit={save}>
          <label>
            {editingId === null ? "Novo nicho" : "Editar nicho"}
            <input autoFocus required minLength={2} maxLength={255} value={name} onChange={(event) => setName(event.target.value)} disabled={busy} placeholder="Ex.: Brindes" />
          </label>
          <div className="modal-actions">
            {editingId !== null ? <button className="secondary-button" disabled={busy} type="button" onClick={() => { setEditingId(null); setName(""); }}>Cancelar edição</button> : null}
            <button className="primary-button" disabled={busy} type="submit">{busy ? "Salvando…" : editingId === null ? "Criar nicho" : "Salvar nicho"}</button>
          </div>
        </form>
        <label>Buscar nichos<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Digite para filtrar" /></label>
        <div className="tag-manager-list">
          {niches.length === 0 ? <p className="empty-state">Nenhum nicho cadastrado.</p> : null}
          {niches.length > 0 && !niches.some((item) => item.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())) ? <p className="empty-state">Nenhum nicho encontrado.</p> : null}
          {niches.filter((item) => item.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())).map((item) => (
            <article className="tag-manager-row" key={item.id}>
              <strong>{item.name}</strong>
              <div className="modal-actions">
                <button type="button" className="secondary-button" disabled={busy} onClick={() => { onSelect(item.name); onClose(); }}>Usar</button>
                <button type="button" className="icon-button" aria-label={`Editar ${item.name}`} disabled={busy} onClick={() => { setEditingId(item.id); setName(item.name); setError(""); setMessage(""); }}><Edit3 size={16} /></button>
                <button type="button" className="icon-button" aria-label={`Excluir ${item.name}`} disabled={busy} onClick={() => setDeleting(item.id)}><Trash2 size={16} /></button>
              </div>
              {deleting === item.id ? <div className="notice warning">
                Excluir “{item.name}” das sugestões?
                <div className="modal-actions">
                  <button type="button" className="secondary-button" disabled={busy} onClick={() => setDeleting(null)}>Cancelar</button>
                  <button type="button" className="danger-button" disabled={busy} onClick={() => remove(item.id)}>Confirmar exclusão</button>
                </div>
              </div> : null}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
