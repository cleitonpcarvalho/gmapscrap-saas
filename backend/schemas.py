from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def validate_quantity(self) -> "SearchCreate":
        if not self.max_results and self.quantity is None:
            raise ValueError("Informe uma quantidade ou marque max_results.")
        return self


class LeadRead(BaseModel):
    id: int
    run_id: int
    niche: str
    location: str
    name: str
    address: str
    phone: str
    website: str
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadCreate(BaseModel):
    niche: str = Field(min_length=1, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    address: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=80)
    website: str = Field(min_length=1, max_length=500)
    email: str = Field(default="", max_length=255)


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, min_length=1)
    phone: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, min_length=1, max_length=500)
    email: str | None = Field(default=None, max_length=255)


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class BulkDeleteResponse(BaseModel):
    deleted: int


class SearchRunRead(BaseModel):
    id: int
    niche: str
    location: str
    target_quantity: int | None
    max_results: bool
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
    website: str = Field(min_length=1, max_length=500)
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
    logo_url: str
    primary_color: str
    text_color: str
    background_color: str
    created_at: datetime
    updated_at: datetime

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
    language: str = Field(default="English", max_length=80)
    logo_url: str = Field(default="", max_length=1000)
    primary_color: str = Field(default="#0a0a0a", max_length=20)
    text_color: str = Field(default="#333333", max_length=20)
    background_color: str = Field(default="#f4f4f4", max_length=20)


class AiTemplateGenerateResponse(BaseModel):
    templates: list[EmailTemplateRead]


class LeadListCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    niche_filter: str = Field(default="", max_length=255)
    location_filter: str = Field(default="", max_length=255)
    search_run_id: int | None = None
    only_never_emailed: bool = False
    never_received_template_id: int | None = None


class LeadListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    niche_filter: str | None = Field(default=None, max_length=255)
    location_filter: str | None = Field(default=None, max_length=255)
    search_run_id: int | None = None
    only_never_emailed: bool | None = None
    never_received_template_id: int | None = None


class LeadListRead(BaseModel):
    id: int
    name: str
    niche_filter: str
    location_filter: str
    search_run_id: int | None
    only_never_emailed: bool
    never_received_template_id: int | None
    created_at: datetime
    updated_at: datetime
    lead_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class CampaignTemplateInput(BaseModel):
    template_id: int
    weight: int = Field(default=1, ge=1, le=100)


class EmailCampaignCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    list_id: int
    templates: list[CampaignTemplateInput] = Field(min_length=1)
    min_delay_seconds: int = Field(default=120, ge=1, le=86400)
    max_delay_seconds: int = Field(default=300, ge=1, le=86400)
    daily_limit: int = Field(default=30, ge=1, le=500)
    weekly_limit: int = Field(default=150, ge=1, le=3000)
    send_window_start: str = Field(default="09:00", max_length=5)
    send_window_end: str = Field(default="17:00", max_length=5)
    timezone_name: str = Field(default="America/New_York", max_length=80)
    send_days: str = Field(default="0,1,2,3,4", max_length=20)


class EmailCampaignUpdate(EmailCampaignCreate):
    pass


class EmailCampaignRead(BaseModel):
    id: int
    name: str
    list_id: int
    list_name: str
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
    open_count: int
    click_count: int
    created_at: datetime
    sent_at: datetime | None
    opened_at: datetime | None
    clicked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
