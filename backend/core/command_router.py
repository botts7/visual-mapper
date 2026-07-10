"""
Command Router - Routes commands through companion (WebSocket/MQTT) or ADB.

This module provides intelligent command routing based on companion availability:
1. WebSocket commands when companion is streaming (lowest latency, no stream interruption)
2. MQTT commands when companion is connected but not streaming
3. ADB commands as fallback when no companion available

Target latency:
- WebSocket: 10-50ms (same connection as streaming)
- MQTT: 50-200ms (separate connection, request-response)
- ADB: 100-500ms (process spawn, device communication)
"""

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)


class CommandMethod(Enum):
    """Command execution method used."""
    WEBSOCKET = "websocket"
    MQTT = "mqtt"
    ADB = "adb"


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    method: CommandMethod
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    latency_ms: float = 0.0


class CommandRouter:
    """
    Routes commands to companion (WebSocket/MQTT) or ADB based on availability.

    Usage:
        router = CommandRouter(deps)
        result = await router.execute("192.168.1.2:5555", "tap", {"x": 500, "y": 300})
    """

    # Supported commands and their required parameters
    SUPPORTED_COMMANDS = {
        "tap": {"required": ["x", "y"]},
        "swipe": {"required": ["x1", "y1", "x2", "y2"], "optional": ["duration"]},
        "long_press": {"required": ["x", "y"]},
        "key_event": {"required": ["key"]},
        "launch_app": {"required": ["package_name"], "optional": ["force_restart"]},
        "get_elements": {"optional": ["bounds_only"]},
        "input_text": {"required": ["text"]},
        "get_screen_info": {},
        # Power/Lock commands - prefer companion to avoid ADB stream interruption
        "wake_screen": {},
        "is_locked": {},
        "get_screen_state": {},
        "unlock": {"optional": ["pin"]},
    }

    def __init__(self, deps=None):
        """
        Initialize CommandRouter.

        Args:
            deps: Dependencies container with adb_bridge, mqtt_manager, etc.
        """
        self._deps = deps

        # WebSocket connections for streaming devices
        # Map: device_id -> websocket object
        self._websocket_connections: Dict[str, Any] = {}

        # Track when WebSocket disconnected for logging purposes
        # Map: device_id -> disconnect timestamp
        self._websocket_disconnected_at: Dict[str, float] = {}

        # Pending WebSocket command futures
        # Map: request_id -> asyncio.Future
        self._pending_ws_commands: Dict[str, asyncio.Future] = {}

        # Command timeout in seconds (reduced for faster fallback when companion unresponsive)
        self._default_timeout = 3.0

        logger.info("[CommandRouter] Initialized")

    def set_deps(self, deps):
        """Set dependencies after initialization."""
        self._deps = deps

    def _normalize_device_id(self, device_id: str) -> str:
        """Normalize device ID to base IP for comparison across formats.

        Handles:
        - 192.0.2.10:5555 -> 192.0.2.10
        - 192_0_2_10_companion -> 192.0.2.10
        - 192_0_2_10_5555 -> 192.0.2.10
        """
        # Remove _companion suffix
        if device_id.endswith("_companion"):
            device_id = device_id[:-10]

        # Replace underscores with dots
        if "_" in device_id:
            device_id = device_id.replace("_", ".")

        # Remove port (anything after :)
        if ":" in device_id:
            device_id = device_id.split(":")[0]

        return device_id

    def register_websocket(self, device_id: str, websocket, send_fn: Callable):
        """
        Register a WebSocket connection for a device.

        Args:
            device_id: Device identifier
            websocket: WebSocket connection object
            send_fn: Async function to send JSON messages
        """
        self._websocket_connections[device_id] = {
            "websocket": websocket,
            "send_fn": send_fn,
            "registered_at": time.time()
        }
        # Clear disconnect timestamp when WS reconnects (using normalized ID)
        normalized_id = self._normalize_device_id(device_id)
        self._websocket_disconnected_at.pop(normalized_id, None)
        logger.info(f"[CommandRouter] Registered WebSocket for {device_id}")

    def unregister_websocket(self, device_id: str):
        """Unregister WebSocket connection for a device."""
        if device_id in self._websocket_connections:
            del self._websocket_connections[device_id]
            # Record disconnect time using normalized ID for logging
            normalized_id = self._normalize_device_id(device_id)
            self._websocket_disconnected_at[normalized_id] = time.time()
            logger.info(f"[CommandRouter] Unregistered WebSocket for {device_id}")

    def has_websocket(self, device_id: str) -> bool:
        """Check if device has an active WebSocket connection."""
        return device_id in self._websocket_connections

    async def execute(
        self,
        device_id: str,
        command: str,
        params: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> CommandResult:
        """
        Execute a command on a device using the best available method.

        Routing priority:
        1. WebSocket (if companion is streaming)
        2. MQTT (if companion is connected)
        3. ADB (fallback)

        Args:
            device_id: Device identifier
            command: Command name (tap, swipe, launch_app, etc.)
            params: Command parameters
            timeout: Optional timeout override

        Returns:
            CommandResult with success status, method used, and data
        """
        start_time = time.time()
        timeout = timeout or self._default_timeout

        # Validate command
        if command not in self.SUPPORTED_COMMANDS:
            return CommandResult(
                success=False,
                method=CommandMethod.ADB,
                error=f"Unknown command: {command}"
            )

        # Validate required parameters
        cmd_spec = self.SUPPORTED_COMMANDS[command]
        required = cmd_spec.get("required", [])
        for param in required:
            if param not in params:
                return CommandResult(
                    success=False,
                    method=CommandMethod.ADB,
                    error=f"Missing required parameter: {param}"
                )

        # Try routing methods in priority order
        result = None

        # Log routing availability for debugging
        ws_available = self._should_use_websocket(device_id)
        mqtt_available = self._should_use_mqtt(device_id)
        logger.info(
            f"[CommandRouter] {command} for {device_id}: "
            f"WS={ws_available}, MQTT={mqtt_available}"
        )

        # 1. Try WebSocket (if streaming)
        if ws_available:
            logger.info(f"[CommandRouter] Using WebSocket for {command} on {device_id}")
            result = await self._execute_websocket(device_id, command, params, timeout)
            if result.success:
                result.latency_ms = (time.time() - start_time) * 1000
                return result
            logger.warning(f"[CommandRouter] WebSocket failed for {command}, trying MQTT")

        # 2. Try MQTT (if companion connected)
        if mqtt_available:
            logger.info(f"[CommandRouter] Using MQTT for {command} on {device_id}")
            result = await self._execute_mqtt(device_id, command, params, timeout)
            if result.success:
                result.latency_ms = (time.time() - start_time) * 1000
                return result
            logger.warning(f"[CommandRouter] MQTT failed for {command}, falling back to ADB")

        # 3. Fall back to ADB
        logger.info(f"[CommandRouter] Using ADB for {command} on {device_id}")
        result = await self._execute_adb(device_id, command, params, timeout)
        result.latency_ms = (time.time() - start_time) * 1000
        return result

    def _should_use_websocket(self, device_id: str) -> bool:
        """Check if WebSocket is available for the device."""
        # Check direct registration
        if device_id in self._websocket_connections:
            return True

        # Check companion stream manager (imported lazily)
        try:
            from core.streaming.companion_receiver import companion_stream_manager
            if companion_stream_manager.is_streaming(device_id):
                return companion_stream_manager.has_websocket_for_commands(device_id)
        except (ImportError, AttributeError):
            pass

        return False

    def _should_use_mqtt(self, device_id: str) -> bool:
        """Check if MQTT is available for the device."""
        if not self._deps or not hasattr(self._deps, 'mqtt_manager'):
            return False

        mqtt = self._deps.mqtt_manager
        if not mqtt:
            return False

        # Check if mqtt manager is connected to broker (is_connected is a property)
        if hasattr(mqtt, 'is_connected') and not mqtt.is_connected:
            return False

        # Check if companion is connected for this device via MQTT
        if hasattr(mqtt, 'is_device_connected'):
            return mqtt.is_device_connected(device_id)

        # Fallback: check if mqtt has the launch_app method (it should)
        return hasattr(mqtt, 'request_launch_app')

    async def _execute_websocket(
        self,
        device_id: str,
        command: str,
        params: Dict[str, Any],
        timeout: float
    ) -> CommandResult:
        """Execute command via WebSocket."""
        try:
            # Get companion stream manager
            from core.streaming.companion_receiver import companion_stream_manager

            # Generate request ID for response matching
            request_id = str(uuid.uuid4())

            # Create future for response
            response_future = asyncio.Future()
            self._pending_ws_commands[request_id] = response_future

            try:
                # Send command via companion receiver
                sent = await companion_stream_manager.send_command(
                    device_id,
                    {
                        "type": "command",
                        "request_id": request_id,
                        "command": command,
                        "params": params
                    }
                )

                if not sent:
                    return CommandResult(
                        success=False,
                        method=CommandMethod.WEBSOCKET,
                        error="Failed to send WebSocket command"
                    )

                # Wait for response
                response = await asyncio.wait_for(response_future, timeout=timeout)

                return CommandResult(
                    success=response.get("success", False),
                    method=CommandMethod.WEBSOCKET,
                    data=response.get("data", {}),
                    error=response.get("error")
                )

            finally:
                self._pending_ws_commands.pop(request_id, None)

        except asyncio.TimeoutError:
            logger.warning(
                f"[CommandRouter] WebSocket command {command} timed out after {timeout}s - "
                f"companion may not be responding"
            )
            return CommandResult(
                success=False,
                method=CommandMethod.WEBSOCKET,
                error=f"WebSocket command timed out after {timeout}s"
            )
        except Exception as e:
            logger.error(f"[CommandRouter] WebSocket error: {e}")
            return CommandResult(
                success=False,
                method=CommandMethod.WEBSOCKET,
                error=str(e)
            )

    def handle_websocket_response(self, request_id: str, response: Dict[str, Any]):
        """
        Handle a WebSocket command response.

        Called by companion receiver when it receives a command_response message.
        """
        future = self._pending_ws_commands.get(request_id)
        if future and not future.done():
            future.set_result(response)
            logger.debug(f"[CommandRouter] Resolved WebSocket response for {request_id}")
        else:
            logger.warning(f"[CommandRouter] No pending request for {request_id}")

    async def _execute_mqtt(
        self,
        device_id: str,
        command: str,
        params: Dict[str, Any],
        timeout: float
    ) -> CommandResult:
        """
        Execute command via MQTT.

        Currently only launch_app and get_elements (UI tree) are supported via MQTT.
        Other commands fall back to ADB.
        """
        try:
            mqtt = self._deps.mqtt_manager

            # Map commands to MQTT methods (only implemented ones)
            if command == "launch_app":
                if not hasattr(mqtt, 'request_launch_app'):
                    return CommandResult(
                        success=False,
                        method=CommandMethod.MQTT,
                        error="MQTT launch_app not available"
                    )
                response = await mqtt.request_launch_app(
                    device_id,
                    params["package_name"],
                    params.get("force_restart", True),
                    timeout=timeout
                )
            elif command == "get_elements":
                if not hasattr(mqtt, 'request_ui_tree'):
                    return CommandResult(
                        success=False,
                        method=CommandMethod.MQTT,
                        error="MQTT ui_tree not available"
                    )
                response = await mqtt.request_ui_tree(
                    device_id,
                    timeout=timeout
                )

            elif command == "tap":
                response = await mqtt.request_tap(
                    device_id,
                    params.get("x", 0),
                    params.get("y", 0),
                    timeout=timeout
                )

            elif command == "swipe":
                response = await mqtt.request_swipe(
                    device_id,
                    params.get("x1", 0),
                    params.get("y1", 0),
                    params.get("x2", 0),
                    params.get("y2", 0),
                    params.get("duration", 300),
                    timeout=timeout
                )

            elif command == "key_event":
                response = await mqtt.request_key_event(
                    device_id,
                    params.get("key", ""),
                    timeout=timeout
                )

            elif command == "input_text":
                response = await mqtt.request_input_text(
                    device_id,
                    params.get("text", ""),
                    timeout=timeout
                )

            elif command == "wake_screen":
                response = await mqtt.request_wake_screen(
                    device_id,
                    timeout=timeout
                )

            elif command == "unlock":
                response = await mqtt.request_unlock(
                    device_id,
                    params.get("pin", ""),
                    timeout=timeout
                )

            elif command == "is_locked":
                response = await mqtt.request_is_locked(
                    device_id,
                    timeout=timeout
                )

            elif command == "get_screen_state":
                response = await mqtt.request_screen_state(
                    device_id,
                    timeout=timeout
                )

            else:
                # Command not implemented via MQTT - fall through to ADB
                logger.debug(f"[CommandRouter] MQTT: {command} not implemented, use ADB")
                return CommandResult(
                    success=False,
                    method=CommandMethod.MQTT,
                    error=f"Command {command} not supported via MQTT"
                )

            if response is None:
                return CommandResult(
                    success=False,
                    method=CommandMethod.MQTT,
                    error="MQTT request timed out or failed"
                )

            return CommandResult(
                success=response.get("success", True),
                method=CommandMethod.MQTT,
                data=response.get("data", response)
            )

        except AttributeError as e:
            # MQTT method doesn't exist
            logger.debug(f"[CommandRouter] MQTT method not available for {command}: {e}")
            return CommandResult(
                success=False,
                method=CommandMethod.MQTT,
                error=f"MQTT command {command} not implemented"
            )
        except Exception as e:
            logger.error(f"[CommandRouter] MQTT error: {e}")
            return CommandResult(
                success=False,
                method=CommandMethod.MQTT,
                error=str(e)
            )

    async def _execute_adb(
        self,
        device_id: str,
        command: str,
        params: Dict[str, Any],
        timeout: float
    ) -> CommandResult:
        """Execute command via ADB."""
        try:
            if not self._deps or not hasattr(self._deps, 'adb_bridge'):
                return CommandResult(
                    success=False,
                    method=CommandMethod.ADB,
                    error="ADB bridge not available"
                )

            adb = self._deps.adb_bridge

            # Map commands to ADB methods
            if command == "tap":
                await adb.tap(device_id, params["x"], params["y"])
                return CommandResult(success=True, method=CommandMethod.ADB)

            elif command == "swipe":
                await adb.swipe(
                    device_id,
                    params["x1"],
                    params["y1"],
                    params["x2"],
                    params["y2"],
                    params.get("duration", 300)
                )
                return CommandResult(success=True, method=CommandMethod.ADB)

            elif command == "long_press":
                # Long press via ADB is just a tap with longer duration
                # implemented as a very short swipe
                x, y = params["x"], params["y"]
                await adb.swipe(device_id, x, y, x, y, 500)
                return CommandResult(success=True, method=CommandMethod.ADB)

            elif command == "key_event":
                key = params["key"]
                # Map key names to keycodes if needed
                keycode_map = {
                    "BACK": "KEYCODE_BACK",
                    "HOME": "KEYCODE_HOME",
                    "RECENTS": "KEYCODE_APP_SWITCH",
                }
                keycode = keycode_map.get(key.upper(), key)
                await adb.keyevent(device_id, keycode)
                return CommandResult(success=True, method=CommandMethod.ADB)

            elif command == "launch_app":
                success = await adb.launch_app(device_id, params["package_name"])
                return CommandResult(success=success, method=CommandMethod.ADB)

            elif command == "get_elements":
                elements = await adb.get_ui_elements(device_id)
                return CommandResult(
                    success=True,
                    method=CommandMethod.ADB,
                    data={"elements": elements}
                )

            elif command == "input_text":
                await adb.type_text(device_id, params["text"])
                return CommandResult(success=True, method=CommandMethod.ADB)

            elif command == "get_screen_info":
                # Get current activity/package via ADB
                info = await adb.get_current_activity(device_id)
                return CommandResult(
                    success=True,
                    method=CommandMethod.ADB,
                    data=info or {}
                )

            elif command == "wake_screen":
                # Send KEYCODE_WAKEUP via ADB
                await adb.keyevent(device_id, 224)
                return CommandResult(
                    success=True,
                    method=CommandMethod.ADB,
                    data={"status": "wake_sent"}
                )

            elif command == "is_locked":
                # Check lock status via ADB shell
                result = await adb.shell_command(
                    device_id,
                    "dumpsys window | grep -E 'mDreamingLockscreen|isStatusBarKeyguard|mShowingLockscreen'"
                )
                is_locked = "true" in result.lower() or "mShowingLockscreen=true" in result
                return CommandResult(
                    success=True,
                    method=CommandMethod.ADB,
                    data={"isLocked": is_locked, "raw": result[:200]}
                )

            elif command == "get_screen_state":
                # Check screen state via ADB
                result = await adb.shell_command(device_id, "dumpsys power | grep -E 'mWakefulness|mScreenOn'")
                screen_on = "Awake" in result or "mScreenOn=true" in result
                lock_result = await adb.shell_command(device_id, "dumpsys window | grep mShowingLockscreen")
                is_locked = "true" in lock_result.lower()
                return CommandResult(
                    success=True,
                    method=CommandMethod.ADB,
                    data={
                        "isScreenOn": screen_on,
                        "isLocked": is_locked,
                    }
                )

            elif command == "unlock":
                # Unlock via ADB: wake + swipe + optional PIN
                # Step 1: Wake screen
                await adb.keyevent(device_id, 224)  # KEYCODE_WAKEUP
                await asyncio.sleep(0.5)

                # Step 2: Get screen dimensions for proper swipe coordinates
                try:
                    size_output = await adb.shell(device_id, "wm size")
                    # Parse "Physical size: 1080x1920" or "Override size: ..."
                    match = re.search(r'(\d+)x(\d+)', size_output)
                    if match:
                        width = int(match.group(1))
                        height = int(match.group(2))
                    else:
                        width, height = 1080, 1920  # Default fallback
                except Exception:
                    width, height = 1080, 1920  # Default fallback

                # Step 3: Swipe up from bottom center to reveal PIN/pattern screen
                center_x = width // 2
                swipe_start_y = int(height * 0.85)  # 85% from top
                swipe_end_y = int(height * 0.25)    # 25% from top
                await adb.swipe(device_id, center_x, swipe_start_y, center_x, swipe_end_y, 300)
                await asyncio.sleep(0.5)

                # Step 4: Enter PIN if provided
                pin = params.get("pin", "")
                if pin:
                    # Try pressing MENU key first (helps on Samsung)
                    await adb.keyevent(device_id, 82)  # KEYCODE_MENU
                    await asyncio.sleep(0.3)
                    await adb.type_text(device_id, pin)
                    await asyncio.sleep(0.3)
                    await adb.keyevent(device_id, 66)  # KEYCODE_ENTER

                return CommandResult(
                    success=True,
                    method=CommandMethod.ADB,
                    data={
                        "status": "unlock_attempted",
                        "pinEntered": bool(pin),
                        "screenSize": f"{width}x{height}"
                    }
                )

            else:
                return CommandResult(
                    success=False,
                    method=CommandMethod.ADB,
                    error=f"Command {command} not supported via ADB"
                )

        except Exception as e:
            logger.error(f"[CommandRouter] ADB error for {command}: {e}")
            return CommandResult(
                success=False,
                method=CommandMethod.ADB,
                error=str(e)
            )

    def get_routing_info(self, device_id: str) -> Dict[str, Any]:
        """
        Get routing information for a device.

        Returns which methods are available and recommended.
        """
        ws_available = self._should_use_websocket(device_id)
        mqtt_available = self._should_use_mqtt(device_id)
        adb_available = self._deps and hasattr(self._deps, 'adb_bridge')

        # Determine recommended method
        if ws_available:
            recommended = "websocket"
        elif mqtt_available:
            recommended = "mqtt"
        elif adb_available:
            recommended = "adb"
        else:
            recommended = "none"

        return {
            "device_id": device_id,
            "websocket_available": ws_available,
            "mqtt_available": mqtt_available,
            "adb_available": adb_available,
            "recommended_method": recommended
        }


# Global singleton instance
command_router = CommandRouter()
