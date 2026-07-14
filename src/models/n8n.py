"""
n8n integration models.
=======================

Two stored shapes (both per-user, isolated):

  user_n8n_credentials — the user's n8n instance URL + ENCRYPTED api key.
                         The plaintext key is NEVER stored or returned; only
                         `key_hint` (masked) is ever exposed.
  user_n8n_workflows   — which workflow templates this user has deployed to
                         their instance, and each one's n8n id + active state.

Request models validate what the user sends; response models guarantee we never
accidentally serialize the secret (there's simply no field for it).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class N8nCredentialCreate(BaseModel):
    # Mode "default": pakai instance n8n milik aplikasi (kredensial dari .env
    # BACKEND, tidak pernah dikirim/ditampilkan ke browser).
    use_default: bool = False
    base_url: Optional[str] = Field(default=None, description="n8n instance base URL")
    api_key: Optional[str] = Field(default=None, min_length=8, description="n8n API key (stored encrypted, never returned)")

    @field_validator("base_url")
    @classmethod
    def _clean_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().rstrip("/")
        if not v.startswith("http"):
            raise ValueError("base_url must start with http(s)://")
        return v

    @model_validator(mode="after")
    def _require_fields_when_custom(self):
        if not self.use_default and not (self.base_url and self.api_key):
            raise ValueError("base_url dan api_key wajib diisi untuk mode custom")
        return self


class N8nCredentialStatus(BaseModel):
    connected: bool
    base_url: Optional[str] = None
    key_hint: Optional[str] = None
    is_default: bool = False             
    verified: bool = False
    verified_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WorkflowInfo(BaseModel):
    workflow_key: str
    name: str
    n8n_workflow_id: Optional[str] = None
    active: bool = False
    deployed: bool = False
    updated_at: Optional[datetime] = None


class SmtpConfig(BaseModel):
    """Optional SMTP details supplied at deploy time.

    If present, the backend creates an SMTP credential ON THE USER'S n8n
    instance via its public API (POST /api/v1/credentials) and attaches it to
    the workflow's Email Send node — so the user never opens the n8n editor.
    Like the n8n API key, the password is used once and never stored by us.
    """
    host: str = Field(..., description="SMTP host, e.g. smtp.gmail.com")
    port: int = Field(default=465)
    user: str = Field(..., description="SMTP username / login email")
    password: str = Field(..., min_length=1, description="SMTP password or app password")
    secure: bool = Field(default=True, description="TLS/SSL (465=true, 587 usually false+STARTTLS)")
    from_email: Optional[str] = Field(default=None, description="From address; defaults to user")


class DeployRequest(BaseModel):
    workflow_key: str = Field(default="economic-report")
    cron: Optional[str] = Field(default="0 8 * * *")
    # Bahasa email yang dikirim workflow ini ("en" | "id").
    language: str = Field(default="en")
    smtp: Optional[SmtpConfig] = None
    # Pakai SMTP default aplikasi (dari .env backend) — kredensial tidak pernah
    # terlihat user. Mengalahkan `smtp` jika keduanya diisi.
    use_default_smtp: bool = False

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        v = (v or "en").lower().strip()
        if v not in ("en", "id"):
            raise ValueError("language harus 'en' atau 'id'")
        return v


class ActiveToggle(BaseModel):
    active: bool


class N8nStatusResponse(BaseModel):
    credential: N8nCredentialStatus
    workflows: List[WorkflowInfo] = Field(default_factory=list)
    available_templates: List[str] = Field(default_factory=list)