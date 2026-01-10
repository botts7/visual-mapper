"""
Health Routes - System Health Check

Provides health check endpoint for monitoring server status.
Depends on mqtt_manager for connection status.
"""

from fastapi import APIRouter
import logging
import os
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])

# Read version from .build-version file (auto-updated by pre-commit hook)
def _get_version():
    """Get version from .build-version file"""
    version_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.build-version')
    try:
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                return f.read().strip()
    except Exception as e:
        logger.warning(f"Failed to read version file: {e}")
    return "0.0.81"  # Fallback version

APP_VERSION = _get_version()


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
        "mqtt_status": mqtt_status
    }
