"""Tests for app.steps.ssrf."""

import ipaddress

import httpx
import pytest

from app.steps.ssrf import (
    DEFAULT_BLOCKED_IPS,
    PinningTransport,
    SsrfError,
    _is_blocked_ip,
    build_client,
    resolve_and_validate,
)


def test_rejects_ftp_scheme():
    with pytest.raises(SsrfError):
        resolve_and_validate("ftp://example.com")


def test_rejects_localhost():
    with pytest.raises(SsrfError):
        resolve_and_validate("http://localhost/")


def test_rejects_metadata_hostname():
    with pytest.raises(SsrfError):
        resolve_and_validate("http://metadata.google.internal/")


def test_rejects_private_ip():
    with pytest.raises(SsrfError):
        resolve_and_validate("http://10.0.0.1/")


def test_rejects_loopback_ipv6():
    with pytest.raises(SsrfError):
        resolve_and_validate("http://[::1]/")


def test_rejects_link_local():
    with pytest.raises(SsrfError):
        resolve_and_validate("http://169.254.169.254/latest/meta-data/")


def test_is_blocked_ip_networks_match_spec():
    nets = [ipaddress.ip_network(n) for n in DEFAULT_BLOCKED_IPS]
    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.1.1", "::1"):
        assert any(ipaddress.ip_address(ip) in n for n in nets)


def test_public_ip_not_blocked():
    assert not _is_blocked_ip("8.8.8.8")


def test_pinning_transport_rewrites_url_and_sets_host(monkeypatch):
    captured = {}

    class FakeInner:
        async def handle_async_request(self, request):
            captured["url"] = str(request.url)
            captured["host"] = request.headers.get("host")
            return httpx.Response(200)

    transport = PinningTransport()
    transport._inner = FakeInner()

    request = httpx.Request("GET", "http://example.com:8080/path")
    request.headers["host"] = "example.com:8080"

    import asyncio

    response = asyncio.run(transport.handle_async_request(request))
    assert response.status_code == 200
    # The pinned IP must be in the URL and the original hostname preserved.
    assert captured["url"].startswith("http://")
    assert "example.com" not in captured["url"]
    assert captured["host"] == "example.com:8080"


def test_pinning_transport_rejects_blocked(monkeypatch):
    transport = PinningTransport()

    class FakeInner:
        async def handle_async_request(self, request):
            raise AssertionError("should not be called")

    transport._inner = FakeInner()

    request = httpx.Request("GET", "http://localhost:8080/")

    import asyncio

    with pytest.raises(SsrfError):
        asyncio.run(transport.handle_async_request(request))


def test_build_client_uses_pinning_transport():
    client = build_client()
    assert isinstance(client._transport, PinningTransport)
