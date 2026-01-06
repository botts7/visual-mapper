"""
Visual Mapper - Play Store Icon Scraper (Phase 8 Enhancement)
Scrapes app icons AND names from Google Play Store for instant loading

Features:
- On-demand scraping from Play Store
- Local persistent cache (data/app-icons-playstore/)
- App name extraction and caching
- Batch scraping for top apps
- Fallback for apps not on Play Store
"""

import os
import logging
import requests
import json
from pathlib import Path
from typing import Optional, Tuple
from google_play_scraper import app as get_app_details

logger = logging.getLogger(__name__)


class PlayStoreIconScraper:
    """
    Scrapes app icons and names from Google Play Store

    Strategy:
    1. Check if icon/name exists in local cache
    2. If not cached, fetch from Play Store API
    3. Download icon from URL and extract app name
    4. Cache both locally
    5. Return icon data and app name
    """

    def __init__(self, cache_dir: str = "data/app-icons-playstore"):
        """
        Initialize Play Store icon scraper

        Args:
            cache_dir: Directory to cache downloaded icons and metadata
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Create metadata cache directory
        self.metadata_dir = self.cache_dir / "metadata"
        self.metadata_dir.mkdir(exist_ok=True)

        logger.info(f"[PlayStoreIconScraper] Initialized (cache: {cache_dir})")

    def get_icon(self, package_name: str) -> Optional[bytes]:
        """
        Get app icon from Play Store (cached or downloaded)

        Args:
            package_name: App package name (e.g., com.netflix.mediaclient)

        Returns:
            Icon image data (PNG/WebP) or None if not found
        """
        # Check cache first
        cache_path = self._get_cache_path(package_name)
        if cache_path.exists():
            logger.debug(f"[PlayStoreIconScraper] Cache hit for {package_name}")
            return cache_path.read_bytes()

        # Scrape from Play Store (also caches app name)
        try:
            icon_data, app_name = self._scrape_icon_and_name(package_name)
            if icon_data:
                # Save icon to cache
                cache_path.write_bytes(icon_data)
                logger.info(f"[PlayStoreIconScraper] ✅ Scraped and cached icon for {package_name} ({len(icon_data)} bytes)")

                # Save app name to metadata cache
                if app_name:
                    self._cache_app_name(package_name, app_name)

                return icon_data
        except Exception as e:
            logger.warning(f"[PlayStoreIconScraper] ❌ Failed to scrape icon for {package_name}: {e}")

        return None

    def _get_cache_path(self, package_name: str) -> Path:
        """Get cache file path for package"""
        # Use package name directly (safe for filenames)
        return self.cache_dir / f"{package_name}.png"

    def _scrape_icon_and_name(self, package_name: str) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Scrape icon and app name from Play Store

        Steps:
        1. Get app details from Play Store API
        2. Extract icon URL and app title
        3. Download icon
        4. Return image data and app name

        Returns:
            Tuple of (icon_data, app_name)
        """
        try:
            # Get app details from Play Store
            logger.debug(f"[PlayStoreIconScraper] Fetching details for {package_name}")
            details = get_app_details(package_name, lang='en', country='us')

            if not details:
                logger.warning(f"[PlayStoreIconScraper] No details found for {package_name}")
                return None, None

            # Extract app name
            app_name = details.get('title')
            if app_name:
                logger.debug(f"[PlayStoreIconScraper] App name: {app_name}")

            # Extract icon URL
            icon_url = details.get('icon')
            if not icon_url:
                logger.warning(f"[PlayStoreIconScraper] No icon URL found for {package_name}")
                return None, app_name

            logger.debug(f"[PlayStoreIconScraper] Icon URL: {icon_url}")

            # Download icon
            response = requests.get(icon_url, timeout=10)
            response.raise_for_status()

            # Return icon data and app name
            return response.content, app_name

        except Exception as e:
            logger.error(f"[PlayStoreIconScraper] Failed to scrape icon/name for {package_name}: {e}")
            return None, None

    def get_app_name(self, package_name: str, cache_only: bool = False) -> Optional[str]:
        """
        Get app name from Play Store (cached or scraped)

        Args:
            package_name: App package name
            cache_only: If True, only return cached names (don't scrape)

        Returns:
            Human-readable app name or None if not found
        """
        # Check metadata cache first
        cached_name = self._get_cached_app_name(package_name)
        if cached_name:
            logger.debug(f"[PlayStoreIconScraper] Name cache hit for {package_name}: {cached_name}")
            return cached_name

        # If cache_only mode, return None if not cached
        if cache_only:
            return None

        # Scrape from Play Store
        try:
            _, app_name = self._scrape_icon_and_name(package_name)
            if app_name:
                # Save to metadata cache
                self._cache_app_name(package_name, app_name)
                logger.info(f"[PlayStoreIconScraper] ✅ Scraped app name for {package_name}: {app_name}")
                return app_name
        except Exception as e:
            logger.warning(f"[PlayStoreIconScraper] ❌ Failed to scrape app name for {package_name}: {e}")

        return None

    def _get_cached_app_name(self, package_name: str) -> Optional[str]:
        """Get cached app name from metadata"""
        metadata_path = self.metadata_dir / f"{package_name}.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    return metadata.get('title')
            except Exception as e:
                logger.debug(f"[PlayStoreIconScraper] Failed to read metadata cache: {e}")
        return None

    def _cache_app_name(self, package_name: str, app_name: str):
        """Cache app name to metadata"""
        metadata_path = self.metadata_dir / f"{package_name}.json"
        try:
            metadata = {
                'title': app_name,
                'package': package_name
            }
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            logger.debug(f"[PlayStoreIconScraper] Cached app name: {package_name} -> {app_name}")
        except Exception as e:
            logger.warning(f"[PlayStoreIconScraper] Failed to cache app name: {e}")

    def batch_scrape(self, package_names: list[str], max_apps: Optional[int] = None) -> int:
        """
        Batch scrape icons for multiple apps

        Args:
            package_names: List of package names to scrape
            max_apps: Maximum number of apps to scrape (None = all)

        Returns:
            Number of icons successfully scraped
        """
        success_count = 0
        total = min(len(package_names), max_apps) if max_apps else len(package_names)

        for i, package_name in enumerate(package_names[:max_apps] if max_apps else package_names):
            try:
                icon_data = self.get_icon(package_name)
                if icon_data:
                    success_count += 1
                    logger.info(f"[PlayStoreIconScraper] {i+1}/{total}: ✅ {package_name}")
                else:
                    logger.warning(f"[PlayStoreIconScraper] {i+1}/{total}: ❌ {package_name} (not found)")
            except Exception as e:
                logger.error(f"[PlayStoreIconScraper] {i+1}/{total}: ❌ {package_name} ({e})")

        logger.info(f"[PlayStoreIconScraper] Batch complete: {success_count}/{total} icons scraped")
        return success_count

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
                logger.info(f"[PlayStoreIconScraper] Cleared cache for {package_name}")
        else:
            # Clear all cached icons
            for cache_file in self.cache_dir.glob("*.png"):
                cache_file.unlink()
            logger.info("[PlayStoreIconScraper] Cleared all Play Store icon cache")

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
