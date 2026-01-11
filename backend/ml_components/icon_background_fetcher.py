"""
Visual Mapper - Background Icon Fetcher (Phase 8 Enhancement)
Asynchronously fetches app icons in the background to populate cache

Features:
- Background task queue for icon fetching
- Smart prioritization (Play Store first, APK extraction fallback)
- Non-blocking - returns SVG immediately, fetches real icon async
- Auto-detection of new apps triggers background fetch
"""

import asyncio
import logging
from typing import Optional, Set
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


class IconBackgroundFetcher:
    """
    Background icon fetcher with priority queue

    Strategy:
    1. When icon requested but not in cache, return SVG immediately
    2. Add to background queue (Play Store then APK extraction)
    3. Next request will have cached icon (instant load)
    """

    def __init__(self, playstore_scraper, apk_extractor):
        """
        Initialize background icon fetcher

        Args:
            playstore_scraper: PlayStoreIconScraper instance
            apk_extractor: AppIconExtractor instance
        """
        self.playstore_scraper = playstore_scraper
        self.apk_extractor = apk_extractor

        # Background task queue (device_id, package_name)
        self.queue = deque()
        self.processing: Set[str] = set()  # Currently processing
        self.task = None  # Background worker task
        self.running = False

        logger.info("[IconBackgroundFetcher] Initialized")

    def request_icon(self, device_id: str, package_name: str):
        """
        Request icon to be fetched in background

        Args:
            device_id: ADB device ID (for APK extraction)
            package_name: App package name
        """
        key = f"{device_id}:{package_name}"

        # Skip if already in queue or processing
        if key in self.processing:
            logger.debug(f"[IconBackgroundFetcher] Already processing: {package_name}")
            return

        # Check if already queued
        for item in self.queue:
            if item == (device_id, package_name):
                logger.debug(f"[IconBackgroundFetcher] Already queued: {package_name}")
                return

        # Add to queue
        self.queue.append((device_id, package_name))
        logger.info(f"[IconBackgroundFetcher] Queued: {package_name} (queue size: {len(self.queue)})")

        # Start worker if not running
        if not self.running:
            self.start()

    def start(self):
        """Start background worker task"""
        if self.running:
            logger.debug("[IconBackgroundFetcher] Worker already running")
            return

        self.running = True
        self.task = asyncio.create_task(self._worker())
        logger.info("[IconBackgroundFetcher] Background worker started")

    def stop(self):
        """Stop background worker task"""
        self.running = False
        if self.task:
            self.task.cancel()
        logger.info("[IconBackgroundFetcher] Background worker stopped")

    async def _worker(self):
        """Background worker that processes icon fetch queue"""
        logger.info("[IconBackgroundFetcher] Worker loop started")

        while self.running:
            try:
                # Get next item from queue
                if not self.queue:
                    # Queue empty, sleep and check again
                    await asyncio.sleep(2)
                    continue

                device_id, package_name = self.queue.popleft()
                key = f"{device_id}:{package_name}"

                # Check if wizard is active on this device (affects ADB-based extraction only)
                wizard_active = False
                try:
                    from main import wizard_active_devices
                    wizard_active = device_id in wizard_active_devices
                except ImportError:
                    pass  # wizard_active_devices not available

                # Mark as processing
                self.processing.add(key)

                try:
                    # Pass wizard_active flag - allows Play Store fetch but skips APK extraction
                    await self._fetch_icon(device_id, package_name, skip_adb=wizard_active)
                finally:
                    # Remove from processing
                    self.processing.discard(key)

                # Small delay between fetches to avoid overwhelming the system
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"[IconBackgroundFetcher] Worker error: {e}")
                await asyncio.sleep(1)

        logger.info("[IconBackgroundFetcher] Worker loop stopped")

    async def _fetch_icon(self, device_id: str, package_name: str, skip_adb: bool = False):
        """
        Fetch icon from Play Store or APK extraction

        Args:
            device_id: ADB device ID
            package_name: App package name
            skip_adb: If True, skip APK extraction (ADB busy with wizard)
        """
        logger.debug(f"[IconBackgroundFetcher] Fetching icon: {package_name} (skip_adb={skip_adb})")

        try:
            # Step 1: Try Play Store (fast, high quality, no ADB needed)
            # NOTE: playstore_scraper.get_icon() uses blocking HTTP calls (google_play_scraper + requests)
            # Must run in thread pool to avoid blocking asyncio event loop
            if self.playstore_scraper:
                icon_data = await asyncio.to_thread(self.playstore_scraper.get_icon, package_name)
                if icon_data:
                    logger.info(f"[IconBackgroundFetcher] ✅ Play Store cached: {package_name}")
                    return

            # Step 2: Try APK extraction (slow, requires ADB)
            # NOTE: APK extraction also involves blocking I/O, run in thread
            if self.apk_extractor and not skip_adb:
                icon_data = await asyncio.to_thread(self.apk_extractor.get_icon, device_id, package_name)
                if icon_data:
                    logger.info(f"[IconBackgroundFetcher] ✅ APK extracted: {package_name}")
                    return
            elif skip_adb:
                logger.debug(f"[IconBackgroundFetcher] Skipping APK extraction (wizard active): {package_name}")

            logger.warning(f"[IconBackgroundFetcher] ❌ Failed to fetch icon: {package_name}")

        except Exception as e:
            logger.error(f"[IconBackgroundFetcher] Fetch failed for {package_name}: {e}")

    async def prefetch_all_apps(self, device_id: str, packages: list[str], max_apps: Optional[int] = None):
        """
        Prefetch icons for all apps on device (background batch job)

        Args:
            device_id: ADB device ID
            packages: List of package names
            max_apps: Maximum number of apps to prefetch (None = all)
        """
        logger.info(f"[IconBackgroundFetcher] Prefetching icons for {len(packages)} apps")

        # Add all packages to queue
        packages_to_fetch = packages[:max_apps] if max_apps else packages

        for package_name in packages_to_fetch:
            self.request_icon(device_id, package_name)

        logger.info(f"[IconBackgroundFetcher] Queued {len(packages_to_fetch)} apps for prefetch")

    def get_queue_stats(self) -> dict:
        """Get background queue statistics"""
        return {
            "queue_size": len(self.queue),
            "processing_count": len(self.processing),
            "is_running": self.running
        }
