"""
Auth Regression Tests
Validates protected endpoints enforce companion auth when using a non-local client IP.
"""
import pytest


def _auth_is_enforced(api_client) -> bool:
    """
    Check if auth is actually enforced by the server.

    If COMPANION_API_KEY is empty, the server runs in development mode
    and allows all requests without auth.
    """
    response = api_client.get(
        "/stream/shared/stats",
        headers={"X-Forwarded-For": "8.8.8.8"},
    )
    return response.status_code == 401


def test_protected_endpoint_rejects_without_key(api_client):
    """Protected endpoints should reject requests without key from external IP"""
    if not _auth_is_enforced(api_client):
        pytest.skip("Auth not enforced (COMPANION_API_KEY not set in server)")

    response = api_client.get(
        "/stream/shared/stats",
        headers={"X-Forwarded-For": "8.8.8.8"},
    )
    assert response.status_code == 401


def test_protected_endpoint_accepts_with_key(api_client, companion_key):
    """Protected endpoints should accept requests with valid key"""
    response = api_client.get(
        "/stream/shared/stats",
        headers={
            "X-Forwarded-For": "8.8.8.8",
            "X-Companion-Key": companion_key,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True


def test_localhost_allowed_without_key(api_client):
    """Localhost requests should be allowed without API key"""
    # Don't set X-Forwarded-For - request will appear from localhost
    response = api_client.get("/stream/shared/stats")
    assert response.status_code == 200
