"""
Element Watcher API Routes

One-click element monitoring - watch any UI element without creating a flow.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging

from core.element_watcher import get_element_watcher_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/element-watchers", tags=["element-watchers"])


class CreateWatcherRequest(BaseModel):
    """Request to create an element watcher."""
    element: Dict[str, Any]  # UI element from ADB
    name: Optional[str] = None  # Auto-generated if not provided
    icon: str = "mdi:eye"


class WatcherResponse(BaseModel):
    """Response with watcher details."""
    id: str
    device_id: str
    name: str
    sensor_id: str
    icon: str
    enabled: bool
    is_visible: bool
    last_seen: Optional[float]
    check_count: int
    signature: Dict[str, Any]


@router.get("/")
async def list_all_watchers() -> Dict[str, Any]:
    """
    List all element watchers across all devices.
    """
    manager = get_element_watcher_manager()
    if not manager:
        return {
            "success": True,
            "message": "Element watcher manager not initialized",
            "devices": {},
        }

    devices = {}
    total = 0
    for device_id, watchers_dict in manager._watchers.items():
        watchers = [w.to_dict() for w in watchers_dict.values()]
        devices[device_id] = watchers
        total += len(watchers)

    return {
        "success": True,
        "devices": devices,
        "total_watchers": total,
    }


@router.get("/{device_id}")
async def list_device_watchers(device_id: str) -> Dict[str, Any]:
    """
    List all element watchers for a specific device.

    Args:
        device_id: Device ID (e.g., 192.168.1.2:5555)
    """
    manager = get_element_watcher_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Element watcher manager not initialized")

    watchers = manager.get_watchers(device_id)

    return {
        "success": True,
        "device_id": device_id,
        "watchers": [w.to_dict() for w in watchers],
        "total": len(watchers),
    }


@router.post("/{device_id}")
async def create_watcher(device_id: str, request: CreateWatcherRequest) -> Dict[str, Any]:
    """
    Create a new element watcher (one-click watch).

    This is the main "Watch" button action. Pass the UI element
    and optionally a custom name.

    Args:
        device_id: Device ID
        request: Element data and optional name

    Returns:
        Created watcher details
    """
    manager = get_element_watcher_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Element watcher manager not initialized")

    try:
        watcher = await manager.create_watcher(
            device_id=device_id,
            element=request.element,
            name=request.name,
            icon=request.icon,
        )

        return {
            "success": True,
            "message": f"Created watcher '{watcher.name}'",
            "watcher": watcher.to_dict(),
        }
    except Exception as e:
        logger.error(f"Failed to create watcher: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{device_id}/{watcher_id}")
async def get_watcher(device_id: str, watcher_id: str) -> Dict[str, Any]:
    """
    Get details of a specific watcher.
    """
    manager = get_element_watcher_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Element watcher manager not initialized")

    watcher = manager.get_watcher(device_id, watcher_id)
    if not watcher:
        raise HTTPException(status_code=404, detail=f"Watcher {watcher_id} not found")

    return {
        "success": True,
        "watcher": watcher.to_dict(),
    }


@router.delete("/{device_id}/{watcher_id}")
async def delete_watcher(device_id: str, watcher_id: str) -> Dict[str, Any]:
    """
    Delete an element watcher.
    """
    manager = get_element_watcher_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Element watcher manager not initialized")

    success = await manager.delete_watcher(device_id, watcher_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Watcher {watcher_id} not found")

    return {
        "success": True,
        "message": f"Deleted watcher {watcher_id}",
    }


@router.post("/{device_id}/{watcher_id}/toggle")
async def toggle_watcher(device_id: str, watcher_id: str) -> Dict[str, Any]:
    """
    Toggle a watcher's enabled state.
    """
    manager = get_element_watcher_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Element watcher manager not initialized")

    watcher = manager.get_watcher(device_id, watcher_id)
    if not watcher:
        raise HTTPException(status_code=404, detail=f"Watcher {watcher_id} not found")

    watcher.enabled = not watcher.enabled
    manager._save_watchers(device_id)

    return {
        "success": True,
        "watcher_id": watcher_id,
        "enabled": watcher.enabled,
    }


@router.post("/{device_id}/start")
async def start_monitoring(device_id: str) -> Dict[str, Any]:
    """
    Start monitoring watchers for a device.

    Usually called automatically on device connect.
    """
    manager = get_element_watcher_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Element watcher manager not initialized")

    await manager.start_device(device_id)

    return {
        "success": True,
        "message": f"Started monitoring for {device_id}",
    }


@router.post("/{device_id}/stop")
async def stop_monitoring(device_id: str) -> Dict[str, Any]:
    """
    Stop monitoring watchers for a device.
    """
    manager = get_element_watcher_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Element watcher manager not initialized")

    await manager.stop_device(device_id)

    return {
        "success": True,
        "message": f"Stopped monitoring for {device_id}",
    }
