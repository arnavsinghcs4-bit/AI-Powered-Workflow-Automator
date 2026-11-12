"""Secret redaction for step outputs and logs.

All step outputs pass through this before being persisted or emitted
to avoid leaking credentials from pipeline definitions.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

_SENSITIVE_PATTERNS = [
    ("api_key", r'(?i)api[_-]?key\s*[=:]\s*"([^"]{4,})"'),
    ("secret", r'(?i)"?secret"?\s*[=:]\s*"([^"]{4,})"'),
    ("password", r'(?i)"?password"?\s*[=:]\s*"([^"]{4,})"'),
    ("token", r'(?i)"?token"?\s*[=:]\s*"([^"]{20,})"'),
]


class SecretRedactionError(Exception):
    """Raised when secret redaction fails."""


def redact(value: Any) -> Any:
    """Walk a value tree and redact anything that looks like a secret."""
    if isinstance(value, str):
        for _label, pattern in _SENSITIVE_PATTERNS:
            value = re.sub(pattern, '"<redacted>"', value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class RedactedResponse(BaseModel):
    """Pydantic model wrapping a response body after redaction."""

    data: dict[str, Any]

    class Config:
        arbitrary_types_allowed = True

    @staticmethod
    def build(data: dict[str, Any]) -> "RedactedResponse":
        return RedactedResponse(data=redact(data))