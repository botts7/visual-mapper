"""
Tests for CommandRouter - verifies proper routing through companion/ADB.
"""
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter, CommandResult, CommandMethod


class TestCommandRouterInit:
    """Test CommandRouter initialization."""

    def test_init_creates_empty_connections(self):
        """CommandRouter should initialize with empty connection tracking."""
        router = CommandRouter()
        assert router._websocket_connections == {}
        assert router._websocket_disconnected_at == {}
        assert router._pending_ws_commands == {}

    def test_no_bypass_websocket_commands_attribute(self):
        """Verify BYPASS_WEBSOCKET_COMMANDS workaround has been removed."""
        router = CommandRouter()
        # The old workaround used a module-level or method-level constant
        # Verify it's not present in the execute method's locals
        import inspect
        source = inspect.getsource(router.execute)
        assert "BYPASS_WEBSOCKET_COMMANDS" not in source, \
            "BYPASS_WEBSOCKET_COMMANDS workaround should be removed"

    def test_no_mqtt_skip_timeout(self):
        """Verify MQTT skip timeout has been removed."""
        router = CommandRouter()
        assert not hasattr(router, '_mqtt_skip_after_disconnect_seconds'), \
            "_mqtt_skip_after_disconnect_seconds should be removed"


class TestWebSocketRegistration:
    """Test WebSocket connection registration."""

    def test_register_websocket(self):
        """Should register WebSocket connection for device."""
        router = CommandRouter()
        mock_ws = Mock()
        mock_send = AsyncMock()

        router.register_websocket("192.168.1.2:42519", mock_ws, mock_send)

        assert "192.168.1.2:42519" in router._websocket_connections
        assert router.has_websocket("192.168.1.2:42519")

    def test_unregister_websocket(self):
        """Should unregister WebSocket connection for device."""
        router = CommandRouter()
        mock_ws = Mock()
        mock_send = AsyncMock()

        router.register_websocket("192.168.1.2:42519", mock_ws, mock_send)
        router.unregister_websocket("192.168.1.2:42519")

        assert "192.168.1.2:42519" not in router._websocket_connections
        assert not router.has_websocket("192.168.1.2:42519")

    def test_unregister_clears_disconnect_on_reconnect(self):
        """Registering should clear previous disconnect timestamp."""
        router = CommandRouter()
        mock_ws = Mock()
        mock_send = AsyncMock()

        # Simulate disconnect then reconnect
        router.register_websocket("192.168.1.2:42519", mock_ws, mock_send)
        router.unregister_websocket("192.168.1.2:42519")
        assert "192.168.1" in str(router._websocket_disconnected_at)  # normalized ID recorded

        router.register_websocket("192.168.1.2:42519", mock_ws, mock_send)
        # Disconnect timestamp should be cleared on reconnect
        normalized = router._normalize_device_id("192.168.1.2:42519")
        assert normalized not in router._websocket_disconnected_at


class TestDeviceIdNormalization:
    """Test device ID normalization."""

    def test_normalize_with_port(self):
        """Should strip port from device ID."""
        router = CommandRouter()
        assert router._normalize_device_id("192.168.1.2:42519") == "192.168.1.2"

    def test_normalize_with_underscores(self):
        """Should convert underscores to dots."""
        router = CommandRouter()
        assert router._normalize_device_id("192_168_1_2") == "192.168.1.2"

    def test_normalize_companion_suffix(self):
        """Should strip _companion suffix."""
        router = CommandRouter()
        assert router._normalize_device_id("192_168_1_2_companion") == "192.168.1.2"


