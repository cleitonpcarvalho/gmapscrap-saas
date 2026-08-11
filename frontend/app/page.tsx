"use client";

import {
  closestCorners,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  type UniqueIdentifier
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy
} from "@dnd-kit/sortable";
import {
  ArrowDownToLine,
  BarChart3,
  Building2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Edit3,
  Eye,
  EyeOff,
  FileText,
  Globe2,
  ListFilter,
  Loader2,
  LogOut,
  Mail,
  Megaphone,
  MessageCircle,
  MousePointerClick,
  Pause,
  Play,
  Plus,
  QrCode,
  RefreshCw,
  Save,
  Search,
  Send,
  Settings,
  ShieldCheck,
  SkipForward,
  Sparkles,
  Tags,
  Trash2,
  Users,
  X
} from "lucide-react";
import type { CSSProperties, FormEvent, MouseEvent, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

type User = { username: string };

type SessionInfo = {
  authenticated: boolean;
  username: string | null;
};

type Stats = {
  total_leads: number;
  total_with_email: number;
  running_jobs: number;
  completed_jobs: number;
};

type SearchRun = {
  id: number;
  niche: string;
  location: string;
  target_quantity: number | null;
  max_results: boolean;
  skip_without_website: boolean;
  validate_whatsapp: boolean;
  enrich_site_insights: boolean;
  status: "queued" | "running" | "paused" | "completed" | "failed";
  message: string;
  scanned_count: number;
  saved_count: number;
  skipped_count: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

type LeadTagSummary = {
  id: number;
  name: string;
  color: string;
  origin?: "manual" | "ai";
};

type LeadTag = LeadTagSummary & {
  description: string | null;
  created_at: string;
  lead_count: number;
};

type LeadTagForm = {
  name: string;
  color: string;
  description: string;
};

type TagFilterMode = "any" | "all";
type LeadTagBulkAction = "add" | "remove";

type Lead = {
  id: number;
  run_id: number;
  niche: string;
  location: string;
  name: string;
  address: string;
  phone: string | null;
  website: string | null;
  email: string;
  site_insights: string | null;
  whatsapp_validated: boolean | null;
  whatsapp_validated_at: string | null;
  whatsapp_validation_status: string | null;
  validate_whatsapp: boolean;
  whatsapp_url: string;
  tags: LeadTagSummary[];
  created_at: string;
};

type ManualLeadForm = {
  niche: string;
  location: string;
  name: string;
  address: string;
  phone: string;
  website: string;
  email: string;
};

type DeleteDialog = { kind: "single"; lead: Lead } | { kind: "bulk"; ids: number[] } | null;
type LeadTagBulkDialog = { action: LeadTagBulkAction; ids: number[] } | null;

type AppView =
  | "dashboard"
  | "search"
  | "leads"
  | "whatsapp"
  | "whatsappInstances"
  | "whatsappTemplates"
  | "whatsappCampaigns"
  | "whatsappCrm"
  | "whatsappAi"
  | "templates"
  | "lists"
  | "campaigns"
  | "history"
  | "settings";

type SmtpConfig = {
  id: number | null;
  from_email: string;
  from_name: string;
  reply_to: string;
  host: string;
  port: number;
  username: string;
  use_ssl: boolean;
  use_tls: boolean;
  has_password: boolean;
};

type EmailTemplate = {
  id: number;
  name: string;
  subject: string;
  html: string;
  text: string;
  content_title: string;
  content_link: string;
  content_button_text: string;
  contact_mailto_subject: string;
  contact_mailto_body: string;
  logo_url: string;
  primary_color: string;
  text_color: string;
  background_color: string;
};

type AiTemplateGenerateResponse = {
  templates: EmailTemplate[];
};

type ContentPreview = {
  url: string;
  title: string;
  image_url: string;
};

type AiEmailLanguage = "pt" | "en" | "es";

type AiTemplateForm = {
  mode: "single" | "sequence";
  count: number;
  niche: string;
  location: string;
  objective: string;
  tone: string;
  content_title: string;
  content_link: string;
  campaign_name: string;
  call_to_action: string;
  language: AiEmailLanguage;
  logo_url: string;
  primary_color: string;
  text_color: string;
  background_color: string;
};

type LeadListChannel = "email" | "whatsapp" | "both";

type LeadList = {
  id: number;
  name: string;
  channel: LeadListChannel;
  niche_filter: string;
  location_filter: string;
  search_run_id: number | null;
  only_never_emailed: boolean;
  only_whatsapp_validated: boolean;
  only_email_opened: boolean;
  only_email_clicked: boolean;
  email_engagement_filter_mode: "or" | "and";
  never_received_template_id: number | null;
  lead_count: number;
};

type EmailMessageMode = "template" | "ai_per_lead";
type AiMessageLanguage = "pt" | "en" | "es";

type EmailCampaign = {
  id: number;
  name: string;
  list_id: number;
  list_name: string;
  status: "draft" | "running" | "paused" | "completed" | "failed";
  objective: string;
  message_mode: EmailMessageMode;
  language: AiMessageLanguage;
  message: string;
  error: string | null;
  min_delay_seconds: number;
  max_delay_seconds: number;
  daily_limit: number;
  weekly_limit: number;
  send_window_start: string;
  send_window_end: string;
  timezone_name: string;
  send_days: string;
  template_ids: number[];
  pending_count: number;
  sent_count: number;
  failed_count: number;
};

type WhatsAppInstanceStatus = "disconnected" | "connecting" | "connected";

type WhatsAppInstance = {
  id: number;
  name: string;
  provider: string;
  status: WhatsAppInstanceStatus;
  evolution_instance_name: string | null;
  phone_number: string | null;
  connected_at: string | null;
  created_at: string;
  updated_at: string;
};

type WhatsAppQrCodeResponse = {
  id: number;
  name: string;
  evolution_instance_name: string;
  base64: string;
  url: string;
  code: string;
  pairing_code: string | null;
  provider_response: Record<string, unknown>;
};

type WhatsAppInstanceStatusResponse = {
  id: number;
  name: string;
  status: WhatsAppInstanceStatus;
  phone_number: string | null;
  connected_at: string | null;
  provider_state: string;
  provider_response: Record<string, unknown>;
};

type WhatsAppMessageTemplate = {
  id: number;
  name: string;
  content: string;
  created_at: string;
};

type WhatsAppTemplateGenerateResponse = {
  content: string;
};

type WhatsAppMessageMode = "template" | "ai_per_lead";

type WhatsAppCampaign = {
  id: number;
  name: string;
  objective: string;
  message_mode: WhatsAppMessageMode;
  language: AiMessageLanguage;
  list_id: number;
  list_name: string;
  funnel_id: number | null;
  funnel_name: string;
  instance_id: number;
  instance_name: string;
  status: "draft" | "running" | "paused" | "completed" | "failed";
  message: string;
  error: string | null;
  min_delay_seconds: number;
  max_delay_seconds: number;
  daily_limit: number;
  weekly_limit: number;
  send_window_start: string;
  send_window_end: string;
  timezone_name: string;
  send_days: string;
  template_ids: number[];
  pending_count: number;
  sent_count: number;
  delivered_count: number;
  read_count: number;
  failed_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

type CrmStage = string;

type CrmFunnelStage = {
  id: number;
  funnel_id: number;
  key: string;
  label: string;
  color: string;
  position: number;
  is_won: boolean;
  is_lost: boolean;
  card_count: number;
};

type CrmFunnel = {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  created_at: string;
  card_count: number;
  stages: CrmFunnelStage[];
};

type CrmLeadFunnelSummary = {
  id: number;
  name: string;
  stage: string;
  stage_label: string;
};

type CrmLead = {
  id: number;
  lead_id: number;
  stage: CrmStage;
  funnel_id: number;
  funnel_name: string;
  stage_id: number;
  stage_label: string;
  stage_color: string;
  qualification_notes: string | null;
  score: number | null;
  position: number | null;
  updated_at: string;
  lead_name: string;
  phone: string | null;
  whatsapp_url: string;
  website: string | null;
  email: string;
  niche: string;
  location: string;
  last_message: string | null;
  last_message_at: string | null;
  conversation_id: number | null;
  tags: LeadTagSummary[];
  other_funnels: CrmLeadFunnelSummary[];
};

type WhatsAppAiSettings = {
  id: number;
  system_prompt: string;
  services_description: string;
  enabled: boolean;
  auto_apply_tags_enabled: boolean;
  updated_at: string;
};

type LeadSiteInsightsEnrichmentResponse = {
  status: string;
  eligible_count: number;
  queued_count: number;
  location_inference: string;
};

type LeadSiteInsightsEnrichmentRequest = {
  lead_ids?: number[];
};

type LeadWhatsAppValidationRequest = {
  lead_ids?: number[];
  niche?: string;
  location?: string;
  search?: string;
  only_pending: boolean;
  revalidate: boolean;
};

type LeadWhatsAppValidationResponse = {
  job_id: string;
  status: string;
  eligible_count: number;
  queued_count: number;
  skipped_count: number;
  message: string;
};

type LeadWhatsAppValidationPreview = {
  total_leads: number;
  never_validated: number;
  valid: number;
  invalid: number;
  unknown: number;
  without_phone: number;
  eligible_now: number;
};

type LeadWhatsAppValidationProgress = {
  job_id: string;
  status: "idle" | "running" | "completed" | "cancelled" | "aborted" | string;
  total: number;
  processed: number;
  valid: number;
  invalid: number;
  unknown: number;
  skipped: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
};

type LeadWhatsappStatusFilter = "" | "valid" | "invalid" | "unknown" | "never";

type LeadWhatsAppValidationScope = "selected" | "filters";

type WhatsAppPortfolioItem = {
  id: number;
  description: string;
  url: string;
  created_at: string;
};

type WhatsAppInstanceFormErrors = {
  name?: string;
};

type WhatsAppCampaignFormErrors = {
  name?: string;
  objective?: string;
  list_id?: string;
  funnel_id?: string;
  instance_id?: string;
  template_id?: string;
  min_delay_seconds?: string;
  max_delay_seconds?: string;
  send_days?: string;
};

type WhatsAppTemplateFormErrors = {
  name?: string;
  content?: string;
};

type EmailSendLog = {
  id: number;
  campaign_id: number;
  campaign_name: string;
  lead_id: number;
  lead_name: string;
  template_id: number;
  template_name: string;
  recipient_email: string;
  subject: string;
  status: string;
  error: string | null;
  generated_content: string | null;
  open_count: number;
  click_count: number;
  created_at: string;
  sent_at: string | null;
  opened_at: string | null;
  clicked_at: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const emptyStats: Stats = {
  total_leads: 0,
  total_with_email: 0,
  running_jobs: 0,
  completed_jobs: 0
};

const defaultSmtpForm: SmtpConfig = {
  id: null,
  from_email: "contato@automasoluct.com.br",
  from_name: "Automa Soluct",
  reply_to: "contato@automasoluct.com.br",
  host: "smtp.zoho.com",
  port: 465,
  username: "contato@automasoluct.com.br",
  use_ssl: true,
  use_tls: false,
  has_password: false
};

const DEFAULT_TEMPLATE_LOGO = "https://automasoluct.com.br/wp-content/uploads/2025/06/Automa_Soluct_Logo_Sem_Fundo.png";
const DEFAULT_CONTACT_EMAIL = "contato@automasoluct.com.br";
const LEADS_PAGE_SIZE = 30;
const HISTORY_PAGE_SIZE = 30;
const SEARCH_RUNS_PAGE_SIZE = 4;
const LIST_FILTER_SEPARATOR = "||";
const WHATSAPP_VALIDATION_DELAY_SECONDS = 1.5;

const idleLeadWhatsAppValidationProgress: LeadWhatsAppValidationProgress = {
  job_id: "",
  status: "idle",
  total: 0,
  processed: 0,
  valid: 0,
  invalid: 0,
  unknown: 0,
  skipped: 0,
  started_at: null,
  finished_at: null,
  error: null
};

const LEAD_WHATSAPP_STATUS_OPTIONS: { value: LeadWhatsappStatusFilter; label: string }[] = [
  { value: "", label: "Todos" },
  { value: "valid", label: "Tem WhatsApp" },
  { value: "invalid", label: "Sem WhatsApp" },
  { value: "unknown", label: "Indeterminado" },
  { value: "never", label: "Não validado" }
];

const CAMPAIGN_TIMEZONES = [
  { value: "America/Sao_Paulo", label: "América do Sul - Brasil/Argentina/Uruguai" },
  { value: "America/Bogota", label: "América do Sul - Colômbia/Peru/Equador" },
  { value: "America/New_York", label: "EUA/Canadá - Eastern" },
  { value: "America/Chicago", label: "EUA/Canadá/América Central - Central" },
  { value: "America/Los_Angeles", label: "EUA/Canadá - Pacific" },
  { value: "Europe/London", label: "Europa Ocidental - UK/Portugal/Irlanda" },
  { value: "Europe/Paris", label: "Europa Ocidental - França/Espanha/Alemanha/Itália" }
];

const CAMPAIGN_SEND_DAYS = [
  { value: "0", label: "Segunda", shortLabel: "Seg" },
  { value: "1", label: "Terça", shortLabel: "Ter" },
  { value: "2", label: "Quarta", shortLabel: "Qua" },
  { value: "3", label: "Quinta", shortLabel: "Qui" },
  { value: "4", label: "Sexta", shortLabel: "Sex" },
  { value: "5", label: "Sábado", shortLabel: "Sáb" },
  { value: "6", label: "Domingo", shortLabel: "Dom" }
];

const HISTORY_ENGAGEMENT_OPTIONS = ["Aberto", "Clicado", "Sem abertura", "Sem clique"];

const defaultAiTemplateForm: AiTemplateForm = {
  mode: "sequence",
  count: 3,
  niche: "",
  location: "",
  objective: "Share a useful automation resource and softly introduce Automa Soluct as an automation partner.",
  tone: "educational, friendly, consultative, low-pressure",
  content_title: "",
  content_link: "",
  campaign_name: "",
  call_to_action:
    "Invite the reader to reply if they need help connecting tools, automating follow-ups, or reducing manual work.",
  language: "pt",
  logo_url: DEFAULT_TEMPLATE_LOGO,
  primary_color: "#0a0a0a",
  text_color: "#333333",
  background_color: "#f4f4f4"
};

const AI_MESSAGE_LANGUAGE_OPTIONS: { value: AiMessageLanguage; label: string }[] = [
  { value: "pt", label: "Português" },
  { value: "en", label: "Inglês" },
  { value: "es", label: "Espanhol" }
];

const defaultCampaignForm = {
  name: "",
  objective: "",
  message_mode: "template" as EmailMessageMode,
  language: "pt" as AiMessageLanguage,
  list_id: "",
  template_ids: [] as number[],
  min_delay_seconds: 120,
  max_delay_seconds: 300,
  daily_limit: 30,
  weekly_limit: 150,
  send_window_start: "09:00",
  send_window_end: "17:00",
  timezone_name: "America/New_York",
  send_days: "0,1,2,3,4",
};

const defaultWhatsappInstanceForm = {
  name: "",
  phone_number: ""
};

const defaultWhatsappCampaignForm = {
  name: "",
  objective: "",
  message_mode: "template" as WhatsAppMessageMode,
  language: "pt" as AiMessageLanguage,
  list_id: "",
  funnel_id: "",
  instance_id: "",
  template_id: "",
  min_delay_seconds: 120,
  max_delay_seconds: 300,
  daily_limit: 30,
  weekly_limit: 150,
  send_window_start: "09:00",
  send_window_end: "17:00",
  timezone_name: "America/Sao_Paulo",
  send_days: "0,1,2,3,4"
};

const defaultWhatsappTemplateForm = {
  name: "",
  content: ""
};

const WHATSAPP_VARIABLES = ["{nome_empresa}", "{website}", "{phone}", "{niche}", "{location}"];

const TAG_COLOR_OPTIONS = [
  "#e0f2fe",
  "#dcfce7",
  "#fef3c7",
  "#fee2e2",
  "#ede9fe",
  "#fce7f3",
  "#ccfbf1",
  "#f3f4f6"
];

const defaultTagForm: LeadTagForm = {
  name: "",
  color: TAG_COLOR_OPTIONS[0],
  description: ""
};

const STAGE_COLOR_OPTIONS = TAG_COLOR_OPTIONS;

type CrmFunnelForm = {
  name: string;
  description: string;
};

type CrmStageForm = {
  label: string;
  color: string;
  is_won: boolean;
  is_lost: boolean;
};

const defaultFunnelForm: CrmFunnelForm = {
  name: "",
  description: ""
};

const defaultStageForm: CrmStageForm = {
  label: "",
  color: STAGE_COLOR_OPTIONS[0],
  is_won: false,
  is_lost: false
};

const defaultWhatsappAiForm = {
  system_prompt: "",
  services_description: "",
  enabled: false,
  auto_apply_tags_enabled: false
};

const defaultWhatsappPortfolioForm = {
  description: "",
  url: ""
};

const defaultManualLeadForm: ManualLeadForm = {
  niche: "",
  location: "",
  name: "",
  address: "",
  phone: "",
  website: "",
  email: ""
};

class ApiRequestError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
  }
}

function apiErrorMessage(payload: unknown) {
  if (!payload || typeof payload !== "object") return "Não foi possível completar a ação.";
  const detail = "detail" in payload ? (payload as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return "Não foi possível completar a ação.";
}

async function apiFetchWithResponse<T>(path: string, init?: RequestInit): Promise<{ data: T; response: Response }> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    ...init
  });

  const rawBody = await response.text();
  let payload: unknown = undefined;
  if (rawBody) {
    try {
      payload = JSON.parse(rawBody);
    } catch {
      payload = rawBody;
    }
  }

  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : payload;
    throw new ApiRequestError(response.status, apiErrorMessage(payload), detail);
  }

  return { data: payload as T, response };
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const { data } = await apiFetchWithResponse<T>(path, init);
  return data;
}

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatFullDateTime(value: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatHumanDuration(totalSeconds: number) {
  if (totalSeconds <= 0) return "menos de 1 minuto";

  const minutes = Math.ceil(totalSeconds / 60);
  if (minutes < 1) return "menos de 1 minuto";
  if (minutes === 1) return "cerca de 1 minuto";
  if (minutes < 60) return `cerca de ${minutes} minutos`;

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (remainingMinutes === 0) return hours === 1 ? "cerca de 1 hora" : `cerca de ${hours} horas`;
  return hours === 1
    ? `cerca de 1 hora e ${remainingMinutes} minutos`
    : `cerca de ${hours} horas e ${remainingMinutes} minutos`;
}

function leadWhatsAppStatus(lead: Lead): { label: string; className: string; title: string } {
  if (!lead.whatsapp_validated_at) {
    return { label: "Não validado", className: "status-pill draft", title: "Ainda não validado" };
  }

  const validatedAt = formatFullDateTime(lead.whatsapp_validated_at);
  if (lead.whatsapp_validation_status === "valid") {
    return { label: "Tem WhatsApp", className: "status-pill connected", title: `Validado em ${validatedAt}` };
  }
  if (lead.whatsapp_validation_status === "invalid") {
    return { label: "Sem WhatsApp", className: "status-pill disconnected", title: `Validado em ${validatedAt}` };
  }
  return { label: "Indeterminado", className: "status-pill connecting", title: `Validado em ${validatedAt}` };
}

function whatsappValidationFinalMessage(progress: LeadWhatsAppValidationProgress) {
  if (progress.status === "cancelled") {
    return `Validação cancelada. ${progress.processed} de ${progress.total} leads já haviam sido processados.`;
  }
  if (progress.status === "aborted") {
    const cause = progress.error || "Validação interrompida por falhas seguidas de conexão com a Evolution.";
    return `${cause} Os leads restantes NÃO foram alterados. Verifique a instância em Instâncias.`;
  }
  return `Validação concluída: ${progress.valid} válidos, ${progress.invalid} inválidos, ${progress.unknown} indeterminados e ${progress.skipped} pulados.`;
}

function statusLabel(status: SearchRun["status"]) {
  const labels = {
    queued: "Na fila",
    running: "Rodando",
    paused: "Pausada",
    completed: "Concluída",
    failed: "Falhou"
  };
  return labels[status];
}

function searchRunMessage(run: SearchRun) {
  const rawMessage = (run.error || run.message || "").trim();

  if (!rawMessage) {
    if (run.status === "failed") return "A busca falhou antes de registrar detalhes.";
    if (run.status === "completed") return "Busca concluída.";
    if (run.status === "paused") return "Busca pausada.";
    return "Busca em andamento.";
  }

  const withoutPrefix = rawMessage.replace(/^message:\s*/i, "").trim();
  const beforeStacktrace = withoutPrefix.split(/stacktrace:/i)[0].trim();
  const likelyTechnicalTrace = /stacktrace:|<unknown>|0x[0-9a-f]{8,}|selenium|webdriver|chrome/i.test(rawMessage);

  if (!beforeStacktrace && likelyTechnicalTrace) {
    return "Google Maps não conseguiu abrir os resultados no Chrome headless. Tente novamente em alguns minutos.";
  }

  const compactMessage = (beforeStacktrace || withoutPrefix)
    .replace(/0x[0-9a-f]+/gi, "")
    .replace(/<unknown>/gi, "")
    .replace(/\s+/g, " ")
    .trim();

  if (likelyTechnicalTrace && compactMessage.toLowerCase() === "message:") {
    return "Google Maps não conseguiu abrir os resultados no Chrome headless. Tente novamente em alguns minutos.";
  }

  return compactMessage.length > 150 ? `${compactMessage.slice(0, 147).trim()}...` : compactMessage;
}

function campaignStatusLabel(status: EmailCampaign["status"]) {
  const labels = {
    draft: "Rascunho",
    running: "Rodando",
    paused: "Pausada",
    completed: "Concluída",
    failed: "Falhou"
  };
  return labels[status];
}

function whatsappInstanceStatusLabel(status: WhatsAppInstanceStatus) {
  const labels = {
    disconnected: "Desconectada",
    connecting: "Conectando",
    connected: "Conectada"
  };
  return labels[status] || status;
}

const DEFAULT_CRM_STAGE_LABELS: Record<string, string> = {
  new: "Novo",
  responded: "Respondeu",
  qualified: "Qualificado",
  not_interested: "Sem interesse",
  converted: "Convertido"
};

function crmStageLabel(stage: CrmStage, stages: CrmFunnelStage[] = []) {
  return stages.find((item) => item.key === stage)?.label || DEFAULT_CRM_STAGE_LABELS[stage] || stage;
}

function formatOptionalText(value: string | null | undefined) {
  const text = safeText(value).trim();
  return text || "-";
}

function formatWhatsappPhoneInput(value: string) {
  const digits = value.replace(/\D/g, "").slice(0, 15);
  return digits ? `+${digits}` : "";
}

function whatsappQrImageSrc(qrCode: WhatsAppQrCodeResponse) {
  const base64 = qrCode.base64?.trim();
  if (!base64) return "";
  return base64.startsWith("data:") ? base64 : `data:image/png;base64,${base64}`;
}

function emailSendStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "Pendente",
    sent: "Enviado",
    failed: "Falhou"
  };
  return labels[status] || normalizeSegmentLabel(status.replace(/_/g, " ")) || "-";
}

function parseCampaignSendDays(value: string) {
  const allowedValues = new Set(CAMPAIGN_SEND_DAYS.map((day) => day.value));
  return new Set(value.split(",").map((day) => day.trim()).filter((day) => allowedValues.has(day)));
}

function formatCampaignSendDays(days: Set<string>) {
  return Array.from(days)
    .sort((left, right) => Number(left) - Number(right))
    .join(",");
}

function formatCampaignSendDaysLabel(value: string) {
  const days = parseCampaignSendDays(value);
  if (days.size === 0 || days.size === CAMPAIGN_SEND_DAYS.length) return "Todos os dias";
  return CAMPAIGN_SEND_DAYS.filter((day) => days.has(day.value))
    .map((day) => day.shortLabel)
    .join(", ");
}

function percent(part: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

function safeText(value: string | null | undefined) {
  return value || "";
}

function displayWebsite(value: string | null | undefined) {
  return safeText(value).trim().replace(/^https?:\/\//, "");
}

function leadPayload(lead: Lead) {
  return {
    niche: lead.niche.trim(),
    location: lead.location.trim(),
    name: lead.name.trim(),
    address: lead.address.trim(),
    phone: safeText(lead.phone).trim(),
    website: safeText(lead.website).trim(),
    email: lead.email.trim()
  };
}

function PhoneCell({ lead }: { lead: Pick<Lead, "phone" | "whatsapp_url"> }) {
  const phone = safeText(lead.phone).trim();
  const url = safeText(lead.whatsapp_url).trim();

  if (!phone) return <>-</>;
  if (!url) return <>{phone}</>;

  return (
    <a className="phone-link" href={url} target="_blank" rel="noreferrer" title="Abrir conversa no WhatsApp">
      {phone}
    </a>
  );
}

function WebsiteCell({ website }: { website: string | null | undefined }) {
  const url = safeText(website).trim();
  if (!url) return <>-</>;

  return (
    <a href={url} target="_blank" rel="noreferrer">
      <Globe2 size={15} />
      {displayWebsite(url)}
    </a>
  );
}

function normalizeTagColor(value: string) {
  const color = value.trim();
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color : TAG_COLOR_OPTIONS[0];
}

function normalizeStageColor(value: string) {
  const color = value.trim();
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color : STAGE_COLOR_OPTIONS[0];
}

function tagPayload(form: LeadTagForm) {
  return {
    name: form.name.trim(),
    color: normalizeTagColor(form.color),
    description: form.description.trim() || null
  };
}

function tagStyle(tag: Pick<LeadTagSummary, "color">): CSSProperties {
  return { "--tag-color": normalizeTagColor(tag.color) } as CSSProperties;
}

function stageStyle(stage: Pick<CrmFunnelStage, "color">): CSSProperties {
  return { "--stage-color": normalizeStageColor(stage.color) } as CSSProperties;
}

function crmStagePayload(form: CrmStageForm) {
  return {
    label: form.label.trim(),
    color: normalizeStageColor(form.color),
    is_won: form.is_won,
    is_lost: form.is_lost
  };
}

function toggleNumberSelection(selected: number[], id: number) {
  return selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id];
}

function TagPills({
  tags,
  limit = 3,
  emptyLabel = "-"
}: {
  tags: LeadTagSummary[] | undefined;
  limit?: number;
  emptyLabel?: string | null;
}) {
  const visibleTags = (tags || []).slice(0, limit);
  const hiddenCount = Math.max(0, (tags || []).length - visibleTags.length);

  if (visibleTags.length === 0) {
    return emptyLabel ? <span className="tag-empty">{emptyLabel}</span> : null;
  }

  return (
    <div className="lead-tag-list">
      {visibleTags.map((tag) => (
        <span
          className={`lead-tag-pill${tag.origin === "ai" ? " ai-tag" : ""}`}
          key={tag.id}
          style={tagStyle(tag)}
          title={tag.origin === "ai" ? `${tag.name} · aplicada pela IA` : tag.name}
        >
          {tag.origin === "ai" ? <Sparkles aria-hidden="true" size={11} /> : null}
          {tag.name}
        </span>
      ))}
      {hiddenCount > 0 ? <span className="lead-tag-pill more-tag">+{hiddenCount}</span> : null}
    </div>
  );
}

function LeadTagFilter({
  allLabel,
  label,
  placeholder,
  tags,
  selectedIds,
  mode,
  onChange,
  onModeChange
}: {
  allLabel: string;
  label: string;
  placeholder: string;
  tags: LeadTag[];
  selectedIds: number[];
  mode: TagFilterMode;
  onChange: (nextSelected: number[]) => void;
  onModeChange: (nextMode: TagFilterMode) => void;
}) {
  const selectedTags = selectedIds
    .map((id) => tags.find((tag) => tag.id === id))
    .filter((tag): tag is LeadTag => Boolean(tag));
  const availableTags = tags.filter((tag) => !selectedIds.includes(tag.id));

  return (
    <label className="tag-filter lead-tag-filter">
      {label}
      <select
        value=""
        onChange={(event) => {
          const nextTagId = Number(event.target.value);
          if (!nextTagId) return;
          onChange([...selectedIds, nextTagId]);
        }}
      >
        <option value="">{placeholder}</option>
        {availableTags.map((tag) => (
          <option key={tag.id} value={tag.id}>
            {tag.name}
          </option>
        ))}
      </select>
      <div className="tag-list">
        {selectedTags.length === 0 ? <span className="filter-tag all-tag">{allLabel}</span> : null}
        {selectedTags.map((tag) => (
          <span className="filter-tag colored-filter-tag" key={tag.id} style={tagStyle(tag)}>
            {tag.name}
            <button
              aria-label={`Remover tag ${tag.name}`}
              onClick={() => onChange(selectedIds.filter((item) => item !== tag.id))}
              type="button"
            >
              <X size={12} />
            </button>
          </span>
        ))}
        {selectedTags.length > 0 ? (
          <>
            <div className="tag-filter-mode" aria-label="Modo do filtro de tags">
              <button
                className={mode === "any" ? "active" : ""}
                onClick={() => onModeChange("any")}
                type="button"
              >
                Qualquer
              </button>
              <button
                className={mode === "all" ? "active" : ""}
                onClick={() => onModeChange("all")}
                type="button"
              >
                Todas
              </button>
            </div>
            <button className="filter-reset-tag" onClick={() => onChange([])} type="button">
              Usar todas
            </button>
          </>
        ) : null}
      </div>
    </label>
  );
}

function TagCheckboxGrid({
  tags,
  selectedIds,
  disabled,
  onToggle
}: {
  tags: LeadTag[];
  selectedIds: number[];
  disabled?: boolean;
  onToggle: (tagId: number, checked: boolean) => void;
}) {
  if (tags.length === 0) {
    return <p className="empty-state">Nenhuma tag criada ainda.</p>;
  }

  return (
    <div className="tag-checkbox-grid">
      {tags.map((tag) => (
        <label className="tag-checkbox" key={tag.id}>
          <input
            checked={selectedIds.includes(tag.id)}
            disabled={disabled}
            onChange={(event) => onToggle(tag.id, event.target.checked)}
            type="checkbox"
          />
          <span className="lead-tag-pill" style={tagStyle(tag)}>
            {tag.name}
          </span>
        </label>
      ))}
    </div>
  );
}

const CRM_LEAD_DND_PREFIX = "crm-lead-";
const CRM_STAGE_DND_PREFIX = "crm-stage-";
const FUNNEL_STAGE_DND_PREFIX = "funnel-stage-";

function crmLeadDragId(leadId: number) {
  return `${CRM_LEAD_DND_PREFIX}${leadId}`;
}

function crmStageDropId(stage: string) {
  return `${CRM_STAGE_DND_PREFIX}${stage}`;
}

function funnelStageDragId(stageId: number) {
  return `${FUNNEL_STAGE_DND_PREFIX}${stageId}`;
}

function parseCrmLeadDragId(id: UniqueIdentifier | null | undefined) {
  const value = String(id || "");
  if (!value.startsWith(CRM_LEAD_DND_PREFIX)) return null;
  const leadId = Number(value.slice(CRM_LEAD_DND_PREFIX.length));
  return Number.isFinite(leadId) ? leadId : null;
}

function parseCrmStageDropId(id: UniqueIdentifier | null | undefined, stages: CrmFunnelStage[]): CrmStage | null {
  const value = String(id || "");
  if (!value.startsWith(CRM_STAGE_DND_PREFIX)) return null;
  const stage = value.slice(CRM_STAGE_DND_PREFIX.length);
  return stages.some((item) => item.key === stage) ? stage : null;
}

function parseFunnelStageDragId(id: UniqueIdentifier | null | undefined) {
  const value = String(id || "");
  if (!value.startsWith(FUNNEL_STAGE_DND_PREFIX)) return null;
  const stageId = Number(value.slice(FUNNEL_STAGE_DND_PREFIX.length));
  return Number.isFinite(stageId) ? stageId : null;
}

function compareCrmLeadsForBoard(first: CrmLead, second: CrmLead) {
  const firstPosition = first.position ?? Number.MAX_SAFE_INTEGER;
  const secondPosition = second.position ?? Number.MAX_SAFE_INTEGER;
  if (firstPosition !== secondPosition) return firstPosition - secondPosition;

  const firstUpdated = Date.parse(first.updated_at || "") || 0;
  const secondUpdated = Date.parse(second.updated_at || "") || 0;
  if (firstUpdated !== secondUpdated) return secondUpdated - firstUpdated;

  return second.id - first.id;
}

function emptyCrmLeadGroups(stages: CrmFunnelStage[]): Record<string, CrmLead[]> {
  return stages.reduce(
    (accumulator, stage) => ({ ...accumulator, [stage.key]: [] }),
    {} as Record<string, CrmLead[]>
  );
}

function groupCrmLeadsByStage(leads: CrmLead[], stages: CrmFunnelStage[]) {
  const grouped = emptyCrmLeadGroups(stages);
  leads.forEach((lead) => {
    if (!grouped[lead.stage]) grouped[lead.stage] = [];
    grouped[lead.stage] = [...grouped[lead.stage], lead];
  });
  Object.keys(grouped).forEach((stage) => {
    grouped[stage] = [...grouped[stage]].sort(compareCrmLeadsForBoard);
  });
  return grouped;
}

function crmStageFromDndData(data: unknown, stages: CrmFunnelStage[]): CrmStage | null {
  if (!data || typeof data !== "object" || !("stage" in data)) return null;
  const stage = String((data as { stage?: unknown }).stage || "");
  return stages.some((item) => item.key === stage) ? stage : null;
}

function crmDropTargetStage(
  over: { id: UniqueIdentifier; data: { current?: unknown } } | null | undefined,
  stages: CrmFunnelStage[]
) {
  return crmStageFromDndData(over?.data.current, stages) || parseCrmStageDropId(over?.id, stages);
}

function crmTargetIndex(
  overId: UniqueIdentifier | null | undefined,
  targetStage: CrmStage,
  grouped: Record<string, CrmLead[]>
) {
  const overLeadId = parseCrmLeadDragId(overId);
  const targetLeads = grouped[targetStage] || [];
  if (!overLeadId) return targetLeads.length;

  const overIndex = targetLeads.findIndex((lead) => lead.lead_id === overLeadId);
  return overIndex >= 0 ? overIndex : targetLeads.length;
}

function clampCrmTargetIndex(index: number, length: number) {
  return Math.max(0, Math.min(index, length));
}

function moveCrmLeadForBoard(
  leads: CrmLead[],
  leadId: number,
  targetStage: CrmStage,
  targetIndex: number,
  stages: CrmFunnelStage[]
): { changed: boolean; leads: CrmLead[]; position: number } {
  const movingLead = leads.find((lead) => lead.lead_id === leadId);
  if (!movingLead) return { changed: false, leads, position: 0 };

  const grouped = groupCrmLeadsByStage(leads, stages);
  const sourceStage = movingLead.stage;
  const sourceIndex = (grouped[sourceStage] || []).findIndex((lead) => lead.lead_id === leadId);
  const sourceLeads = (grouped[sourceStage] || []).filter((lead) => lead.lead_id !== leadId);
  const targetLeads =
    sourceStage === targetStage ? sourceLeads : (grouped[targetStage] || []).filter((lead) => lead.lead_id !== leadId);
  const boundedIndex = clampCrmTargetIndex(targetIndex, targetLeads.length);

  if (sourceStage === targetStage && sourceIndex === boundedIndex) {
    return { changed: false, leads, position: boundedIndex };
  }

  const movedLead = { ...movingLead, stage: targetStage };
  targetLeads.splice(boundedIndex, 0, movedLead);

  const updates = new Map<number, CrmLead>();
  sourceLeads.forEach((lead, index) => {
    updates.set(lead.lead_id, { ...lead, position: index });
  });
  targetLeads.forEach((lead, index) => {
    updates.set(lead.lead_id, { ...lead, stage: targetStage, position: index });
  });

  return {
    changed: true,
    leads: leads.map((lead) => updates.get(lead.lead_id) || lead),
    position: boundedIndex
  };
}

function moveFunnelStageIds(stages: CrmFunnelStage[], activeStageId: number, overStageId: number) {
  const ordered = [...stages].sort((first, second) => first.position - second.position || first.id - second.id);
  const fromIndex = ordered.findIndex((stage) => stage.id === activeStageId);
  const toIndex = ordered.findIndex((stage) => stage.id === overStageId);
  if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return null;

  const [movingStage] = ordered.splice(fromIndex, 1);
  ordered.splice(toIndex, 0, movingStage);
  return ordered.map((stage) => stage.id);
}

function CrmLeadCardContent({ lead }: { lead: CrmLead }) {
  const hasNotes = Boolean(safeText(lead.qualification_notes).trim());
  const lastMessage = safeText(lead.last_message).trim();
  const context = [lead.niche, lead.location].filter(Boolean).join(" · ") || "-";

  return (
    <>
      <div className="crm-card-header">
        <div>
          <strong>{formatOptionalText(lead.lead_name)}</strong>
          <span>{context}</span>
        </div>
        {hasNotes ? (
          <span className="crm-note-indicator" title="Há notas salvas">
            <FileText size={13} />
          </span>
        ) : null}
      </div>
      <TagPills tags={lead.tags} emptyLabel={null} />
      {lastMessage ? <p className="crm-card-snippet">{lastMessage}</p> : null}
    </>
  );
}

function SortableCrmLeadCard({
  lead,
  disabled,
  onOpen
}: {
  lead: CrmLead;
  disabled: boolean;
  onOpen: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: crmLeadDragId(lead.lead_id),
    data: { type: "lead", leadId: lead.lead_id, stage: lead.stage },
    disabled
  });
  const style: CSSProperties = {
    transform: transform
      ? `translate3d(${Math.round(transform.x)}px, ${Math.round(transform.y)}px, 0) scaleX(${transform.scaleX ?? 1}) scaleY(${transform.scaleY ?? 1})`
      : undefined,
    transition
  };

  return (
    <button
      className={`crm-lead-card crm-lead-card-button ${isDragging ? "is-dragging" : ""}`}
      disabled={disabled}
      onClick={onOpen}
      ref={setNodeRef}
      style={style}
      type="button"
      {...attributes}
      {...listeners}
    >
      <CrmLeadCardContent lead={lead} />
    </button>
  );
}

