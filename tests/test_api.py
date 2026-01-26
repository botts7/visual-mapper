"""
API Endpoint Tests for Visual Mapper
Tests the backend API endpoints including version display
"""
import pytest
import re


class TestMetaAPI:
    """Test meta/root API endpoints"""

    def test_api_root_returns_200(self, api_client):
        """API root should return 200 OK"""
        response = api_client.get("/")
        assert response.status_code == 200

    def test_api_root_has_version(self, api_client):
        """API root should include version field"""
        response = api_client.get("/")
        data = response.json()
        assert "version" in data, "Response missing 'version' field"

    def test_api_version_format(self, api_client):
        """Version should be in semver format (X.Y.Z or X.Y.Z-prerelease)"""
        response = api_client.get("/")
        data = response.json()
        version = data["version"]
        # Should match X.Y.Z or X.Y.Z-prerelease pattern (e.g., 0.4.0-beta.4)
        assert re.match(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$', version), f"Invalid version format: {version}"

    def test_api_version_not_hardcoded(self, api_client):
        """Version should NOT be the old hardcoded 0.0.12"""
        response = api_client.get("/")
        data = response.json()
        version = data["version"]
        assert version != "0.0.12", "Version is still hardcoded to 0.0.12!"
        assert version != "unknown", "Version file not found!"

    def test_api_version_matches_build_file(self, api_client):
        """Version should match .build-version file"""
        from pathlib import Path

        # Read expected version from file
        version_file = Path(__file__).parent.parent / ".build-version"
        expected_version = version_file.read_text().strip()

        # Get API version
        response = api_client.get("/")
        data = response.json()
        actual_version = data["version"]

        assert actual_version == expected_version, \
            f"API version ({actual_version}) doesn't match .build-version ({expected_version})"

    def test_api_root_has_name(self, api_client):
        """API root should include app name"""
        response = api_client.get("/")
        data = response.json()
        assert data.get("name") == "Visual Mapper API"

    def test_api_root_has_endpoints(self, api_client):
        """API root should list available endpoints"""
        response = api_client.get("/")
        data = response.json()
        assert "endpoints" in data
        endpoints = data["endpoints"]

        # Check critical endpoints are listed
        assert "health" in endpoints
        assert "devices" in endpoints
        assert "sensors" in endpoints
        assert "device_classes" in endpoints


class TestDeviceClassesAPI:
    """Test device classes endpoint"""

    def test_device_classes_returns_200(self, api_client):
        """Device classes endpoint should return 200"""
        response = api_client.get("/device-classes")
        assert response.status_code == 200

    def test_device_classes_has_data(self, api_client):
        """Device classes should return sensor type data"""
        response = api_client.get("/device-classes")
        data = response.json()
        # Should have sensor device classes
        assert len(data) > 0, "Device classes response is empty"


class TestHealthAPI:
    """Test health check endpoint"""

    def test_health_returns_200(self, api_client):
        """Health endpoint should return 200"""
        response = api_client.get("/health")
        assert response.status_code == 200


class TestStaticFiles:
    """Test static file serving"""

    def test_frontend_index_accessible(self, api_client):
        """Frontend index.html should be accessible"""
        # Static files are served from root, not /api
        import httpx
        with httpx.Client(base_url="http://127.0.0.1:8765", timeout=10) as client:
            response = client.get("/")
            # Should redirect to flow-wizard or serve HTML
            assert response.status_code in [200, 307, 302]

    def test_flow_wizard_accessible(self, api_client):
        """Flow wizard HTML should be accessible"""
        import httpx
        with httpx.Client(base_url="http://127.0.0.1:8765", timeout=10) as client:
            response = client.get("/flow-wizard.html")
            assert response.status_code == 200
            assert "text/html" in response.headers.get("content-type", "")

    def test_css_accessible(self, api_client):
        """CSS files should be accessible"""
        import httpx
        with httpx.Client(base_url="http://127.0.0.1:8765", timeout=10) as client:
            response = client.get("/css/flow-wizard.css")
            assert response.status_code == 200
            assert "text/css" in response.headers.get("content-type", "")

    def test_js_modules_accessible(self, api_client):
        """JavaScript modules should be accessible"""
        import httpx
        with httpx.Client(base_url="http://127.0.0.1:8765", timeout=10) as client:
            response = client.get("/js/modules/smart-suggestions.js")
            assert response.status_code == 200
            assert "javascript" in response.headers.get("content-type", "")
