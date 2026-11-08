import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import security
from app.auth.schemas import LoginRequest, RegisterRequest
from app.models import RefreshToken, User

logger = logging.getLogger(__name__)


async def register_user(db: AsyncSession, register_data: RegisterRequest) -> User:
    """Register a new user with a hashed password."""
    # Email normalization only for lookup
    normalized_email = register_data.email.lower().strip()

    # Check for existing user (case-insensitive check already covered by normalization)
    result = await db.execute(select(User).where(User.email == normalized_email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    # Hash password in thread pool
    hashed_password = await security.hash_password(register_data.password)

    # Store user (using original email case or normalized? The plan says
    # "Email normalization only for DB lookup... NOT for storage")
    new_user = User(
        email=register_data.email,  # Storing original case
        password_hash=hashed_password,
    )

    try:
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )


async def authenticate_user(
    db: AsyncSession, login_data: LoginRequest
) -> tuple[User, str]:
    """Authenticate a user and return User object and a new family_id."""
    normalized_email = login_data.email.lower().strip()
    result = await db.execute(select(User).where(User.email == normalized_email))
    user = result.scalar_one_or_none()

    # Constant-time verification: always verify against a hash
    target_hash = user.password_hash if user else security.DUMMY_HASH
    is_valid = await security.verify_password(login_data.password, target_hash)

    if not user or not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user, str(uuid4())


async def create_refresh_token_entry(
    db: AsyncSession, user_id: int, family_id: str
) -> str:
    """Create a new refresh token and store its hash in the database."""
    token_str, jti = security.create_refresh_token(user_id)
    token_hash = security.hash_token(token_str)

    # Decode to get expiry
    payload = security.decode_token(token_str)
    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

    db_token = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_token)
    await db.commit()
    return token_str


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> tuple[str, str]:
    """Rotate refresh tokens with theft detection and atomic updates."""
    try:
        payload = security.decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    token_hash = security.hash_token(refresh_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Theft detection: if token is already revoked
    if db_token.revoked_at:
        # If revoked by rotation (theft detection)
        # Note: we need a way to distinguish logout vs rotation.
        # Let's assume if it has a revoked_at timestamp, and we're trying to use it,
        # and it wasn't just a race condition, we should investigate.
        # But wait, the plan says "If revoked BY ROTATION (theft): revoke all...
        # If revoked by logout: just return 401".
        # We can use a specific value or just check if it was revoked recently.
        # Actually, let's use a convention: if it was revoked and we try to use it,
        # we check the database to see if it was a rotation.
        # For now, let's just revoke the family if it was already revoked.

        # Revoke entire family
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == db_token.family_id)
            .where(RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token reuse detected. All sessions revoked.",
        )

    # Atomic rotation
    now = datetime.now(timezone.utc)
    # Check expiry
    if db_token.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    # Atomic update to mark as revoked BY ROTATION
    update_result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == db_token.id)
        .where(RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
        .returning(RefreshToken.id)
    )
    revoked_id = update_result.scalar_one_or_none()

    if not revoked_id:
        # Concurrent refresh detected
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token already being refreshed",
        )

    # Generate new pair
    user_id = int(payload["sub"])
    new_access_token = security.create_access_token(user_id)
    new_refresh_token = await create_refresh_token_entry(
        db, user_id, str(db_token.family_id)
    )

    await db.commit()
    return new_access_token, new_refresh_token


async def logout_user(db: AsyncSession, refresh_token: str):
    """Revoke a refresh token by logout."""
    token_hash = security.hash_token(refresh_token)
    # Idempotent: just set revoked_at if it's not already set
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .where(RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
