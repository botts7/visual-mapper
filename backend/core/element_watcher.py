"""
Element Watcher - One-click element monitoring

Allows users to "watch" UI elements with a single click.
Watched elements are monitored and published as binary_sensors to Home Assistant.

No flows required - just click "Watch" on any element.
"""

import asyncio
import json
import logging
import time
import re
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ElementSignature:
    """Identifies a UI element for matching."""
    resource_id: str = ""
    text: str = ""
    content_desc: str = ""
    class_name: str = ""
    # Bounds are stored but matching is fuzzy (elements can shift slightly)
    bounds: Optional[Dict[str, int]] = None

    def matches(self, element: Dict[str, Any], fuzzy: bool = True) -> bool:
        """
        Check if this signature matches an element.

        Args:
            element: UI element dict from ADB
            fuzzy: If True, allow partial text matches

        Returns:
            True if element matches this signature
        """
        # Resource ID is the strongest identifier
        if self.resource_id:
            elem_res_id = element.get("resource_id", "") or element.get("resourceId", "")
            if self.resource_id == elem_res_id:
                return True

        # Content description match
        if self.content_desc:
            elem_desc = element.get("content_desc", "") or element.get("contentDescription", "")
            if self.content_desc == elem_desc:
                return True

        # Text match (exact or fuzzy)
        if self.text:
            elem_text = element.get("text", "")
            if fuzzy:
                if self.text.lower() in elem_text.lower() or elem_text.lower() in self.text.lower():
                    return True
            elif self.text == elem_text:
                return True

        # Class + approximate bounds match (fallback)
        if self.class_name and self.bounds:
            elem_class = element.get("class", "") or element.get("className", "")
            elem_bounds = element.get("bounds", {})

            if elem_class == self.class_name and elem_bounds:
                # Check if bounds are within 20% tolerance
                if self._bounds_match(elem_bounds, tolerance=0.2):
                    return True

        return False

    def _bounds_match(self, elem_bounds: Dict[str, int], tolerance: float = 0.2) -> bool:
        """Check if bounds match within tolerance."""
        if not self.bounds or not elem_bounds:
            return False

        for key in ["x", "y", "width", "height"]:
            sig_val = self.bounds.get(key, 0)
            elem_val = elem_bounds.get(key, 0)

            if sig_val == 0:
                continue

            diff = abs(sig_val - elem_val) / max(sig_val, 1)
            if diff > tolerance:
                return False

        return True