function CrmStageColumn({
  stage,
  leads,
  isDragOver,
  children
}: {
  stage: CrmFunnelStage;
  leads: CrmLead[];
  isDragOver: boolean;
  children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: crmStageDropId(stage.key),
    data: { type: "stage", stage: stage.key }
  });

  return (
    <section className={`crm-column ${isOver || isDragOver ? "drag-over" : ""}`} ref={setNodeRef}>
      <div className="crm-column-heading">
        <div>
          <h2>{stage.label}</h2>
          <small>{leads.length} leads</small>
        </div>
        <span className="stage-count-pill" style={stageStyle(stage)}>
          {leads.length}
        </span>
      </div>

      <SortableContext items={leads.map((lead) => crmLeadDragId(lead.lead_id))} strategy={verticalListSortingStrategy}>
        <div className="crm-card-list">
          {leads.length === 0 ? <p className="empty-state">Sem leads neste estágio.</p> : null}
          {children}
        </div>
      </SortableContext>
    </section>
  );
}

function SortableFunnelStageRow({
  stage,
  disabled,
  onEdit,
  onDelete
}: {
  stage: CrmFunnelStage;
  disabled: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: funnelStageDragId(stage.id),
    data: { type: "funnel-stage", stageId: stage.id },
    disabled
  });
  const style: CSSProperties = {
    transform: transform
      ? `translate3d(${Math.round(transform.x)}px, ${Math.round(transform.y)}px, 0) scaleX(${transform.scaleX ?? 1}) scaleY(${transform.scaleY ?? 1})`
      : undefined,
    transition
  };

  return (
    <article className={`stage-manager-row ${isDragging ? "is-dragging" : ""}`} ref={setNodeRef} style={style}>
      <button
        className="stage-drag-handle"
        disabled={disabled}
        title="Reordenar estágio"
        type="button"
        {...attributes}
        {...listeners}
      >
        <MousePointerClick size={15} />
      </button>
      <div className="stage-manager-main">
        <div>
          <span className="stage-color-dot" style={stageStyle(stage)} />
          <strong>{stage.label}</strong>
        </div>
        <small>
          {stage.card_count} cards · chave {stage.key}
        </small>
        <div className="stage-terminal-flags">
          {stage.is_won ? <span>Ganho</span> : null}
          {stage.is_lost ? <span>Perda</span> : null}
        </div>
      </div>
      <div className="row-actions">
        <button className="icon-button" disabled={disabled} onClick={onEdit} title="Editar estágio" type="button">
          <Edit3 size={16} />
        </button>
        <button className="icon-button danger" disabled={disabled} onClick={onDelete} title="Excluir estágio" type="button">
          <Trash2 size={16} />
        </button>
      </div>
    </article>
  );
}

type TemplatePreviewSource = {
  name: string;
  subject: string;
  html: string;
  text: string;
  content_title: string;
  content_link: string;
  content_button_text: string;
  contact_mailto_subject: string;
  contact_mailto_body: string;
  logo_url: string;
  primary_color: string;
  text_color: string;
  background_color: string;
};

function substituteTemplateVariables(text: string, variables: Record<string, string>) {
  return (text || "").replace(/{{\s*([a-zA-Z0-9_]+)\s*}}/g, (_, key: string) => variables[key] || "");
}

function renderTemplatePreview(template: TemplatePreviewSource, contentPreview?: ContentPreview, sampleLead?: Lead) {
  const sampleCompany = sampleLead?.name || "Example Company";
  const sampleNiche = sampleLead?.niche || "local service";
  const sampleLocation = sampleLead?.location || "their market";
  const thumbnailUrl = youtubeThumbnailUrl(template.content_link) || contentPreview?.image_url || "";
  const safeContentLink = template.content_link || "https://automasoluct.com.br";
  const safeContentTitle = template.content_title || contentPreview?.title || "How to automate your service workflows";
  const contactEmail = DEFAULT_CONTACT_EMAIL;
  const mailtoSubject = substituteTemplateVariables(
    template.contact_mailto_subject || "Automation and integration help",
    { company_name: sampleCompany }
  );
  const mailtoBody = substituteTemplateVariables(
    template.contact_mailto_body ||
      "Hi Cleiton,\n\nI saw your email about automation for {{company_name}} and would like to learn more.\n\n",
    { company_name: sampleCompany }
  );
  const getInTouchLink = `mailto:${contactEmail}?subject=${encodeURIComponent(mailtoSubject)}&body=${encodeURIComponent(mailtoBody)}`;
  const contentCard = contentCardHtml(
    safeContentLink,
    thumbnailUrl,
    safeContentTitle,
    template.primary_color,
    template.content_button_text
  );
  const variables: Record<string, string> = {
    lead_name: sampleCompany,
    company_name: sampleCompany,
    name: sampleCompany,
    email: sampleLead?.email || "hello@example.com",
    website: sampleLead?.website || "https://example-service.com",
    phone: sampleLead?.phone || "+1 205-555-0198",
    address: sampleLead?.address || "120 Main St",
    niche: sampleNiche,
    location: sampleLocation,
    localidade: sampleLocation,
    content_title: safeContentTitle,
    content_link: safeContentLink,
    raw_content_link: safeContentLink,
    content_thumbnail_url: thumbnailUrl,
    content_video_block: contentCard,
    content_card_block: contentCard,
    contact_email: contactEmail,
    get_in_touch_link: getInTouchLink,
    logo_url: template.logo_url || DEFAULT_TEMPLATE_LOGO,
    primary_color: template.primary_color || "#0a0a0a",
    text_color: template.text_color || "#333333",
    background_color: template.background_color || "#f4f4f4"
  };

  const rendered = (template.html || "").replace(/{{\s*([a-zA-Z0-9_]+)\s*}}/g, (_, key: string) => variables[key] || "");
  return withPreviewBaseTarget(rendered);
}

function renderTemplateSubject(template: TemplatePreviewSource, sampleLead?: Lead) {
  const sampleCompany = sampleLead?.name || "Example Company";
  return (template.subject || "").replace(/{{\s*([a-zA-Z0-9_]+)\s*}}/g, (_, key: string) => {
    const values: Record<string, string> = {
      lead_name: sampleCompany,
      company_name: sampleCompany,
      name: sampleCompany,
      niche: sampleLead?.niche || "local service",
      location: sampleLead?.location || "their market",
      content_title: template.content_title || "How to automate your service workflows"
    };
    return values[key] || "";
  });
}

function youtubeVideoId(url: string) {
  if (!url) return "";

  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase().replace("www.", "");

    if (host === "youtu.be") {
      return parsed.pathname.replace("/", "").split("/")[0];
    }

    if (host === "youtube.com" || host === "m.youtube.com") {
      const queryId = parsed.searchParams.get("v");
      if (queryId) return queryId;

      const [, kind, id] = parsed.pathname.split("/");
      if (["embed", "shorts", "live"].includes(kind) && id) return id;
    }
  } catch {
    return "";
  }

  return "";
}

function youtubeThumbnailUrl(url: string) {
  const videoId = youtubeVideoId(url);
  return videoId ? `https://i.ytimg.com/vi/${videoId}/hq720.jpg` : "";
}

function contentCardHtml(
  contentLink: string,
  thumbnailUrl: string,
  contentTitle: string,
  primaryColor: string,
  buttonText?: string
) {
  if (!contentLink) return "";

  const safeButtonText = buttonText || "Open the content";
  const safeContentTitle = contentTitle || safeButtonText;
  const media = thumbnailUrl
    ? `<img src="${thumbnailUrl}" alt="${safeContentTitle}" width="520" style="display:block;width:100%;max-width:520px;height:auto;border-radius:8px;border:1px solid #eeeeee;" />`
    : `<span style="display:block;width:100%;max-width:520px;border:1px solid #eeeeee;border-radius:8px;padding:28px 24px;background-color:#f6f8f7;color:#222222;font-size:18px;line-height:1.45;font-weight:700;">${safeContentTitle}</span>`;

  return `
              <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px 0;">
                <tr>
                  <td align="center">
                    <a href="${contentLink}" target="_blank" rel="noopener noreferrer" style="display:block;text-decoration:none;color:inherit;">
                      ${media}
                      <span style="display:inline-block;margin-top:12px;background-color:${primaryColor || "#0a0a0a"};color:#ffffff;border-radius:999px;padding:12px 18px;font-size:14px;font-weight:700;">${safeButtonText}</span>
                    </a>
                  </td>
                </tr>
              </table>
  `;
}

function withPreviewBaseTarget(html: string) {
  const base = '<base target="_blank" />';
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/<head([^>]*)>/i, `<head$1>${base}`);
  }
  return `${base}${html}`;
}

const SEGMENT_ACRONYMS: Record<string, string> = {
  ai: "AI",
  api: "API",
  b2b: "B2B",
  b2c: "B2C",
  crm: "CRM",
  erp: "ERP",
  hvac: "HVAC",
  ia: "IA",
  it: "IT",
  ny: "NY",
  nyc: "NYC",
  ppc: "PPC",
  ptac: "PTAC",
  saas: "SaaS",
  seo: "SEO",
  uk: "UK",
  us: "US",
  usa: "USA"
};

const SEGMENT_LOWERCASE_WORDS = new Set([
  "a",
  "and",
  "as",
  "da",
  "das",
  "de",
  "do",
  "dos",
  "e",
  "em",
  "for",
  "in",
  "na",
  "nas",
  "no",
  "nos",
  "of",
  "on",
  "the"
]);

function normalizeSegmentToken(token: string, isFirst: boolean) {
  if (!/[A-Za-z0-9À-ÿ]/.test(token)) return token;

  return token
    .split("-")
    .map((part, index) => {
      const lower = part.toLocaleLowerCase();
      if (SEGMENT_ACRONYMS[lower]) return SEGMENT_ACRONYMS[lower];
      if (SEGMENT_LOWERCASE_WORDS.has(lower) && !(isFirst && index === 0)) return lower;
      return `${lower.slice(0, 1).toLocaleUpperCase()}${lower.slice(1)}`;
    })
    .join("-");
}

function normalizeSegmentLabel(value: string) {
  const text = value.trim().replace(/\s+/g, " ");
  if (!text) return "";
  return text
    .split(" ")
    .map((token, index) => normalizeSegmentToken(token, index === 0))
    .join(" ");
}

function uniqueSortedValues(values: string[]) {
  const byKey = new Map<string, string>();
  values.forEach((value) => {
    const normalized = normalizeSegmentLabel(value);
    if (!normalized) return;

    const key = normalized.toLocaleLowerCase();
    if (!byKey.has(key)) {
      byKey.set(key, normalized);
    }
  });
  return Array.from(byKey.values()).sort((left, right) => left.localeCompare(right));
}

function encodeListFilterValues(values: string[]) {
  return uniqueSortedValues(values).join(LIST_FILTER_SEPARATOR);
}

function decodeListFilterValues(value: string) {
  if (!value.trim()) return [];
  if (value.includes(LIST_FILTER_SEPARATOR)) {
    return uniqueSortedValues(value.split(LIST_FILTER_SEPARATOR));
  }
  return uniqueSortedValues([value]);
}

function formatListFilter(value: string, fallback: string) {
  const values = decodeListFilterValues(value);
  return values.length > 0 ? values.join(", ") : fallback;
}

