from datetime import datetime

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.services.text_normalization import normalize_label, normalize_list_filter


class LoginRequest(BaseModel):
    username: str
    password: str


class UserRead(BaseModel):
    username: str


class SessionRead(BaseModel):
    authenticated: bool
    username: str | None = None


class SearchCreate(BaseModel):
    niche: str = Field(min_length=2, max_length=255)
    location: str = Field(min_length=2, max_length=255)
    quantity: int | None = Field(default=None, ge=1, le=500)
    max_results: bool = False
    skip_without_website: bool = True
    only_without_website: bool = False
    validate_whatsapp: bool = False
    enrich_site_insights: bool = False

    @field_validator("niche", "location", mode="before")
    @classmethod
    def normalize_segment(cls, value: str) -> str:
        return normalize_label(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_quantity(self) -> "SearchCreate":
        if not self.max_results and self.quantity is None:
            raise ValueError("Informe uma quantidade ou marque max_results.")
        if self.only_without_website:
            self.skip_without_website = False
        return self


class TagSummary(BaseModel):
    id: int
    name: str
    color: str
    origin: Literal["manual", "ai"] = "manual"

    model_config = ConfigDict(from_attributes=True)


class LeadRead(BaseModel):
    id: int
    run_id: int
    niche: str
    location: str
    name: str
    address: str
    phone: str
    website: str | None = None
    email: str
    site_insights: str | None = None
    whatsapp_validated: bool | None = None
    whatsapp_validated_at: datetime | None = None
    whatsapp_validation_status: str | None = None
    validate_whatsapp: bool = False
    whatsapp_url: str = ""
    tags: list[TagSummary] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadCreate(BaseModel):
    niche: str = Field(min_length=1, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    address: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=80)
    website: str = Field(default="", max_length=500)
    email: str = Field(default="", max_length=255)

    @field_validator("niche", "location", mode="before")
    @classmethod
    def normalize_segment(cls, value: str) -> str:
        return normalize_label(value) if isinstance(value, str) else value


class LeadUpdate(BaseModel):
    niche: str | None = Field(default=None, min_length=1, max_length=255)
    location: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=255)

    @field_validator("niche", "location", mode="before")
    @classmethod
    def normalize_segment(cls, value: str | None) -> str | None:
        return normalize_label(value) if isinstance(value, str) else value


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class BulkDeleteResponse(BaseModel):
    deleted: int


TagBulkAction = Literal["add", "remove"]


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="#e0f2fe", pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Informe o nome da tag.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Informe o nome da tag.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TagRead(TagSummary):
    description: str | None = None
    created_at: datetime
    lead_count: int = 0


class TagDeleteResponse(BaseModel):
    deleted: bool
    affected_leads: int


class LeadTagsRequest(BaseModel):
    tag_ids: list[int] = Field(min_length=1, max_length=100)


class LeadTagsBulkRequest(BaseModel):
    lead_ids: list[int] = Field(min_length=1, max_length=500)
    tag_ids: list[int] = Field(min_length=1, max_length=100)
    action: TagBulkAction


class LeadTagsBulkResponse(BaseModel):
    action: TagBulkAction
    matched_leads: int
    matched_tags: int
    changed_associations: int


class SearchRunRead(BaseModel):
    id: int
    niche: str
    location: str
    target_quantity: int | None
    max_results: bool
    skip_without_website: bool
    only_without_website: bool
    validate_whatsapp: bool
    enrich_site_insights: bool
    status: str
    message: str
    scanned_count: int
    saved_count: int
    skipped_count: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class DesktopSearchLead(BaseModel):
    scanned: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=255)
    address: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=80)
    website: str = Field(default="", max_length=500)
    email: str = Field(default="", max_length=255)


class DesktopSearchUpdate(BaseModel):
    status: Literal["running", "paused", "completed", "failed"] | None = None
    message: str | None = Field(default=None, max_length=2000)
    scanned_count: int | None = Field(default=None, ge=0)
    skipped_delta: int = Field(default=0, ge=0, le=50)
    error: str | None = Field(default=None, max_length=2000)


class DesktopLeadIngestResponse(BaseModel):
    saved: bool
    message: str
    run: SearchRunRead


