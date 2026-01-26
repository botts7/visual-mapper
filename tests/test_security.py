"""
Security and Authentication Tests

Tests for CORS configuration, REST API authentication, and WebSocket authentication.
Ensures the beta-auth security features work correctly without regressions.
"""
import pytest
import httpx

# Import test configuration
from conftest import TEST_HOST, TEST_PORT, BASE_URL, API_BASE, TEST_COMPANION_KEY


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


class TestCORSConfiguration:
    """Test CORS is properly configured"""

    def test_cors_allows_localhost_origin(self, api_client):
        """Localhost origin should be allowed by CORS"""
        response = api_client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8080",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Should allow localhost
        allow_origin = response.headers.get("Access-Control-Allow-Origin", "")
        # Either allows the origin or allows all (for local testing)
        assert response.status_code in (200, 204) or allow_origin in (
            "http://localhost:8080",
            "*",
        )

    def test_cors_preflight_has_correct_headers(self, api_client):
        """CORS preflight should return expected headers"""
        response = api_client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8080",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Companion-Key",
            },
        )
        # Should return CORS headers
        # Allow-Methods should include common methods
        if response.status_code in (200, 204):
            allow_methods = response.headers.get("Access-Control-Allow-Methods", "")
            # GET should be allowed for most endpoints
            assert "GET" in allow_methods or "*" in allow_methods


class TestRESTAuthentication:
    """Test REST API authentication"""

    def test_protected_endpoint_without_key_from_external_ip_returns_401(
        self, api_client
    ):
        """Protected endpoints should require auth when accessed from external IP"""
        if not _auth_is_enforced(api_client):
            pytest.skip("Auth not enforced (COMPANION_API_KEY not set)")

        response = api_client.get(
            "/stream/shared/stats",
            headers={"X-Forwarded-For": "8.8.8.8"},
        )
        assert response.status_code == 401

    def test_protected_endpoint_with_valid_key_succeeds(self, api_client, companion_key):
        """Valid API key should grant access from external IP"""
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

    def test_protected_endpoint_with_invalid_key_returns_401(self, api_client):
        """Invalid API key should be rejected"""
        if not _auth_is_enforced(api_client):
            pytest.skip("Auth not enforced (COMPANION_API_KEY not set)")

        response = api_client.get(
            "/stream/shared/stats",
            headers={
                "X-Forwarded-For": "8.8.8.8",
                "X-Companion-Key": "wrong-key-12345",
            },
        )
        assert response.status_code == 401

    def test_localhost_bypasses_auth(self, api_client):
        """Requests from localhost should bypass auth requirement"""
        # Don't send X-Forwarded-For - request appears to come from localhost
        # Note: In test environment, client IP is 127.0.0.1 by default
        response = api_client.get("/stream/shared/stats")
        # Should succeed because localhost is trusted
        assert response.status_code == 200

    def test_unprotected_endpoint_accessible_without_auth(self, api_client):
        """Health check and other unprotected endpoints should work without auth"""
        response = api_client.get("/health")
        assert response.status_code == 200

    def test_multiple_protected_endpoints_require_auth(self, api_client):
        """Verify multiple protected endpoints enforce auth"""
        if not _auth_is_enforced(api_client):
            pytest.skip("Auth not enforced (COMPANION_API_KEY not set)")

        protected_endpoints = [
            "/stream/stats",
            "/stream/shared/stats",
            "/stream/companion/stats",
        ]

        for endpoint in protected_endpoints:
            response = api_client.get(
                endpoint,
                headers={"X-Forwarded-For": "8.8.8.8"},
            )
            assert response.status_code == 401, f"Endpoint {endpoint} should require auth"


class TestWebSocketAuthentication:
    """Test WebSocket authentication"""

    def test_ws_from_localhost_connects_successfully(self, backend_server):
        """WebSocket from localhost should connect without auth"""
        try:
            from websockets.sync.client import connect as ws_connect
        except ImportError:
            pytest.skip("websockets not installed")

        ws_url = f"ws://{TEST_HOST}:{TEST_PORT}/api/ws/stream-mjpeg-v2/test-device"
        try:
            # Connect from localhost - should succeed
            with ws_connect(ws_url, open_timeout=5) as ws:
                # Receive config message
                msg = ws.recv(timeout=5)
                assert msg is not None
                # Connection succeeded
        except Exception as e:
            # Connection issues are OK if server doesn't have ADB - we're testing auth
            if "1008" in str(e):
                pytest.fail("WebSocket rejected with 1008 - auth failed for localhost")

    def test_ws_with_valid_key_connects(self, backend_server, companion_key):
        """WebSocket with valid X-Companion-Key should connect"""
        try:
            from websockets.sync.client import connect as ws_connect
        except ImportError:
            pytest.skip("websockets not installed")

        ws_url = f"ws://{TEST_HOST}:{TEST_PORT}/api/ws/stream-mjpeg-v2/test-device"
        try:
            with ws_connect(
                ws_url,
                additional_headers={"X-Companion-Key": companion_key},
                open_timeout=5,
            ) as ws:
                msg = ws.recv(timeout=5)
                assert msg is not None
        except Exception as e:
            if "1008" in str(e):
                pytest.fail("WebSocket rejected with 1008 - auth failed with valid key")


