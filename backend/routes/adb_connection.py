"""
ADB Connection Routes - Device Connection Management

Provides endpoints for connecting, pairing, and disconnecting Android devices
via TCP/IP and wireless debugging (Android 11+).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
from routes import get_deps
from services.device_identity import get_device_identity_resolver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adb", tags=["adb_connection"])


# Request models
class ConnectDeviceRequest(BaseModel):
    host: Optional[str] = None
    ip: Optional[str] = None  # Frontend often sends 'ip'
    port: int = 5555


class DisconnectDeviceRequest(BaseModel):
    device_id: str


class PairingRequest(BaseModel):
    pairing_host: Optional[str] = None
    ip: Optional[str] = None  # Frontend sends 'ip'
    pairing_port: int
    pairing_code: str
    connection_port: Optional[int] = 5555  # Make optional with default


# =============================================================================
# CONNECTION MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/connect")
async def connect_device(request: ConnectDeviceRequest):
    """Connect to Android device via TCP/IP"""
    deps = get_deps()
    try:
        host = request.host or request.ip
        if not host:
            raise HTTPException(status_code=400, detail="Host or IP is required")

        logger.info(f"[API] Connecting to {host}:{request.port}")
        device_id = await deps.adb_bridge.connect_device(host, request.port)
        return {
            "device_id": device_id,
            "connected": True,
            "success": True,  # Frontend expects success: true
            "message": f"Connected to {device_id}"
        }
    except Exception as e:
        logger.error(f"[API] Connection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pair")
async def pair_device(request: PairingRequest):
    """Pair with Android 11+ device using wireless pairing"""
    deps = get_deps()
    try:
        host = request.pairing_host or request.ip
        if not host:
            raise HTTPException(status_code=400, detail="Host or IP is required")

        logger.info(f"[API] Pairing with {host}:{request.pairing_port}")

        # Step 1: Pair with pairing port using code
        success = await deps.adb_bridge.pair_device(
            host,
            request.pairing_port,
            request.pairing_code
        )

        if not success:
            return {
                "success": False,
                "message": "Pairing failed - check code and port"
            }

        # Step 2: Connect on connection port after successful pairing
        # Use connection_port if provided, else use pairing_port (some devices use same)
        conn_port = request.connection_port or request.pairing_port
        logger.info(f"[API] Pairing successful, connecting on port {conn_port}")
        device_id = await deps.adb_bridge.connect_device(host, conn_port)

        return {
            "success": True,
            "device_id": device_id,
            "message": f"Paired and connected to {device_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Pairing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnect")
async def disconnect_device(request: DisconnectDeviceRequest):
    """Disconnect from Android device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Disconnecting from {request.device_id}")
        await deps.adb_bridge.disconnect_device(request.device_id)
        return {
            "device_id": request.device_id,
            "disconnected": True,
            "message": f"Disconnected from {request.device_id}"
        }
    except Exception as e:
        logger.error(f"[API] Disconnection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/announced")
async def get_announced_devices():
    """Get devices that have announced themselves via MQTT

    Android companion apps can announce their connection details to enable
    auto-discovery without network scanning. This solves the Android 11+
    wireless debugging discovery problem (dynamic ports).

    Returns:
        List of announced devices with connection info
    """
    deps = get_deps()
    try:
        # Get announced devices from MQTT manager
        announced = deps.mqtt_manager.get_announced_devices() if deps.mqtt_manager else []
        return {
            "devices": announced,
            "count": len(announced)
        }
    except Exception as e:
        logger.error(f"[API] Failed to get announced devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DEVICE IDENTITY ENDPOINTS
# =============================================================================

@router.get("/known-devices")
async def get_known_devices():
    """Get all known devices with their stable identifiers."""
    try:
        deps = get_deps()
        resolver = get_device_identity_resolver(deps.data_dir)
        devices = resolver.get_all_devices()
        return {
            "devices": devices,
            "count": len(devices)
        }
    except Exception as e:
        logger.error(f"[API] Failed to get known devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/identity/{device_id}")
async def get_device_identity(device_id: str):
    """Get identity information for a specific device.

    Args:
        device_id: Either connection_id (IP:port) or stable_device_id

    Returns:
        Device identity info including stable_device_id and connection info
    """
    deps = get_deps()
    try:
        resolver = get_device_identity_resolver(deps.data_dir)

        # First try to resolve to stable ID
        stable_id = resolver.resolve_any_id(device_id)

        # Get device info
        info = resolver.get_device_info(stable_id)

        # Get current connection if device is connected
        current_conn = resolver.get_connection_id(stable_id)
        is_connected = current_conn in deps.adb_bridge.devices if deps.adb_bridge else False

        return {
            "device_id": device_id,
            "stable_device_id": stable_id,
            "current_connection": current_conn,
            "is_connected": is_connected,
            "model": info.get("model") if info else None,
            "manufacturer": info.get("manufacturer") if info else None,
            "last_seen": info.get("last_seen") if info else None,
            "connection_history": info.get("connection_history", []) if info else []
        }
    except Exception as e:
        logger.error(f"[API] Failed to get device identity: {e}")
        raise HTTPException(status_code=500, detail=str(e))