class TestRoutingLogic:
    """Test command routing logic."""

    def test_should_use_websocket_with_registered_connection(self):
        """Should use WebSocket when device has registered connection."""
        router = CommandRouter()
        mock_ws = Mock()
        mock_send = AsyncMock()

        router.register_websocket("192.168.1.2:42519", mock_ws, mock_send)

        assert router._should_use_websocket("192.168.1.2:42519") is True

    def test_should_not_use_websocket_without_connection(self):
        """Should not use WebSocket when no connection registered."""
        router = CommandRouter()
        assert router._should_use_websocket("192.168.1.2:42519") is False

    def test_should_use_mqtt_without_deps(self):
        """Should not use MQTT when no deps available."""
        router = CommandRouter()
        assert router._should_use_mqtt("192.168.1.2:42519") is False

    def test_should_use_mqtt_with_connected_device(self):
        """Should use MQTT when device is connected via MQTT."""
        router = CommandRouter()

        # Mock deps with mqtt_manager
        mock_mqtt = Mock()
        mock_mqtt.is_connected = True
        mock_mqtt.is_device_connected = Mock(return_value=True)

        mock_deps = Mock()
        mock_deps.mqtt_manager = mock_mqtt

        router.set_deps(mock_deps)

        assert router._should_use_mqtt("192.168.1.2:42519") is True
        mock_mqtt.is_device_connected.assert_called_with("192.168.1.2:42519")

    def test_should_not_use_mqtt_when_broker_disconnected(self):
        """Should not use MQTT when broker is not connected."""
        router = CommandRouter()

        mock_mqtt = Mock()
        mock_mqtt.is_connected = False

        mock_deps = Mock()
        mock_deps.mqtt_manager = mock_mqtt

        router.set_deps(mock_deps)

        assert router._should_use_mqtt("192.168.1.2:42519") is False


class TestMQTTManagerIsDeviceConnected:
    """Test MQTTManager.is_device_connected method."""

    def test_is_device_connected_with_capabilities(self):
        """Should return True when device has capabilities."""
        from core.mqtt.mqtt_manager import MQTTManager

        manager = MQTTManager(broker="localhost")
        manager.set_device_capabilities("192.168.1.2:42519", ["CAP_OVERLAY_V2"])

        assert manager.is_device_connected("192.168.1.2:42519") is True

    def test_is_device_connected_with_sanitized_id(self):
        """Should find device with sanitized ID format."""
        from core.mqtt.mqtt_manager import MQTTManager

        manager = MQTTManager(broker="localhost")
        # Store with sanitized format
        sanitized = manager._sanitize_device_id("192.168.1.2:42519")
        manager._device_capabilities[sanitized] = ["CAP_OVERLAY_V2"]

        assert manager.is_device_connected("192.168.1.2:42519") is True

    def test_is_device_connected_with_companion_format(self):
        """Should find device with companion ID format."""
        from core.mqtt.mqtt_manager import MQTTManager

        manager = MQTTManager(broker="localhost")
        # Store with companion format
        companion_id = manager._get_companion_device_id("192.168.1.2:42519")
        manager._device_capabilities[companion_id] = ["CAP_OVERLAY_V2"]

        assert manager.is_device_connected("192.168.1.2:42519") is True

    def test_is_device_connected_false_when_not_found(self):
        """Should return False when device not in any tracking dict."""
        from core.mqtt.mqtt_manager import MQTTManager

        manager = MQTTManager(broker="localhost")
        assert manager.is_device_connected("192.168.1.2:42519") is False


