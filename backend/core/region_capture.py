"""
Region Capture - Screenshot regions linked to sensors

Allows users to capture a screen region and link it to sensors.
The region becomes a picture entity in Home Assistant, showing
visual context for the extracted sensor values.

Example: Capture the solar graph area → link to sensor.solar_production
         HA card shows the graph image + the extracted value
"""

import asyncio
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class RegionBounds:
    """Screen region coordinates."""
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> "RegionBounds":
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            width=data.get("width", 100),
            height=data.get("height", 100),
        )


@dataclass
class CapturedRegion:
    """A captured screen region linked to sensors."""
    id: str
    device_id: str
    name: str  # Friendly name (e.g., "Solar Graph")
    bounds: RegionBounds
    linked_sensors: List[str] = field(default_factory=list)  # Sensor IDs
    # Image settings
    jpeg_quality: int = 75
    update_interval_seconds: int = 60  # How often to refresh
    # State
    last_captured: Optional[float] = None
    last_image_path: Optional[str] = None
    enabled: bool = True
    # Timestamps
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "name": self.name,
            "bounds": self.bounds.to_dict(),
            "linked_sensors": self.linked_sensors,
            "jpeg_quality": self.jpeg_quality,
            "update_interval_seconds": self.update_interval_seconds,
            "last_captured": self.last_captured,
            "last_image_path": self.last_image_path,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapturedRegion":
        bounds_data = data.get("bounds", {})
        return cls(
            id=data["id"],
            device_id=data["device_id"],
            name=data["name"],
            bounds=RegionBounds.from_dict(bounds_data),
            linked_sensors=data.get("linked_sensors", []),
            jpeg_quality=data.get("jpeg_quality", 75),
            update_interval_seconds=data.get("update_interval_seconds", 60),
            last_captured=data.get("last_captured"),
            last_image_path=data.get("last_image_path"),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


def generate_region_id(device_id: str, name: str) -> str:
    """Generate a unique region ID."""
    device_part = re.sub(r'[^a-zA-Z0-9]', '_', device_id)[:15]
    name_part = re.sub(r'[^a-zA-Z0-9]', '_', name.lower())[:20]
    timestamp = int(time.time() * 1000) % 100000
    return f"region_{device_part}_{name_part}_{timestamp}"


class RegionCaptureManager:
    """
    Manages captured screen regions linked to sensors.

    Regions are periodically captured and served as images
    that can be displayed in Home Assistant cards.
    """

    DATA_DIR = Path("data")
    IMAGES_DIR = Path("data/region_images")
    UPDATE_INTERVAL_SECONDS = 60  # Default refresh interval

    def __init__(self, adb_bridge, mqtt_manager=None):
        self.adb_bridge = adb_bridge
        self.mqtt_manager = mqtt_manager

        # Regions indexed by device_id, then region_id
        self._regions: Dict[str, Dict[str, CapturedRegion]] = {}
        self._update_tasks: Dict[str, asyncio.Task] = {}

        # Ensure directories exist
        self.DATA_DIR.mkdir(exist_ok=True)
        self.IMAGES_DIR.mkdir(exist_ok=True)

        # Load existing regions
        self._load_all_regions()

    def _get_regions_file(self, device_id: str) -> Path:
        """Get path to regions JSON file for a device."""
        safe_device_id = re.sub(r'[^a-zA-Z0-9_]', '_', device_id)
        return self.DATA_DIR / f"regions_{safe_device_id}.json"

    def _get_image_path(self, region: CapturedRegion) -> Path:
        """Get path for a region's image file."""
        safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', region.id)
        return self.IMAGES_DIR / f"{safe_id}.jpg"

    def _load_all_regions(self):
        """Load all region files on startup."""
        for file_path in self.DATA_DIR.glob("regions_*.json"):
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                device_id = data.get("device_id", "")
                regions_data = data.get("regions", [])

                if device_id:
                    self._regions[device_id] = {}
                    for r_data in regions_data:
                        try:
                            region = CapturedRegion.from_dict(r_data)
                            self._regions[device_id][region.id] = region
                        except Exception as e:
                            logger.warning(f"Failed to load region: {e}")

                    logger.info(
                        f"[RegionCapture] Loaded {len(self._regions[device_id])} regions for {device_id}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load regions from {file_path}: {e}")

    def _save_regions(self, device_id: str):
        """Save regions for a device to JSON file."""
        regions = self._regions.get(device_id, {})
        data = {
            "device_id": device_id,
            "regions": [r.to_dict() for r in regions.values()],
            "updated_at": time.time(),
        }

        file_path = self._get_regions_file(device_id)
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"[RegionCapture] Saved {len(regions)} regions to {file_path}")
        except Exception as e:
            logger.error(f"[RegionCapture] Failed to save regions: {e}")

    async def create_region(
        self,
        device_id: str,
        name: str,
        bounds: Dict[str, int],
        linked_sensors: Optional[List[str]] = None,
        jpeg_quality: int = 75,
        update_interval_seconds: int = 60,
    ) -> CapturedRegion:
        """
        Create a new captured region.

        Args:
            device_id: Device ID
            name: Friendly name (e.g., "Solar Graph")
            bounds: Region bounds {x, y, width, height}
            linked_sensors: Optional list of sensor IDs to link
            jpeg_quality: JPEG compression quality (1-100)
            update_interval_seconds: How often to refresh the image

        Returns:
            Created CapturedRegion
        """
        region_id = generate_region_id(device_id, name)

        region = CapturedRegion(
            id=region_id,
            device_id=device_id,
            name=name,
            bounds=RegionBounds.from_dict(bounds),
            linked_sensors=linked_sensors or [],
            jpeg_quality=jpeg_quality,
            update_interval_seconds=update_interval_seconds,
            enabled=True,
        )

        # Store
        if device_id not in self._regions:
            self._regions[device_id] = {}
        self._regions[device_id][region_id] = region

        # Capture initial image
        await self._capture_region(region)

        # Save
        self._save_regions(device_id)

        logger.info(
            f"[RegionCapture] Created region '{name}' for {device_id} "
            f"(bounds={bounds}, linked_sensors={linked_sensors})"
        )

        return region

    async def delete_region(self, device_id: str, region_id: str) -> bool:
        """Delete a captured region."""
        regions = self._regions.get(device_id, {})
        if region_id not in regions:
            return False

        region = regions.pop(region_id)

        # Delete image file
        image_path = self._get_image_path(region)
        if image_path.exists():
            try:
                image_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete image: {e}")

        # Save
        self._save_regions(device_id)

        logger.info(f"[RegionCapture] Deleted region '{region.name}' from {device_id}")
        return True

    def get_regions(self, device_id: str) -> List[CapturedRegion]:
        """Get all regions for a device."""
        return list(self._regions.get(device_id, {}).values())

    def get_region(self, device_id: str, region_id: str) -> Optional[CapturedRegion]:
        """Get a specific region."""
        return self._regions.get(device_id, {}).get(region_id)

    async def link_sensor(self, device_id: str, region_id: str, sensor_id: str) -> bool:
        """Link a sensor to a region."""
        region = self.get_region(device_id, region_id)
        if not region:
            return False

        if sensor_id not in region.linked_sensors:
            region.linked_sensors.append(sensor_id)
            region.updated_at = time.time()
            self._save_regions(device_id)
            logger.info(f"[RegionCapture] Linked sensor {sensor_id} to region {region_id}")

        return True

    async def unlink_sensor(self, device_id: str, region_id: str, sensor_id: str) -> bool:
        """Unlink a sensor from a region."""
        region = self.get_region(device_id, region_id)
        if not region:
            return False

        if sensor_id in region.linked_sensors:
            region.linked_sensors.remove(sensor_id)
            region.updated_at = time.time()
            self._save_regions(device_id)
            logger.info(f"[RegionCapture] Unlinked sensor {sensor_id} from region {region_id}")

        return True

    async def capture_now(self, device_id: str, region_id: str) -> Optional[bytes]:
        """
        Capture a region immediately and return the image bytes.

        Also updates the stored image file.
        """
        region = self.get_region(device_id, region_id)
        if not region:
            return None

        return await self._capture_region(region)

    async def get_image(self, device_id: str, region_id: str) -> Optional[bytes]:
        """
        Get the latest captured image for a region.

        Returns cached image if available, otherwise captures fresh.
        """
        region = self.get_region(device_id, region_id)
        if not region:
            return None

        image_path = self._get_image_path(region)

        # Return cached image if recent enough
        if image_path.exists():
            try:
                # Check if image is still fresh
                file_age = time.time() - image_path.stat().st_mtime
                if file_age < region.update_interval_seconds:
                    return image_path.read_bytes()
            except Exception:
                pass

        # Capture fresh image
        return await self._capture_region(region)

    async def _capture_region(self, region: CapturedRegion) -> Optional[bytes]:
        """Capture and save a region image."""
        try:
            # Get full screenshot
            screenshot_bytes = await self.adb_bridge.capture_screenshot(region.device_id)
            if not screenshot_bytes or len(screenshot_bytes) < 1000:
                logger.warning(f"[RegionCapture] Failed to capture screenshot for {region.device_id}")
                return None

            # Open and crop
            img = Image.open(io.BytesIO(screenshot_bytes))
            bounds = region.bounds

            # Ensure bounds are within image
            x = max(0, min(bounds.x, img.width - 1))
            y = max(0, min(bounds.y, img.height - 1))
            right = min(bounds.x + bounds.width, img.width)
            bottom = min(bounds.y + bounds.height, img.height)

            # Crop the region
            cropped = img.crop((x, y, right, bottom))

            # Convert to JPEG
            output = io.BytesIO()
            if cropped.mode == "RGBA":
                cropped = cropped.convert("RGB")
            cropped.save(output, format="JPEG", quality=region.jpeg_quality, optimize=True)
            image_bytes = output.getvalue()

            # Save to file
            image_path = self._get_image_path(region)
            image_path.write_bytes(image_bytes)

            # Update state
            region.last_captured = time.time()
            region.last_image_path = str(image_path)

            logger.debug(
                f"[RegionCapture] Captured region '{region.name}': "
                f"{cropped.width}x{cropped.height}, {len(image_bytes)} bytes"
            )

            return image_bytes

        except Exception as e:
            logger.warning(f"[RegionCapture] Failed to capture region: {e}")
            return None

    async def start_device(self, device_id: str):
        """Start background capture for a device's regions."""
        if device_id in self._update_tasks and not self._update_tasks[device_id].done():
            return  # Already running

        regions = self.get_regions(device_id)
        if not regions:
            return  # No regions to capture

        self._update_tasks[device_id] = asyncio.create_task(
            self._update_loop(device_id)
        )
        logger.info(f"[RegionCapture] Started capture loop for {device_id} ({len(regions)} regions)")

    async def stop_device(self, device_id: str):
        """Stop background capture for a device."""
        if device_id in self._update_tasks:
            self._update_tasks[device_id].cancel()
            try:
                await self._update_tasks[device_id]
            except asyncio.CancelledError:
                pass
            del self._update_tasks[device_id]
            logger.info(f"[RegionCapture] Stopped capture loop for {device_id}")

    async def _update_loop(self, device_id: str):
        """Background loop to periodically capture regions."""
        while True:
            try:
                regions = [r for r in self.get_regions(device_id) if r.enabled]
                if not regions:
                    await asyncio.sleep(60)
                    continue

                # Find minimum update interval
                min_interval = min(r.update_interval_seconds for r in regions)

                # Capture each region that's due
                now = time.time()
                for region in regions:
                    if region.last_captured is None or \
                       (now - region.last_captured) >= region.update_interval_seconds:
                        await self._capture_region(region)

                # Save state
                self._save_regions(device_id)

                await asyncio.sleep(min_interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[RegionCapture] Update loop error: {e}")
                await asyncio.sleep(60)


# Singleton instance
_region_capture_manager: Optional[RegionCaptureManager] = None


def get_region_capture_manager() -> Optional[RegionCaptureManager]:
    """Get the global RegionCaptureManager instance."""
    return _region_capture_manager


def init_region_capture_manager(adb_bridge, mqtt_manager=None) -> RegionCaptureManager:
    """Initialize the global RegionCaptureManager instance."""
    global _region_capture_manager
    _region_capture_manager = RegionCaptureManager(adb_bridge, mqtt_manager)
    return _region_capture_manager