class StatsRead(BaseModel):
    total_leads: int
    total_with_email: int
    running_jobs: int
    completed_jobs: int


class SmtpConfigRead(BaseModel):
    id: int | None = None
    from_email: str = ""
    from_name: str = ""
    reply_to: str = ""
    host: str = "smtp.zoho.com"
    port: int = 465
    username: str = ""
    use_ssl: bool = True
    use_tls: bool = False
    has_password: bool = False

    model_config = ConfigDict(from_attributes=True)


class SmtpConfigUpdate(BaseModel):
    from_email: str = Field(default="", max_length=255)
    from_name: str = Field(default="", max_length=255)
    reply_to: str = Field(default="", max_length=255)
    host: str = Field(default="smtp.zoho.com", min_length=2, max_length=255)
    port: int = Field(default=465, ge=1, le=65535)
    username: str = Field(default="", max_length=255)
    password: str | None = Field(default=None, max_length=1000)
    use_ssl: bool = True
    use_tls: bool = False


class SmtpTestRequest(BaseModel):
    to_email: str = Field(min_length=3, max_length=255)
    template_id: int | None = None


class ContentPreviewRead(BaseModel):
    url: str
    title: str = ""
    image_url: str = ""


class EmailTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    subject: str = Field(min_length=2, max_length=500)
    html: str = Field(min_length=1)
    text: str = ""
    content_title: str = Field(default="", max_length=500)
    content_link: str = Field(default="", max_length=1000)
    content_button_text: str = Field(default="Open the content", max_length=200)
    contact_mailto_subject: str = Field(default="Automation and integration help", max_length=300)
    contact_mailto_body: str = Field(
        default="Hi Cleiton,\n\nI saw your email about automation for {{company_name}} and would like to learn more.\n\n"
    )
    logo_url: str = Field(default="", max_length=1000)
    primary_color: str = Field(default="#0a0a0a", max_length=20)
    text_color: str = Field(default="#333333", max_length=20)
    background_color: str = Field(default="#f4f4f4", max_length=20)


class EmailTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    subject: str | None = Field(default=None, min_length=2, max_length=500)
    html: str | None = Field(default=None, min_length=1)
    text: str | None = None
    content_title: str | None = Field(default=None, max_length=500)
    content_link: str | None = Field(default=None, max_length=1000)
    content_button_text: str | None = Field(default=None, max_length=200)
    contact_mailto_subject: str | None = Field(default=None, max_length=300)
    contact_mailto_body: str | None = None
    logo_url: str | None = Field(default=None, max_length=1000)
    primary_color: str | None = Field(default=None, max_length=20)
    text_color: str | None = Field(default=None, max_length=20)
    background_color: str | None = Field(default=None, max_length=20)


class EmailTemplateRead(BaseModel):
    id: int
    name: str
    subject: str
    html: str
    text: str
    content_title: str
    content_link: str
    content_button_text: str
    contact_mailto_subject: str
    contact_mailto_body: str
    logo_url: str
    primary_color: str
    text_color: str
    background_color: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WhatsAppMessageTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    content: str = Field(min_length=1)


class WhatsAppMessageTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    content: str | None = Field(default=None, min_length=1)


class WhatsAppMessageTemplateRead(BaseModel):
    id: int
    name: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WhatsAppTemplateGenerateRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=1000)


class WhatsAppTemplateGenerateResponse(BaseModel):
    content: str


class LeadSiteInsightsEnrichmentResponse(BaseModel):
    status: str
    eligible_count: int
    queued_count: int
    location_inference: str


class LeadSiteInsightsEnrichmentRequest(BaseModel):
    lead_ids: list[int] = Field(default_factory=list, max_length=1000)


class LeadWhatsAppValidationRequest(BaseModel):
    """Request for validating WhatsApp on saved leads.

    Precedence: when lead_ids is provided and non-empty, it is authoritative and
    niche/location/search filters are ignored. When lead_ids is None or empty,
    selection is performed entirely on the server by filters, intentionally
    allowing validation of leads beyond the 500 rows loaded by the frontend.
    """

    lead_ids: list[int] | None = Field(default=None, max_length=1000)
    niche: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    search: str | None = Field(default=None, max_length=255)
    only_pending: bool = True
    revalidate: bool = False
    limit: int | None = Field(default=None, ge=1)


