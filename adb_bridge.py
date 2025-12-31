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
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from utils.adb_manager import ADBManager
from utils.base_connection import BaseADBConnection
from playstore_icon_scraper import PlayStoreIconScraper
from adb_helpers import PersistentADBShell

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
        self._adb_lock = asyncio.Lock()  # Prevent concurrent ADB operations (screenshots, UI dumps)
        self._stream_lock = asyncio.Lock()  # Separate lock for streaming (non-blocking)
        self._device_discovered_callbacks = []  # Callbacks for device auto-import

        # UI Hierarchy Cache (prevents repeated expensive uiautomator dumps)
        self._ui_cache: Dict[str, dict] = {}  # {device_id: {"elements": [...], "timestamp": float, "xml": str}}
        self._ui_cache_ttl_ms: float = 1000  # Default 1 second TTL
        self._ui_cache_enabled: bool = True
        self._ui_cache_hits: int = 0
        self._ui_cache_misses: int = 0

        # Screenshot Cache (prevents repeated captures for rapid consecutive calls)
        self._screenshot_cache: Dict[str, dict] = {}  # {device_id: {"image": bytes, "timestamp": float}}
        self._screenshot_cache_ttl_ms: float = 100  # 100ms TTL for screenshots
        self._screenshot_cache_enabled: bool = True
        self._screenshot_cache_hits: int = 0
        self._screenshot_cache_misses: int = 0

        # Streaming state (isolated from screenshot capture)
        self._stream_active: Dict[str, bool] = {}  # Track active streams per device
        self._stream_frame_count: Dict[str, int] = {}  # Frame counter per device

        # Unlock attempt tracking (prevent device lockout)
        self._unlock_failures: Dict[str, dict] = {}  # {device_id: {"count": int, "last_attempt": float, "locked_out": bool}}
        self._max_unlock_attempts: int = 2  # Max attempts before giving up (most devices lock after 5)
        self._unlock_cooldown_seconds: int = 300  # 5 minute cooldown after failures

        # Stable device identifier cache (survives IP/port changes)
        self._device_serial_cache: Dict[str, str] = {}  # {device_id: serial_number}

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

    # === UI Hierarchy Cache Methods ===

    def set_ui_cache_ttl(self, ttl_ms: float):
        """Set UI hierarchy cache TTL in milliseconds (default: 1000ms)"""
        self._ui_cache_ttl_ms = ttl_ms
        logger.info(f"[ADBBridge] UI cache TTL set to {ttl_ms}ms")

    def set_ui_cache_enabled(self, enabled: bool):
        """Enable or disable UI hierarchy caching"""
        self._ui_cache_enabled = enabled
        logger.info(f"[ADBBridge] UI cache {'enabled' if enabled else 'disabled'}")

    def clear_ui_cache(self, device_id: str = None):
        """Clear UI hierarchy cache for a device or all devices"""
        if device_id:
            if device_id in self._ui_cache:
                del self._ui_cache[device_id]
                logger.debug(f"[ADBBridge] UI cache cleared for {device_id}")
        else:
            self._ui_cache.clear()
            logger.debug("[ADBBridge] UI cache cleared for all devices")

    def get_ui_cache_stats(self) -> dict:
        """Get UI cache statistics"""
        total = self._ui_cache_hits + self._ui_cache_misses
        hit_rate = (self._ui_cache_hits / total * 100) if total > 0 else 0
        return {
            "enabled": self._ui_cache_enabled,
            "ttl_ms": self._ui_cache_ttl_ms,
            "cached_devices": len(self._ui_cache),
            "hits": self._ui_cache_hits,
            "misses": self._ui_cache_misses,
            "hit_rate_percent": round(hit_rate, 1)
        }

    # === Stable Device Identifier Methods ===

    async def get_device_serial(self, device_id: str, force_refresh: bool = False) -> str:
        """
        Get stable device identifier that survives IP/port changes.

        Tries multiple methods with fallbacks:
        1. ADB serial number (adb get-serialno)
        2. Android ID (settings get secure android_id)
        3. Build fingerprint hash (ro.build.fingerprint)
        4. Fallback: hash of model + manufacturer

        Args:
            device_id: Current device ID (IP:port or USB serial)
            force_refresh: If True, bypass cache and fetch fresh

        Returns:
            Stable unique identifier string
        """
        # Check cache first
        if not force_refresh and device_id in self._device_serial_cache:
            return self._device_serial_cache[device_id]

        conn = self.devices.get(device_id)
        if not conn or not conn.available:
            # Return sanitized device_id as fallback
            logger.warning(f"[ADBBridge] Device {device_id} not available, using device_id as identifier")
            return self._sanitize_identifier(device_id)

        serial = None

        # Method 1: Try adb get-serialno
        try:
            result = await asyncio.wait_for(
                conn.execute_command("get-serialno"),
                timeout=3.0
            )
            if result and result.strip() and result.strip() != "unknown":
                serial = result.strip()
                logger.debug(f"[ADBBridge] Got serial via get-serialno: {serial}")
        except Exception as e:
            logger.debug(f"[ADBBridge] get-serialno failed: {e}")

        # Method 2: Try Android ID (most reliable for Android 8+)
        # Hash it for privacy - still unique but not reversible
        if not serial:
            try:
                result = await asyncio.wait_for(
                    conn.shell("settings get secure android_id"),
                    timeout=3.0
                )
                if result and result.strip() and result.strip() != "null":
                    import hashlib
                    # Hash the android_id for privacy
                    serial = hashlib.sha256(result.strip().encode()).hexdigest()[:16]
                    logger.debug(f"[ADBBridge] Got serial via android_id hash: {serial}")
            except Exception as e:
                logger.debug(f"[ADBBridge] android_id failed: {e}")

        # Method 3: Try build fingerprint
        if not serial:
            try:
                result = await asyncio.wait_for(
                    conn.shell("getprop ro.build.fingerprint"),
                    timeout=3.0
                )
                if result and result.strip():
                    # Hash the fingerprint to get a shorter ID
                    import hashlib
                    serial = hashlib.md5(result.strip().encode()).hexdigest()[:16]
                    logger.debug(f"[ADBBridge] Got serial via fingerprint hash: {serial}")
            except Exception as e:
                logger.debug(f"[ADBBridge] fingerprint failed: {e}")

        # Method 4: Fallback - hash of model + manufacturer
        if not serial:
            try:
                model = await asyncio.wait_for(
                    conn.shell("getprop ro.product.model"),
                    timeout=3.0
                )
                manufacturer = await asyncio.wait_for(
                    conn.shell("getprop ro.product.manufacturer"),
                    timeout=3.0
                )
                combo = f"{manufacturer.strip()}_{model.strip()}"
                import hashlib
                serial = hashlib.md5(combo.encode()).hexdigest()[:16]
                logger.debug(f"[ADBBridge] Got serial via model hash: {serial}")
            except Exception as e:
                logger.debug(f"[ADBBridge] model hash failed: {e}")

        # Final fallback: sanitized device_id
        if not serial:
            serial = self._sanitize_identifier(device_id)
            logger.warning(f"[ADBBridge] All serial methods failed, using device_id: {serial}")

        # Cache the result
        self._device_serial_cache[device_id] = serial
        logger.info(f"[ADBBridge] Device {device_id} -> stable ID: {serial}")

        return serial

    def _sanitize_identifier(self, identifier: str) -> str:
        """Sanitize an identifier for use in MQTT topics and unique_ids"""
        import re
        # Replace colons, dots, and other special chars with underscores
        return re.sub(r'[^a-zA-Z0-9]', '_', identifier)

    def get_cached_serial(self, device_id: str) -> Optional[str]:
        """Get cached serial without fetching (returns None if not cached)"""
        return self._device_serial_cache.get(device_id)

    def set_cached_serial(self, device_id: str, serial: str):
        """Manually set cached serial (useful for migration)"""
        self._device_serial_cache[device_id] = serial
        logger.debug(f"[ADBBridge] Manually cached serial for {device_id}: {serial}")

    def _get_cached_ui_elements(self, device_id: str) -> Optional[List[Dict]]:
        """Get cached UI elements if still valid"""
        if not self._ui_cache_enabled:
            return None

        cache_entry = self._ui_cache.get(device_id)
        if not cache_entry:
            return None

        # Check if cache is still valid
        age_ms = (time.time() - cache_entry["timestamp"]) * 1000
        if age_ms > self._ui_cache_ttl_ms:
            logger.debug(f"[ADBBridge] UI cache expired for {device_id} (age: {age_ms:.0f}ms)")
            return None

        self._ui_cache_hits += 1
        logger.debug(f"[ADBBridge] UI cache HIT for {device_id} (age: {age_ms:.0f}ms)")
        return cache_entry["elements"]

    def _set_cached_ui_elements(self, device_id: str, elements: List[Dict], xml_str: str = None):
        """Store UI elements in cache"""
        if not self._ui_cache_enabled:
            return

        self._ui_cache[device_id] = {
            "elements": elements,
            "timestamp": time.time(),
            "xml": xml_str
        }
        self._ui_cache_misses += 1
        logger.debug(f"[ADBBridge] UI cache stored for {device_id} ({len(elements)} elements)")

    # === Screenshot Cache Methods ===

    def set_screenshot_cache_ttl(self, ttl_ms: float):
        """Set screenshot cache TTL in milliseconds (default: 100ms)"""
        self._screenshot_cache_ttl_ms = ttl_ms
        logger.info(f"[ADBBridge] Screenshot cache TTL set to {ttl_ms}ms")

    def set_screenshot_cache_enabled(self, enabled: bool):
        """Enable or disable screenshot caching"""
        self._screenshot_cache_enabled = enabled
        logger.info(f"[ADBBridge] Screenshot cache {'enabled' if enabled else 'disabled'}")

    def get_screenshot_cache_stats(self) -> dict:
        """Get screenshot cache statistics"""
        total = self._screenshot_cache_hits + self._screenshot_cache_misses
        hit_rate = (self._screenshot_cache_hits / total * 100) if total > 0 else 0
        return {
            "enabled": self._screenshot_cache_enabled,
            "ttl_ms": self._screenshot_cache_ttl_ms,
            "cached_devices": len(self._screenshot_cache),
            "hits": self._screenshot_cache_hits,
            "misses": self._screenshot_cache_misses,
            "hit_rate_percent": round(hit_rate, 1)
        }

    def _get_cached_screenshot(self, device_id: str) -> Optional[bytes]:
        """Get cached screenshot if still valid"""
        if not self._screenshot_cache_enabled:
            return None

        cache_entry = self._screenshot_cache.get(device_id)
        if not cache_entry:
            return None

        age_ms = (time.time() - cache_entry["timestamp"]) * 1000
        if age_ms > self._screenshot_cache_ttl_ms:
            return None

        self._screenshot_cache_hits += 1
        logger.debug(f"[ADBBridge] Screenshot cache HIT for {device_id} (age: {age_ms:.0f}ms)")
        return cache_entry["image"]

    def _set_cached_screenshot(self, device_id: str, image: bytes):
        """Store screenshot in cache"""
        if not self._screenshot_cache_enabled:
            return

        self._screenshot_cache[device_id] = {
            "image": image,
            "timestamp": time.time()
        }
        self._screenshot_cache_misses += 1

    # === Streaming Methods (Isolated from Screenshot Capture) ===

    async def capture_stream_frame(self, device_id: str, timeout: float = 2.0) -> bytes:
        """
        Capture a frame for streaming - optimized for throughput.

        This method is isolated from capture_screenshot to prevent streaming
        from blocking single screenshot captures. Uses a separate lock.

        Args:
            device_id: Device identifier
            timeout: Max capture time (shorter for streaming)

        Returns:
            PNG image bytes (empty on failure)
        """
        conn = self.devices.get(device_id)
        if not conn:
            return b""

        # Use separate streaming lock - non-blocking with screenshots
        async with self._stream_lock:
            start_time = time.time()

            try:
                import subprocess

                def _run_screencap():
                    result = subprocess.run(
                        ["adb", "-s", device_id, "exec-out", "screencap", "-p"],
                        capture_output=True,
                        timeout=timeout
                    )
                    return result.stdout if result.returncode == 0 else b""

                result = await asyncio.to_thread(_run_screencap)
                elapsed = (time.time() - start_time) * 1000

                if result and len(result) > 1000:
                    # Update stream stats
                    self._stream_frame_count[device_id] = self._stream_frame_count.get(device_id, 0) + 1
                    return result

                return b""

            except subprocess.TimeoutExpired:
                logger.debug(f"[ADBBridge] Stream frame timeout for {device_id}")
                return b""
            except Exception as e:
                logger.debug(f"[ADBBridge] Stream frame error: {e}")
                return b""

    def start_stream(self, device_id: str):
        """Mark streaming as active for a device"""
        self._stream_active[device_id] = True
        self._stream_frame_count[device_id] = 0
        logger.info(f"[ADBBridge] Stream started for {device_id}")

    def stop_stream(self, device_id: str):
        """Mark streaming as stopped for a device"""
        self._stream_active[device_id] = False
        frames = self._stream_frame_count.get(device_id, 0)
        logger.info(f"[ADBBridge] Stream stopped for {device_id} ({frames} frames)")

    def is_streaming(self, device_id: str) -> bool:
        """Check if streaming is active for a device"""
        return self._stream_active.get(device_id, False)

    def get_stream_stats(self, device_id: str = None) -> dict:
        """Get streaming statistics"""
        if device_id:
            return {
                "device_id": device_id,
                "active": self._stream_active.get(device_id, False),
                "frame_count": self._stream_frame_count.get(device_id, 0)
            }
        else:
            return {
                "active_streams": sum(1 for v in self._stream_active.values() if v),
                "devices": {
                    d: {"active": a, "frames": self._stream_frame_count.get(d, 0)}
                    for d, a in self._stream_active.items()
                }
            }

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

    async def scan_network_for_devices(self, network_range: str = None) -> List[Dict]:
        """
        Scan local network for Android devices with ADB ports open.

        This performs intelligent network scanning to find devices and detect
        their Android version to recommend the optimal connection method.

        Args:
            network_range: Network to scan (e.g., "192.168.1.0/24")
                          If None, will scan the local subnet automatically

        Returns:
            List of discovered device dicts with:
            - ip: Device IP address
            - port: Detected ADB port (5555 for legacy, or custom)
            - android_version: Android version number (e.g., 11, 13)
            - sdk_version: Android SDK version (e.g., 30, 33)
            - model: Device model name
            - recommended_method: "pairing" (Android 11+) or "tcp" (older)
            - state: "available" or "connected"
        """
        async with self._adb_lock:
            try:
                import subprocess
                import socket

                logger.info(f"[ADBBridge] Starting network scan for Android devices...")

                discovered_devices = []

                # STEP 1: Find devices already connected via ADB
                # This is fastest and most reliable for already-paired devices
                logger.debug("[ADBBridge] Checking for ADB-connected devices...")
                def _run_adb_devices():
                    result = subprocess.run(
                        ["adb", "devices", "-l"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    return result.returncode == 0, result.stdout

                try:
                    success, output = await asyncio.to_thread(_run_adb_devices)
                    if success:
                        for line in output.split('\n')[1:]:
                            line = line.strip()
                            if not line or '\t' not in line:
                                continue

                            parts = line.split()
                            if len(parts) < 2:
                                continue

                            device_id = parts[0]
                            state = parts[1]

                            # Only process network devices (IP:port format)
                            if ':' not in device_id:
                                continue

                            # Extract IP and port
                            ip, port_str = device_id.rsplit(':', 1)
                            port = int(port_str)

                            # Extract model if available
                            model = "Unknown"
                            for part in parts[2:]:
                                if part.startswith("model:"):
                                    model = part.split(":")[1].replace("_", " ")
                                    break

                            # Get Android version for this device
                            android_version = None
                            sdk_version = None
                            recommended_method = "tcp"  # Default fallback

                            if state == "device":
                                try:
                                    # Device is already connected, we can query it directly
                                    conn = self.devices.get(device_id)
                                    if not conn:
                                        # Create temporary connection to query version
                                        conn = await self.manager.get_connection(ip, port)
                                        await conn.connect()

                                    # Get Android version
                                    version_output = await conn.shell("getprop ro.build.version.release")
                                    sdk_output = await conn.shell("getprop ro.build.version.sdk")

                                    android_version = version_output.strip() if version_output else None
                                    sdk_version = int(sdk_output.strip()) if sdk_output and sdk_output.strip().isdigit() else None

                                    # Determine recommended method based on SDK version
                                    # Android 11 = SDK 30+
                                    if sdk_version and sdk_version >= 30:
                                        recommended_method = "pairing"
                                    else:
                                        recommended_method = "tcp"

                                    # Clean up temporary connection
                                    if device_id not in self.devices:
                                        await conn.close()

                                except Exception as e:
                                    logger.debug(f"[ADBBridge] Could not get version for {device_id}: {e}")

                            discovered_devices.append({
                                "ip": ip,
                                "port": port,
                                "android_version": android_version,
                                "sdk_version": sdk_version,
                                "model": model,
                                "recommended_method": recommended_method,
                                "state": "connected" if state == "device" else "available",
                                "device_id": device_id
                            })

                            logger.info(f"[ADBBridge] Found ADB device: {ip}:{port} (Android {android_version}, SDK {sdk_version}) -> {recommended_method}")

                except Exception as e:
                    logger.warning(f"[ADBBridge] ADB devices check failed: {e}")

                # STEP 2: Scan local network for port 5555 (legacy ADB)
                # This finds devices that haven't been connected yet
                if network_range is None:
                    # Auto-detect local network
                    try:
                        # Get local IP address
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.connect(("8.8.8.8", 80))
                        local_ip = s.getsockname()[0]
                        s.close()

                        # Calculate network range (assume /24)
                        ip_parts = local_ip.split('.')
                        network_range = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
                        logger.info(f"[ADBBridge] Auto-detected network range: {network_range}")
                    except Exception as e:
                        logger.warning(f"[ADBBridge] Could not auto-detect network range: {e}")
                        # Return only ADB-connected devices if network scan fails
                        return discovered_devices

                # Parse network range (basic /24 support)
                if network_range and network_range.endswith('/24'):
                    base_ip = network_range.replace('/24', '')
                    ip_parts = base_ip.split('.')

                    logger.debug(f"[ADBBridge] Scanning network {network_range} for port 5555...")

                    # Scan common IP range (limit to avoid timeout)
                    # Only scan .1-.254 range
                    async def check_port(ip: str, port: int = 5555, timeout: float = 0.5) -> bool:
                        """Quick check if port is open"""
                        try:
                            def _check():
                                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                sock.settimeout(timeout)
                                result = sock.connect_ex((ip, port))
                                sock.close()
                                return result == 0

                            return await asyncio.to_thread(_check)
                        except Exception:
                            return False

                    # Quick parallel scan of subnet (limit concurrent connections)
                    scan_tasks = []
                    for i in range(1, 255):
                        ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.{i}"

                        # Skip if already found via ADB
                        if any(d['ip'] == ip for d in discovered_devices):
                            continue

                        scan_tasks.append(check_port(ip, 5555, timeout=0.3))

                    # Run scans in batches to avoid overwhelming the network
                    batch_size = 50
                    for i in range(0, len(scan_tasks), batch_size):
                        batch = scan_tasks[i:i+batch_size]
                        results = await asyncio.gather(*batch)

                        # Process results
                        for idx, is_open in enumerate(results):
                            if is_open:
                                ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.{i + idx + 1}"
                                logger.info(f"[ADBBridge] Found open ADB port: {ip}:5555")

                                # Try to connect and get version
                                android_version = None
                                sdk_version = None
                                model = "Unknown"
                                recommended_method = "tcp"

                                try:
                                    # Quick connection to get device info
                                    conn = await self.manager.get_connection(ip, 5555)
                                    if await conn.connect():
                                        # Get version info
                                        version_output = await asyncio.wait_for(
                                            conn.shell("getprop ro.build.version.release"),
                                            timeout=2.0
                                        )
                                        sdk_output = await asyncio.wait_for(
                                            conn.shell("getprop ro.build.version.sdk"),
                                            timeout=2.0
                                        )
                                        model_output = await asyncio.wait_for(
                                            conn.shell("getprop ro.product.model"),
                                            timeout=2.0
                                        )

                                        android_version = version_output.strip() if version_output else None
                                        sdk_version = int(sdk_output.strip()) if sdk_output and sdk_output.strip().isdigit() else None
                                        model = model_output.strip() if model_output else "Unknown"

                                        # Determine recommended method
                                        if sdk_version and sdk_version >= 30:
                                            recommended_method = "pairing"
                                        else:
                                            recommended_method = "tcp"

                                        await conn.close()

                                        discovered_devices.append({
                                            "ip": ip,
                                            "port": 5555,
                                            "android_version": android_version,
                                            "sdk_version": sdk_version,
                                            "model": model,
                                            "recommended_method": recommended_method,
                                            "state": "available",
                                            "device_id": f"{ip}:5555"
                                        })

                                        logger.info(f"[ADBBridge] Discovered device: {ip}:5555 (Android {android_version}, SDK {sdk_version}) -> {recommended_method}")

                                except Exception as e:
                                    logger.debug(f"[ADBBridge] Could not get info for {ip}:5555: {e}")
                                    # Add device anyway, just without version info
                                    discovered_devices.append({
                                        "ip": ip,
                                        "port": 5555,
                                        "android_version": None,
                                        "sdk_version": None,
                                        "model": "Unknown",
                                        "recommended_method": "tcp",
                                        "state": "available",
                                        "device_id": f"{ip}:5555"
                                    })

                logger.info(f"[ADBBridge] Network scan complete: Found {len(discovered_devices)} devices")
                return discovered_devices

            except Exception as e:
                logger.error(f"[ADBBridge] Network scan failed: {e}")
                return []

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

    async def capture_screenshot(
        self,
        device_id: str,
        timeout: float = 5.0,
        force_refresh: bool = False,
        format: str = "png"
    ) -> bytes:
        """
        Capture screenshot from device with caching for rapid consecutive calls.

        Args:
            device_id: Device identifier
            timeout: Max time for capture in seconds (default 5s for streaming)
            force_refresh: If True, bypass cache and capture fresh screenshot
            format: Screenshot format - "png" (default, compressed) or "raw" (uncompressed, 10-20% faster)

        Returns:
            Screenshot image bytes (PNG or raw RGBA depending on format)

        Raises:
            ValueError: If device not connected or invalid format

        Performance:
            - PNG format: Compressed, smaller network transfer, slower (default)
            - Raw format: Uncompressed RGBA, 10-20% faster capture, larger data
        """
        if format not in ("png", "raw"):
            raise ValueError(f"Invalid format: {format}. Must be 'png' or 'raw'.")
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        # Check cache first (unless force_refresh)
        # Note: Cache key includes format to avoid mixing PNG/raw cached data
        cache_key = f"{device_id}_{format}"
        if not force_refresh:
            cached = self._get_cached_screenshot(cache_key)
            if cached is not None:
                return cached

        # Use lock to prevent concurrent ADB operations
        async with self._adb_lock:
            start_time = time.time()

            # Determine screencap command based on format
            if format == "png":
                screencap_cmd = ["screencap", "-p"]  # PNG format (compressed)
                shell_cmd = "screencap -p"
                min_size = 1000  # Valid PNG should be > 1KB
            else:  # raw
                screencap_cmd = ["screencap"]  # Raw RGBA format (no compression, 10-20% faster)
                shell_cmd = "screencap"
                min_size = 10000  # Raw should be much larger (width * height * 4 bytes)

            try:
                # Try using subprocess with exec-out for more reliable binary data transfer
                import subprocess

                def _run_screencap():
                    result = subprocess.run(
                        ["adb", "-s", device_id, "exec-out"] + screencap_cmd,
                        capture_output=True,
                        timeout=timeout  # Use provided timeout instead of 60s
                    )
                    return result.stdout if result.returncode == 0 else b""

                result = await asyncio.to_thread(_run_screencap)
                elapsed = (time.time() - start_time) * 1000

                if result and len(result) > min_size:  # Valid screenshot
                    logger.debug(f"[ADBBridge] Screenshot captured ({format}): {len(result)} bytes in {elapsed:.0f}ms")
                    # Store in cache
                    self._set_cached_screenshot(cache_key, result)
                    return result

                # Fallback to shell method if exec-out fails (only if we have time)
                if elapsed < (timeout * 1000 - 500):  # At least 500ms remaining
                    logger.debug(f"[ADBBridge] exec-out failed, trying shell method ({format})")
                    result = await conn.shell(shell_cmd)

                    # Result should be bytes for binary data
                    if isinstance(result, str):
                        result = result.encode('latin1')

                    logger.debug(f"[ADBBridge] Screenshot via shell ({format}): {len(result)} bytes")
                    # Store in cache
                    if result and len(result) > min_size:
                        self._set_cached_screenshot(cache_key, result)
                    return result
                else:
                    logger.warning(f"[ADBBridge] exec-out failed, no time for fallback ({format})")
                    return b""

            except subprocess.TimeoutExpired:
                elapsed = (time.time() - start_time) * 1000
                logger.warning(f"[ADBBridge] Screenshot timeout after {elapsed:.0f}ms ({format})")
                return b""
            except Exception as e:
                logger.error(f"[ADBBridge] Screenshot failed ({format}): {e}")
                raise

    async def get_ui_elements(self, device_id: str, force_refresh: bool = False, bounds_only: bool = False) -> List[Dict]:
        """
        Extract UI element hierarchy using uiautomator.

        Args:
            device_id: Device identifier
            force_refresh: If True, bypass cache and fetch fresh data
            bounds_only: If True, parse only text, resource_id, class, and bounds
                        (30-40% faster - use for sensor extraction)

        Returns:
            List of element dicts with text, bounds, resource_id, etc.

        Raises:
            ValueError: If device not connected
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        # Check cache first (unless force_refresh)
        if not force_refresh:
            cached = self._get_cached_ui_elements(device_id)
            if cached is not None:
                return cached

        # Use lock to prevent concurrent ADB operations
        async with self._adb_lock:
            try:
                mode = "bounds-only (fast)" if bounds_only else "full"
                logger.debug(f"[ADBBridge] Extracting UI elements from {device_id} (cache miss, mode={mode})")

                # Clean up old dump file first to avoid stale data
                await conn.shell("rm -f /sdcard/window_dump.xml")

                # Dump UI hierarchy to file then read it (more reliable than /dev/tty)
                # Some devices don't output XML to /dev/tty properly
                # Added retry logic for flaky uiautomator
                max_retries = 2
                dump_output = None

                for attempt in range(max_retries):
                    try:
                        dump_output = await conn.shell("uiautomator dump && cat /sdcard/window_dump.xml")

                        # Check if we got valid output
                        if dump_output and '<?xml' in dump_output:
                            break
                        else:
                            logger.warning(f"[ADBBridge] UI dump attempt {attempt + 1}/{max_retries} failed: no XML in output")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(0.5)  # Brief delay before retry
                    except Exception as e:
                        logger.warning(f"[ADBBridge] UI dump attempt {attempt + 1}/{max_retries} failed: {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(0.5)  # Brief delay before retry
                        else:
                            raise

                if not dump_output:
                    raise ValueError("Failed to get UI dump after retries")

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
                    if bounds_only:
                        # Minimal parsing for sensor extraction (30-40% faster)
                        element = {
                            'text': node.get('text', ''),
                            'resource_id': node.get('resource-id', ''),
                            'class': node.get('class', ''),
                            'bounds': self._parse_bounds(node.get('bounds', '')),
                        }
                    else:
                        # Full parsing for UI interaction
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

                # Store in cache
                self._set_cached_ui_elements(device_id, elements, xml_str)

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

        # Use lock to prevent concurrent ADB operations
        async with self._adb_lock:
            try:
                # Clean up old dump file first
                await conn.shell("rm -f /sdcard/window_dump.xml")

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

        # Invalidate UI cache - screen state has changed
        self.clear_ui_cache(device_id)

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

        # Invalidate UI cache - screen state has changed
        self.clear_ui_cache(device_id)

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

    # ========== Screen Power Control (Headless Mode) ==========

    async def is_screen_on(self, device_id: str) -> bool:
        """
        Check if the device screen is currently on.

        Args:
            device_id: Device identifier

        Returns:
            True if screen is on, False if off/locked or device not connected
        """
        conn = self.devices.get(device_id)
        if not conn:
            logger.debug(f"[ADBBridge] Device {device_id} not in devices dict for is_screen_on check")
            return False  # Don't raise - return False so wake logic can try to proceed

        try:
            # Don't use grep - it may not be available on all Android devices
            # Parse the full dumpsys power output in Python
            result = await conn.shell("dumpsys power")

            # Check for various indicators that screen is on
            # Different Android versions use different output formats
            screen_on_indicators = [
                "mWakefulness=Awake",  # Android 4.4+
                "Display Power: state=ON",  # Common format
                "state=ON",  # Simplified check
                "mScreenOn=true",  # Older Android versions
            ]

            for indicator in screen_on_indicators:
                if indicator in result:
                    logger.debug(f"[ADBBridge] Screen is ON (detected: {indicator})")
                    return True

            logger.debug(f"[ADBBridge] Screen appears to be OFF")
            return False
        except Exception as e:
            logger.warning(f"[ADBBridge] Failed to check screen state: {e}")
            return False

    async def wake_screen(self, device_id: str) -> bool:
        """
        Wake the device screen.

        Args:
            device_id: Device identifier

        Returns:
            True if wake command sent successfully, False if device not connected or command failed
        """
        conn = self.devices.get(device_id)
        if not conn:
            logger.warning(f"[ADBBridge] Cannot wake screen - device {device_id} not in devices dict")
            return False  # Don't raise - just return False

        try:
            logger.info(f"[ADBBridge] Waking screen on {device_id}")
            await conn.shell("input keyevent 224")  # KEYCODE_WAKEUP
            return True
        except Exception as e:
            logger.error(f"[ADBBridge] Failed to wake screen: {e}")
            return False

    async def sleep_screen(self, device_id: str) -> bool:
        """
        Put the device screen to sleep.

        Args:
            device_id: Device identifier

        Returns:
            True if sleep command sent successfully, False if device not connected or command failed
        """
        conn = self.devices.get(device_id)
        if not conn:
            logger.warning(f"[ADBBridge] Cannot sleep screen - device {device_id} not in devices dict")
            return False  # Don't raise - just return False

        try:
            logger.info(f"[ADBBridge] Sleeping screen on {device_id}")
            await conn.shell("input keyevent 223")  # KEYCODE_SLEEP
            return True
        except Exception as e:
            logger.error(f"[ADBBridge] Failed to sleep screen: {e}")
            return False

    async def ensure_screen_on(self, device_id: str, timeout_ms: int = 3000) -> bool:
        """
        Ensure the device screen is on, waking it if necessary.

        Args:
            device_id: Device identifier
            timeout_ms: Maximum time to wait for screen to wake (default 3000ms)

        Returns:
            True if screen is on (or was successfully woken), False on timeout
        """
        # Check if already on
        if await self.is_screen_on(device_id):
            logger.debug(f"[ADBBridge] Screen already on for {device_id}")
            return True

        # Try to wake
        await self.wake_screen(device_id)

        # Wait and verify (check every 100ms)
        attempts = timeout_ms // 100
        for i in range(attempts):
            await asyncio.sleep(0.1)
            if await self.is_screen_on(device_id):
                logger.info(f"[ADBBridge] Screen woke after {(i + 1) * 100}ms")
                return True

        logger.warning(f"[ADBBridge] Screen failed to wake after {timeout_ms}ms")
        return False

    async def unlock_screen(self, device_id: str) -> bool:
        """
        Attempt to unlock the screen (works for swipe-to-unlock, not PIN/pattern).

        Uses wm dismiss-keyguard (Android 8+) for maximum reliability.

        Args:
            device_id: Device identifier

        Returns:
            True if unlock command sent successfully
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        try:
            logger.info(f"[ADBBridge] Unlocking screen on {device_id}")

            # Method 1: wm dismiss-keyguard (most reliable on Android 8+)
            try:
                await conn.shell("wm dismiss-keyguard")
                await asyncio.sleep(0.3)
                # Check if unlocked
                if not await self.is_locked(device_id):
                    logger.info(f"[ADBBridge] Screen unlocked via wm dismiss-keyguard")
                    return True
            except Exception as e:
                logger.debug(f"[ADBBridge] wm dismiss-keyguard failed: {e}")

            # Method 2: MENU key (often dismisses lock screen on swipe-to-unlock)
            await conn.shell("input keyevent 82")  # KEYCODE_MENU
            await asyncio.sleep(0.3)

            # Method 3: Swipe up (fallback for older devices)
            try:
                wm_output = await conn.shell("wm size")
                match = re.search(r'(\d+)x(\d+)', wm_output)
                if match:
                    width, height = int(match.group(1)), int(match.group(2))
                else:
                    width, height = 1080, 1920
                center_x = width // 2
                await conn.shell(f"input swipe {center_x} {int(height * 0.8)} {center_x} {int(height * 0.3)} 300")
            except:
                # Fallback with hardcoded coordinates
                await conn.shell("input swipe 540 1800 540 800 300")

            return True
        except Exception as e:
            logger.error(f"[ADBBridge] Failed to unlock screen: {e}")
            return False

    def get_unlock_status(self, device_id: str) -> dict:
        """
        Get unlock attempt status for a device.

        Returns:
            Dict with failure_count, in_cooldown, cooldown_remaining_seconds, locked_out
        """
        failure_info = self._unlock_failures.get(device_id, {"count": 0, "last_attempt": 0, "locked_out": False})

        # Check if cooldown has expired
        time_since_failure = time.time() - failure_info.get("last_attempt", 0)
        in_cooldown = failure_info.get("count", 0) >= self._max_unlock_attempts and time_since_failure < self._unlock_cooldown_seconds
        cooldown_remaining = max(0, self._unlock_cooldown_seconds - time_since_failure) if in_cooldown else 0

        return {
            "failure_count": failure_info.get("count", 0),
            "in_cooldown": in_cooldown,
            "cooldown_remaining_seconds": int(cooldown_remaining),
            "locked_out": failure_info.get("locked_out", False),
            "max_attempts": self._max_unlock_attempts
        }

    def reset_unlock_failures(self, device_id: str):
        """Reset unlock failure count for a device (call after successful manual unlock)."""
        if device_id in self._unlock_failures:
            del self._unlock_failures[device_id]
            logger.info(f"[ADBBridge] Reset unlock failures for {device_id}")

    async def _get_pin_entry_count(self, device_id: str) -> int:
        """
        Get the number of PIN digits currently entered by checking UI elements.

        Looks for PIN entry indicators like dots/bullets in the lock screen UI.

        Returns:
            Number of digits detected, or -1 if cannot determine
        """
        conn = self.devices.get(device_id)
        if not conn:
            return -1

        try:
            # Get UI hierarchy and look for PIN entry field
            elements = await self.get_ui_elements(device_id)
            if isinstance(elements, dict):
                elements = elements.get('elements', [])

            for elem in elements:
                elem_class = elem.get('class', '')
                text = elem.get('text', '')
                content_desc = elem.get('content_desc', '')

                # Look for PIN entry indicators
                # Many lock screens use PasswordTextView or similar with dots
                if 'Password' in elem_class or 'Pin' in elem_class or 'Keyguard' in elem_class:
                    # Count dots or bullets in text (common PIN masking)
                    if text:
                        # Count bullet characters (•, *, etc.)
                        dot_count = text.count('•') + text.count('●') + text.count('*') + text.count('○')
                        if dot_count > 0:
                            logger.debug(f"[ADBBridge] Found PIN indicator with {dot_count} dots in '{elem_class}'")
                            return dot_count

                # Also check for "X digits entered" type content descriptions
                if content_desc:
                    import re
                    match = re.search(r'(\d+)\s*(digit|character|number)', content_desc.lower())
                    if match:
                        count = int(match.group(1))
                        logger.debug(f"[ADBBridge] Found PIN count {count} in content_desc: '{content_desc}'")
                        return count

            # Fallback: Look for any element with multiple dots
            for elem in elements:
                text = elem.get('text', '')
                if text and len(text) <= 10:  # PIN is usually 4-10 digits
                    # Count any character that could be a masked digit
                    masked_chars = sum(1 for c in text if c in '•●*○◉◎')
                    if masked_chars >= 4:  # At least 4 masked chars = likely PIN field
                        logger.debug(f"[ADBBridge] Found {masked_chars} masked characters in text")
                        return masked_chars

            logger.debug(f"[ADBBridge] Could not detect PIN entry count from UI")
            return -1

        except Exception as e:
            logger.debug(f"[ADBBridge] Error getting PIN count: {e}")
            return -1

    async def _wait_for_pin_entry_screen(self, device_id: str, timeout: float = 3.0) -> bool:
        """
        Wait for PIN entry screen to be ready by checking for PIN-related UI elements.

        Returns:
            True if PIN entry screen detected, False if timeout
        """
        conn = self.devices.get(device_id)
        if not conn:
            return False

        start_time = time.time()
        while (time.time() - start_time) < timeout:
            try:
                # Check for PIN entry indicators in the focused window
                result = await conn.shell("dumpsys window | grep -E 'mCurrentFocus|isKeyguardLocked'")

                # Look for keyguard-related windows indicating PIN entry is ready
                if "Keyguard" in result or "KeyguardBouncer" in result or "KeyguardSimPin" in result:
                    logger.debug(f"[ADBBridge] PIN entry screen detected")
                    return True

                # Also check if there's a focused input field
                if "StatusBar" not in result and "Launcher" not in result:
                    # Not on home screen or status bar - likely PIN entry
                    logger.debug(f"[ADBBridge] Focused window suggests PIN entry ready")
                    return True

            except Exception as e:
                logger.debug(f"[ADBBridge] Error checking PIN screen: {e}")

            await asyncio.sleep(0.3)

        logger.warning(f"[ADBBridge] Timeout waiting for PIN entry screen")
        return False

    async def unlock_device(self, device_id: str, passcode: str) -> bool:
        """
        Unlock device with passcode/PIN using universal Android methods.

        Features:
        - Lockout protection: Max 2 attempts to prevent device lockout
        - Cooldown period: 5 minutes after max failures
        - PIN screen detection: Waits for PIN entry to be ready
        - Detailed logging for debugging

        Args:
            device_id: Device identifier
            passcode: Numeric passcode or PIN

        Returns:
            True if unlock successful, False otherwise

        Note:
            Check get_unlock_status() if unlock fails to see if device is in cooldown.
        """
        conn = self.devices.get(device_id)
        if not conn:
            logger.warning(f"[ADBBridge] Cannot unlock - device {device_id} not in devices dict")
            return False

        # Check cooldown status
        status = self.get_unlock_status(device_id)
        if status["in_cooldown"]:
            logger.warning(f"[ADBBridge] Device {device_id} is in unlock cooldown ({status['cooldown_remaining_seconds']}s remaining). "
                          f"Manual unlock required to prevent lockout.")
            return False

        if status["locked_out"]:
            logger.error(f"[ADBBridge] Device {device_id} marked as locked out. Manual intervention required.")
            return False

        try:
            logger.info(f"[ADBBridge] Unlocking device {device_id} (attempt {status['failure_count'] + 1}/{self._max_unlock_attempts})")

            # Step 1: Wake screen
            logger.info(f"[ADBBridge] Step 1: Waking screen...")
            await conn.shell("input keyevent 224")  # KEYCODE_WAKEUP
            await asyncio.sleep(0.5)

            # Check if already unlocked (screen was just off)
            if not await self.is_locked(device_id):
                logger.info(f"[ADBBridge] Device already unlocked (screen was just off)")
                self.reset_unlock_failures(device_id)
                return True

            # Step 2: Dismiss keyguard to reveal PIN entry
            logger.info(f"[ADBBridge] Step 2: Dismissing keyguard...")
            await conn.shell("input keyevent 82")   # KEYCODE_MENU
            await asyncio.sleep(0.3)

            try:
                await conn.shell("wm dismiss-keyguard")
            except Exception as e:
                logger.debug(f"[ADBBridge] wm dismiss-keyguard failed: {e}")
                # Fallback: swipe up
                try:
                    wm_output = await conn.shell("wm size")
                    match = re.search(r'(\d+)x(\d+)', wm_output)
                    if match:
                        width, height = int(match.group(1)), int(match.group(2))
                    else:
                        width, height = 1080, 1920
                    center_x = width // 2
                    await conn.shell(f"input swipe {center_x} {int(height * 0.8)} {center_x} {int(height * 0.3)} 300")
                except:
                    pass

            await asyncio.sleep(0.5)

            # Step 3: Check if unlock happened without PIN (swipe-only lock)
            if not await self.is_locked(device_id):
                logger.info(f"[ADBBridge] Device unlocked (swipe-only lock)")
                self.reset_unlock_failures(device_id)
                return True

            # Step 4: Wait for PIN entry screen to be ready
            logger.info(f"[ADBBridge] Step 3: Waiting for PIN entry screen...")
            pin_ready = await self._wait_for_pin_entry_screen(device_id, timeout=2.0)
            if not pin_ready:
                logger.warning(f"[ADBBridge] PIN entry screen not detected - trying anyway")

            # Extra wait to ensure PIN field is focused
            await asyncio.sleep(0.3)

            # Step 5: Clear any existing PIN input first
            logger.info(f"[ADBBridge] Step 4: Clearing any existing PIN input...")
            for _ in range(10):  # Clear up to 10 digits
                await conn.shell("input keyevent 67")  # KEYCODE_DEL
                await asyncio.sleep(0.03)
            await asyncio.sleep(0.2)

            # Step 6: Enter PIN using key events (more discrete than input text)
            # Key codes: 0-9 map to KEYCODE_0 (7) through KEYCODE_9 (16)
            expected_digits = len(passcode)
            max_retries = 2

            for attempt in range(max_retries):
                logger.info(f"[ADBBridge] Step 5: Entering PIN ({expected_digits} digits, attempt {attempt + 1}/{max_retries})...")

                # Enter each digit
                entered_count = 0
                for digit in passcode:
                    if digit.isdigit():
                        keycode = 7 + int(digit)  # KEYCODE_0=7, KEYCODE_1=8, etc.
                        await conn.shell(f"input keyevent {keycode}")
                        entered_count += 1
                        await asyncio.sleep(0.12)  # Slightly longer delay for reliability

                await asyncio.sleep(0.3)

                # Check PIN entry count by looking at UI
                try:
                    actual_count = await self._get_pin_entry_count(device_id)
                    logger.info(f"[ADBBridge] PIN entry check: expected {expected_digits}, detected {actual_count}")

                    if actual_count == expected_digits:
                        # Correct count, proceed to confirm
                        break
                    elif actual_count > expected_digits:
                        # Too many digits - clear and retry
                        logger.warning(f"[ADBBridge] Too many digits entered ({actual_count}), clearing and retrying...")
                        for _ in range(actual_count + 2):
                            await conn.shell("input keyevent 67")  # KEYCODE_DEL
                            await asyncio.sleep(0.03)
                        await asyncio.sleep(0.2)
                        continue
                    else:
                        # Too few or couldn't detect - try anyway
                        logger.warning(f"[ADBBridge] Fewer digits detected ({actual_count}), proceeding anyway...")
                        break
                except Exception as e:
                    logger.debug(f"[ADBBridge] Could not verify PIN count: {e}, proceeding anyway")
                    break

            await asyncio.sleep(0.2)

            # Step 7: Confirm PIN
            logger.info(f"[ADBBridge] Step 6: Confirming PIN...")
            await conn.shell("input keyevent 66")  # KEYCODE_ENTER
            await asyncio.sleep(1.0)  # Wait for unlock animation

            # Step 7: Verify unlock
            still_locked = await self.is_locked(device_id)
            if still_locked:
                # Record failure
                failure_info = self._unlock_failures.get(device_id, {"count": 0, "last_attempt": 0, "locked_out": False})
                failure_info["count"] = failure_info.get("count", 0) + 1
                failure_info["last_attempt"] = time.time()
                self._unlock_failures[device_id] = failure_info

                remaining = self._max_unlock_attempts - failure_info["count"]
                if remaining <= 0:
                    logger.error(f"[ADBBridge] UNLOCK FAILED for {device_id} - Max attempts reached! "
                                f"Entering {self._unlock_cooldown_seconds}s cooldown to prevent device lockout. "
                                f"Please unlock device manually and call reset_unlock_failures().")
                else:
                    logger.warning(f"[ADBBridge] Unlock failed for {device_id} - {remaining} attempts remaining before cooldown")

                return False

            # Success - reset failure count
            logger.info(f"[ADBBridge] Device {device_id} unlocked successfully")
            self.reset_unlock_failures(device_id)
            return True

        except Exception as e:
            logger.error(f"[ADBBridge] Failed to unlock device: {e}")
            return False

    async def is_locked(self, device_id: str) -> bool:
        """
        Check if device screen is locked (showing lock screen).

        Returns:
            True if device is locked, False if unlocked
        """
        conn = self.devices.get(device_id)
        if not conn:
            logger.warning(f"[ADBBridge] Device {device_id} not connected for lock check")
            return False  # Can't check - assume unlocked

        try:
            # Get full window dump and check for lock indicators
            result = await conn.shell("dumpsys window")

            if not result:
                logger.warning(f"[ADBBridge] Empty window dump for {device_id}")
                return False

            # Check for lock screen indicators
            if "mShowingLockscreen=true" in result:
                logger.info(f"[ADBBridge] Device {device_id} is LOCKED (mShowingLockscreen=true)")
                return True
            if "mDreamingLockscreen=true" in result:
                logger.info(f"[ADBBridge] Device {device_id} is LOCKED (mDreamingLockscreen=true)")
                return True

            # Explicitly check for unlocked state
            if "mShowingLockscreen=false" in result or "mDreamingLockscreen=false" in result:
                logger.info(f"[ADBBridge] Device {device_id} is UNLOCKED")
                return False

            # Cannot determine - assume LOCKED to be safe (prevents false success)
            logger.warning(f"[ADBBridge] Cannot determine lock status for {device_id}, assuming LOCKED for safety")
            return True

        except Exception as e:
            logger.error(f"[ADBBridge] Error checking lock status for {device_id}: {e}")
            return False

    async def execute_batch_commands(self, device_id: str, commands: List[str]) -> List[tuple]:
        """
        Execute multiple shell commands in a single persistent session.

        This is 50-70% faster than individual command execution due to:
        - Single shell session reuse
        - Reduced connection overhead
        - Pipelined command execution

        Args:
            device_id: Device identifier
            commands: List of shell commands to execute

        Returns:
            List of (success: bool, output: str) tuples

        Example:
            results = await adb_bridge.execute_batch_commands(device_id, [
                "getprop ro.build.version.release",
                "dumpsys activity activities | grep mCurrentFocus",
                "input keyevent KEYCODE_HOME"
            ])
        """
        if not self.devices.get(device_id):
            raise ValueError(f"Device not connected: {device_id}")

        logger.debug(f"[ADBBridge] Executing batch of {len(commands)} commands on {device_id}")

        async with PersistentADBShell(device_id) as shell:
            results = await shell.execute_batch(commands)

        return results

    async def get_current_activity(self, device_id: str, as_dict: bool = False) -> str | Dict:
        """
        Get the current focused activity/window on the device.

        Args:
            device_id: Device identifier
            as_dict: If True, return dict with package, activity, full_name

        Returns:
            String: Current activity name (e.g., "com.android.launcher3/.Launcher")
            Dict (if as_dict=True): {package, activity, full_name}

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

                if as_dict:
                    return self._parse_activity_string(activity)
                return activity
            else:
                # Fallback: try to parse just the activity name
                if "mCurrentFocus=" in output:
                    # Extract anything that looks like package/activity
                    match = re.search(r'([a-zA-Z0-9_.]+/[a-zA-Z0-9_.]+)', output)
                    if match:
                        activity = match.group(1)
                        logger.debug(f"[ADBBridge] Current activity (fallback): {activity}")
                        if as_dict:
                            return self._parse_activity_string(activity)
                        return activity

                logger.warning(f"[ADBBridge] Could not parse activity from: {output[:200]}")
                if as_dict:
                    return {"package": None, "activity": None, "full_name": None}
                return ""

        except Exception as e:
            logger.error(f"[ADBBridge] Failed to get current activity: {e}")
            if as_dict:
                return {"package": None, "activity": None, "full_name": None}
            return ""

    def _parse_activity_string(self, activity_str: str) -> Dict:
        """
        Parse activity string into package and activity components.

        Args:
            activity_str: Format "com.package/activity" or "com.package/.Activity"

        Returns:
            Dict with package, activity, full_name
        """
        if not activity_str or '/' not in activity_str:
            return {"package": None, "activity": None, "full_name": None}

        parts = activity_str.split('/', 1)
        package = parts[0]
        activity = parts[1] if len(parts) > 1 else None

        # Expand shorthand activity names (e.g., ".MainActivity" → "com.package.MainActivity")
        if activity and activity.startswith('.'):
            activity = package + activity

        return {
            "package": package,
            "activity": activity,
            "full_name": activity_str
        }

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

    async def stop_app(self, device_id: str, package_name: str) -> bool:
        """
        Force stop an app by package name.

        Args:
            device_id: Device identifier
            package_name: Package name (e.g., "com.android.chrome")

        Returns:
            True if stop command succeeded

        Raises:
            ValueError: If device not connected
        """
        conn = self.devices.get(device_id)
        if not conn:
            raise ValueError(f"Device not connected: {device_id}")

        try:
            logger.info(f"[ADBBridge] Force stopping app {package_name} on {device_id}")

            # Use am force-stop to kill the app
            await conn.shell(f"am force-stop {package_name}")

            return True

        except Exception as e:
            logger.error(f"[ADBBridge] Failed to stop app {package_name}: {e}")
            return False
