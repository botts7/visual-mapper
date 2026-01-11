"""
Meta Routes - API Root and Device Classes

Provides informational endpoints about the API itself.
No dependencies on managers - safest module to extract first.
"""

from fastapi import APIRouter, HTTPException
import logging
from core.mqtt.ha_device_classes import export_to_json as export_device_classes
from utils.version import APP_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["meta"])

logger.info(f"[Meta] Loaded version: {APP_VERSION}")


@router.get("/")
async def api_root():
    """API root endpoint"""
    return {
        "name": "Visual Mapper API",
        "version": APP_VERSION,
        "endpoints": {
            "health": "/api/health",
            "diagnostics_adb": "/api/diagnostics/adb/{device_id}",
            "diagnostics_streaming": "/api/diagnostics/streaming/{device_id}",
            "diagnostics_benchmark": "/api/diagnostics/benchmark/{device_id}",
            "diagnostics_system": "/api/diagnostics/system",
            "connect": "/api/adb/connect",
            "pair": "/api/adb/pair",
            "disconnect": "/api/adb/disconnect",
            "devices": "/api/adb/devices",
            "screenshot": "/api/adb/screenshot",
            "sensors": "/api/sensors",
            "sensors_by_device": "/api/sensors/{device_id}",
            "sensor_detail": "/api/sensors/{device_id}/{sensor_id}",
            "device_classes": "/api/device-classes",
            "shell_stats": "/api/shell/stats",
            "shell_execute": "/api/shell/{device_id}/execute",
            "shell_batch": "/api/shell/{device_id}/batch",
            "shell_benchmark": "/api/shell/{device_id}/benchmark",
            "maintenance_server_restart": "/api/maintenance/server/restart",
            "maintenance_metrics": "/api/maintenance/metrics",
        },
    }


@router.get("/device-classes")
async def get_device_classes():
    """
    Get comprehensive Home Assistant device class reference.
    Includes all sensor types, units, icons, and validation rules.

    This is a local reference file, not pulled from Home Assistant.
    Works in both standalone and add-on modes.
    """
    try:
        return export_device_classes()
    except Exception as e:
        logger.error(f"[API] Failed to export device classes: {e}")
        raise HTTPException(status_code=500, detail=str(e))