class LeadWhatsAppValidationResponse(BaseModel):
    job_id: str
    status: str
    eligible_count: int
    queued_count: int
    skipped_count: int
    message: str


class LeadWhatsAppValidationProgress(BaseModel):
    job_id: str
    status: str
    total: int
    processed: int
    valid: int
    invalid: int
    unknown: int
    skipped: int
    started_at: str | None
    finished_at: str | None
    error: str | None


class LeadWhatsAppValidationPreview(BaseModel):
    total_leads: int
    never_validated: int
    valid: int
    invalid: int
    unknown: int
    without_phone: int
    eligible_now: int


CrmStage = str


class CrmFunnelStageCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    key: str | None = Field(default=None, min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    color: str = Field(default="#f3f4f6", pattern=r"^#[0-9A-Fa-f]{6}$")
    is_won: bool = False
    is_lost: bool = False

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Informe o nome do estágio.")
        return normalized


class CrmFunnelStageUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    key: str | None = Field(default=None, min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    position: int | None = Field(default=None, ge=0)
    is_won: bool | None = None
    is_lost: bool | None = None

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Informe o nome do estágio.")
        return normalized


class CrmFunnelStageReorderRequest(BaseModel):
    stage_ids: list[int] = Field(min_length=1)


class CrmFunnelStageRead(BaseModel):
    id: int
    funnel_id: int
    key: str
    label: str
    color: str
    position: int
    is_won: bool
    is_lost: bool
    card_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class CrmFunnelCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Informe o nome do funil.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CrmFunnelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Informe o nome do funil.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CrmFunnelRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_default: bool
    created_at: datetime
    card_count: int = 0
    stages: list[CrmFunnelStageRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CrmLeadFunnelSummary(BaseModel):
    id: int
    name: str
    stage: str
    stage_label: str


class CrmLeadUpdate(BaseModel):
    stage: CrmStage | None = None
    funnel_id: int | None = None
    position: int | None = Field(default=None, ge=0)
    qualification_notes: str | None = Field(default=None, max_length=5000)


class CrmLeadRead(BaseModel):
    id: int
    lead_id: int
    funnel_id: int
    funnel_name: str
    stage_id: int
    stage: CrmStage
    stage_label: str
    stage_color: str
    qualification_notes: str | None = None
    score: int | None = None
    position: int | None = None
    updated_at: datetime
    lead_name: str
    phone: str | None = None
    whatsapp_url: str = ""
    website: str | None = None
    email: str
    niche: str
    location: str
    tags: list[TagSummary] = Field(default_factory=list)
    last_message: str | None = None
    last_message_at: datetime | None = None
    conversation_id: int | None = None
    other_funnels: list[CrmLeadFunnelSummary] = Field(default_factory=list)


class WhatsAppAiSettingsUpdate(BaseModel):
    system_prompt: str | None = Field(default=None, max_length=8000)
    services_description: str | None = Field(default=None, max_length=12000)
    enabled: bool | None = None
    auto_apply_tags_enabled: bool | None = None


class WhatsAppAiSettingsRead(BaseModel):
    id: int
    system_prompt: str
    services_description: str
    enabled: bool
    auto_apply_tags_enabled: bool
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WhatsAppPortfolioItemCreate(BaseModel):
    description: str = Field(min_length=3, max_length=500)
    url: str = Field(min_length=3, max_length=1000)


class WhatsAppPortfolioItemRead(BaseModel):
    id: int
    description: str
    url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AiTemplateGenerateRequest(BaseModel):
    mode: Literal["single", "sequence"] = "sequence"
    count: int = Field(default=3, ge=1, le=5)
    niche: str = Field(default="", max_length=255)
    location: str = Field(default="", max_length=255)
    objective: str = Field(default="Share useful automation content and softly introduce Automa Soluct.", max_length=1000)
    tone: str = Field(default="educational, friendly, consultative, low-pressure", max_length=255)
    content_title: str = Field(default="", max_length=500)
    content_link: str = Field(default="", max_length=1000)
    campaign_name: str = Field(default="", max_length=255)
    call_to_action: str = Field(
        default="Invite the reader to reply if they need help with automation, integrations, follow-ups, or reducing manual work.",
        max_length=1000,
    )
    language: Literal["pt", "en", "es"] = "pt"
    logo_url: str = Field(default="", max_length=1000)
    primary_color: str = Field(default="#0a0a0a", max_length=20)
    text_color: str = Field(default="#333333", max_length=20)
    background_color: str = Field(default="#f4f4f4", max_length=20)


class AiTemplateGenerateResponse(BaseModel):
    templates: list[EmailTemplateRead]


EmailEngagementFilterMode = Literal["or", "and"]
LeadListChannel = Literal["email", "whatsapp", "both"]


class LeadListCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    channel: LeadListChannel = "both"
    niche_filter: str = Field(default="", max_length=255)
    location_filter: str = Field(default="", max_length=255)
    search_run_id: int | None = None
    only_never_emailed: bool = False
    only_whatsapp_validated: bool = False
    only_email_opened: bool = False
    only_email_clicked: bool = False
    email_engagement_filter_mode: EmailEngagementFilterMode = "or"
    never_received_template_id: int | None = None

    @field_validator("niche_filter", "location_filter", mode="before")
    @classmethod
    def normalize_filter(cls, value: str) -> str:
        return normalize_list_filter(value) if isinstance(value, str) else value


class LeadListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    channel: LeadListChannel | None = None
    niche_filter: str | None = Field(default=None, max_length=255)
    location_filter: str | None = Field(default=None, max_length=255)
    search_run_id: int | None = None
    only_never_emailed: bool | None = None
    only_whatsapp_validated: bool | None = None
    only_email_opened: bool | None = None
    only_email_clicked: bool | None = None
    email_engagement_filter_mode: EmailEngagementFilterMode | None = None
    never_received_template_id: int | None = None

    @field_validator("niche_filter", "location_filter", mode="before")
    @classmethod
    def normalize_filter(cls, value: str | None) -> str | None:
        return normalize_list_filter(value) if isinstance(value, str) else value


class LeadListRead(BaseModel):
    id: int
    name: str
    channel: LeadListChannel
    niche_filter: str
    location_filter: str
    search_run_id: int | None
    only_never_emailed: bool
    only_whatsapp_validated: bool
    only_email_opened: bool
    only_email_clicked: bool
    email_engagement_filter_mode: EmailEngagementFilterMode
    never_received_template_id: int | None
    created_at: datetime
    updated_at: datetime
    lead_count: int = 0

    model_config = ConfigDict(from_attributes=True)


EmailMessageMode = Literal["template", "ai_per_lead"]
WhatsAppMessageMode = Literal["template", "ai_per_lead"]
AiMessageLanguage = Literal["pt", "en", "es"]


class CampaignTemplateInput(BaseModel):
    template_id: int
    weight: int = Field(default=1, ge=1, le=100)


class EmailCampaignCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    list_id: int
    templates: list[CampaignTemplateInput] = Field(min_length=1)
    objective: str | None = Field(default="", max_length=2000)
    message_mode: EmailMessageMode = "template"
    language: AiMessageLanguage = "pt"
    min_delay_seconds: int = Field(default=120, ge=1, le=86400)
    max_delay_seconds: int = Field(default=300, ge=1, le=86400)
    daily_limit: int = Field(default=30, ge=1, le=500)
    weekly_limit: int = Field(default=150, ge=1, le=3000)
    send_window_start: str = Field(default="09:00", max_length=5)
    send_window_end: str = Field(default="17:00", max_length=5)
    timezone_name: str = Field(default="America/New_York", max_length=80)
    send_days: str = Field(default="0,1,2,3,4", max_length=20)

    @field_validator("send_days")
    @classmethod
    def validate_send_days(cls, value: str) -> str:
        seen: set[int] = set()
        days: list[int] = []

        for raw_day in (value or "").split(","):
            day = raw_day.strip()
            if not day:
                continue
            if not day.isdigit():
                raise ValueError("Dias de envio devem ser números de 0 a 6.")

            day_number = int(day)
            if day_number < 0 or day_number > 6:
                raise ValueError("Dias de envio devem ficar entre 0 (segunda) e 6 (domingo).")

            if day_number not in seen:
                seen.add(day_number)
                days.append(day_number)

        if not days:
            raise ValueError("Escolha ao menos um dia de envio.")

        return ",".join(str(day) for day in sorted(days))


class EmailCampaignUpdate(EmailCampaignCreate):
    pass


class EmailCampaignRead(BaseModel):
    id: int
    name: str
    list_id: int
    list_name: str
    status: str
    objective: str
    message_mode: EmailMessageMode
    language: AiMessageLanguage
    message: str
    error: str | None
    min_delay_seconds: int
    max_delay_seconds: int
    daily_limit: int
    weekly_limit: int
    send_window_start: str
    send_window_end: str
    timezone_name: str
    send_days: str
    template_ids: list[int]
    pending_count: int
    sent_count: int
    failed_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class EmailSendRead(BaseModel):
    id: int
    campaign_id: int
    campaign_name: str
    lead_id: int
    lead_name: str
    template_id: int
    template_name: str
    recipient_email: str
    subject: str
    status: str
    error: str | None
    generated_content: str | None
    open_count: int
    click_count: int
    created_at: datetime
    sent_at: datetime | None
    opened_at: datetime | None
    clicked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class WhatsAppInstanceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    phone_number: str | None = Field(default=None, max_length=80)


class WhatsAppInstanceRead(BaseModel):
    id: int
    name: str
    provider: str
    status: str
    evolution_instance_name: str | None
    phone_number: str | None
    connected_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WhatsAppQrCodeRead(BaseModel):
    id: int
    name: str
    evolution_instance_name: str
    base64: str = ""
    url: str = ""
    code: str = ""
    pairing_code: str | None = None
    provider_response: dict[str, Any]


class WhatsAppInstanceStatusRead(BaseModel):
    id: int
    name: str
    status: str
    phone_number: str | None
    connected_at: datetime | None
    provider_state: str
    provider_response: dict[str, Any]


class WhatsAppCampaignCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    objective: str | None = Field(default="", max_length=2000)
    message_mode: WhatsAppMessageMode = "template"
    language: AiMessageLanguage = "pt"
    list_id: int
    funnel_id: int | None = None
    instance_id: int
    templates: list[CampaignTemplateInput] = Field(default_factory=list)
    min_delay_seconds: int = Field(default=120, ge=1, le=86400)
    max_delay_seconds: int = Field(default=300, ge=1, le=86400)
    daily_limit: int = Field(default=30, ge=1, le=500)
    weekly_limit: int = Field(default=150, ge=1, le=3000)
    send_window_start: str = Field(default="09:00", max_length=5)
    send_window_end: str = Field(default="17:00", max_length=5)
    timezone_name: str = Field(default="America/New_York", max_length=80)
    send_days: str = Field(default="0,1,2,3,4", max_length=20)

    @field_validator("send_days")
    @classmethod
    def validate_send_days(cls, value: str) -> str:
        seen: set[int] = set()
        days: list[int] = []

        for raw_day in (value or "").split(","):
            day = raw_day.strip()
            if not day:
                continue
            if not day.isdigit():
                raise ValueError("Dias de envio devem ser números de 0 a 6.")

            day_number = int(day)
            if day_number < 0 or day_number > 6:
                raise ValueError("Dias de envio devem ficar entre 0 (segunda) e 6 (domingo).")

            if day_number not in seen:
                seen.add(day_number)
                days.append(day_number)

        if not days:
            raise ValueError("Escolha ao menos um dia de envio.")

        return ",".join(str(day) for day in sorted(days))


class WhatsAppCampaignUpdate(WhatsAppCampaignCreate):
    pass


class WhatsAppCampaignRead(BaseModel):
    id: int
    name: str
    objective: str
    message_mode: WhatsAppMessageMode
    language: AiMessageLanguage
    list_id: int
    list_name: str
    funnel_id: int | None = None
    funnel_name: str = ""
    instance_id: int
    instance_name: str
    status: str
    message: str
    error: str | None
    min_delay_seconds: int
    max_delay_seconds: int
    daily_limit: int
    weekly_limit: int
    send_window_start: str
    send_window_end: str
    timezone_name: str
    send_days: str
    template_ids: list[int]
    pending_count: int
    sent_count: int
    delivered_count: int
    read_count: int
    failed_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