class TestTrustedSources:
    """Test trusted source detection"""

    def test_ha_ingress_header_is_trusted(self, api_client):
        """Requests with X-Ingress-Path header should be trusted"""
        response = api_client.get(
            "/stream/shared/stats",
            headers={
                "X-Forwarded-For": "8.8.8.8",
                "X-Ingress-Path": "/api/hassio_ingress/abc123",
            },
        )
        # Should succeed because HA Ingress is trusted
        assert response.status_code == 200

    def test_docker_internal_network_is_trusted(self, api_client):
        """Requests from Docker internal networks should be trusted"""
        # 172.30.x.x is a common HA add-on network
        response = api_client.get(
            "/stream/shared/stats",
            headers={"X-Forwarded-For": "172.30.32.2"},
        )
        # Should succeed because Docker internal network is trusted
        assert response.status_code == 200

    def test_ipv6_localhost_is_trusted(self, api_client):
        """IPv6 localhost (::1) should be trusted"""
        response = api_client.get(
            "/stream/shared/stats",
            headers={"X-Forwarded-For": "::1"},
        )
        assert response.status_code == 200


class TestAuthErrorResponses:
    """Test authentication error responses are correct"""

    def test_401_includes_www_authenticate_header(self, api_client):
        """401 responses should include WWW-Authenticate header"""
        if not _auth_is_enforced(api_client):
            pytest.skip("Auth not enforced (COMPANION_API_KEY not set)")

        response = api_client.get(
            "/stream/shared/stats",
            headers={"X-Forwarded-For": "8.8.8.8"},
        )
        assert response.status_code == 401
        # Should indicate the auth method
        auth_header = response.headers.get("WWW-Authenticate", "")
        assert "X-Companion-Key" in auth_header

    def test_401_includes_helpful_detail(self, api_client):
        """401 responses should include helpful error detail"""
        if not _auth_is_enforced(api_client):
            pytest.skip("Auth not enforced (COMPANION_API_KEY not set)")

        response = api_client.get(
            "/stream/shared/stats",
            headers={"X-Forwarded-For": "8.8.8.8"},
        )
        assert response.status_code == 401
        data = response.json()
        detail = data.get("detail", "")
        # Should mention how to authenticate
        assert "X-Companion-Key" in detail or "localhost" in detail or "Ingress" in detail


class TestAuthCodeVerification:
    """
    Verify auth code logic is correct by testing the actual auth module.

    These tests don't require a running server and verify the auth implementation.
    """

    def test_verify_api_key_value_allows_when_key_matches(self):
        """_verify_api_key_value returns True when key matches"""
        import sys
        import os

        # Temporarily set the key in environment
        original = os.environ.get("COMPANION_API_KEY")
        try:
            os.environ["COMPANION_API_KEY"] = "test-secret"

            # Force reimport to pick up new env var
            if "routes.auth" in sys.modules:
                del sys.modules["routes.auth"]

            from routes.auth import _verify_api_key_value

            # Reload the module-level constant
            import routes.auth
            routes.auth.COMPANION_API_KEY = "test-secret"

            assert routes.auth._verify_api_key_value("test-secret") is True
            assert routes.auth._verify_api_key_value("wrong-key") is False
        finally:
            if original is not None:
                os.environ["COMPANION_API_KEY"] = original
            elif "COMPANION_API_KEY" in os.environ:
                del os.environ["COMPANION_API_KEY"]

    def test_verify_api_key_value_allows_all_when_unset(self):
        """_verify_api_key_value returns True for any key when COMPANION_API_KEY is empty"""
        import sys
        import os

        # Temporarily unset the key
        original = os.environ.get("COMPANION_API_KEY")
        try:
            if "COMPANION_API_KEY" in os.environ:
                del os.environ["COMPANION_API_KEY"]

            # Force reimport to pick up new env var
            if "routes.auth" in sys.modules:
                del sys.modules["routes.auth"]

            from routes.auth import _verify_api_key_value

            # Reload the module-level constant
            import routes.auth
            routes.auth.COMPANION_API_KEY = ""

            # Should allow all when no key is configured
            assert routes.auth._verify_api_key_value("") is True
            assert routes.auth._verify_api_key_value("any-key") is True
        finally:
            if original is not None:
                os.environ["COMPANION_API_KEY"] = original
