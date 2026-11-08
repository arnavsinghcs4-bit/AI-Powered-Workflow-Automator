import asyncio
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt

from app.config import config

# Dummy hash created at startup with the same cost factor (12)
# to avoid timing attacks on non-existent users
_DUMMY_SALT = bcrypt.gensalt(rounds=12)
_DUMMY_PASSWORD = b"dummy_password_for_timing_safety"
_PREHASHED_DUMMY = base64.b64encode(hashlib.sha256(_DUMMY_PASSWORD).digest())
DUMMY_HASH = bcrypt.hashpw(_PREHASHED_DUMMY, _DUMMY_SALT).decode("utf-8")


def _prehash_password(password: str) -> bytes:
    """SHA-256 + base64 the password to avoid bcrypt's 72-byte limit."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def _sync_hash_password(password: str) -> str:
    prehashed = _prehash_password(password)
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(prehashed, salt).decode("utf-8")


def _sync_verify_password(plain_password: str, hashed_password: str) -> bool:
    prehashed = _prehash_password(plain_password)
    try:
        return bcrypt.checkpw(prehashed, hashed_password.encode("utf-8"))
    except Exception:
        return False


async def hash_password(password: str) -> str:
    """Hash a password using SHA-256 + base64 + bcrypt in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_hash_password, password)


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _sync_verify_password, plain_password, hashed_password
    )


def create_token(
    user_id: int,
    token_type: str,
    expires_delta: timedelta,
    jti: str | None = None,
) -> str:
    """Create a signed JWT token with sub, type, iat, exp, and jti claims."""
    now = datetime.now(timezone.utc)
    if jti is None:
        jti = str(uuid4())

    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": jti,
    }

    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def create_access_token(user_id: int) -> str:
    return create_token(
        user_id=user_id,
        token_type="access",
        expires_delta=timedelta(minutes=config.JWT_ACCESS_TOKEN_LIFETIME),
    )


def create_refresh_token(user_id: int, jti: str | None = None) -> tuple[str, str]:
    """Returns (token_string, jti)."""
    if jti is None:
        jti = str(uuid4())
    token = create_token(
        user_id=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=config.JWT_REFRESH_TOKEN_LIFETIME),
        jti=jti,
    )
    return token, jti


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    return jwt.decode(
        token,
        config.JWT_SECRET,
        algorithms=["HS256"],
        options={"require": ["sub", "type", "iat", "exp", "jti"]},
    )


def hash_token(token: str) -> str:
    """Hash a refresh token using SHA-256 for DB storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