@dataclass
class ElementWatcher:
    """A watched element that becomes a binary_sensor."""
    id: str
    device_id: str
    name: str  # Friendly name (auto-generated or user-provided)
    signature: ElementSignature
    sensor_id: str  # MQTT sensor ID
    icon: str = "mdi:eye"
    enabled: bool = True
    # State tracking
    last_seen: Optional[float] = None
    is_visible: bool = False
    check_count: int = 0
    # Timestamps
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "id": self.id,
            "device_id": self.device_id,
            "name": self.name,
            "signature": asdict(self.signature),
            "sensor_id": self.sensor_id,
            "icon": self.icon,
            "enabled": self.enabled,
            "last_seen": self.last_seen,
            "is_visible": self.is_visible,
            "check_count": self.check_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ElementWatcher":
        """Create from dict."""
        sig_data = data.get("signature", {})
        signature = ElementSignature(
            resource_id=sig_data.get("resource_id", ""),
            text=sig_data.get("text", ""),
            content_desc=sig_data.get("content_desc", ""),
            class_name=sig_data.get("class_name", ""),
            bounds=sig_data.get("bounds"),
        )
        return cls(
            id=data["id"],
            device_id=data["device_id"],
            name=data["name"],
            signature=signature,
            sensor_id=data["sensor_id"],
            icon=data.get("icon", "mdi:eye"),
            enabled=data.get("enabled", True),
            last_seen=data.get("last_seen"),
            is_visible=data.get("is_visible", False),
            check_count=data.get("check_count", 0),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


def generate_watcher_name(element: Dict[str, Any]) -> str:
    """
    Auto-generate a friendly name from element properties.

    Priority: text > content_desc > resource_id > class
    """
    # Try text first
    text = element.get("text", "")
    if text and len(text) <= 30:
        # Sanitize: remove special chars, limit length
        name = re.sub(r'[^a-zA-Z0-9\s]', '', text)[:25]
        if name:
            return f"{name} Visible"

    # Try content description
    desc = element.get("content_desc", "") or element.get("contentDescription", "")
    if desc and len(desc) <= 30:
        name = re.sub(r'[^a-zA-Z0-9\s]', '', desc)[:25]
        if name:
            return f"{name} Visible"

    # Try resource ID
    res_id = element.get("resource_id", "") or element.get("resourceId", "")
    if res_id:
        # Extract the ID part after the last /
        id_part = res_id.split("/")[-1] if "/" in res_id else res_id
        # Convert snake_case to Title Case
        name = id_part.replace("_", " ").title()[:25]
        return f"{name} Visible"

    # Fallback to class name
    class_name = element.get("class", "") or element.get("className", "")
    if class_name:
        # Extract just the class name (after last .)
        short_class = class_name.split(".")[-1]
        return f"{short_class} Visible"

    return "Element Visible"


def generate_sensor_id(device_id: str, watcher_name: str) -> str:
    """Generate a unique sensor ID from device and name."""
    # Sanitize device ID
    device_part = re.sub(r'[^a-zA-Z0-9]', '_', device_id)[:20]
    # Sanitize name
    name_part = re.sub(r'[^a-zA-Z0-9]', '_', watcher_name.lower())[:30]
    # Add timestamp for uniqueness
    timestamp = int(time.time() * 1000) % 100000
    return f"{device_part}_{name_part}_{timestamp}"


class ElementWatcherManager:
    """
    Manages element watchers for all devices.

    Watchers are persisted to JSON files and monitored in the background.
    Each visible element becomes a binary_sensor in Home Assistant.
    """

    CHECK_INTERVAL_SECONDS = 10  # How often to check element visibility
    DATA_DIR = Path("data")

    def __init__(self, adb_bridge, mqtt_manager):
        self.adb_bridge = adb_bridge
        self.mqtt_manager = mqtt_manager

        # Watchers indexed by device_id, then watcher_id
        self._watchers: Dict[str, Dict[str, ElementWatcher]] = {}
        self._update_tasks: Dict[str, asyncio.Task] = {}
        self._running = False

        # Ensure data directory exists
        self.DATA_DIR.mkdir(exist_ok=True)

        # Load existing watchers
        self._load_all_watchers()

    def _get_watchers_file(self, device_id: str) -> Path:
        """Get path to watchers JSON file for a device."""
        safe_device_id = re.sub(r'[^a-zA-Z0-9_]', '_', device_id)
        return self.DATA_DIR / f"element_watchers_{safe_device_id}.json"

    def _load_all_watchers(self):
        """Load all watcher files on startup."""
        for file_path in self.DATA_DIR.glob("element_watchers_*.json"):
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                device_id = data.get("device_id", "")
                watchers_data = data.get("watchers", [])

                if device_id:
                    self._watchers[device_id] = {}
                    for w_data in watchers_data:
                        try:
                            watcher = ElementWatcher.from_dict(w_data)
                            self._watchers[device_id][watcher.id] = watcher
                        except Exception as e:
                            logger.warning(f"Failed to load watcher: {e}")

                    logger.info(
                        f"[ElementWatcher] Loaded {len(self._watchers[device_id])} watchers for {device_id}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load watchers from {file_path}: {e}")

    def _save_watchers(self, device_id: str):
        """Save watchers for a device to JSON file."""
        watchers = self._watchers.get(device_id, {})
        data = {
            "device_id": device_id,
            "watchers": [w.to_dict() for w in watchers.values()],
            "updated_at": time.time(),
        }

        file_path = self._get_watchers_file(device_id)
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"[ElementWatcher] Saved {len(watchers)} watchers to {file_path}")
        except Exception as e:
            logger.error(f"[ElementWatcher] Failed to save watchers: {e}")

    async def create_watcher(
        self,
        device_id: str,
        element: Dict[str, Any],
        name: Optional[str] = None,
        icon: str = "mdi:eye",
    ) -> ElementWatcher:
        """
        Create a new element watcher from a UI element.

        This is the "one-click" operation - user clicks "Watch" on an element.

        Args:
            device_id: Device ID
            element: UI element dict from ADB
            name: Optional friendly name (auto-generated if not provided)
            icon: MDI icon for Home Assistant

        Returns:
            Created ElementWatcher
        """
        # Auto-generate name if not provided
        if not name:
            name = generate_watcher_name(element)

        # Create signature from element
        signature = ElementSignature(
            resource_id=element.get("resource_id", "") or element.get("resourceId", ""),
            text=element.get("text", ""),
            content_desc=element.get("content_desc", "") or element.get("contentDescription", ""),
            class_name=element.get("class", "") or element.get("className", ""),
            bounds=element.get("bounds"),
        )

        # Generate IDs
        watcher_id = f"ew_{int(time.time() * 1000) % 1000000}"
        sensor_id = generate_sensor_id(device_id, name)

        # Create watcher
        watcher = ElementWatcher(
            id=watcher_id,
            device_id=device_id,
            name=name,
            signature=signature,
            sensor_id=sensor_id,
            icon=icon,
            enabled=True,
            is_visible=True,  # Assume visible since user just clicked it
            last_seen=time.time(),
        )

        # Store
        if device_id not in self._watchers:
            self._watchers[device_id] = {}
        self._watchers[device_id][watcher_id] = watcher

        # Save to file
        self._save_watchers(device_id)

        # Publish MQTT discovery
        await self._publish_discovery(watcher)

        # Publish initial state (visible)
        await self._publish_state(watcher)

        logger.info(
            f"[ElementWatcher] Created watcher '{name}' for {device_id} "
            f"(resource_id={signature.resource_id}, text={signature.text[:20] if signature.text else 'none'})"
        )

        return watcher

    async def delete_watcher(self, device_id: str, watcher_id: str) -> bool:
        """Delete an element watcher."""
        watchers = self._watchers.get(device_id, {})
        if watcher_id not in watchers:
            return False

        watcher = watchers.pop(watcher_id)

        # Remove from MQTT
        await self._remove_discovery(watcher)

        # Save
        self._save_watchers(device_id)

        logger.info(f"[ElementWatcher] Deleted watcher '{watcher.name}' from {device_id}")
        return True

    def get_watchers(self, device_id: str) -> List[ElementWatcher]:
        """Get all watchers for a device."""
        return list(self._watchers.get(device_id, {}).values())

    def get_watcher(self, device_id: str, watcher_id: str) -> Optional[ElementWatcher]:
        """Get a specific watcher."""
        return self._watchers.get(device_id, {}).get(watcher_id)

    async def start_device(self, device_id: str):
        """Start monitoring watchers for a device."""
        if device_id in self._update_tasks and not self._update_tasks[device_id].done():
            return  # Already running

        # Publish discoveries for existing watchers
        for watcher in self.get_watchers(device_id):
            if watcher.enabled:
                await self._publish_discovery(watcher)

        # Start update loop
        self._update_tasks[device_id] = asyncio.create_task(
            self._update_loop(device_id)
        )
        logger.info(f"[ElementWatcher] Started monitoring for {device_id}")

    async def stop_device(self, device_id: str):
        """Stop monitoring watchers for a device."""
        if device_id in self._update_tasks:
            self._update_tasks[device_id].cancel()
            try:
                await self._update_tasks[device_id]
            except asyncio.CancelledError:
                pass
            del self._update_tasks[device_id]
            logger.info(f"[ElementWatcher] Stopped monitoring for {device_id}")

    async def _update_loop(self, device_id: str):
        """Background loop to check element visibility."""
        while True:
            try:
                await self._check_elements(device_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[ElementWatcher] Update error for {device_id}: {e}")

            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    async def _check_elements(self, device_id: str):
        """Check visibility of all watched elements for a device."""
        watchers = [w for w in self.get_watchers(device_id) if w.enabled]
        if not watchers:
            return

        try:
            # Get current UI elements
            elements = await self.adb_bridge.get_ui_elements(device_id)
            if not elements:
                return

            # Check each watcher
            for watcher in watchers:
                watcher.check_count += 1
                was_visible = watcher.is_visible

                # Check if any element matches the signature
                is_visible = any(
                    watcher.signature.matches(elem)
                    for elem in elements
                )

                watcher.is_visible = is_visible
                if is_visible:
                    watcher.last_seen = time.time()

                # Publish state if changed
                if is_visible != was_visible:
                    await self._publish_state(watcher)
                    logger.debug(
                        f"[ElementWatcher] '{watcher.name}' visibility changed: {was_visible} -> {is_visible}"
                    )

            # Save updated state periodically
            self._save_watchers(device_id)

        except Exception as e:
            logger.debug(f"[ElementWatcher] Failed to check elements: {e}")

    async def _publish_discovery(self, watcher: ElementWatcher):
        """Publish MQTT discovery for a watcher."""
        if not self.mqtt_manager:
            return

        try:
            # Get stable device ID
            stable_device_id = None
            if self.adb_bridge:
                try:
                    stable_device_id = await self.adb_bridge.get_device_serial(watcher.device_id)
                except Exception:
                    pass

            await self.mqtt_manager.publish_auto_sensor_discovery(
                device_id=watcher.device_id,
                stable_device_id=stable_device_id or watcher.device_id,
                sensor_id=watcher.sensor_id,
                name=watcher.name,
                sensor_type="binary_sensor",
                icon=watcher.icon,
                device_class=None,
                unit=None,
            )
        except Exception as e:
            logger.warning(f"[ElementWatcher] Failed to publish discovery: {e}")

    async def _publish_state(self, watcher: ElementWatcher):
        """Publish current state to MQTT."""
        if not self.mqtt_manager:
            return

        try:
            device_name = watcher.device_id.replace(":", "_").replace(".", "_")
            await self.mqtt_manager.publish_auto_sensor_state(
                device_name=device_name,
                sensor_id=watcher.sensor_id,
                state="ON" if watcher.is_visible else "OFF",
                attributes={
                    "last_seen": watcher.last_seen,
                    "check_count": watcher.check_count,
                    "resource_id": watcher.signature.resource_id,
                    "element_text": watcher.signature.text[:50] if watcher.signature.text else None,
                },
            )
        except Exception as e:
            logger.debug(f"[ElementWatcher] Failed to publish state: {e}")

    async def _remove_discovery(self, watcher: ElementWatcher):
        """Remove MQTT discovery for a watcher."""
        if not self.mqtt_manager:
            return

        try:
            # Publish empty payload to remove from HA
            stable_device_id = None
            if self.adb_bridge:
                try:
                    stable_device_id = await self.adb_bridge.get_device_serial(watcher.device_id)
                except Exception:
                    pass

            sanitized_device = re.sub(r'[^a-zA-Z0-9_]', '_', stable_device_id or watcher.device_id)
            sanitized_sensor = re.sub(r'[^a-zA-Z0-9_]', '_', watcher.sensor_id)
            topic = f"homeassistant/binary_sensor/{sanitized_device}/{sanitized_sensor}/config"

            # Publish empty payload with retain to remove
            if hasattr(self.mqtt_manager, 'client') and self.mqtt_manager.client:
                self.mqtt_manager.client.publish(topic, "", retain=True)
        except Exception as e:
            logger.debug(f"[ElementWatcher] Failed to remove discovery: {e}")


# Singleton instance
_element_watcher_manager: Optional[ElementWatcherManager] = None


def get_element_watcher_manager() -> Optional[ElementWatcherManager]:
    """Get the global ElementWatcherManager instance."""
    return _element_watcher_manager


def init_element_watcher_manager(adb_bridge, mqtt_manager) -> ElementWatcherManager:
    """Initialize the global ElementWatcherManager instance."""
    global _element_watcher_manager
    _element_watcher_manager = ElementWatcherManager(adb_bridge, mqtt_manager)
    return _element_watcher_manager
