"use client";

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
  MousePointerClick,
  Pause,
  Play,
  Plus,
  Save,
  Search,
  Send,
  Settings,
  ShieldCheck,
  SkipForward,
  Sparkles,
  Trash2,
  X
} from "lucide-react";
import type { FormEvent } from "react";
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

type Lead = {
  id: number;
  run_id: number;
  niche: string;
  location: string;
  name: string;
  address: string;
  phone: string;
  website: string;
  email: string;
  created_at: string;
};

type DeleteDialog = { kind: "single"; lead: Lead } | { kind: "bulk"; ids: number[] } | null;

type AppView = "dashboard" | "search" | "leads" | "templates" | "lists" | "campaigns" | "history" | "settings";

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
  language: string;
  logo_url: string;
  primary_color: string;
  text_color: string;
  background_color: string;
};

type LeadList = {
  id: number;
  name: string;
  niche_filter: string;
  location_filter: string;
  search_run_id: number | null;
  only_never_emailed: boolean;
  never_received_template_id: number | null;
  lead_count: number;
};

type EmailCampaign = {
  id: number;
  name: string;
  list_id: number;
  list_name: string;
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
  failed_count: number;
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
const SEARCH_RUNS_PAGE_SIZE = 4;
const LIST_FILTER_SEPARATOR = "||";

const CAMPAIGN_TIMEZONES = [
  { value: "America/Sao_Paulo", label: "América do Sul - Brasil/Argentina/Uruguai" },
  { value: "America/Bogota", label: "América do Sul - Colômbia/Peru/Equador" },
  { value: "America/New_York", label: "EUA/Canadá - Eastern" },
  { value: "America/Chicago", label: "EUA/Canadá/América Central - Central" },
  { value: "America/Los_Angeles", label: "EUA/Canadá - Pacific" },
  { value: "Europe/London", label: "Europa Ocidental - UK/Portugal/Irlanda" },
  { value: "Europe/Paris", label: "Europa Ocidental - França/Espanha/Alemanha/Itália" }
];

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
  language: "English",
  logo_url: DEFAULT_TEMPLATE_LOGO,
  primary_color: "#0a0a0a",
  text_color: "#333333",
  background_color: "#f4f4f4"
};

const defaultCampaignForm = {
  name: "",
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

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    ...init
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Não foi possível completar a ação.");
  }

  return response.json() as Promise<T>;
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

