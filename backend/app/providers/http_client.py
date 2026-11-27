"""Shared SSRF-protected HTTP client provider."""

from typing import Dict, Optional

import httpx

from app.providers.base import HTTPClient, HTTPResponse
from app.steps.ssrf import build_client as build_ssrf_client, SsrfError


class SharedHTTPClient(HTTPClient):
    """SSRF-protected HTTP client for use by webhook_out and other steps."""

    def __init__(self, default_timeout: float = 30.0, max_redirects: int = 5):
        self.default_timeout = default_timeout
        self.max_redirects = max_redirects
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self, timeout: float) -> httpx.AsyncClient:
        """Get or create an SSRF-protected client."""
        if self._client is None:
            self._client = build_ssrf_client(timeout=timeout)
        return self._client

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[bytes] = None,
        timeout: float = 30.0,
        follow_redirects: bool = True,
        max_redirects: int = 5,
    ) -> HTTPResponse:
        """Make an HTTP request with SSRF protection."""
        client = self._get_client(timeout)
        try:
            response = await client.request(
                method,
                url,
                headers=headers,
                content=content,
                follow_redirects=follow_redirects,
            )
            return HTTPResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                body=response.content,
                url=str(response.url),
            )
        except SsrfError as e:
            raise SsrfError(str(e))
        except httpx.HTTPError as e:
            raise e

    async def close(self) -> None:
        """Close the client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None