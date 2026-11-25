"use client";
import { useState } from "react";
import type { Company } from "./types";

export function CompanyEditor({ company, busy, onSave, onCancel }: {
  company: Company; busy: boolean; onSave: (payload: unknown) => void; onCancel: () => void;
}) {
  // Keep the opening snapshot/version even if another section reloads details.
  // Otherwise an old draft could silently inherit a newer concurrency token.
  const [snapshot] = useState(company);
  company = snapshot;
  const profile = company.commercial_profile!;
  const [values, setValues] = useState({
    name: company.name, phone: company.phone, email: company.email, website: company.website,
    address: company.address, niche: company.niche, location: company.location,
    contact_name: profile.contact_name || "", contact_phone: profile.contact_phone || "", contact_email: profile.contact_email || ""
  });
  function save() {
    // Use the established lead PATCH and its company/site/email validation.
    // Never send its legacy niche/location fields: those change SearchRun.
    const payload: Record<string, unknown> = {};
    for (const key of ["name", "phone", "email", "website", "address"] as const) {
      if (values[key].trim() !== company[key]) payload[key] = values[key].trim();
    }
    const commercial: Record<string, unknown> = { version: profile.version };
    if (values.niche.trim() !== company.niche) commercial.niche_override = values.niche.trim() || null;
    if (values.location.trim() !== company.location) commercial.location_override = values.location.trim() || null;
    for (const key of ["contact_name", "contact_phone", "contact_email"] as const) {
      if (values[key].trim() !== (profile[key] || "")) commercial[key] = values[key].trim() || null;
    }
    payload.commercial_profile = commercial;
    onSave(payload);
  }
  const field = (key: keyof typeof values, label: string, maxLength: number, type = "text", required = false) =>
    <label key={key}>{label}<input type={type} required={required} maxLength={maxLength} value={values[key]}
      onChange={e => setValues(current => ({ ...current, [key]: e.target.value }))} /></label>;
  return <form aria-label="Editar empresa" onSubmit={e => { e.preventDefault(); save(); }}>
    <fieldset className="manual-crm-fields" disabled={busy}>
      {field("name", "Nome da empresa", 255, "text", true)}
      {field("phone", "Telefone principal", 80, "tel")}
      {field("email", "E-mail principal", 255, "email")}
      {field("website", "Site", 500)}
      {field("address", "Endereço", 1000)}
      {field("niche", "Nicho comercial", 255)}
      {field("location", "Localidade comercial", 255)}
    </fieldset>
    <p className="helper-text">Nicho e localidade são classificações comerciais. Deixe em branco para usar a origem da coleta. A busca histórica é preservada.</p>
    <h4>Representante da empresa</h4>
    <p className="helper-text">Pessoa de contato do prospect, separada dos dados principais da empresa e do vendedor do CRM. Use código do país e DDD no telefone.</p>
    <fieldset className="manual-crm-fields" disabled={busy}>
      {field("contact_name", "Nome do contato", 255)}
      {field("contact_phone", "Telefone do contato", 80, "tel")}
      {field("contact_email", "E-mail do contato", 255, "email")}
    </fieldset>
    <p className="helper-text">Estas informações são compartilhadas entre as oportunidades desta empresa.</p>
    <div className="manual-crm-actions"><button className="primary-button" disabled={busy}>{busy ? "Salvando empresa…" : "Salvar empresa"}</button>
      <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>Cancelar edição</button></div>
  </form>;
}
