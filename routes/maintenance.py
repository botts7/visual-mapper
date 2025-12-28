"""
Maintenance Routes - ADB Server and Device Maintenance

Provides endpoints for server management (restart, status) and device
optimization (cache trimming, UI optimization, ART compilation, display reset).
"""

from fastapi import APIRouter, HTTPException
import logging
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


# =============================================================================
# SERVER MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/server/restart")
async def restart_adb_server():
    """Restart ADB server to fix zombie processes and connection issues"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.restart_adb_server()


@router.get("/server/status")
async def get_adb_server_status():
    """Get ADB server status and connected devices"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.get_server_status()


# =============================================================================
# DEVICE OPTIMIZATION ENDPOINTS
# =============================================================================

@router.post("/{device_id}/trim-cache")
async def trim_device_cache(device_id: str):
    """Clear all app caches on device to free storage and improve performance"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.trim_cache(device_id)


@router.post("/{device_id}/compile-apps")
async def compile_device_apps(device_id: str, mode: str = "speed-profile"):
    """Force ART compilation for faster app launches (takes 5-15 minutes)

    Modes: speed-profile (recommended), speed, verify, quicken
    """
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.compile_apps(device_id, mode)


@router.post("/{device_id}/optimize-ui")
async def optimize_device_ui(device_id: str):
    """Disable visual effects for faster UI operations"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.optimize_ui(device_id)


@router.post("/{device_id}/reset-ui")
async def reset_device_ui(device_id: str):
    """Reset UI animations and effects to defaults"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.reset_ui_optimizations(device_id)


@router.post("/{device_id}/full-optimize")
async def full_device_optimize(device_id: str):
    """Run full optimization suite (cache + UI)"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.full_optimize(device_id)


@router.post("/{device_id}/reset-display")
async def reset_device_display(device_id: str):
    """Emergency reset of display size and density"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.reset_display(device_id)


# =============================================================================
# BACKGROUND LIMIT ENDPOINTS
# =============================================================================

@router.get("/{device_id}/background-limit")
async def get_background_limit(device_id: str):
    """Get current background process limit"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.get_background_limit(device_id)


@router.post("/{device_id}/background-limit")
async def set_background_limit(device_id: str, limit: int = 4):
    """Set background process limit (0-4, -1 for default)"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await deps.adb_maintenance.set_background_limit(device_id, limit)


# =============================================================================
# METRICS ENDPOINTS
# =============================================================================

@router.get("/metrics")
async def get_all_connection_metrics():
    """Get connection health metrics for all devices"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return {"success": True, "metrics": deps.adb_maintenance.get_all_metrics()}


@router.get("/{device_id}/metrics")
async def get_device_connection_metrics(device_id: str):
    """Get connection health metrics for a specific device"""
    deps = get_deps()
    if not deps.adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    metrics = deps.adb_maintenance.get_connection_metrics(device_id)
    if not metrics:
        return {"success": True, "metrics": None, "message": "No metrics yet for this device"}
    return {"success": True, "metrics": metrics}
