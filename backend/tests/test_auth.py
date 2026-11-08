"""Authentication integration tests - focused on core Phase 2 endpoints."""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import security, service
from app.main import app
from app.models import RefreshToken, User


@pytest.fixture
def override_config(monkeypatch):
    """Override config for tests."""
    monkeypatch.setenv("ENABLE_RATE_LIMITING", "false")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-at-least-32-characters-long-1234")
    monkeypatch.setenv("ENV", "test")


@pytest.fixture
async def client(db_session, override_config):
    """Create test client with dependency overrides."""
    from app.database import get_session

    async def override_get_session():
        return db_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def clean_db(db_session):
    """Clean test database."""
    await db_session.execute(text("DELETE FROM refresh_tokens CASCADE"))
    await db_session.execute(text("DELETE FROM users CASCADE"))
    await db_session.commit()
    yield db_session


@pytest.fixture
async def test_user(clean_db):
    """Create a test user."""
    email = "test@example.com"
    password = "SecurePassword123"
    hashed = await security.hash_password(password)
    user = User(email=email, password_hash=hashed)
    clean_db.add(user)
    await clean_db.commit()
    await clean_db.refresh(user)
    return {"user": user, "password": password, "email": email}


# ============================================================================
# REGISTER TESTS
# ============================================================================

async def test_register_success(client, clean_db):
    """POST /auth/register - successful registration."""
    response = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "SecurePassword123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert data["id"] is not None
    assert "password_hash" not in data


async def test_register_duplicate_email(client, test_user):
    """POST /auth/register - rejects duplicate email."""
    response = await client.post(
        "/auth/register",
        json={"email": test_user["email"], "password": "DifferentPass123"},
    )
    assert response.status_code == 409


async def test_register_duplicate_email_case_insensitive(client, test_user):
    """POST /auth/register - rejects duplicate with different case."""
    response = await client.post(
        "/auth/register",
        json={"email": test_user["email"].upper(), "password": "DifferentPass123"},
    )
    assert response.status_code == 409


async def test_register_invalid_email(client, clean_db):
    """POST /auth/register - rejects invalid email."""
    response = await client.post(
        "/auth/register",
        json={"email": "invalid-email", "password": "SecurePassword123"},
    )
    assert response.status_code == 422


async def test_register_short_password(client, clean_db):
    """POST /auth/register - rejects password < 10 chars."""
    response = await client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "Short1"},
    )
    assert response.status_code == 422


async def test_register_long_password(client, clean_db):
    """POST /auth/register - rejects password > 128 chars."""
    response = await client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "a" * 129},
    )
    assert response.status_code == 422


async def test_register_password_not_returned(client, clean_db):
    """POST /auth/register - password never in response."""
    response = await client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "SecurePassword123"},
    )
    data_str = str(response.json()).lower()
    assert "password_hash" not in data_str


# ============================================================================
# LOGIN TESTS
# ============================================================================

async def test_login_success(client, test_user):
    """POST /auth/login - successful login."""
    response = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"].split(".")) == 3
    assert len(data["refresh_token"].split(".")) == 3


async def test_login_wrong_password(client, test_user):
    """POST /auth/login - rejects wrong password."""
    response = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": "WrongPassword123"},
    )
    assert response.status_code == 401
    assert "incorrect" in response.json()["detail"].lower()


async def test_login_unknown_email(client, clean_db):
    """POST /auth/login - rejects unknown email."""
    response = await client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "SomePassword123"},
    )
    assert response.status_code == 401
    assert "incorrect" in response.json()["detail"].lower()


async def test_login_email_case_insensitive(client, test_user):
    """POST /auth/login - email lookup is case-insensitive."""
    response = await client.post(
        "/auth/login",
        json={"email": test_user["email"].upper(), "password": test_user["password"]},
    )
    assert response.status_code == 200


async def test_login_token_claims(client, test_user):
    """POST /auth/login - tokens have required JWT claims."""
    response = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    data = response.json()

    access_payload = security.decode_token(data["access_token"])
    assert access_payload["type"] == "access"
    assert access_payload["sub"] == str(test_user["user"].id)
    assert "exp" in access_payload
    assert "iat" in access_payload
    assert "jti" in access_payload

    refresh_payload = security.decode_token(data["refresh_token"])
    assert refresh_payload["type"] == "refresh"
    assert refresh_payload["sub"] == str(test_user["user"].id)


async def test_login_creates_refresh_token_entry(client, clean_db, test_user):
    """POST /auth/login - creates refresh_tokens DB entry."""
    response = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    data = response.json()

    token_hash = security.hash_token(data["refresh_token"])
    result = await clean_db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    db_token = result.scalar_one_or_none()
    assert db_token is not None
    assert db_token.user_id == test_user["user"].id
    assert db_token.revoked_at is None


# ============================================================================
# REFRESH TESTS
# ============================================================================

async def test_refresh_success(client, test_user):
    """POST /auth/refresh - refreshes tokens successfully."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    old_token = login.json()["refresh_token"]

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": old_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["refresh_token"] != old_token


async def test_refresh_rotation_revokes_old(client, test_user):
    """POST /auth/refresh - old token is revoked after rotation."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    old_token = login.json()["refresh_token"]

    await client.post("/auth/refresh", json={"refresh_token": old_token})

    # Try to use old token again
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": old_token},
    )
    assert response.status_code == 401


