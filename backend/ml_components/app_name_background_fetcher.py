"""
Visual Mapper - Background App Name Fetcher
Asynchronously fetches real app names from Google Play Store to populate cache

Features:
- Background task queue for app name fetching
- Non-blocking - allows instant app list loading with cached names
- Progress tracking for dev mode display
- Auto-detection of new apps triggers background fetch
"""

import asyncio
import logging
from typing import Optional, Set, Dict
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)


class AppNameBackgroundFetcher:
    """
    Background app name fetcher with priority queue

    Strategy:
    1. When app list loads, use cache-only mode (instant)
    2. Trigger background fetch for uncached apps
    3. Next session will have real names (instant load)
    """

    def __init__(self, playstore_scraper):
        """
        Initialize background app name fetcher

        Args:
            playstore_scraper: PlayStoreIconScraper instance (has get_app_name method)
        """
        self.playstore_scraper = playstore_scraper

        # Background task queue (package_name)
        self.queue = deque()
        self.processing: Set[str] = set()  # Currently processing
        self.completed: Set[str] = set()  # Successfully completed
        self.failed: Set[str] = set()  # Failed to fetch
        self.task = None  # Background worker task
        self.running = False

        # Stats for progress tracking
        self.total_requested = 0
        self.session_start_time = None

        logger.info("[AppNameBackgroundFetcher] Initialized")

    def request_name(self, package_name: str):
        """
        Request app name to be fetched in background

        Args:
            package_name: App package name
        """
        # Skip if already completed or failed
        if package_name in self.completed or package_name in self.failed:
            logger.debug(
                f"[AppNameBackgroundFetcher] Already processed: {package_name}"
            )
            return

        # Skip if already in queue or processing
        if package_name in self.processing:
            logger.debug(
                f"[AppNameBackgroundFetcher] Already processing: {package_name}"
            )
            return

        # Check if already queued
        if package_name in self.queue:
            logger.debug(f"[AppNameBackgroundFetcher] Already queued: {package_name}")
            return

        # Add to queue
        self.queue.append(package_name)
        self.total_requested += 1
        logger.debug(
            f"[AppNameBackgroundFetcher] Queued: {package_name} (queue size: {len(self.queue)})"
        )

        # Start worker if not running
        if not self.running:
            self.start()

    def start(self):
        """Start background worker task"""
        if self.running:
            logger.debug("[AppNameBackgroundFetcher] Worker already running")
            return

        self.running = True
        self.session_start_time = datetime.now()
        self.task = asyncio.create_task(self._worker())
        logger.info("[AppNameBackgroundFetcher] Background worker started")

    def stop(self):
        """Stop background worker task"""
        self.running = False
        if self.task:
            self.task.cancel()
        logger.info("[AppNameBackgroundFetcher] Background worker stopped")

    async def _worker(self):
        """Background worker that processes app name fetch queue"""
        logger.info("[AppNameBackgroundFetcher] Worker loop started")

        while self.running:
            try:
                # Get next item from queue
                if not self.queue:
                    # Queue empty, sleep and check again
                    await asyncio.sleep(2)
                    continue

                package_name = self.queue.popleft()

                # Mark as processing
                self.processing.add(package_name)

                try:
                    success = await self._fetch_name(package_name)
                    if success:
                        self.completed.add(package_name)
                    else:
                        self.failed.add(package_name)
                finally:
                    # Remove from processing
                    self.processing.discard(package_name)

                # Small delay between fetches to avoid overwhelming Play Store
                await asyncio.sleep(1.5)

            except Exception as e:
                logger.error(f"[AppNameBackgroundFetcher] Worker error: {e}")
                await asyncio.sleep(1)

        logger.info("[AppNameBackgroundFetcher] Worker loop stopped")

    async def _fetch_name(self, package_name: str) -> bool:
        """
        Fetch app name from Play Store

        Args:
            package_name: App package name

        Returns:
            True if successful, False otherwise
        """
        logger.debug(f"[AppNameBackgroundFetcher] Fetching name: {package_name}")

        try:
            # Fetch app name (NOT cache_only, this will scrape if needed)
            # NOTE: get_app_name() uses blocking HTTP calls (google_play_scraper + requests)
            # Must run in thread pool to avoid blocking asyncio event loop
            app_name = await asyncio.to_thread(
                self.playstore_scraper.get_app_name,
                package_name,
                False,  # cache_only=False
            )

            if app_name:
                logger.info(
                    f"[AppNameBackgroundFetcher] ✅ Fetched: {package_name} → {app_name}"
                )
                return True
            else:
                logger.warning(
                    f"[AppNameBackgroundFetcher] ❌ No name found: {package_name}"
                )
                return False

        except Exception as e:
            logger.error(
                f"[AppNameBackgroundFetcher] Fetch failed for {package_name}: {e}"
            )
            return False

    async def prefetch_all_apps(
        self, packages: list[str], max_apps: Optional[int] = None
    ):
        """
        Prefetch app names for all apps (background batch job)

        Args:
            packages: List of package names
            max_apps: Maximum number of apps to prefetch (None = all)
        """
        logger.info(
            f"[AppNameBackgroundFetcher] Prefetching names for {len(packages)} apps"
        )

        # Add all packages to queue
        packages_to_fetch = packages[:max_apps] if max_apps else packages

        for package_name in packages_to_fetch:
            self.request_name(package_name)

        logger.info(
            f"[AppNameBackgroundFetcher] Queued {len(packages_to_fetch)} apps for prefetch"
        )

    def get_queue_stats(self) -> dict:
        """
        Get background queue statistics

        Returns:
            {
                "queue_size": 45,
                "processing_count": 1,
                "completed_count": 120,
                "failed_count": 5,
                "total_requested": 165,
                "progress_percentage": 75.8,
                "is_running": true
            }
        """
        completed_count = len(self.completed)
        failed_count = len(self.failed)
        total_processed = completed_count + failed_count

        progress_percentage = 0.0
        if self.total_requested > 0:
            progress_percentage = round(
                (total_processed / self.total_requested) * 100, 1
            )

        return {
            "queue_size": len(self.queue),
            "processing_count": len(self.processing),
            "completed_count": completed_count,
            "failed_count": failed_count,
            "total_requested": self.total_requested,
            "progress_percentage": progress_percentage,
            "is_running": self.running,
        }

    def reset_stats(self):
        """Reset session statistics (for new fetch session)"""
        self.queue.clear()
        self.processing.clear()
        self.completed.clear()
        self.failed.clear()
        self.total_requested = 0
        self.session_start_time = None
        logger.info("[AppNameBackgroundFetcher] Stats reset")
