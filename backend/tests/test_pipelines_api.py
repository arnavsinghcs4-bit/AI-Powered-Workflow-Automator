"""Pipeline API integration tests - Phase 3 endpoints."""

import pytest
from httpx import AsyncClient

from app.auth import security


@pytest.fixture
async def auth_client(client, test_user):
    """Test client with authenticated user."""
    login = await client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    access_token = login.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {access_token}"})
    return client


@pytest.fixture
async def auth_client2(db_session):
    """Second authenticated test client for cross-user isolation tests."""
    from app.database import get_session
    from app.main import app
    from httpx import AsyncClient
    from app.auth import security

    # Create second user
    user = await client.post(
        "/auth/register",
        json={"email": "user2@test.com", "password": "SecurePassword123"},
    )

    async def override_get_session():
        return db_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        login = await ac.post(
            "/auth/login",
            json={"email": "user2@test.com", "password": "SecurePassword123"},
        )
        access_token = login.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {access_token}"})
        yield ac
    app.dependency_overrides.clear()


class TestPipelineCRUD:
    """CRUD operations on pipelines."""

    async def test_create_pipeline_success(self, auth_client):
        """POST /pipelines - create a pipeline."""
        response = await auth_client.post(
            "/pipelines/",
            json={"name": "Test Pipeline", "description": "A test pipeline"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Pipeline"
        assert data["description"] == "A test pipeline"
        assert data["id"] is not None
        assert data["user_id"] is not None
        assert data["is_active"] is True

    async def test_create_pipeline_minimal(self, auth_client):
        """POST /pipelines - create with only required fields."""
        response = await auth_client.post(
            "/pipelines/",
            json={"name": "Minimal Pipeline"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Pipeline"
        assert data["description"] is None

    async def test_create_pipeline_empty_name_rejected(self, auth_client):
        """POST /pipelines - rejects empty name."""
        response = await auth_client.post(
            "/pipelines/",
            json={"name": ""},
        )
        assert response.status_code == 422

    async def test_list_pipelines(self, auth_client):
        """GET /pipelines - list user's pipelines."""
        # Create a few pipelines
        await auth_client.post("/pipelines/", json={"name": "Pipeline 1"})
        await auth_client.post("/pipelines/", json={"name": "Pipeline 2"})

        response = await auth_client.get("/pipelines/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = {p["name"] for p in data}
        assert names == {"Pipeline 1", "Pipeline 2"}

    async def test_list_pipelines_empty(self, auth_client):
        """GET /pipelines - empty list when no pipelines."""
        response = await auth_client.get("/pipelines/")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_pipeline_success(self, auth_client):
        """GET /pipelines/{id} - retrieve a pipeline."""
        create_resp = await auth_client.post(
            "/pipelines/", json={"name": "Get Me", "description": "Desc"}
        )
        pipeline_id = create_resp.json()["id"]

        response = await auth_client.get(f"/pipelines/{pipeline_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == pipeline_id
        assert data["name"] == "Get Me"
        assert data["description"] == "Desc"

    async def test_get_pipeline_not_found(self, auth_client):
        """GET /pipelines/{id} - 404 for non-existent."""
        response = await auth_client.get("/pipelines/999999")
        assert response.status_code == 404

    async def test_get_pipeline_cross_user_404(self, auth_client, auth_client2):
        """GET /pipelines/{id} - 404 for another user's pipeline."""
        # Client1 creates a pipeline
        create_resp = await auth_client.post("/pipelines/", json={"name": "Private"})
        pipeline_id = create_resp.json()["id"]

        # Client2 tries to access it
        response = await auth_client2.get(f"/pipelines/{pipeline_id}")
        assert response.status_code == 404


class TestPipelineVersions:
    """Pipeline version management."""

    async def test_create_version_success(self, auth_client):
        """POST /pipelines/{id}/versions - create a version."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "Versioned"})
        pipeline_id = create_resp.json()["id"]

        response = await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={
                "version_number": 1,
                "definition": {"nodes": []},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["pipeline_id"] == pipeline_id
        assert data["version_number"] == 1
        assert data["definition"] == {"nodes": []}

    async def test_create_version_auto_number(self, auth_client):
        """POST /pipelines/{id}/versions - version_number is required."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "Auto Ver"})
        pipeline_id = create_resp.json()["id"]

        # version_number is required in schema
        response = await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={"definition": {"nodes": []}},
        )
        assert response.status_code == 422

    async def test_list_versions(self, auth_client):
        """GET /pipelines/{id}/versions - list versions."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "List Versions"})
        pipeline_id = create_resp.json()["id"]

        await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={"version_number": 1, "definition": {"nodes": [{"id": "a"}]}},
        )
        await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={"version_number": 2, "definition": {"nodes": [{"id": "b"}]}},
        )

        response = await auth_client.get(f"/pipelines/{pipeline_id}/versions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Should be ordered by version_number desc
        assert data[0]["version_number"] == 2
        assert data[1]["version_number"] == 1

    async def test_list_versions_cross_user_404(self, auth_client, auth_client2):
        """GET /pipelines/{id}/versions - 404 for another user's pipeline."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "Private"})
        pipeline_id = create_resp.json()["id"]

        await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={"version_number": 1, "definition": {"nodes": []}},
        )

        response = await auth_client2.get(f"/pipelines/{pipeline_id}/versions")
        assert response.status_code == 404


class TestPipelineRun:
    """Triggering pipeline runs."""

    async def test_run_pipeline_success(self, auth_client):
        """POST /pipelines/{id}/run - trigger a run."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "Runnable"})
        pipeline_id = create_resp.json()["id"]

        # Create a version with a simple http_request step
        await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={
                "version_number": 1,
                "definition": {
                    "nodes": [
                        {
                            "id": "step1",
                            "type": "http_request",
                            "config": {
                                "method": "GET",
                                "url": "http://example.com/api",
                            },
                        }
                    ]
                },
            },
        )

        response = await auth_client.post(
            f"/pipelines/{pipeline_id}/run",
            json={"trigger_type": "manual"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["run_id"] is not None
        assert data["pipeline_id"] == pipeline_id
        assert data["status"] == "pending"
        assert "message" in data

    async def test_run_pipeline_uses_latest_version(self, auth_client):
        """POST /pipelines/{id}/run - uses latest version when version_id omitted."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "Latest Ver"})
        pipeline_id = create_resp.json()["id"]

        # Create v1
        v1_resp = await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={
                "version_number": 1,
                "definition": {"nodes": [{"id": "a", "type": "http_request", "config": {"url": "http://a.com"}}]},
            },
        )
        v1_id = v1_resp.json()["id"]

        # Create v2
        v2_resp = await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={
                "version_number": 2,
                "definition": {"nodes": [{"id": "b", "type": "http_request", "config": {"url": "http://b.com"}}]},
            },
        )
        v2_id = v2_resp.json()["id"]

        # Run without version_id - should use v2
        response = await auth_client.post(
            f"/pipelines/{pipeline_id}/run",
            json={},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["version_id"] == v2_id

    async def test_run_pipeline_explicit_version(self, auth_client):
        """POST /pipelines/{id}/run - uses explicit version_id."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "Explicit Ver"})
        pipeline_id = create_resp.json()["id"]

        v1_resp = await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={
                "version_number": 1,
                "definition": {"nodes": [{"id": "a", "type": "http_request", "config": {"url": "http://a.com"}}]},
            },
        )
        v1_id = v1_resp.json()["id"]

        v2_resp = await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={
                "version_number": 2,
                "definition": {"nodes": [{"id": "b", "type": "http_request", "config": {"url": "http://b.com"}}]},
            },
        )
        v2_id = v2_resp.json()["id"]

        # Run with explicit v1
        response = await auth_client.post(
            f"/pipelines/{pipeline_id}/run",
            json={"version_id": v1_id},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["version_id"] == v1_id

    async def test_run_pipeline_no_versions_404(self, auth_client):
        """POST /pipelines/{id}/run - 404 when no versions exist."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "No Versions"})
        pipeline_id = create_resp.json()["id"]

        response = await auth_client.post(
            f"/pipelines/{pipeline_id}/run",
            json={},
        )
        assert response.status_code == 404
        assert "No pipeline versions exist" in response.json()["detail"]

    async def test_run_pipeline_invalid_definition_400(self, auth_client):
        """POST /pipelines/{id}/run - 400 for invalid step config."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "Bad Def"})
        pipeline_id = create_resp.json()["id"]

        await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={
                "version_number": 1,
                "definition": {
                    "nodes": [
                        {
                            "id": "step1",
                            "type": "http_request",
                            "config": {"method": "INVALID", "url": "http://example.com"},
                        }
                    ]
                },
            },
        )

        response = await auth_client.post(
            f"/pipelines/{pipeline_id}/run",
            json={},
        )
        assert response.status_code == 400
        assert "Invalid pipeline definition" in response.json()["detail"]

    async def test_run_pipeline_cross_user_404(self, auth_client, auth_client2):
        """POST /pipelines/{id}/run - 404 for another user's pipeline."""
        create_resp = await auth_client.post("/pipelines/", json={"name": "Private"})
        pipeline_id = create_resp.json()["id"]

        await auth_client.post(
            f"/pipelines/{pipeline_id}/versions",
            json={"version_number": 1, "definition": {"nodes": []}},
        )

        response = await auth_client2.post(
            f"/pipelines/{pipeline_id}/run",
            json={},
        )
        assert response.status_code == 404


class TestStepTypes:
    """Step type registry."""

    async def test_list_step_types(self, auth_client):
        """GET /pipelines/step-types - returns registered step types."""
        response = await auth_client.get("/pipelines/step-types")
        assert response.status_code == 200
        data = response.json()
        assert "http_request" in data
        assert "transform" in data


# The auth_client2 fixture is defined at the top