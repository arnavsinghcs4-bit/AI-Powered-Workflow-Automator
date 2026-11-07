"""Tests for health check endpoint."""
import pytest


@pytest.mark.asyncio
async def test_health_check_ok(client):
    """Test health check when DB and Redis are available."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"
    assert data["redis"] == "connected"


@pytest.mark.asyncio
async def test_root_endpoint(client):
    """Test root endpoint."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
