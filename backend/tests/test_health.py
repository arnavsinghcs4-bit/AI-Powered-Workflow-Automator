"""Tests for health check endpoint."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_health_check_ok(client):
    """Test health check when DB and Redis are available (mocked)."""
    # Mock the database session execution
    with patch("app.health.async_session_maker") as mock_session_maker:
        # Create a mock async context manager
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session_maker.return_value.__aenter__.return_value = mock_session

        # Mock Redis
        with patch("app.health.redis.from_url") as mock_redis:
            mock_redis_client = AsyncMock()
            mock_redis_client.ping = AsyncMock(return_value=True)
            mock_redis_client.close = AsyncMock()
            mock_redis.return_value = mock_redis_client

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
