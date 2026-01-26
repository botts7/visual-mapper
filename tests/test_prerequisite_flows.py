"""
Tests for Prerequisite Flows System

Tests cover:
- PrerequisiteFlowManager unit tests (core logic)
- API endpoint integration tests
- Configuration persistence
- Device ID sanitization
"""
import pytest
import tempfile
import shutil
import json
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.flows.prerequisite_flows import (
    PrerequisiteFlowManager,
    PREREQUISITE_TYPES,
    get_prerequisite_manager,
    init_prerequisite_manager,
)

# Test configuration - matches conftest.py
TEST_HOST = "127.0.0.1"
TEST_PORT = 8765
API_BASE = f"http://{TEST_HOST}:{TEST_PORT}/api"
TEST_COMPANION_KEY = "test-companion-key"


# =============================================================================
# UNIT TESTS: PrerequisiteFlowManager
# =============================================================================


class TestPrerequisiteFlowManagerUnit:
    """Unit tests for PrerequisiteFlowManager core functionality."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create temporary data directory for tests."""
        temp_dir = tempfile.mkdtemp(prefix="prereq-test-")
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def manager(self, temp_data_dir):
        """Create manager instance with temp directory."""
        return PrerequisiteFlowManager(data_dir=temp_data_dir)

    # -------------------------------------------------------------------------
    # Device ID Sanitization Tests
    # -------------------------------------------------------------------------

    def test_device_id_sanitization_colons(self, manager):
        """Device IDs with colons are sanitized for filesystem."""
        device_id = "192.168.1.1:5555"
        path = manager._get_config_path(device_id)
        assert ":" not in path.name
        assert "_" in path.name
        assert "192.168.1.1_5555" in path.name

    def test_device_id_sanitization_slashes(self, manager):
        """Device IDs with slashes are sanitized for filesystem."""
        device_id = "device/with/slashes"
        path = manager._get_config_path(device_id)
        assert "/" not in path.name
        assert "device_with_slashes" in path.name

    def test_device_id_sanitization_combined(self, manager):
        """Device IDs with mixed special chars are fully sanitized."""
        device_id = "192.168.1.1:5555/serial"
        path = manager._get_config_path(device_id)
        assert ":" not in path.name
        assert "/" not in path.name

    # -------------------------------------------------------------------------
    # Configuration Persistence Tests
    # -------------------------------------------------------------------------

    def test_load_config_nonexistent_returns_empty(self, manager):
        """Loading config for unknown device returns empty dict."""
        config = manager._load_config("nonexistent_device")
        assert config == {}

    def test_save_and_load_config_roundtrip(self, manager):
        """Config can be saved and loaded correctly."""
        device_id = "test_device"
        test_config = {
            "enable_accessibility": {
                "flow_id": "abc123",
                "auto_run": True,
                "success_count": 5
            }
        }

        result = manager._save_config(device_id, test_config)
        assert result is True

        loaded = manager._load_config(device_id)
        assert loaded == test_config

    def test_config_file_creation(self, manager, temp_data_dir):
        """Config file is created in correct location."""
        device_id = "test_device"
        manager._save_config(device_id, {"test": "data"})

        config_path = Path(temp_data_dir) / "config" / f"prerequisite_flows_{device_id}.json"
        assert config_path.exists()

    # -------------------------------------------------------------------------
    # Prerequisite Types Tests
    # -------------------------------------------------------------------------

    def test_get_prerequisite_types_returns_all(self, manager):
        """get_prerequisite_types returns all defined types."""
        types = manager.get_prerequisite_types()
        assert "enable_accessibility" in types
        assert "start_streaming" in types
        assert "grant_overlay_permission" in types

    def test_prerequisite_types_have_required_fields(self, manager):
        """Each prerequisite type has required metadata fields."""
        types = manager.get_prerequisite_types()
        for prereq_type, metadata in types.items():
            assert "name" in metadata, f"{prereq_type} missing 'name'"
            assert "description" in metadata, f"{prereq_type} missing 'description'"
            assert "guidance_steps" in metadata, f"{prereq_type} missing 'guidance_steps'"
            assert isinstance(metadata["guidance_steps"], list)

    # -------------------------------------------------------------------------
    # Flow Linking Tests
    # -------------------------------------------------------------------------

    def test_link_flow_creates_entry(self, manager):
        """link_flow creates config entry with flow_id."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"
        flow_id = "flow_abc123"

        result = manager.link_flow(device_id, prereq_type, flow_id)
        assert result is True

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert config is not None
        assert config["flow_id"] == flow_id

    def test_link_flow_sets_timestamp(self, manager):
        """link_flow sets linked_at timestamp."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        before = datetime.now().isoformat()
        manager.link_flow(device_id, prereq_type, "flow_123")

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert "linked_at" in config
        # Timestamp should be recent (within 1 second)
        assert config["linked_at"] >= before[:19]  # Compare ISO strings

    def test_link_flow_invalid_type_returns_false(self, manager):
        """link_flow with invalid prerequisite type returns False."""
        result = manager.link_flow("device", "invalid_type", "flow_id")
        assert result is False

    def test_unlink_flow_removes_flow_id(self, manager):
        """unlink_flow removes flow_id from config."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        # Link first
        manager.link_flow(device_id, prereq_type, "flow_123")

        # Unlink
        result = manager.unlink_flow(device_id, prereq_type)
        assert result is True

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert config is not None
        assert "flow_id" not in config
        assert "linked_at" not in config

    def test_unlink_flow_idempotent(self, manager):
        """unlink_flow on non-linked prerequisite returns True."""
        result = manager.unlink_flow("device", "enable_accessibility")
        assert result is True

    # -------------------------------------------------------------------------
    # Auto-Run Tests
    # -------------------------------------------------------------------------

    def test_set_auto_run_enabled(self, manager):
        """set_auto_run enables auto_run flag."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        result = manager.set_auto_run(device_id, prereq_type, True)
        assert result is True

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert config["auto_run"] is True

    def test_set_auto_run_disabled(self, manager):
        """set_auto_run disables auto_run flag."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        # Enable first
        manager.set_auto_run(device_id, prereq_type, True)

        # Then disable
        result = manager.set_auto_run(device_id, prereq_type, False)
        assert result is True

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert config["auto_run"] is False

    def test_set_auto_run_invalid_type_returns_false(self, manager):
        """set_auto_run with invalid type returns False."""
        result = manager.set_auto_run("device", "invalid_type", True)
        assert result is False

    def test_set_auto_run_persists(self, manager):
        """set_auto_run persists across loads."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        manager.set_auto_run(device_id, prereq_type, True)

        # Create new manager instance (simulates restart)
        new_manager = PrerequisiteFlowManager(data_dir=manager.data_dir)
        config = new_manager.get_prerequisite_config(device_id, prereq_type)
        assert config["auto_run"] is True

    # -------------------------------------------------------------------------
    # Run Recording Tests
    # -------------------------------------------------------------------------

    def test_record_run_success_increments_counter(self, manager):
        """record_run with success=True increments success_count."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        manager.record_run(device_id, prereq_type, success=True)

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert config["success_count"] == 1

    def test_record_run_failure_increments_counter(self, manager):
        """record_run with success=False increments fail_count."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        manager.record_run(device_id, prereq_type, success=False)

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert config["fail_count"] == 1

    def test_record_run_sets_timestamp(self, manager):
        """record_run sets last_run timestamp."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        manager.record_run(device_id, prereq_type, success=True)

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert "last_run" in config

    def test_record_run_accumulates(self, manager):
        """Multiple record_run calls accumulate counters."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        manager.record_run(device_id, prereq_type, success=True)
        manager.record_run(device_id, prereq_type, success=True)
        manager.record_run(device_id, prereq_type, success=False)

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert config["success_count"] == 2
        assert config["fail_count"] == 1

    # -------------------------------------------------------------------------
    # Data Retrieval Tests
    # -------------------------------------------------------------------------

    def test_get_prerequisite_config_returns_config(self, manager):
        """get_prerequisite_config returns correct config."""
        device_id = "test_device"
        prereq_type = "enable_accessibility"

        manager.link_flow(device_id, prereq_type, "flow_123")

        config = manager.get_prerequisite_config(device_id, prereq_type)
        assert config is not None
        assert config["flow_id"] == "flow_123"

    def test_get_prerequisite_config_nonexistent_returns_none(self, manager):
        """get_prerequisite_config for missing config returns None."""
        config = manager.get_prerequisite_config("device", "enable_accessibility")
        assert config is None

    def test_get_all_prerequisites_empty_device(self, manager):
        """get_all_prerequisites for new device returns empty dict."""
        config = manager.get_all_prerequisites("new_device")
        assert config == {}

    def test_get_all_prerequisites_multiple_configs(self, manager):
        """get_all_prerequisites returns all configured prerequisites."""
        device_id = "test_device"

        manager.link_flow(device_id, "enable_accessibility", "flow_1")
        manager.link_flow(device_id, "start_streaming", "flow_2")

        configs = manager.get_all_prerequisites(device_id)
        assert "enable_accessibility" in configs
        assert "start_streaming" in configs

    def test_get_guidance_steps_valid_type(self, manager):
        """get_guidance_steps returns steps for valid type."""
        steps = manager.get_guidance_steps("enable_accessibility")
        assert isinstance(steps, list)
        assert len(steps) > 0
        assert "Settings" in steps[0]

    def test_get_guidance_steps_invalid_type_returns_empty(self, manager):
        """get_guidance_steps for invalid type returns empty list."""
        steps = manager.get_guidance_steps("invalid_type")
        assert steps == []

    # -------------------------------------------------------------------------
    # Singleton Tests
    # -------------------------------------------------------------------------

    def test_get_prerequisite_manager_returns_singleton(self, temp_data_dir):
        """get_prerequisite_manager returns same instance."""
        # Reset singleton
        import core.flows.prerequisite_flows as pfm
        pfm._prerequisite_manager = None

        manager1 = get_prerequisite_manager(temp_data_dir)
        manager2 = get_prerequisite_manager(temp_data_dir)

        assert manager1 is manager2

    def test_init_prerequisite_manager_creates_new_instance(self, temp_data_dir):
        """init_prerequisite_manager creates new instance."""
        import core.flows.prerequisite_flows as pfm

        manager1 = init_prerequisite_manager(temp_data_dir)
        manager2 = init_prerequisite_manager(temp_data_dir)

        # Should be different instances
        assert manager1 is not manager2


