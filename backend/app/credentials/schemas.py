"""Credentials schemas for Phase 4 secrets management."""

import re
from enum import Enum
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field, field_validator


class CredentialKind(str, Enum):
    """Credential kind enumeration."""
    API_KEY = "api_key"
    SMTP = "smtp"
    BEARER = "bearer"
    BASIC = "basic"


# Per-kind payload schemas
class ApiKeyPayload(BaseModel):
    """API key credential payload."""
    api_key: str = Field(..., min_length=1)


class SmtpPayload(BaseModel):
    """SMTP credential payload."""
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    sender_email: str = Field(..., min_length=1)
    tls_mode: Literal["starttls", "ssl", "none"] = "starttls"

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        # Basic hostname validation - no CR/LF
        if "\r" in v or "\n" in v:
            raise ValueError("Host must not contain CR/LF")
        return v

    @field_validator("username", "password", "sender_email")
    @classmethod
    def validate_no_crlf(cls, v: str) -> str:
        if "\r" in v or "\n" in v:
            raise ValueError("Must not contain CR/LF")
        return v


class BearerPayload(BaseModel):
    """Bearer token credential payload."""
    token: str = Field(..., min_length=1)


class BasicPayload(BaseModel):
    """Basic auth credential payload."""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

    @field_validator("username", "password")
    @classmethod
    def validate_no_crlf(cls, v: str) -> str:
        if "\r" in v or "\n" in v:
            raise ValueError("Must not contain CR/LF")
        return v


CREDENTIAL_PAYLOAD_SCHEMAS: Dict[CredentialKind, type[BaseModel]] = {
    CredentialKind.API_KEY: ApiKeyPayload,
    CredentialKind.SMTP: SmtpPayload,
    CredentialKind.BEARER: BearerPayload,
    CredentialKind.BASIC: BasicPayload,
}


def validate_credential_name(name: str) -> str:
    """Validate credential name matches ^[a-z][a-z0-9_]{0,63}$."""
    if not re.match(r"^[a-z][a-z0-9_]{0,63}$", name):
        raise ValueError(
            "Credential name must match ^[a-z][a-z0-9_]{0,63}$ "
            "(lowercase letter, then lowercase letters/numbers/underscores, max 64 chars)"
        )
    return name


class CredentialBase(BaseModel):
    """Base credential schema."""
    name: str = Field(..., min_length=1, max_length=64)
    kind: CredentialKind


class CredentialCreate(CredentialBase):
    """Create credential request."""
    payload: Dict[str, Any] = Field(..., description="Credential payload, validated per kind")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_credential_name(v)

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, v: Dict[str, Any], info) -> Dict[str, Any]:
        kind = info.data.get("kind")
        if kind and kind in CREDENTIAL_PAYLOAD_SCHEMAS:
            CREDENTIAL_PAYLOAD_SCHEMAS[kind].model_validate(v)
        return v


class CredentialUpdate(BaseModel):
    """Update credential request (rotation)."""
    payload: Dict[str, Any] = Field(..., description="New credential payload, validated per kind")


class CredentialInDB(CredentialBase):
    """Credential response (never includes decrypted value)."""
    id: int
    user_id: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CredentialListItem(BaseModel):
    """Credential list item (names and kinds only)."""
    id: int
    name: str
    kind: CredentialKind
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True