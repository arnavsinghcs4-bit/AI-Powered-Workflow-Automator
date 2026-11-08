from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, validator


class UserBase(BaseModel):
    email: EmailStr


class RegisterRequest(UserBase):
    password: str = Field(..., min_length=10, max_length=128)

    @validator("password")
    def password_not_too_simple(cls, v):
        # Basic check to ensure it's not just one character repeated
        if len(set(v)) < 4:
            raise ValueError("Password is too simple")
        return v


class LoginRequest(UserBase):
    password: str


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
