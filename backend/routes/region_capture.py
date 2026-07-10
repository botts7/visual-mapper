"""
Region Capture API Routes

Capture screen regions linked to sensors for Home Assistant picture cards.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging

from core.region_capture import get_region_capture_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/regions", tags=["region-capture"])


class CreateRegionRequest(BaseModel):
    """Request to create a captured region."""
    name: str
    bounds: Dict[str, int]  # {x, y, width, height}
    linked_sensors: Optional[List[str]] = None
    jpeg_quality: int = 75
    update_interval_seconds: int = 60


class LinkSensorRequest(BaseModel):
    """Request to link/unlink a sensor."""
    sensor_id: str


@router.get("/")
async def list_all_regions() -> Dict[str, Any]:
    """
    List all captured regions across all devices.
    """
    manager = get_region_capture_manager()
    if not manager:
        return {
            "success": True,
            "message": "Region capture manager not initialized",
            "devices": {},
        }

    devices = {}
    total = 0
    for device_id, regions_dict in manager._regions.items():
        regions = [r.to_dict() for r in regions_dict.values()]
        devices[device_id] = regions
        total += len(regions)

    return {
        "success": True,
        "devices": devices,
        "total_regions": total,
    }


@router.get("/{device_id}")
async def list_device_regions(device_id: str) -> Dict[str, Any]:
    """
    List all captured regions for a specific device.
    """
    manager = get_region_capture_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Region capture manager not initialized")

    regions = manager.get_regions(device_id)

    return {
        "success": True,
        "device_id": device_id,
        "regions": [r.to_dict() for r in regions],
        "total": len(regions),
    }


@router.post("/{device_id}")
async def create_region(device_id: str, request: CreateRegionRequest) -> Dict[str, Any]:
    """
    Create a new captured region.

    Draw a rectangle on the screen, optionally link to sensors.
    The region will be periodically captured and available as an image.

    Args:
        device_id: Device ID
        request: Region bounds and optional linked sensors
    """
    manager = get_region_capture_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Region capture manager not initialized")

    # Validate bounds
    bounds = request.bounds
    if not all(k in bounds for k in ["x", "y", "width", "height"]):
        raise HTTPException(
            status_code=400,
            detail="Bounds must include x, y, width, and height"
        )

    if bounds.get("width", 0) < 10 or bounds.get("height", 0) < 10:
        raise HTTPException(
            status_code=400,
            detail="Region must be at least 10x10 pixels"
        )

    try:
        region = await manager.create_region(
            device_id=device_id,
            name=request.name,
            bounds=bounds,
            linked_sensors=request.linked_sensors,
            jpeg_quality=request.jpeg_quality,
            update_interval_seconds=request.update_interval_seconds,
        )

        return {
            "success": True,
            "message": f"Created region '{region.name}'",
            "region": region.to_dict(),
            "image_url": f"/api/regions/{device_id}/{region.id}/image",
        }
    except Exception as e:
        logger.error(f"Failed to create region: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{device_id}/{region_id}")
async def get_region(device_id: str, region_id: str) -> Dict[str, Any]:
    """
    Get details of a specific region.
    """
    manager = get_region_capture_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Region capture manager not initialized")

    region = manager.get_region(device_id, region_id)
    if not region:
        raise HTTPException(status_code=404, detail=f"Region {region_id} not found")

    return {
        "success": True,
        "region": region.to_dict(),
        "image_url": f"/api/regions/{device_id}/{region_id}/image",
    }


@router.delete("/{device_id}/{region_id}")
async def delete_region(device_id: str, region_id: str) -> Dict[str, Any]:
    """
    Delete a captured region.
    """
    manager = get_region_capture_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Region capture manager not initialized")

    success = await manager.delete_region(device_id, region_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Region {region_id} not found")

    return {
        "success": True,
        "message": f"Deleted region {region_id}",
    }


@router.get("/{device_id}/{region_id}/image")
async def get_region_image(device_id: str, region_id: str) -> Response:
    """
    Get the captured image for a region.

    Returns JPEG image bytes. Use this URL in HA picture cards.

    Example Lovelace:
    ```yaml
    type: picture-entity
    entity: sensor.solar_production
    image: /api/regions/{device_id}/{region_id}/image
    ```
    """
    manager = get_region_capture_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Region capture manager not initialized")

    image_bytes = await manager.get_image(device_id, region_id)
    if not image_bytes:
        raise HTTPException(status_code=404, detail="Image not available")

    return Response(
        content=image_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "max-age=30",  # Cache for 30 seconds
        },
    )


@router.post("/{device_id}/{region_id}/capture")
async def capture_region_now(device_id: str, region_id: str) -> Dict[str, Any]:
    """
    Capture a region immediately.

    Forces a fresh capture regardless of the update interval.
    """
    manager = get_region_capture_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Region capture manager not initialized")

    image_bytes = await manager.capture_now(device_id, region_id)
    if not image_bytes:
        raise HTTPException(status_code=500, detail="Failed to capture region")

    return {
        "success": True,
        "message": "Region captured",
        "image_size": len(image_bytes),
        "image_url": f"/api/regions/{device_id}/{region_id}/image",
    }


@router.post("/{device_id}/{region_id}/link")
async def link_sensor(device_id: str, region_id: str, request: LinkSensorRequest) -> Dict[str, Any]:
    """
    Link a sensor to a region.

    Linked sensors are associated with the region's image for
    context in Home Assistant cards.
    """
    manager = get_region_capture_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Region capture manager not initialized")

    success = await manager.link_sensor(device_id, region_id, request.sensor_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Region {region_id} not found")

    return {
        "success": True,
        "message": f"Linked sensor {request.sensor_id} to region",
    }


@router.post("/{device_id}/{region_id}/unlink")
async def unlink_sensor(device_id: str, region_id: str, request: LinkSensorRequest) -> Dict[str, Any]:
    """
    Unlink a sensor from a region.
    """
    manager = get_region_capture_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Region capture manager not initialized")

    success = await manager.unlink_sensor(device_id, region_id, request.sensor_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Region {region_id} not found")

    return {
        "success": True,
        "message": f"Unlinked sensor {request.sensor_id} from region",
    }