# =============================================================================
# INTEGRATION TESTS: API Endpoints
# =============================================================================


class TestPrerequisitesAPI:
    """Integration tests for prerequisite API endpoints."""

    @pytest.fixture
    def auth_headers(self, companion_key):
        """Headers with auth key."""
        return {"X-Companion-Key": companion_key}

    # -------------------------------------------------------------------------
    # Types Endpoint Tests
    # -------------------------------------------------------------------------

    def test_get_types_returns_all(self, api_client, auth_headers):
        """GET /prerequisites/types returns all prerequisite types."""
        response = api_client.get("/prerequisites/types", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "types" in data
        assert "enable_accessibility" in data["types"]
        assert "start_streaming" in data["types"]
        assert "grant_overlay_permission" in data["types"]

    def test_get_types_includes_metadata(self, api_client, auth_headers):
        """Prerequisite types include required metadata."""
        response = api_client.get("/prerequisites/types", headers=auth_headers)
        data = response.json()

        accessibility = data["types"]["enable_accessibility"]
        assert "name" in accessibility
        assert "description" in accessibility
        assert "guidance_steps" in accessibility

    # -------------------------------------------------------------------------
    # Status Endpoint Tests
    # -------------------------------------------------------------------------

    def test_get_status_returns_all_prerequisites(self, api_client, auth_headers):
        """GET /prerequisites/{device_id}/status returns all prerequisite status."""
        response = api_client.get(
            "/prerequisites/test_device/status",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert "prerequisites" in data
        # Should have all 3 prerequisite types
        prereqs = data["prerequisites"]
        assert "enable_accessibility" in prereqs
        assert "start_streaming" in prereqs
        assert "grant_overlay_permission" in prereqs

    def test_get_status_includes_config(self, api_client, auth_headers):
        """Status endpoint includes flow configuration."""
        # Link a flow first
        api_client.post(
            "/prerequisites/test_device/enable_accessibility/link-flow",
            json={"flow_id": "flow_abc"},
            headers=auth_headers
        )

        response = api_client.get(
            "/prerequisites/test_device/status",
            headers=auth_headers
        )
        data = response.json()

        accessibility = data["prerequisites"]["enable_accessibility"]
        assert accessibility.get("flow_id") == "flow_abc"

    # -------------------------------------------------------------------------
    # Detail Endpoint Tests
    # -------------------------------------------------------------------------

    def test_get_detail_returns_full_info(self, api_client, auth_headers):
        """GET /prerequisites/{device_id}/{type} returns full information."""
        response = api_client.get(
            "/prerequisites/test_device/enable_accessibility",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert "name" in data
        assert "description" in data
        assert "guidance_steps" in data

    def test_get_detail_invalid_type_returns_400(self, api_client, auth_headers):
        """Invalid prerequisite type returns 400."""
        response = api_client.get(
            "/prerequisites/test_device/invalid_type",
            headers=auth_headers
        )
        assert response.status_code == 400

    # -------------------------------------------------------------------------
    # Flow Linking Tests
    # -------------------------------------------------------------------------

    def test_link_flow_success(self, api_client, auth_headers):
        """POST link-flow successfully links a flow."""
        response = api_client.post(
            "/prerequisites/test_device/enable_accessibility/link-flow",
            json={"flow_id": "flow_xyz"},
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

    def test_unlink_flow_success(self, api_client, auth_headers):
        """DELETE link-flow removes flow association."""
        # Link first
        api_client.post(
            "/prerequisites/test_device/enable_accessibility/link-flow",
            json={"flow_id": "flow_to_remove"},
            headers=auth_headers
        )

        # Unlink
        response = api_client.delete(
            "/prerequisites/test_device/enable_accessibility/link-flow",
            headers=auth_headers
        )
        assert response.status_code == 200

    # -------------------------------------------------------------------------
    # Auto-Run Tests
    # -------------------------------------------------------------------------

    def test_set_auto_run_enabled(self, api_client, auth_headers):
        """POST set-auto-run enables auto_run."""
        response = api_client.post(
            "/prerequisites/test_device/enable_accessibility/set-auto-run",
            json={"enabled": True},
            headers=auth_headers
        )
        assert response.status_code == 200

        # Verify it's set
        status = api_client.get(
            "/prerequisites/test_device/status",
            headers=auth_headers
        ).json()
        assert status["prerequisites"]["enable_accessibility"].get("auto_run") is True

    def test_set_auto_run_disabled(self, api_client, auth_headers):
        """POST set-auto-run disables auto_run."""
        # Enable first
        api_client.post(
            "/prerequisites/test_device/enable_accessibility/set-auto-run",
            json={"enabled": True},
            headers=auth_headers
        )

        # Disable
        response = api_client.post(
            "/prerequisites/test_device/enable_accessibility/set-auto-run",
            json={"enabled": False},
            headers=auth_headers
        )
        assert response.status_code == 200

    # -------------------------------------------------------------------------
    # Record Run Tests
    # -------------------------------------------------------------------------

    def test_record_run_success(self, api_client, auth_headers):
        """POST record-run records successful execution."""
        response = api_client.post(
            "/prerequisites/test_device/enable_accessibility/record-run",
            json={"success": True},
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

    def test_record_run_failure(self, api_client, auth_headers):
        """POST record-run records failed execution."""
        response = api_client.post(
            "/prerequisites/test_device/enable_accessibility/record-run",
            json={"success": False},
            headers=auth_headers
        )
        assert response.status_code == 200

    # -------------------------------------------------------------------------
    # Guidance Endpoint Tests
    # -------------------------------------------------------------------------

    def test_get_guidance_returns_steps(self, api_client, auth_headers):
        """GET guidance returns step-by-step instructions."""
        response = api_client.get(
            "/prerequisites/test_device/enable_accessibility/guidance",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert "steps" in data
        assert isinstance(data["steps"], list)
        assert len(data["steps"]) > 0

    # -------------------------------------------------------------------------
    # Authentication Tests
    # -------------------------------------------------------------------------

    def test_endpoints_require_auth(self, api_client):
        """All endpoints require authentication."""
        # No auth header
        endpoints = [
            ("GET", "/prerequisites/types"),
            ("GET", "/prerequisites/test/status"),
            ("GET", "/prerequisites/test/enable_accessibility"),
            ("POST", "/prerequisites/test/enable_accessibility/link-flow"),
            ("POST", "/prerequisites/test/enable_accessibility/set-auto-run"),
            ("POST", "/prerequisites/test/enable_accessibility/record-run"),
            ("GET", "/prerequisites/test/enable_accessibility/guidance"),
        ]

        for method, path in endpoints:
            if method == "GET":
                response = api_client.get(path)
            else:
                response = api_client.post(path, json={})

            # Should get 401 or 403 without auth
            assert response.status_code in (401, 403), \
                f"{method} {path} should require auth, got {response.status_code}"
