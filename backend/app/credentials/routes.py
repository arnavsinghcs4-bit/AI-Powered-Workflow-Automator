"""Credentials API routes for Phase 4 secrets management."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.database import get_session
from app.auth.dependencies import get_current_user
from app.models import User
from app.credentials.schemas import (
    CredentialCreate,
    CredentialInDB,
    CredentialUpdate,
    CredentialListItem,
)
from app.credentials.service import (
    create_credential,
    get_credential,
    list_credentials,
    delete_credential,
    update_credential,
    CredentialNotFound,
    CredentialValidationError,
)

router = APIRouter(prefix="/credentials", tags=["credentials"])

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=config.REDIS_URL,
    enabled=config.ENABLE_RATE_LIMITING,
)


@router.post(
    "/",
    response_model=CredentialInDB,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(f"{config.RATE_LIMIT_REGISTER}/minute")
async def create_credential_endpoint(
    request: Request,
    payload: CredentialCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new credential for the authenticated user."""
    try:
        return await create_credential(db, payload, current_user.id)
    except CredentialValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/",
    response_model=list[CredentialListItem],
)
async def list_credentials_endpoint(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List credentials for the authenticated user (names and kinds only)."""
    return await list_credentials(db, current_user.id)


@router.get(
    "/{credential_id}",
    response_model=CredentialInDB,
)
async def get_credential_endpoint(
    credential_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get a credential by ID (owner-scoped, never returns decrypted value)."""
    try:
        return await get_credential(db, credential_id, current_user.id)
    except CredentialNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put(
    "/{credential_id}",
    response_model=CredentialInDB,
)
async def update_credential_endpoint(
    credential_id: int,
    payload: CredentialUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Rotate a credential's payload (owner-scoped)."""
    try:
        return await update_credential(db, credential_id, current_user.id, payload)
    except CredentialNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CredentialValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_credential_endpoint(
    credential_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a credential (owner-scoped)."""
    try:
        await delete_credential(db, credential_id, current_user.id)
    except CredentialNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))