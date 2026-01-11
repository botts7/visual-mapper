"""
Visual Mapper - Device Icon Scraper (Phase 8 Enhancement)
Scrapes app icons directly from device launcher/app drawer

Features:
- Scrapes icons from device app drawer (device-specific rendering)
- Handles adaptive icons, themed icons, custom launchers
- Triggered on device onboarding and when new apps detected
- Local persistent cache (data/device-icons/{device_id}/)
"""

import os
import io
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from PIL import Image

logger = logging.getLogger(__name__)


class DeviceIconScraper:
    """
    Scrapes app icons from device app drawer

    Strategy:
    1. Open device launcher (app drawer)
    2. Take screenshot of app grid
    3. Get UI hierarchy to map icons to packages
    4. Crop individual icons from screenshot
    5. Cache locally per device
    """

    def __init__(self, adb_bridge, cache_dir: str = "data/device-icons"):
        """
        Initialize device icon scraper

        Args:
            adb_bridge: ADBBridge instance for device interaction
            cache_dir: Directory to cache scraped icons
        """
        self.adb_bridge = adb_bridge
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[DeviceIconScraper] Initialized (cache: {cache_dir})")

    def _sanitize_device_id(self, device_id: str) -> str:
        """Sanitize device ID for use in file paths (Windows doesn't allow colons)"""
        return device_id.replace(":", "_")

    async def scrape_device_icons(self, device_id: str, max_apps: int = None) -> int:
        """
        Scrape all app icons from device launcher

        Args:
            device_id: ADB device ID
            max_apps: Maximum number of apps to scrape (None = all)

        Returns:
            Number of icons successfully scraped
        """
        logger.info(f"[DeviceIconScraper] Starting icon scrape for device {device_id}")

        try:
            # 1. Get list of installed apps
            apps = await self.adb_bridge.get_installed_apps(device_id)
            logger.info(f"[DeviceIconScraper] Found {len(apps)} installed apps")

            # 2. Open app drawer (try multiple launcher methods)
            await self._open_app_drawer(device_id)

            # 3. Wait for UI to settle
            import asyncio

            await asyncio.sleep(2)

            # 4. Get UI hierarchy and screenshot
            hierarchy_xml = await self.adb_bridge.get_ui_hierarchy_xml(device_id)
            screenshot = await self.adb_bridge.capture_screenshot(device_id)

            if not hierarchy_xml or not screenshot:
                logger.error(
                    "[DeviceIconScraper] Failed to get UI hierarchy or screenshot"
                )
                return 0

            # 5. Parse hierarchy and extract icon positions
            icon_mappings = self._parse_app_drawer_hierarchy(hierarchy_xml, apps)
            logger.info(f"[DeviceIconScraper] Found {len(icon_mappings)} icon mappings")

            # 6. Crop and save icons
            success_count = 0
            device_cache_dir = self.cache_dir / self._sanitize_device_id(device_id)
            device_cache_dir.mkdir(parents=True, exist_ok=True)

            screenshot_img = Image.open(io.BytesIO(screenshot))

            for package_name, bounds in (
                list(icon_mappings.items())[:max_apps]
                if max_apps
                else icon_mappings.items()
            ):
                try:
                    # Crop icon from screenshot
                    icon_img = screenshot_img.crop(bounds)

                    # Save to cache
                    cache_path = device_cache_dir / f"{package_name}.png"
                    icon_img.save(cache_path, "PNG")

                    success_count += 1
                    logger.debug(
                        f"[DeviceIconScraper] ✅ Scraped icon for {package_name}"
                    )

                except Exception as e:
                    logger.warning(
                        f"[DeviceIconScraper] ❌ Failed to scrape {package_name}: {e}"
                    )

            logger.info(
                f"[DeviceIconScraper] ✅ Scraped {success_count}/{len(icon_mappings)} icons from {device_id}"
            )

            # 7. Return to home
            await self._return_home(device_id)

            return success_count

        except Exception as e:
            logger.error(f"[DeviceIconScraper] Scraping failed for {device_id}: {e}")
            await self._return_home(device_id)
            return 0

    def get_icon(self, device_id: str, package_name: str) -> Optional[bytes]:
        """
        Get cached device-specific icon

        Args:
            device_id: ADB device ID
            package_name: App package name

        Returns:
            Icon PNG data or None if not cached
        """
        cache_path = (
            self.cache_dir / self._sanitize_device_id(device_id) / f"{package_name}.png"
        )
        if cache_path.exists():
            logger.debug(
                f"[DeviceIconScraper] Cache hit for {device_id}/{package_name}"
            )
            return cache_path.read_bytes()
        return None

    def should_update(self, device_id: str, current_apps: List[str]) -> bool:
        """
        Check if icon cache should be updated (new apps installed)

        Args:
            device_id: ADB device ID
            current_apps: List of currently installed package names

        Returns:
            True if cache should be updated
        """
        device_cache_dir = self.cache_dir / self._sanitize_device_id(device_id)
        if not device_cache_dir.exists():
            logger.info(
                f"[DeviceIconScraper] No cache exists for {device_id}, needs initial scrape"
            )
            return True

        # Get cached package names
        cached_packages = {f.stem for f in device_cache_dir.glob("*.png")}
        current_packages = set(current_apps)

        # Check for new apps
        new_apps = current_packages - cached_packages
        if new_apps:
            logger.info(
                f"[DeviceIconScraper] Detected {len(new_apps)} new apps on {device_id}"
            )
            return True

        return False

    async def _open_app_drawer(self, device_id: str):
        """Open device app drawer (try multiple launcher methods)"""
        try:
            # Method 1: Swipe up from bottom (works on most modern launchers)
            await self.adb_bridge.swipe(device_id, 540, 1800, 540, 500, 300)
            logger.debug("[DeviceIconScraper] Opened app drawer (swipe method)")
        except:
            try:
                # Method 2: KEYCODE_APP_SWITCH (Samsung, some launchers)
                await self.adb_bridge.keyevent(device_id, "KEYCODE_APP_SWITCH")
                logger.debug("[DeviceIconScraper] Opened app drawer (keycode method)")
            except:
                logger.warning("[DeviceIconScraper] Failed to open app drawer")

    async def _return_home(self, device_id: str):
        """Return device to home screen"""
        try:
            await self.adb_bridge.keyevent(device_id, "KEYCODE_HOME")
            logger.debug("[DeviceIconScraper] Returned to home screen")
        except:
            pass

    def _parse_app_drawer_hierarchy(
        self, hierarchy_xml: str, apps: List[dict]
    ) -> Dict[str, Tuple[int, int, int, int]]:
        """
        Parse UI hierarchy to find app icons and their screen positions

        Args:
            hierarchy_xml: UI hierarchy XML string
            apps: List of installed app dicts with 'package' and 'label'

        Returns:
            Dict mapping package_name -> (left, top, right, bottom) bounds
        """
        icon_mappings = {}

        try:
            root = ET.fromstring(hierarchy_xml)

            # Build package name mapping (both package and label)
            package_map = {app["package"].lower(): app["package"] for app in apps}
            label_map = {
                app["label"].lower(): app["package"] for app in apps if "label" in app
            }

            # Find all nodes that could be app icons
            # Strategy: Look for ImageView/TextView pairs or containers with app info
            for node in root.iter("node"):
                package_name = None
                bounds_str = node.get("bounds")

                if not bounds_str:
                    continue

                # Strategy 1: Check text/content-desc for app name
                text = (node.get("text") or "").lower()
                content_desc = (node.get("content-desc") or "").lower()

                # Try to match by label
                if text in label_map:
                    package_name = label_map[text]
                elif content_desc in label_map:
                    package_name = label_map[content_desc]

                # Strategy 2: Check resource-id for package hints
                resource_id = node.get("resource-id") or ""
                for pkg in package_map.keys():
                    if pkg in resource_id.lower():
                        package_name = package_map[pkg]
                        break

                # Strategy 3: For ImageView, look at parent/sibling text nodes
                if not package_name and node.get("class") == "android.widget.ImageView":
                    parent = node.find("..")
                    if parent is not None:
                        for sibling in parent:
                            sib_text = (sibling.get("text") or "").lower()
                            sib_desc = (sibling.get("content-desc") or "").lower()
                            if sib_text in label_map:
                                package_name = label_map[sib_text]
                                break
                            elif sib_desc in label_map:
                                package_name = label_map[sib_desc]
                                break

                if package_name and package_name not in icon_mappings:
                    # Parse bounds: "[left,top][right,bottom]"
                    bounds = self._parse_bounds(bounds_str)
                    if bounds:
                        icon_mappings[package_name] = bounds
                        logger.debug(
                            f"[DeviceIconScraper] Mapped {package_name} to bounds {bounds}"
                        )

        except Exception as e:
            logger.error(f"[DeviceIconScraper] Failed to parse hierarchy: {e}")

        return icon_mappings

    def _parse_bounds(self, bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
        """
        Parse bounds string from UI hierarchy

        Args:
            bounds_str: Bounds string like "[0,0][100,100]"

        Returns:
            Tuple of (left, top, right, bottom) or None
        """
        try:
            # Remove brackets and split
            bounds_str = bounds_str.replace("][", ",").replace("[", "").replace("]", "")
            coords = [int(x) for x in bounds_str.split(",")]
            if len(coords) == 4:
                return tuple(coords)
        except:
            pass
        return None

    def get_cache_stats(self, device_id: str = None) -> dict:
        """Get cache statistics"""
        if device_id:
            device_cache_dir = self.cache_dir / self._sanitize_device_id(device_id)
            if device_cache_dir.exists():
                cache_files = list(device_cache_dir.glob("*.png"))
                total_size = sum(f.stat().st_size for f in cache_files)
                return {
                    "device_id": device_id,
                    "total_icons": len(cache_files),
                    "total_size_bytes": total_size,
                    "total_size_mb": round(total_size / 1024 / 1024, 2),
                    "cache_dir": str(device_cache_dir),
                }

        # All devices
        all_devices = [d for d in self.cache_dir.iterdir() if d.is_dir()]
        total_icons = sum(len(list(d.glob("*.png"))) for d in all_devices)
        total_size = sum(
            sum(f.stat().st_size for f in d.glob("*.png")) for d in all_devices
        )

        return {
            "total_devices": len(all_devices),
            "total_icons": total_icons,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "cache_dir": str(self.cache_dir),
        }

    def clear_cache(self, device_id: str = None, package_name: str = None):
        """
        Clear icon cache

        Args:
            device_id: Clear specific device (if None, clears all devices)
            package_name: Clear specific package (requires device_id)
        """
        if device_id and package_name:
            cache_path = self.cache_dir / device_id / f"{package_name}.png"
            if cache_path.exists():
                cache_path.unlink()
                logger.info(
                    f"[DeviceIconScraper] Cleared cache for {device_id}/{package_name}"
                )
        elif device_id:
            device_cache_dir = self.cache_dir / device_id
            if device_cache_dir.exists():
                for cache_file in device_cache_dir.glob("*.png"):
                    cache_file.unlink()
                logger.info(f"[DeviceIconScraper] Cleared all cache for {device_id}")
        else:
            # Clear all devices
            for device_dir in self.cache_dir.iterdir():
                if device_dir.is_dir():
                    for cache_file in device_dir.glob("*.png"):
                        cache_file.unlink()
            logger.info("[DeviceIconScraper] Cleared all device icon cache")
