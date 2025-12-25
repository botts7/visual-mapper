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
from playstore_icon_scraper import PlayStoreIconScraper

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

        # Initialize Play Store scraper for app name extraction
        self.playstore_scraper = PlayStoreIconScraper()

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

            # Try using subprocess with exec-out for more reliable binary data transfer
            import subprocess

            def _run_screencap():
                result = subprocess.run(
                    ["adb", "-s", device_id, "exec-out", "screencap", "-p"],
                    capture_output=True,
                    timeout=30
                )
                return result.stdout if result.returncode == 0 else b""

            result = await asyncio.to_thread(_run_screencap)

            if result and len(result) > 1000:  # Valid PNG should be > 1KB
                logger.debug(f"[ADBBridge] Screenshot captured via exec-out: {len(result)} bytes")
                return result

            # Fallback to shell method if exec-out fails
            logger.debug("[ADBBridge] exec-out failed, trying shell method")
            result = await conn.shell("screencap -p")

            # Result should be bytes for PNG data
            if isinstance(result, str):
                # Fallback: encode as latin1 if somehow still a string
                result = result.encode('latin1')

            logger.debug(f"[ADBBridge] Screenshot captured via shell: {len(result)} bytes")
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

            # Dump UI hierarchy to file then read it (more reliable than /dev/tty)
            # Some devices don't output XML to /dev/tty properly
            dump_output = await conn.shell("uiautomator dump && cat /sdcard/window_dump.xml")

            # Clean up the output:
            # 1. Remove the "UI hierarchy dumped to: /sdcard/window_dump.xml" message
            # 2. Extract only the XML portion (starts with <?xml)
            # 3. Remove any trailing junk after the closing tag
            xml_start = dump_output.find('<?xml')
            if xml_start == -1:
                logger.error(f"[ADBBridge] No XML found in uiautomator output: {dump_output[:200]}")
                raise ValueError("No XML data in uiautomator output")

            xml_str = dump_output[xml_start:]

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
                    # Added for height estimation
                    'content_desc': node.get('content-desc', ''),
                    'scrollable': node.get('scrollable') == 'true',
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

    async def get_ui_hierarchy_xml(self, device_id: str) -> str:
        """
        Get raw UI hierarchy XML (for device_icon_scraper)

        Args:
            device_id: Device identifier

        Returns:
            Raw XML string from uiautomator
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        try:
            dump_output = await conn.shell("uiautomator dump && cat /sdcard/window_dump.xml")

            # Extract XML portion
            xml_start = dump_output.find('<?xml')
            if xml_start == -1:
                raise ValueError("No XML data in uiautomator output")

            xml_str = dump_output[xml_start:]

            # Find end of XML
            xml_end = xml_str.find('</hierarchy>')
            if xml_end > 0:
                xml_str = xml_str[:xml_end + len('</hierarchy>')]

            return xml_str
        except Exception as e:
            logger.error(f"[ADBBridge] get_ui_hierarchy_xml failed: {e}")
            raise

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
        # Use subprocess for swipe - adb-shell library has issues with input commands
        import subprocess
        await asyncio.to_thread(
            subprocess.run,
            ['adb', '-s', device_id, 'shell', 'input', 'touchscreen', 'swipe',
             str(x1), str(y1), str(x2), str(y2), str(duration)],
            capture_output=True, timeout=10
        )

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

    async def get_installed_apps(self, device_id: str, extract_real_labels: bool = True) -> List[Dict[str, str]]:
        """
        Get list of installed apps (packages) on the device.

        Args:
            device_id: Device identifier
            extract_real_labels: Extract real app names from dumpsys (slower but accurate)

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

            # Build package list with fallback labels
            packages = []
            for line in output.strip().split('\n'):
                if line.startswith('package:'):
                    package = line.replace('package:', '').strip()
                    packages.append(package)

            logger.debug(f"[ADBBridge] Found {len(packages)} total packages")

            # Get ONLY packages with LAUNCHER activities (apps in app drawer)
            # These are the only apps we can actually launch and automate
            # Excludes system services, frameworks, background processes - they can't be used in flows anyway
            launcher_output = await conn.shell(
                "cmd package query-activities --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER"
            )

            # Parse output to extract package names
            # Format: "packagename/activityname"
            launcher_packages_set = set()
            for line in launcher_output.strip().split('\n'):
                line = line.strip()
                if '/' in line and not line.startswith('['):  # Skip headers/errors
                    package = line.split('/')[0].strip()
                    if package:
                        launcher_packages_set.add(package)

            launcher_packages = sorted(list(launcher_packages_set))

            logger.info(f"[ADBBridge] Found {len(launcher_packages)} launchable apps (filtered from {len(packages)} total packages)")

            # Extract real labels only for launchable apps (performance optimization)
            label_map = {}
            if extract_real_labels:
                label_map = await self._extract_labels_batch(conn, launcher_packages)
                logger.info(f"[ADBBridge] Extracted {len(label_map)} real app labels")

            # Build final app list - ONLY launchable apps
            apps = []
            for package in launcher_packages:
                # Use real label if available, otherwise use smart fallback
                if package in label_map:
                    label = label_map[package]
                else:
                    label = self._smart_label_from_package(package)

                apps.append({
                    "package": package,
                    "label": label,
                    "is_system": False  # All apps returned are launchable (not system services)
                })

            logger.info(f"[ADBBridge] Found {len(apps)} total apps on {device_id}")
            return apps

        except Exception as e:
            logger.error(f"[ADBBridge] Failed to get installed apps: {e}")
            return []

    async def _extract_labels_batch(self, conn, packages: List[str]) -> Dict[str, str]:
        """
        Extract real app labels for multiple packages efficiently

        Multi-tier strategy:
        1. Try Play Store scraper (cached + on-demand, very fast)
        2. For remaining packages, try aapt dump (slower but accurate)

        Args:
            conn: Device connection
            packages: List of package names

        Returns:
            Dict mapping package_name -> real_label
        """
        labels = {}

        try:
            # TIER 1: Play Store scraper (cache-only for speed, real names fetched during icon loading)
            logger.debug(f"[ADBBridge] Checking Play Store cache for {len(packages)} packages...")
            playstore_count = 0

            for package in packages:
                # Use cache_only=True to prevent timeout (real names fetched asynchronously during icon load)
                app_name = self.playstore_scraper.get_app_name(package, cache_only=True)
                if app_name:
                    labels[package] = app_name
                    playstore_count += 1

            logger.info(f"[ADBBridge] ✅ Play Store cache provided {playstore_count} labels")

            # TIER 2: APK extraction for remaining packages (slower, limited)
            remaining_packages = [pkg for pkg in packages if pkg not in labels]

            if remaining_packages:
                logger.debug(f"[ADBBridge] Trying aapt for {len(remaining_packages)} remaining packages...")

                # Get all packages with their APK paths
                output = await conn.shell("pm list packages -f")

                # Build package -> path mapping
                package_paths = {}
                for line in output.split('\n'):
                    if line.startswith('package:'):
                        # Format: package:/data/app/com.example.app-xxx/base.apk=com.example.app
                        parts = line[8:].split('=')
                        if len(parts) == 2:
                            apk_path = parts[0].strip()
                            package = parts[1].strip()
                            package_paths[package] = apk_path

                logger.debug(f"[ADBBridge] Found {len(package_paths)} package paths")

                # For each remaining package, try to extract label using aapt
                # Limit to first 50 to avoid timeout
                aapt_count = 0
                for package in remaining_packages[:50]:
                    if package in package_paths:
                        try:
                            apk_path = package_paths[package]
                            # Try aapt dump badging
                            output = await conn.shell(f"aapt dump badging '{apk_path}' 2>/dev/null | grep 'application-label:'")

                            if output and 'application-label:' in output:
                                # Format: application-label:'App Name'
                                match = re.search(r"application-label:'([^']+)'", output)
                                if match:
                                    labels[package] = match.group(1)
                                    aapt_count += 1
                                    continue

                        except:
                            pass

                logger.info(f"[ADBBridge] ✅ AAPT extracted {aapt_count} additional labels")

            logger.info(f"[ADBBridge] Total extracted: {len(labels)} labels ({playstore_count} Play Store, {len(labels) - playstore_count} AAPT)")

        except Exception as e:
            logger.warning(f"[ADBBridge] Label extraction failed: {e}")

        return labels

    def _smart_label_from_package(self, package: str) -> str:
        """
        Generate a smart app label from package name

        Handles common patterns better than just taking the last segment

        Examples:
        - au.com.stan.and → Stan (take company name, not "and")
        - com.netflix.mediaclient → Netflix (take brand, not "mediaclient")
        - com.google.android.gms → Google Play Services (known mapping)
        - com.android.chrome → Chrome
        """
        # Known package mappings for common apps
        known_labels = {
            'com.google.android.gms': 'Google Play Services',
            'com.google.android.gsf': 'Google Services Framework',
            'com.android.vending': 'Google Play Store',
            'com.google.android.gm': 'Gmail',
            'com.google.android.youtube': 'YouTube',
            'com.google.android.apps.maps': 'Google Maps',
            'com.android.chrome': 'Chrome',
            'com.microsoft.teams': 'Microsoft Teams',
            'au.com.stan.and': 'Stan',
            'com.cbs.ca': 'Paramount+',
            'com.netflix.mediaclient': 'Netflix',
            'com.amazon.avod.thirdpartyclient': 'Prime Video',
            'com.hulu.plus': 'Hulu',
            'com.disney.disneyplus': 'Disney+',
            'com.spotify.music': 'Spotify',
            'com.zhiliaoapp.musically': 'TikTok',
            'com.facebook.katana': 'Facebook',
            'com.instagram.android': 'Instagram',
            'com.twitter.android': 'Twitter',
            'com.whatsapp': 'WhatsApp',
        }

        if package in known_labels:
            return known_labels[package]

        # Split package into segments
        segments = package.split('.')

        # For reverse domain notation (com.company.app), try to find the app name
        if len(segments) >= 3:
            # Skip TLD and domain, look for meaningful segments
            # com.google.android.youtube → ['com', 'google', 'android', 'youtube']
            meaningful_segments = segments[2:]  # Skip 'com.google'

            # Filter out common non-label segments
            excluded = {'android', 'app', 'apps', 'client', 'mobile', 'app', 'main', 'launcher'}

            for seg in meaningful_segments:
                if seg and seg.lower() not in excluded and len(seg) > 2:
                    return seg.title()

            # If all segments were excluded, use the company name
            if len(segments) > 1:
                company = segments[1]  # e.g., 'netflix' from 'com.netflix.xxx'
                if company and company.lower() not in {'android', 'google', 'samsung'}:
                    return company.title()

        # Fallback: use last segment
        return segments[-1].title() if segments else package.title()

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
