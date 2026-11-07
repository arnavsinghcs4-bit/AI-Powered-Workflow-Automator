"""Schemas for request/response DTOs."""
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class HealthCheck(BaseModel):
    """Health check response."""
    status: str
    db: str
    redis: str