function percent(part: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

function leadPayload(lead: Lead) {
  return {
    name: lead.name.trim(),
    address: lead.address.trim(),
    phone: lead.phone.trim(),
    website: lead.website.trim(),
    email: lead.email.trim()
  };
}

type TemplatePreviewSource = {
  name: string;
  subject: string;
  html: string;
  text: string;
  content_title: string;
  content_link: string;
  logo_url: string;
  primary_color: string;
  text_color: string;
  background_color: string;
};

function renderTemplatePreview(template: TemplatePreviewSource, contentPreview?: ContentPreview, sampleLead?: Lead) {
  const sampleCompany = sampleLead?.name || "Example Company";
  const sampleNiche = sampleLead?.niche || "local service";
  const sampleLocation = sampleLead?.location || "their market";
  const thumbnailUrl = youtubeThumbnailUrl(template.content_link) || contentPreview?.image_url || "";
  const safeContentLink = template.content_link || "https://automasoluct.com.br";
  const safeContentTitle = template.content_title || contentPreview?.title || "How to automate your service workflows";
  const contactEmail = DEFAULT_CONTACT_EMAIL;
  const getInTouchLink = `mailto:${contactEmail}?subject=${encodeURIComponent(
    "Automation and integration help"
  )}&body=${encodeURIComponent(
    `Hi Cleiton,\n\nI saw your email about automation for ${sampleCompany} and would like to learn more.\n\n`
  )}`;
  const contentCard = contentCardHtml(safeContentLink, thumbnailUrl, safeContentTitle, template.primary_color);
  const variables: Record<string, string> = {
    lead_name: `team at ${sampleCompany}`,
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
      lead_name: `team at ${sampleCompany}`,
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

function contentCardHtml(contentLink: string, thumbnailUrl: string, contentTitle: string, primaryColor: string) {
  if (!contentLink) return "";

  const media = thumbnailUrl
    ? `<img src="${thumbnailUrl}" alt="${contentTitle}" width="520" style="display:block;width:100%;max-width:520px;height:auto;border-radius:8px;border:1px solid #eeeeee;" />`
    : `<span style="display:block;width:100%;max-width:520px;border:1px solid #eeeeee;border-radius:8px;padding:28px 24px;background-color:#f6f8f7;color:#222222;font-size:18px;line-height:1.45;font-weight:700;">${contentTitle}</span>`;

  return `
              <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px 0;">
                <tr>
                  <td align="center">
                    <a href="${contentLink}" target="_blank" rel="noopener noreferrer" style="display:block;text-decoration:none;color:inherit;">
                      ${media}
                      <span style="display:inline-block;margin-top:12px;background-color:${primaryColor || "#0a0a0a"};color:#ffffff;border-radius:999px;padding:12px 18px;font-size:14px;font-weight:700;">Open the content</span>
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

function uniqueSortedValues(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).sort((left, right) =>
    left.localeCompare(right)
  );
}

function encodeListFilterValues(values: string[]) {
  return uniqueSortedValues(values).join(LIST_FILTER_SEPARATOR);
}

function decodeListFilterValues(value: string) {
  if (!value.trim()) return [];
  if (value.includes(LIST_FILTER_SEPARATOR)) {
    return value
      .split(LIST_FILTER_SEPARATOR)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [value.trim()];
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
  const [formError, setFormError] = useState("");
  const [runError, setRunError] = useState("");
  const [actionError, setActionError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [searches, setSearches] = useState<SearchRun[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [leadNameQuery, setLeadNameQuery] = useState("");
  const [selectedLeadNiches, setSelectedLeadNiches] = useState<string[]>([]);
  const [selectedLeadLocations, setSelectedLeadLocations] = useState<string[]>([]);
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
    logo_url: DEFAULT_TEMPLATE_LOGO,
    primary_color: "#0a0a0a",
    text_color: "#333333",
    background_color: "#f4f4f4"
  });
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);
  const [selectedListNiches, setSelectedListNiches] = useState<string[]>([]);
  const [selectedListLocations, setSelectedListLocations] = useState<string[]>([]);
  const [leadListForm, setLeadListForm] = useState({
    name: "",
    niche_filter: "",
    location_filter: "",
    search_run_id: "",
    only_never_emailed: false,
    never_received_template_id: ""
  });
  const [campaigns, setCampaigns] = useState<EmailCampaign[]>([]);
  const [emailSends, setEmailSends] = useState<EmailSendLog[]>([]);
  const [campaignModalOpen, setCampaignModalOpen] = useState(false);
  const [editingCampaignId, setEditingCampaignId] = useState<number | null>(null);
  const [campaignForm, setCampaignForm] = useState(defaultCampaignForm);
  const [emailBusy, setEmailBusy] = useState(false);
  const [editingLead, setEditingLead] = useState<Lead | null>(null);
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialog>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [runActionLoading, setRunActionLoading] = useState<number | null>(null);

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

  const leadNicheOptions = useMemo(() => uniqueSortedValues(leads.map((lead) => lead.niche)), [leads]);
  const leadLocationOptions = useMemo(() => uniqueSortedValues(leads.map((lead) => lead.location)), [leads]);
  const filteredLeads = useMemo(() => {
    const normalizedLeadNameQuery = leadNameQuery.trim().toLowerCase();
    return leads.filter((lead) => {
      const matchesName = !normalizedLeadNameQuery || lead.name.toLowerCase().includes(normalizedLeadNameQuery);
      const matchesNiche = selectedLeadNiches.length === 0 || selectedLeadNiches.includes(lead.niche);
      const matchesLocation = selectedLeadLocations.length === 0 || selectedLeadLocations.includes(lead.location);
      return matchesName && matchesNiche && matchesLocation;
    });
  }, [leadNameQuery, leads, selectedLeadNiches, selectedLeadLocations]);
  const leadPageCount = Math.max(1, Math.ceil(filteredLeads.length / LEADS_PAGE_SIZE));
  const currentLeadPage = Math.min(leadPage, leadPageCount);
  const leadPageStartIndex = (currentLeadPage - 1) * LEADS_PAGE_SIZE;
  const paginatedLeads = filteredLeads.slice(leadPageStartIndex, leadPageStartIndex + LEADS_PAGE_SIZE);
  const leadPageStart = filteredLeads.length === 0 ? 0 : leadPageStartIndex + 1;
  const leadPageEnd = Math.min(leadPageStartIndex + LEADS_PAGE_SIZE, filteredLeads.length);
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const allVisibleSelected = paginatedLeads.length > 0 && paginatedLeads.every((lead) => selectedIdSet.has(lead.id));
  const recentLeads = useMemo(() => leads.slice(0, 8), [leads]);
  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedTemplateId) || templates[0] || null,
    [templates, selectedTemplateId]
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

  async function refreshData() {
    const [nextStats, nextSearches, nextLeads] = await Promise.all([
      apiFetch<Stats>("/api/stats"),
      apiFetch<SearchRun[]>("/api/searches"),
      apiFetch<Lead[]>("/api/leads")
    ]);

    setStats(nextStats);
    setSearches(nextSearches);
    setLeads(nextLeads);
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

  useEffect(() => {
    if (window.location.hash === "#leads") {
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
  }, [user, activeRun]);

  useEffect(() => {
    setSelectedIds((current) => current.filter((id) => leads.some((lead) => lead.id === id)));
  }, [leads]);

  useEffect(() => {
    setLeadPage(1);
  }, [leadNameQuery, selectedLeadNiches, selectedLeadLocations]);

  useEffect(() => {
    if (leadPage > leadPageCount) {
      setLeadPage(leadPageCount);
    }
  }, [leadPage, leadPageCount]);

  useEffect(() => {
    if (runPage > runPageCount) {
      setRunPage(runPageCount);
    }
  }, [runPage, runPageCount]);

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

  useEffect(() => {
    if (!user || !emailViews.includes(activeView)) return;

    refreshEmailData().catch(() => undefined);
  }, [user, activeView]);

  function switchView(view: AppView) {
    setActiveView(view);
    const hashes: Record<AppView, string> = {
      dashboard: "#dashboard",
      search: "#busca",
      leads: "#leads",
      templates: "#templates",
      lists: "#listas",
      campaigns: "#campanhas",
      history: "#historico",
      settings: "#settings"
    };
    const hash = hashes[view];
    window.history.replaceState(null, "", hash);
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
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Login inválido.");
    }
  }

  async function handleLogout() {
    await apiFetch<{ status: string }>("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setUser(null);
    setSearches([]);
    setLeads([]);
    setSelectedIds([]);
    setEditingLead(null);
    setDeleteDialog(null);
    setSelectedLeadNiches([]);
    setSelectedLeadLocations([]);
    setLeadPage(1);
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

  async function handleDeleteTemplate(template: EmailTemplate) {
    if (!window.confirm(`Excluir o template "${template.name}"?`)) return;

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
          niche_filter: encodeListFilterValues(selectedListNiches),
          location_filter: encodeListFilterValues(selectedListLocations),
          search_run_id: null,
          only_never_emailed: leadListForm.only_never_emailed,
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

  function resetCampaignEditor() {
    setEditingCampaignId(null);
    setCampaignForm({
      ...defaultCampaignForm,
      list_id: leadLists[0]?.id ? String(leadLists[0].id) : "",
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

  async function handleSaveCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEmailError("");
    setEmailMessage("");

    if (!campaignForm.list_id || campaignForm.template_ids.length === 0) {
      setEmailError("Escolha uma lista e ao menos um template.");
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
          max_results: maxResults
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
    const visibleIds = paginatedLeads.map((lead) => lead.id);

    if (allVisibleSelected) {
      setSelectedIds((current) => current.filter((id) => !visibleIds.includes(id)));
      return;
    }

    setSelectedIds((current) => Array.from(new Set([...current, ...visibleIds])));
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
            className={`nav-item ${activeView === "lists" ? "active" : ""}`}
            onClick={() => switchView("lists")}
            type="button"
          >
            <ListFilter size={18} />
            Listas
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
          ) : (
            <button className="secondary-button" disabled={emailBusy} onClick={refreshEmailData} type="button">
              <Clock3 size={18} />
              Atualizar
            </button>
          )}
        </header>

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
                          <a href={lead.website} target="_blank" rel="noreferrer">
                            <Globe2 size={15} />
                            {lead.website.replace(/^https?:\/\//, "")}
                          </a>
                        </td>
                        <td>{lead.email}</td>
                        <td>{lead.phone || "-"}</td>
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
                <span className="muted-count">{filteredLeads.length} visíveis</span>
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

            {actionError ? <p className="error-text">{actionError}</p> : null}

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

            <div className="filters-row">
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
              <button
                className="secondary-button"
                onClick={() => {
                  setSelectedLeadNiches([]);
                  setSelectedLeadLocations([]);
                  setLeadNameQuery("");
                  setLeadPage(1);
                }}
                type="button"
              >
                Limpar filtros
              </button>
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
                    <th>Nome</th>
                    <th>Nicho</th>
                    <th>Localidade</th>
                    <th>Endereço</th>
                    <th>Telefone</th>
                    <th>Site</th>
                    <th>E-mail</th>
                    <th>Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLeads.length === 0 ? (
                    <tr>
                      <td className="empty-cell" colSpan={9}>
                        <SkipForward size={18} />
                        Nenhum lead encontrado para os filtros.
                      </td>
                    </tr>
                  ) : null}
                  {paginatedLeads.map((lead) => (
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
                        <strong>{lead.name}</strong>
                      </td>
                      <td>{lead.niche}</td>
                      <td>{lead.location}</td>
                      <td>{lead.address}</td>
                      <td>{lead.phone || "-"}</td>
                      <td>
                        <a href={lead.website} target="_blank" rel="noreferrer">
                          <Globe2 size={15} />
                          {lead.website.replace(/^https?:\/\//, "")}
                        </a>
                      </td>
                      <td>{lead.email || "-"}</td>
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
                    </tr>
                  ))}
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
                        <td>{sendLog.error || sendLog.status}</td>
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
                      <strong>{list.name}</strong>
                      <span>{list.lead_count} leads</span>
                      <small>
                        {formatListFilter(list.niche_filter, "Todos os nichos")} · {formatListFilter(list.location_filter, "Todas as localidades")}
                      </small>
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
                  <span className="muted-count">{emailSends.length} registros</span>
                  <span className="muted-count">{emailDashboard.opens} aberturas totais</span>
                  <span className="muted-count">{emailDashboard.clicks} cliques totais</span>
                </div>
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
                    {emailSends.length === 0 ? (
                      <tr>
                        <td className="empty-cell" colSpan={9}>
                          Nenhum envio registrado.
                        </td>
                      </tr>
                    ) : null}
                    {emailSends.map((sendLog) => (
                      <tr key={sendLog.id}>
                        <td>
                          <strong>{sendLog.lead_name}</strong>
                          <span>{sendLog.recipient_email}</span>
                        </td>
                        <td>{sendLog.campaign_name}</td>
                        <td>{sendLog.template_name}</td>
                        <td>{sendLog.error || sendLog.status}</td>
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
                  {leadLists.map((list) => (
                    <option key={list.id} value={list.id}>
                      {list.name} · {list.lead_count} leads
                    </option>
                  ))}
                </select>
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
              <label className="wide-field">
                Dias de envio
                <input
                  value={campaignForm.send_days}
                  onChange={(event) => setCampaignForm({ ...campaignForm, send_days: event.target.value })}
                />
              </label>
            </div>

            <div className="template-picker modal-template-picker">
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
              A janela de envio é calculada no fuso escolhido. Dias de envio usa 0 a 6, onde 0 é segunda-feira.
              Ex.: 0,1,2,3,4 envia de segunda a sexta. O título e o link do conteúdo vêm de cada template selecionado.
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
                <input value={aiForm.language} onChange={(event) => setAiForm({ ...aiForm, language: event.target.value })} />
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
                Telefone
                <input
                  value={editingLead.phone}
                  onChange={(event) => setEditingLead({ ...editingLead, phone: event.target.value })}
                />
              </label>
              <label>
                Site
                <input
                  value={editingLead.website}
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
    </main>
  );
}
