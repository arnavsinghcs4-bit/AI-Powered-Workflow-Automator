"""DNS-resolved SSRF protection for the http_request step.

Policy:
1. Parse the URL, resolve the hostname to IP(s) via the resolver.
2. Reject private/loopback/link-local/reserved IPs and the configured
   blocklist.
3. Pin the validated IP: rewrite the request URL to that IP and set the
   Host header to the original hostname so TLS SNI still works.
4. Re-validate on every redirect hop (the transport wraps every request,
   including ones httpx issues after a 3xx).

Decision 9 of the spec: pin the validated IP when connecting; re-validate
every redirect hop.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}
DEFAULT_BLOCKED_IPS = {
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.88.99.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "255.255.255.255/32",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
}

_NETWORKS = [ipaddress.ip_network(n) for n in DEFAULT_BLOCKED_IPS]


class SsrfError(Exception):
    """Raised when a request target fails SSRF validation."""


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return any(ip in net for net in _NETWORKS)


def resolve_and_validate(url: str) -> str:
    """Validate a URL's host and return the pinned-IP URL.

    Raises SsrfError on any violation.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfError(f"unsupported scheme: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise SsrfError("no hostname in URL")
    if hostname.lower() in BLOCKED_HOSTNAMES:
        raise SsrfError(f"blocked hostname: {hostname!r}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(hostname, port)
    except socket.gaierror as e:
        raise SsrfError(f"DNS resolution failed for {hostname!r}") from e

    pinned_ip = None
    for _family, _kind, _canon, _sa, sockaddr in infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise SsrfError(f"blocked IP {ip_str} for {hostname!r}")
        pinned_ip = ip_str
        break

    if pinned_ip is None:
        raise SsrfError(f"no resolvable address for {hostname!r}")

    pinned = parsed._replace(netloc=f"{pinned_ip}:{port}")
    return pinned.geturl()


class PinningTransport(httpx.AsyncBaseTransport):
    """httpx transport that re-validates the destination on every request."""

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Preserve the original Host header (hostname + port) so TLS SNI
        # and virtual-host routing still work against the pinned IP.
        original_host = request.headers.get("host") or request.url.host
        pinned = resolve_and_validate(str(request.url))
        request.url = httpx.URL(pinned)
        request.headers["host"] = original_host
        return await self._inner.handle_async_request(request)


def build_client(timeout: float = 10.0) -> httpx.AsyncClient:
    """Return an AsyncClient whose transport re-validates every hop."""
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        transport=PinningTransport(),
    )