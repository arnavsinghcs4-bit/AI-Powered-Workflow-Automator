"""Abstract provider interfaces for Phase 4."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class HTTPResponse:
    """HTTP response from provider."""
    status_code: int
    headers: Dict[str, str]
    body: bytes
    url: str = ""


class HTTPClient:
    """Abstract HTTP client interface."""
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[bytes] = None,
        timeout: float = 30.0,
    ) -> HTTPResponse:
        raise NotImplementedError


@dataclass
class EmailResult:
    """Result from sending email."""
    sent: bool
    recipients: List[str]
    error: Optional[str] = None


class EmailProvider:
    """Abstract email provider interface."""
    async def send(
        self,
        *,
        to: List[str],
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> EmailResult:
        raise NotImplementedError


@dataclass
class LLMResult:
    """Result from LLM completion."""
    output: Dict[str, Any]
    input_tokens: int
    output_tokens: int
    latency_ms: int


class LLMProvider:
    """Abstract LLM provider interface."""
    async def complete(
        self,
        *,
        model: str,
        prompt: str,
        json_schema: Dict[str, Any],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResult:
        raise NotImplementedError