async def test_refresh_maintains_family(client, clean_db, test_user):
    """POST /auth/refresh - maintains same family_id across rotations."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    token1 = login.json()["refresh_token"]

    hash1 = security.hash_token(token1)
    result = await clean_db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash1)
    )
    family_id = result.scalar_one_or_none().family_id

    refresh1 = await client.post("/auth/refresh", json={"refresh_token": token1})
    token2 = refresh1.json()["refresh_token"]

    hash2 = security.hash_token(token2)
    result = await clean_db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash2)
    )
    assert result.scalar_one_or_none().family_id == family_id


async def test_refresh_theft_detection(client, clean_db, test_user):
    """POST /auth/refresh - reusing revoked token revokes entire family."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    token1 = login.json()["refresh_token"]

    hash1 = security.hash_token(token1)
    result = await clean_db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash1)
    )
    family_id = result.scalar_one_or_none().family_id

    # Refresh twice
    r1 = await client.post("/auth/refresh", json={"refresh_token": token1})
    token2 = r1.json()["refresh_token"]

    await client.post("/auth/refresh", json={"refresh_token": token2})

    # Reuse token1 (should trigger theft detection)
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": token1},
    )
    assert response.status_code == 401
    assert "reuse detected" in response.json()["detail"].lower()

    # All tokens in family should be revoked
    result = await clean_db.execute(
        select(RefreshToken).where(RefreshToken.family_id == family_id)
    )
    for token in result.scalars().all():
        assert token.revoked_at is not None


async def test_refresh_expired_token(client, clean_db):
    """POST /auth/refresh - rejects expired token."""
    expired_token = security.create_token(
        user_id=1,
        token_type="refresh",
        expires_delta=timedelta(minutes=-1),
    )

    token_hash = security.hash_token(expired_token)
    db_token = RefreshToken(
        user_id=1,
        family_id=uuid4(),
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    clean_db.add(db_token)
    await clean_db.commit()

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": expired_token},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


async def test_refresh_access_token_as_refresh(client, test_user):
    """POST /auth/refresh - rejects access token used as refresh."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    access_token = login.json()["access_token"]

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert response.status_code == 401


async def test_refresh_tampered_token(client, clean_db):
    """POST /auth/refresh - rejects tampered token."""
    valid_token = security.create_token(
        user_id=1,
        token_type="refresh",
        expires_delta=timedelta(days=7),
    )
    tampered = valid_token[:-1] + ("X" if valid_token[-1] != "X" else "Y")

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": tampered},
    )
    assert response.status_code == 401


# ============================================================================
# LOGOUT TESTS
# ============================================================================

async def test_logout_success(client, test_user):
    """POST /auth/logout - successful logout."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    refresh_token = login.json()["refresh_token"]

    response = await client.post(
        "/auth/logout",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 204


async def test_logout_revokes_token(client, test_user):
    """POST /auth/logout - token cannot be refreshed after logout."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    refresh_token = login.json()["refresh_token"]

    await client.post("/auth/logout", json={"refresh_token": refresh_token})

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 401


async def test_logout_idempotent(client, test_user):
    """POST /auth/logout - logout twice returns 204 both times."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    refresh_token = login.json()["refresh_token"]

    r1 = await client.post("/auth/logout", json={"refresh_token": refresh_token})
    r2 = await client.post("/auth/logout", json={"refresh_token": refresh_token})

    assert r1.status_code == 204
    assert r2.status_code == 204


# ============================================================================
# /AUTH/ME TESTS
# ============================================================================

async def test_me_success(client, test_user):
    """GET /auth/me - returns current user."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    access_token = login.json()["access_token"]

    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_user["user"].id
    assert data["email"] == test_user["email"]
    assert "password_hash" not in data


async def test_me_no_token(client, clean_db):
    """GET /auth/me - rejects missing token."""
    response = await client.get("/auth/me")
    assert response.status_code == 403


async def test_me_expired_token(client, clean_db):
    """GET /auth/me - rejects expired token."""
    expired_token = security.create_token(
        user_id=1,
        token_type="access",
        expires_delta=timedelta(minutes=-1),
    )

    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401


async def test_me_refresh_token_as_bearer(client, test_user):
    """GET /auth/me - rejects refresh token used as bearer."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    refresh_token = login.json()["refresh_token"]

    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert response.status_code == 401
    assert "token type" in response.json()["detail"].lower()


async def test_me_user_deleted(client, clean_db, test_user):
    """GET /auth/me - returns 401 if user deleted."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    access_token = login.json()["access_token"]

    await clean_db.execute(
        text("DELETE FROM users WHERE id = :user_id"),
        {"user_id": test_user["user"].id}
    )
    await clean_db.commit()

    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 401


# ============================================================================
# SECURITY PROPERTY TESTS
# ============================================================================

async def test_password_hashed_not_plaintext(client, clean_db):
    """Password is bcrypt hashed, not plaintext."""
    response = await client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "SecurePassword123"},
    )
    assert response.status_code == 201

    result = await clean_db.execute(
        select(User).where(User.email == "user@example.com")
    )
    user = result.scalar_one_or_none()
    assert user.password_hash.startswith("$2")  # bcrypt marker
    assert user.password_hash != "SecurePassword123"


async def test_password_never_in_responses(client, clean_db, test_user):
    """Password and password_hash never in API responses."""
    # Login
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    login_str = str(login.json()).lower()
    assert "password_hash" not in login_str

    # Me
    access_token = login.json()["access_token"]
    me = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    me_str = str(me.json()).lower()
    assert "password_hash" not in me_str
