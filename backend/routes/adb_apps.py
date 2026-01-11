"""
ADB App Management Routes - App Installation and Control

Provides endpoints for managing apps on Android devices:
- List installed apps
- Get app icons (with multi-tier caching)
- Launch apps
- Stop/force-close apps
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
import time
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adb", tags=["adb_apps"])


# Request models
class LaunchAppRequest(BaseModel):
    device_id: str
    package: str
    force_restart: bool = False  # If True, force-stop app before launching


class StopAppRequest(BaseModel):
    device_id: str
    package: str


# =============================================================================
# APP INFO ENDPOINTS
# =============================================================================


@router.get("/apps/{device_id}")
async def get_installed_apps(device_id: str):
    """Get list of installed apps on device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Getting installed apps for {device_id}")
        apps = await deps.adb_bridge.get_installed_apps(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "apps": apps,
            "count": len(apps),
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Get apps failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/app-icon/{device_id}/{package_name}")
async def get_app_icon(
    device_id: str, package_name: str, skip_extraction: bool = False
):
    """
    Get app icon - multi-tier approach for optimal performance

    Multi-Tier Loading Strategy (prioritized by quality):
    0. Play Store cache - INSTANT + BEST QUALITY (authoritative, high-res)
    1. APK extraction cache - INSTANT (extracted from APK)
    2. Device-specific cache - INSTANT (screenshot crop fallback)
    3. Background fetch + SVG fallback - INSTANT response while fetching

    Args:
        device_id: ADB device ID
        package_name: App package name
        skip_extraction: If true, skip slow methods and return SVG

    Returns:
        Icon image data (PNG/WebP/SVG)
    """
    from fastapi.responses import Response

    deps = get_deps()

    # Tier 0: Check Play Store cache (INSTANT + BEST QUALITY)
    # Play Store icons are high quality, properly sized, and authoritative
    # Always check the cache directory - icons may exist even if scraper isn't initialized
    from pathlib import Path

    playstore_cache = Path(f"data/app-icons-playstore/{package_name}.png")
    if playstore_cache.exists():
        icon_data = playstore_cache.read_bytes()
        logger.debug(f"[API] Tier 0: Play Store cache hit for {package_name}")
        return Response(
            content=icon_data,
            media_type="image/png",
            headers={"X-Icon-Source": "playstore"},
        )

    # Tier 1: Check APK extraction cache (INSTANT)
    # Always check the cache directory - icons may exist even if extractor isn't initialized
    import glob

    apk_cache_pattern = f"data/app-icons/{package_name}_*.png"
    apk_caches = glob.glob(apk_cache_pattern)
    if apk_caches:
        icon_data = Path(apk_caches[0]).read_bytes()
        logger.debug(f"[API] Tier 1: APK cache hit for {package_name}")
        return Response(
            content=icon_data,
            media_type="image/png",
            headers={"X-Icon-Source": "apk-extraction"},
        )

    # Tier 2: Check device-specific cache (INSTANT but lower quality)
    # Device scraper crops from screenshots - use as fallback only for apps not on Play Store
    if deps.device_icon_scraper:
        icon_data = deps.device_icon_scraper.get_icon(device_id, package_name)
        if icon_data:
            logger.debug(f"[API] Tier 2: Device scraper cache hit for {package_name}")
            return Response(
                content=icon_data,
                media_type="image/png",
                headers={"X-Icon-Source": "device-scraper"},
            )

    # Tier 3: Not in cache - Trigger background fetch and return SVG immediately
    # Background fetch will populate cache for next request (smart progressive loading)
    if deps.icon_background_fetcher and not skip_extraction:
        deps.icon_background_fetcher.request_icon(device_id, package_name)
        logger.debug(f"[API] Tier 3: Background fetch requested for {package_name}")

    # Tier 4: SVG fallback (INSTANT - return immediately while background fetch happens)
    first_letter = package_name.split(".")[-1][0].upper() if package_name else "A"
    hash_val = hash(package_name) % 360
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
        <rect width="48" height="48" fill="hsl({hash_val}, 70%, 60%)" rx="8"/>
        <text x="24" y="32" font-family="Arial, sans-serif" font-size="24" font-weight="bold"
              fill="white" text-anchor="middle">{first_letter}</text>
    </svg>"""
    logger.debug(
        f"[API] Tier 4: SVG fallback for {package_name} (background fetch in progress)"
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"X-Icon-Source": "svg-placeholder"},
    )


# =============================================================================
# APP CONTROL ENDPOINTS
# =============================================================================


@router.post("/launch")
async def launch_app(request: LaunchAppRequest):
    """
    Launch an app by package name

    Args:
        device_id: ADB device ID
        package: App package name
        force_restart: If True, force-stop the app first for a fresh start
    """
    deps = get_deps()
    try:
        # Force-stop first if requested (ensures fresh app start)
        if request.force_restart:
            logger.info(
                f"[API] Force-stopping {request.package} before launch (fresh start)"
            )
            try:
                await deps.adb_bridge.stop_app(request.device_id, request.package)
                # Brief pause to let the app fully stop
                import asyncio

                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"[API] Force-stop failed (continuing with launch): {e}")

        logger.info(f"[API] Launching {request.package} on {request.device_id}")
        success = await deps.adb_bridge.launch_app(request.device_id, request.package)

        return {
            "success": success,
            "device_id": request.device_id,
            "package": request.package,
            "force_restart": request.force_restart,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Launch app failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop-app")
async def stop_app(request: StopAppRequest):
    """Force stop an app by package name"""
    deps = get_deps()
    try:
        logger.info(f"[API] Force stopping {request.package} on {request.device_id}")
        success = await deps.adb_bridge.stop_app(request.device_id, request.package)

        return {
            "success": success,
            "device_id": request.device_id,
            "package": request.package,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Stop app failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ICON MANAGEMENT ENDPOINTS
# =============================================================================


@router.post("/prefetch-icons/{device_id}")
async def prefetch_app_icons(device_id: str, max_apps: Optional[int] = None):
    """
    Prefetch app icons in background (Play Store + APK extraction)

    This triggers background fetching for all apps on the device.
    Icons load instantly from cache on subsequent requests.

    Args:
        device_id: ADB device ID
        max_apps: Maximum number of apps to prefetch (None = all)

    Returns:
        {
            "success": true,
            "apps_queued": 375,
            "queue_stats": {...}
        }
    """
    deps = get_deps()
    try:
        if not deps.icon_background_fetcher:
            raise HTTPException(
                status_code=500, detail="Background icon fetcher not initialized"
            )

        logger.info(f"[API] Starting background icon prefetch for {device_id}")

        # Get list of installed apps
        apps = await deps.adb_bridge.get_installed_apps(device_id)
        packages = [app["package"] for app in apps]

        # Queue all apps for background fetch
        await deps.icon_background_fetcher.prefetch_all_apps(
            device_id, packages, max_apps
        )

        queue_stats = deps.icon_background_fetcher.get_queue_stats()

        logger.info(
            f"[API] ✅ Queued {len(packages[:max_apps] if max_apps else packages)} apps for prefetch"
        )

        return {
            "success": True,
            "apps_queued": len(packages[:max_apps] if max_apps else packages),
            "total_apps": len(packages),
            "queue_stats": queue_stats,
        }

    except Exception as e:
        logger.error(f"[API] Icon prefetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Icon prefetch failed: {str(e)}")


@router.get("/icon-queue-stats")
async def get_icon_queue_stats():
    """
    Get background icon fetching queue statistics

    Returns:
        {
            "queue_size": 45,
            "processing_count": 1,
            "is_running": true
        }
    """
    deps = get_deps()
    try:
        if not deps.icon_background_fetcher:
            raise HTTPException(
                status_code=500, detail="Background icon fetcher not initialized"
            )

        stats = deps.icon_background_fetcher.get_queue_stats()
        return stats

    except Exception as e:
        logger.error(f"[API] Failed to get queue stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get queue stats: {str(e)}"
        )


@router.get("/app-name-queue-stats")
async def get_app_name_queue_stats():
    """
    Get background app name fetching queue statistics

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
    deps = get_deps()
    try:
        if not deps.app_name_background_fetcher:
            raise HTTPException(
                status_code=500, detail="Background app name fetcher not initialized"
            )

        stats = deps.app_name_background_fetcher.get_queue_stats()
        return stats

    except Exception as e:
        logger.error(f"[API] Failed to get app name queue stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get app name queue stats: {str(e)}"
        )


@router.post("/prefetch-app-names/{device_id}")
async def prefetch_app_names(device_id: str, max_apps: Optional[int] = None):
    """
    Prefetch real app names from Google Play Store (background job)

    This should be triggered when device is selected in Flow Wizard to populate
    the app name cache silently in the background.

    Strategy:
    - Returns immediately (non-blocking)
    - Fetches names in background over ~5-10 minutes
    - Names appear in cache for next session
    - Progress visible in dev mode via /api/adb/app-name-queue-stats

    Args:
        device_id: ADB device ID
        max_apps: Maximum number of apps to prefetch (None = all)

    Returns:
        {
            "success": true,
            "queued_count": 165,
            "stats": {...}
        }
    """
    deps = get_deps()
    try:
        if not deps.app_name_background_fetcher:
            raise HTTPException(
                status_code=500, detail="Background app name fetcher not initialized"
            )

        logger.info(f"[API] Starting app name prefetch for {device_id}")

        # Get list of installed apps (returns list of dicts with 'package' key)
        apps = await deps.adb_bridge.get_installed_apps(device_id)
        packages = [app["package"] for app in apps]

        # Queue app name prefetch (non-blocking)
        await deps.app_name_background_fetcher.prefetch_all_apps(packages, max_apps)

        # Get stats
        stats = deps.app_name_background_fetcher.get_queue_stats()

        logger.info(
            f"[API] ✅ Queued {stats['total_requested']} apps for name prefetch"
        )

        return {
            "success": True,
            "queued_count": stats["total_requested"],
            "stats": stats,
        }

    except Exception as e:
        logger.error(f"[API] App name prefetch failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"App name prefetch failed: {str(e)}"
        )


@router.post("/scrape-device-icons/{device_id}")
async def scrape_device_icons(device_id: str, max_apps: Optional[int] = None):
    """
    Scrape app icons from device app drawer (device onboarding)

    This should be triggered:
    1. During device onboarding (first time setup)
    2. When new apps are detected on the device
    3. Manually by user if icons need refresh

    Args:
        device_id: ADB device ID
        max_apps: Maximum number of apps to scrape (None = all)

    Returns:
        {
            "success": true,
            "icons_scraped": 42,
            "total_apps": 120,
            "cache_stats": {...}
        }
    """
    deps = get_deps()
    try:
        if not deps.device_icon_scraper:
            raise HTTPException(
                status_code=500, detail="Device icon scraper not initialized"
            )

        logger.info(f"[API] Starting device icon scraping for {device_id}")

        # Scrape icons from device
        icons_scraped = await deps.device_icon_scraper.scrape_device_icons(
            device_id, max_apps
        )

        # Get cache stats
        cache_stats = deps.device_icon_scraper.get_cache_stats(device_id)

        logger.info(f"[API] ✅ Scraped {icons_scraped} icons from {device_id}")

        return {
            "success": True,
            "icons_scraped": icons_scraped,
            "cache_stats": cache_stats,
        }
    except Exception as e:
        logger.error(f"[API] Device icon scraping failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check-icon-cache/{device_id}")
async def check_icon_cache(device_id: str):
    """
    Check if device icon cache needs updating (new apps detected)

    Returns:
        {
            "needs_update": true/false,
            "cache_stats": {...},
            "new_apps_count": 5
        }
    """
    deps = get_deps()
    try:
        if not deps.device_icon_scraper:
            raise HTTPException(
                status_code=500, detail="Device icon scraper not initialized"
            )

        # Get installed apps
        apps = await deps.adb_bridge.get_installed_apps(device_id)
        app_packages = [app["package"] for app in apps]

        # Check if update needed
        needs_update = deps.device_icon_scraper.should_update(device_id, app_packages)

        # Get cache stats
        cache_stats = deps.device_icon_scraper.get_cache_stats(device_id)

        # Calculate new apps count
        from pathlib import Path

        safe_device_id = device_id.replace(":", "_")
        device_cache_dir = Path(f"data/device-icons/{safe_device_id}")
        cached_packages = (
            {f.stem for f in device_cache_dir.glob("*.png")}
            if device_cache_dir.exists()
            else set()
        )
        new_apps_count = len(set(app_packages) - cached_packages)

        return {
            "needs_update": needs_update,
            "cache_stats": cache_stats,
            "new_apps_count": new_apps_count,
            "total_apps": len(app_packages),
        }
    except Exception as e:
        logger.error(f"[API] Check icon cache failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/icon-cache-stats")
async def get_icon_cache_stats(device_id: Optional[str] = None):
    """
    Get icon cache statistics for all scrapers

    Args:
        device_id: Optional device ID for device-specific stats

    Returns:
        {
            "device_scraper": {...},
            "playstore_scraper": {...},
            "apk_extractor": {...}
        }
    """
    deps = get_deps()
    try:
        stats = {}

        # Device scraper stats
        if deps.device_icon_scraper:
            stats["device_scraper"] = deps.device_icon_scraper.get_cache_stats(
                device_id
            )

        # Play Store scraper stats
        if deps.playstore_icon_scraper:
            stats["playstore_scraper"] = deps.playstore_icon_scraper.get_cache_stats()

        # APK extractor stats
        if deps.app_icon_extractor:
            stats["apk_extractor"] = deps.app_icon_extractor.get_cache_stats()

        return stats
    except Exception as e:
        logger.error(f"[API] Get icon cache stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
