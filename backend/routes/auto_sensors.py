"""
Auto Sensors API Routes

Endpoints for zero-config sensors that are automatically created on device connect.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
import logging

from services.auto_sensors import get_auto_sensor_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auto-sensors", tags=["auto-sensors"])


@router.get("/")
async def list_auto_sensors() -> Dict[str, Any]:
    """
    List all auto-sensors and their current states.

    Returns summary of all devices with auto-sensors.
    """
    manager = get_auto_sensor_manager()
    if not manager:
        return {
            "success": True,
            "message": "Auto-sensor manager not initialized",
            "devices": {},
        }

    devices = {}
    for device_id, app_state in manager._app_states.items():
        screen_state = manager._screen_states.get(device_id)
        devices[device_id] = {
            "app_screen": {
                "state": app_state.display_state,
                "attributes": app_state.to_attributes(),
            },
            "screen_frozen": screen_state.is_frozen if screen_state else False,
            "screen_change_count": screen_state.change_count if screen_state else 0,
        }

    return {
        "success": True,
        "devices": devices,
        "total_devices": len(devices),
    }


@router.get("/{device_id}")
async def get_device_auto_sensors(device_id: str) -> Dict[str, Any]:
    """
    Get auto-sensor states for a specific device.

    Args:
        device_id: Device ID (e.g., 192.168.1.2:5555)

    Returns:
        Current state of all auto-sensors for the device.
    """
    manager = get_auto_sensor_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Auto-sensor manager not initialized")

    app_state = manager.get_app_state(device_id)
    screen_state = manager.get_screen_state(device_id)

    if not app_state and not screen_state:
        raise HTTPException(
            status_code=404,
            detail=f"No auto-sensors found for device {device_id}"
        )

    return {
        "success": True,
        "device_id": device_id,
        "app_screen": {
            "state": app_state.display_state if app_state else "Unknown",
            "package": app_state.package if app_state else "",
            "app_name": app_state.app_name if app_state else "",
            "activity": app_state.activity if app_state else "",
            "screen_type": app_state.screen_type.value if app_state else "unknown",
        },
        "screen_frozen": {
            "state": screen_state.is_frozen if screen_state else False,
            "static_seconds": int(
                (screen_state.static_since if screen_state else 0)
                - (screen_state.last_change_time if screen_state else 0)
            ) if screen_state and screen_state.is_frozen else 0,
        },
        "screen_changed": {
            "change_count": screen_state.change_count if screen_state else 0,
            "last_change": screen_state.last_change_time if screen_state else None,
        },
    }


@router.post("/{device_id}/start")
async def start_auto_sensors(device_id: str, stable_device_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Manually start auto-sensors for a device.

    Normally auto-sensors start automatically on device connect.
    This endpoint allows manual start if needed.
    """
    manager = get_auto_sensor_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Auto-sensor manager not initialized")

    await manager.start_device(device_id, stable_device_id or device_id)

    return {
        "success": True,
        "message": f"Auto-sensors started for {device_id}",
    }


@router.post("/{device_id}/stop")
async def stop_auto_sensors(device_id: str) -> Dict[str, Any]:
    """
    Stop auto-sensors for a device.
    """
    manager = get_auto_sensor_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Auto-sensor manager not initialized")

    await manager.stop_device(device_id)

    return {
        "success": True,
        "message": f"Auto-sensors stopped for {device_id}",
    }
