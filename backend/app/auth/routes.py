from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import dependencies, security, service
from app.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.config import config
from app.database import get_session
from app.models import User

router = APIRouter()

# Initialize limiter with Redis backend
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=config.REDIS_URL,
    enabled=config.ENABLE_RATE_LIMITING,
)


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit(f"{config.RATE_LIMIT_REGISTER}/minute")
async def register(
    request: Request,
    register_data: RegisterRequest,
    db: AsyncSession = Depends(get_session),
):
    """Register a new user."""
    return await service.register_user(db, register_data)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(f"{config.RATE_LIMIT_LOGIN}/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_session),
):
    """Authenticate a user and return access and refresh tokens."""
    user, family_id = await service.authenticate_user(db, login_data)
    access_token = security.create_access_token(user.id)
    refresh_token = await service.create_refresh_token_entry(db, user.id, family_id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    refresh_data: RefreshRequest,
    db: AsyncSession = Depends(get_session),
):
    """Refresh access token using refresh token rotation."""
    access_token, new_refresh_token = await service.refresh_tokens(
        db, refresh_data.refresh_token
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    refresh_data: RefreshRequest,
    db: AsyncSession = Depends(get_session),
):
    """Logout by revoking the refresh token."""
    await service.logout_user(db, refresh_data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(dependencies.get_current_user)):
    """Get the current authenticated user's details."""
    return current_user
