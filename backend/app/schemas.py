"""Schemas for request/response DTOs."""

from pydantic import BaseModel


class HealthCheck(BaseModel):
    """Health check response."""

    status: str
    db: str
    redis: str