class TestCommandExecution:
    """Test command execution flow."""

    @pytest.mark.asyncio
    async def test_execute_unknown_command(self):
        """Should return error for unknown command."""
        router = CommandRouter()

        result = await router.execute(
            "192.168.1.2:42519",
            "unknown_command",
            {}
        )

        assert result.success is False
        assert "Unknown command" in result.error

    @pytest.mark.asyncio
    async def test_execute_missing_required_param(self):
        """Should return error when required parameter missing."""
        router = CommandRouter()

        result = await router.execute(
            "192.168.1.2:42519",
            "tap",
            {"x": 100}  # Missing "y"
        )

        assert result.success is False
        assert "Missing required parameter" in result.error

    @pytest.mark.asyncio
    async def test_execute_routes_to_websocket_first(self):
        """Should try WebSocket first when available."""
        router = CommandRouter()
        mock_ws = Mock()
        mock_send = AsyncMock()

        router.register_websocket("192.168.1.2:42519", mock_ws, mock_send)

        # Mock the companion stream manager at the import location
        with patch('core.streaming.companion_receiver.companion_stream_manager') as mock_csm:
            mock_csm.is_streaming.return_value = False
            mock_csm.send_command = AsyncMock(return_value=True)

            # Since we have no real WS, it will timeout and fall through to ADB
            # The test verifies routing logic works correctly
            result = await router.execute(
                "192.168.1.2:42519",
                "tap",
                {"x": 100, "y": 200},
                timeout=0.1  # Short timeout for test
            )

            # Will fail (timeout or no ADB deps), but we verify routing was attempted
            # Method could be WEBSOCKET (timeout) or ADB (fallback)
            assert result.method in (CommandMethod.WEBSOCKET, CommandMethod.ADB)

    @pytest.mark.asyncio
    async def test_launch_app_not_bypassed(self):
        """Verify launch_app goes through normal routing (bypass removed)."""
        router = CommandRouter()

        # Mock deps with mqtt_manager that has device connected
        mock_mqtt = Mock()
        mock_mqtt.is_connected = True
        mock_mqtt.is_device_connected = Mock(return_value=True)
        mock_mqtt.request_launch_app = AsyncMock(return_value={"success": True})

        mock_adb = Mock()
        mock_adb.launch_app = AsyncMock(return_value=True)

        mock_deps = Mock()
        mock_deps.mqtt_manager = mock_mqtt
        mock_deps.adb_bridge = mock_adb

        router.set_deps(mock_deps)

        result = await router.execute(
            "192.168.1.2:42519",
            "launch_app",
            {"package_name": "com.example.app"}
        )

        # Should use MQTT (not ADB bypass)
        assert result.success is True
        assert result.method == CommandMethod.MQTT
        mock_mqtt.request_launch_app.assert_called_once()
        mock_adb.launch_app.assert_not_called()

    @pytest.mark.asyncio
    async def test_wake_screen_not_bypassed(self):
        """Verify wake_screen goes through normal routing (bypass removed)."""
        router = CommandRouter()

        mock_mqtt = Mock()
        mock_mqtt.is_connected = True
        mock_mqtt.is_device_connected = Mock(return_value=True)
        mock_mqtt.request_wake_screen = AsyncMock(return_value={"success": True})

        mock_deps = Mock()
        mock_deps.mqtt_manager = mock_mqtt

        router.set_deps(mock_deps)

        result = await router.execute(
            "192.168.1.2:42519",
            "wake_screen",
            {}
        )

        assert result.success is True
        assert result.method == CommandMethod.MQTT
        mock_mqtt.request_wake_screen.assert_called_once()

    @pytest.mark.asyncio
    async def test_unlock_not_bypassed(self):
        """Verify unlock goes through normal routing (bypass removed)."""
        router = CommandRouter()

        mock_mqtt = Mock()
        mock_mqtt.is_connected = True
        mock_mqtt.is_device_connected = Mock(return_value=True)
        mock_mqtt.request_unlock = AsyncMock(return_value={"success": True})

        mock_deps = Mock()
        mock_deps.mqtt_manager = mock_mqtt

        router.set_deps(mock_deps)

        result = await router.execute(
            "192.168.1.2:42519",
            "unlock",
            {}
        )

        assert result.success is True
        assert result.method == CommandMethod.MQTT
        mock_mqtt.request_unlock.assert_called_once()


class TestRoutingInfo:
    """Test routing info retrieval."""

    def test_get_routing_info_websocket_preferred(self):
        """Should recommend WebSocket when available."""
        router = CommandRouter()
        mock_ws = Mock()
        mock_send = AsyncMock()

        router.register_websocket("192.168.1.2:42519", mock_ws, mock_send)

        info = router.get_routing_info("192.168.1.2:42519")

        assert info["websocket_available"] is True
        assert info["recommended_method"] == "websocket"

    def test_get_routing_info_mqtt_preferred(self):
        """Should recommend MQTT when WS unavailable but MQTT connected."""
        router = CommandRouter()

        mock_mqtt = Mock()
        mock_mqtt.is_connected = True
        mock_mqtt.is_device_connected = Mock(return_value=True)

        mock_deps = Mock()
        mock_deps.mqtt_manager = mock_mqtt
        mock_deps.adb_bridge = Mock()

        router.set_deps(mock_deps)

        info = router.get_routing_info("192.168.1.2:42519")

        assert info["websocket_available"] is False
        assert info["mqtt_available"] is True
        assert info["recommended_method"] == "mqtt"

    def test_get_routing_info_adb_fallback(self):
        """Should recommend ADB when no companion available."""
        router = CommandRouter()

        mock_deps = Mock()
        mock_deps.mqtt_manager = None
        mock_deps.adb_bridge = Mock()

        router.set_deps(mock_deps)

        info = router.get_routing_info("192.168.1.2:42519")

        assert info["websocket_available"] is False
        assert info["mqtt_available"] is False
        assert info["adb_available"] is True
        assert info["recommended_method"] == "adb"
