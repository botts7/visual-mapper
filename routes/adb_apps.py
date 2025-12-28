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
import logging
import time
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adb", tags=["adb_apps"])


# Request models
class LaunchAppRequest(BaseModel):
    device_id: str
    package: str


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
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Get apps failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/app-icon/{device_id}/{package_name}")
async def get_app_icon(device_id: str, package_name: str, skip_extraction: bool = False):
    """
    Get app icon - multi-tier approach for optimal performance

    Multi-Tier Loading Strategy:
    0. Device-specific cache (scraped from device) - INSTANT + BEST QUALITY
    1. Play Store cache (pre-populated/scraped) - INSTANT
    2. APK extraction cache (previously extracted) - INSTANT
    3. If skip_extraction=true: Return SVG immediately - INSTANT
    4. Play Store scrape (on-demand) - 1-2 seconds
    5. APK extraction (for system/OEM apps) - 10-30 seconds
    6. SVG fallback - INSTANT

    Args:
        device_id: ADB device ID
        package_name: App package name
        skip_extraction: If true, skip slow methods (scraping/extraction) and return SVG

    Returns:
        Icon image data (PNG/WebP/SVG)
    """
    from fastapi.responses import Response
    deps = get_deps()

    # Tier 0: Check device-specific cache (INSTANT + BEST QUALITY)
    # This is scraped from the actual device app drawer, so it respects:
    # - User's launcher theme
    # - Adaptive icons (rendered correctly)
    # - Custom icon packs
    # - OEM customizations
    if deps.device_icon_scraper:
        icon_data = deps.device_icon_scraper.get_icon(device_id, package_name)
        if icon_data:
            logger.debug(f"[API] Tier 0: Device-specific cache hit for {package_name}")
            return Response(content=icon_data, media_type="image/png", headers={"X-Icon-Source": "device-scraper"})

    # Tier 1: Check Play Store cache (INSTANT)
    if deps.playstore_icon_scraper:
        from pathlib import Path
        playstore_cache = Path(f"data/app-icons-playstore/{package_name}.png")
        if playstore_cache.exists():
            icon_data = playstore_cache.read_bytes()
            logger.debug(f"[API] Tier 1: Play Store cache hit for {package_name}")
            return Response(content=icon_data, media_type="image/png", headers={"X-Icon-Source": "playstore"})

    # Tier 2: Check APK extraction cache (INSTANT)
    if deps.app_icon_extractor:
        from pathlib import Path
        import glob
        apk_cache_pattern = f"data/app-icons/{package_name}_*.png"
        apk_caches = glob.glob(apk_cache_pattern)
        if apk_caches:
            icon_data = Path(apk_caches[0]).read_bytes()
            logger.debug(f"[API] Tier 2: APK cache hit for {package_name}")
            return Response(content=icon_data, media_type="image/png", headers={"X-Icon-Source": "apk-extraction"})

    # Tier 3: Not in cache - Trigger background fetch and return SVG immediately
    # Background fetch will populate cache for next request (smart progressive loading)
    if deps.icon_background_fetcher and not skip_extraction:
        deps.icon_background_fetcher.request_icon(device_id, package_name)
        logger.debug(f"[API] Tier 3: Background fetch requested for {package_name}")

    # Tier 4: SVG fallback (INSTANT - return immediately while background fetch happens)
    first_letter = package_name.split('.')[-1][0].upper() if package_name else 'A'
    hash_val = hash(package_name) % 360
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
        <rect width="48" height="48" fill="hsl({hash_val}, 70%, 60%)" rx="8"/>
        <text x="24" y="32" font-family="Arial, sans-serif" font-size="24" font-weight="bold"
              fill="white" text-anchor="middle">{first_letter}</text>
    </svg>'''
    logger.debug(f"[API] Tier 4: SVG fallback for {package_name} (background fetch in progress)")
    return Response(content=svg, media_type="image/svg+xml", headers={"X-Icon-Source": "svg-placeholder"})


# =============================================================================
# APP CONTROL ENDPOINTS
# =============================================================================

@router.post("/launch")
async def launch_app(request: LaunchAppRequest):
    """Launch an app by package name"""
    deps = get_deps()
    try:
        logger.info(f"[API] Launching {request.package} on {request.device_id}")
        success = await deps.adb_bridge.launch_app(request.device_id, request.package)

        return {
            "success": success,
            "device_id": request.device_id,
            "package": request.package,
            "timestamp": time.time()
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
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Stop app failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
