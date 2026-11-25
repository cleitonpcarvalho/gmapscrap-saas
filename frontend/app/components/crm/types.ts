export type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
export type Stage = { id: number; funnel_id: number; key: string; label: string; color: string; position: number };
export type Funnel = { id: number; name: string; stages: Stage[] };
export type CompanyProfile = {
  available: boolean; version: number; niche_override: string | null; location_override: string | null;
  contact_name: string | null; contact_phone: string | null; contact_email: string | null;
  contact_call_url: string; contact_whatsapp_url: string; contact_email_url: string;
};
export type Company = {
  id: number; name: string; niche: string; location: string; address: string; phone: string; email: string;
  website: string; call_url: string; whatsapp_url: string; tags: { id: number; name: string; color: string }[];
  provenance: { run_id: number; niche: string; location: string; created_at: string; status: string };
  commercial_profile?: CompanyProfile;
  already_in_pipeline?: boolean;
};
export type FollowUp = {
  id: number; card_id: number; title: string; due_at: string; status: string; version: number;
  lead_name?: string; funnel_name?: string;
};
export type Activity = { id: number; kind: string; body: string; actor: string; created_at: string; details?: { due_at?: string; previous_due_at?: string } | null };
export type Card = {
  id: number; lead: Company; funnel_id: number; funnel_name: string; stage_id: number; stage_label: string; stage_color: string;
  managed_manually: boolean; qualification_notes: string | null; estimated_value: string | null; currency: string;
  sales_outcome: "open" | "won" | "lost" | null; lost_reason: string | null; closed_at: string | null; version: number;
  position?: number | null;
  next_follow_up: FollowUp | null; activities?: Activity[]; follow_ups?: FollowUp[];
  stage_history?: { id: number; from_stage: string; to_stage: string; changed_by: string; changed_at: string }[];
};
export const ROOT = "/api/crm/manual";
export const localDate = (value: string) => new Date(value).toLocaleString();
export const money = (card: Card) => card.estimated_value === null ? "Valor não informado" :
  new Intl.NumberFormat(undefined, { style: "currency", currency: card.currency }).format(Number(card.estimated_value));
export const outcomeLabel = (value: Card["sales_outcome"]) => ({ open: "Aberta", won: "Ganha", lost: "Perdida" }[value || "open"]);
