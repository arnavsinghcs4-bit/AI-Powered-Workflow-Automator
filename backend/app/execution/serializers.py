"""Secret redaction for step outputs and logs.

All step outputs pass through this before being persisted or emitted
to avoid leaking credentials from pipeline definitions.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

# Regex patterns for inline secrets in strings
_SENSITIVE_PATTERNS = [
    ("api_key", r'(?i)api[_-]?key\s*[=:]\s*"([^"]{4,})"'),
    ("secret", r'(?i)"?secret"?\s*[=:]\s*"([^"]{4,})"'),
    ("password", r'(?i)"?password"?\s*[=:]\s*"([^"]{4,})"'),
    ("token", r'(?i)"?token"?\s*[=:]\s*"([^"]{20,})"'),
]

# Field names that should be redacted regardless of value
_SENSITIVE_FIELDS = {
    "api_key",
    "secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "authorization",
    "auth",
    "credential",
    "encrypted_value",
    "secret_key",
    "signing_key",
    "webhook_secret",
}


class SecretRedactionError(Exception):
    """Raised when secret redaction fails."""


def redact(value: Any) -> Any:
    """Walk a value tree and redact anything that looks like a secret."""
    if isinstance(value, str):
        # First check if the entire string looks like a secret value (long random string)
        if _looks_like_secret(value):
            return "<redacted>"
        for _label, pattern in _SENSITIVE_PATTERNS:
            value = re.sub(pattern, '"<redacted>"', value)
        return value
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            # Redact sensitive field names entirely
            if k.lower() in _SENSITIVE_FIELDS:
                result[k] = "<redacted>"
            else:
                result[k] = redact(v)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _looks_like_secret(value: str) -> bool:
    """Check if a string looks like a secret (base64, hex, or long random)."""
    # Skip short strings
    if len(value) < 20:
        return False
    # Base64-like (with possible padding)
    if re.match(r"^[A-Za-z0-9+/]{20,}={0,2}$", value):
        return True
    # Long hex string
    if re.match(r"^[0-9a-fA-F]{32,}$", value):
        return True
    # JWT-like (three base64 parts separated by dots)
    if re.match(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$", value):
        return True
    return False


class RedactedResponse(BaseModel):
    """Pydantic model wrapping a response body after redaction."""

    data: dict[str, Any]

    class Config:
        arbitrary_types_allowed = True

    @staticmethod
    def build(data: dict[str, Any]) -> "RedactedResponse":
        return RedactedResponse(data=redact(data))
