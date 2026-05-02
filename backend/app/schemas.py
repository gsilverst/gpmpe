from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


class BusinessCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="America/New_York", min_length=1, max_length=60)
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default="US", max_length=100)


class BusinessResponse(BaseModel):
    id: int
    legal_name: str
    display_name: str
    timezone: str
    is_active: bool
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class BusinessUpdate(BaseModel):
    legal_name: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=100)


class CampaignCreate(BaseModel):
    campaign_name: str = Field(min_length=1, max_length=200)
    campaign_key: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    objective: str | None = Field(default=None, max_length=1000)
    footnote_text: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active", "paused", "completed", "archived"] = "draft"
    start_date: str | None = None
    end_date: str | None = None


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    objective: str | None = Field(default=None, max_length=1000)
    footnote_text: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active", "paused", "completed", "archived"] | None = None
    start_date: str | None = None
    end_date: str | None = None


class CampaignCloneRequest(BaseModel):
    new_campaign_name: str = Field(min_length=1, max_length=200)
    campaign_key: str | None = Field(default=None, max_length=100)


class CampaignOfferCreate(BaseModel):
    offer_name: str = Field(min_length=1, max_length=200)
    offer_type: str = Field(default="discount", min_length=1, max_length=100)
    offer_value: str | None = Field(default=None, max_length=200)
    start_date: str | None = None
    end_date: str | None = None
    terms_text: str | None = Field(default=None, max_length=2000)


class CampaignAssetCreate(BaseModel):
    asset_type: str = Field(min_length=1, max_length=100)
    source_type: Literal["upload", "url", "generated"]
    mime_type: str = Field(min_length=1, max_length=100)
    source_path: str = Field(min_length=1, max_length=500)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] | None = None

    @field_validator("source_path")
    @classmethod
    def validate_no_path_traversal(cls, v: str) -> str:
        if ".." in Path(v).parts:
            raise ValueError("source_path must not contain path traversal sequences")
        return v

    @model_validator(mode="after")
    def validate_url_source(self) -> "CampaignAssetCreate":
        if self.source_type == "url":
            parsed = urlparse(self.source_path)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("source_path must be a valid http or https URL when source_type is url")
        return self


class TemplateDefinitionCreate(BaseModel):
    template_name: str = Field(min_length=1, max_length=200)
    template_kind: str = Field(min_length=1, max_length=100)
    size_spec: str | None = Field(default=None, max_length=50)
    layout: dict[str, Any] | None = None
    default_values: dict[str, Any] | None = None


class CampaignTemplateBindingCreate(BaseModel):
    template_id: int
    override_values: dict[str, Any] | None = None


class ChatMessageRequest(BaseModel):
    campaign_id: int | None = None
    message: str = Field(min_length=1, max_length=4000)


class ComponentCreate(BaseModel):
    component_key: str = Field(min_length=1, max_length=100)
    component_kind: str = Field(default="featured-offers", max_length=100)
    display_title: str = Field(min_length=1, max_length=200)
    render_region: str | None = Field(default=None, max_length=100)
    render_mode: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] | None = None
    background_color: str | None = Field(default=None, max_length=100)
    header_accent_color: str | None = Field(default=None, max_length=100)
    footnote_text: str | None = Field(default=None, max_length=2000)
    subtitle: str | None = Field(default=None, max_length=1000)
    description_text: str | None = Field(default=None, max_length=4000)
    display_order: int = 0


class ComponentUpdate(BaseModel):
    component_key: str | None = Field(default=None, min_length=1, max_length=100)
    component_kind: str | None = Field(default=None, max_length=100)
    display_title: str | None = Field(default=None, min_length=1, max_length=200)
    render_region: str | None = Field(default=None, max_length=100)
    render_mode: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] | None = None
    background_color: str | None = Field(default=None, max_length=100)
    header_accent_color: str | None = Field(default=None, max_length=100)
    footnote_text: str | None = Field(default=None, max_length=2000)
    subtitle: str | None = Field(default=None, max_length=1000)
    description_text: str | None = Field(default=None, max_length=4000)
    display_order: int | None = None


class ComponentItemCreate(BaseModel):
    item_name: str = Field(min_length=1, max_length=200)
    item_kind: str = Field(default="service", max_length=100)
    render_role: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] | None = None
    duration_label: str | None = Field(default=None, max_length=200)
    item_value: str | None = Field(default=None, max_length=200)
    background_color: str | None = Field(default=None, max_length=100)
    description_text: str | None = Field(default=None, max_length=4000)
    terms_text: str | None = Field(default=None, max_length=2000)
    display_order: int = 0


class ComponentItemUpdate(BaseModel):
    item_name: str | None = Field(default=None, min_length=1, max_length=200)
    item_kind: str | None = Field(default=None, max_length=100)
    render_role: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] | None = None
    duration_label: str | None = Field(default=None, max_length=200)
    item_value: str | None = Field(default=None, max_length=200)
    background_color: str | None = Field(default=None, max_length=100)
    description_text: str | None = Field(default=None, max_length=4000)
    terms_text: str | None = Field(default=None, max_length=2000)
    display_order: int | None = None


class CampaignSaveRequest(BaseModel):
    commit_message: str | None = Field(default=None, max_length=500)


class ArtifactRenderRequest(BaseModel):
    artifact_type: Literal["flyer", "poster"] = "flyer"
    overwrite: bool = False
    custom_name: str | None = Field(default=None, max_length=100)


class StartupResolveRequest(BaseModel):
    direction: Literal["yaml_to_db", "db_to_yaml", "skip"]


class RuntimeGitSettingsRequest(BaseModel):
    repo_path: str | None = Field(default=None, max_length=1000)
    remote_url: str | None = Field(default=None, max_length=1000)
    remote_name: str = Field(default="origin", min_length=1, max_length=100)
    branch: str = Field(default="HEAD", min_length=1, max_length=200)
    user_name: str | None = Field(default=None, max_length=200)
    user_email: str | None = Field(default=None, max_length=320)
    push_enabled: bool = False
    credential_provider: Literal["local", "aws"] = "local"
    credential_reference: str | None = Field(default=None, max_length=1000)
    credential_secret: str | None = Field(default=None, max_length=10000)


class RuntimeGitSettingsResponse(BaseModel):
    scope: str = "global"
    repo_path: str | None = None
    remote_url: str | None = None
    remote_name: str
    branch: str
    user_name: str | None = None
    user_email: str | None = None
    push_enabled: bool
    credential_provider: str
    credential_reference: str | None = None
    credential_configured: bool
    updated_at: str | None = None


class AdminAuditLogResponse(BaseModel):
    id: int
    actor: str
    action: str
    scope: str
    metadata: dict[str, Any]
    created_at: str | None = None


class ArtifactResponse(BaseModel):
    id: int
    campaign_id: int
    artifact_type: str
    file_path: str
    checksum: str
    status: str
    created_at: str | None = None
