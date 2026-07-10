"""
Health Routes - System Health Check

Provides health check endpoint for monitoring server status.
Depends on mqtt_manager for connection status.
"""

from fastapi import APIRouter
import logging
import socket
from routes import get_deps
from utils.version import APP_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


def get_local_ip():
    """Get the local IP address of the server."""
    try:
        # Create a socket and connect to an external address to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return None


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

    # Get server's local IP
    server_ip = get_local_ip()

    return {
        "status": "ok",
        "version": APP_VERSION,
        "message": "Visual Mapper is running",
        "mqtt_connected": mqtt_connected,
        "mqtt_status": mqtt_status,
        "server_ip": server_ip,
    }
