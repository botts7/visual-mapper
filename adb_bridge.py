"""
Visual Mapper - ADB Bridge
Version: 0.0.3 (Phase 2)

This module handles communication with Android devices via ADB.
Now uses hybrid connection strategy with support for:
- Legacy TCP/IP (port 5555)
- Android 11+ wireless pairing
- TLS connections
- ADB Server addon
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from utils.adb_manager import ADBManager
from utils.base_connection import BaseADBConnection

logger = logging.getLogger(__name__)


class ADBBridge:
    """
    Android Debug Bridge connection manager with hybrid strategy.

    Handles device connections, screenshot capture, and UI element extraction.
    Uses ADBManager to automatically select optimal connection method.
    """

    def __init__(self):
        """Initialize ADB bridge with ADBManager"""
        self.manager = ADBManager(hass=None)  # Standalone mode
        self.devices: Dict[str, BaseADBConnection] = {}
        self._adb_lock = asyncio.Lock()  # Prevent concurrent ADB operations
        self._device_discovered_callbacks = []  # Callbacks for device auto-import

        logger.info("[ADBBridge] Initialized (Phase 2 - hybrid connection strategy)")

    def register_device_discovered_callback(self, callback):
        """
        Register a callback to be called when a device is auto-imported.

        Args:
            callback: Async function that takes device_id as parameter
        """
        self._device_discovered_callbacks.append(callback)
        logger.info(f"[ADBBridge] Registered device discovered callback: {callback.__name__}")

    async def pair_device(self, pairing_host: str, pairing_port: int, pairing_code: str) -> bool:
        """
        Pair with Android 11+ device using wireless pairing.

        Args:
            pairing_host: Device IP address
            pairing_port: Pairing port (shown on device)
            pairing_code: 6-digit pairing code (shown on device)

        Returns:
            True if pairing successful, False otherwise
        """
        try:
            logger.info(f"[ADBBridge] Pairing with {pairing_host}:{pairing_port}")

            # Pairing REQUIRES subprocess ADB (adb pair command)
            # Import here to avoid circular dependency
            from utils.adb_subprocess import SubprocessADBConnection

            # Create a temporary subprocess connection for pairing
            device_id = f"{pairing_host}:{pairing_port}"
            conn = SubprocessADBConnection(None, device_id)

            # Use subprocess to run: adb pair <host>:<port> <code>
            try:
                def _pair():
                    import subprocess
                    # Use Popen for interactive input
                    proc = subprocess.Popen(
                        ["adb", "pair", device_id],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )

                    # Send pairing code to stdin
                    try:
                        stdout, stderr = proc.communicate(input=f"{pairing_code}\n", timeout=10)
                        output = stdout + stderr

                        # Check for success indicators
                        success = (
                            "Successfully paired" in output or
                            "success" in output.lower() or
                            proc.returncode == 0
                        )

                        return success, output
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        stdout, stderr = proc.communicate()
                        return False, f"Timeout: {stdout + stderr}"

                success, output = await conn._run_in_executor(_pair)

                if success:
                    logger.info(f"[ADBBridge] ✅ Paired successfully: {output}")
                    return True
                else:
                    logger.error(f"[ADBBridge] ❌ Pairing failed: {output}")
                    return False

            except Exception as e:
                logger.error(f"[ADBBridge] Pairing command failed: {e}")
                return False

        except Exception as e:
            logger.error(f"[ADBBridge] Pairing error: {e}")
            return False

    async def connect_device(self, host: str, port: int = 5555) -> str:
        """
        Connect to Android device via TCP/IP using optimal strategy.

        Args:
            host: Device IP address
            port: ADB port (default: 5555)

        Returns:
            device_id: Format "host:port"

        Raises:
            ConnectionError: If connection fails
        """
        device_id = f"{host}:{port}"

        # Return existing connection if already connected
        if device_id in self.devices:
            logger.info(f"[ADBBridge] Device {device_id} already connected")
            return device_id

        try:
            logger.info(f"[ADBBridge] Connecting to {device_id}...")

            # Get optimal connection type from manager
            conn = await self.manager.get_connection(host, port)

            # Attempt connection
            if await conn.connect():
                self.devices[device_id] = conn
                logger.info(f"[ADBBridge] ✅ Connected to {device_id}")
                return device_id
            else:
                logger.error(f"[ADBBridge] ❌ Failed to connect to {device_id}")
                raise ConnectionError(f"Failed to connect to {device_id}")

        except Exception as e:
            logger.error(f"[ADBBridge] ❌ Connection error for {device_id}: {e}")
            raise ConnectionError(f"Failed to connect to {device_id}: {e}")

    async def disconnect_device(self, device_id: str) -> None:
        """
        Disconnect from device.

        Args:
            device_id: Device identifier
        """
        if device_id not in self.devices:
            logger.warning(f"[ADBBridge] Device {device_id} not found")
            return

        try:
            conn = self.devices[device_id]
            await conn.close()
            del self.devices[device_id]
            logger.info(f"[ADBBridge] Disconnected from {device_id}")
        except Exception as e:
            logger.error(f"[ADBBridge] Error disconnecting {device_id}: {e}")

    async def discover_devices(self) -> List[Dict]:
        """
        Discover devices already connected via ADB.

        Uses `adb devices` to find devices and auto-imports them.

        Returns:
            List of discovered device dicts with id, state, model
        """
        async with self._adb_lock:  # Prevent concurrent adb commands
            try:
                import subprocess

                # Run adb devices -l in thread pool (non-blocking)
                def _run_adb_devices():
                    result = subprocess.run(
                        ["adb", "devices", "-l"],
                        capture_output=True,
                        text=True,
                        timeout=10  # Increased from 5s to 10s
                    )
                    return result.returncode == 0, result.stdout

                # Run in executor to avoid blocking event loop
                success, output = await asyncio.to_thread(_run_adb_devices)

                if not success:
                    logger.warning("[ADBBridge] adb devices command failed")
                    return []

                devices_list = []

                # Parse output (skip header line)
                for line in output.split('\n')[1:]:
                    line = line.strip()
                    if not line:
                        continue

                    # Format: "192.168.86.2:40951 device product:gta8xx model:SM_X205 ..."
                    parts = line.split()
                    if len(parts) < 2:
                        continue

                    device_id = parts[0]
                    state = parts[1]

                    # Extract model if available
                    model = ""
                    for part in parts[2:]:
                        if part.startswith("model:"):
                            model = part.split(":")[1].replace("_", " ")
                            break

                    devices_list.append({
                        "id": device_id,
                        "state": state,
                        "model": model,
                        "discovered": True
                    })

                    # Auto-import device if not already tracked
                    if device_id not in self.devices and state == "device":
                        logger.info(f"[ADBBridge] Auto-importing discovered device {device_id}")
                        try:
                            # Create connection for this device
                            conn = await self.manager.get_connection(device_id.split(':')[0], int(device_id.split(':')[1]))
                            # Mark as already connected
                            conn._connected = True
                            self.devices[device_id] = conn

                            # Trigger device discovered callbacks
                            for callback in self._device_discovered_callbacks:
                                try:
                                    await callback(device_id)
                                except Exception as e:
                                    logger.error(f"[ADBBridge] Device discovered callback failed: {e}")
                        except Exception as e:
                            logger.warning(f"[ADBBridge] Failed to auto-import {device_id}: {e}")

                return devices_list

            except FileNotFoundError:
                logger.warning("[ADBBridge] ADB binary not found for device discovery")
                return []
            except subprocess.TimeoutExpired:
                logger.error("[ADBBridge] Device discovery timed out after 10 seconds")
                return []
            except Exception as e:
                logger.error(f"[ADBBridge] Device discovery failed: {e}")
                return []

    async def get_devices(self) -> List[Dict]:
        """
        Get list of connected devices with metadata.

        First discovers ADB-connected devices, then returns all tracked devices
        with model info and current activity.

        Returns:
            List of device dicts with id, state, model, current_activity, and connected status
        """
        # Discover and auto-import ADB devices (includes model info)
        discovered = await self.discover_devices()

        # Create lookup for model names
        model_lookup = {dev["id"]: dev.get("model", "") for dev in discovered}

        devices_list = []

        for device_id, conn in self.devices.items():
            device_info = {
                "id": device_id,
                "state": "device",  # Connected state
                "connected": conn.available,
                "model": model_lookup.get(device_id, "Unknown model")
            }

            # Get current activity if device is available
            if conn.available:
                try:
                    current_activity = await self.get_current_activity(device_id)
                    device_info["current_activity"] = current_activity
                except Exception as e:
                    logger.debug(f"[ADBBridge] Could not get current activity for {device_id}: {e}")
                    device_info["current_activity"] = "Unknown"
            else:
                device_info["current_activity"] = "Offline"

            devices_list.append(device_info)

        return devices_list

    async def capture_screenshot(self, device_id: str) -> bytes:
        """
        Capture PNG screenshot from device.

        Args:
            device_id: Device identifier

        Returns:
            PNG image bytes

        Raises:
            ValueError: If device not connected
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        try:
            logger.debug(f"[ADBBridge] Capturing screenshot from {device_id}")

            # Execute screencap command
            # -p flag outputs PNG format
            result = await conn.shell("screencap -p")

            # Result should be bytes for PNG data
            if isinstance(result, str):
                # Fallback: encode as latin1 if somehow still a string
                result = result.encode('latin1')

            logger.debug(f"[ADBBridge] Screenshot captured: {len(result)} bytes")
            return result

        except Exception as e:
            logger.error(f"[ADBBridge] Screenshot failed: {e}")
            raise

    async def get_ui_elements(self, device_id: str) -> List[Dict]:
        """
        Extract UI element hierarchy using uiautomator.

        Args:
            device_id: Device identifier

        Returns:
            List of element dicts with text, bounds, resource_id, etc.

        Raises:
            ValueError: If device not connected
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        try:
            logger.debug(f"[ADBBridge] Extracting UI elements from {device_id}")

            # Dump UI hierarchy to stdout (v3 approach)
            # Using /dev/tty instead of file path to get output directly
            # --compressed flag prevents waiting for idle state (fixes animated UIs)
            xml_str = await conn.shell("uiautomator dump --compressed /dev/tty")

            # Clean up the output:
            # 1. Remove the "UI hierarchy dumped to: /dev/tty" message
            # 2. Extract only the XML portion (starts with <?xml)
            # 3. Remove any trailing junk after the closing tag
            xml_start = xml_str.find('<?xml')
            if xml_start == -1:
                logger.error(f"[ADBBridge] No XML found in uiautomator output: {xml_str[:200]}")
                raise ValueError("No XML data in uiautomator output")

            xml_str = xml_str[xml_start:]

            # Find the end of the XML document
            # Look for closing </hierarchy> tag
            xml_end = xml_str.find('</hierarchy>')
            if xml_end > 0:
                xml_str = xml_str[:xml_end + len('</hierarchy>')]

            logger.debug(f"[ADBBridge] Cleaned XML length: {len(xml_str)} chars")

            # Parse XML
            root = ET.fromstring(xml_str)
            elements = []

            # Extract all nodes
            for node in root.iter('node'):
                element = {
                    'text': node.get('text', ''),
                    'resource_id': node.get('resource-id', ''),
                    'class': node.get('class', ''),
                    'bounds': self._parse_bounds(node.get('bounds', '')),
                    'clickable': node.get('clickable') == 'true',
                    'visible': node.get('visible-to-user') == 'true',
                    'enabled': node.get('enabled') == 'true',
                    'focused': node.get('focused') == 'true',
                }
                elements.append(element)

            logger.debug(f"[ADBBridge] Extracted {len(elements)} UI elements")
            return elements

        except Exception as e:
            logger.error(f"[ADBBridge] UI extraction failed: {e}")
            raise

    def _parse_bounds(self, bounds_str: str) -> Optional[Dict]:
        """
        Parse UI element bounds string.

        Args:
            bounds_str: Format "[x1,y1][x2,y2]"

        Returns:
            Dict with x, y, width, height or None if invalid
        """
        try:
            # Pattern: [x1,y1][x2,y2]
            matches = re.findall(r'\[(\d+),(\d+)\]', bounds_str)

            if len(matches) == 2:
                x1, y1 = map(int, matches[0])
                x2, y2 = map(int, matches[1])

                return {
                    'x': x1,
                    'y': y1,
                    'width': x2 - x1,
                    'height': y2 - y1
                }
        except Exception as e:
            logger.warning(f"[ADBBridge] Failed to parse bounds '{bounds_str}': {e}")

        return None

    # Device Control Methods

    async def tap(self, device_id: str, x: int, y: int) -> None:
        """
        Simulate tap at coordinates.

        Args:
            device_id: Device identifier
            x: X coordinate
            y: Y coordinate
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        logger.debug(f"[ADBBridge] Tap at ({x}, {y}) on {device_id}")
        await conn.shell(f"input tap {x} {y}")

    async def swipe(self, device_id: str, x1: int, y1: int,
                    x2: int, y2: int, duration: int = 300) -> None:
        """
        Simulate swipe gesture.

        Args:
            device_id: Device identifier
            x1, y1: Start coordinates
            x2, y2: End coordinates
            duration: Swipe duration in ms (default: 300)
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        logger.debug(f"[ADBBridge] Swipe ({x1},{y1}) -> ({x2},{y2}) on {device_id}")
        await conn.shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")

    async def type_text(self, device_id: str, text: str) -> None:
        """
        Type text on device.

        Args:
            device_id: Device identifier
            text: Text to type (spaces will be escaped)
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        # Escape spaces with %s
        escaped_text = text.replace(' ', '%s')

        logger.debug(f"[ADBBridge] Type text on {device_id}")
        await conn.shell(f"input text {escaped_text}")

    async def keyevent(self, device_id: str, keycode: str) -> None:
        """
        Send key event to device.

        Args:
            device_id: Device identifier
            keycode: Android keycode (e.g., "KEYCODE_HOME", "3", "BACK")

        Common keycodes:
            KEYCODE_HOME (3) - Home button
            KEYCODE_BACK (4) - Back button
            KEYCODE_APP_SWITCH (187) - Recent apps
            KEYCODE_POWER (26) - Power button
            KEYCODE_VOLUME_UP (24) - Volume up
            KEYCODE_VOLUME_DOWN (25) - Volume down
            KEYCODE_MENU (82) - Menu button
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        logger.debug(f"[ADBBridge] Key event {keycode} on {device_id}")
        await conn.shell(f"input keyevent {keycode}")

    async def get_current_activity(self, device_id: str) -> str:
        """
        Get the current focused activity/window on the device.

        Args:
            device_id: Device identifier

        Returns:
            Current activity name (e.g., "com.android.launcher3/.Launcher")

        Raises:
            ValueError: If device not connected
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        try:
            # Use dumpsys to get current focused window
            # Example output: "mCurrentFocus=Window{abc123 u0 com.android.launcher3/com.android.launcher3.Launcher}"
            output = await conn.shell("dumpsys activity | grep mCurrentFocus")

            # Extract activity name from output
            # Pattern: Window{...package/activity}
            match = re.search(r'Window\{[^\}]+\s+([^\}]+)\}', output)
            if match:
                activity = match.group(1).strip()
                # Remove "u0 " prefix if present (user ID)
                activity = re.sub(r'^u\d+\s+', '', activity)
                logger.debug(f"[ADBBridge] Current activity: {activity}")
                return activity
            else:
                # Fallback: try to parse just the activity name
                if "mCurrentFocus=" in output:
                    # Extract anything that looks like package/activity
                    match = re.search(r'([a-zA-Z0-9_.]+/[a-zA-Z0-9_.]+)', output)
                    if match:
                        activity = match.group(1)
                        logger.debug(f"[ADBBridge] Current activity (fallback): {activity}")
                        return activity

                logger.warning(f"[ADBBridge] Could not parse activity from: {output[:200]}")
                return ""

        except Exception as e:
            logger.error(f"[ADBBridge] Failed to get current activity: {e}")
            return ""

    async def get_installed_apps(self, device_id: str) -> List[Dict[str, str]]:
        """
        Get list of installed apps (packages) on the device.

        Args:
            device_id: Device identifier

        Returns:
            List of dicts with package name and app label
            Example: [{"package": "com.android.chrome", "label": "Chrome"}, ...]

        Raises:
            ValueError: If device not connected
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        try:
            logger.debug(f"[ADBBridge] Listing installed apps for {device_id}")

            # Get ALL packages (system + third-party)
            # Frontend can filter if needed - PARITY PRINCIPLE
            output = await conn.shell("pm list packages")

            apps = []
            for line in output.strip().split('\n'):
                if line.startswith('package:'):
                    package = line.replace('package:', '').strip()

                    # Determine if system app
                    # System apps typically start with: com.android, com.google, android
                    is_system = package.startswith(('com.android', 'com.google', 'android.'))

                    # Simple label from package name
                    label = package.split('.')[-1].title()

                    apps.append({
                        "package": package,
                        "label": label,
                        "is_system": is_system
                    })

            logger.info(f"[ADBBridge] Found {len(apps)} total apps on {device_id}")
            return apps

        except Exception as e:
            logger.error(f"[ADBBridge] Failed to get installed apps: {e}")
            return []

    async def launch_app(self, device_id: str, package_name: str) -> bool:
        """
        Launch an app by package name.

        Args:
            device_id: Device identifier
            package_name: Package name (e.g., "com.android.chrome")

        Returns:
            True if launch command succeeded

        Raises:
            ValueError: If device not connected
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        try:
            logger.info(f"[ADBBridge] Launching app {package_name} on {device_id}")

            # Use monkey to launch app (works without knowing activity name)
            await conn.shell(f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1")

            return True

        except Exception as e:
            logger.error(f"[ADBBridge] Failed to launch app {package_name}: {e}")
            return False
