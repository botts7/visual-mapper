"""
Visual Mapper - App Icon Extractor (Phase 8 Enhancement)
Extracts real app icons from Android devices via ADB

Features:
- Extracts icons from APKs on device
- Local persistent cache (data/app-icons/)
- Fallback to SVG if extraction fails
- Toggle via ENABLE_REAL_ICONS config flag
"""

import os
import logging
import hashlib
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AppIconExtractor:
    """
    Extracts real app icons from Android devices

    Strategy:
    1. Get APK path from device
    2. Pull APK to temp location
    3. Extract icon from APK (it's a ZIP file)
    4. Cache locally
    5. Return PNG data
    """

    def __init__(self, cache_dir: str = "data/app-icons", enable_extraction: bool = True):
        """
        Initialize icon extractor

        Args:
            cache_dir: Directory to cache extracted icons
            enable_extraction: Enable real icon extraction (if False, returns None)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.enable_extraction = enable_extraction

        logger.info(f"[AppIconExtractor] Initialized (cache: {cache_dir}, enabled: {enable_extraction})")

    def get_icon(self, device_id: str, package_name: str) -> Optional[bytes]:
        """
        Get app icon (cached or extracted)

        Args:
            device_id: ADB device ID
            package_name: App package name

        Returns:
            PNG icon data or None if extraction disabled/failed
        """
        if not self.enable_extraction:
            logger.debug(f"[AppIconExtractor] Extraction disabled, returning None for {package_name}")
            return None

        # Check cache first
        cache_path = self._get_cache_path(package_name)
        if cache_path.exists():
            logger.debug(f"[AppIconExtractor] Cache hit for {package_name}")
            return cache_path.read_bytes()

        # Extract from device
        try:
            icon_data = self._extract_icon_from_device(device_id, package_name)
            if icon_data:
                # Save to cache
                cache_path.write_bytes(icon_data)
                logger.info(f"[AppIconExtractor] Extracted and cached icon for {package_name} ({len(icon_data)} bytes)")
                return icon_data
        except Exception as e:
            logger.warning(f"[AppIconExtractor] Failed to extract icon for {package_name}: {e}")

        return None

    def _get_cache_path(self, package_name: str) -> Path:
        """Get cache file path for package"""
        # Use hash to avoid filename issues with special characters
        safe_name = hashlib.md5(package_name.encode()).hexdigest()
        return self.cache_dir / f"{package_name}_{safe_name}.png"

    def _extract_icon_from_device(self, device_id: str, package_name: str) -> Optional[bytes]:
        """
        Extract icon from APK on device

        Steps:
        1. Get APK path from package manager
        2. Pull APK to temp file
        3. Extract icon from APK ZIP
        4. Return PNG data
        """
        try:
            # 1. Get APK path
            apk_path = self._get_apk_path(device_id, package_name)
            if not apk_path:
                logger.warning(f"[AppIconExtractor] Could not find APK path for {package_name}")
                return None

            # 2. Pull APK to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.apk') as tmp_apk:
                tmp_apk_path = tmp_apk.name

            try:
                self._pull_apk(device_id, apk_path, tmp_apk_path)

                # 3. Extract icon from APK
                icon_data = self._extract_icon_from_apk(tmp_apk_path, package_name)
                return icon_data

            finally:
                # Clean up temp file
                try:
                    os.unlink(tmp_apk_path)
                except:
                    pass

        except Exception as e:
            logger.error(f"[AppIconExtractor] Extraction failed for {package_name}: {e}")
            return None

    def _get_apk_path(self, device_id: str, package_name: str) -> Optional[str]:
        """Get APK path from device using pm path"""
        try:
            result = subprocess.run(
                ['adb', '-s', device_id, 'shell', 'pm', 'path', package_name],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0 and result.stdout:
                # Output can be multiple lines for split APKs:
                # package:/data/app/.../base.apk
                # package:/data/app/.../split_config.arm64_v8a.apk
                # ...
                # We only need base.apk which contains the icon
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line.startswith('package:'):
                        path = line[8:].strip()  # Remove "package:" prefix
                        # Prefer base.apk, fallback to first APK
                        if 'base.apk' in path:
                            return path

                # If no base.apk found, use first APK path
                if lines and lines[0].startswith('package:'):
                    return lines[0][8:].strip()

        except Exception as e:
            logger.error(f"[AppIconExtractor] Failed to get APK path: {e}")

        return None

    def _pull_apk(self, device_id: str, apk_path: str, dest_path: str):
        """Pull APK from device"""
        result = subprocess.run(
            ['adb', '-s', device_id, 'pull', apk_path, dest_path],
            capture_output=True,
            timeout=30
        )

        if result.returncode != 0:
            raise Exception(f"Failed to pull APK: {result.stderr.decode()}")

    def _extract_icon_from_apk(self, apk_path: str, package_name: str) -> Optional[bytes]:
        """
        Extract icon from APK (ZIP file)

        Enhanced Strategy:
        1. Try common icon paths in order of preference (highest density first)
        2. Support multiple formats: PNG, WebP
        3. Try round icons, foreground layers, standard icons
        4. Handle adaptive icons (parse XML to find actual drawables)
        5. Comprehensive fallback search if specific paths fail
        """
        # Densities in order of preference (highest quality first)
        densities = ['xxxhdpi', 'xxhdpi', 'xhdpi', 'hdpi', 'mdpi', 'anydpi-v26']

        # Icon names to try (in order of preference)
        icon_names = [
            'ic_launcher_round',      # Round icons (often better looking)
            'ic_launcher_foreground', # Adaptive icon foreground
            'ic_launcher',            # Standard launcher icon
        ]

        # Directories to search
        directories = ['mipmap', 'drawable']

        # File extensions to try
        extensions = ['.png', '.webp']

        # Build comprehensive path list
        icon_paths = []

        for density in densities:
            for directory in directories:
                for icon_name in icon_names:
                    for ext in extensions:
                        # Try with -v4 suffix (versioned resources)
                        if density != 'anydpi-v26':
                            icon_paths.append(f'res/{directory}-{density}-v4/{icon_name}{ext}')

                        # Try without -v4 suffix
                        icon_paths.append(f'res/{directory}-{density}/{icon_name}{ext}')

        try:
            with zipfile.ZipFile(apk_path, 'r') as apk_zip:
                # Get all files in APK
                all_files = apk_zip.namelist()

                logger.debug(f"[AppIconExtractor] Searching {len(icon_paths)} icon paths for {package_name}")

                # Try each specific icon path
                for icon_path in icon_paths:
                    if icon_path in all_files:
                        logger.info(f"[AppIconExtractor] ✅ Found icon at {icon_path}")
                        return apk_zip.read(icon_path)

                # Fallback 1: Check for adaptive icon XML and extract foreground layer
                logger.debug(f"[AppIconExtractor] Specific paths failed, checking for adaptive icon XML...")
                adaptive_icon_data = self._extract_adaptive_icon(apk_zip, all_files, package_name)
                if adaptive_icon_data:
                    logger.info(f"[AppIconExtractor] ✅ Extracted adaptive icon foreground for {package_name}")
                    return adaptive_icon_data

                # Fallback 2: Search for any ic_launcher variant (PNG or WebP)
                logger.debug(f"[AppIconExtractor] Adaptive icon failed, trying pattern search...")
                for file_path in all_files:
                    if ('ic_launcher' in file_path and
                        (file_path.endswith('.png') or file_path.endswith('.webp'))):
                        logger.info(f"[AppIconExtractor] ✅ Found icon via pattern search: {file_path}")
                        return apk_zip.read(file_path)

                # Fallback 3: Search for any file named 'icon' in mipmap/drawable
                logger.debug(f"[AppIconExtractor] Pattern search failed, trying generic icon search...")
                for file_path in all_files:
                    if (('mipmap' in file_path or 'drawable' in file_path) and
                        'icon' in file_path.lower() and
                        (file_path.endswith('.png') or file_path.endswith('.webp'))):
                        logger.info(f"[AppIconExtractor] ✅ Found icon via generic search: {file_path}")
                        return apk_zip.read(file_path)

                # Log which files ARE in the APK to help debug
                icon_related_files = [f for f in all_files if 'launcher' in f or 'icon' in f.lower()]
                if icon_related_files:
                    logger.warning(f"[AppIconExtractor] ❌ No extractable icon found for {package_name}. Icon-related files: {icon_related_files[:10]}")
                else:
                    logger.warning(f"[AppIconExtractor] ❌ No icon-related files found in APK for {package_name}")

        except Exception as e:
            logger.error(f"[AppIconExtractor] ❌ Failed to extract icon from APK: {e}")

        return None

    def _extract_adaptive_icon(self, apk_zip: zipfile.ZipFile, all_files: list, package_name: str) -> Optional[bytes]:
        """
        Extract foreground layer from adaptive icon XML

        Adaptive icons (API 26+) are defined in XML like:
        <adaptive-icon>
            <background android:drawable="@drawable/ic_launcher_background"/>
            <foreground android:drawable="@drawable/ic_launcher_foreground"/>
        </adaptive-icon>

        This method finds the XML, parses it, and extracts the foreground drawable
        """
        try:
            # Find adaptive icon XML files
            adaptive_xml_paths = [
                'res/mipmap-anydpi-v26/ic_launcher.xml',
                'res/mipmap-anydpi-v26/ic_launcher_round.xml',
            ]

            for xml_path in adaptive_xml_paths:
                if xml_path in all_files:
                    logger.debug(f"[AppIconExtractor] Found adaptive icon XML: {xml_path}")

                    # Read and parse XML
                    xml_content = apk_zip.read(xml_path).decode('utf-8', errors='ignore')

                    # Extract foreground drawable reference (simple regex - not full XML parsing)
                    # Example: <foreground android:drawable="@drawable/ic_launcher_foreground"/>
                    import re
                    foreground_match = re.search(r'<foreground[^>]*android:drawable="@([^"]+)"', xml_content)

                    if foreground_match:
                        drawable_ref = foreground_match.group(1)  # e.g., "drawable/ic_launcher_foreground"
                        logger.debug(f"[AppIconExtractor] Adaptive icon foreground: {drawable_ref}")

                        # Try to find the actual drawable file (PNG/WebP)
                        # Search in different densities
                        for density in ['xxxhdpi', 'xxhdpi', 'xhdpi', 'hdpi', 'mdpi']:
                            drawable_name = drawable_ref.split('/')[-1]  # Get just the filename
                            drawable_dir = drawable_ref.split('/')[0] if '/' in drawable_ref else 'drawable'

                            for ext in ['.png', '.webp']:
                                possible_path = f'res/{drawable_dir}-{density}/{drawable_name}{ext}'
                                if possible_path in all_files:
                                    logger.info(f"[AppIconExtractor] ✅ Found adaptive foreground at {possible_path}")
                                    return apk_zip.read(possible_path)

                        # Try without density suffix
                        for ext in ['.png', '.webp']:
                            possible_path = f'res/{drawable_ref}{ext}'
                            if possible_path in all_files:
                                logger.info(f"[AppIconExtractor] ✅ Found adaptive foreground at {possible_path}")
                                return apk_zip.read(possible_path)

        except Exception as e:
            logger.debug(f"[AppIconExtractor] Adaptive icon extraction failed: {e}")

        return None

    def clear_cache(self, package_name: Optional[str] = None):
        """
        Clear icon cache

        Args:
            package_name: Clear specific package (if None, clears all)
        """
        if package_name:
            cache_path = self._get_cache_path(package_name)
            if cache_path.exists():
                cache_path.unlink()
                logger.info(f"[AppIconExtractor] Cleared cache for {package_name}")
        else:
            # Clear all cached icons
            for cache_file in self.cache_dir.glob("*.png"):
                cache_file.unlink()
            logger.info("[AppIconExtractor] Cleared all icon cache")

    def get_cache_size(self) -> int:
        """Get total cache size in bytes"""
        total_size = sum(f.stat().st_size for f in self.cache_dir.glob("*.png"))
        return total_size

    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        cache_files = list(self.cache_dir.glob("*.png"))
        total_size = sum(f.stat().st_size for f in cache_files)

        return {
            "total_icons": len(cache_files),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "cache_dir": str(self.cache_dir)
        }
