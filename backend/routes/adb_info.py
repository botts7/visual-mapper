"""
ADB Info Routes - Device Information and Status

Provides read-only information about connected devices.
Does not perform control operations (those are in adb_control.py).
"""

from fastapi import APIRouter, HTTPException
import logging
import time
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adb", tags=["adb_info"])


@router.get("/devices")
async def get_devices():
    """Get list of connected devices"""
    deps = get_deps()
    try:
        devices = await deps.adb_bridge.get_devices()

        # Update MQTT device info cache with device models for friendly names
        if deps.mqtt_manager:
            for device in devices:
                device_id = device.get("id")
                model = device.get("model")
                if device_id and model:
                    deps.mqtt_manager.set_device_info(device_id, model=model)

        return {"devices": devices}
    except Exception as e:
        logger.error(f"[API] Failed to get devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connection-status")
async def get_connection_status():
    """Get connection monitor status for all devices"""
    deps = get_deps()
    try:
        if not deps.connection_monitor:
            return {"error": "Connection monitor not initialized"}

        status = deps.connection_monitor.get_status_summary()
        return status
    except Exception as e:
        logger.error(f"[API] Failed to get connection status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scan")
async def scan_network(network_range: str = None):
    """
    Scan local network for Android devices with ADB enabled.

    This endpoint performs intelligent network scanning to find devices and
    automatically detects Android version to recommend the optimal connection method.

    Query Parameters:
        network_range: Optional network range to scan (e.g., "192.168.1.0/24")
                      If not provided, will auto-detect and scan local subnet

    Returns:
        {
            "devices": [
                {
                    "ip": "192.168.1.100",
                    "port": 5555,
                    "android_version": "13",
                    "sdk_version": 33,
                    "model": "SM-G998B",
                    "recommended_method": "pairing",  # or "tcp"
                    "state": "available"  # or "connected"
                }
            ],
            "total": 2,
            "scan_duration_ms": 1234
        }
    """
    deps = get_deps()
    try:
        start_time = time.time()

        logger.info(f"[API] Starting network scan (range: {network_range or 'auto'})")

        devices = await deps.adb_bridge.scan_network_for_devices(network_range)

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[API] Network scan complete: Found {len(devices)} devices in {duration_ms:.0f}ms"
        )

        return {
            "devices": devices,
            "total": len(devices),
            "scan_duration_ms": round(duration_ms, 1),
        }
    except Exception as e:
        logger.error(f"[API] Network scan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/screen-state/{device_id}")
async def get_screen_state(device_id: str):
    """Check if device screen is currently on"""
    deps = get_deps()
    try:
        logger.info(f"[API] Checking screen state for {device_id}")
        is_on = await deps.adb_bridge.is_screen_on(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "screen_on": is_on,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Screen state check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lock-status/{device_id}")
async def get_lock_status(device_id: str):
    """Check if device is locked (showing lock screen)"""
    deps = get_deps()
    try:
        logger.info(f"[API] Checking lock status for {device_id}")
        is_locked = await deps.adb_bridge.is_locked(device_id)
        is_screen_on = await deps.adb_bridge.is_screen_on(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "is_locked": is_locked,
            "screen_on": is_screen_on,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Lock status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity/{device_id}")
async def get_current_activity(device_id: str):
    """Get current focused activity/window on device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Getting current activity for {device_id}")
        activity = await deps.adb_bridge.get_current_activity(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "activity": activity,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Get activity failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stable-id/{device_id}")
async def get_stable_device_id(device_id: str, force_refresh: bool = False):
    """
    Get stable device identifier (survives IP/port changes).
    Uses Android ID hash as primary method with fallbacks.
    """
    deps = get_deps()
    try:
        logger.info(f"[API] Getting stable device ID for {device_id}")
        stable_id = await deps.adb_bridge.get_device_serial(device_id, force_refresh)
        return {
            "success": True,
            "device_id": device_id,
            "stable_device_id": stable_id,
            "cached": not force_refresh
            and deps.adb_bridge.get_cached_serial(device_id) is not None,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Get stable device ID failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/screen/current/{device_id}")
async def get_current_screen(device_id: str):
    """
    Get current screen info (activity with package/activity breakdown).
    Used for screen awareness in Flow Wizard.

    Returns:
        activity: {package, activity, full_name}
        element_count: Number of UI elements on screen
        timestamp: Current time
    """
    deps = get_deps()
    try:
        logger.info(f"[API] Getting current screen info for {device_id}")

        # Get activity info as dict (with package breakdown)
        activity_info = await deps.adb_bridge.get_current_activity(
            device_id, as_dict=True
        )

        return {
            "success": True,
            "device_id": device_id,
            "activity": activity_info,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Get screen info failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
