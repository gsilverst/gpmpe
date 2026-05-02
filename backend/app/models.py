from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AppMeta(Base):
    __tablename__ = "app_meta"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class RuntimeGitSettings(Base):
    __tablename__ = "runtime_git_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(50), nullable=False, server_default="global")
    repo_path: Mapped[str | None] = mapped_column(Text)
    remote_url: Mapped[str | None] = mapped_column(Text)
    remote_name: Mapped[str] = mapped_column(String(100), nullable=False, server_default="origin")
    branch: Mapped[str] = mapped_column(String(200), nullable=False, server_default="HEAD")
    user_name: Mapped[str | None] = mapped_column(String(200))
    user_email: Mapped[str | None] = mapped_column(String(320))
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    credential_provider: Mapped[str] = mapped_column(String(50), nullable=False, server_default="local")
    credential_reference: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    __table_args__ = (UniqueConstraint("scope", name="uix_runtime_git_settings_scope"),)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False, server_default="system")
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False, server_default="global")
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, server_default="America/New_York")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    contacts: Mapped[list[BusinessContact]] = relationship("BusinessContact", back_populates="business", cascade="all, delete-orphan")
    locations: Mapped[list[BusinessLocation]] = relationship("BusinessLocation", back_populates="business", cascade="all, delete-orphan")
    brand_themes: Mapped[list[BrandTheme]] = relationship("BrandTheme", back_populates="business", cascade="all, delete-orphan")
    campaigns: Mapped[list[Campaign]] = relationship("Campaign", back_populates="business", cascade="all, delete-orphan")


class BusinessContact(Base):
    __tablename__ = "business_contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    contact_type: Mapped[str] = mapped_column(String(50), nullable=False)  # phone, email, website
    contact_value: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    business: Mapped[Business] = relationship("Business", back_populates="contacts")


class BusinessLocation(Base):
    __tablename__ = "business_locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100))
    line1: Mapped[str] = mapped_column(String(200), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False, server_default="US")
    hours_json: Mapped[str | None] = mapped_column(Text)  # JSON string
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    business: Mapped[Business] = relationship("Business", back_populates="locations")


class BrandTheme(Base):
    __tablename__ = "brand_themes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, server_default="default")
    primary_color: Mapped[str | None] = mapped_column(String(50))
    secondary_color: Mapped[str | None] = mapped_column(String(50))
    accent_color: Mapped[str | None] = mapped_column(String(50))
    font_family: Mapped[str | None] = mapped_column(String(100))
    logo_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    business: Mapped[Business] = relationship("Business", back_populates="brand_themes")

    __table_args__ = (UniqueConstraint("business_id", "name", name="uix_business_theme_name"),)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    campaign_name: Mapped[str] = mapped_column(String(200), nullable=False)
    campaign_key: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text)
    footnote_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="draft")
    start_date: Mapped[str | None] = mapped_column(String(50))
    end_date: Mapped[str | None] = mapped_column(String(50))
    details_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    business: Mapped[Business] = relationship("Business", back_populates="campaigns")
    offers: Mapped[list[CampaignOffer]] = relationship("CampaignOffer", back_populates="campaign", cascade="all, delete-orphan")
    assets: Mapped[list[CampaignAsset]] = relationship("CampaignAsset", back_populates="campaign", cascade="all, delete-orphan")
    template_bindings: Mapped[list[CampaignTemplateBinding]] = relationship("CampaignTemplateBinding", back_populates="campaign", cascade="all, delete-orphan")
    artifacts: Mapped[list[GeneratedArtifact]] = relationship("GeneratedArtifact", back_populates="campaign", cascade="all, delete-orphan")
    components: Mapped[list[CampaignComponent]] = relationship("CampaignComponent", back_populates="campaign", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("business_id", "campaign_name", "campaign_key", name="uix_campaign_business_name_key"),)


class CampaignOffer(Base):
    __tablename__ = "campaign_offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    offer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    offer_type: Mapped[str] = mapped_column(String(100), nullable=False, server_default="discount")
    offer_value: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[str | None] = mapped_column(String(50))
    end_date: Mapped[str | None] = mapped_column(String(50))
    terms_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="offers")


class CampaignAsset(Base):
    __tablename__ = "campaign_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # upload, url, generated
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="assets")


class TemplateDefinition(Base):
    __tablename__ = "template_definitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    template_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    size_spec: Mapped[str | None] = mapped_column(String(50))
    layout_json: Mapped[str | None] = mapped_column(Text)
    default_values_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    bindings: Mapped[list[CampaignTemplateBinding]] = relationship("CampaignTemplateBinding", back_populates="template")


class CampaignTemplateBinding(Base):
    __tablename__ = "campaign_template_bindings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("template_definitions.id", ondelete="RESTRICT"), nullable=False)
    override_values_json: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="template_bindings")
    template: Mapped[TemplateDefinition] = relationship("TemplateDefinition", back_populates="bindings")


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="flyer")
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="complete")
    template_snapshot_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="artifacts")


class CampaignComponent(Base):
    __tablename__ = "campaign_components"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    component_key: Mapped[str] = mapped_column(String(100), nullable=False)
    component_kind: Mapped[str] = mapped_column(String(100), nullable=False, server_default="featured-offers")
    render_region: Mapped[str | None] = mapped_column(String(100))
    render_mode: Mapped[str | None] = mapped_column(String(100))
    style_json: Mapped[str | None] = mapped_column(Text)
    display_title: Mapped[str] = mapped_column(String(200), nullable=False)
    background_color: Mapped[str | None] = mapped_column(String(100))
    header_accent_color: Mapped[str | None] = mapped_column(String(100))
    footnote_text: Mapped[str | None] = mapped_column(Text)
    subtitle: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="components")
    items: Mapped[list[CampaignComponentItem]] = relationship("CampaignComponentItem", back_populates="component", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("campaign_id", "component_key", name="uix_campaign_component_key"),)


class CampaignComponentItem(Base):
    __tablename__ = "campaign_component_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaign_components.id", ondelete="CASCADE"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    item_kind: Mapped[str] = mapped_column(String(100), nullable=False, server_default="service")
    render_role: Mapped[str | None] = mapped_column(String(100))
    style_json: Mapped[str | None] = mapped_column(Text)
    duration_label: Mapped[str | None] = mapped_column(String(200))
    item_value: Mapped[str | None] = mapped_column(String(200))
    background_color: Mapped[str | None] = mapped_column(String(100))
    description_text: Mapped[str | None] = mapped_column(Text)
    terms_text: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    component: Mapped[CampaignComponent] = relationship("CampaignComponent", back_populates="items")
