"""
Device Identity Resolver - Maps connection IDs to stable device IDs

This service solves the problem of Android 11+ wireless debugging port changes.
It maintains a persistent mapping between:
- connection_id: The IP:port or USB serial used to connect (changes with each session)
- stable_device_id: Hardware serial or android_id hash (persistent across sessions)

Usage:
    resolver = DeviceIdentityResolver()

    # When a device connects, register it
    resolver.register_device("192.168.1.2:46747", "R9YT50J4S9D")

    # Later, resolve connection_id to stable_id
    stable_id = resolver.get_stable_id("192.168.1.2:46747")

    # Or find connection_id for a stable_id
    conn_id = resolver.get_connection_id("R9YT50J4S9D")
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)


class DeviceIdentityResolver:
    """
    Resolves between connection IDs (IP:port) and stable device IDs (hardware serial).

    Maintains a persistent mapping that survives server restarts.
    Handles device migrations when stable_device_id changes (rare).
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.mapping_file = self.data_dir / "device_identity_map.json"
        self._lock = Lock()

        # In-memory mappings
        self._conn_to_stable: Dict[str, str] = {}  # connection_id -> stable_device_id
        self._stable_to_conn: Dict[str, str] = (
            {}
        )  # stable_device_id -> connection_id (current)
        self._device_info: Dict[str, Dict] = {}  # stable_device_id -> device metadata

        # Legacy ID mappings for migration
        self._legacy_to_stable: Dict[str, str] = {}  # old_id -> new_stable_id

        self._load_mapping()
        logger.info(
            f"[DeviceIdentity] Initialized with {len(self._stable_to_conn)} known devices"
        )

    def _load_mapping(self):
        """Load mappings from disk"""
        if not self.mapping_file.exists():
            return

        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._conn_to_stable = data.get("conn_to_stable", {})
            self._stable_to_conn = data.get("stable_to_conn", {})
            self._device_info = data.get("device_info", {})
            self._legacy_to_stable = data.get("legacy_to_stable", {})

            logger.debug(
                f"[DeviceIdentity] Loaded {len(self._stable_to_conn)} device mappings"
            )
        except Exception as e:
            logger.error(f"[DeviceIdentity] Failed to load mapping: {e}")

    def _save_mapping(self):
        """Save mappings to disk"""
        try:
            data = {
                "conn_to_stable": self._conn_to_stable,
                "stable_to_conn": self._stable_to_conn,
                "device_info": self._device_info,
                "legacy_to_stable": self._legacy_to_stable,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.mapping_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.debug("[DeviceIdentity] Saved device mappings")
        except Exception as e:
            logger.error(f"[DeviceIdentity] Failed to save mapping: {e}")

    def register_device(
        self,
        connection_id: str,
        stable_device_id: str,
        device_model: Optional[str] = None,
        device_manufacturer: Optional[str] = None,
    ) -> bool:
        """
        Register a device connection with its stable ID.

        Call this when a device connects successfully.

        Args:
            connection_id: The IP:port or USB serial used to connect
            stable_device_id: Hardware serial (preferred) or android_id hash
            device_model: Optional device model name
            device_manufacturer: Optional manufacturer name

        Returns:
            True if this is a new device or updated connection, False otherwise
        """
        with self._lock:
            is_new = stable_device_id not in self._stable_to_conn
            old_conn = self._stable_to_conn.get(stable_device_id)

            # Update mappings
            self._conn_to_stable[connection_id] = stable_device_id
            self._stable_to_conn[stable_device_id] = connection_id

            # Update device info
            if stable_device_id not in self._device_info:
                self._device_info[stable_device_id] = {}

            self._device_info[stable_device_id].update(
                {
                    "current_connection": connection_id,
                    "last_seen": datetime.now().isoformat(),
                    "model": device_model
                    or self._device_info[stable_device_id].get("model"),
                    "manufacturer": device_manufacturer
                    or self._device_info[stable_device_id].get("manufacturer"),
                }
            )

            # Track connection history
            history = self._device_info[stable_device_id].get("connection_history", [])
            if connection_id not in history:
                history.append(connection_id)
                # Keep last 10 connections
                self._device_info[stable_device_id]["connection_history"] = history[
                    -10:
                ]

            self._save_mapping()

            if is_new:
                logger.info(
                    f"[DeviceIdentity] New device registered: {stable_device_id} via {connection_id}"
                )
            elif old_conn != connection_id:
                logger.info(
                    f"[DeviceIdentity] Device {stable_device_id} reconnected: {old_conn} -> {connection_id}"
                )

            return is_new or old_conn != connection_id

    def get_stable_id(self, connection_id: str) -> Optional[str]:
        """
        Get stable device ID for a connection ID.

        Args:
            connection_id: IP:port or USB serial

        Returns:
            Stable device ID if known, None otherwise
        """
        with self._lock:
            return self._conn_to_stable.get(connection_id)

    def get_connection_id(self, stable_device_id: str) -> Optional[str]:
        """
        Get current connection ID for a stable device ID.

        Args:
            stable_device_id: Hardware serial or android_id hash

        Returns:
            Current connection ID if device is known, None otherwise
        """
        with self._lock:
            return self._stable_to_conn.get(stable_device_id)

    def resolve_any_id(self, device_id: str) -> str:
        """
        Resolve any device ID (connection or stable) to the stable ID.

        This is the main method to use when you have an ID and need the stable version.
        Handles both IP:port and stable IDs transparently.

        Args:
            device_id: Either connection_id (IP:port) or stable_device_id

        Returns:
            stable_device_id if resolvable, or the input as-is
        """
        with self._lock:
            # Check if it's a known connection_id
            if device_id in self._conn_to_stable:
                return self._conn_to_stable[device_id]

            # Check if it's already a stable_device_id
            if device_id in self._stable_to_conn:
                return device_id

            # Check legacy mappings
            if device_id in self._legacy_to_stable:
                return self._legacy_to_stable[device_id]

            # Unknown - return as-is (might be a new device)
            return device_id

    def register_legacy_id(self, legacy_id: str, stable_device_id: str):
        """
        Register a legacy ID that should map to a stable device ID.

        Use this when migrating old data that used android_id hashes.

        Args:
            legacy_id: Old ID format (e.g., android_id hash like "c7028879b7a83aa7")
            stable_device_id: New stable ID (hardware serial like "R9YT50J4S9D")
        """
        with self._lock:
            self._legacy_to_stable[legacy_id] = stable_device_id
            logger.info(
                f"[DeviceIdentity] Registered legacy mapping: {legacy_id} -> {stable_device_id}"
            )
            self._save_mapping()

    def get_device_info(self, stable_device_id: str) -> Optional[Dict]:
        """Get device metadata"""
        with self._lock:
            return self._device_info.get(stable_device_id)

    def get_all_devices(self) -> List[Dict]:
        """Get list of all known devices with their info"""
        with self._lock:
            devices = []
            for stable_id, info in self._device_info.items():
                devices.append(
                    {
                        "stable_device_id": stable_id,
                        "current_connection": info.get("current_connection"),
                        "model": info.get("model"),
                        "manufacturer": info.get("manufacturer"),
                        "last_seen": info.get("last_seen"),
                        "connection_count": len(info.get("connection_history", [])),
                    }
                )
            return devices

    def forget_device(self, device_id: str) -> bool:
        """
        Remove a device from persistent storage (forget it completely).

        Args:
            device_id: Either stable_device_id or connection_id (IP:port)

        Returns:
            True if device was found and removed, False otherwise
        """
        with self._lock:
            # Try to resolve to stable_id first
            stable_id = None

            # Check if it's already a stable_id
            if device_id in self._device_info:
                stable_id = device_id
            # Check if it's a connection_id
            elif device_id in self._conn_to_stable:
                stable_id = self._conn_to_stable[device_id]

            if not stable_id:
                logger.warning(f"[DeviceIdentity] Device {device_id} not found in registry")
                return False

            # Remove from all mappings
            conn_id = self._stable_to_conn.get(stable_id)
            if conn_id and conn_id in self._conn_to_stable:
                del self._conn_to_stable[conn_id]
            if stable_id in self._stable_to_conn:
                del self._stable_to_conn[stable_id]
            if stable_id in self._device_info:
                del self._device_info[stable_id]

            # Also check legacy mappings
            legacy_to_remove = [k for k, v in self._legacy_to_stable.items() if v == stable_id]
            for legacy_id in legacy_to_remove:
                del self._legacy_to_stable[legacy_id]

            self._save_mapping()
            logger.info(f"[DeviceIdentity] Forgot device {stable_id} (was {device_id})")
            return True

    def sanitize_for_filename(self, device_id: str) -> str:
        """
        Sanitize a device ID for use in filenames.

        Args:
            device_id: Any device ID

        Returns:
            Filesystem-safe version
        """
        # First resolve to stable ID
        stable_id = self.resolve_any_id(device_id)
        # Then sanitize
        return (
            stable_id.replace(":", "_")
            .replace(".", "_")
            .replace("/", "_")
            .replace(" ", "_")
        )

    def sanitize_for_mqtt(self, device_id: str) -> str:
        """
        Sanitize a device ID for use in MQTT topics.

        Args:
            device_id: Any device ID

        Returns:
            MQTT-safe version (no +, #, /, or spaces)
        """
        stable_id = self.resolve_any_id(device_id)
        import re

        return re.sub(r"[^a-zA-Z0-9_-]", "_", stable_id)


# Singleton instance for global access
_resolver_instance: Optional[DeviceIdentityResolver] = None


def get_device_identity_resolver(data_dir: str = "data") -> DeviceIdentityResolver:
    """Get or create the singleton DeviceIdentityResolver instance"""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = DeviceIdentityResolver(data_dir)
    return _resolver_instance
