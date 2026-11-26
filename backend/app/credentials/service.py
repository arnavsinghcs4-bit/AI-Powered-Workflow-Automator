"""Credentials service for Phase 4 secrets management."""

import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from cryptography.fernet import Fernet,MultiFernet
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.credentials.models import Credential, LLMCall
from app.credentials.schemas import (
    CredentialCreate,
    CredentialInDB,
    CredentialUpdate,
    CredentialListItem,
    CREDENTIAL_PAYLOAD_SCHEMAS,
    CredentialKind,
)
from app.models import User


class CredentialNotFound(Exception):
    """Raised when a credential is not found."""
    pass


class CredentialValidationError(Exception):
    """Raised when credential validation fails."""
    pass


class EncryptionKeyError(Exception):
    """Raised when encryption key is missing or invalid."""
    pass


def _get_encryption() -> MultiFernet:
    """Build the encryption object from SECRETS_ENCRYPTION_KEY (comma-separated for rotation)."""
    key_env = os.getenv("SECRETS_ENCRYPTION_KEY")
    if not key_env:
        raise EncryptionKeyError("SECRETS_ENCRYPTION_KEY environment variable is required")

    # First key encrypts; all keys can decrypt (rotation).
    keys = [k.strip() for k in key_env.split(",") if k.strip()]
    if not keys:
        raise EncryptionKeyError("SECRETS_ENCRYPTION_KEY must contain at least one key")

    fernets = []
    for key in keys:
        try:
            fernets.append(Fernet(key.encode()))
        except ValueError as e:
            raise EncryptionKeyError("Invalid Fernet key in SECRETS_ENCRYPTION_KEY") from e
    return MultiFernet(fernets)


# Global encryption instance - lazily initialized
_encryption: Optional[MultiFernet] = None


def get_encryption() -> MultiFernet:
    """Get the global encryption instance, initializing lazily."""
    global _encryption
    if _encryption is None:
        _encryption = _get_encryption()
    return _encryption


def encrypt(value: str) -> bytes:
    """Encrypt a string value."""
    enc = get_encryption()
    return enc.encrypt(value.encode())


def decrypt(encrypted: bytes) -> str:
    """Decrypt an encrypted value."""
    enc = get_encryption()
    return enc.decrypt(encrypted).decode()


async def create_credential(
    db: AsyncSession,
    payload: CredentialCreate,
    user_id: int,
) -> CredentialInDB:
    """Create a new credential for the user."""
    # Validate payload against kind-specific schema
    _validate_payload(payload.kind, payload.payload)

    # Check for duplicate name
    existing = await db.execute(
        select(Credential).where(
            Credential.user_id == user_id,
            Credential.name == payload.name,
        )
    )
    if existing.scalar_one_or_none():
        raise CredentialValidationError(f"Credential '{payload.name}' already exists")

    # Serialize and encrypt payload
    payload_json = json.dumps(payload.payload)
    encrypted = encrypt(payload_json)

    credential = Credential(
        user_id=user_id,
        name=payload.name,
        kind=payload.kind.value,
        encrypted_value=encrypted,
    )
    db.add(credential)
    await db.commit()
    await db.refresh(credential)

    return CredentialInDB(
        id=credential.id,
        user_id=credential.user_id,
        name=credential.name,
        kind=CredentialKind(credential.kind),
        created_at=credential.created_at.isoformat(),
        updated_at=credential.updated_at.isoformat(),
    )


async def get_credential(
    db: AsyncSession,
    credential_id: int,
    user_id: int,
) -> CredentialInDB:
    """Get a credential by ID (owner-scoped)."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.user_id == user_id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise CredentialNotFound(f"Credential {credential_id} not found")
    return CredentialInDB(
        id=credential.id,
        user_id=credential.user_id,
        name=credential.name,
        kind=CredentialKind(credential.kind),
        created_at=credential.created_at.isoformat(),
        updated_at=credential.updated_at.isoformat(),
    )


async def get_credential_by_name(
    db: AsyncSession,
    name: str,
    user_id: int,
) -> CredentialInDB:
    """Get a credential by name (owner-scoped)."""
    result = await db.execute(
        select(Credential).where(
            Credential.user_id == user_id,
            Credential.name == name,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise CredentialNotFound(f"Credential '{name}' not found")
    return CredentialInDB(
        id=credential.id,
        user_id=credential.user_id,
        name=credential.name,
        kind=CredentialKind(credential.kind),
        created_at=credential.created_at.isoformat(),
        updated_at=credential.updated_at.isoformat(),
    )


async def decrypt_credential(
    db: AsyncSession,
    credential_id: int,
    user_id: int,
) -> dict:
    """Decrypt and return credential payload (for worker execution only)."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.user_id == user_id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise CredentialNotFound(f"Credential {credential_id} not found")

    decrypted = decrypt(credential.encrypted_value)
    return json.loads(decrypted)


async def list_credentials(
    db: AsyncSession,
    user_id: int,
) -> List[CredentialListItem]:
    """List user's credentials (names and kinds only, no values)."""
    result = await db.execute(
        select(Credential).where(Credential.user_id == user_id).order_by(Credential.name)
    )
    credentials = result.scalars().all()
    return [
        CredentialListItem(
            id=c.id,
            name=c.name,
            kind=CredentialKind(c.kind),
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )
        for c in credentials
    ]


async def update_credential(
    db: AsyncSession,
    credential_id: int,
    user_id: int,
    payload: CredentialUpdate,
) -> CredentialInDB:
    """Update (rotate) a credential's payload."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.user_id == user_id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise CredentialNotFound(f"Credential {credential_id} not found")

    # Validate new payload against existing kind
    _validate_payload(CredentialKind(credential.kind), payload.payload)

    # Serialize and encrypt new payload
    payload_json = json.dumps(payload.payload)
    encrypted = encrypt(payload_json)

    credential.encrypted_value = encrypted
    await db.commit()
    await db.refresh(credential)

    return CredentialInDB(
        id=credential.id,
        user_id=credential.user_id,
        name=credential.name,
        kind=CredentialKind(credential.kind),
        created_at=credential.created_at.isoformat(),
        updated_at=credential.updated_at.isoformat(),
    )


async def delete_credential(
    db: AsyncSession,
    credential_id: int,
    user_id: int,
) -> None:
    """Delete a credential (owner-scoped)."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.user_id == user_id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise CredentialNotFound(f"Credential {credential_id} not found")

    await db.delete(credential)
    await db.commit()


async def get_llm_token_usage(db: AsyncSession, user_id: int) -> int:
    """Get total tokens used by a user in the current budget window (1 hour)."""
    window_start = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await db.execute(
        select(func.coalesce(func.sum(LLMCall.input_tokens + LLMCall.output_tokens), 0)).where(
            LLMCall.user_id == user_id,
            LLMCall.created_at >= window_start,
        )
    )
    return result.scalar() or 0


async def record_llm_call(
    db: AsyncSession,
    step_run_id: int,
    user_id: int,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    status: str,
) -> LLMCall:
    """Record an LLM call for token budget tracking."""
    call = LLMCall(
        step_run_id=step_run_id,
        user_id=user_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        status=status,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call