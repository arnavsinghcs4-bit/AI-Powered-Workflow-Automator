"""Provider abstractions for Phase 4."""

from app.providers.base import HTTPClient, HTTPResponse, EmailProvider, EmailResult, LLMProvider, LLMResult
from app.providers.http_client import SharedHTTPClient
from app.providers.smtp_provider import SMTPProvider
from app.providers.anthropic_provider import AnthropicProvider

__all__ = [
    "HTTPClient",
    "HTTPResponse",
    "EmailProvider",
    "EmailResult",
    "LLMProvider",
    "LLMResult",
    "SharedHTTPClient",
    "SMTPProvider",
    "AnthropicProvider",
]