"""
Cache Routes - Cache Management

Provides endpoints for managing UI hierarchy and screenshot caches.
Includes statistics, clearing, and settings configuration.
"""

from fastapi import APIRouter, HTTPException
import logging
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cache", tags=["cache"])


# === UI Cache Endpoints ===


@router.get("/ui/stats")
async def get_ui_cache_stats():
    """Get UI hierarchy cache statistics"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "cache": deps.adb_bridge.get_ui_cache_stats()}


@router.post("/ui/clear")
async def clear_ui_cache(device_id: str = None):
    """Clear UI hierarchy cache for a device or all devices"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    deps.adb_bridge.clear_ui_cache(device_id)
    return {
        "success": True,
        "message": (
            f"UI cache cleared for {device_id}"
            if device_id
            else "UI cache cleared for all devices"
        ),
    }


@router.post("/ui/settings")
async def update_ui_cache_settings(enabled: bool = None, ttl_ms: float = None):
    """Update UI hierarchy cache settings"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")

    if enabled is not None:
        deps.adb_bridge.set_ui_cache_enabled(enabled)
    if ttl_ms is not None:
        deps.adb_bridge.set_ui_cache_ttl(ttl_ms)

    return {"success": True, "cache": deps.adb_bridge.get_ui_cache_stats()}


# === Screenshot Cache Endpoints ===


@router.get("/screenshot/stats")
async def get_screenshot_cache_stats():
    """Get screenshot cache statistics"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "cache": deps.adb_bridge.get_screenshot_cache_stats()}


@router.post("/screenshot/settings")
async def update_screenshot_cache_settings(enabled: bool = None, ttl_ms: float = None):
    """Update screenshot cache settings"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")

    if enabled is not None:
        deps.adb_bridge.set_screenshot_cache_enabled(enabled)
    if ttl_ms is not None:
        deps.adb_bridge.set_screenshot_cache_ttl(ttl_ms)

    return {"success": True, "cache": deps.adb_bridge.get_screenshot_cache_stats()}


# === Combined Cache Endpoints ===


@router.get("/all/stats")
async def get_all_cache_stats():
    """Get all cache statistics (UI + Screenshot)"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {
        "success": True,
        "ui_cache": deps.adb_bridge.get_ui_cache_stats(),
        "screenshot_cache": deps.adb_bridge.get_screenshot_cache_stats(),
    }
