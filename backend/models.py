from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    niche: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    target_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_results: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    skip_without_website: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    only_without_website: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validate_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enrich_site_insights: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="Na fila", nullable=False)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    saved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    leads: Mapped[list["Lead"]] = relationship(
        back_populates="search_run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("website", name="uq_leads_website"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("search_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    site_insights: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp_validated: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    whatsapp_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    whatsapp_validation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    whatsapp_validation_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    search_run: Mapped[SearchRun] = relationship(back_populates="leads")

    @property
    def niche(self) -> str:
        return self.search_run.niche if self.search_run else ""

    @property
    def location(self) -> str:
        return self.search_run.location if self.search_run else ""

    @property
    def validate_whatsapp(self) -> bool:
        return bool(self.search_run and self.search_run.validate_whatsapp)

    @property
    def whatsapp_url(self) -> str:
        if self.whatsapp_validated is False:
            return ""
        if self.whatsapp_validated is not True and not self.validate_whatsapp:
            return ""

        from backend.services.whatsapp_validation import normalize_phone_e164

        normalized_phone = normalize_phone_e164(self.phone, f"{self.address} {self.location}")
        if not normalized_phone:
            return ""

        return f"https://wa.me/{normalized_phone.lstrip('+')}"


class SmtpConfig(Base):
    __tablename__ = "smtp_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    from_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    reply_to: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    host: Mapped[str] = mapped_column(String(255), default="smtp.zoho.com", nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=465, nullable=False)
    username: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_tls: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    @property
    def has_password(self) -> bool:
        return bool(self.password_encrypted)


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    content_link: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    content_button_text: Mapped[str] = mapped_column(String(200), default="Open the content", nullable=False)
    contact_mailto_subject: Mapped[str] = mapped_column(
        String(300), default="Automation and integration help", nullable=False
    )
    contact_mailto_body: Mapped[str] = mapped_column(
        Text,
        default="Hi Cleiton,\n\nI saw your email about automation for {{company_name}} and would like to learn more.\n\n",
        nullable=False,
    )
    logo_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    primary_color: Mapped[str] = mapped_column(String(20), default="#0a0a0a", nullable=False)
    text_color: Mapped[str] = mapped_column(String(20), default="#333333", nullable=False)
    background_color: Mapped[str] = mapped_column(String(20), default="#f4f4f4", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LeadList(Base):
    __tablename__ = "lead_lists"
    __table_args__ = (
        CheckConstraint(
            "email_engagement_filter_mode IN ('or', 'and')",
            name="ck_lead_lists_email_engagement_filter_mode",
        ),
        CheckConstraint(
            "channel IN ('email', 'whatsapp', 'both')",
            name="ck_lead_lists_channel",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    channel: Mapped[str] = mapped_column(String(10), default="both", nullable=False)
    niche_filter: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    location_filter: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    search_run_id: Mapped[int | None] = mapped_column(ForeignKey("search_runs.id", ondelete="SET NULL"), nullable=True)
    only_never_emailed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    only_whatsapp_validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    only_email_opened: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    only_email_clicked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_engagement_filter_mode: Mapped[str] = mapped_column(String(10), default="or", nullable=False)
    never_received_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    search_run: Mapped[SearchRun | None] = relationship(lazy="selectin")
    never_received_template: Mapped[EmailTemplate | None] = relationship(lazy="selectin")


class LeadEmailPreference(Base):
    __tablename__ = "lead_email_preferences"

    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), primary_key=True)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lead: Mapped[Lead] = relationship(lazy="selectin")


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"
    __table_args__ = (
        CheckConstraint(
            "message_mode IN ('template', 'ai_per_lead')",
            name="ck_email_campaigns_message_mode",
        ),
        CheckConstraint(
            "language IN ('pt', 'en', 'es')",
            name="ck_email_campaigns_language",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    list_id: Mapped[int] = mapped_column(ForeignKey("lead_lists.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    message_mode: Mapped[str] = mapped_column(String(30), default="template", nullable=False)
    language: Mapped[str] = mapped_column(String(5), default="pt", nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_delay_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    max_delay_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    weekly_limit: Mapped[int] = mapped_column(Integer, default=150, nullable=False)
    send_window_start: Mapped[str] = mapped_column(String(5), default="09:00", nullable=False)
    send_window_end: Mapped[str] = mapped_column(String(5), default="17:00", nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(80), default="America/New_York", nullable=False)
    send_days: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4", nullable=False)
    content_title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    content_link: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    pending_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lead_list: Mapped[LeadList] = relationship(lazy="selectin")
    templates: Mapped[list["EmailCampaignTemplate"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def list_name(self) -> str:
        return self.lead_list.name if self.lead_list else ""

    @property
    def template_ids(self) -> list[int]:
        return [item.template_id for item in self.templates]


class EmailCampaignTemplate(Base):
    __tablename__ = "email_campaign_templates"
    __table_args__ = (UniqueConstraint("campaign_id", "template_id", name="uq_campaign_template"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("email_templates.id", ondelete="RESTRICT"), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    campaign: Mapped[EmailCampaign] = relationship(back_populates="templates")
    template: Mapped[EmailTemplate] = relationship(lazy="selectin")


class EmailSend(Base):
    __tablename__ = "email_sends"
    __table_args__ = (UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_lead_send"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("email_templates.id", ondelete="RESTRICT"), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    click_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped[EmailCampaign] = relationship(lazy="selectin")
    lead: Mapped[Lead] = relationship(lazy="selectin")
    template: Mapped[EmailTemplate] = relationship(lazy="selectin")

    @property
    def lead_name(self) -> str:
        return self.lead.name if self.lead else ""

    @property
    def campaign_name(self) -> str:
        return self.campaign.name if self.campaign else ""

    @property
    def template_name(self) -> str:
        return self.template.name if self.template else ""


class WhatsAppInstance(Base):
    __tablename__ = "whatsapp_instances"
    __table_args__ = (
        CheckConstraint("provider IN ('evolution', 'meta_official')", name="ck_whatsapp_instances_provider"),
        CheckConstraint(
            "status IN ('disconnected', 'connecting', 'connected')",
            name="ck_whatsapp_instances_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(30), default="evolution", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="disconnected", nullable=False)
    evolution_instance_name: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    phone_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WhatsAppMessageTemplate(Base):
    __tablename__ = "whatsapp_message_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhatsAppCampaign(Base):
    __tablename__ = "whatsapp_campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'running', 'paused', 'completed')",
            name="ck_whatsapp_campaigns_status",
        ),
        CheckConstraint(
            "message_mode IN ('template', 'ai_per_lead')",
            name="ck_whatsapp_campaigns_message_mode",
        ),
        CheckConstraint(
            "language IN ('pt', 'en', 'es')",
            name="ck_whatsapp_campaigns_language",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    list_id: Mapped[int] = mapped_column(ForeignKey("lead_lists.id", ondelete="RESTRICT"), nullable=False)
    instance_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_instances.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    message_mode: Mapped[str] = mapped_column(String(30), default="template", nullable=False)
    language: Mapped[str] = mapped_column(String(5), default="pt", nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_delay_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    max_delay_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    weekly_limit: Mapped[int] = mapped_column(Integer, default=150, nullable=False)
    send_window_start: Mapped[str] = mapped_column(String(5), default="09:00", nullable=False)
    send_window_end: Mapped[str] = mapped_column(String(5), default="17:00", nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(80), default="America/New_York", nullable=False)
    send_days: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4", nullable=False)
    pending_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    read_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lead_list: Mapped[LeadList] = relationship(lazy="selectin")
    instance: Mapped[WhatsAppInstance] = relationship(lazy="selectin")
    templates: Mapped[list["WhatsAppCampaignTemplate"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def list_name(self) -> str:
        return self.lead_list.name if self.lead_list else ""

    @property
    def instance_name(self) -> str:
        return self.instance.name if self.instance else ""

    @property
    def template_ids(self) -> list[int]:
        return [item.template_id for item in self.templates]


class WhatsAppCampaignTemplate(Base):
    __tablename__ = "whatsapp_campaign_templates"
    __table_args__ = (UniqueConstraint("campaign_id", "template_id", name="uq_whatsapp_campaign_template"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_campaigns.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("whatsapp_message_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    campaign: Mapped[WhatsAppCampaign] = relationship(back_populates="templates")
    template: Mapped[WhatsAppMessageTemplate | None] = relationship(lazy="selectin")


class WhatsAppSend(Base):
    __tablename__ = "whatsapp_sends"
    __table_args__ = (
        UniqueConstraint("campaign_id", "lead_id", name="uq_whatsapp_campaign_lead_send"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'delivered', 'read', 'failed')",
            name="ck_whatsapp_sends_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_campaigns.id", ondelete="CASCADE"), nullable=False)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("whatsapp_message_templates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    recipient_phone: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    generated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped[WhatsAppCampaign] = relationship(lazy="selectin")
    lead: Mapped[Lead] = relationship(lazy="selectin")
    template: Mapped[WhatsAppMessageTemplate] = relationship(lazy="selectin")

    @property
    def lead_name(self) -> str:
        return self.lead.name if self.lead else ""

    @property
    def campaign_name(self) -> str:
        return self.campaign.name if self.campaign else ""

    @property
    def template_name(self) -> str:
        return self.template.name if self.template else ""


class WhatsAppConversation(Base):
    __tablename__ = "whatsapp_conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'needs_attention', 'handled')",
            name="ck_whatsapp_conversations_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_instances.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped[Lead | None] = relationship(lazy="selectin")
    instance: Mapped[WhatsAppInstance] = relationship(lazy="selectin")
    messages: Mapped[list["WhatsAppMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_whatsapp_messages_direction"),
        CheckConstraint(
            "message_type IN ('text', 'audio', 'image', 'other')",
            name="ck_whatsapp_messages_message_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("whatsapp_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    audio_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[WhatsAppConversation] = relationship(back_populates="messages")


class WhatsAppAiSettings(Base):
    __tablename__ = "whatsapp_ai_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    services_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WhatsAppPortfolioItem(Base):
    __tablename__ = "whatsapp_portfolio_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhatsAppWebhookSettings(Base):
    __tablename__ = "whatsapp_webhook_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CrmLead(Base):
    __tablename__ = "crm_leads"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('new', 'responded', 'qualified', 'not_interested', 'converted')",
            name="ck_crm_leads_stage",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, unique=True)
    stage: Mapped[str] = mapped_column(String(30), default="new", nullable=False)
    qualification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lead: Mapped[Lead] = relationship(lazy="selectin")
    stage_history: Mapped[list["CrmStageHistory"]] = relationship(
        back_populates="crm_lead",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CrmStageHistory(Base):
    __tablename__ = "crm_stage_history"
    __table_args__ = (
        CheckConstraint(
            "from_stage IN ('new', 'responded', 'qualified', 'not_interested', 'converted')",
            name="ck_crm_stage_history_from_stage",
        ),
        CheckConstraint(
            "to_stage IN ('new', 'responded', 'qualified', 'not_interested', 'converted')",
            name="ck_crm_stage_history_to_stage",
        ),
        CheckConstraint("changed_by IN ('ai', 'manual')", name="ck_crm_stage_history_changed_by"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    crm_lead_id: Mapped[int] = mapped_column(ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False)
    from_stage: Mapped[str] = mapped_column(String(30), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    changed_by: Mapped[str] = mapped_column(String(20), nullable=False)

    crm_lead: Mapped[CrmLead] = relationship(back_populates="stage_history")