function TagDropdown({
  allLabel,
  label,
  placeholder,
  options,
  selected,
  onChange
}: {
  allLabel?: string;
  label: string;
  placeholder: string;
  options: string[];
  selected: string[];
  onChange: (nextSelected: string[]) => void;
}) {
  const availableOptions = options.filter((option) => !selected.includes(option));

  return (
    <label className="tag-filter">
      {label}
      <select
        value=""
        onChange={(event) => {
          const nextValue = event.target.value;
          if (!nextValue) return;
          onChange([...selected, nextValue]);
        }}
      >
        <option value="">{placeholder}</option>
        {availableOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      {allLabel || selected.length > 0 ? (
        <div className="tag-list">
          {selected.length === 0 && allLabel ? <span className="filter-tag all-tag">{allLabel}</span> : null}
          {selected.map((tag) => (
            <span className="filter-tag" key={tag}>
              {tag}
              <button
                aria-label={`Remover ${tag}`}
                onClick={() => onChange(selected.filter((item) => item !== tag))}
                type="button"
              >
                <X size={12} />
              </button>
            </span>
          ))}
          {selected.length > 0 && allLabel ? (
            <button className="filter-reset-tag" onClick={() => onChange([])} type="button">
              Usar todos
            </button>
          ) : null}
        </div>
      ) : null}
    </label>
  );
}

function ColorField({
  label,
  value,
  onChange
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="color-field">
      {label}
      <div className="color-control">
        <input
          aria-label={label}
          className="color-native"
          type="color"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <span className="color-swatch" style={{ background: value }} />
        <input className="color-code" value={value} onChange={(event) => onChange(event.target.value)} />
      </div>
    </label>
  );
}

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [loginError, setLoginError] = useState("");
  const [username, setUsername] = useState("cleiton.carvalho@automasoluct.com.br");
  const [password, setPassword] = useState("");
  const [activeView, setActiveView] = useState<AppView>("search");
  const [niche, setNiche] = useState("");
  const [location, setLocation] = useState("");
  const [quantity, setQuantity] = useState("10");
  const [maxResults, setMaxResults] = useState(false);
  const [skipWithoutWebsite, setSkipWithoutWebsite] = useState(true);
  const [validateWhatsapp, setValidateWhatsapp] = useState(false);
  const [enrichSiteInsights, setEnrichSiteInsights] = useState(false);
  const [formError, setFormError] = useState("");
  const [runError, setRunError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [leadEnrichmentBusy, setLeadEnrichmentBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [searches, setSearches] = useState<SearchRun[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [tags, setTags] = useState<LeadTag[]>([]);
  const [leadTotalCount, setLeadTotalCount] = useState(0);
  const [leadResultLimit, setLeadResultLimit] = useState(500);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [leadNameQuery, setLeadNameQuery] = useState("");
  const [selectedLeadNiches, setSelectedLeadNiches] = useState<string[]>([]);
  const [selectedLeadLocations, setSelectedLeadLocations] = useState<string[]>([]);
  const [selectedLeadTagIds, setSelectedLeadTagIds] = useState<number[]>([]);
  const [leadTagFilterMode, setLeadTagFilterMode] = useState<TagFilterMode>("any");
  const [leadWhatsappStatusFilter, setLeadWhatsappStatusFilter] = useState<LeadWhatsappStatusFilter>("");
  const [selectedLeadEmailCampaignId, setSelectedLeadEmailCampaignId] = useState("");
  const [leadEmailOpenedOnly, setLeadEmailOpenedOnly] = useState(false);
  const [leadEmailClickedOnly, setLeadEmailClickedOnly] = useState(false);
  const [selectedLeadWhatsappCampaignId, setSelectedLeadWhatsappCampaignId] = useState("");
  const [leadWhatsappRepliedOnly, setLeadWhatsappRepliedOnly] = useState(false);
  const [leadPage, setLeadPage] = useState(1);
  const [runPage, setRunPage] = useState(1);
  const [emailError, setEmailError] = useState("");
  const [emailMessage, setEmailMessage] = useState("");
  const [smtpForm, setSmtpForm] = useState<SmtpConfig>(defaultSmtpForm);
  const [smtpPassword, setSmtpPassword] = useState("");
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);
  const [smtpTestEmail, setSmtpTestEmail] = useState("cleiton.engsoft@gmail.com");
  const [smtpTestTemplateId, setSmtpTestTemplateId] = useState("");
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [contentPreviews, setContentPreviews] = useState<Record<string, ContentPreview>>({});
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null);
  const [editingTemplateId, setEditingTemplateId] = useState<number | null>(null);
  const [templateDeleteDialog, setTemplateDeleteDialog] = useState<EmailTemplate | null>(null);
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiForm, setAiForm] = useState<AiTemplateForm>(defaultAiTemplateForm);
  const [selectedAiNiches, setSelectedAiNiches] = useState<string[]>([]);
  const [selectedAiLocations, setSelectedAiLocations] = useState<string[]>([]);
  const [templateForm, setTemplateForm] = useState({
    name: "",
    subject: "New video: {{content_title}}",
    html:
      '<div style="background:{{background_color}};padding:24px;"><img src="{{logo_url}}" height="56" alt="Automa Soluct" /><p style="color:{{text_color}};">Hi {{lead_name}},</p><p style="color:{{text_color}};">I wanted to share this content with you:</p><p><strong>{{content_title}}</strong></p>{{content_card_block}}<p style="color:{{text_color}};">We specialize in automation and integrations for service businesses. If you ever need help connecting tools, automating follow-ups, or reducing manual work, just click below and send me a quick note.</p><p><a style="background:{{primary_color}};color:#fff;text-decoration:none;padding:12px 18px;border-radius:6px;" href="{{get_in_touch_link}}">Get in touch</a></p><p style="color:{{text_color}};">Best,<br/>Cleiton</p></div>',
    text: "Hi {{lead_name}},\n\nI wanted to share this content with you:\n{{content_title}}\n{{content_link}}\n\nBest,\nCleiton",
    content_title: "",
    content_link: "",
    content_button_text: "Open the content",
    contact_mailto_subject: "Automation and integration help",
    contact_mailto_body:
      "Hi Cleiton,\n\nI saw your email about automation for {{company_name}} and would like to learn more.\n\n",
    logo_url: DEFAULT_TEMPLATE_LOGO,
    primary_color: "#0a0a0a",
    text_color: "#333333",
    background_color: "#f4f4f4"
  });
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);
  const [selectedListNiches, setSelectedListNiches] = useState<string[]>([]);
  const [selectedListLocations, setSelectedListLocations] = useState<string[]>([]);
  const [editingLeadList, setEditingLeadList] = useState<LeadList | null>(null);
  const [leadListDeleteDialog, setLeadListDeleteDialog] = useState<LeadList | null>(null);
  const [selectedEditListNiches, setSelectedEditListNiches] = useState<string[]>([]);
  const [selectedEditListLocations, setSelectedEditListLocations] = useState<string[]>([]);
  const [leadListForm, setLeadListForm] = useState({
    name: "",
    channel: "both" as LeadListChannel,
    niche_filter: "",
    location_filter: "",
    search_run_id: "",
    only_never_emailed: false,
    only_whatsapp_validated: false,
    only_email_opened: false,
    only_email_clicked: false,
    email_engagement_filter_mode: "or" as "or" | "and",
    never_received_template_id: ""
  });
  const [editLeadListForm, setEditLeadListForm] = useState({
    name: "",
    channel: "both" as LeadListChannel,
    only_never_emailed: false,
    only_whatsapp_validated: false,
    only_email_opened: false,
    only_email_clicked: false,
    email_engagement_filter_mode: "or" as "or" | "and",
    never_received_template_id: ""
  });
  const [campaigns, setCampaigns] = useState<EmailCampaign[]>([]);
  const [emailSends, setEmailSends] = useState<EmailSendLog[]>([]);
  const [selectedHistoryCampaigns, setSelectedHistoryCampaigns] = useState<string[]>([]);
  const [selectedHistoryTemplates, setSelectedHistoryTemplates] = useState<string[]>([]);
  const [selectedHistoryStatuses, setSelectedHistoryStatuses] = useState<string[]>([]);
  const [selectedHistoryEngagements, setSelectedHistoryEngagements] = useState<string[]>([]);
  const [historyPage, setHistoryPage] = useState(1);
  const [campaignModalOpen, setCampaignModalOpen] = useState(false);
  const [editingCampaignId, setEditingCampaignId] = useState<number | null>(null);
  const [campaignDeleteDialog, setCampaignDeleteDialog] = useState<EmailCampaign | null>(null);
  const [campaignForm, setCampaignForm] = useState(defaultCampaignForm);
  const [emailBusy, setEmailBusy] = useState(false);
  const [whatsappError, setWhatsappError] = useState("");
  const [whatsappMessage, setWhatsappMessage] = useState("");
  const [whatsappInstances, setWhatsappInstances] = useState<WhatsAppInstance[]>([]);
  const [whatsappTemplates, setWhatsappTemplates] = useState<WhatsAppMessageTemplate[]>([]);
  const [whatsappCampaigns, setWhatsappCampaigns] = useState<WhatsAppCampaign[]>([]);
  const [crmFunnels, setCrmFunnels] = useState<CrmFunnel[]>([]);
  const [selectedCrmFunnelId, setSelectedCrmFunnelId] = useState<number | null>(null);
  const [crmLeads, setCrmLeads] = useState<CrmLead[]>([]);
  const [crmNoteDrafts, setCrmNoteDrafts] = useState<Record<number, string>>({});
  const [crmDetailLeadId, setCrmDetailLeadId] = useState<number | null>(null);
  const [selectedCrmTagIds, setSelectedCrmTagIds] = useState<number[]>([]);
  const [crmTagFilterMode, setCrmTagFilterMode] = useState<TagFilterMode>("any");
  const [activeCrmDragLeadId, setActiveCrmDragLeadId] = useState<number | null>(null);
  const [overCrmStage, setOverCrmStage] = useState<CrmStage | null>(null);
  const [funnelManagerOpen, setFunnelManagerOpen] = useState(false);
  const [funnelForm, setFunnelForm] = useState<CrmFunnelForm>(defaultFunnelForm);
  const [editingFunnelId, setEditingFunnelId] = useState<number | null>(null);
  const [stageForm, setStageForm] = useState<CrmStageForm>(defaultStageForm);
  const [editingStageId, setEditingStageId] = useState<number | null>(null);
  const [funnelDeleteDialog, setFunnelDeleteDialog] = useState<CrmFunnel | null>(null);
  const [funnelDeleteMoveToId, setFunnelDeleteMoveToId] = useState("");
  const [stageDeleteDialog, setStageDeleteDialog] = useState<CrmFunnelStage | null>(null);
  const [stageDeleteMoveToId, setStageDeleteMoveToId] = useState("");
  const [funnelError, setFunnelError] = useState("");
  const [funnelMessage, setFunnelMessage] = useState("");
  const [funnelBusyAction, setFunnelBusyAction] = useState("");
  const [activeFunnelStageDragId, setActiveFunnelStageDragId] = useState<number | null>(null);
  const [whatsappAiSettings, setWhatsappAiSettings] = useState<WhatsAppAiSettings | null>(null);
  const [whatsappAiForm, setWhatsappAiForm] = useState(defaultWhatsappAiForm);
  const [whatsappPortfolioItems, setWhatsappPortfolioItems] = useState<WhatsAppPortfolioItem[]>([]);
  const [whatsappPortfolioForm, setWhatsappPortfolioForm] = useState(defaultWhatsappPortfolioForm);
  const [whatsappInstanceForm, setWhatsappInstanceForm] = useState(defaultWhatsappInstanceForm);
  const [whatsappInstanceFormErrors, setWhatsappInstanceFormErrors] = useState<WhatsAppInstanceFormErrors>({});
  const [whatsappTemplateForm, setWhatsappTemplateForm] = useState(defaultWhatsappTemplateForm);
  const [whatsappTemplateObjective, setWhatsappTemplateObjective] = useState("");
  const [whatsappTemplateFormErrors, setWhatsappTemplateFormErrors] = useState<WhatsAppTemplateFormErrors>({});
  const [editingWhatsappTemplateId, setEditingWhatsappTemplateId] = useState<number | null>(null);
  const [whatsappTemplateDeleteDialog, setWhatsappTemplateDeleteDialog] = useState<WhatsAppMessageTemplate | null>(null);
  const [whatsappCampaignForm, setWhatsappCampaignForm] = useState(defaultWhatsappCampaignForm);
  const [whatsappCampaignFormErrors, setWhatsappCampaignFormErrors] = useState<WhatsAppCampaignFormErrors>({});
  const [whatsappCampaignModalOpen, setWhatsappCampaignModalOpen] = useState(false);
  const [editingWhatsappCampaignId, setEditingWhatsappCampaignId] = useState<number | null>(null);
  const [whatsappQrModal, setWhatsappQrModal] = useState<{
    instance: WhatsAppInstance;
    qrCode: WhatsAppQrCodeResponse;
  } | null>(null);
  const [whatsappInstanceDeleteDialog, setWhatsappInstanceDeleteDialog] = useState<WhatsAppInstance | null>(null);
  const [whatsappCampaignStartDialog, setWhatsappCampaignStartDialog] = useState<WhatsAppCampaign | null>(null);
  const [whatsappCampaignDeleteDialog, setWhatsappCampaignDeleteDialog] = useState<WhatsAppCampaign | null>(null);
  const [whatsappBusyAction, setWhatsappBusyAction] = useState("");
  const [editingLead, setEditingLead] = useState<Lead | null>(null);
  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const [tagForm, setTagForm] = useState<LeadTagForm>(defaultTagForm);
  const [editingTagId, setEditingTagId] = useState<number | null>(null);
  const [tagDeleteDialog, setTagDeleteDialog] = useState<LeadTag | null>(null);
  const [tagError, setTagError] = useState("");
  const [tagMessage, setTagMessage] = useState("");
  const [tagBusyAction, setTagBusyAction] = useState("");
  const [leadTagBulkDialog, setLeadTagBulkDialog] = useState<LeadTagBulkDialog>(null);
  const [leadTagBulkTagIds, setLeadTagBulkTagIds] = useState<number[]>([]);
  const [leadTagBulkError, setLeadTagBulkError] = useState("");
  const [leadTagBulkSaving, setLeadTagBulkSaving] = useState(false);
  const [crmInlineTagForm, setCrmInlineTagForm] = useState<LeadTagForm>(defaultTagForm);
  const [manualLeadOpen, setManualLeadOpen] = useState(false);
  const [manualLeadForm, setManualLeadForm] = useState<ManualLeadForm>(defaultManualLeadForm);
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialog>(null);
  const [leadWhatsappValidationDialogOpen, setLeadWhatsappValidationDialogOpen] = useState(false);
  const [leadWhatsappValidationScope, setLeadWhatsappValidationScope] =
    useState<LeadWhatsAppValidationScope>("filters");
  const [leadWhatsappValidationRevalidate, setLeadWhatsappValidationRevalidate] = useState(false);
  const [leadWhatsappValidationPreview, setLeadWhatsappValidationPreview] =
    useState<LeadWhatsAppValidationPreview | null>(null);
  const [leadWhatsappValidationPreviewLoading, setLeadWhatsappValidationPreviewLoading] = useState(false);
  const [leadWhatsappValidationPreviewError, setLeadWhatsappValidationPreviewError] = useState("");
  const [leadWhatsappValidationSubmitting, setLeadWhatsappValidationSubmitting] = useState(false);
  const [leadWhatsappValidationCancelling, setLeadWhatsappValidationCancelling] = useState(false);
  const [leadWhatsappValidationProgress, setLeadWhatsappValidationProgress] =
    useState<LeadWhatsAppValidationProgress>(idleLeadWhatsAppValidationProgress);
  const [savingEdit, setSavingEdit] = useState(false);
  const [savingManualLead, setSavingManualLead] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [runActionLoading, setRunActionLoading] = useState<number | null>(null);
  const crmDndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 160, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const activeRun = useMemo(
    () => searches.find((run) => run.status === "running" || run.status === "queued"),
    [searches]
  );
  const runPageCount = Math.max(1, Math.ceil(searches.length / SEARCH_RUNS_PAGE_SIZE));
  const currentRunPage = Math.min(runPage, runPageCount);
  const runPageStartIndex = (currentRunPage - 1) * SEARCH_RUNS_PAGE_SIZE;
  const paginatedSearches = searches.slice(runPageStartIndex, runPageStartIndex + SEARCH_RUNS_PAGE_SIZE);
  const runPageStart = searches.length === 0 ? 0 : runPageStartIndex + 1;
  const runPageEnd = Math.min(runPageStartIndex + SEARCH_RUNS_PAGE_SIZE, searches.length);

  const emailLeadLists = useMemo(
    () => leadLists.filter((list) => list.channel === "email" || list.channel === "both"),
    [leadLists]
  );
  const whatsappLeadLists = useMemo(
    () => leadLists.filter((list) => list.channel === "whatsapp" || list.channel === "both"),
    [leadLists]
  );
  const defaultCrmFunnel = useMemo(
    () => crmFunnels.find((funnel) => funnel.is_default) || crmFunnels[0] || null,
    [crmFunnels]
  );
  const selectedCrmFunnel = useMemo(
    () => crmFunnels.find((funnel) => funnel.id === selectedCrmFunnelId) || defaultCrmFunnel,
    [crmFunnels, defaultCrmFunnel, selectedCrmFunnelId]
  );
  const selectedCrmStages = useMemo(
    () => [...(selectedCrmFunnel?.stages || [])].sort((first, second) => first.position - second.position || first.id - second.id),
    [selectedCrmFunnel]
  );
  const selectedCrmFunnelIdValue = selectedCrmFunnel?.id ?? null;
  const activeFunnelStage = useMemo(
    () => selectedCrmStages.find((stage) => stage.id === activeFunnelStageDragId) || null,
    [activeFunnelStageDragId, selectedCrmStages]
  );

  const leadNicheOptions = useMemo(() => uniqueSortedValues(leads.map((lead) => lead.niche)), [leads]);
  const leadLocationOptions = useMemo(() => uniqueSortedValues(leads.map((lead) => lead.location)), [leads]);
  const leadApiPath = useMemo(() => {
    const params = new URLSearchParams();
    if (leadWhatsappStatusFilter) params.set("whatsapp_status", leadWhatsappStatusFilter);
    if (selectedLeadEmailCampaignId) params.set("email_campaign_id", selectedLeadEmailCampaignId);
    if (leadEmailOpenedOnly) params.set("email_opened", "true");
    if (leadEmailClickedOnly) params.set("email_clicked", "true");
    if (selectedLeadWhatsappCampaignId) params.set("whatsapp_campaign_id", selectedLeadWhatsappCampaignId);
    if (leadWhatsappRepliedOnly) params.set("whatsapp_replied", "true");
    selectedLeadTagIds.forEach((tagId) => params.append("tag_ids", String(tagId)));
    if (selectedLeadTagIds.length > 0) params.set("tag_filter_mode", leadTagFilterMode);
    const query = params.toString();
    return `/api/leads${query ? `?${query}` : ""}`;
  }, [
    leadEmailClickedOnly,
    leadEmailOpenedOnly,
    leadTagFilterMode,
    leadWhatsappStatusFilter,
    leadWhatsappRepliedOnly,
    selectedLeadTagIds,
    selectedLeadEmailCampaignId,
    selectedLeadWhatsappCampaignId
  ]);
  const crmApiPath = useMemo(() => {
    const params = new URLSearchParams();
    if (selectedCrmFunnelIdValue) params.set("funnel_id", String(selectedCrmFunnelIdValue));
    selectedCrmTagIds.forEach((tagId) => params.append("tag_ids", String(tagId)));
    if (selectedCrmTagIds.length > 0) params.set("tag_filter_mode", crmTagFilterMode);
    const query = params.toString();
    return `/api/crm/leads${query ? `?${query}` : ""}`;
  }, [crmTagFilterMode, selectedCrmFunnelIdValue, selectedCrmTagIds]);
  const filteredLeads = useMemo(() => {
    const normalizedLeadNameQuery = leadNameQuery.trim().toLowerCase();
    return leads.filter((lead) => {
      const matchesName = !normalizedLeadNameQuery || lead.name.toLowerCase().includes(normalizedLeadNameQuery);
      const matchesNiche = selectedLeadNiches.length === 0 || selectedLeadNiches.includes(lead.niche);
      const matchesLocation = selectedLeadLocations.length === 0 || selectedLeadLocations.includes(lead.location);
      return matchesName && matchesNiche && matchesLocation;
    });
  }, [leadNameQuery, leads, selectedLeadNiches, selectedLeadLocations]);
  const leadServerFilters = useMemo(
    () => ({
      niche: selectedLeadNiches.length === 1 ? selectedLeadNiches[0] : undefined,
      location: selectedLeadLocations.length === 1 ? selectedLeadLocations[0] : undefined,
      search: leadNameQuery.trim() || undefined
    }),
    [leadNameQuery, selectedLeadLocations, selectedLeadNiches]
  );
  const leadWhatsappStatusFilterLabel = useMemo(
    () => LEAD_WHATSAPP_STATUS_OPTIONS.find((option) => option.value === leadWhatsappStatusFilter)?.label || "Todos",
    [leadWhatsappStatusFilter]
  );
  const leadPageCount = Math.max(1, Math.ceil(filteredLeads.length / LEADS_PAGE_SIZE));
  const currentLeadPage = Math.min(leadPage, leadPageCount);
  const leadPageStartIndex = (currentLeadPage - 1) * LEADS_PAGE_SIZE;
  const paginatedLeads = filteredLeads.slice(leadPageStartIndex, leadPageStartIndex + LEADS_PAGE_SIZE);
  const leadPageStart = filteredLeads.length === 0 ? 0 : leadPageStartIndex + 1;
  const leadPageEnd = Math.min(leadPageStartIndex + LEADS_PAGE_SIZE, filteredLeads.length);
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedIdsKey = selectedIds.join(",");
  const filteredLeadIds = useMemo(() => filteredLeads.map((lead) => lead.id), [filteredLeads]);
  const allVisibleSelected = filteredLeadIds.length > 0 && filteredLeadIds.every((leadId) => selectedIdSet.has(leadId));
  const leadRowsLoadedCount = leads.length;
  const hasMoreLeadsThanLoaded = leadTotalCount > leadRowsLoadedCount;
  const leadWhatsappValidationRunning = leadWhatsappValidationProgress.status === "running";
  const leadWhatsappValidationProgressPercent = leadWhatsappValidationProgress.total
    ? Math.min(100, Math.round((leadWhatsappValidationProgress.processed / leadWhatsappValidationProgress.total) * 100))
    : 0;
  const leadWhatsappValidationEstimatedDuration = formatHumanDuration(
    (leadWhatsappValidationPreview?.eligible_now || 0) * WHATSAPP_VALIDATION_DELAY_SECONDS
  );
  const leadWhatsappValidationFilterScopeNotice = useMemo(() => {
    if (leadWhatsappValidationScope !== "filters") return "";

    const notices = [];
    if (selectedLeadNiches.length > 1 || selectedLeadLocations.length > 1) {
      notices.push("A validação por filtros no banco inteiro usa um nicho e uma localidade por vez.");
    }
    if (leadWhatsappStatusFilter && (leadWhatsappStatusFilter !== "never" || leadWhatsappValidationRevalidate)) {
      notices.push("Para validar exatamente o status de WhatsApp filtrado na lista, selecione os leads visíveis.");
    }
    return notices.join(" ");
  }, [
    leadWhatsappStatusFilter,
    leadWhatsappValidationRevalidate,
    leadWhatsappValidationScope,
    selectedLeadLocations.length,
    selectedLeadNiches.length
  ]);
  const recentLeads = useMemo(() => leads.slice(0, 8), [leads]);
  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedTemplateId) || templates[0] || null,
    [templates, selectedTemplateId]
  );
  const selectedCampaignSendDays = useMemo(() => parseCampaignSendDays(campaignForm.send_days), [campaignForm.send_days]);
  const selectedWhatsappCampaignSendDays = useMemo(
    () => parseCampaignSendDays(whatsappCampaignForm.send_days),
    [whatsappCampaignForm.send_days]
  );
  const connectedWhatsappInstances = useMemo(
    () => whatsappInstances.filter((instance) => instance.status === "connected"),
    [whatsappInstances]
  );
  const disconnectedWhatsappInstances = useMemo(
    () => whatsappInstances.filter((instance) => instance.status === "disconnected"),
    [whatsappInstances]
  );
  const whatsappDashboard = useMemo(() => {
    const connected = whatsappInstances.filter((instance) => instance.status === "connected").length;
    const running = whatsappCampaigns.filter((campaign) => campaign.status === "running").length;
    const sent = whatsappCampaigns.reduce((total, campaign) => total + campaign.sent_count, 0);
    const total = whatsappCampaigns.reduce(
      (sum, campaign) => sum + campaign.pending_count + campaign.sent_count + campaign.delivered_count + campaign.read_count + campaign.failed_count,
      0
    );

    return { connected, running, sent, total };
  }, [whatsappCampaigns, whatsappInstances]);
  const crmLeadsByStage = useMemo(() => groupCrmLeadsByStage(crmLeads, selectedCrmStages), [crmLeads, selectedCrmStages]);
  const selectedCrmLead = useMemo(
    () => (crmDetailLeadId ? crmLeads.find((lead) => lead.lead_id === crmDetailLeadId) || null : null),
    [crmDetailLeadId, crmLeads]
  );
  const activeCrmDragLead = useMemo(
    () => (activeCrmDragLeadId ? crmLeads.find((lead) => lead.lead_id === activeCrmDragLeadId) || null : null),
    [activeCrmDragLeadId, crmLeads]
  );
  const previewTemplate = selectedTemplate || templateForm;
  const previewContentLink = previewTemplate.content_link.trim();
  const previewContentData = contentPreviews[previewContentLink];
  const previewSampleLead = leads[0];
  const emailDashboard = useMemo(() => {
    const sent = emailSends.filter((sendLog) => sendLog.status === "sent").length;
    const pending = emailSends.filter((sendLog) => sendLog.status === "pending").length;
    const failed = emailSends.filter((sendLog) => sendLog.status === "failed").length;
    const opened = emailSends.filter((sendLog) => sendLog.open_count > 0).length;
    const clicked = emailSends.filter((sendLog) => sendLog.click_count > 0).length;
    const opens = emailSends.reduce((total, sendLog) => total + sendLog.open_count, 0);
    const clicks = emailSends.reduce((total, sendLog) => total + sendLog.click_count, 0);
    const runningCampaigns = campaigns.filter((campaign) => campaign.status === "running").length;
    const completedCampaigns = campaigns.filter((campaign) => campaign.status === "completed").length;
    const templateStats = templates.map((template) => {
      const sends = emailSends.filter((sendLog) => sendLog.template_id === template.id);
      const templateSent = sends.filter((sendLog) => sendLog.status === "sent").length;
      const templateOpened = sends.filter((sendLog) => sendLog.open_count > 0).length;
      const templateClicked = sends.filter((sendLog) => sendLog.click_count > 0).length;
      return {
        id: template.id,
        name: template.name,
        sent: templateSent,
        opened: templateOpened,
        clicked: templateClicked,
        openRate: percent(templateOpened, templateSent),
        clickRate: percent(templateClicked, templateSent)
      };
    });

    return {
      sent,
      pending,
      failed,
      opened,
      clicked,
      opens,
      clicks,
      runningCampaigns,
      completedCampaigns,
      openRate: percent(opened, sent),
      clickRate: percent(clicked, sent),
      templateStats
    };
  }, [campaigns, emailSends, templates]);

  const historyCampaignOptions = useMemo(
    () => uniqueSortedValues(emailSends.map((sendLog) => sendLog.campaign_name)),
    [emailSends]
  );
  const historyTemplateOptions = useMemo(
    () => uniqueSortedValues(emailSends.map((sendLog) => sendLog.template_name)),
    [emailSends]
  );
  const historyStatusOptions = useMemo(
    () => uniqueSortedValues(emailSends.map((sendLog) => emailSendStatusLabel(sendLog.status))),
    [emailSends]
  );
  const filteredEmailSends = useMemo(() => {
    return emailSends.filter((sendLog) => {
      const campaignName = normalizeSegmentLabel(sendLog.campaign_name);
      const templateName = normalizeSegmentLabel(sendLog.template_name);
      const status = emailSendStatusLabel(sendLog.status);
      const matchesCampaign =
        selectedHistoryCampaigns.length === 0 || selectedHistoryCampaigns.includes(campaignName);
      const matchesTemplate =
        selectedHistoryTemplates.length === 0 || selectedHistoryTemplates.includes(templateName);
      const matchesStatus =
        selectedHistoryStatuses.length === 0 || selectedHistoryStatuses.includes(status);
      const matchesEngagement =
        selectedHistoryEngagements.length === 0 ||
        selectedHistoryEngagements.some((engagement) => {
          if (engagement === "Aberto") return sendLog.open_count > 0;
          if (engagement === "Clicado") return sendLog.click_count > 0;
          if (engagement === "Sem abertura") return sendLog.open_count === 0;
          if (engagement === "Sem clique") return sendLog.click_count === 0;
          return false;
        });

      return matchesCampaign && matchesTemplate && matchesStatus && matchesEngagement;
    });
  }, [
    emailSends,
    selectedHistoryCampaigns,
    selectedHistoryEngagements,
    selectedHistoryStatuses,
    selectedHistoryTemplates
  ]);
  const historyMetrics = useMemo(
    () => ({
      opens: filteredEmailSends.reduce((total, sendLog) => total + sendLog.open_count, 0),
      clicks: filteredEmailSends.reduce((total, sendLog) => total + sendLog.click_count, 0)
    }),
    [filteredEmailSends]
  );
  const historyPageCount = Math.max(1, Math.ceil(filteredEmailSends.length / HISTORY_PAGE_SIZE));
  const currentHistoryPage = Math.min(historyPage, historyPageCount);
  const historyPageStartIndex = (currentHistoryPage - 1) * HISTORY_PAGE_SIZE;
  const paginatedEmailSends = filteredEmailSends.slice(
    historyPageStartIndex,
    historyPageStartIndex + HISTORY_PAGE_SIZE
  );
  const historyPageStart = filteredEmailSends.length === 0 ? 0 : historyPageStartIndex + 1;
  const historyPageEnd = Math.min(historyPageStartIndex + HISTORY_PAGE_SIZE, filteredEmailSends.length);

  function leadWhatsappValidationPayload(): LeadWhatsAppValidationRequest {
    const payload: LeadWhatsAppValidationRequest = {
      only_pending: leadWhatsappStatusFilter === "never" && !leadWhatsappValidationRevalidate,
      revalidate: leadWhatsappValidationRevalidate
    };

    if (leadWhatsappValidationScope === "selected" && selectedIds.length > 0) {
      payload.lead_ids = selectedIds;
      return payload;
    }

    if (leadServerFilters.niche) payload.niche = leadServerFilters.niche;
    if (leadServerFilters.location) payload.location = leadServerFilters.location;
    if (leadServerFilters.search) payload.search = leadServerFilters.search;
    return payload;
  }

  function applyLeadWhatsappValidationProgress(
    progress: LeadWhatsAppValidationProgress,
    options: { showFinalSummary?: boolean } = {}
  ) {
    setLeadWhatsappValidationProgress(progress);
    if (!options.showFinalSummary || progress.status === "idle" || progress.status === "running") return;

    if (progress.status === "aborted") {
      setActionMessage("");
      setActionError(whatsappValidationFinalMessage(progress));
      return;
    }

    setActionError("");
    setActionMessage(whatsappValidationFinalMessage(progress));
  }

  async function refreshLeadWhatsappValidationProgress(options: { showFinalSummary?: boolean } = {}) {
    const progress = await apiFetch<LeadWhatsAppValidationProgress>("/api/leads/validate-whatsapp/progress");
    applyLeadWhatsappValidationProgress(progress, options);

    if (options.showFinalSummary && progress.status !== "idle" && progress.status !== "running") {
      await refreshData();
    }

    return progress;
  }

  async function refreshTags() {
    const nextTags = await apiFetch<LeadTag[]>("/api/tags");
    setTags(nextTags);
    return nextTags;
  }

  async function refreshData() {
    const [nextStats, nextSearches, nextLeadsResponse, nextTags] = await Promise.all([
      apiFetch<Stats>("/api/stats"),
      apiFetch<SearchRun[]>("/api/searches"),
      apiFetchWithResponse<Lead[]>(leadApiPath),
      apiFetch<LeadTag[]>("/api/tags")
    ]);

    setStats(nextStats);
    setSearches(nextSearches);
    setLeads(nextLeadsResponse.data);
    setTags(nextTags);
    setLeadTotalCount(Number(nextLeadsResponse.response.headers.get("X-Total-Count")) || nextLeadsResponse.data.length);
    setLeadResultLimit(Number(nextLeadsResponse.response.headers.get("X-Result-Limit")) || 500);
  }

  async function refreshEmailData() {
    const [nextSmtp, nextTemplates, nextLists, nextCampaigns, nextSends] = await Promise.all([
      apiFetch<SmtpConfig>("/api/email/smtp"),
      apiFetch<EmailTemplate[]>("/api/email/templates"),
      apiFetch<LeadList[]>("/api/email/lists"),
      apiFetch<EmailCampaign[]>("/api/email/campaigns"),
      apiFetch<EmailSendLog[]>("/api/email/sends")
    ]);

    setSmtpForm({ ...defaultSmtpForm, ...nextSmtp });
    setTemplates(nextTemplates);
    setLeadLists(nextLists);
    setCampaigns(nextCampaigns);
    setEmailSends(nextSends);
  }

  async function refreshWhatsappData() {
    const [nextInstances, nextTemplates, nextCampaigns, nextFunnels, nextCrmLeads, nextAiSettings, nextPortfolioItems, nextTags] = await Promise.all([
      apiFetch<WhatsAppInstance[]>("/api/whatsapp/instances"),
      apiFetch<WhatsAppMessageTemplate[]>("/api/whatsapp/templates"),
      apiFetch<WhatsAppCampaign[]>("/api/whatsapp/campaigns"),
      apiFetch<CrmFunnel[]>("/api/crm/funnels"),
      apiFetch<CrmLead[]>(crmApiPath),
      apiFetch<WhatsAppAiSettings>("/api/whatsapp/ai-settings"),
      apiFetch<WhatsAppPortfolioItem[]>("/api/whatsapp/portfolio"),
      apiFetch<LeadTag[]>("/api/tags")
    ]);

    setWhatsappInstances(nextInstances);
    setWhatsappTemplates(nextTemplates);
    setWhatsappCampaigns(nextCampaigns);
    setCrmFunnels(nextFunnels);
    setWhatsappAiSettings(nextAiSettings);
    setWhatsappAiForm({
      system_prompt: nextAiSettings.system_prompt,
      services_description: nextAiSettings.services_description || "",
      enabled: nextAiSettings.enabled,
      auto_apply_tags_enabled: nextAiSettings.auto_apply_tags_enabled
    });
    setWhatsappPortfolioItems(nextPortfolioItems);
    setCrmLeads(nextCrmLeads);
    setTags(nextTags);
    setCrmNoteDrafts((current) =>
      Object.fromEntries(
        nextCrmLeads.map((lead) => [lead.id, current[lead.id] ?? lead.qualification_notes ?? ""])
      )
    );
  }

  async function handleRefreshWhatsappData() {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction("refresh-whatsapp");

    try {
      await refreshWhatsappData();
      setWhatsappMessage("Dados de WhatsApp atualizados.");
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível atualizar os dados de WhatsApp.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  useEffect(() => {
    if (window.location.pathname === "/whatsapp/instancias") {
      setActiveView("whatsappInstances");
    } else if (window.location.pathname === "/whatsapp/templates") {
      setActiveView("whatsappTemplates");
    } else if (window.location.pathname === "/whatsapp/campanhas") {
      setActiveView("whatsappCampaigns");
    } else if (window.location.pathname === "/crm" || window.location.pathname === "/whatsapp/crm") {
      setActiveView("whatsappCrm");
    } else if (window.location.pathname === "/whatsapp/ia") {
      setActiveView("whatsappAi");
    } else if (window.location.pathname === "/whatsapp" || window.location.hash === "#whatsapp") {
      setActiveView("whatsapp");
    } else if (window.location.hash === "#leads") {
      setActiveView("leads");
    } else if (window.location.hash === "#email" || window.location.hash === "#dashboard") {
      setActiveView("dashboard");
    } else if (window.location.hash === "#templates") {
      setActiveView("templates");
    } else if (window.location.hash === "#listas") {
      setActiveView("lists");
    } else if (window.location.hash === "#campanhas") {
      setActiveView("campaigns");
    } else if (window.location.hash === "#historico") {
      setActiveView("history");
    } else if (window.location.hash === "#settings") {
      setActiveView("settings");
    }

    apiFetch<SessionInfo>("/api/auth/session")
      .then(async (session) => {
        if (session.authenticated && session.username) {
          setUser({ username: session.username });
          await refreshData();
          await refreshEmailData();
          await refreshWhatsappData();
        } else {
          setUser(null);
        }
      })
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  useEffect(() => {
    if (!user) return;

    const interval = window.setInterval(() => {
      refreshData().catch(() => undefined);
    }, activeRun ? 2500 : 6000);

    return () => window.clearInterval(interval);
  }, [user, activeRun, leadApiPath]);

  useEffect(() => {
    if (!user) return;

    refreshData().catch(() => undefined);
  }, [user, leadApiPath]);

  useEffect(() => {
    if (!user) return;

    refreshLeadWhatsappValidationProgress().catch(() => undefined);
  }, [user]);

  useEffect(() => {
    if (leadWhatsappValidationScope === "selected" && selectedIds.length === 0) {
      setLeadWhatsappValidationScope("filters");
    }
  }, [leadWhatsappValidationScope, selectedIds.length]);

  useEffect(() => {
    if (!leadWhatsappValidationDialogOpen) return;

    let cancelled = false;
    setLeadWhatsappValidationPreview(null);
    setLeadWhatsappValidationPreviewError("");
    setLeadWhatsappValidationPreviewLoading(true);

    apiFetch<LeadWhatsAppValidationPreview>("/api/leads/validate-whatsapp/preview", {
      method: "POST",
      body: JSON.stringify(leadWhatsappValidationPayload())
    })
      .then((preview) => {
        if (cancelled) return;
        setLeadWhatsappValidationPreview(preview);
      })
      .catch((error) => {
        if (cancelled) return;
        setLeadWhatsappValidationPreviewError(
          error instanceof Error ? error.message : "Não foi possível carregar a prévia."
        );
      })
      .finally(() => {
        if (cancelled) return;
        setLeadWhatsappValidationPreviewLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    leadServerFilters,
    leadWhatsappStatusFilter,
    leadWhatsappValidationDialogOpen,
    leadWhatsappValidationRevalidate,
    leadWhatsappValidationScope,
    selectedIdsKey
  ]);

  useEffect(() => {
    if (!user || !leadWhatsappValidationRunning) return;

    let cancelled = false;
    const interval = window.setInterval(async () => {
      try {
        const progress = await apiFetch<LeadWhatsAppValidationProgress>("/api/leads/validate-whatsapp/progress");
        if (cancelled) return;
        applyLeadWhatsappValidationProgress(progress, { showFinalSummary: true });
        if (progress.status !== "idle" && progress.status !== "running") {
          await refreshData();
        }
      } catch (error) {
        if (cancelled) return;
        setActionError(error instanceof Error ? error.message : "Não foi possível consultar o progresso.");
      }
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [leadApiPath, leadWhatsappValidationRunning, user]);

  useEffect(() => {
    setSelectedIds((current) => current.filter((id) => leads.some((lead) => lead.id === id)));
  }, [leads]);

  useEffect(() => {
    const availableTagIds = new Set(tags.map((tag) => tag.id));
    setSelectedLeadTagIds((current) => {
      const next = current.filter((id) => availableTagIds.has(id));
      return next.length === current.length ? current : next;
    });
    setSelectedCrmTagIds((current) => {
      const next = current.filter((id) => availableTagIds.has(id));
      return next.length === current.length ? current : next;
    });
    setLeadTagBulkTagIds((current) => {
      const next = current.filter((id) => availableTagIds.has(id));
      return next.length === current.length ? current : next;
    });
  }, [tags]);

  useEffect(() => {
    setLeadPage(1);
  }, [
    leadEmailClickedOnly,
    leadEmailOpenedOnly,
    leadNameQuery,
    leadTagFilterMode,
    leadWhatsappRepliedOnly,
    leadWhatsappStatusFilter,
    selectedLeadEmailCampaignId,
    selectedLeadTagIds,
    selectedLeadNiches,
    selectedLeadLocations,
    selectedLeadWhatsappCampaignId
  ]);

  useEffect(() => {
    setHistoryPage(1);
  }, [selectedHistoryCampaigns, selectedHistoryEngagements, selectedHistoryStatuses, selectedHistoryTemplates]);

  useEffect(() => {
    if (leadPage > leadPageCount) {
      setLeadPage(leadPageCount);
    }
  }, [leadPage, leadPageCount]);

  useEffect(() => {
    if (historyPage > historyPageCount) {
      setHistoryPage(historyPageCount);
    }
  }, [historyPage, historyPageCount]);

  useEffect(() => {
    if (runPage > runPageCount) {
      setRunPage(runPageCount);
    }
  }, [runPage, runPageCount]);

  useEffect(() => {
    setWhatsappCampaignForm((current) => {
      const listId =
        current.list_id && whatsappLeadLists.some((list) => String(list.id) === current.list_id)
          ? current.list_id
          : whatsappLeadLists[0]?.id
            ? String(whatsappLeadLists[0].id)
            : "";
      const instanceId =
        current.instance_id && connectedWhatsappInstances.some((instance) => String(instance.id) === current.instance_id)
          ? current.instance_id
          : connectedWhatsappInstances[0]?.id
            ? String(connectedWhatsappInstances[0].id)
            : "";
      const templateId =
        current.message_mode === "ai_per_lead"
          ? ""
          : current.template_id && whatsappTemplates.some((template) => String(template.id) === current.template_id)
            ? current.template_id
            : whatsappTemplates[0]?.id
              ? String(whatsappTemplates[0].id)
              : "";
      const funnelId =
        current.funnel_id && crmFunnels.some((funnel) => String(funnel.id) === current.funnel_id)
          ? current.funnel_id
          : "";

      if (
        listId === current.list_id &&
        instanceId === current.instance_id &&
        templateId === current.template_id &&
        funnelId === current.funnel_id
      ) {
        return current;
      }
      return { ...current, list_id: listId, instance_id: instanceId, template_id: templateId, funnel_id: funnelId };
    });
  }, [connectedWhatsappInstances, crmFunnels, whatsappLeadLists, whatsappTemplates]);

  useEffect(() => {
    if (templates.length === 0) {
      setSelectedTemplateId(null);
      return;
    }

    if (!selectedTemplateId || !templates.some((template) => template.id === selectedTemplateId)) {
      setSelectedTemplateId(templates[0].id);
    }
  }, [templates, selectedTemplateId]);

  useEffect(() => {
    if (!smtpTestTemplateId && templates.length > 0) {
      setSmtpTestTemplateId(String(templates[0].id));
    }
  }, [templates, smtpTestTemplateId]);

  useEffect(() => {
    if (!user || activeView !== "templates" || !previewContentLink || youtubeThumbnailUrl(previewContentLink) || previewContentData) {
      return;
    }

    let cancelled = false;
    apiFetch<ContentPreview>(`/api/email/content-preview?url=${encodeURIComponent(previewContentLink)}`)
      .then((preview) => {
        if (cancelled) return;
        setContentPreviews((current) => ({ ...current, [previewContentLink]: preview }));
      })
      .catch(() => {
        if (cancelled) return;
        setContentPreviews((current) => ({ ...current, [previewContentLink]: { url: previewContentLink, title: "", image_url: "" } }));
      });

    return () => {
      cancelled = true;
    };
  }, [user, activeView, previewContentLink, previewContentData]);

  const emailViews: AppView[] = ["dashboard", "templates", "lists", "campaigns", "history", "settings"];
  const whatsappViews: AppView[] = ["whatsapp", "whatsappInstances", "whatsappTemplates", "whatsappCampaigns", "whatsappCrm", "whatsappAi"];

  useEffect(() => {
    if (!user || !emailViews.includes(activeView)) return;

    refreshEmailData().catch(() => undefined);
  }, [user, activeView]);

  useEffect(() => {
    if (!user || !whatsappViews.includes(activeView)) return;

    refreshWhatsappData().catch(() => undefined);
    refreshEmailData().catch(() => undefined);
  }, [user, activeView, crmApiPath]);

  useEffect(() => {
    if (crmFunnels.length === 0) {
      setSelectedCrmFunnelId(null);
      return;
    }

    setSelectedCrmFunnelId((current) => {
      if (current && crmFunnels.some((funnel) => funnel.id === current)) return current;
      return crmFunnels.find((funnel) => funnel.is_default)?.id || crmFunnels[0].id;
    });
  }, [crmFunnels]);

  useEffect(() => {
    if (!user || !whatsappViews.includes(activeView)) return;

    // O backend reconfere o status da instância na Evolution periodicamente (mesmo
    // scheduler das campanhas); este intervalo só mantém a tela sincronizada com o que
    // já foi persistido, sem chamar a Evolution diretamente a partir do navegador.
    const interval = window.setInterval(() => {
      refreshWhatsappData().catch(() => undefined);
    }, 60000);

    return () => window.clearInterval(interval);
  }, [user, activeView, crmApiPath]);

  useEffect(() => {
    if (!selectedCrmLead) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        requestCloseCrmDetailModal();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedCrmLead, crmNoteDrafts]);

  function switchView(view: AppView) {
    setActiveView(view);
    const routes: Record<AppView, string> = {
      dashboard: "#dashboard",
      search: "#busca",
      leads: "#leads",
      whatsapp: "/whatsapp",
      whatsappInstances: "/whatsapp/instancias",
      whatsappTemplates: "/whatsapp/templates",
      whatsappCampaigns: "/whatsapp/campanhas",
      whatsappCrm: "/crm",
      whatsappAi: "/whatsapp/ia",
      templates: "#templates",
      lists: "#listas",
      campaigns: "#campanhas",
      history: "#historico",
      settings: "#settings"
    };
    const route = routes[view];
    window.history.replaceState(null, "", route.startsWith("/") ? route : `/${route}`);
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginError("");

    try {
      const me = await apiFetch<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      setUser(me);
      setPassword("");
      await refreshData();
      await refreshEmailData();
      await refreshWhatsappData();
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Login inválido.");
    }
  }

  async function handleLogout() {
    await apiFetch<{ status: string }>("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setUser(null);
    setSearches([]);
    setLeads([]);
    setTags([]);
    setLeadTotalCount(0);
    setLeadResultLimit(500);
    setSelectedIds([]);
    setEditingLead(null);
    setTagManagerOpen(false);
    setTagForm(defaultTagForm);
    setEditingTagId(null);
    setTagDeleteDialog(null);
    setSelectedLeadTagIds([]);
    setLeadTagFilterMode("any");
    setSelectedCrmTagIds([]);
    setCrmTagFilterMode("any");
    setLeadTagBulkDialog(null);
    setLeadTagBulkTagIds([]);
    setLeadTagBulkError("");
    setLeadTagBulkSaving(false);
    setCrmInlineTagForm(defaultTagForm);
    setTagError("");
    setTagMessage("");
    setTagBusyAction("");
    setManualLeadOpen(false);
    setManualLeadForm(defaultManualLeadForm);
    setDeleteDialog(null);
    setSelectedLeadNiches([]);
    setSelectedLeadLocations([]);
    setLeadWhatsappStatusFilter("");
    setLeadWhatsappValidationDialogOpen(false);
    setLeadWhatsappValidationProgress(idleLeadWhatsAppValidationProgress);
    setSelectedLeadEmailCampaignId("");
    setLeadEmailOpenedOnly(false);
    setLeadEmailClickedOnly(false);
    setSelectedLeadWhatsappCampaignId("");
    setLeadWhatsappRepliedOnly(false);
    setLeadPage(1);
    setTemplateDeleteDialog(null);
    setEmailMessage("");
    setEmailError("");
    setStats(emptyStats);
  }

  async function handleSaveSmtp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      await apiFetch<SmtpConfig>("/api/email/smtp", {
        method: "PUT",
        body: JSON.stringify({
          ...smtpForm,
          password: smtpPassword || null
        })
      });
      setSmtpPassword("");
      setEmailMessage("SMTP salvo.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível salvar o SMTP.");
    } finally {
      setEmailBusy(false);
    }
  }

  async function handleTestSmtp() {
    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      await apiFetch<{ status: string }>("/api/email/smtp/test", {
        method: "POST",
        body: JSON.stringify({
          to_email: smtpTestEmail,
          template_id: smtpTestTemplateId ? Number(smtpTestTemplateId) : null
        })
      });
      setEmailMessage(smtpTestTemplateId ? "Template de teste enviado." : "E-mail de teste enviado.");
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Teste SMTP falhou.");
    } finally {
      setEmailBusy(false);
    }
  }

  function resetTemplateEditor() {
    setEditingTemplateId(null);
    setTemplateForm({
      name: "",
      subject: "New video: {{content_title}}",
      html:
        '<div style="background:{{background_color}};padding:24px;"><img src="{{logo_url}}" height="56" alt="Automa Soluct" /><p style="color:{{text_color}};">Hi {{lead_name}},</p><p style="color:{{text_color}};">I wanted to share this content with you:</p><p><strong>{{content_title}}</strong></p>{{content_card_block}}<p style="color:{{text_color}};">We specialize in automation and integrations for service businesses. If you ever need help connecting tools, automating follow-ups, or reducing manual work, just click below and send me a quick note.</p><p><a style="background:{{primary_color}};color:#fff;text-decoration:none;padding:12px 18px;border-radius:6px;" href="{{get_in_touch_link}}">Get in touch</a></p><p style="color:{{text_color}};">Best,<br/>Cleiton</p></div>',
      text: "Hi {{lead_name}},\n\nI wanted to share this content with you:\n{{content_title}}\n{{content_link}}\n\nBest,\nCleiton",
      content_title: "",
      content_link: "",
      content_button_text: "Open the content",
      contact_mailto_subject: "Automation and integration help",
      contact_mailto_body:
        "Hi Cleiton,\n\nI saw your email about automation for {{company_name}} and would like to learn more.\n\n",
      logo_url: DEFAULT_TEMPLATE_LOGO,
      primary_color: "#0a0a0a",
      text_color: "#333333",
      background_color: "#f4f4f4"
    });
  }

  function openNewTemplateModal() {
    resetTemplateEditor();
    setTemplateModalOpen(true);
  }

  function loadTemplateForEdit(template: EmailTemplate) {
    setSelectedTemplateId(template.id);
    setEditingTemplateId(template.id);
    setTemplateModalOpen(true);
    setTemplateForm({
      name: template.name,
      subject: template.subject,
      html: template.html,
      text: template.text,
      content_title: template.content_title,
      content_link: template.content_link,
      content_button_text: template.content_button_text || "Open the content",
      contact_mailto_subject: template.contact_mailto_subject || "Automation and integration help",
      contact_mailto_body:
        template.contact_mailto_body ||
        "Hi Cleiton,\n\nI saw your email about automation for {{company_name}} and would like to learn more.\n\n",
      logo_url: template.logo_url,
      primary_color: template.primary_color,
      text_color: template.text_color,
      background_color: template.background_color
    });
  }

  async function handleSaveTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      const wasEditing = Boolean(editingTemplateId);
      const savedTemplate = await apiFetch<EmailTemplate>(
        editingTemplateId ? `/api/email/templates/${editingTemplateId}` : "/api/email/templates",
        {
          method: editingTemplateId ? "PATCH" : "POST",
          body: JSON.stringify(templateForm)
        }
      );
      setSelectedTemplateId(savedTemplate.id);
      setTemplateModalOpen(false);
      setEditingTemplateId(null);
      if (!wasEditing) setTemplateForm({ ...templateForm, name: "" });
      setEmailMessage(wasEditing ? "Template atualizado." : "Template criado.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível salvar o template.");
    } finally {
      setEmailBusy(false);
    }
  }

  function handleDeleteTemplate(template: EmailTemplate) {
    setEmailError("");
    setEmailMessage("");
    setTemplateDeleteDialog(template);
  }

  async function confirmDeleteTemplate() {
    if (!templateDeleteDialog) return;

    const template = templateDeleteDialog;

    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      await apiFetch<{ status: string }>(`/api/email/templates/${template.id}`, {
        method: "DELETE"
      });
      if (editingTemplateId === template.id) {
        resetTemplateEditor();
      }
      setSelectedTemplateId(null);
      setTemplateDeleteDialog(null);
      setEmailMessage("Template excluído.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível excluir o template.");
    } finally {
      setEmailBusy(false);
    }
  }

  function openAiTemplateModal() {
    const source = selectedTemplate || templateForm;
    const nextNiches = selectedLeadNiches.length > 0 ? selectedLeadNiches : decodeListFilterValues(aiForm.niche);
    const nextLocations = selectedLeadLocations.length > 0 ? selectedLeadLocations : decodeListFilterValues(aiForm.location);
    setEmailError("");
    setEmailMessage("");
    setSelectedAiNiches(nextNiches);
    setSelectedAiLocations(nextLocations);
    setAiForm((current) => ({
      ...defaultAiTemplateForm,
      ...current,
      niche: encodeListFilterValues(nextNiches),
      location: encodeListFilterValues(nextLocations),
      campaign_name: current.campaign_name || (niche ? `Sequence for ${niche}` : ""),
      content_title: source.content_title || current.content_title,
      content_link: source.content_link || current.content_link,
      logo_url: source.logo_url || DEFAULT_TEMPLATE_LOGO,
      primary_color: source.primary_color || "#0a0a0a",
      text_color: source.text_color || "#333333",
      background_color: source.background_color || "#f4f4f4"
    }));
    setAiModalOpen(true);
  }

  async function handleGenerateTemplatesWithAi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEmailError("");
    setEmailMessage("");
    setAiBusy(true);

    try {
      const payload = {
        ...aiForm,
        count: Number(aiForm.count),
        niche: encodeListFilterValues(selectedAiNiches),
        location: encodeListFilterValues(selectedAiLocations)
      };
      const result = await apiFetch<AiTemplateGenerateResponse>("/api/email/templates/ai-generate", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      await refreshEmailData();
      if (result.templates.length > 0) {
        setSelectedTemplateId(result.templates[0].id);
      }
      setAiModalOpen(false);
      setEmailMessage(result.templates.length === 1 ? "Template gerado com IA." : "Sequência gerada com IA.");
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível gerar templates com IA.");
    } finally {
      setAiBusy(false);
    }
  }

  async function handleCreateLeadList(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      await apiFetch<LeadList>("/api/email/lists", {
        method: "POST",
        body: JSON.stringify({
          name: leadListForm.name,
          channel: leadListForm.channel,
          niche_filter: encodeListFilterValues(selectedListNiches),
          location_filter: encodeListFilterValues(selectedListLocations),
          search_run_id: null,
          only_never_emailed: leadListForm.only_never_emailed,
          only_whatsapp_validated: leadListForm.only_whatsapp_validated,
          only_email_opened: leadListForm.only_email_opened,
          only_email_clicked: leadListForm.only_email_clicked,
          email_engagement_filter_mode: leadListForm.email_engagement_filter_mode,
          never_received_template_id: leadListForm.never_received_template_id
            ? Number(leadListForm.never_received_template_id)
            : null
        })
      });
      setLeadListForm({ ...leadListForm, name: "", search_run_id: "" });
      setSelectedListNiches([]);
      setSelectedListLocations([]);
      setEmailMessage("Lista criada.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível criar a lista.");
    } finally {
      setEmailBusy(false);
    }
  }

  function openEditLeadListModal(list: LeadList) {
    setEmailError("");
    setEmailMessage("");
    setEditingLeadList(list);
    setEditLeadListForm({
      name: list.name,
      channel: list.channel,
      only_never_emailed: list.only_never_emailed,
      only_whatsapp_validated: list.only_whatsapp_validated,
      only_email_opened: list.only_email_opened,
      only_email_clicked: list.only_email_clicked,
      email_engagement_filter_mode: list.email_engagement_filter_mode,
      never_received_template_id: list.never_received_template_id ? String(list.never_received_template_id) : ""
    });
    setSelectedEditListNiches(decodeListFilterValues(list.niche_filter));
    setSelectedEditListLocations(decodeListFilterValues(list.location_filter));
  }

  function closeEditLeadListModal() {
    setEmailError("");
    setEditingLeadList(null);
    setSelectedEditListNiches([]);
    setSelectedEditListLocations([]);
    setEditLeadListForm({
      name: "",
      channel: "both",
      only_never_emailed: false,
      only_whatsapp_validated: false,
      only_email_opened: false,
      only_email_clicked: false,
      email_engagement_filter_mode: "or",
      never_received_template_id: ""
    });
  }

  function handleDeleteLeadList(list: LeadList) {
    setEmailError("");
    setEmailMessage("");
    setLeadListDeleteDialog(list);
  }

  async function handleSaveLeadList(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingLeadList) return;

    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      await apiFetch<LeadList>(`/api/email/lists/${editingLeadList.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: editLeadListForm.name,
          channel: editLeadListForm.channel,
          niche_filter: encodeListFilterValues(selectedEditListNiches),
          location_filter: encodeListFilterValues(selectedEditListLocations),
          search_run_id: editingLeadList.search_run_id,
          only_never_emailed: editLeadListForm.only_never_emailed,
          only_whatsapp_validated: editLeadListForm.only_whatsapp_validated,
          only_email_opened: editLeadListForm.only_email_opened,
          only_email_clicked: editLeadListForm.only_email_clicked,
          email_engagement_filter_mode: editLeadListForm.email_engagement_filter_mode,
          never_received_template_id: editLeadListForm.never_received_template_id
            ? Number(editLeadListForm.never_received_template_id)
            : null
        })
      });
      closeEditLeadListModal();
      setEmailMessage("Lista atualizada.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível atualizar a lista.");
    } finally {
      setEmailBusy(false);
    }
  }

  async function confirmDeleteLeadList() {
    if (!leadListDeleteDialog) return;

    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      await apiFetch(`/api/email/lists/${leadListDeleteDialog.id}`, { method: "DELETE" });
      setLeadListDeleteDialog(null);
      setEmailMessage("Lista excluída.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível excluir a lista.");
    } finally {
      setEmailBusy(false);
    }
  }

  function resetCampaignEditor() {
    setEditingCampaignId(null);
    setCampaignForm({
      ...defaultCampaignForm,
      list_id: emailLeadLists[0]?.id ? String(emailLeadLists[0].id) : "",
      template_ids: templates[0]?.id ? [templates[0].id] : []
    });
  }

  function openNewCampaignModal() {
    resetCampaignEditor();
    setEmailError("");
    setEmailMessage("");
    setCampaignModalOpen(true);
  }

  function loadCampaignForEdit(campaign: EmailCampaign) {
    setEmailError("");
    setEmailMessage("");
    setEditingCampaignId(campaign.id);
    setCampaignForm({
      name: campaign.name,
      objective: campaign.objective || "",
      message_mode: campaign.message_mode || "template",
      language: campaign.language || "pt",
      list_id: String(campaign.list_id),
      template_ids: campaign.template_ids || [],
      min_delay_seconds: campaign.min_delay_seconds,
      max_delay_seconds: campaign.max_delay_seconds,
      daily_limit: campaign.daily_limit,
      weekly_limit: campaign.weekly_limit,
      send_window_start: campaign.send_window_start,
      send_window_end: campaign.send_window_end,
      timezone_name: campaign.timezone_name || "America/New_York",
      send_days: campaign.send_days,
    });
    setCampaignModalOpen(true);
  }

  function toggleCampaignTemplate(templateId: number) {
    setCampaignForm((current) => ({
      ...current,
      template_ids: current.template_ids.includes(templateId)
        ? current.template_ids.filter((id) => id !== templateId)
        : [...current.template_ids, templateId]
    }));
  }

  function toggleCampaignSendDay(day: string) {
    setCampaignForm((current) => {
      const nextDays = parseCampaignSendDays(current.send_days);

      if (nextDays.has(day)) {
        if (nextDays.size === 1) return current;
        nextDays.delete(day);
      } else {
        nextDays.add(day);
      }

      return { ...current, send_days: formatCampaignSendDays(nextDays) };
    });
  }

  async function handleSaveCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEmailError("");
    setEmailMessage("");

    if (!campaignForm.list_id || campaignForm.template_ids.length === 0) {
      setEmailError("Escolha uma lista e ao menos um template visual.");
      return;
    }

    if (campaignForm.message_mode === "ai_per_lead" && !campaignForm.objective.trim()) {
      setEmailError("Informe o objetivo para gerar e-mails individuais com IA.");
      return;
    }

    setEmailBusy(true);
    try {
      await apiFetch<EmailCampaign>(editingCampaignId ? `/api/email/campaigns/${editingCampaignId}` : "/api/email/campaigns", {
        method: editingCampaignId ? "PATCH" : "POST",
        body: JSON.stringify({
          ...campaignForm,
          list_id: Number(campaignForm.list_id),
          templates: campaignForm.template_ids.map((template_id) => ({ template_id, weight: 1 }))
        })
      });
      setCampaignModalOpen(false);
      setEditingCampaignId(null);
      setCampaignForm(defaultCampaignForm);
      setEmailMessage(editingCampaignId ? "Campanha atualizada." : "Campanha criada.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível salvar a campanha.");
    } finally {
      setEmailBusy(false);
    }
  }

  async function handleCampaignAction(campaignId: number, action: "start" | "pause") {
    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      await apiFetch<EmailCampaign>(`/api/email/campaigns/${campaignId}/${action}`, { method: "POST" });
      setEmailMessage(action === "start" ? "Campanha iniciada." : "Campanha pausada.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível atualizar a campanha.");
    } finally {
      setEmailBusy(false);
    }
  }

  function handleDeleteCampaign(campaign: EmailCampaign) {
    setEmailError("");
    setEmailMessage("");
    setCampaignDeleteDialog(campaign);
  }

  async function confirmDeleteCampaign() {
    if (!campaignDeleteDialog) return;

    const campaign = campaignDeleteDialog;

    setEmailError("");
    setEmailMessage("");
    setEmailBusy(true);

    try {
      await apiFetch<{ status: string }>(`/api/email/campaigns/${campaign.id}`, {
        method: "DELETE"
      });
      if (editingCampaignId === campaign.id) {
        resetCampaignEditor();
        setCampaignModalOpen(false);
      }
      setCampaignDeleteDialog(null);
      setEmailMessage("Campanha excluída.");
      await refreshEmailData();
    } catch (error) {
      setEmailError(error instanceof Error ? error.message : "Não foi possível excluir a campanha.");
    } finally {
      setEmailBusy(false);
    }
  }

  function updateWhatsappInstanceFromStatus(statusResponse: WhatsAppInstanceStatusResponse) {
    const mergeStatus = (instance: WhatsAppInstance): WhatsAppInstance => ({
      ...instance,
      status: statusResponse.status,
      phone_number: statusResponse.phone_number || instance.phone_number,
      connected_at: statusResponse.connected_at || instance.connected_at
    });

    setWhatsappInstances((current) =>
      current.map((instance) => (instance.id === statusResponse.id ? mergeStatus(instance) : instance))
    );
    setWhatsappQrModal((current) =>
      current && current.instance.id === statusResponse.id
        ? { ...current, instance: mergeStatus(current.instance) }
        : current
    );
  }

  async function handleCreateWhatsappInstance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWhatsappError("");
    setWhatsappMessage("");

    const name = whatsappInstanceForm.name.trim();
    const phoneNumber = whatsappInstanceForm.phone_number.trim();

    if (!name) {
      setWhatsappInstanceFormErrors({ name: "Informe um nome para a instância." });
      return;
    }

    setWhatsappInstanceFormErrors({});
    setWhatsappBusyAction("create-instance");

    try {
      await apiFetch<WhatsAppInstance>("/api/whatsapp/instances", {
        method: "POST",
        body: JSON.stringify({ name, phone_number: phoneNumber || null })
      });
      setWhatsappInstanceForm(defaultWhatsappInstanceForm);
      setWhatsappMessage("Instância criada. Abra o QR Code para conectar.");
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível criar a instância.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  async function handleOpenWhatsappQrCode(instance: WhatsAppInstance) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`qr-${instance.id}`);

    try {
      const qrCode = await apiFetch<WhatsAppQrCodeResponse>(`/api/whatsapp/instances/${instance.id}/qrcode`);
      setWhatsappQrModal({ instance, qrCode });
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível carregar o QR Code.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  async function handleRefreshWhatsappInstanceStatus(instanceId: number) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`status-${instanceId}`);

    try {
      const statusResponse = await apiFetch<WhatsAppInstanceStatusResponse>(`/api/whatsapp/instances/${instanceId}/status`);
      updateWhatsappInstanceFromStatus(statusResponse);
      setWhatsappMessage(`Status atualizado: ${whatsappInstanceStatusLabel(statusResponse.status)}.`);
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível atualizar o status.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  function handleDeleteWhatsappInstance(instance: WhatsAppInstance) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappInstanceDeleteDialog(instance);
  }

  async function confirmDeleteWhatsappInstance() {
    if (!whatsappInstanceDeleteDialog) return;

    const instance = whatsappInstanceDeleteDialog;
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`delete-instance-${instance.id}`);

    try {
      await apiFetch<{ status: string }>(`/api/whatsapp/instances/${instance.id}`, { method: "DELETE" });
      setWhatsappInstanceDeleteDialog(null);
      setWhatsappQrModal((current) => (current?.instance.id === instance.id ? null : current));
      setWhatsappMessage("Instância excluída.");
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível excluir a instância.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  function resetWhatsappTemplateForm() {
    setEditingWhatsappTemplateId(null);
    setWhatsappTemplateForm(defaultWhatsappTemplateForm);
    setWhatsappTemplateFormErrors({});
  }

  function loadWhatsappTemplateForEdit(template: WhatsAppMessageTemplate) {
    setWhatsappError("");
    setWhatsappMessage("");
    setEditingWhatsappTemplateId(template.id);
    setWhatsappTemplateForm({
      name: template.name,
      content: template.content
    });
    setWhatsappTemplateFormErrors({});
    switchView("whatsappTemplates");
  }

  function validateWhatsappTemplateForm() {
    const errors: WhatsAppTemplateFormErrors = {};
    if (!whatsappTemplateForm.name.trim()) {
      errors.name = "Informe o nome do template.";
    }
    if (!whatsappTemplateForm.content.trim()) {
      errors.content = "Escreva o texto do template.";
    }

    setWhatsappTemplateFormErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSaveWhatsappTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWhatsappError("");
    setWhatsappMessage("");

    if (!validateWhatsappTemplateForm()) {
      return;
    }

    setWhatsappBusyAction("save-template");

    try {
      await apiFetch<WhatsAppMessageTemplate>(
        editingWhatsappTemplateId ? `/api/whatsapp/templates/${editingWhatsappTemplateId}` : "/api/whatsapp/templates",
        {
          method: editingWhatsappTemplateId ? "PATCH" : "POST",
          body: JSON.stringify({
            name: whatsappTemplateForm.name.trim(),
            content: whatsappTemplateForm.content.trim()
          })
        }
      );
      setWhatsappMessage(editingWhatsappTemplateId ? "Template atualizado." : "Template criado.");
      resetWhatsappTemplateForm();
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível salvar o template.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  function requestDeleteWhatsappTemplate(template: WhatsAppMessageTemplate) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappTemplateDeleteDialog(template);
  }

  async function confirmDeleteWhatsappTemplate() {
    if (!whatsappTemplateDeleteDialog) return;

    const template = whatsappTemplateDeleteDialog;
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`delete-template-${template.id}`);

    try {
      await apiFetch<{ status: string }>(`/api/whatsapp/templates/${template.id}`, { method: "DELETE" });
      if (editingWhatsappTemplateId === template.id) {
        resetWhatsappTemplateForm();
      }
      setWhatsappTemplateDeleteDialog(null);
      setWhatsappMessage("Template excluído.");
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível excluir o template.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  async function handleGenerateWhatsappTemplateWithAi() {
    setWhatsappError("");
    setWhatsappMessage("");
    const objective = whatsappTemplateObjective.trim();

    if (!objective) {
      setWhatsappError("Descreva o objetivo antes de gerar o template.");
      return;
    }

    setWhatsappBusyAction("generate-template-ai");
    try {
      const generated = await apiFetch<WhatsAppTemplateGenerateResponse>("/api/whatsapp/templates/generate", {
        method: "POST",
        body: JSON.stringify({ objective })
      });
      setWhatsappTemplateForm((current) => ({
        ...current,
        content: generated.content
      }));
      setWhatsappTemplateFormErrors((current) => ({ ...current, content: "" }));
      setWhatsappMessage("Sugestão gerada. Revise o texto antes de salvar.");
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível gerar o template com IA.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  function toggleWhatsappCampaignSendDay(day: string) {
    setWhatsappCampaignForm((current) => {
      const nextDays = parseCampaignSendDays(current.send_days);

      if (nextDays.has(day)) {
        nextDays.delete(day);
      } else {
        nextDays.add(day);
      }

      return { ...current, send_days: formatCampaignSendDays(nextDays) };
    });
  }

  function openNewWhatsappCampaignModal() {
    setWhatsappError("");
    setWhatsappMessage("");
    setEditingWhatsappCampaignId(null);
    setWhatsappCampaignFormErrors({});
    setWhatsappCampaignForm((current) => ({
      ...defaultWhatsappCampaignForm,
      list_id:
        current.list_id && whatsappLeadLists.some((list) => String(list.id) === current.list_id)
          ? current.list_id
          : whatsappLeadLists[0]?.id
            ? String(whatsappLeadLists[0].id)
            : "",
      funnel_id: "",
      instance_id:
        current.instance_id && connectedWhatsappInstances.some((instance) => String(instance.id) === current.instance_id)
          ? current.instance_id
          : connectedWhatsappInstances[0]?.id
            ? String(connectedWhatsappInstances[0].id)
            : "",
      template_id:
        current.template_id && whatsappTemplates.some((template) => String(template.id) === current.template_id)
          ? current.template_id
          : whatsappTemplates[0]?.id
            ? String(whatsappTemplates[0].id)
            : ""
    }));
    setWhatsappCampaignModalOpen(true);
  }

  function loadWhatsappCampaignForEdit(campaign: WhatsAppCampaign) {
    setWhatsappError("");
    setWhatsappMessage("");
    setEditingWhatsappCampaignId(campaign.id);
    setWhatsappCampaignFormErrors({});
    setWhatsappCampaignForm({
      name: campaign.name,
      objective: campaign.objective || "",
      message_mode: campaign.message_mode || "template",
      language: campaign.language || "pt",
      list_id: String(campaign.list_id),
      funnel_id: campaign.funnel_id ? String(campaign.funnel_id) : "",
      instance_id: String(campaign.instance_id),
      template_id: campaign.template_ids[0] ? String(campaign.template_ids[0]) : "",
      min_delay_seconds: campaign.min_delay_seconds,
      max_delay_seconds: campaign.max_delay_seconds,
      daily_limit: campaign.daily_limit,
      weekly_limit: campaign.weekly_limit,
      send_window_start: campaign.send_window_start,
      send_window_end: campaign.send_window_end,
      timezone_name: campaign.timezone_name || "America/Sao_Paulo",
      send_days: campaign.send_days
    });
    setWhatsappCampaignModalOpen(true);
  }

  function closeWhatsappCampaignModal() {
    setWhatsappCampaignModalOpen(false);
    setEditingWhatsappCampaignId(null);
    setWhatsappCampaignFormErrors({});
  }

  function validateWhatsappCampaignForm() {
    const errors: WhatsAppCampaignFormErrors = {};
    const minDelay = Number(whatsappCampaignForm.min_delay_seconds);
    const maxDelay = Number(whatsappCampaignForm.max_delay_seconds);

    if (!whatsappCampaignForm.name.trim()) {
      errors.name = "Informe o nome da campanha.";
    }
    if (whatsappCampaignForm.message_mode === "ai_per_lead" && !whatsappCampaignForm.objective.trim()) {
      errors.objective = "Informe o objetivo para gerar mensagens individuais com IA.";
    }
    if (!whatsappCampaignForm.list_id) {
      errors.list_id = "Escolha uma lista de leads.";
    }
    if (whatsappCampaignForm.funnel_id && !crmFunnels.some((funnel) => String(funnel.id) === whatsappCampaignForm.funnel_id)) {
      errors.funnel_id = "Escolha um funil válido.";
    }
    if (!whatsappCampaignForm.instance_id) {
      errors.instance_id = "Escolha uma instância conectada.";
    }
    if (whatsappCampaignForm.message_mode === "template" && !whatsappCampaignForm.template_id) {
      errors.template_id = "Escolha um template de mensagem.";
    }
    if (!Number.isFinite(minDelay) || minDelay < 1) {
      errors.min_delay_seconds = "Use um delay mínimo de pelo menos 1 segundo.";
    }
    if (!Number.isFinite(maxDelay) || maxDelay < 1) {
      errors.max_delay_seconds = "Use um delay máximo de pelo menos 1 segundo.";
    }
    if (Number.isFinite(minDelay) && Number.isFinite(maxDelay) && minDelay >= maxDelay) {
      errors.max_delay_seconds = "O delay máximo precisa ser maior que o mínimo.";
    }
    if (parseCampaignSendDays(whatsappCampaignForm.send_days).size === 0) {
      errors.send_days = "Escolha ao menos um dia de envio.";
    }

    setWhatsappCampaignFormErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSaveWhatsappCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWhatsappError("");
    setWhatsappMessage("");

    if (!validateWhatsappCampaignForm()) {
      return;
    }

    const { template_id, ...campaignPayload } = whatsappCampaignForm;
    const templates =
      whatsappCampaignForm.message_mode === "template" ? [{ template_id: Number(template_id), weight: 1 }] : [];
    const funnelId = whatsappCampaignForm.funnel_id ? Number(whatsappCampaignForm.funnel_id) : null;
    setWhatsappBusyAction("create-campaign");

    try {
      await apiFetch<WhatsAppCampaign>(
        editingWhatsappCampaignId ? `/api/whatsapp/campaigns/${editingWhatsappCampaignId}` : "/api/whatsapp/campaigns",
        {
          method: editingWhatsappCampaignId ? "PATCH" : "POST",
          body: JSON.stringify({
            ...campaignPayload,
            list_id: Number(whatsappCampaignForm.list_id),
            funnel_id: funnelId,
            instance_id: Number(whatsappCampaignForm.instance_id),
            templates
          })
        }
      );
      setWhatsappCampaignForm({
        ...defaultWhatsappCampaignForm,
        list_id: whatsappLeadLists[0]?.id ? String(whatsappLeadLists[0].id) : "",
        funnel_id: "",
        instance_id: connectedWhatsappInstances[0]?.id ? String(connectedWhatsappInstances[0].id) : "",
        template_id: whatsappTemplates[0]?.id ? String(whatsappTemplates[0].id) : ""
      });
      setWhatsappCampaignModalOpen(false);
      setWhatsappMessage(editingWhatsappCampaignId ? "Campanha atualizada." : "Campanha criada.");
      setEditingWhatsappCampaignId(null);
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível salvar a campanha.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  function requestStartWhatsappCampaign(campaign: WhatsAppCampaign) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappCampaignStartDialog(campaign);
  }

  async function confirmStartWhatsappCampaign() {
    if (!whatsappCampaignStartDialog) return;

    const campaign = whatsappCampaignStartDialog;
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`start-campaign-${campaign.id}`);

    try {
      await apiFetch<WhatsAppCampaign>(`/api/whatsapp/campaigns/${campaign.id}/start`, { method: "POST" });
      setWhatsappCampaignStartDialog(null);
      setWhatsappMessage("Campanha iniciada.");
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível iniciar a campanha.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  async function pauseWhatsappCampaign(campaign: WhatsAppCampaign) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`pause-campaign-${campaign.id}`);

    try {
      await apiFetch<WhatsAppCampaign>(`/api/whatsapp/campaigns/${campaign.id}/pause`, { method: "POST" });
      setWhatsappMessage("Campanha pausada.");
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível pausar a campanha.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  function requestDeleteWhatsappCampaign(campaign: WhatsAppCampaign) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappCampaignDeleteDialog(campaign);
  }

  async function confirmDeleteWhatsappCampaign() {
    if (!whatsappCampaignDeleteDialog) return;

    const campaign = whatsappCampaignDeleteDialog;
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`delete-campaign-${campaign.id}`);

    try {
      await apiFetch<{ status: string }>(`/api/whatsapp/campaigns/${campaign.id}`, { method: "DELETE" });
      setWhatsappCampaignDeleteDialog(null);
      setWhatsappMessage("Campanha excluída.");
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível excluir a campanha.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  function crmNotesChanged(lead: CrmLead | null) {
    if (!lead) return false;
    const noteDraft = crmNoteDrafts[lead.id] ?? lead.qualification_notes ?? "";
    return noteDraft !== (lead.qualification_notes || "");
  }

  function openCrmDetailModal(lead: CrmLead) {
    setWhatsappError("");
    setWhatsappMessage("");
    setCrmDetailLeadId(lead.lead_id);
  }

  function requestCloseCrmDetailModal() {
    if (crmNotesChanged(selectedCrmLead)) {
      const shouldClose = window.confirm("Há notas não salvas neste lead. Fechar mesmo assim?");
      if (!shouldClose) return;
      if (selectedCrmLead) {
        setCrmNoteDrafts((current) => ({
          ...current,
          [selectedCrmLead.id]: selectedCrmLead.qualification_notes || ""
        }));
      }
    }
    setCrmDetailLeadId(null);
  }

  function handleCrmDetailBackdropMouseDown(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) {
      requestCloseCrmDetailModal();
    }
  }

  function handleCrmDragStart(event: DragStartEvent) {
    const leadId = parseCrmLeadDragId(event.active.id);
    if (!leadId) return;
    const lead = crmLeads.find((item) => item.lead_id === leadId);
    setActiveCrmDragLeadId(leadId);
    setOverCrmStage(lead?.stage || null);
  }

  function handleCrmDragOver(event: DragOverEvent) {
    setOverCrmStage(crmDropTargetStage(event.over, selectedCrmStages));
  }

  function handleCrmDragCancel() {
    setActiveCrmDragLeadId(null);
    setOverCrmStage(null);
  }

  async function handleCrmDragEnd(event: DragEndEvent) {
    const leadId = parseCrmLeadDragId(event.active.id);
    const targetStage = crmDropTargetStage(event.over, selectedCrmStages);
    setActiveCrmDragLeadId(null);
    setOverCrmStage(null);

    if (!leadId || !targetStage || !selectedCrmFunnelIdValue) return;

    const previousLeads = crmLeads;
    const grouped = groupCrmLeadsByStage(previousLeads, selectedCrmStages);
    const targetIndex = crmTargetIndex(event.over?.id, targetStage, grouped);
    const moveResult = moveCrmLeadForBoard(previousLeads, leadId, targetStage, targetIndex, selectedCrmStages);
    if (!moveResult.changed) return;

    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`crm-${leadId}`);
    setCrmLeads(moveResult.leads);

    try {
      const updatedLead = await apiFetch<CrmLead>(`/api/crm/leads/${leadId}`, {
        method: "PATCH",
        body: JSON.stringify({ stage: targetStage, position: moveResult.position, funnel_id: selectedCrmFunnelIdValue })
      });
      setCrmLeads((current) => current.map((lead) => (lead.id === updatedLead.id ? { ...lead, ...updatedLead } : lead)));
      setCrmNoteDrafts((current) => ({ ...current, [updatedLead.id]: updatedLead.qualification_notes || "" }));
      setWhatsappMessage("CRM atualizado.");
    } catch (error) {
      setCrmLeads(previousLeads);
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível mover o card no CRM.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  async function patchCrmLead(
    leadId: number,
    payload: { stage?: CrmStage; position?: number; qualification_notes?: string | null; funnel_id?: number }
  ) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`crm-${leadId}`);
    const shouldRefreshBoardOrder = payload.stage !== undefined || payload.position !== undefined;
    const currentLead = crmLeads.find((lead) => lead.lead_id === leadId);
    const requestPayload = {
      ...payload,
      funnel_id: payload.funnel_id ?? currentLead?.funnel_id ?? selectedCrmFunnelIdValue ?? undefined
    };

    try {
      const updatedLead = await apiFetch<CrmLead>(`/api/crm/leads/${leadId}`, {
        method: "PATCH",
        body: JSON.stringify(requestPayload)
      });
      setCrmLeads((current) => current.map((lead) => (lead.id === updatedLead.id ? updatedLead : lead)));
      setCrmNoteDrafts((current) => ({ ...current, [updatedLead.id]: updatedLead.qualification_notes || "" }));
      setWhatsappMessage("CRM atualizado.");
      if (shouldRefreshBoardOrder) {
        await refreshWhatsappData();
      }
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível atualizar o CRM.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  function handleCrmStageChange(lead: CrmLead, stage: CrmStage) {
    if (stage === lead.stage) return;
    patchCrmLead(lead.lead_id, { stage, funnel_id: lead.funnel_id });
  }

  function handleCrmNoteChange(cardId: number, notes: string) {
    setCrmNoteDrafts((current) => ({ ...current, [cardId]: notes }));
  }

  function saveCrmNotes(lead: CrmLead) {
    patchCrmLead(lead.lead_id, { funnel_id: lead.funnel_id, qualification_notes: crmNoteDrafts[lead.id] || null });
  }

  function applyLeadTagSnapshot(updatedLead: Lead) {
    setLeads((current) => current.map((lead) => (lead.id === updatedLead.id ? updatedLead : lead)));
    setCrmLeads((current) =>
      current.map((lead) =>
        lead.lead_id === updatedLead.id
          ? {
              ...lead,
              phone: updatedLead.phone,
              whatsapp_url: updatedLead.whatsapp_url,
              website: updatedLead.website,
              email: updatedLead.email,
              niche: updatedLead.niche,
              location: updatedLead.location,
              tags: updatedLead.tags
            }
          : lead
      )
    );
    setEditingLead((current) => (current?.id === updatedLead.id ? updatedLead : current));
  }

  async function refreshCrmFunnels() {
    const nextFunnels = await apiFetch<CrmFunnel[]>("/api/crm/funnels");
    setCrmFunnels(nextFunnels);
    return nextFunnels;
  }

  function openFunnelManager() {
    setFunnelError("");
    setFunnelMessage("");
    setFunnelForm(defaultFunnelForm);
    setStageForm(defaultStageForm);
    setEditingFunnelId(null);
    setEditingStageId(null);
    setFunnelDeleteDialog(null);
    setStageDeleteDialog(null);
    setFunnelManagerOpen(true);
    refreshCrmFunnels().catch((error) =>
      setFunnelError(error instanceof Error ? error.message : "Não foi possível carregar os funis.")
    );
  }

  function closeFunnelManager() {
    if (funnelBusyAction) return;
    setFunnelManagerOpen(false);
    setFunnelError("");
    setFunnelMessage("");
    setFunnelForm(defaultFunnelForm);
    setStageForm(defaultStageForm);
    setEditingFunnelId(null);
    setEditingStageId(null);
    setFunnelDeleteDialog(null);
    setStageDeleteDialog(null);
  }

  function startEditFunnel(funnel: CrmFunnel) {
    setFunnelError("");
    setFunnelMessage("");
    setSelectedCrmFunnelId(funnel.id);
    setEditingFunnelId(funnel.id);
    setFunnelForm({
      name: funnel.name,
      description: funnel.description || ""
    });
  }

  function cancelEditFunnel() {
    setEditingFunnelId(null);
    setFunnelForm(defaultFunnelForm);
    setFunnelError("");
  }

  async function handleSaveFunnel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFunnelError("");
    setFunnelMessage("");

    if (!funnelForm.name.trim()) {
      setFunnelError("Informe o nome do funil.");
      return;
    }

    setFunnelBusyAction(editingFunnelId ? `save-funnel-${editingFunnelId}` : "create-funnel");
    try {
      const savedFunnel = await apiFetch<CrmFunnel>(editingFunnelId ? `/api/crm/funnels/${editingFunnelId}` : "/api/crm/funnels", {
        method: editingFunnelId ? "PATCH" : "POST",
        body: JSON.stringify({
          name: funnelForm.name.trim(),
          description: funnelForm.description.trim() || null
        })
      });
      setSelectedCrmFunnelId(savedFunnel.id);
      setFunnelForm(defaultFunnelForm);
      setEditingFunnelId(null);
      setFunnelMessage(editingFunnelId ? "Funil atualizado." : "Funil criado.");
      await refreshWhatsappData();
    } catch (error) {
      setFunnelError(error instanceof Error ? error.message : "Não foi possível salvar o funil.");
    } finally {
      setFunnelBusyAction("");
    }
  }

  function requestDeleteFunnel(funnel: CrmFunnel) {
    setFunnelError("");
    setFunnelMessage("");
    if (funnel.is_default) {
      setFunnelError("Não é possível excluir o funil padrão.");
      return;
    }
    setFunnelDeleteDialog(funnel);
    setFunnelDeleteMoveToId("");
  }

  async function confirmDeleteFunnel() {
    if (!funnelDeleteDialog) return;

    const moveToFunnelId = funnelDeleteMoveToId ? Number(funnelDeleteMoveToId) : null;
    if (funnelDeleteDialog.card_count > 0 && !moveToFunnelId) {
      setFunnelError("Escolha um funil de destino para mover os cards antes de excluir.");
      return;
    }

    setFunnelError("");
    setFunnelMessage("");
    setFunnelBusyAction(`delete-funnel-${funnelDeleteDialog.id}`);
    try {
      const query = moveToFunnelId ? `?move_to_funnel_id=${moveToFunnelId}` : "";
      await apiFetch<{ deleted: boolean }>(`/api/crm/funnels/${funnelDeleteDialog.id}${query}`, { method: "DELETE" });
      setSelectedCrmFunnelId(moveToFunnelId || defaultCrmFunnel?.id || null);
      setFunnelDeleteDialog(null);
      setFunnelDeleteMoveToId("");
      setFunnelMessage("Funil excluído.");
      await refreshWhatsappData();
    } catch (error) {
      setFunnelError(error instanceof Error ? error.message : "Não foi possível excluir o funil.");
    } finally {
      setFunnelBusyAction("");
    }
  }

  function startEditStage(stage: CrmFunnelStage) {
    setFunnelError("");
    setFunnelMessage("");
    setEditingStageId(stage.id);
    setStageForm({
      label: stage.label,
      color: normalizeStageColor(stage.color),
      is_won: stage.is_won,
      is_lost: stage.is_lost
    });
  }

  function cancelEditStage() {
    setEditingStageId(null);
    setStageForm(defaultStageForm);
    setFunnelError("");
  }

  async function handleSaveStage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedCrmFunnel) return;

    setFunnelError("");
    setFunnelMessage("");
    if (!stageForm.label.trim()) {
      setFunnelError("Informe o nome do estágio.");
      return;
    }

    setFunnelBusyAction(editingStageId ? `save-stage-${editingStageId}` : "create-stage");
    try {
      await apiFetch<CrmFunnelStage>(
        editingStageId
          ? `/api/crm/funnels/${selectedCrmFunnel.id}/stages/${editingStageId}`
          : `/api/crm/funnels/${selectedCrmFunnel.id}/stages`,
        {
          method: editingStageId ? "PATCH" : "POST",
          body: JSON.stringify(crmStagePayload(stageForm))
        }
      );
      setEditingStageId(null);
      setStageForm(defaultStageForm);
      setFunnelMessage(editingStageId ? "Estágio atualizado." : "Estágio criado.");
      await refreshWhatsappData();
    } catch (error) {
      setFunnelError(error instanceof Error ? error.message : "Não foi possível salvar o estágio.");
    } finally {
      setFunnelBusyAction("");
    }
  }

  function requestDeleteStage(stage: CrmFunnelStage) {
    setFunnelError("");
    setFunnelMessage("");
    if (selectedCrmStages.length <= 1) {
      setFunnelError("Todo funil precisa ter pelo menos um estágio.");
      return;
    }
    setStageDeleteDialog(stage);
    setStageDeleteMoveToId("");
  }

  async function confirmDeleteStage() {
    if (!stageDeleteDialog || !selectedCrmFunnel) return;

    const moveToStageId = stageDeleteMoveToId ? Number(stageDeleteMoveToId) : null;
    if (stageDeleteDialog.card_count > 0 && !moveToStageId) {
      setFunnelError("Escolha um estágio de destino para mover os cards antes de excluir.");
      return;
    }

    setFunnelError("");
    setFunnelMessage("");
    setFunnelBusyAction(`delete-stage-${stageDeleteDialog.id}`);
    try {
      const query = moveToStageId ? `?move_to_stage_id=${moveToStageId}` : "";
      await apiFetch<{ deleted: boolean }>(
        `/api/crm/funnels/${selectedCrmFunnel.id}/stages/${stageDeleteDialog.id}${query}`,
        { method: "DELETE" }
      );
      setStageDeleteDialog(null);
      setStageDeleteMoveToId("");
      setStageForm((current) => (editingStageId === stageDeleteDialog.id ? defaultStageForm : current));
      setEditingStageId((current) => (current === stageDeleteDialog.id ? null : current));
      setFunnelMessage("Estágio excluído.");
      await refreshWhatsappData();
    } catch (error) {
      setFunnelError(error instanceof Error ? error.message : "Não foi possível excluir o estágio.");
    } finally {
      setFunnelBusyAction("");
    }
  }

  function handleFunnelStageDragStart(event: DragStartEvent) {
    setActiveFunnelStageDragId(parseFunnelStageDragId(event.active.id));
  }

  function handleFunnelStageDragCancel() {
    setActiveFunnelStageDragId(null);
  }

  async function handleFunnelStageDragEnd(event: DragEndEvent) {
    const activeStageId = parseFunnelStageDragId(event.active.id);
    const overStageId = parseFunnelStageDragId(event.over?.id);
    setActiveFunnelStageDragId(null);

    if (!selectedCrmFunnel || !activeStageId || !overStageId) return;
    const stageIds = moveFunnelStageIds(selectedCrmStages, activeStageId, overStageId);
    if (!stageIds) return;

    setFunnelError("");
    setFunnelMessage("");
    setFunnelBusyAction("reorder-stages");
    try {
      await apiFetch<CrmFunnelStage[]>(`/api/crm/funnels/${selectedCrmFunnel.id}/stages`, {
        method: "PATCH",
        body: JSON.stringify({ stage_ids: stageIds })
      });
      setFunnelMessage("Ordem dos estágios atualizada.");
      await refreshWhatsappData();
    } catch (error) {
      setFunnelError(error instanceof Error ? error.message : "Não foi possível reordenar os estágios.");
    } finally {
      setFunnelBusyAction("");
    }
  }

  function openTagManager() {
    setTagError("");
    setTagMessage("");
    setTagForm(defaultTagForm);
    setEditingTagId(null);
    setTagDeleteDialog(null);
    setTagManagerOpen(true);
    refreshTags().catch((error) =>
      setTagError(error instanceof Error ? error.message : "Não foi possível carregar as tags.")
    );
  }

  function closeTagManager() {
    if (tagBusyAction) return;
    setTagManagerOpen(false);
    setTagForm(defaultTagForm);
    setEditingTagId(null);
    setTagError("");
    setTagMessage("");
  }

  function startEditTag(tag: LeadTag) {
    setTagError("");
    setTagMessage("");
    setEditingTagId(tag.id);
    setTagForm({
      name: tag.name,
      color: normalizeTagColor(tag.color),
      description: tag.description || ""
    });
  }

  function cancelEditTag() {
    setEditingTagId(null);
    setTagForm(defaultTagForm);
    setTagError("");
  }

  async function handleSaveTag(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTagError("");
    setTagMessage("");

    if (!tagForm.name.trim()) {
      setTagError("Informe o nome da tag.");
      return;
    }

    setTagBusyAction(editingTagId ? `save-tag-${editingTagId}` : "create-tag");
    try {
      await apiFetch<LeadTag>(editingTagId ? `/api/tags/${editingTagId}` : "/api/tags", {
        method: editingTagId ? "PATCH" : "POST",
        body: JSON.stringify(tagPayload(tagForm))
      });
      setTagMessage(editingTagId ? "Tag atualizada." : "Tag criada.");
      setTagForm(defaultTagForm);
      setEditingTagId(null);
      await refreshData();
      await refreshWhatsappData();
    } catch (error) {
      setTagError(error instanceof Error ? error.message : "Não foi possível salvar a tag.");
    } finally {
      setTagBusyAction("");
    }
  }

  function requestDeleteTag(tag: LeadTag) {
    setTagError("");
    setTagMessage("");
    setTagDeleteDialog(tag);
  }

  async function confirmDeleteTag() {
    if (!tagDeleteDialog) return;

    const tag = tagDeleteDialog;
    setTagError("");
    setTagMessage("");
    setTagBusyAction(`delete-tag-${tag.id}`);

    try {
      const response = await apiFetch<{ deleted: boolean; affected_leads: number }>(`/api/tags/${tag.id}`, {
        method: "DELETE"
      });
      setSelectedLeadTagIds((current) => current.filter((id) => id !== tag.id));
      setSelectedCrmTagIds((current) => current.filter((id) => id !== tag.id));
      setLeadTagBulkTagIds((current) => current.filter((id) => id !== tag.id));
      setTagDeleteDialog(null);
      setTagForm((current) => (editingTagId === tag.id ? defaultTagForm : current));
      setEditingTagId((current) => (current === tag.id ? null : current));
      setTagMessage(`${response.affected_leads} leads perderam a tag "${tag.name}".`);
      await refreshData();
      await refreshWhatsappData();
    } catch (error) {
      setTagError(error instanceof Error ? error.message : "Não foi possível excluir a tag.");
    } finally {
      setTagBusyAction("");
    }
  }

  async function toggleLeadTag(leadId: number, tagId: number, checked: boolean) {
    setWhatsappError("");
    setWhatsappMessage("");
    setTagBusyAction(`lead-tag-${leadId}-${tagId}`);

    try {
      const updatedLead = checked
        ? await apiFetch<Lead>(`/api/leads/${leadId}/tags`, {
            method: "POST",
            body: JSON.stringify({ tag_ids: [tagId] })
          })
        : await apiFetch<Lead>(`/api/leads/${leadId}/tags/${tagId}`, { method: "DELETE" });
      applyLeadTagSnapshot(updatedLead);
      await refreshTags();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível atualizar as tags do lead.");
    } finally {
      setTagBusyAction("");
    }
  }

  async function handleCreateCrmInlineTag(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedCrmLead) return;

    setWhatsappError("");
    setWhatsappMessage("");
    if (!crmInlineTagForm.name.trim()) {
      setWhatsappError("Informe o nome da tag.");
      return;
    }

    setTagBusyAction("crm-create-tag");
    try {
      const createdTag = await apiFetch<LeadTag>("/api/tags", {
        method: "POST",
        body: JSON.stringify(tagPayload(crmInlineTagForm))
      });
      const updatedLead = await apiFetch<Lead>(`/api/leads/${selectedCrmLead.lead_id}/tags`, {
        method: "POST",
        body: JSON.stringify({ tag_ids: [createdTag.id] })
      });
      applyLeadTagSnapshot(updatedLead);
      setCrmInlineTagForm(defaultTagForm);
      setWhatsappMessage("Tag criada e aplicada ao lead.");
      await refreshTags();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível criar a tag.");
    } finally {
      setTagBusyAction("");
    }
  }

  function openLeadTagBulkDialog(action: LeadTagBulkAction) {
    if (selectedIds.length === 0) return;

    setActionError("");
    setActionMessage("");
    setLeadTagBulkError("");
    setLeadTagBulkTagIds([]);
    setLeadTagBulkDialog({ action, ids: [...selectedIds] });
  }

  function closeLeadTagBulkDialog() {
    if (leadTagBulkSaving) return;
    setLeadTagBulkDialog(null);
    setLeadTagBulkTagIds([]);
    setLeadTagBulkError("");
  }

  async function confirmLeadTagBulk() {
    if (!leadTagBulkDialog) return;

    setLeadTagBulkError("");
    if (leadTagBulkTagIds.length === 0) {
      setLeadTagBulkError("Selecione pelo menos uma tag.");
      return;
    }

    setLeadTagBulkSaving(true);
    try {
      const response = await apiFetch<{
        action: LeadTagBulkAction;
        matched_leads: number;
        matched_tags: number;
        changed_associations: number;
      }>("/api/leads/tags/bulk", {
        method: "POST",
        body: JSON.stringify({
          lead_ids: leadTagBulkDialog.ids,
          tag_ids: leadTagBulkTagIds,
          action: leadTagBulkDialog.action
        })
      });
      const actionLabel = leadTagBulkDialog.action === "add" ? "aplicadas" : "removidas";
      setActionMessage(
        `${response.changed_associations} associações ${actionLabel} em ${response.matched_leads} leads.`
      );
      setSelectedIds([]);
      setLeadTagBulkDialog(null);
      setLeadTagBulkTagIds([]);
      await refreshData();
      await refreshWhatsappData();
    } catch (error) {
      setLeadTagBulkError(error instanceof Error ? error.message : "Não foi possível atualizar tags em lote.");
    } finally {
      setLeadTagBulkSaving(false);
    }
  }

  async function handleSaveWhatsappAiSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction("save-ai-settings");

    try {
      const updatedSettings = await apiFetch<WhatsAppAiSettings>("/api/whatsapp/ai-settings", {
        method: "PUT",
        body: JSON.stringify({
          system_prompt: whatsappAiForm.system_prompt,
          services_description: whatsappAiForm.services_description,
          enabled: whatsappAiForm.enabled,
          auto_apply_tags_enabled: whatsappAiForm.auto_apply_tags_enabled
        })
      });
      setWhatsappAiSettings(updatedSettings);
      setWhatsappAiForm({
        system_prompt: updatedSettings.system_prompt,
        services_description: updatedSettings.services_description || "",
        enabled: updatedSettings.enabled,
        auto_apply_tags_enabled: updatedSettings.auto_apply_tags_enabled
      });
      setWhatsappMessage("Configuração de IA salva.");
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível salvar a configuração de IA.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  async function handleCreateWhatsappPortfolioItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWhatsappError("");
    setWhatsappMessage("");

    if (!whatsappPortfolioForm.description.trim() || !whatsappPortfolioForm.url.trim()) {
      setWhatsappError("Informe descrição e link do item de portfólio.");
      return;
    }

    setWhatsappBusyAction("create-portfolio");
    try {
      await apiFetch<WhatsAppPortfolioItem>("/api/whatsapp/portfolio", {
        method: "POST",
        body: JSON.stringify({
          description: whatsappPortfolioForm.description.trim(),
          url: whatsappPortfolioForm.url.trim()
        })
      });
      setWhatsappPortfolioForm(defaultWhatsappPortfolioForm);
      setWhatsappMessage("Item de portfólio adicionado.");
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível adicionar o item de portfólio.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  async function deleteWhatsappPortfolioItem(itemId: number) {
    setWhatsappError("");
    setWhatsappMessage("");
    setWhatsappBusyAction(`delete-portfolio-${itemId}`);

    try {
      await apiFetch<{ status: string }>(`/api/whatsapp/portfolio/${itemId}`, { method: "DELETE" });
      setWhatsappMessage("Item de portfólio removido.");
      await refreshWhatsappData();
    } catch (error) {
      setWhatsappError(error instanceof Error ? error.message : "Não foi possível remover o item de portfólio.");
    } finally {
      setWhatsappBusyAction("");
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");

    if (!niche.trim() || !location.trim()) {
      setFormError("Preencha nicho e cidade/estado.");
      return;
    }

    if (!maxResults && (!quantity || Number(quantity) <= 0)) {
      setFormError("Informe uma quantidade válida ou marque máximo possível.");
      return;
    }

    setSubmitting(true);
    try {
      await apiFetch<SearchRun>("/api/searches", {
        method: "POST",
        body: JSON.stringify({
          niche: niche.trim(),
          location: location.trim(),
          quantity: maxResults ? null : Number(quantity),
          max_results: maxResults,
          skip_without_website: skipWithoutWebsite,
          validate_whatsapp: validateWhatsapp,
          enrich_site_insights: enrichSiteInsights
        })
      });
      setRunPage(1);
      await refreshData();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Não foi possível iniciar a busca.");
    } finally {
      setSubmitting(false);
    }
  }

  function toggleLead(leadId: number) {
    setSelectedIds((current) =>
      current.includes(leadId) ? current.filter((id) => id !== leadId) : [...current, leadId]
    );
  }

  function toggleAllVisible() {
    if (allVisibleSelected) {
      setSelectedIds((current) => current.filter((id) => !filteredLeadIds.includes(id)));
      return;
    }

    setSelectedIds((current) => Array.from(new Set([...current, ...filteredLeadIds])));
  }

  async function handleEnrichExistingLeads() {
    setActionError("");
    setActionMessage("");
    setLeadEnrichmentBusy(true);

    try {
      const request: RequestInit = { method: "POST" };
      if (selectedIds.length > 0) {
        const payload: LeadSiteInsightsEnrichmentRequest = { lead_ids: selectedIds };
        request.body = JSON.stringify(payload);
      }
      const response = await apiFetch<LeadSiteInsightsEnrichmentResponse>("/api/leads/enrich-site-insights", {
        ...request
      });
      const hasSelection = selectedIds.length > 0;
      setActionMessage(
        response.queued_count > 0
          ? hasSelection
            ? `Enriquecimento iniciado: ${response.queued_count} de ${response.eligible_count} leads selecionados elegíveis entraram na fila.`
            : `Enriquecimento iniciado: ${response.queued_count} de ${response.eligible_count} leads elegíveis entraram na fila.`
          : hasSelection
            ? "Nenhum lead selecionado elegível para enriquecer agora."
            : "Nenhum lead elegível para enriquecer agora."
      );
      await refreshData();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Não foi possível iniciar o enriquecimento.");
    } finally {
      setLeadEnrichmentBusy(false);
    }
  }

  function openLeadWhatsappValidationDialog() {
    setActionError("");
    setActionMessage("");
    setLeadWhatsappValidationPreview(null);
    setLeadWhatsappValidationPreviewError("");
    setLeadWhatsappValidationRevalidate(false);
    setLeadWhatsappValidationScope(selectedIds.length > 0 ? "selected" : "filters");
    setLeadWhatsappValidationDialogOpen(true);
  }

  function closeLeadWhatsappValidationDialog() {
    if (leadWhatsappValidationSubmitting) return;
    setLeadWhatsappValidationDialogOpen(false);
    setLeadWhatsappValidationPreviewError("");
  }

  async function confirmLeadWhatsappValidation() {
    if (!leadWhatsappValidationPreview || leadWhatsappValidationPreview.eligible_now <= 0) return;

    setActionError("");
    setActionMessage("");
    setLeadWhatsappValidationPreviewError("");
    setLeadWhatsappValidationSubmitting(true);

    try {
      const response = await apiFetch<LeadWhatsAppValidationResponse>("/api/leads/validate-whatsapp", {
        method: "POST",
        body: JSON.stringify(leadWhatsappValidationPayload())
      });
      setLeadWhatsappValidationDialogOpen(false);
      setActionMessage(response.message);
      await refreshLeadWhatsappValidationProgress({ showFinalSummary: true });
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409 && typeof error.detail === "object" && error.detail && "job_id" in error.detail) {
        setLeadWhatsappValidationDialogOpen(false);
        setActionMessage(error.message);
        await refreshLeadWhatsappValidationProgress();
        return;
      }

      setLeadWhatsappValidationPreviewError(
        error instanceof Error ? error.message : "Não foi possível iniciar a validação."
      );
    } finally {
      setLeadWhatsappValidationSubmitting(false);
    }
  }

  async function cancelLeadWhatsappValidation() {
    setActionError("");
    setActionMessage("");
    setLeadWhatsappValidationCancelling(true);

    try {
      const progress = await apiFetch<LeadWhatsAppValidationProgress>("/api/leads/validate-whatsapp/cancel", {
        method: "POST"
      });
      applyLeadWhatsappValidationProgress(progress);
      setActionMessage("Cancelamento solicitado. O lead em validação termina antes de parar o lote.");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Não foi possível cancelar a validação.");
      await refreshLeadWhatsappValidationProgress().catch(() => undefined);
    } finally {
      setLeadWhatsappValidationCancelling(false);
    }
  }

  function openManualLeadModal() {
    setActionError("");
    setManualLeadForm({
      ...defaultManualLeadForm,
      niche: selectedLeadNiches[0] || niche,
      location: selectedLeadLocations[0] || location
    });
    setManualLeadOpen(true);
  }

  function closeManualLeadModal() {
    setActionError("");
    setManualLeadOpen(false);
    setManualLeadForm(defaultManualLeadForm);
  }

  async function handleCreateManualLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (
      !manualLeadForm.niche.trim() ||
      !manualLeadForm.location.trim() ||
      !manualLeadForm.name.trim()
    ) {
      setActionError("Preencha nome, nicho e localidade.");
      return;
    }

    setActionError("");
    setSavingManualLead(true);
    try {
      const createdLead = await apiFetch<Lead>("/api/leads", {
        method: "POST",
        body: JSON.stringify(manualLeadForm)
      });
      setManualLeadOpen(false);
      setManualLeadForm(defaultManualLeadForm);
      setLeadNameQuery(createdLead.name);
      setSelectedLeadNiches([]);
      setSelectedLeadLocations([]);
      setLeadPage(1);
      await refreshData();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Não foi possível cadastrar o lead.");
    } finally {
      setSavingManualLead(false);
    }
  }

  async function handlePauseSearch(runId: number) {
    setRunError("");
    setRunActionLoading(runId);

    try {
      await apiFetch<SearchRun>(`/api/searches/${runId}/pause`, { method: "POST" });
      await refreshData();
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Não foi possível pausar a busca.");
    } finally {
      setRunActionLoading(null);
    }
  }

  async function handleResumeSearch(runId: number) {
    setRunError("");
    setRunActionLoading(runId);

    try {
      await apiFetch<SearchRun>(`/api/searches/${runId}/resume`, { method: "POST" });
      await refreshData();
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Não foi possível retomar a busca.");
    } finally {
      setRunActionLoading(null);
    }
  }

  async function handleDeleteLead(lead: Lead) {
    setActionError("");
    setDeleteDialog({ kind: "single", lead });
  }

  async function handleBulkDelete() {
    if (selectedIds.length === 0) return;

    setActionError("");
    setDeleteDialog({ kind: "bulk", ids: [...selectedIds] });
  }

  async function confirmDelete() {
    if (!deleteDialog) return;

    setActionError("");
    setDeleting(true);

    try {
      if (deleteDialog.kind === "single") {
        await apiFetch<{ status: string }>(`/api/leads/${deleteDialog.lead.id}`, { method: "DELETE" });
        setSelectedIds((current) => current.filter((id) => id !== deleteDialog.lead.id));
      } else {
        await apiFetch<{ deleted: number }>("/api/leads/bulk-delete", {
          method: "POST",
          body: JSON.stringify({ ids: deleteDialog.ids })
        });
        setSelectedIds([]);
      }

      setDeleteDialog(null);
      await refreshData();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Não foi possível excluir.");
    } finally {
      setDeleting(false);
    }
  }

  async function handleSaveLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingLead) return;

    setActionError("");
    setSavingEdit(true);
    try {
      await apiFetch<Lead>(`/api/leads/${editingLead.id}`, {
        method: "PATCH",
        body: JSON.stringify(leadPayload(editingLead))
      });
      setEditingLead(null);
      await refreshData();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Não foi possível salvar o lead.");
    } finally {
      setSavingEdit(false);
    }
  }

  if (authLoading) {
    return (
      <main className="center-screen">
        <Loader2 className="spin" size={28} />
      </main>
    );
  }

  if (!user) {
    return (
      <main className="login-shell">
        <section className="login-panel">
          <div className="brand-lockup login-brand">
            <img className="brand-logo login-logo" src="/gmapscrap-logo.png" alt="GmapScrap" />
            <h1>Entrar no sistema</h1>
          </div>

          <form className="login-form" onSubmit={handleLogin}>
            <label>
              Usuário
              <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
            </label>
            <label>
              Senha
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
              />
            </label>
            {loginError ? <p className="error-text">{loginError}</p> : null}
            <button className="primary-button" type="submit">
              <ShieldCheck size={18} />
              Acessar
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup compact sidebar-brand">
          <img className="brand-logo sidebar-logo" src="/gmapscrap-logo.png" alt="GmapScrap Leads Web" />
        </div>

        <nav className="nav-list">
          <button
            className={`nav-item ${activeView === "search" ? "active" : ""}`}
            onClick={() => switchView("search")}
            type="button"
          >
            <Search size={18} />
            Busca
          </button>
          <button
            className={`nav-item ${activeView === "leads" ? "active" : ""}`}
            onClick={() => switchView("leads")}
            type="button"
          >
            <Building2 size={18} />
            Leads
          </button>
          <button
            className={`nav-item ${activeView === "dashboard" ? "active" : ""}`}
            onClick={() => switchView("dashboard")}
            type="button"
          >
            <BarChart3 size={18} />
            Dashboard
          </button>
          <button
            className={`nav-item ${activeView === "whatsappCrm" ? "active" : ""}`}
            onClick={() => switchView("whatsappCrm")}
            type="button"
          >
            <Users size={18} />
            CRM
          </button>
          <button
            className={`nav-item ${activeView === "lists" ? "active" : ""}`}
            onClick={() => switchView("lists")}
            type="button"
          >
            <ListFilter size={18} />
            Listas
          </button>

          <div className="nav-section-label">WhatsApp</div>
          <button
            className={`nav-item ${activeView === "whatsapp" ? "active" : ""}`}
            onClick={() => switchView("whatsapp")}
            type="button"
          >
            <BarChart3 size={18} />
            Resumo
          </button>
          <button
            className={`nav-item ${activeView === "whatsappInstances" ? "active" : ""}`}
            onClick={() => switchView("whatsappInstances")}
            type="button"
          >
            <MessageCircle size={18} />
            Instâncias
          </button>
          <button
            className={`nav-item ${activeView === "whatsappTemplates" ? "active" : ""}`}
            onClick={() => switchView("whatsappTemplates")}
            type="button"
          >
            <FileText size={18} />
            Templates
          </button>
          <button
            className={`nav-item ${activeView === "whatsappCampaigns" ? "active" : ""}`}
            onClick={() => switchView("whatsappCampaigns")}
            type="button"
          >
            <Megaphone size={18} />
            Campanhas
          </button>
          <button
            className={`nav-item ${activeView === "whatsappAi" ? "active" : ""}`}
            onClick={() => switchView("whatsappAi")}
            type="button"
          >
            <Sparkles size={18} />
            IA
          </button>

          <div className="nav-section-label">E-mail</div>
          <button
            className={`nav-item ${activeView === "templates" ? "active" : ""}`}
            onClick={() => switchView("templates")}
            type="button"
          >
            <FileText size={18} />
            Templates
          </button>
          <button
            className={`nav-item ${activeView === "campaigns" ? "active" : ""}`}
            onClick={() => switchView("campaigns")}
            type="button"
          >
            <Megaphone size={18} />
            Campanhas
          </button>
          <button
            className={`nav-item ${activeView === "history" ? "active" : ""}`}
            onClick={() => switchView("history")}
            type="button"
          >
            <Mail size={18} />
            Histórico
          </button>
          <button
            className={`nav-item ${activeView === "settings" ? "active" : ""}`}
            onClick={() => switchView("settings")}
            type="button"
          >
            <Settings size={18} />
            Configurações
          </button>
        </nav>

        <button className="ghost-button logout" onClick={handleLogout}>
          <LogOut size={18} />
          Sair
        </button>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Painel</p>
            <h1>
              {activeView === "search"
                ? "Coleta de leads com site e e-mail"
                : activeView === "leads"
                  ? "Base de leads"
                  : activeView === "settings"
                    ? "Configurações"
                      : activeView === "dashboard"
                        ? "Dashboard"
                        : activeView === "whatsapp"
                          ? "WhatsApp"
                          : activeView === "whatsappInstances"
                            ? "Instâncias WhatsApp"
                            : activeView === "whatsappTemplates"
                              ? "Templates WhatsApp"
                              : activeView === "whatsappCampaigns"
                                ? "Campanhas WhatsApp"
                                : activeView === "whatsappCrm"
                                  ? "CRM"
                                  : activeView === "whatsappAi"
                                    ? "IA WhatsApp"
                                    : activeView === "templates"
                                      ? "Templates de e-mail"
                                      : activeView === "lists"
                                        ? "Listas de leads"
                                        : activeView === "campaigns"
                                          ? "Campanhas de e-mail"
                                          : "Histórico de envios"}
            </h1>
          </div>
          {activeView === "search" || activeView === "leads" ? (
            <a className="secondary-button" href={`${API_BASE}/api/leads/export.csv`} target="_blank" rel="noreferrer">
              <ArrowDownToLine size={18} />
              CSV
            </a>
          ) : whatsappViews.includes(activeView) ? (
            <button className="secondary-button" disabled={Boolean(whatsappBusyAction)} onClick={handleRefreshWhatsappData} type="button">
              {whatsappBusyAction === "refresh-whatsapp" ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
              Atualizar
            </button>
          ) : (
            <button className="secondary-button" disabled={emailBusy} onClick={refreshEmailData} type="button">
              <Clock3 size={18} />
              Atualizar
            </button>
          )}
        </header>

        {whatsappViews.includes(activeView) && disconnectedWhatsappInstances.length > 0 ? (
          <div className="notice warning">
            {disconnectedWhatsappInstances.length === 1
              ? `Instância "${disconnectedWhatsappInstances[0].name}" desconectada da Evolution. A IA não responde e campanhas que dependem dela ficam pausadas automaticamente.`
              : `${disconnectedWhatsappInstances.length} instâncias desconectadas da Evolution (${disconnectedWhatsappInstances
                  .map((instance) => instance.name)
                  .join(", ")}). A IA não responde e campanhas que dependem delas ficam pausadas automaticamente.`}{" "}
            {activeView !== "whatsappInstances" ? (
              <button type="button" className="link-button" onClick={() => switchView("whatsappInstances")}>
                Reconectar
              </button>
            ) : null}
          </div>
        ) : null}

        {activeView === "search" || activeView === "leads" ? (
          <section className="metrics-grid">
            <article className="metric-card">
              <Building2 size={20} />
              <span>Leads</span>
              <strong>{stats.total_leads}</strong>
            </article>
            <article className="metric-card">
              <Mail size={20} />
              <span>Com e-mail</span>
              <strong>{stats.total_with_email}</strong>
            </article>
            <article className="metric-card">
              <Clock3 size={20} />
              <span>Rodando</span>
              <strong>{stats.running_jobs}</strong>
            </article>
            <article className="metric-card">
              <CheckCircle2 size={20} />
              <span>Concluídas</span>
              <strong>{stats.completed_jobs}</strong>
            </article>
          </section>
        ) : null}

        {activeView === "search" ? (
          <>
            <section className="content-grid">
              <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Nova busca</p>
                  <h2>Google Maps headless</h2>
                </div>
                {activeRun ? (
                  <span className="live-pill">
                    <Loader2 className="spin" size={16} />
                    Em execução
                  </span>
                ) : null}
              </div>

              <form className="search-form" onSubmit={handleSearch}>
                <label>
                  Nicho
                  <input
                    placeholder="Ex.: pressure washing"
                    value={niche}
                    onChange={(event) => setNiche(event.target.value)}
                  />
                </label>
                <label>
                  Cidade, estado ou país
                  <input
                    placeholder="Ex.: Anchorage, AK"
                    value={location}
                    onChange={(event) => setLocation(event.target.value)}
                  />
                </label>
                <div className="quantity-row">
                  <label>
                    Quantidade
                    <input
                      disabled={maxResults}
                      min={1}
                      max={500}
                      type="number"
                      value={maxResults ? "" : quantity}
                      onChange={(event) => setQuantity(event.target.value)}
                      placeholder={maxResults ? "Máximo" : "10"}
                    />
                  </label>
                  <label className="checkbox-label">
                    <input
                      checked={maxResults}
                      onChange={(event) => setMaxResults(event.target.checked)}
                      type="checkbox"
                    />
                    Máximo possível
                  </label>
                </div>
                <div className="search-options">
                  <label className="checkbox-label">
                    <input
                      checked={skipWithoutWebsite}
                      onChange={(event) => setSkipWithoutWebsite(event.target.checked)}
                      type="checkbox"
                    />
                    Ignorar sem site
                  </label>
                  <label className="checkbox-label">
                    <input
                      checked={validateWhatsapp}
                      onChange={(event) => setValidateWhatsapp(event.target.checked)}
                      type="checkbox"
                    />
                    Validar WhatsApp
                  </label>
                  <label className="checkbox-label">
                    <input
                      checked={enrichSiteInsights}
                      onChange={(event) => setEnrichSiteInsights(event.target.checked)}
                      type="checkbox"
                    />
                    Gerar insights do site
                  </label>
                </div>
                {formError ? <p className="error-text">{formError}</p> : null}
                <button className="primary-button" disabled={submitting} type="submit">
                  {submitting ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
                  Iniciar busca
                </button>
              </form>
            </section>

              <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Execuções</p>
                  <h2>Status</h2>
                </div>
                <Sparkles size={20} />
              </div>

              <div className="jobs-list">
                {runError ? <p className="error-text">{runError}</p> : null}
                {searches.length === 0 ? <p className="empty-state">Nenhuma busca iniciada.</p> : null}
                {paginatedSearches.map((run) => (
                  <article className="job-row" key={run.id}>
                    <div>
                      <strong>{run.niche}</strong>
                      <span>
                        {run.location} · {formatDate(run.created_at)}
                      </span>
                      <p title={run.error || run.message}>{searchRunMessage(run)}</p>
                    </div>
                    <div className="job-meta">
                      <div className="job-actions">
                        <span className={`status-pill ${run.status}`}>{statusLabel(run.status)}</span>
                        {run.status === "running" || run.status === "queued" ? (
                          <button
                            className="icon-button"
                            disabled={runActionLoading === run.id}
                            onClick={() => handlePauseSearch(run.id)}
                            title="Pausar busca"
                            type="button"
                          >
                            {runActionLoading === run.id ? <Loader2 className="spin" size={16} /> : <Pause size={16} />}
                          </button>
                        ) : null}
                        {run.status === "paused" ? (
                          <button
                            className="icon-button"
                            disabled={runActionLoading === run.id}
                            onClick={() => handleResumeSearch(run.id)}
                            title="Retomar busca"
                            type="button"
                          >
                            {runActionLoading === run.id ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                          </button>
                        ) : null}
                      </div>
                      <span>
                        {run.saved_count} salvos · {run.skipped_count} pulados
                      </span>
                    </div>
                  </article>
                ))}
              </div>
              {searches.length > SEARCH_RUNS_PAGE_SIZE ? (
                <div className="pagination-row compact-pagination">
                  <span className="helper-text">
                    Mostrando {runPageStart}-{runPageEnd} de {searches.length}
                  </span>
                  <div className="row-actions">
                    <button
                      className="secondary-button compact-button"
                      disabled={currentRunPage <= 1}
                      onClick={() => setRunPage((page) => Math.max(1, page - 1))}
                      type="button"
                    >
                      <ChevronLeft size={16} />
                      Anterior
                    </button>
                    <span className="muted-count">
                      Página {currentRunPage} de {runPageCount}
                    </span>
                    <button
                      className="secondary-button compact-button"
                      disabled={currentRunPage >= runPageCount}
                      onClick={() => setRunPage((page) => Math.min(runPageCount, page + 1))}
                      type="button"
                    >
                      Próxima
                      <ChevronRight size={16} />
                    </button>
                  </div>
                </div>
              ) : null}
            </section>
            </section>

            <section className="panel table-panel live-leads-panel">
              <div className="panel-heading leads-heading">
                <div>
                  <p className="eyebrow">Resultado ao vivo</p>
                  <h2>Leads encontrados</h2>
                </div>
                <div className="lead-actions">
                  {activeRun ? (
                    <span className="live-pill">
                      <Loader2 className="spin" size={16} />
                      Atualizando
                    </span>
                  ) : null}
                  <span className="muted-count">{recentLeads.length} recentes</span>
                  <button className="secondary-button" onClick={() => switchView("leads")} type="button">
                    <Building2 size={16} />
                    Ver base
                  </button>
                </div>
              </div>

              <div className="table-wrap compact-wrap">
                <table className="compact-table">
                  <thead>
                    <tr>
                      <th>Nome</th>
                      <th>Nicho</th>
                      <th>Localidade</th>
                      <th>Site</th>
                      <th>E-mail</th>
                      <th>Telefone</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentLeads.length === 0 ? (
                      <tr>
                        <td className="empty-cell" colSpan={6}>
                          <SkipForward size={18} />
                          Os leads salvos vão aparecer aqui durante a busca.
                        </td>
                      </tr>
                    ) : null}
                    {recentLeads.map((lead) => (
                      <tr key={lead.id}>
                        <td>
                          <strong>{lead.name}</strong>
                        </td>
                        <td>{lead.niche}</td>
                        <td>{lead.location}</td>
                        <td>
                          <WebsiteCell website={lead.website} />
                        </td>
                        <td>{lead.email}</td>
                        <td>
                          <PhoneCell lead={lead} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : activeView === "leads" ? (
          <section className="panel table-panel">
            <div className="panel-heading leads-heading">
              <div>
                <p className="eyebrow">Banco de dados</p>
                <h2>Leads salvos</h2>
              </div>
              <div className="lead-actions">
                <button
                  className="secondary-button compact-button"
                  disabled={leadEnrichmentBusy}
                  onClick={handleEnrichExistingLeads}
                  type="button"
                >
                  {leadEnrichmentBusy ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
                  Enriquecer leads existentes
                </button>
                <button
                  className="secondary-button compact-button"
                  disabled={leadWhatsappValidationRunning || leadWhatsappValidationSubmitting}
                  onClick={openLeadWhatsappValidationDialog}
                  type="button"
                >
                  {leadWhatsappValidationRunning || leadWhatsappValidationSubmitting ? (
                    <Loader2 className="spin" size={16} />
                  ) : (
                    <ShieldCheck size={16} />
                  )}
                  {leadWhatsappValidationRunning
                    ? "Validando WhatsApp"
                    : selectedIds.length > 0
                      ? `Validar WhatsApp (${selectedIds.length})`
                      : "Validar WhatsApp"}
                </button>
                <button className="secondary-button compact-button" onClick={openTagManager} type="button">
                  <Tags size={16} />
                  Gerenciar tags
                </button>
                <button
                  className="secondary-button compact-button"
                  disabled={selectedIds.length === 0 || tags.length === 0}
                  onClick={() => openLeadTagBulkDialog("add")}
                  type="button"
                >
                  <Tags size={16} />
                  Aplicar tags{selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
                </button>
                <button
                  className="secondary-button compact-button"
                  disabled={selectedIds.length === 0 || tags.length === 0}
                  onClick={() => openLeadTagBulkDialog("remove")}
                  type="button"
                >
                  <X size={16} />
                  Remover tags
                </button>
                <button className="primary-button compact-button" onClick={openManualLeadModal} type="button">
                  <Plus size={16} />
                  Adicionar lead
                </button>
                <span className="muted-count">{filteredLeads.length} visíveis</span>
                {hasMoreLeadsThanLoaded ? (
                  <span className="muted-count">
                    {leadRowsLoadedCount} de {leadTotalCount} carregados
                  </span>
                ) : null}
                <button
                  className="danger-button"
                  disabled={selectedIds.length === 0}
                  onClick={handleBulkDelete}
                  type="button"
                >
                  <Trash2 size={16} />
                  Excluir selecionados
                </button>
              </div>
            </div>

            {actionError ? <div className="notice danger">{actionError}</div> : null}
            {actionMessage ? <div className="notice success">{actionMessage}</div> : null}
            {leadWhatsappValidationRunning ? (
              <div className="notice warning" style={{ display: "grid", gap: 10, position: "sticky", top: 16, zIndex: 1 }}>
                <div className="panel-heading" style={{ gap: 12 }}>
                  <div>
                    <p className="eyebrow">Validação WhatsApp</p>
                    <strong>
                      {leadWhatsappValidationProgress.processed}/{leadWhatsappValidationProgress.total} leads processados
                    </strong>
                  </div>
                  <button
                    className="danger-button compact-button"
                    disabled={leadWhatsappValidationCancelling}
                    onClick={cancelLeadWhatsappValidation}
                    type="button"
                  >
                    {leadWhatsappValidationCancelling ? <Loader2 className="spin" size={16} /> : <X size={16} />}
                    Cancelar validação
                  </button>
                </div>
                <div className="progress-track" aria-label="Progresso da validação de WhatsApp">
                  <span style={{ width: `${leadWhatsappValidationProgressPercent}%` }} />
                </div>
                <div className="lead-actions" style={{ justifyContent: "flex-start" }}>
                  <span className="muted-count">Válidos {leadWhatsappValidationProgress.valid}</span>
                  <span className="muted-count">Inválidos {leadWhatsappValidationProgress.invalid}</span>
                  <span className="muted-count">Indeterminados {leadWhatsappValidationProgress.unknown}</span>
                  <span className="muted-count">Pulados {leadWhatsappValidationProgress.skipped}</span>
                </div>
              </div>
            ) : null}
            {hasMoreLeadsThanLoaded ? (
              <div className="notice warning">
                Há {leadTotalCount} leads no banco para os filtros do servidor, mas esta tela carregou {leadRowsLoadedCount}.
                No modal, a opção "Todos os leads que correspondem aos filtros atuais" alcança os registros além do limite de {leadResultLimit}.
              </div>
            ) : null}

            <div className="lead-search-row">
              <label>
                Buscar por empresa
                <div className="input-with-icon">
                  <Search size={17} />
                  <input
                    placeholder="Digite o nome da empresa"
                    value={leadNameQuery}
                    onChange={(event) => setLeadNameQuery(event.target.value)}
                  />
                </div>
              </label>
            </div>

            <div className="filters-row lead-primary-filters-row">
              <TagDropdown
                allLabel="Todos os nichos"
                label="Filtrar por nicho"
                options={leadNicheOptions}
                placeholder="Adicionar nicho"
                selected={selectedLeadNiches}
                onChange={setSelectedLeadNiches}
              />
              <TagDropdown
                allLabel="Todas as localidades"
                label="Filtrar por localidade"
                options={leadLocationOptions}
                placeholder="Adicionar localidade"
                selected={selectedLeadLocations}
                onChange={setSelectedLeadLocations}
              />
              <label className="tag-filter">
                Filtrar por WhatsApp
                <select
                  value={leadWhatsappStatusFilter}
                  onChange={(event) => setLeadWhatsappStatusFilter(event.target.value as LeadWhatsappStatusFilter)}
                >
                  {LEAD_WHATSAPP_STATUS_OPTIONS.map((option) => (
                    <option key={option.value || "all"} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <div className="tag-list">
                  <span className={leadWhatsappStatusFilter ? "filter-tag" : "filter-tag all-tag"}>
                    {leadWhatsappStatusFilterLabel}
                    {leadWhatsappStatusFilter ? (
                      <button
                        aria-label="Remover filtro de WhatsApp"
                        onClick={() => setLeadWhatsappStatusFilter("")}
                        type="button"
                      >
                        <X size={12} />
                      </button>
                    ) : null}
                  </span>
                </div>
              </label>
              <LeadTagFilter
                allLabel="Todas as tags"
                label="Filtrar por tag"
                mode={leadTagFilterMode}
                onChange={setSelectedLeadTagIds}
                onModeChange={setLeadTagFilterMode}
                placeholder="Adicionar tag"
                selectedIds={selectedLeadTagIds}
                tags={tags}
              />
              <button
                className="secondary-button"
                onClick={() => {
                  setSelectedLeadNiches([]);
                  setSelectedLeadLocations([]);
                  setLeadNameQuery("");
                  setSelectedLeadTagIds([]);
                  setLeadTagFilterMode("any");
                  setLeadWhatsappStatusFilter("");
                  setSelectedLeadEmailCampaignId("");
                  setLeadEmailOpenedOnly(false);
                  setLeadEmailClickedOnly(false);
                  setSelectedLeadWhatsappCampaignId("");
                  setLeadWhatsappRepliedOnly(false);
                  setLeadPage(1);
                }}
                type="button"
              >
                Limpar filtros
              </button>
            </div>

            <div className="filters-row lead-campaign-filters-row">
              <label>
                Campanha de e-mail
                <select
                  value={selectedLeadEmailCampaignId}
                  onChange={(event) => setSelectedLeadEmailCampaignId(event.target.value)}
                >
                  <option value="">Todas as campanhas de e-mail</option>
                  {campaigns.map((campaign) => (
                    <option key={campaign.id} value={campaign.id}>
                      {campaign.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="checkbox-label">
                <input
                  checked={leadEmailOpenedOnly}
                  onChange={(event) => setLeadEmailOpenedOnly(event.target.checked)}
                  type="checkbox"
                />
                Abriu e-mail
              </label>
              <label className="checkbox-label">
                <input
                  checked={leadEmailClickedOnly}
                  onChange={(event) => setLeadEmailClickedOnly(event.target.checked)}
                  type="checkbox"
                />
                Clicou e-mail
              </label>
              <label>
                Campanha WhatsApp
                <select
                  value={selectedLeadWhatsappCampaignId}
                  onChange={(event) => setSelectedLeadWhatsappCampaignId(event.target.value)}
                >
                  <option value="">Todas as campanhas WhatsApp</option>
                  {whatsappCampaigns.map((campaign) => (
                    <option key={campaign.id} value={campaign.id}>
                      {campaign.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="checkbox-label">
                <input
                  checked={leadWhatsappRepliedOnly}
                  onChange={(event) => setLeadWhatsappRepliedOnly(event.target.checked)}
                  type="checkbox"
                />
                Respondeu WhatsApp
              </label>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="select-col">
                      <input
                        aria-label="Selecionar todos os leads"
                        checked={allVisibleSelected}
                        onChange={toggleAllVisible}
                        type="checkbox"
                      />
                    </th>
                    <th>Ações</th>
                    <th>Nome</th>
                    <th>Nicho</th>
                    <th>Localidade</th>
                    <th>Endereço</th>
                    <th>Telefone</th>
                    <th>WhatsApp</th>
                    <th>Tags</th>
                    <th>Site</th>
                    <th>Insights site</th>
                    <th>E-mail</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLeads.length === 0 ? (
                    <tr>
                      <td className="empty-cell" colSpan={12}>
                        <SkipForward size={18} />
                        Nenhum lead encontrado para os filtros.
                      </td>
                    </tr>
                  ) : null}
                  {paginatedLeads.map((lead) => {
                    const whatsappStatus = leadWhatsAppStatus(lead);
                    return (
                      <tr key={lead.id}>
                        <td className="select-col">
                          <input
                            aria-label={`Selecionar ${lead.name}`}
                            checked={selectedIdSet.has(lead.id)}
                            onChange={() => toggleLead(lead.id)}
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <div className="row-actions">
                            <button
                              className="icon-button"
                              onClick={() => {
                                setActionError("");
                                setEditingLead({ ...lead });
                              }}
                              title="Editar lead"
                              type="button"
                            >
                              <Edit3 size={16} />
                            </button>
                            <button
                              className="icon-button danger"
                              onClick={() => handleDeleteLead(lead)}
                              title="Excluir lead"
                              type="button"
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                        </td>
                        <td>
                          <strong>{lead.name}</strong>
                        </td>
                        <td>{lead.niche}</td>
                        <td>{lead.location}</td>
                        <td>{lead.address}</td>
                        <td>
                          <PhoneCell lead={lead} />
                        </td>
                        <td>
                          <span className={whatsappStatus.className} title={whatsappStatus.title}>
                            {whatsappStatus.label}
                          </span>
                        </td>
                        <td>
                          <TagPills tags={lead.tags} />
                        </td>
                        <td>
                          <WebsiteCell website={lead.website} />
                        </td>
                        <td>
                          {lead.site_insights ? (
                            <details className="lead-insights-details">
                              <summary>Ver insights</summary>
                              <p>{lead.site_insights}</p>
                            </details>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td>{lead.email || "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="pagination-row">
              <span className="helper-text">
                Mostrando {leadPageStart}-{leadPageEnd} de {filteredLeads.length}
              </span>
              <div className="row-actions">
                <button
                  className="secondary-button compact-button"
                  disabled={currentLeadPage <= 1}
                  onClick={() => setLeadPage((page) => Math.max(1, page - 1))}
                  type="button"
                >
                  <ChevronLeft size={16} />
                  Anterior
                </button>
                <span className="muted-count">
                  Página {currentLeadPage} de {leadPageCount}
                </span>
                <button
                  className="secondary-button compact-button"
                  disabled={currentLeadPage >= leadPageCount}
                  onClick={() => setLeadPage((page) => Math.min(leadPageCount, page + 1))}
                  type="button"
                >
                  Próxima
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </section>
        ) : activeView === "whatsapp" ? (
          <section className="email-workspace whatsapp-workspace">
            {(whatsappError || whatsappMessage) && (
              <div className={`notice ${whatsappError ? "danger" : "success"}`}>{whatsappError || whatsappMessage}</div>
            )}

            <section className="dashboard-metrics">
              <article className="metric-card">
                <MessageCircle size={20} />
                <span>Instâncias conectadas</span>
                <strong>{whatsappDashboard.connected}</strong>
              </article>
              <article className="metric-card">
                <FileText size={20} />
                <span>Templates</span>
                <strong>{whatsappTemplates.length}</strong>
              </article>
              <article className="metric-card">
                <Megaphone size={20} />
                <span>Campanhas rodando</span>
                <strong>{whatsappDashboard.running}</strong>
              </article>
              <article className="metric-card">
                <Send size={20} />
                <span>Mensagens enviadas</span>
                <strong>{whatsappDashboard.sent}</strong>
              </article>
            </section>
          </section>
        ) : activeView === "whatsappInstances" ? (
          <section className="email-workspace whatsapp-workspace">
            {(whatsappError || whatsappMessage) && (
              <div className={`notice ${whatsappError ? "danger" : "success"}`}>{whatsappError || whatsappMessage}</div>
            )}

            <section className="email-grid whatsapp-grid">
              <form className="panel email-panel" onSubmit={handleCreateWhatsappInstance}>
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Evolution</p>
                    <h2>Nova instância</h2>
                  </div>
                  <MessageCircle size={20} />
                </div>
                <div className="form-grid single-column-grid">
                  <label>
                    Nome
                    <input
                      value={whatsappInstanceForm.name}
                      onChange={(event) => {
                        setWhatsappInstanceForm({ ...whatsappInstanceForm, name: event.target.value });
                        setWhatsappInstanceFormErrors((current) => ({ ...current, name: "" }));
                      }}
                    />
                    {whatsappInstanceFormErrors.name ? <small className="field-error">{whatsappInstanceFormErrors.name}</small> : null}
                  </label>
                  <label>
                    Telefone
                    <input
                      inputMode="tel"
                      placeholder="+5511999999999"
                      value={whatsappInstanceForm.phone_number}
                      onChange={(event) =>
                        setWhatsappInstanceForm({
                          ...whatsappInstanceForm,
                          phone_number: formatWhatsappPhoneInput(event.target.value)
                        })
                      }
                    />
                    <small className="helper-text">Opcional. Use DDI e DDD quando souber o número.</small>
                  </label>
                </div>
                <button className="primary-button" disabled={whatsappBusyAction === "create-instance"} type="submit">
                  {whatsappBusyAction === "create-instance" ? <Loader2 className="spin" size={18} /> : <Plus size={18} />}
                  Criar instância
                </button>
              </form>

              <section className="panel table-panel whatsapp-instance-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Conexões</p>
                    <h2>Instâncias</h2>
                  </div>
                  <span className="muted-count">{whatsappInstances.length} instâncias</span>
                </div>
                <div className="table-wrap">
                  <table className="campaign-table whatsapp-table">
                    <thead>
                      <tr>
                        <th>Nome</th>
                        <th>Status</th>
                        <th>Telefone</th>
                        <th>Conectada em</th>
                        <th>Ações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {whatsappInstances.length === 0 ? (
                        <tr>
                          <td className="empty-cell" colSpan={5}>
                            Nenhuma instância criada.
                          </td>
                        </tr>
                      ) : null}
                      {whatsappInstances.map((instance) => {
                        const qrBusy = whatsappBusyAction === `qr-${instance.id}`;
                        const statusBusy = whatsappBusyAction === `status-${instance.id}`;
                        return (
                          <tr key={instance.id}>
                            <td>
                              <strong>{instance.name}</strong>
                              <span>{instance.evolution_instance_name || instance.provider}</span>
                            </td>
                            <td>
                              <span className={`status-pill ${instance.status}`}>
                                {whatsappInstanceStatusLabel(instance.status)}
                              </span>
                            </td>
                            <td>{formatOptionalText(instance.phone_number)}</td>
                            <td>{formatDate(instance.connected_at)}</td>
                            <td>
                              <div className="row-actions">
                                <button
                                  className="secondary-button compact-button"
                                  disabled={qrBusy}
                                  onClick={() => handleOpenWhatsappQrCode(instance)}
                                  type="button"
                                >
                                  {qrBusy ? <Loader2 className="spin" size={16} /> : <QrCode size={16} />}
                                  QR Code
                                </button>
                                <button
                                  className="icon-button"
                                  disabled={statusBusy}
                                  onClick={() => handleRefreshWhatsappInstanceStatus(instance.id)}
                                  title="Atualizar status"
                                  type="button"
                                >
                                  {statusBusy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                                </button>
                                <button
                                  className="icon-button danger"
                                  onClick={() => handleDeleteWhatsappInstance(instance)}
                                  title="Excluir instância"
                                  type="button"
                                >
                                  <Trash2 size={16} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            </section>
          </section>
        ) : activeView === "whatsappTemplates" ? (
          <section className="email-workspace whatsapp-workspace">
            {(whatsappError || whatsappMessage) && (
              <div className={`notice ${whatsappError ? "danger" : "success"}`}>{whatsappError || whatsappMessage}</div>
            )}

            <section className="email-grid whatsapp-template-grid">
              <form className="panel email-panel" onSubmit={handleSaveWhatsappTemplate}>
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Mensagem</p>
                    <h2>{editingWhatsappTemplateId ? "Editar template" : "Novo template"}</h2>
                  </div>
                  <FileText size={20} />
                </div>
                <div className="form-grid single-column-grid">
                  <label>
                    Nome
                    <input
                      value={whatsappTemplateForm.name}
                      onChange={(event) => {
                        setWhatsappTemplateForm({ ...whatsappTemplateForm, name: event.target.value });
                        setWhatsappTemplateFormErrors((current) => ({ ...current, name: "" }));
                      }}
                    />
                    {whatsappTemplateFormErrors.name ? <small className="field-error">{whatsappTemplateFormErrors.name}</small> : null}
                  </label>
                  <label>
                    Objetivo
                    <textarea
                      rows={3}
                      value={whatsappTemplateObjective}
                      onChange={(event) => setWhatsappTemplateObjective(event.target.value)}
                      placeholder="Ex: vender criação de site grátis, paga só se gostar"
                    />
                  </label>
                  <button
                    className="secondary-button compact-button"
                    disabled={whatsappBusyAction === "generate-template-ai"}
                    onClick={handleGenerateWhatsappTemplateWithAi}
                    type="button"
                  >
                    {whatsappBusyAction === "generate-template-ai" ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
                    Gerar com IA
                  </button>
                  <label>
                    Conteúdo
                    <textarea
                      rows={8}
                      value={whatsappTemplateForm.content}
                      onChange={(event) => {
                        setWhatsappTemplateForm({ ...whatsappTemplateForm, content: event.target.value });
                        setWhatsappTemplateFormErrors((current) => ({ ...current, content: "" }));
                      }}
                    />
                    {whatsappTemplateFormErrors.content ? <small className="field-error">{whatsappTemplateFormErrors.content}</small> : null}
                  </label>
                  <div className="variable-hints">
                    {WHATSAPP_VARIABLES.map((variable) => (
                      <span className="filter-tag" key={variable}>
                        {variable}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="row-actions">
                  {editingWhatsappTemplateId ? (
                    <button className="secondary-button" onClick={resetWhatsappTemplateForm} type="button">
                      Cancelar edição
                    </button>
                  ) : null}
                  <button className="primary-button" disabled={whatsappBusyAction === "save-template"} type="submit">
                    {whatsappBusyAction === "save-template" ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
                    {editingWhatsappTemplateId ? "Salvar template" : "Criar template"}
                  </button>
                </div>
              </form>

              <section className="panel table-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Biblioteca</p>
                    <h2>Templates WhatsApp</h2>
                  </div>
                  <span className="muted-count">{whatsappTemplates.length} templates</span>
                </div>
                <div className="table-wrap">
                  <table className="campaign-table whatsapp-table">
                    <thead>
                      <tr>
                        <th>Template</th>
                        <th>Conteúdo</th>
                        <th>Criado em</th>
                        <th>Ações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {whatsappTemplates.length === 0 ? (
                        <tr>
                          <td className="empty-cell" colSpan={4}>
                            Nenhum template criado.
                          </td>
                        </tr>
                      ) : null}
                      {whatsappTemplates.map((template) => (
                        <tr key={template.id}>
                          <td>
                            <strong>{template.name}</strong>
                          </td>
                          <td>
                            <span className="template-text-preview">{template.content}</span>
                          </td>
                          <td>{formatDate(template.created_at)}</td>
                          <td>
                            <div className="row-actions">
                              <button
                                className="icon-button"
                                onClick={() => loadWhatsappTemplateForEdit(template)}
                                title="Editar template"
                                type="button"
                              >
                                <Edit3 size={16} />
                              </button>
                              <button
                                className="icon-button danger"
                                onClick={() => requestDeleteWhatsappTemplate(template)}
                                title="Excluir template"
                                type="button"
                              >
                                <Trash2 size={16} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </section>
          </section>
        ) : activeView === "whatsappCampaigns" ? (
          <section className="email-workspace whatsapp-workspace">
            {(whatsappError || whatsappMessage) && (
              <div className={`notice ${whatsappError ? "danger" : "success"}`}>{whatsappError || whatsappMessage}</div>
            )}

            <section className="panel table-panel whatsapp-campaign-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Campanhas</p>
                  <h2>Fila WhatsApp</h2>
                </div>
                <div className="lead-actions">
                  <span className="muted-count">{whatsappCampaigns.length} campanhas</span>
                  <button className="secondary-button compact-button" onClick={openNewWhatsappCampaignModal} type="button">
                    <Plus size={16} />
                    Adicionar campanha
                  </button>
                </div>
              </div>
              <div className="table-wrap">
                <table className="campaign-table whatsapp-table">
                  <thead>
                    <tr>
                      <th>Campanha</th>
                      <th>Instância</th>
                      <th>Mensagem</th>
                      <th>Status</th>
                      <th>Enviados/total</th>
                      <th>Janela</th>
                      <th>Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {whatsappCampaigns.length === 0 ? (
                      <tr>
                        <td className="empty-cell" colSpan={7}>
                          Nenhuma campanha criada.
                        </td>
                      </tr>
                    ) : null}
                    {whatsappCampaigns.map((campaign) => {
                      const successCount = campaign.sent_count + campaign.delivered_count + campaign.read_count;
                      const total =
                        campaign.pending_count + campaign.sent_count + campaign.delivered_count + campaign.read_count + campaign.failed_count;
                      const startBusy = whatsappBusyAction === `start-campaign-${campaign.id}`;
                      const pauseBusy = whatsappBusyAction === `pause-campaign-${campaign.id}`;
                      const campaignTemplateNames = campaign.template_ids
                        .map((templateId) => whatsappTemplates.find((template) => template.id === templateId)?.name || `#${templateId}`)
                        .join(", ");
                      return (
                        <tr key={campaign.id}>
                          <td>
                            <strong>{campaign.name}</strong>
                            <span>{campaign.list_name}</span>
                            <span>Funil: {campaign.funnel_name || defaultCrmFunnel?.name || "Funil padrão"}</span>
                            {campaign.objective ? <span>{campaign.objective}</span> : null}
                            <span>{campaign.message || campaign.error}</span>
                          </td>
                          <td>{campaign.instance_name}</td>
                          <td>
                            {campaign.message_mode === "ai_per_lead" ? "IA por lead" : campaignTemplateNames || "-"}
                          </td>
                          <td>
                            <span className={`status-pill ${campaign.status}`}>{campaignStatusLabel(campaign.status)}</span>
                          </td>
                          <td>
                            {successCount}/{total}
                            {campaign.failed_count ? <span>{campaign.failed_count} falhas</span> : null}
                          </td>
                          <td>
                            {campaign.send_window_start}-{campaign.send_window_end}
                            <span>{formatCampaignSendDaysLabel(campaign.send_days)}</span>
                          </td>
                          <td>
                            <div className="row-actions">
                              <button
                                className="icon-button"
                                disabled={campaign.status === "running"}
                                onClick={() => loadWhatsappCampaignForEdit(campaign)}
                                title={campaign.status === "running" ? "Pause a campanha antes de editar" : "Editar campanha"}
                                type="button"
                              >
                                <Edit3 size={16} />
                              </button>
                              {campaign.status === "draft" || campaign.status === "paused" ? (
                                <button
                                  className="icon-button"
                                  disabled={startBusy}
                                  onClick={() => requestStartWhatsappCampaign(campaign)}
                                  title="Iniciar campanha"
                                  type="button"
                                >
                                  {startBusy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                                </button>
                              ) : null}
                              {campaign.status === "running" ? (
                                <button
                                  className="icon-button"
                                  disabled={pauseBusy}
                                  onClick={() => pauseWhatsappCampaign(campaign)}
                                  title="Pausar campanha"
                                  type="button"
                                >
                                  {pauseBusy ? <Loader2 className="spin" size={16} /> : <Pause size={16} />}
                                </button>
                              ) : null}
                              {campaign.status !== "running" ? (
                                <button
                                  className="icon-button danger"
                                  onClick={() => requestDeleteWhatsappCampaign(campaign)}
                                  title="Excluir campanha"
                                  type="button"
                                >
                                  <Trash2 size={16} />
                                </button>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          </section>
        ) : activeView === "whatsappCrm" ? (
          <section className="email-workspace whatsapp-workspace crm-workspace">
            {(whatsappError || whatsappMessage) && (
              <div className={`notice ${whatsappError ? "danger" : "success"}`}>{whatsappError || whatsappMessage}</div>
            )}

            <section className="panel crm-board-toolbar">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Pipeline</p>
                  <h2>CRM WhatsApp</h2>
                </div>
                <div className="lead-actions">
                  <span className="muted-count">{crmLeads.length} cards</span>
                  <label className="crm-funnel-selector">
                    Funil
                    <select
                      disabled={crmFunnels.length === 0}
                      value={selectedCrmFunnelIdValue || ""}
                      onChange={(event) => setSelectedCrmFunnelId(event.target.value ? Number(event.target.value) : null)}
                    >
                      {crmFunnels.map((funnel) => (
                        <option key={funnel.id} value={funnel.id}>
                          {funnel.name}
                          {funnel.is_default ? " · padrão" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button className="secondary-button compact-button" onClick={openFunnelManager} type="button">
                    <Settings size={16} />
                    Gerenciar funis
                  </button>
                  <button className="secondary-button compact-button" onClick={openTagManager} type="button">
                    <Tags size={16} />
                    Gerenciar tags
                  </button>
                </div>
              </div>
              <div className="filters-row crm-board-filters-row">
                <LeadTagFilter
                  allLabel="Todas as tags"
                  label="Filtrar board por tag"
                  mode={crmTagFilterMode}
                  onChange={setSelectedCrmTagIds}
                  onModeChange={setCrmTagFilterMode}
                  placeholder="Adicionar tag"
                  selectedIds={selectedCrmTagIds}
                  tags={tags}
                />
                <button
                  className="secondary-button"
                  onClick={() => {
                    setSelectedCrmTagIds([]);
                    setCrmTagFilterMode("any");
                  }}
                  type="button"
                >
                  Limpar filtros
                </button>
              </div>
            </section>

            <DndContext
              collisionDetection={closestCorners}
              onDragCancel={handleCrmDragCancel}
              onDragEnd={handleCrmDragEnd}
              onDragOver={handleCrmDragOver}
              onDragStart={handleCrmDragStart}
              sensors={crmDndSensors}
            >
              <section className="crm-board" aria-label="Pipeline de CRM">
                {selectedCrmStages.length === 0 ? <p className="empty-state">Nenhum estágio neste funil.</p> : null}
                {selectedCrmStages.map((stage) => {
                  const stageLeads = crmLeadsByStage[stage.key] || [];
                  return (
                    <CrmStageColumn
                      isDragOver={overCrmStage === stage.key}
                      key={stage.id}
                      leads={stageLeads}
                      stage={stage}
                    >
                      {stageLeads.map((lead) => (
                        <SortableCrmLeadCard
                          disabled={whatsappBusyAction === `crm-${lead.lead_id}`}
                          key={lead.id}
                          lead={lead}
                          onOpen={() => openCrmDetailModal(lead)}
                        />
                      ))}
                    </CrmStageColumn>
                  );
                })}
              </section>
              <DragOverlay>
                {activeCrmDragLead ? (
                  <article className="crm-lead-card crm-drag-overlay">
                    <CrmLeadCardContent lead={activeCrmDragLead} />
                  </article>
                ) : null}
              </DragOverlay>
            </DndContext>
          </section>
        ) : activeView === "whatsappAi" ? (
          <section className="email-workspace whatsapp-workspace whatsapp-ai-workspace">
            {(whatsappError || whatsappMessage) && (
              <div className={`notice ${whatsappError ? "danger" : "success"}`}>{whatsappError || whatsappMessage}</div>
            )}

            <form className="panel email-panel whatsapp-ai-panel" onSubmit={handleSaveWhatsappAiSettings}>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Resposta automática</p>
                  <h2>Configuração da IA</h2>
                </div>
                <span className={`status-pill ${whatsappAiForm.enabled ? "connected" : "disconnected"}`}>
                  {whatsappAiForm.enabled ? "Ativa" : "Inativa"}
                </span>
              </div>

              <label className="checkbox-label whatsapp-ai-toggle">
                <input
                  checked={whatsappAiForm.enabled}
                  onChange={(event) => setWhatsappAiForm({ ...whatsappAiForm, enabled: event.target.checked })}
                  type="checkbox"
                />
                Ativar resposta automática
              </label>

              <label className="checkbox-label whatsapp-ai-toggle">
                <input
                  checked={whatsappAiForm.auto_apply_tags_enabled}
                  onChange={(event) =>
                    setWhatsappAiForm({ ...whatsappAiForm, auto_apply_tags_enabled: event.target.checked })
                  }
                  type="checkbox"
                />
                IA pode aplicar tags automaticamente
              </label>

              <label>
                Sobre seus serviços
                <textarea
                  rows={8}
                  value={whatsappAiForm.services_description}
                  onChange={(event) => setWhatsappAiForm({ ...whatsappAiForm, services_description: event.target.value })}
                  placeholder="Descreva o que você oferece, diferenciais e público-alvo. Não inclua valores."
                />
              </label>

              <label>
                Prompt de sistema
                <textarea
                  rows={14}
                  value={whatsappAiForm.system_prompt}
                  onChange={(event) => setWhatsappAiForm({ ...whatsappAiForm, system_prompt: event.target.value })}
                />
              </label>

              <div className="whatsapp-ai-footer">
                <small>Última atualização: {formatDate(whatsappAiSettings?.updated_at || null)}</small>
                <button className="primary-button" disabled={whatsappBusyAction === "save-ai-settings"} type="submit">
                  {whatsappBusyAction === "save-ai-settings" ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
                  Salvar configuração
                </button>
              </div>
            </form>

            <section className="panel table-panel whatsapp-portfolio-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Contexto comercial</p>
                  <h2>Portfólio</h2>
                </div>
                <span className="muted-count">{whatsappPortfolioItems.length} itens</span>
              </div>

              <form className="form-grid portfolio-form" onSubmit={handleCreateWhatsappPortfolioItem}>
                <label>
                  Descrição curta
                  <input
                    value={whatsappPortfolioForm.description}
                    onChange={(event) => setWhatsappPortfolioForm({ ...whatsappPortfolioForm, description: event.target.value })}
                    placeholder="Ex: site institucional para clínica odontológica"
                  />
                </label>
                <label>
                  Link
                  <input
                    value={whatsappPortfolioForm.url}
                    onChange={(event) => setWhatsappPortfolioForm({ ...whatsappPortfolioForm, url: event.target.value })}
                    placeholder="https://..."
                  />
                </label>
                <button className="primary-button" disabled={whatsappBusyAction === "create-portfolio"} type="submit">
                  {whatsappBusyAction === "create-portfolio" ? <Loader2 className="spin" size={18} /> : <Plus size={18} />}
                  Adicionar
                </button>
              </form>

              <div className="table-wrap">
                <table className="whatsapp-table">
                  <thead>
                    <tr>
                      <th>Descrição</th>
                      <th>Link</th>
                      <th>Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {whatsappPortfolioItems.length === 0 ? (
                      <tr>
                        <td className="empty-cell" colSpan={3}>
                          Nenhum item de portfólio cadastrado.
                        </td>
                      </tr>
                    ) : null}
                    {whatsappPortfolioItems.map((item) => {
                      const deleteBusy = whatsappBusyAction === `delete-portfolio-${item.id}`;
                      return (
                        <tr key={item.id}>
                          <td>
                            <strong>{item.description}</strong>
                            <span>{formatDate(item.created_at)}</span>
                          </td>
                          <td>
                            <a href={item.url} rel="noreferrer" target="_blank">
                              {item.url}
                            </a>
                          </td>
                          <td>
                            <button
                              className="icon-button danger"
                              disabled={deleteBusy}
                              onClick={() => deleteWhatsappPortfolioItem(item.id)}
                              title="Remover item"
                              type="button"
                            >
                              {deleteBusy ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          </section>
        ) : activeView === "dashboard" ? (
          <section className="email-workspace">
            {(emailError || emailMessage) && (
              <div className={`notice ${emailError ? "danger" : "success"}`}>{emailError || emailMessage}</div>
            )}

            <section className="dashboard-metrics">
              <article className="metric-card">
                <Send size={20} />
                <span>Enviados</span>
                <strong>{emailDashboard.sent}</strong>
              </article>
              <article className="metric-card">
                <Eye size={20} />
                <span>Abertos</span>
                <strong>{emailDashboard.opened}</strong>
                <small>{emailDashboard.openRate} de abertura</small>
              </article>
              <article className="metric-card">
                <MousePointerClick size={20} />
                <span>Cliques</span>
                <strong>{emailDashboard.clicked}</strong>
                <small>{emailDashboard.clickRate} de clique</small>
              </article>
              <article className="metric-card">
                <Megaphone size={20} />
                <span>Campanhas rodando</span>
                <strong>{emailDashboard.runningCampaigns}</strong>
                <small>{emailDashboard.completedCampaigns} concluídas</small>
              </article>
            </section>

            <section className="dashboard-grid">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Operação</p>
                    <h2>Campanhas recentes</h2>
                  </div>
                  <Megaphone size={20} />
                </div>
                <div className="jobs-list">
                  {campaigns.length === 0 ? <p className="empty-state">Nenhuma campanha criada.</p> : null}
                  {campaigns.slice(0, 6).map((campaign) => {
                    const total = campaign.pending_count + campaign.sent_count + campaign.failed_count;
                    return (
                      <article className="campaign-card" key={campaign.id}>
                        <div>
                          <strong>{campaign.name}</strong>
                          <span>{campaign.list_name}</span>
                        </div>
                        <span className={`status-pill ${campaign.status}`}>{campaignStatusLabel(campaign.status)}</span>
                        <div className="progress-track">
                          <span style={{ width: percent(campaign.sent_count, total) }} />
                        </div>
                        <small>
                          {campaign.sent_count} enviados · {campaign.pending_count} na fila · {campaign.failed_count} falhas
                        </small>
                      </article>
                    );
                  })}
                </div>
              </section>

              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Engajamento</p>
                    <h2>Por template</h2>
                  </div>
                  <BarChart3 size={20} />
                </div>
                <div className="template-stats-list">
                  {emailDashboard.templateStats.map((item) => (
                    <article className="template-stat-row" key={item.id}>
                      <div>
                        <strong>{item.name}</strong>
                        <span>{item.sent} enviados</span>
                      </div>
                      <div className="stat-pair">
                        <span>{item.openRate} aberturas</span>
                        <span>{item.clickRate} cliques</span>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            </section>

            <section className="panel table-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Atividade</p>
                  <h2>Últimos envios</h2>
                </div>
                <button className="secondary-button" onClick={() => switchView("history")} type="button">
                  Ver histórico
                </button>
              </div>
              <div className="table-wrap">
                <table className="history-table">
                  <thead>
                    <tr>
                      <th>Lead</th>
                      <th>Campanha</th>
                      <th>Status</th>
                      <th>Aberturas</th>
                      <th>Cliques</th>
                      <th>Enviado em</th>
                    </tr>
                  </thead>
                  <tbody>
                    {emailSends.slice(0, 8).map((sendLog) => (
                      <tr key={sendLog.id}>
                        <td>
                          <strong>{sendLog.lead_name}</strong>
                          <span>{sendLog.recipient_email}</span>
                        </td>
                        <td>{sendLog.campaign_name}</td>
                        <td>{sendLog.error || emailSendStatusLabel(sendLog.status)}</td>
                        <td>{sendLog.open_count}</td>
                        <td>{sendLog.click_count}</td>
                        <td>{formatDate(sendLog.sent_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </section>
        ) : activeView === "templates" ? (
          <section className="email-workspace">
            {(emailError || emailMessage) && (
              <div className={`notice ${emailError ? "danger" : "success"}`}>{emailError || emailMessage}</div>
            )}

            <section className="template-layout">
              <section className="panel template-library">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Biblioteca</p>
                    <h2>Templates salvos</h2>
                  </div>
                  <div className="row-actions">
                    <button className="secondary-button compact-button" onClick={openAiTemplateModal} title="Gerar templates com IA" type="button">
                      <Sparkles size={16} />
                      IA
                    </button>
                    <button className="icon-button" onClick={openNewTemplateModal} title="Novo template" type="button">
                      <Plus size={16} />
                    </button>
                  </div>
                </div>
                <div className="template-list">
                  {templates.map((template) => (
                    <button
                      className={`template-card ${selectedTemplate?.id === template.id ? "active" : ""}`}
                      key={template.id}
                      onClick={() => {
                        setSelectedTemplateId(template.id);
                        setEditingTemplateId(null);
                      }}
                      type="button"
                    >
                      <strong>{template.name}</strong>
                      <span>{renderTemplateSubject(template, previewSampleLead)}</span>
                      <small>{template.content_title || "Sem título de conteúdo"}</small>
                    </button>
                  ))}
                </div>
              </section>

              <section className="panel template-preview-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Pré-visualização</p>
                    <h2>{selectedTemplate?.name || "Novo template"}</h2>
                  </div>
                  {selectedTemplate ? (
                    <div className="row-actions">
                      <button className="icon-button" onClick={() => loadTemplateForEdit(selectedTemplate)} title="Editar template" type="button">
                        <Edit3 size={16} />
                      </button>
                      <button className="icon-button danger" onClick={() => handleDeleteTemplate(selectedTemplate)} title="Excluir template" type="button">
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ) : null}
                </div>
                <div className="subject-preview">
                  <span>Assunto</span>
                  <strong>{renderTemplateSubject(previewTemplate, previewSampleLead)}</strong>
                </div>
                <iframe
                  className="template-preview-frame"
                  sandbox="allow-popups allow-popups-to-escape-sandbox"
                  srcDoc={renderTemplatePreview(previewTemplate, previewContentData, previewSampleLead)}
                  title="Pré-visualização do template"
                />
              </section>
            </section>
          </section>
        ) : activeView === "lists" ? (
          <section className="email-workspace">
            {(emailError || emailMessage) && (
              <div className={`notice ${emailError ? "danger" : "success"}`}>{emailError || emailMessage}</div>
            )}

            <section className="email-grid">
              <form className="panel email-panel" onSubmit={handleCreateLeadList}>
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Segmentação</p>
                    <h2>Nova lista</h2>
                  </div>
                  <ListFilter size={20} />
                </div>
                <div className="form-grid">
                  <label>
                    Nome
                    <input value={leadListForm.name} onChange={(event) => setLeadListForm({ ...leadListForm, name: event.target.value })} />
                  </label>
                  <label>
                    Canal
                    <select
                      value={leadListForm.channel}
                      onChange={(event) =>
                        setLeadListForm({ ...leadListForm, channel: event.target.value as LeadListChannel })
                      }
                    >
                      <option value="both">Ambos</option>
                      <option value="email">E-mail</option>
                      <option value="whatsapp">WhatsApp</option>
                    </select>
                  </label>
                  <TagDropdown
                    allLabel="Todos os nichos"
                    label="Nichos"
                    options={leadNicheOptions}
                    placeholder="Adicionar nicho"
                    selected={selectedListNiches}
                    onChange={setSelectedListNiches}
                  />
                  <TagDropdown
                    allLabel="Todas as localidades"
                    label="Localidades"
                    options={leadLocationOptions}
                    placeholder="Adicionar localidade"
                    selected={selectedListLocations}
                    onChange={setSelectedListLocations}
                  />
                  <label className="checkbox-label">
                    <input
                      checked={leadListForm.only_whatsapp_validated}
                      onChange={(event) =>
                        setLeadListForm({ ...leadListForm, only_whatsapp_validated: event.target.checked })
                      }
                      type="checkbox"
                    />
                    Somente com WhatsApp válido
                  </label>
                  <label className="checkbox-label">
                    <input
                      checked={leadListForm.only_email_opened}
                      onChange={(event) => setLeadListForm({ ...leadListForm, only_email_opened: event.target.checked })}
                      type="checkbox"
                    />
                    Abriu algum e-mail
                  </label>
                  <label className="checkbox-label">
                    <input
                      checked={leadListForm.only_email_clicked}
                      onChange={(event) => setLeadListForm({ ...leadListForm, only_email_clicked: event.target.checked })}
                      type="checkbox"
                    />
                    Clicou em algum e-mail
                  </label>
                  <label>
                    Combinação de engajamento
                    <select
                      value={leadListForm.email_engagement_filter_mode}
                      onChange={(event) =>
                        setLeadListForm({
                          ...leadListForm,
                          email_engagement_filter_mode: event.target.value as "or" | "and"
                        })
                      }
                    >
                      <option value="or">Abriu ou clicou</option>
                      <option value="and">Abriu e clicou</option>
                    </select>
                  </label>
                  <label>
                    Nunca recebeu template
                    <select
                      value={leadListForm.never_received_template_id}
                      onChange={(event) => setLeadListForm({ ...leadListForm, never_received_template_id: event.target.value })}
                    >
                      <option value="">Ignorar</option>
                      {templates.map((template) => (
                        <option key={template.id} value={template.id}>
                          {template.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="checkbox-label">
                    <input
                      checked={leadListForm.only_never_emailed}
                      onChange={(event) => setLeadListForm({ ...leadListForm, only_never_emailed: event.target.checked })}
                      type="checkbox"
                    />
                    Nunca recebeu e-mail
                  </label>
                </div>
                <button className="primary-button" disabled={emailBusy} type="submit">
                  <ListFilter size={16} />
                  Criar lista
                </button>
              </form>

              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Listas</p>
                    <h2>Listas prontas</h2>
                  </div>
                  <span className="muted-count">{leadLists.length} listas</span>
                </div>
                <div className="list-card-grid">
                  {leadLists.length === 0 ? <p className="empty-state">Nenhuma lista criada.</p> : null}
                  {leadLists.map((list) => (
                    <article className="list-card" key={list.id}>
                      <div className="list-card-header">
                        <strong>{list.name}</strong>
                        <div className="row-actions">
                          <button
                            className="icon-button"
                            onClick={() => openEditLeadListModal(list)}
                            title="Editar lista"
                            type="button"
                          >
                            <Edit3 size={16} />
                          </button>
                          <button
                            className="icon-button danger"
                            onClick={() => handleDeleteLeadList(list)}
                            title="Excluir lista"
                            type="button"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>
                      <span>{list.lead_count} leads</span>
                      <small>
                        {formatListFilter(list.niche_filter, "Todos os nichos")} · {formatListFilter(list.location_filter, "Todas as localidades")}
                      </small>
                      <small>
                        Canal: {list.channel === "email" ? "E-mail" : list.channel === "whatsapp" ? "WhatsApp" : "Ambos"}
                      </small>
                      {list.only_whatsapp_validated ? <small>Somente WhatsApp válido</small> : null}
                      {list.only_email_opened || list.only_email_clicked ? (
                        <small>
                          Engajamento:{" "}
                          {list.only_email_opened && list.only_email_clicked
                            ? list.email_engagement_filter_mode === "and"
                              ? "abriu e clicou"
                              : "abriu ou clicou"
                            : list.only_email_opened
                              ? "abriu algum e-mail"
                              : "clicou em algum e-mail"}
                        </small>
                      ) : null}
                      {list.only_never_emailed ? <small>Nunca recebeu e-mail</small> : null}
                      {list.never_received_template_id ? (
                        <small>
                          Nunca recebeu: {templates.find((template) => template.id === list.never_received_template_id)?.name || "template selecionado"}
                        </small>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>
            </section>
          </section>
        ) : activeView === "campaigns" ? (
          <section className="email-workspace">
            {(emailError || emailMessage) && (
              <div className={`notice ${emailError ? "danger" : "success"}`}>{emailError || emailMessage}</div>
            )}

            <section className="panel table-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Controle</p>
                  <h2>Campanhas</h2>
                </div>
                <div className="lead-actions">
                  <span className="muted-count">{campaigns.length} campanhas</span>
                  <button className="secondary-button compact-button" onClick={openNewCampaignModal} type="button">
                    <Plus size={16} />
                    Adicionar campanha
                  </button>
                </div>
              </div>
              <div className="table-wrap">
                <table className="campaign-table">
                  <thead>
                    <tr>
                      <th>Campanha</th>
                      <th>Lista</th>
                      <th>Status</th>
                      <th>Fila</th>
                      <th>Enviados</th>
                      <th>Falhas</th>
                      <th>Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {campaigns.length === 0 ? (
                      <tr>
                        <td className="empty-cell" colSpan={7}>
                          Nenhuma campanha criada.
                        </td>
                      </tr>
                    ) : null}
                    {campaigns.map((campaign) => (
                      <tr key={campaign.id}>
                        <td>
                          <strong>{campaign.name}</strong>
                          <span>{campaign.message_mode === "ai_per_lead" ? "IA por lead" : "Template fixo"}</span>
                          {campaign.objective ? <span>{campaign.objective}</span> : null}
                          <span>{campaign.message || campaign.error}</span>
                        </td>
                        <td>{campaign.list_name}</td>
                        <td>
                          <span className={`status-pill ${campaign.status}`}>{campaignStatusLabel(campaign.status)}</span>
                        </td>
                        <td>{campaign.pending_count}</td>
                        <td>{campaign.sent_count}</td>
                        <td>{campaign.failed_count}</td>
                        <td>
                          <div className="row-actions">
                            <button
                              className="icon-button"
                              disabled={campaign.status === "running"}
                              onClick={() => loadCampaignForEdit(campaign)}
                              title={campaign.status === "running" ? "Pause a campanha antes de editar" : "Editar campanha"}
                              type="button"
                            >
                              <Edit3 size={16} />
                            </button>
                            {campaign.status === "draft" || campaign.status === "paused" ? (
                              <button className="icon-button" onClick={() => handleCampaignAction(campaign.id, "start")} title="Iniciar campanha" type="button">
                                <Play size={16} />
                              </button>
                            ) : null}
                            {campaign.status === "running" ? (
                              <button className="icon-button" onClick={() => handleCampaignAction(campaign.id, "pause")} title="Pausar campanha" type="button">
                                <Pause size={16} />
                              </button>
                            ) : null}
                            <button
                              className="icon-button danger"
                              disabled={campaign.status === "running"}
                              onClick={() => handleDeleteCampaign(campaign)}
                              title={campaign.status === "running" ? "Pause a campanha antes de excluir" : "Excluir campanha"}
                              type="button"
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </section>
        ) : activeView === "history" ? (
          <section className="email-workspace">
            {(emailError || emailMessage) && (
              <div className={`notice ${emailError ? "danger" : "success"}`}>{emailError || emailMessage}</div>
            )}

            <section className="panel table-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Rastreamento</p>
                  <h2>Histórico de envios</h2>
                </div>
                <div className="lead-actions">
                  <span className="muted-count">{filteredEmailSends.length} visíveis</span>
                  {filteredEmailSends.length !== emailSends.length ? (
                    <span className="muted-count">{emailSends.length} totais</span>
                  ) : null}
                  <span className="muted-count">{historyMetrics.opens} aberturas</span>
                  <span className="muted-count">{historyMetrics.clicks} cliques</span>
                </div>
              </div>
              <div className="filters-row history-filters-row">
                <TagDropdown
                  allLabel="Todas as campanhas"
                  label="Filtrar por campanha"
                  options={historyCampaignOptions}
                  placeholder="Adicionar campanha"
                  selected={selectedHistoryCampaigns}
                  onChange={setSelectedHistoryCampaigns}
                />
                <TagDropdown
                  allLabel="Todos os templates"
                  label="Filtrar por template"
                  options={historyTemplateOptions}
                  placeholder="Adicionar template"
                  selected={selectedHistoryTemplates}
                  onChange={setSelectedHistoryTemplates}
                />
                <TagDropdown
                  allLabel="Todos os status"
                  label="Filtrar por status"
                  options={historyStatusOptions}
                  placeholder="Adicionar status"
                  selected={selectedHistoryStatuses}
                  onChange={setSelectedHistoryStatuses}
                />
                <TagDropdown
                  allLabel="Todo engajamento"
                  label="Filtrar por engajamento"
                  options={HISTORY_ENGAGEMENT_OPTIONS}
                  placeholder="Adicionar engajamento"
                  selected={selectedHistoryEngagements}
                  onChange={setSelectedHistoryEngagements}
                />
                <button
                  className="secondary-button"
                  onClick={() => {
                    setSelectedHistoryCampaigns([]);
                    setSelectedHistoryTemplates([]);
                    setSelectedHistoryStatuses([]);
                    setSelectedHistoryEngagements([]);
                    setHistoryPage(1);
                  }}
                  type="button"
                >
                  Limpar filtros
                </button>
              </div>
              <div className="table-wrap">
                <table className="history-table">
                  <thead>
                    <tr>
                      <th>Lead</th>
                      <th>Campanha</th>
                      <th>Template</th>
                      <th>Status</th>
                      <th>Aberturas</th>
                      <th>Cliques</th>
                      <th>Aberto em</th>
                      <th>Clicado em</th>
                      <th>Enviado em</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredEmailSends.length === 0 ? (
                      <tr>
                        <td className="empty-cell" colSpan={9}>
                          Nenhum envio encontrado para os filtros.
                        </td>
                      </tr>
                    ) : null}
                    {paginatedEmailSends.map((sendLog) => (
                      <tr key={sendLog.id}>
                        <td>
                          <strong>{sendLog.lead_name}</strong>
                          <span>{sendLog.recipient_email}</span>
                        </td>
                        <td>{sendLog.campaign_name}</td>
                        <td>{sendLog.template_name}</td>
                        <td>{sendLog.error || emailSendStatusLabel(sendLog.status)}</td>
                        <td>{sendLog.open_count}</td>
                        <td>{sendLog.click_count}</td>
                        <td>{formatDate(sendLog.opened_at)}</td>
                        <td>{formatDate(sendLog.clicked_at)}</td>
                        <td>{formatDate(sendLog.sent_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pagination-row">
                <span className="helper-text">
                  Mostrando {historyPageStart}-{historyPageEnd} de {filteredEmailSends.length}
                </span>
                <div className="row-actions">
                  <button
                    className="secondary-button compact-button"
                    disabled={currentHistoryPage <= 1}
                    onClick={() => setHistoryPage((page) => Math.max(1, page - 1))}
                    type="button"
                  >
                    <ChevronLeft size={16} />
                    Anterior
                  </button>
                  <span className="muted-count">
                    Página {currentHistoryPage} de {historyPageCount}
                  </span>
                  <button
                    className="secondary-button compact-button"
                    disabled={currentHistoryPage >= historyPageCount}
                    onClick={() => setHistoryPage((page) => Math.min(historyPageCount, page + 1))}
                    type="button"
                  >
                    Próxima
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            </section>
          </section>
        ) : activeView === "settings" ? (
          <section className="email-workspace">
            {(emailError || emailMessage) && (
              <div className={`notice ${emailError ? "danger" : "success"}`}>{emailError || emailMessage}</div>
            )}

            <form className="panel email-panel settings-panel" onSubmit={handleSaveSmtp}>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Configurações</p>
                  <h2>SMTP Zoho</h2>
                </div>
                <Settings size={20} />
              </div>
              <div className="form-grid">
                <label>
                  From e-mail
                  <input value={smtpForm.from_email} onChange={(event) => setSmtpForm({ ...smtpForm, from_email: event.target.value })} />
                </label>
                <label>
                  From name
                  <input value={smtpForm.from_name} onChange={(event) => setSmtpForm({ ...smtpForm, from_name: event.target.value })} />
                </label>
                <label>
                  Reply-to
                  <input value={smtpForm.reply_to} onChange={(event) => setSmtpForm({ ...smtpForm, reply_to: event.target.value })} />
                </label>
                <label>
                  Usuário SMTP
                  <input
                    autoComplete="username"
                    value={smtpForm.username}
                    onChange={(event) => setSmtpForm({ ...smtpForm, username: event.target.value })}
                  />
                </label>
                <label>
                  Host
                  <input value={smtpForm.host} onChange={(event) => setSmtpForm({ ...smtpForm, host: event.target.value })} />
                </label>
                <label>
                  Porta
                  <input type="number" value={smtpForm.port} onChange={(event) => setSmtpForm({ ...smtpForm, port: Number(event.target.value) })} />
                </label>
                <label>
                  Senha SMTP
                  <div className="password-row">
                    <input
                      autoComplete="current-password"
                      placeholder={smtpForm.has_password ? "Senha salva: ••••••••••••" : "Senha do SMTP"}
                      type={showSmtpPassword ? "text" : "password"}
                      value={smtpPassword}
                      onChange={(event) => setSmtpPassword(event.target.value)}
                    />
                    <button
                      className="icon-button"
                      onClick={() => setShowSmtpPassword((current) => !current)}
                      title={showSmtpPassword ? "Ocultar senha digitada" : "Mostrar senha digitada"}
                      type="button"
                    >
                      {showSmtpPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </label>
                <label>
                  E-mail de teste
                  <input value={smtpTestEmail} onChange={(event) => setSmtpTestEmail(event.target.value)} />
                </label>
                <label className="wide-field">
                  Template de teste
                  <select value={smtpTestTemplateId} onChange={(event) => setSmtpTestTemplateId(event.target.value)}>
                    <option value="">Teste simples SMTP</option>
                    {templates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p className="helper-text">
                No Zoho, o From e-mail precisa ser o mesmo endereço do usuário SMTP ou um alias autorizado. Reply-to é para
                onde a resposta vai; não é cópia. O e-mail de teste é o destinatário do teste. Ao escolher um template, o
                teste renderiza esse modelo com dados fictícios de lead.
              </p>
              <div className="inline-controls">
                <label className="checkbox-label">
                  <input
                    checked={smtpForm.use_ssl}
                    onChange={(event) => setSmtpForm({ ...smtpForm, use_ssl: event.target.checked, use_tls: false })}
                    type="checkbox"
                  />
                  SSL
                </label>
                <label className="checkbox-label">
                  <input
                    checked={smtpForm.use_tls}
                    onChange={(event) => setSmtpForm({ ...smtpForm, use_tls: event.target.checked, use_ssl: false })}
                    type="checkbox"
                  />
                  TLS
                </label>
                <button className="primary-button" disabled={emailBusy} type="submit">
                  <Save size={16} />
                  Salvar SMTP
                </button>
                <button className="secondary-button" disabled={emailBusy} onClick={handleTestSmtp} type="button">
                  <Send size={16} />
                  Testar
                </button>
              </div>
            </form>
          </section>
        ) : null}
      </section>

      {editingLeadList ? (
        <div className="modal-backdrop">
          <form className="edit-modal" onSubmit={handleSaveLeadList}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Editar lista</p>
                <h2>{editingLeadList.name}</h2>
              </div>
              <button className="icon-button" onClick={closeEditLeadListModal} title="Fechar" type="button">
                <X size={18} />
              </button>
            </div>

            <div className="edit-grid">
              <label className="wide-field">
                Nome
                <input
                  required
                  value={editLeadListForm.name}
                  onChange={(event) => setEditLeadListForm({ ...editLeadListForm, name: event.target.value })}
                />
              </label>
              <label>
                Canal
                <select
                  value={editLeadListForm.channel}
                  onChange={(event) =>
                    setEditLeadListForm({ ...editLeadListForm, channel: event.target.value as LeadListChannel })
                  }
                >
                  <option value="both">Ambos</option>
                  <option value="email">E-mail</option>
                  <option value="whatsapp">WhatsApp</option>
                </select>
              </label>
              <TagDropdown
                allLabel="Todos os nichos"
                label="Nichos"
                options={leadNicheOptions}
                placeholder="Adicionar nicho"
                selected={selectedEditListNiches}
                onChange={setSelectedEditListNiches}
              />
              <TagDropdown
                allLabel="Todas as localidades"
                label="Localidades"
                options={leadLocationOptions}
                placeholder="Adicionar localidade"
                selected={selectedEditListLocations}
                onChange={setSelectedEditListLocations}
              />
              <label className="checkbox-label">
                <input
                  checked={editLeadListForm.only_whatsapp_validated}
                  onChange={(event) =>
                    setEditLeadListForm({ ...editLeadListForm, only_whatsapp_validated: event.target.checked })
                  }
                  type="checkbox"
                />
                Somente com WhatsApp válido
              </label>
              <label className="checkbox-label">
                <input
                  checked={editLeadListForm.only_email_opened}
                  onChange={(event) =>
                    setEditLeadListForm({ ...editLeadListForm, only_email_opened: event.target.checked })
                  }
                  type="checkbox"
                />
                Abriu algum e-mail
              </label>
              <label className="checkbox-label">
                <input
                  checked={editLeadListForm.only_email_clicked}
                  onChange={(event) =>
                    setEditLeadListForm({ ...editLeadListForm, only_email_clicked: event.target.checked })
                  }
                  type="checkbox"
                />
                Clicou em algum e-mail
              </label>
              <label>
                Combinação de engajamento
                <select
                  value={editLeadListForm.email_engagement_filter_mode}
                  onChange={(event) =>
                    setEditLeadListForm({
                      ...editLeadListForm,
                      email_engagement_filter_mode: event.target.value as "or" | "and"
                    })
                  }
                >
                  <option value="or">Abriu ou clicou</option>
                  <option value="and">Abriu e clicou</option>
                </select>
              </label>
              <label>
                Nunca recebeu template
                <select
                  value={editLeadListForm.never_received_template_id}
                  onChange={(event) =>
                    setEditLeadListForm({ ...editLeadListForm, never_received_template_id: event.target.value })
                  }
                >
                  <option value="">Ignorar</option>
                  {templates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="checkbox-label">
                <input
                  checked={editLeadListForm.only_never_emailed}
                  onChange={(event) =>
                    setEditLeadListForm({ ...editLeadListForm, only_never_emailed: event.target.checked })
                  }
                  type="checkbox"
                />
                Nunca recebeu e-mail
              </label>
            </div>

            {emailError ? <p className="error-text">{emailError}</p> : null}

            <div className="modal-actions">
              <button className="secondary-button" disabled={emailBusy} onClick={closeEditLeadListModal} type="button">
                Cancelar
              </button>
              <button className="primary-button" disabled={emailBusy} type="submit">
                {emailBusy ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
                Salvar lista
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {leadListDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir lista?</h2>
              <p className="confirm-copy">
                A lista "{leadListDeleteDialog.name}" será removida. Se alguma campanha estiver usando esta lista, o sistema pode impedir a exclusão.
              </p>
            </div>

            {emailError ? <p className="error-text">{emailError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={emailBusy}
                onClick={() => {
                  setEmailError("");
                  setLeadListDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button className="danger-button" disabled={emailBusy} onClick={confirmDeleteLeadList} type="button">
                {emailBusy ? <Loader2 className="spin" size={18} /> : <Trash2 size={18} />}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {campaignModalOpen ? (
        <div className="modal-backdrop">
          <form className="edit-modal template-modal" onSubmit={handleSaveCampaign}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Disparo controlado</p>
                <h2>{editingCampaignId ? "Editar campanha" : "Adicionar campanha"}</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => {
                  setCampaignModalOpen(false);
                  setEditingCampaignId(null);
                }}
                title="Fechar"
                type="button"
              >
                <X size={18} />
              </button>
            </div>

            <div className="edit-grid">
              <label>
                Nome
                <input value={campaignForm.name} onChange={(event) => setCampaignForm({ ...campaignForm, name: event.target.value })} />
              </label>
              <label>
                Lista
                <select value={campaignForm.list_id} onChange={(event) => setCampaignForm({ ...campaignForm, list_id: event.target.value })}>
                  <option value="">Escolha</option>
                  {emailLeadLists.map((list) => (
                    <option key={list.id} value={list.id}>
                      {list.name} · {list.lead_count} leads
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Modo de mensagem
                <select
                  value={campaignForm.message_mode}
                  onChange={(event) =>
                    setCampaignForm({ ...campaignForm, message_mode: event.target.value as EmailMessageMode })
                  }
                >
                  <option value="template">Template fixo</option>
                  <option value="ai_per_lead">Gerar individual por IA</option>
                </select>
              </label>
              {campaignForm.message_mode === "ai_per_lead" ? (
                <label>
                  Idioma da mensagem
                  <select
                    value={campaignForm.language}
                    onChange={(event) =>
                      setCampaignForm({ ...campaignForm, language: event.target.value as AiMessageLanguage })
                    }
                  >
                    {AI_MESSAGE_LANGUAGE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="wide-field">
                Objetivo da campanha
                <textarea
                  placeholder="Ex: vender sites para empresas sem site, desenvolvimento gratuito, paga só se gostar"
                  rows={3}
                  value={campaignForm.objective}
                  onChange={(event) => setCampaignForm({ ...campaignForm, objective: event.target.value })}
                />
                <span className="helper-text">
                  Obrigatório no modo IA por lead. O template selecionado continua definindo o visual do e-mail.
                </span>
              </label>
              <label>
                Delay mínimo (s)
                <input
                  min={1}
                  type="number"
                  value={campaignForm.min_delay_seconds}
                  onChange={(event) => setCampaignForm({ ...campaignForm, min_delay_seconds: Number(event.target.value) })}
                />
              </label>
              <label>
                Delay máximo (s)
                <input
                  min={1}
                  type="number"
                  value={campaignForm.max_delay_seconds}
                  onChange={(event) => setCampaignForm({ ...campaignForm, max_delay_seconds: Number(event.target.value) })}
                />
              </label>
              <label>
                Limite diário
                <input
                  min={1}
                  type="number"
                  value={campaignForm.daily_limit}
                  onChange={(event) => setCampaignForm({ ...campaignForm, daily_limit: Number(event.target.value) })}
                />
              </label>
              <label>
                Limite semanal
                <input
                  min={1}
                  type="number"
                  value={campaignForm.weekly_limit}
                  onChange={(event) => setCampaignForm({ ...campaignForm, weekly_limit: Number(event.target.value) })}
                />
              </label>
              <label>
                Janela início
                <input
                  value={campaignForm.send_window_start}
                  onChange={(event) => setCampaignForm({ ...campaignForm, send_window_start: event.target.value })}
                />
              </label>
              <label>
                Janela fim
                <input
                  value={campaignForm.send_window_end}
                  onChange={(event) => setCampaignForm({ ...campaignForm, send_window_end: event.target.value })}
                />
              </label>
              <label>
                Fuso horário
                <select
                  value={campaignForm.timezone_name}
                  onChange={(event) => setCampaignForm({ ...campaignForm, timezone_name: event.target.value })}
                >
                  {CAMPAIGN_TIMEZONES.map((timezoneOption) => (
                    <option key={timezoneOption.value} value={timezoneOption.value}>
                      {timezoneOption.label}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset className="wide-field day-picker-field">
                <legend>Dias de envio</legend>
                <div className="send-day-picker">
                  {CAMPAIGN_SEND_DAYS.map((day) => {
                    const checked = selectedCampaignSendDays.has(day.value);
                    return (
                      <label className={`send-day-option ${checked ? "active" : ""}`} key={day.value} title={day.label}>
                        <input checked={checked} onChange={() => toggleCampaignSendDay(day.value)} type="checkbox" />
                        <span>{day.shortLabel}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            </div>

            <div className="template-picker modal-template-picker">
              <p className="helper-text">
                {campaignForm.message_mode === "ai_per_lead"
                  ? "Escolha o template visual que será usado como base para cores, logomarca e estrutura do e-mail."
                  : "Escolha um ou mais templates fixos para alternar na campanha."}
              </p>
              {templates.map((template) => (
                <label className="checkbox-label" key={template.id}>
                  <input
                    checked={campaignForm.template_ids.includes(template.id)}
                    onChange={() => toggleCampaignTemplate(template.id)}
                    type="checkbox"
                  />
                  {template.name}
                </label>
              ))}
            </div>

            <p className="helper-text modal-helper">
              A janela de envio é calculada no fuso escolhido. O título e o link do conteúdo vêm de cada template selecionado.
            </p>

            <div className="modal-actions">
              <button
                className="secondary-button"
                onClick={() => {
                  setCampaignModalOpen(false);
                  setEditingCampaignId(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button className="primary-button" disabled={emailBusy} type="submit">
                {emailBusy ? <Loader2 className="spin" size={18} /> : <Megaphone size={18} />}
                {editingCampaignId ? "Salvar campanha" : "Criar campanha"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {whatsappCampaignModalOpen ? (
        <div className="modal-backdrop">
          <form className="edit-modal template-modal" onSubmit={handleSaveWhatsappCampaign}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Disparo controlado</p>
                <h2>{editingWhatsappCampaignId ? "Editar campanha" : "Adicionar campanha"}</h2>
              </div>
              <button className="icon-button" onClick={closeWhatsappCampaignModal} title="Fechar" type="button">
                <X size={18} />
              </button>
            </div>

            <div className="edit-grid">
              <label>
                Nome
                <input
                  value={whatsappCampaignForm.name}
                  onChange={(event) => {
                    setWhatsappCampaignForm({ ...whatsappCampaignForm, name: event.target.value });
                    setWhatsappCampaignFormErrors((current) => ({ ...current, name: "" }));
                  }}
                />
                {whatsappCampaignFormErrors.name ? <small className="field-error">{whatsappCampaignFormErrors.name}</small> : null}
              </label>
              <label className="wide-field">
                Objetivo da campanha
                <textarea
                  rows={3}
                  value={whatsappCampaignForm.objective}
                  onChange={(event) => {
                    setWhatsappCampaignForm({ ...whatsappCampaignForm, objective: event.target.value });
                    setWhatsappCampaignFormErrors((current) => ({ ...current, objective: "" }));
                  }}
                  placeholder="Ex: vender criação de site grátis, paga só se gostar"
                />
                {whatsappCampaignFormErrors.objective ? <small className="field-error">{whatsappCampaignFormErrors.objective}</small> : null}
              </label>
              <label>
                Modo de mensagem
                <select
                  value={whatsappCampaignForm.message_mode}
                  onChange={(event) => {
                    const messageMode = event.target.value as WhatsAppMessageMode;
                    setWhatsappCampaignForm({
                      ...whatsappCampaignForm,
                      message_mode: messageMode,
                      template_id:
                        messageMode === "ai_per_lead"
                          ? ""
                          : whatsappCampaignForm.template_id ||
                            (whatsappTemplates[0]?.id ? String(whatsappTemplates[0].id) : "")
                    });
                    setWhatsappCampaignFormErrors((current) => ({ ...current, objective: "", template_id: "" }));
                  }}
                >
                  <option value="template">Template fixo</option>
                  <option value="ai_per_lead">Gerar individual por IA</option>
                </select>
              </label>
              {whatsappCampaignForm.message_mode === "ai_per_lead" ? (
                <label>
                  Idioma da mensagem
                  <select
                    value={whatsappCampaignForm.language}
                    onChange={(event) =>
                      setWhatsappCampaignForm({
                        ...whatsappCampaignForm,
                        language: event.target.value as AiMessageLanguage
                      })
                    }
                  >
                    {AI_MESSAGE_LANGUAGE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label>
                Lista de leads
                <select
                  value={whatsappCampaignForm.list_id}
                  onChange={(event) => {
                    setWhatsappCampaignForm({ ...whatsappCampaignForm, list_id: event.target.value });
                    setWhatsappCampaignFormErrors((current) => ({ ...current, list_id: "" }));
                  }}
                >
                  <option value="">Escolha</option>
                  {whatsappLeadLists.map((list) => (
                    <option key={list.id} value={list.id}>
                      {list.name} · {list.lead_count} leads
                    </option>
                  ))}
                </select>
                {whatsappCampaignFormErrors.list_id ? <small className="field-error">{whatsappCampaignFormErrors.list_id}</small> : null}
              </label>
              <label>
                Funil do CRM
                <select
                  value={whatsappCampaignForm.funnel_id}
                  onChange={(event) => {
                    setWhatsappCampaignForm({ ...whatsappCampaignForm, funnel_id: event.target.value });
                    setWhatsappCampaignFormErrors((current) => ({ ...current, funnel_id: "" }));
                  }}
                >
                  <option value="">Funil padrão{defaultCrmFunnel ? ` · ${defaultCrmFunnel.name}` : ""}</option>
                  {crmFunnels
                    .filter((funnel) => !funnel.is_default)
                    .map((funnel) => (
                      <option key={funnel.id} value={funnel.id}>
                        {funnel.name}
                      </option>
                    ))}
                </select>
                {whatsappCampaignFormErrors.funnel_id ? <small className="field-error">{whatsappCampaignFormErrors.funnel_id}</small> : null}
              </label>
              <label>
                Instância conectada
                <select
                  value={whatsappCampaignForm.instance_id}
                  onChange={(event) => {
                    setWhatsappCampaignForm({ ...whatsappCampaignForm, instance_id: event.target.value });
                    setWhatsappCampaignFormErrors((current) => ({ ...current, instance_id: "" }));
                  }}
                >
                  <option value="">Escolha</option>
                  {connectedWhatsappInstances.map((instance) => (
                    <option key={instance.id} value={instance.id}>
                      {instance.name}
                    </option>
                  ))}
                </select>
                {whatsappCampaignFormErrors.instance_id ? <small className="field-error">{whatsappCampaignFormErrors.instance_id}</small> : null}
              </label>
              {whatsappCampaignForm.message_mode === "template" ? (
                <label>
                  Template
                  <select
                    value={whatsappCampaignForm.template_id}
                    onChange={(event) => {
                      setWhatsappCampaignForm({ ...whatsappCampaignForm, template_id: event.target.value });
                      setWhatsappCampaignFormErrors((current) => ({ ...current, template_id: "" }));
                    }}
                  >
                    <option value="">Escolha</option>
                    {whatsappTemplates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                  {whatsappCampaignFormErrors.template_id ? <small className="field-error">{whatsappCampaignFormErrors.template_id}</small> : null}
                </label>
              ) : null}
              <label>
                Delay mínimo (s)
                <input
                  min={1}
                  type="number"
                  value={whatsappCampaignForm.min_delay_seconds}
                  onChange={(event) => {
                    setWhatsappCampaignForm({ ...whatsappCampaignForm, min_delay_seconds: Number(event.target.value) });
                    setWhatsappCampaignFormErrors((current) => ({ ...current, min_delay_seconds: "", max_delay_seconds: "" }));
                  }}
                />
                {whatsappCampaignFormErrors.min_delay_seconds ? (
                  <small className="field-error">{whatsappCampaignFormErrors.min_delay_seconds}</small>
                ) : null}
              </label>
              <label>
                Delay máximo (s)
                <input
                  min={1}
                  type="number"
                  value={whatsappCampaignForm.max_delay_seconds}
                  onChange={(event) => {
                    setWhatsappCampaignForm({ ...whatsappCampaignForm, max_delay_seconds: Number(event.target.value) });
                    setWhatsappCampaignFormErrors((current) => ({ ...current, max_delay_seconds: "" }));
                  }}
                />
                {whatsappCampaignFormErrors.max_delay_seconds ? (
                  <small className="field-error">{whatsappCampaignFormErrors.max_delay_seconds}</small>
                ) : null}
              </label>
              <label>
                Limite diário
                <input
                  min={1}
                  type="number"
                  value={whatsappCampaignForm.daily_limit}
                  onChange={(event) => setWhatsappCampaignForm({ ...whatsappCampaignForm, daily_limit: Number(event.target.value) })}
                />
              </label>
              <label>
                Limite semanal
                <input
                  min={1}
                  type="number"
                  value={whatsappCampaignForm.weekly_limit}
                  onChange={(event) => setWhatsappCampaignForm({ ...whatsappCampaignForm, weekly_limit: Number(event.target.value) })}
                />
              </label>
              <label>
                Janela início
                <input
                  type="time"
                  value={whatsappCampaignForm.send_window_start}
                  onChange={(event) => setWhatsappCampaignForm({ ...whatsappCampaignForm, send_window_start: event.target.value })}
                />
              </label>
              <label>
                Janela fim
                <input
                  type="time"
                  value={whatsappCampaignForm.send_window_end}
                  onChange={(event) => setWhatsappCampaignForm({ ...whatsappCampaignForm, send_window_end: event.target.value })}
                />
              </label>
              <label className="wide-field">
                Fuso horário
                <select
                  value={whatsappCampaignForm.timezone_name}
                  onChange={(event) => setWhatsappCampaignForm({ ...whatsappCampaignForm, timezone_name: event.target.value })}
                >
                  {CAMPAIGN_TIMEZONES.map((timezoneOption) => (
                    <option key={timezoneOption.value} value={timezoneOption.value}>
                      {timezoneOption.label}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset className="wide-field day-picker-field">
                <legend>Dias de envio</legend>
                <div className="send-day-picker">
                  {CAMPAIGN_SEND_DAYS.map((day) => {
                    const checked = selectedWhatsappCampaignSendDays.has(day.value);
                    return (
                      <label className={`send-day-option ${checked ? "active" : ""}`} key={day.value} title={day.label}>
                        <input checked={checked} onChange={() => toggleWhatsappCampaignSendDay(day.value)} type="checkbox" />
                        <span>{day.shortLabel}</span>
                      </label>
                    );
                  })}
                </div>
                {whatsappCampaignFormErrors.send_days ? <small className="field-error">{whatsappCampaignFormErrors.send_days}</small> : null}
              </fieldset>
            </div>

            <div className="modal-actions">
              <button className="secondary-button" onClick={closeWhatsappCampaignModal} type="button">
                Cancelar
              </button>
              <button className="primary-button" disabled={whatsappBusyAction === "create-campaign"} type="submit">
                {whatsappBusyAction === "create-campaign" ? <Loader2 className="spin" size={18} /> : <Megaphone size={18} />}
                {editingWhatsappCampaignId ? "Salvar campanha" : "Criar campanha"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {aiModalOpen ? (
        <div className="modal-backdrop">
          <form className="edit-modal template-modal" onSubmit={handleGenerateTemplatesWithAi}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">OpenAI</p>
                <h2>Gerar templates com IA</h2>
              </div>
              <button className="icon-button" onClick={() => setAiModalOpen(false)} title="Fechar" type="button">
                <X size={18} />
              </button>
            </div>

            <div className="edit-grid">
              <label>
                Tipo
                <select
                  value={aiForm.mode}
                  onChange={(event) =>
                    setAiForm({
                      ...aiForm,
                      mode: event.target.value as AiTemplateForm["mode"],
                      count: event.target.value === "single" ? 1 : Math.max(aiForm.count, 2)
                    })
                  }
                >
                  <option value="sequence">Sequência de templates</option>
                  <option value="single">Template único</option>
                </select>
              </label>
              <label>
                Quantidade
                <input
                  disabled={aiForm.mode === "single"}
                  max={5}
                  min={1}
                  type="number"
                  value={aiForm.mode === "single" ? 1 : aiForm.count}
                  onChange={(event) => setAiForm({ ...aiForm, count: Number(event.target.value) })}
                />
              </label>
              <label>
                Nome da campanha/tema
                <input
                  placeholder="Ex.: Jobber workflow tips"
                  value={aiForm.campaign_name}
                  onChange={(event) => setAiForm({ ...aiForm, campaign_name: event.target.value })}
                />
              </label>
              <label>
                Idioma
                <select
                  value={aiForm.language}
                  onChange={(event) => setAiForm({ ...aiForm, language: event.target.value as AiEmailLanguage })}
                >
                  <option value="pt">Português</option>
                  <option value="en">Inglês</option>
                  <option value="es">Espanhol</option>
                </select>
              </label>
              <TagDropdown
                allLabel="Todos os nichos"
                label="Contexto de nichos"
                options={leadNicheOptions}
                placeholder="Adicionar nicho"
                selected={selectedAiNiches}
                onChange={setSelectedAiNiches}
              />
              <TagDropdown
                allLabel="Todas as localidades"
                label="Contexto de localidades"
                options={leadLocationOptions}
                placeholder="Adicionar localidade"
                selected={selectedAiLocations}
                onChange={setSelectedAiLocations}
              />
              <label className="wide-field">
                Objetivo
                <textarea
                  rows={3}
                  value={aiForm.objective}
                  onChange={(event) => setAiForm({ ...aiForm, objective: event.target.value })}
                />
              </label>
              <label className="wide-field">
                Tom
                <input value={aiForm.tone} onChange={(event) => setAiForm({ ...aiForm, tone: event.target.value })} />
              </label>
              <label>
                Título do conteúdo
                <input
                  placeholder="Ex.: How to automate Jobber workflows"
                  value={aiForm.content_title}
                  onChange={(event) => setAiForm({ ...aiForm, content_title: event.target.value })}
                />
              </label>
              <label>
                Link do conteúdo
                <input
                  placeholder="YouTube ou blog"
                  value={aiForm.content_link}
                  onChange={(event) => setAiForm({ ...aiForm, content_link: event.target.value })}
                />
              </label>
              <label className="wide-field">
                Logo do e-mail
                <input value={aiForm.logo_url} onChange={(event) => setAiForm({ ...aiForm, logo_url: event.target.value })} />
              </label>
              <ColorField
                label="Cor principal"
                value={aiForm.primary_color}
                onChange={(value) => setAiForm({ ...aiForm, primary_color: value })}
              />
              <ColorField
                label="Cor da fonte"
                value={aiForm.text_color}
                onChange={(value) => setAiForm({ ...aiForm, text_color: value })}
              />
              <ColorField
                label="Cor de fundo"
                value={aiForm.background_color}
                onChange={(value) => setAiForm({ ...aiForm, background_color: value })}
              />
              <label className="wide-field">
                Call to action
                <textarea
                  rows={3}
                  value={aiForm.call_to_action}
                  onChange={(event) => setAiForm({ ...aiForm, call_to_action: event.target.value })}
                />
              </label>
            </div>

            <p className="helper-text modal-helper">
              Nichos e localidades servem só como contexto para a IA. O envio real usa variáveis dinâmicas para empresa, nicho e localidade;
              o sistema também adiciona saudação, thumb do conteúdo, botão de conteúdo e CTA de resposta por e-mail.
            </p>

            <div className="modal-actions">
              <button className="secondary-button" onClick={() => setAiModalOpen(false)} type="button">
                Cancelar
              </button>
              <button className="primary-button" disabled={aiBusy} type="submit">
                {aiBusy ? <Loader2 className="spin" size={18} /> : <Sparkles size={18} />}
                Gerar e salvar
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {templateModalOpen ? (
        <div className="modal-backdrop">
          <form className="edit-modal template-modal" onSubmit={handleSaveTemplate}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">{editingTemplateId ? "Editar template" : "Novo template"}</p>
                <h2>{editingTemplateId ? templateForm.name || "Template" : "Criar template"}</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => {
                  setTemplateModalOpen(false);
                  setEditingTemplateId(null);
                }}
                title="Fechar"
                type="button"
              >
                <X size={18} />
              </button>
            </div>

            <div className="edit-grid">
              <label>
                Nome
                <input value={templateForm.name} onChange={(event) => setTemplateForm({ ...templateForm, name: event.target.value })} />
              </label>
              <label>
                Assunto
                <input
                  value={templateForm.subject}
                  onChange={(event) => setTemplateForm({ ...templateForm, subject: event.target.value })}
                />
              </label>
              <label>
                Título do conteúdo
                <input
                  placeholder="Ex.: How to automate Jobber workflows"
                  value={templateForm.content_title}
                  onChange={(event) => setTemplateForm({ ...templateForm, content_title: event.target.value })}
                />
              </label>
              <label>
                Link do conteúdo
                <input
                  placeholder="YouTube ou blog"
                  value={templateForm.content_link}
                  onChange={(event) => setTemplateForm({ ...templateForm, content_link: event.target.value })}
                />
              </label>
              <label>
                Texto do botão de conteúdo
                <input
                  placeholder="Ex.: Abrir conteúdo"
                  value={templateForm.content_button_text}
                  onChange={(event) => setTemplateForm({ ...templateForm, content_button_text: event.target.value })}
                />
              </label>
              <label>
                Assunto do e-mail de contato (mailto)
                <input
                  placeholder="Ex.: Ajuda com automação e integrações"
                  value={templateForm.contact_mailto_subject}
                  onChange={(event) => setTemplateForm({ ...templateForm, contact_mailto_subject: event.target.value })}
                />
              </label>
              <label className="wide-field">
                Corpo do e-mail de contato (mailto)
                <textarea
                  rows={3}
                  placeholder="Ex.: Oi Cleiton, vi seu e-mail sobre automação para {{company_name}} e gostaria de saber mais."
                  value={templateForm.contact_mailto_body}
                  onChange={(event) => setTemplateForm({ ...templateForm, contact_mailto_body: event.target.value })}
                />
              </label>
              <label className="wide-field">
                Logo do e-mail
                <input
                  placeholder="URL da logo"
                  value={templateForm.logo_url}
                  onChange={(event) => setTemplateForm({ ...templateForm, logo_url: event.target.value })}
                />
              </label>
              <ColorField
                label="Cor principal"
                value={templateForm.primary_color}
                onChange={(value) => setTemplateForm({ ...templateForm, primary_color: value })}
              />
              <ColorField
                label="Cor da fonte"
                value={templateForm.text_color}
                onChange={(value) => setTemplateForm({ ...templateForm, text_color: value })}
              />
              <ColorField
                label="Cor de fundo"
                value={templateForm.background_color}
                onChange={(value) => setTemplateForm({ ...templateForm, background_color: value })}
              />
              <label className="wide-field">
                HTML
                <textarea
                  rows={9}
                  value={templateForm.html}
                  onChange={(event) => setTemplateForm({ ...templateForm, html: event.target.value })}
                />
              </label>
              <label className="wide-field">
                Texto simples
                <textarea
                  rows={5}
                  value={templateForm.text}
                  onChange={(event) => setTemplateForm({ ...templateForm, text: event.target.value })}
                />
              </label>
            </div>

            <p className="helper-text modal-helper">
              Variáveis: {"{{lead_name}}"}, {"{{company_name}}"}, {"{{email}}"}, {"{{website}}"}, {"{{niche}}"},{" "}
              {"{{location}}"}, {"{{content_title}}"}, {"{{content_link}}"}, {"{{content_thumbnail_url}}"},{" "}
              {"{{content_card_block}}"}, {"{{get_in_touch_link}}"}, {"{{contact_email}}"}, {"{{logo_url}}"},{" "}
              {"{{primary_color}}"}, {"{{text_color}}"}, {"{{background_color}}"}.
            </p>

            <div className="modal-actions">
              <button
                className="secondary-button"
                onClick={() => {
                  setTemplateModalOpen(false);
                  setEditingTemplateId(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button className="primary-button" disabled={emailBusy} type="submit">
                {emailBusy ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
                {editingTemplateId ? "Salvar template" : "Criar template"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {selectedCrmLead
        ? (() => {
            const website = safeText(selectedCrmLead.website).trim();
            const websiteHref = website && !/^https?:\/\//i.test(website) ? `https://${website}` : website;
            const noteDraft = crmNoteDrafts[selectedCrmLead.id] ?? selectedCrmLead.qualification_notes ?? "";
            const crmBusy = whatsappBusyAction === `crm-${selectedCrmLead.lead_id}`;
            const crmTagBusy =
              tagBusyAction === "crm-create-tag" || tagBusyAction.startsWith(`lead-tag-${selectedCrmLead.lead_id}-`);
            const notesChanged = crmNotesChanged(selectedCrmLead);
            const selectedCrmLeadTagIds = selectedCrmLead.tags.map((tag) => tag.id);
            const currentStageOptions = selectedCrmStages.some((stage) => stage.key === selectedCrmLead.stage)
              ? selectedCrmStages
              : [
                  ...selectedCrmStages,
                  {
                    id: selectedCrmLead.stage_id,
                    funnel_id: selectedCrmLead.funnel_id,
                    key: selectedCrmLead.stage,
                    label: selectedCrmLead.stage_label || crmStageLabel(selectedCrmLead.stage, selectedCrmStages),
                    color: selectedCrmLead.stage_color || STAGE_COLOR_OPTIONS[0],
                    position: selectedCrmStages.length,
                    is_won: false,
                    is_lost: false,
                    card_count: 0
                  }
                ];

            return (
              <div className="modal-backdrop" onMouseDown={handleCrmDetailBackdropMouseDown}>
                <section className="edit-modal crm-detail-modal" role="dialog" aria-modal="true">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Lead no CRM</p>
                      <h2>{formatOptionalText(selectedCrmLead.lead_name)}</h2>
                    </div>
                    <button className="icon-button" onClick={requestCloseCrmDetailModal} title="Fechar" type="button">
                      <X size={18} />
                    </button>
                  </div>

                  <div className="crm-detail-meta">
                    <span>{selectedCrmLead.funnel_name}</span>
                    <span>{formatOptionalText(selectedCrmLead.niche)}</span>
                    <span>{formatOptionalText(selectedCrmLead.location)}</span>
                  </div>
                  {selectedCrmLead.other_funnels.length > 0 ? (
                    <div className="crm-other-funnels">
                      <span>Também está em:</span>
                      {selectedCrmLead.other_funnels.map((funnel) => (
                        <button
                          className="filter-tag all-tag"
                          key={funnel.id}
                          onClick={() => {
                            setSelectedCrmFunnelId(funnel.id);
                            setCrmDetailLeadId(null);
                          }}
                          type="button"
                        >
                          {funnel.name} · {funnel.stage_label}
                        </button>
                      ))}
                    </div>
                  ) : null}

                  <dl className="crm-detail-list">
                    <div>
                      <dt>Telefone</dt>
                      <dd>
                        <PhoneCell lead={selectedCrmLead} />
                      </dd>
                    </div>
                    <div>
                      <dt>Site</dt>
                      <dd>
                        {website ? (
                          <a href={websiteHref} target="_blank" rel="noreferrer">
                            <Globe2 size={15} />
                            {displayWebsite(website)}
                          </a>
                        ) : (
                          "-"
                        )}
                      </dd>
                    </div>
                    <div className="wide-field">
                      <dt>Última mensagem</dt>
                      <dd className="crm-detail-message">
                        <p>{formatOptionalText(selectedCrmLead.last_message)}</p>
                        <small>{formatDate(selectedCrmLead.last_message_at)}</small>
                      </dd>
                    </div>
                  </dl>

                  <section className="crm-detail-tags" aria-label="Tags do lead">
                    <div className="crm-detail-section-heading">
                      <div>
                        <p className="eyebrow">Tags</p>
                        <h3>Classificação do lead</h3>
                      </div>
                      <TagPills tags={selectedCrmLead.tags} emptyLabel="Sem tags" />
                    </div>

                    <TagCheckboxGrid
                      disabled={crmTagBusy}
                      onToggle={(tagId, checked) => toggleLeadTag(selectedCrmLead.lead_id, tagId, checked)}
                      selectedIds={selectedCrmLeadTagIds}
                      tags={tags}
                    />

                    <form className="inline-tag-form" onSubmit={handleCreateCrmInlineTag}>
                      <input
                        placeholder="Nova tag"
                        value={crmInlineTagForm.name}
                        onChange={(event) => setCrmInlineTagForm({ ...crmInlineTagForm, name: event.target.value })}
                      />
                      <div className="tag-color-options compact-tag-color-options" aria-label="Cor da nova tag">
                        {TAG_COLOR_OPTIONS.map((color) => (
                          <button
                            aria-label={`Usar cor ${color}`}
                            className={`tag-color-option ${normalizeTagColor(crmInlineTagForm.color) === color ? "active" : ""}`}
                            key={color}
                            onClick={() => setCrmInlineTagForm({ ...crmInlineTagForm, color })}
                            style={{ background: color }}
                            type="button"
                          />
                        ))}
                      </div>
                      <button className="secondary-button compact-button" disabled={crmTagBusy} type="submit">
                        {tagBusyAction === "crm-create-tag" ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
                        Criar tag
                      </button>
                    </form>
                  </section>

                  <label className="crm-stage-control">
                    Estágio
                    <select
                      disabled={crmBusy}
                      value={selectedCrmLead.stage}
                      onChange={(event) => handleCrmStageChange(selectedCrmLead, event.target.value)}
                    >
                      {currentStageOptions.map((stageOption) => (
                        <option key={stageOption.key} value={stageOption.key}>
                          {stageOption.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="crm-notes-control">
                    Notas
                    <textarea
                      rows={5}
                      value={noteDraft}
                      onChange={(event) => handleCrmNoteChange(selectedCrmLead.id, event.target.value)}
                    />
                  </label>

                  <div className="modal-actions">
                    <button className="secondary-button" onClick={requestCloseCrmDetailModal} type="button">
                      Fechar
                    </button>
                    <button
                      className="primary-button"
                      disabled={crmBusy || !notesChanged}
                      onClick={() => saveCrmNotes(selectedCrmLead)}
                      type="button"
                    >
                      {crmBusy ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
                      Salvar notas
                    </button>
                  </div>
                </section>
              </div>
            );
          })()
        : null}

      {funnelManagerOpen ? (
        <div className="modal-backdrop">
          <section className="edit-modal funnel-manager-modal" role="dialog" aria-modal="true">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Funis do CRM</p>
                <h2>Gerenciar funis</h2>
              </div>
              <button className="icon-button" onClick={closeFunnelManager} title="Fechar" type="button">
                <X size={18} />
              </button>
            </div>

            {funnelError ? <div className="notice danger modal-helper">{funnelError}</div> : null}
            {funnelMessage ? <div className="notice success modal-helper">{funnelMessage}</div> : null}

            <div className="funnel-manager-layout">
              <form className="tag-manager-form" onSubmit={handleSaveFunnel}>
                <div className="panel-heading compact-heading">
                  <div>
                    <p className="eyebrow">{editingFunnelId ? "Editar" : "Novo funil"}</p>
                    <h3>{editingFunnelId ? "Atualizar funil" : "Criar funil"}</h3>
                  </div>
                </div>
                <label>
                  Nome
                  <input
                    value={funnelForm.name}
                    onChange={(event) => setFunnelForm({ ...funnelForm, name: event.target.value })}
                    placeholder="Ex: Vendas inbound"
                  />
                </label>
                <label>
                  Descrição
                  <textarea
                    rows={3}
                    value={funnelForm.description}
                    onChange={(event) => setFunnelForm({ ...funnelForm, description: event.target.value })}
                    placeholder="Opcional"
                  />
                </label>
                <div className="modal-actions tag-form-actions">
                  {editingFunnelId ? (
                    <button className="secondary-button" disabled={Boolean(funnelBusyAction)} onClick={cancelEditFunnel} type="button">
                      Cancelar edição
                    </button>
                  ) : null}
                  <button className="primary-button" disabled={Boolean(funnelBusyAction)} type="submit">
                    {funnelBusyAction === "create-funnel" || funnelBusyAction.startsWith("save-funnel-") ? (
                      <Loader2 className="spin" size={18} />
                    ) : (
                      <Save size={18} />
                    )}
                    {editingFunnelId ? "Salvar funil" : "Criar funil"}
                  </button>
                </div>
              </form>

              <div className="funnel-manager-list">
                {crmFunnels.length === 0 ? <p className="empty-state">Nenhum funil carregado.</p> : null}
                {crmFunnels.map((funnel) => (
                  <article
                    className={`funnel-manager-row ${selectedCrmFunnel?.id === funnel.id ? "active" : ""}`}
                    key={funnel.id}
                  >
                    <button
                      className="funnel-pick-button"
                      disabled={Boolean(funnelBusyAction)}
                      onClick={() => {
                        setSelectedCrmFunnelId(funnel.id);
                        setEditingStageId(null);
                        setStageForm(defaultStageForm);
                      }}
                      type="button"
                    >
                      <strong>{funnel.name}</strong>
                      <span>
                        {funnel.card_count} cards · {funnel.stages.length} estágios
                      </span>
                      {funnel.is_default ? <small>Funil padrão</small> : null}
                    </button>
                    <div className="row-actions">
                      <button
                        className="icon-button"
                        disabled={Boolean(funnelBusyAction)}
                        onClick={() => startEditFunnel(funnel)}
                        title="Editar funil"
                        type="button"
                      >
                        <Edit3 size={16} />
                      </button>
                      <button
                        className="icon-button danger"
                        disabled={Boolean(funnelBusyAction) || funnel.is_default}
                        onClick={() => requestDeleteFunnel(funnel)}
                        title={funnel.is_default ? "O funil padrão não pode ser excluído" : "Excluir funil"}
                        type="button"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </article>
                ))}
              </div>

              <section className="stage-manager-panel">
                <div className="panel-heading compact-heading">
                  <div>
                    <p className="eyebrow">Estágios</p>
                    <h3>{selectedCrmFunnel ? selectedCrmFunnel.name : "Selecione um funil"}</h3>
                  </div>
                </div>

                <div className="stage-manager-grid">
                  <form className="tag-manager-form" onSubmit={handleSaveStage}>
                    <div className="panel-heading compact-heading">
                      <div>
                        <p className="eyebrow">{editingStageId ? "Editar" : "Novo estágio"}</p>
                        <h3>{editingStageId ? "Atualizar estágio" : "Criar estágio"}</h3>
                      </div>
                    </div>
                    <label>
                      Nome
                      <input
                        disabled={!selectedCrmFunnel}
                        value={stageForm.label}
                        onChange={(event) => setStageForm({ ...stageForm, label: event.target.value })}
                        placeholder="Ex: Proposta enviada"
                      />
                    </label>
                    <div className="tag-color-field">
                      <span>Cor</span>
                      <div className="tag-color-options">
                        {STAGE_COLOR_OPTIONS.map((color) => (
                          <button
                            aria-label={`Usar cor ${color}`}
                            className={`tag-color-option ${normalizeStageColor(stageForm.color) === color ? "active" : ""}`}
                            disabled={!selectedCrmFunnel}
                            key={color}
                            onClick={() => setStageForm({ ...stageForm, color })}
                            style={{ background: color }}
                            type="button"
                          />
                        ))}
                      </div>
                    </div>
                    <div className="stage-terminal-controls">
                      <label className="checkbox-label">
                        <input
                          checked={stageForm.is_won}
                          disabled={!selectedCrmFunnel}
                          onChange={(event) =>
                            setStageForm({
                              ...stageForm,
                              is_won: event.target.checked,
                              is_lost: event.target.checked ? false : stageForm.is_lost
                            })
                          }
                          type="checkbox"
                        />
                        Ganho
                      </label>
                      <label className="checkbox-label">
                        <input
                          checked={stageForm.is_lost}
                          disabled={!selectedCrmFunnel}
                          onChange={(event) =>
                            setStageForm({
                              ...stageForm,
                              is_lost: event.target.checked,
                              is_won: event.target.checked ? false : stageForm.is_won
                            })
                          }
                          type="checkbox"
                        />
                        Perda
                      </label>
                    </div>
                    <div className="modal-actions tag-form-actions">
                      {editingStageId ? (
                        <button className="secondary-button" disabled={Boolean(funnelBusyAction)} onClick={cancelEditStage} type="button">
                          Cancelar edição
                        </button>
                      ) : null}
                      <button className="primary-button" disabled={Boolean(funnelBusyAction) || !selectedCrmFunnel} type="submit">
                        {funnelBusyAction === "create-stage" || funnelBusyAction.startsWith("save-stage-") ? (
                          <Loader2 className="spin" size={18} />
                        ) : (
                          <Save size={18} />
                        )}
                        {editingStageId ? "Salvar estágio" : "Criar estágio"}
                      </button>
                    </div>
                  </form>

                  <div className="stage-manager-list">
                    <DndContext
                      collisionDetection={closestCorners}
                      onDragCancel={handleFunnelStageDragCancel}
                      onDragEnd={handleFunnelStageDragEnd}
                      onDragStart={handleFunnelStageDragStart}
                      sensors={crmDndSensors}
                    >
                      <SortableContext
                        items={selectedCrmStages.map((stage) => funnelStageDragId(stage.id))}
                        strategy={verticalListSortingStrategy}
                      >
                        {selectedCrmStages.length === 0 ? <p className="empty-state">Nenhum estágio criado.</p> : null}
                        {selectedCrmStages.map((stage) => (
                          <SortableFunnelStageRow
                            disabled={Boolean(funnelBusyAction)}
                            key={stage.id}
                            onDelete={() => requestDeleteStage(stage)}
                            onEdit={() => startEditStage(stage)}
                            stage={stage}
                          />
                        ))}
                      </SortableContext>
                      <DragOverlay>
                        {activeFunnelStage ? (
                          <article className="stage-manager-row stage-drag-overlay">
                            <div className="stage-manager-main">
                              <div>
                                <span className="stage-color-dot" style={stageStyle(activeFunnelStage)} />
                                <strong>{activeFunnelStage.label}</strong>
                              </div>
                              <small>{activeFunnelStage.card_count} cards</small>
                            </div>
                          </article>
                        ) : null}
                      </DragOverlay>
                    </DndContext>
                  </div>
                </div>
              </section>
            </div>
          </section>
        </div>
      ) : null}

      {funnelDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir funil?</h2>
              <p className="confirm-copy">
                O funil "{funnelDeleteDialog.name}" será excluído.
                {funnelDeleteDialog.card_count > 0 ? ` ${funnelDeleteDialog.card_count} cards precisam ser movidos.` : ""}
              </p>
            </div>

            {funnelDeleteDialog.card_count > 0 ? (
              <label className="modal-helper">
                Mover cards para
                <select value={funnelDeleteMoveToId} onChange={(event) => setFunnelDeleteMoveToId(event.target.value)}>
                  <option value="">Escolha um funil</option>
                  {crmFunnels
                    .filter((funnel) => funnel.id !== funnelDeleteDialog.id)
                    .map((funnel) => (
                      <option key={funnel.id} value={funnel.id}>
                        {funnel.name}
                      </option>
                    ))}
                </select>
              </label>
            ) : null}

            {funnelError ? <p className="error-text">{funnelError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={funnelBusyAction === `delete-funnel-${funnelDeleteDialog.id}`}
                onClick={() => {
                  setFunnelError("");
                  setFunnelDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="danger-button"
                disabled={funnelBusyAction === `delete-funnel-${funnelDeleteDialog.id}`}
                onClick={confirmDeleteFunnel}
                type="button"
              >
                {funnelBusyAction === `delete-funnel-${funnelDeleteDialog.id}` ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <Trash2 size={18} />
                )}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {stageDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir estágio?</h2>
              <p className="confirm-copy">
                O estágio "{stageDeleteDialog.label}" será excluído.
                {stageDeleteDialog.card_count > 0 ? ` ${stageDeleteDialog.card_count} cards precisam ser movidos.` : ""}
              </p>
            </div>

            {stageDeleteDialog.card_count > 0 ? (
              <label className="modal-helper">
                Mover cards para
                <select value={stageDeleteMoveToId} onChange={(event) => setStageDeleteMoveToId(event.target.value)}>
                  <option value="">Escolha um estágio</option>
                  {selectedCrmStages
                    .filter((stage) => stage.id !== stageDeleteDialog.id)
                    .map((stage) => (
                      <option key={stage.id} value={stage.id}>
                        {stage.label}
                      </option>
                    ))}
                </select>
              </label>
            ) : null}

            {funnelError ? <p className="error-text">{funnelError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={funnelBusyAction === `delete-stage-${stageDeleteDialog.id}`}
                onClick={() => {
                  setFunnelError("");
                  setStageDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="danger-button"
                disabled={funnelBusyAction === `delete-stage-${stageDeleteDialog.id}`}
                onClick={confirmDeleteStage}
                type="button"
              >
                {funnelBusyAction === `delete-stage-${stageDeleteDialog.id}` ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <Trash2 size={18} />
                )}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {tagManagerOpen ? (
        <div className="modal-backdrop">
          <section className="edit-modal tag-manager-modal" role="dialog" aria-modal="true">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Tags globais</p>
                <h2>Gerenciar tags</h2>
              </div>
              <button className="icon-button" onClick={closeTagManager} title="Fechar" type="button">
                <X size={18} />
              </button>
            </div>

            {tagError ? <div className="notice danger modal-helper">{tagError}</div> : null}
            {tagMessage ? <div className="notice success modal-helper">{tagMessage}</div> : null}

            <div className="tag-manager-layout">
              <form className="tag-manager-form" onSubmit={handleSaveTag}>
                <div className="panel-heading compact-heading">
                  <div>
                    <p className="eyebrow">{editingTagId ? "Editar" : "Nova tag"}</p>
                    <h3>{editingTagId ? "Atualizar tag" : "Criar tag"}</h3>
                  </div>
                </div>
                <label>
                  Nome
                  <input
                    value={tagForm.name}
                    onChange={(event) => setTagForm({ ...tagForm, name: event.target.value })}
                    placeholder="Ex: Usa Bling"
                  />
                </label>
                <label>
                  Descrição
                  <textarea
                    rows={3}
                    value={tagForm.description}
                    onChange={(event) => setTagForm({ ...tagForm, description: event.target.value })}
                    placeholder="Opcional"
                  />
                </label>
                <div className="tag-color-field">
                  <span>Cor</span>
                  <div className="tag-color-options">
                    {TAG_COLOR_OPTIONS.map((color) => (
                      <button
                        aria-label={`Usar cor ${color}`}
                        className={`tag-color-option ${normalizeTagColor(tagForm.color) === color ? "active" : ""}`}
                        key={color}
                        onClick={() => setTagForm({ ...tagForm, color })}
                        style={{ background: color }}
                        type="button"
                      />
                    ))}
                  </div>
                </div>
                <div className="modal-actions tag-form-actions">
                  {editingTagId ? (
                    <button className="secondary-button" disabled={Boolean(tagBusyAction)} onClick={cancelEditTag} type="button">
                      Cancelar edição
                    </button>
                  ) : null}
                  <button className="primary-button" disabled={Boolean(tagBusyAction)} type="submit">
                    {tagBusyAction === "create-tag" || tagBusyAction.startsWith("save-tag-") ? (
                      <Loader2 className="spin" size={18} />
                    ) : (
                      <Save size={18} />
                    )}
                    {editingTagId ? "Salvar tag" : "Criar tag"}
                  </button>
                </div>
              </form>

              <div className="tag-manager-list">
                {tags.length === 0 ? <p className="empty-state">Nenhuma tag criada ainda.</p> : null}
                {tags.map((tag) => (
                  <article className="tag-manager-row" key={tag.id}>
                    <div className="tag-manager-main">
                      <span className="lead-tag-pill" style={tagStyle(tag)}>
                        {tag.name}
                      </span>
                      {tag.description ? <p>{tag.description}</p> : null}
                      <small>{tag.lead_count} leads</small>
                    </div>
                    <div className="row-actions">
                      <button
                        className="icon-button"
                        disabled={Boolean(tagBusyAction)}
                        onClick={() => startEditTag(tag)}
                        title="Editar tag"
                        type="button"
                      >
                        <Edit3 size={16} />
                      </button>
                      <button
                        className="icon-button danger"
                        disabled={Boolean(tagBusyAction)}
                        onClick={() => requestDeleteTag(tag)}
                        title="Excluir tag"
                        type="button"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </section>
        </div>
      ) : null}

      {tagDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir tag?</h2>
              <p className="confirm-copy">
                A tag "{tagDeleteDialog.name}" será removida de {tagDeleteDialog.lead_count} leads.
              </p>
            </div>

            {tagError ? <p className="error-text">{tagError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={tagBusyAction === `delete-tag-${tagDeleteDialog.id}`}
                onClick={() => {
                  setTagError("");
                  setTagDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="danger-button"
                disabled={tagBusyAction === `delete-tag-${tagDeleteDialog.id}`}
                onClick={confirmDeleteTag}
                type="button"
              >
                {tagBusyAction === `delete-tag-${tagDeleteDialog.id}` ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <Trash2 size={18} />
                )}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {manualLeadOpen ? (
        <div className="modal-backdrop">
          <form className="edit-modal" onSubmit={handleCreateManualLead}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Cadastro manual</p>
                <h2>Adicionar lead</h2>
              </div>
              <button className="icon-button" onClick={closeManualLeadModal} title="Fechar" type="button">
                <X size={18} />
              </button>
            </div>

            <div className="edit-grid">
              <label>
                Nome da empresa
                <input
                  required
                  value={manualLeadForm.name}
                  onChange={(event) => setManualLeadForm({ ...manualLeadForm, name: event.target.value })}
                />
              </label>
              <label>
                Nicho
                <input
                  required
                  value={manualLeadForm.niche}
                  onChange={(event) => setManualLeadForm({ ...manualLeadForm, niche: event.target.value })}
                />
              </label>
              <label>
                Localidade
                <input
                  required
                  value={manualLeadForm.location}
                  onChange={(event) => setManualLeadForm({ ...manualLeadForm, location: event.target.value })}
                />
              </label>
              <label>
                Telefone
                <input
                  value={manualLeadForm.phone}
                  onChange={(event) => setManualLeadForm({ ...manualLeadForm, phone: event.target.value })}
                />
              </label>
              <label>
                Site
                <input
                  placeholder="https://empresa.com"
                  value={manualLeadForm.website}
                  onChange={(event) => setManualLeadForm({ ...manualLeadForm, website: event.target.value })}
                />
              </label>
              <label>
                E-mail
                <input
                  type="email"
                  value={manualLeadForm.email}
                  onChange={(event) => setManualLeadForm({ ...manualLeadForm, email: event.target.value })}
                />
              </label>
              <label className="wide-field">
                Endereço
                <input
                  value={manualLeadForm.address}
                  onChange={(event) => setManualLeadForm({ ...manualLeadForm, address: event.target.value })}
                />
              </label>
            </div>

            {actionError ? <p className="error-text">{actionError}</p> : null}

            <div className="modal-actions">
              <button className="secondary-button" onClick={closeManualLeadModal} type="button">
                Cancelar
              </button>
              <button className="primary-button" disabled={savingManualLead} type="submit">
                {savingManualLead ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
                Salvar lead
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {editingLead ? (
        <div className="modal-backdrop">
          <form className="edit-modal" onSubmit={handleSaveLead}>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Editar lead</p>
                <h2>{editingLead.name}</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => {
                  setActionError("");
                  setEditingLead(null);
                }}
                title="Fechar"
                type="button"
              >
                <X size={18} />
              </button>
            </div>

            <div className="edit-grid">
              <label>
                Nome
                <input
                  value={editingLead.name}
                  onChange={(event) => setEditingLead({ ...editingLead, name: event.target.value })}
                />
              </label>
              <label>
                Nicho
                <input
                  value={editingLead.niche}
                  onChange={(event) => setEditingLead({ ...editingLead, niche: event.target.value })}
                />
              </label>
              <label>
                Localidade
                <input
                  value={editingLead.location}
                  onChange={(event) => setEditingLead({ ...editingLead, location: event.target.value })}
                />
              </label>
              <label>
                Telefone
                <input
                  value={safeText(editingLead.phone)}
                  onChange={(event) => setEditingLead({ ...editingLead, phone: event.target.value })}
                />
              </label>
              <label>
                Site
                <input
                  value={editingLead.website || ""}
                  onChange={(event) => setEditingLead({ ...editingLead, website: event.target.value })}
                />
              </label>
              <label>
                E-mail
                <input
                  value={editingLead.email}
                  onChange={(event) => setEditingLead({ ...editingLead, email: event.target.value })}
                />
              </label>
              <label className="wide-field">
                Endereço
                <input
                  value={editingLead.address}
                  onChange={(event) => setEditingLead({ ...editingLead, address: event.target.value })}
                />
              </label>
            </div>

            {actionError ? <p className="error-text">{actionError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                onClick={() => {
                  setActionError("");
                  setEditingLead(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button className="primary-button" disabled={savingEdit} type="submit">
                {savingEdit ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
                Salvar
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {leadWhatsappValidationDialogOpen ? (
        <div className="modal-backdrop">
          <section className="confirm-modal" style={{ width: "min(680px, 100%)" }}>
            <div className="confirm-icon start-confirm-icon">
              <ShieldCheck size={22} />
            </div>
            <div>
              <p className="eyebrow">Validar WhatsApp</p>
              <h2>Confirmar validação dos leads?</h2>
              <p className="confirm-copy">
                Confira o escopo e a prévia antes de iniciar o lote na instância conectada.
              </p>
            </div>

            <div className="modal-helper" style={{ display: "grid", gap: 10 }}>
              {selectedIds.length > 0 ? (
                <label className="checkbox-label">
                  <input
                    checked={leadWhatsappValidationScope === "selected"}
                    onChange={() => setLeadWhatsappValidationScope("selected")}
                    type="radio"
                  />
                  {selectedIds.length === 1
                    ? "Apenas 1 lead selecionado"
                    : `Apenas os ${selectedIds.length} leads selecionados`}
                </label>
              ) : null}
              <label className="checkbox-label">
                <input
                  checked={leadWhatsappValidationScope === "filters"}
                  onChange={() => setLeadWhatsappValidationScope("filters")}
                  type="radio"
                />
                Todos os leads que correspondem aos filtros atuais
              </label>
              <label className="checkbox-label">
                <input
                  checked={leadWhatsappValidationRevalidate}
                  onChange={(event) => setLeadWhatsappValidationRevalidate(event.target.checked)}
                  type="checkbox"
                />
                Revalidar leads já validados
              </label>
              <p className="confirm-copy" style={{ marginTop: 0 }}>
                Com esta opção desmarcada, apenas leads nunca validados e os que ficaram com resultado indeterminado serão processados.
              </p>
            </div>

            {leadWhatsappValidationFilterScopeNotice ? (
              <div className="notice warning modal-helper">{leadWhatsappValidationFilterScopeNotice}</div>
            ) : null}

            {leadWhatsappValidationPreviewLoading ? (
              <div className="notice warning modal-helper">
                <Loader2 className="spin" size={16} /> Carregando prévia da validação...
              </div>
            ) : null}

            {leadWhatsappValidationPreviewError ? (
              <p className="error-text modal-helper">{leadWhatsappValidationPreviewError}</p>
            ) : null}

            {leadWhatsappValidationPreview ? (
              <>
                <div className="template-stats-list modal-helper">
                  <article className="template-stat-row">
                    <span>Nunca validados</span>
                    <strong>{leadWhatsappValidationPreview.never_validated}</strong>
                  </article>
                  <article className="template-stat-row">
                    <span>Já válidos</span>
                    <strong>{leadWhatsappValidationPreview.valid}</strong>
                  </article>
                  <article className="template-stat-row">
                    <span>Já inválidos</span>
                    <strong>{leadWhatsappValidationPreview.invalid}</strong>
                  </article>
                  <article className="template-stat-row">
                    <span>Indeterminados</span>
                    <strong>{leadWhatsappValidationPreview.unknown}</strong>
                  </article>
                  <article className="template-stat-row">
                    <span>Sem telefone</span>
                    <strong>{leadWhatsappValidationPreview.without_phone}</strong>
                  </article>
                  <article className="template-stat-row">
                    <span>Total no escopo</span>
                    <strong>{leadWhatsappValidationPreview.total_leads}</strong>
                  </article>
                </div>
                <div className="notice warning modal-helper">
                  <strong>{leadWhatsappValidationPreview.eligible_now} leads serão processados agora.</strong>
                  {" "}Cada lead consome uma consulta na instância do WhatsApp, e lotes grandes podem levar tempo e gerar limitação no número. Duração estimada: {leadWhatsappValidationEstimatedDuration}.
                </div>
              </>
            ) : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={leadWhatsappValidationSubmitting}
                onClick={closeLeadWhatsappValidationDialog}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="primary-button"
                disabled={
                  leadWhatsappValidationPreviewLoading ||
                  leadWhatsappValidationSubmitting ||
                  !leadWhatsappValidationPreview ||
                  leadWhatsappValidationPreview.eligible_now <= 0
                }
                onClick={confirmLeadWhatsappValidation}
                type="button"
              >
                {leadWhatsappValidationSubmitting ? <Loader2 className="spin" size={18} /> : <ShieldCheck size={18} />}
                Iniciar validação
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {leadTagBulkDialog
        ? (() => {
            const isRemove = leadTagBulkDialog.action === "remove";
            const title = isRemove ? "Remover tags dos leads?" : "Aplicar tags aos leads?";
            const actionText = isRemove ? "Remover tags" : "Aplicar tags";
            return (
              <div className="modal-backdrop">
                <section className="confirm-modal tag-bulk-modal">
                  <div className={`confirm-icon ${isRemove ? "" : "start-confirm-icon"}`}>
                    {isRemove ? <X size={22} /> : <Tags size={22} />}
                  </div>
                  <div>
                    <p className="eyebrow">Ação em lote</p>
                    <h2>{title}</h2>
                    <p className="confirm-copy">
                      {leadTagBulkDialog.ids.length} leads selecionados serão atualizados.
                    </p>
                  </div>

                  <div className="modal-helper">
                    <TagCheckboxGrid
                      disabled={leadTagBulkSaving}
                      onToggle={(tagId) => setLeadTagBulkTagIds((current) => toggleNumberSelection(current, tagId))}
                      selectedIds={leadTagBulkTagIds}
                      tags={tags}
                    />
                  </div>

                  {leadTagBulkError ? <p className="error-text">{leadTagBulkError}</p> : null}

                  <div className="modal-actions">
                    <button className="secondary-button" disabled={leadTagBulkSaving} onClick={closeLeadTagBulkDialog} type="button">
                      Cancelar
                    </button>
                    <button
                      className={isRemove ? "danger-button" : "primary-button"}
                      disabled={leadTagBulkSaving || tags.length === 0}
                      onClick={confirmLeadTagBulk}
                      type="button"
                    >
                      {leadTagBulkSaving ? <Loader2 className="spin" size={18} /> : isRemove ? <X size={18} /> : <Tags size={18} />}
                      {actionText}
                    </button>
                  </div>
                </section>
              </div>
            );
          })()
        : null}

      {deleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>
                {deleteDialog.kind === "single"
                  ? "Excluir este lead?"
                  : `Excluir ${deleteDialog.ids.length} leads selecionados?`}
              </h2>
              <p className="confirm-copy">
                {deleteDialog.kind === "single"
                  ? `${deleteDialog.lead.name} será removido da base.`
                  : "Os registros selecionados serão removidos da base."}
              </p>
            </div>

            {actionError ? <p className="error-text">{actionError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={deleting}
                onClick={() => {
                  setActionError("");
                  setDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button className="danger-button" disabled={deleting} onClick={confirmDelete} type="button">
                {deleting ? <Loader2 className="spin" size={18} /> : <Trash2 size={18} />}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {templateDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir template?</h2>
              <p className="confirm-copy">
                O template "{templateDeleteDialog.name}" será removido da biblioteca. Se alguma campanha estiver usando este template, o sistema pode impedir a exclusão.
              </p>
            </div>

            {emailError ? <p className="error-text">{emailError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={emailBusy}
                onClick={() => {
                  setEmailError("");
                  setTemplateDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button className="danger-button" disabled={emailBusy} onClick={confirmDeleteTemplate} type="button">
                {emailBusy ? <Loader2 className="spin" size={18} /> : <Trash2 size={18} />}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {campaignDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir campanha?</h2>
              <p className="confirm-copy">
                A campanha "{campaignDeleteDialog.name}" será removida junto com a fila e o histórico de envios dela.
              </p>
            </div>

            {emailError ? <p className="error-text">{emailError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={emailBusy}
                onClick={() => {
                  setEmailError("");
                  setCampaignDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button className="danger-button" disabled={emailBusy} onClick={confirmDeleteCampaign} type="button">
                {emailBusy ? <Loader2 className="spin" size={18} /> : <Trash2 size={18} />}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {whatsappQrModal ? (
        <div className="modal-backdrop">
          <section className="edit-modal whatsapp-qr-modal">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Conexão</p>
                <h2>{whatsappQrModal.instance.name}</h2>
              </div>
              <button className="icon-button" onClick={() => setWhatsappQrModal(null)} title="Fechar" type="button">
                <X size={18} />
              </button>
            </div>

            <div className="qr-status-row">
              <span className={`status-pill ${whatsappQrModal.instance.status}`}>
                {whatsappInstanceStatusLabel(whatsappQrModal.instance.status)}
              </span>
              <span className="muted-count">{formatOptionalText(whatsappQrModal.instance.phone_number)}</span>
            </div>

            <div className="qr-frame">
              {whatsappQrImageSrc(whatsappQrModal.qrCode) ? (
                <img src={whatsappQrImageSrc(whatsappQrModal.qrCode)} alt="QR Code da instância de WhatsApp" />
              ) : whatsappQrModal.qrCode.url ? (
                <img src={whatsappQrModal.qrCode.url} alt="QR Code da instância de WhatsApp" />
              ) : whatsappQrModal.qrCode.code ? (
                <pre className="qr-code-text">{whatsappQrModal.qrCode.code}</pre>
              ) : (
                <p className="empty-state">QR Code indisponível no retorno da Evolution API.</p>
              )}
            </div>

            {whatsappError ? <p className="error-text">{whatsappError}</p> : null}

            <div className="modal-actions">
              <button className="secondary-button" onClick={() => setWhatsappQrModal(null)} type="button">
                Fechar
              </button>
              <button
                className="primary-button"
                disabled={whatsappBusyAction === `status-${whatsappQrModal.instance.id}`}
                onClick={() => handleRefreshWhatsappInstanceStatus(whatsappQrModal.instance.id)}
                type="button"
              >
                {whatsappBusyAction === `status-${whatsappQrModal.instance.id}` ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <RefreshCw size={18} />
                )}
                Atualizar status
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {whatsappInstanceDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir instância?</h2>
              <p className="confirm-copy">
                A instância "{whatsappInstanceDeleteDialog.name}" será removida do painel e desconectada na Evolution API quando disponível.
              </p>
            </div>

            {whatsappError ? <p className="error-text">{whatsappError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={whatsappBusyAction === `delete-instance-${whatsappInstanceDeleteDialog.id}`}
                onClick={() => {
                  setWhatsappError("");
                  setWhatsappInstanceDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="danger-button"
                disabled={whatsappBusyAction === `delete-instance-${whatsappInstanceDeleteDialog.id}`}
                onClick={confirmDeleteWhatsappInstance}
                type="button"
              >
                {whatsappBusyAction === `delete-instance-${whatsappInstanceDeleteDialog.id}` ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <Trash2 size={18} />
                )}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {whatsappTemplateDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir template?</h2>
              <p className="confirm-copy">
                O template "{whatsappTemplateDeleteDialog.name}" será removido da biblioteca. Campanhas que usam esse template podem impedir a exclusão.
              </p>
            </div>

            {whatsappError ? <p className="error-text">{whatsappError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={whatsappBusyAction === `delete-template-${whatsappTemplateDeleteDialog.id}`}
                onClick={() => {
                  setWhatsappError("");
                  setWhatsappTemplateDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="danger-button"
                disabled={whatsappBusyAction === `delete-template-${whatsappTemplateDeleteDialog.id}`}
                onClick={confirmDeleteWhatsappTemplate}
                type="button"
              >
                {whatsappBusyAction === `delete-template-${whatsappTemplateDeleteDialog.id}` ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <Trash2 size={18} />
                )}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {whatsappCampaignStartDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon start-confirm-icon">
              <Play size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar início</p>
              <h2>Iniciar campanha?</h2>
              <p className="confirm-copy">
                A campanha "{whatsappCampaignStartDialog.name}" começará a enviar mensagens reais pela instância selecionada.
              </p>
            </div>

            {whatsappError ? <p className="error-text">{whatsappError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={whatsappBusyAction === `start-campaign-${whatsappCampaignStartDialog.id}`}
                onClick={() => {
                  setWhatsappError("");
                  setWhatsappCampaignStartDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="primary-button"
                disabled={whatsappBusyAction === `start-campaign-${whatsappCampaignStartDialog.id}`}
                onClick={confirmStartWhatsappCampaign}
                type="button"
              >
                {whatsappBusyAction === `start-campaign-${whatsappCampaignStartDialog.id}` ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <Play size={18} />
                )}
                Iniciar
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {whatsappCampaignDeleteDialog ? (
        <div className="modal-backdrop">
          <section className="confirm-modal">
            <div className="confirm-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <p className="eyebrow">Confirmar exclusão</p>
              <h2>Excluir campanha?</h2>
              <p className="confirm-copy">
                A campanha "{whatsappCampaignDeleteDialog.name}" será removida junto com a fila de envios dela.
              </p>
            </div>

            {whatsappError ? <p className="error-text">{whatsappError}</p> : null}

            <div className="modal-actions">
              <button
                className="secondary-button"
                disabled={whatsappBusyAction === `delete-campaign-${whatsappCampaignDeleteDialog.id}`}
                onClick={() => {
                  setWhatsappError("");
                  setWhatsappCampaignDeleteDialog(null);
                }}
                type="button"
              >
                Cancelar
              </button>
              <button
                className="danger-button"
                disabled={whatsappBusyAction === `delete-campaign-${whatsappCampaignDeleteDialog.id}`}
                onClick={confirmDeleteWhatsappCampaign}
                type="button"
              >
                {whatsappBusyAction === `delete-campaign-${whatsappCampaignDeleteDialog.id}` ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <Trash2 size={18} />
                )}
                Excluir
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
