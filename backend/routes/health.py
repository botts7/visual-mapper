"""
Health Routes - System Health Check

Provides health check endpoint for monitoring server status.
Depends on mqtt_manager for connection status.
"""

from fastapi import APIRouter
import logging
from routes import get_deps
from utils.version import APP_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


@router.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    """
    Health check endpoint

    Returns server status, version, and MQTT connection status.
    Used by monitoring systems and health checks.
    Supports both GET and HEAD methods for Docker health checks.
    """
    deps = get_deps()

    # Check MQTT connection status
    mqtt_connected = bool(deps.mqtt_manager and deps.mqtt_manager.is_connected)
    mqtt_status = "connected" if mqtt_connected else "disconnected"

    return {
        "status": "ok",
        "version": APP_VERSION,
        "message": "Visual Mapper is running",
        "mqtt_connected": mqtt_connected,
        "mqtt_status": mqtt_status,
    }
