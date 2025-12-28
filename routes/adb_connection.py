"""
ADB Connection Routes - Device Connection Management

Provides endpoints for connecting, pairing, and disconnecting Android devices
via TCP/IP and wireless debugging (Android 11+).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adb", tags=["adb_connection"])


# Request models
class ConnectDeviceRequest(BaseModel):
    host: str
    port: int = 5555


class DisconnectDeviceRequest(BaseModel):
    device_id: str


class PairingRequest(BaseModel):
    pairing_host: str
    pairing_port: int
    pairing_code: str
    connection_port: int  # The actual ADB port to connect to after pairing


# =============================================================================
# CONNECTION MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/connect")
async def connect_device(request: ConnectDeviceRequest):
    """Connect to Android device via TCP/IP"""
    deps = get_deps()
    try:
        logger.info(f"[API] Connecting to {request.host}:{request.port}")
        device_id = await deps.adb_bridge.connect_device(request.host, request.port)
        return {
            "device_id": device_id,
            "connected": True,
            "message": f"Connected to {device_id}"
        }
    except Exception as e:
        logger.error(f"[API] Connection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pair")
async def pair_device(request: PairingRequest):
    """Pair with Android 11+ device using wireless pairing

    Android 11+ wireless debugging uses TWO ports:
    - Pairing port (e.g., 37899) - for initial pairing with code
    - Connection port (e.g., 45441) - for actual ADB connection after pairing
    """
    deps = get_deps()
    try:
        logger.info(f"[API] Pairing with {request.pairing_host}:{request.pairing_port}")

        # Step 1: Pair with pairing port using code
        success = await deps.adb_bridge.pair_device(
            request.pairing_host,
            request.pairing_port,
            request.pairing_code
        )

        if not success:
            raise HTTPException(status_code=500, detail="Pairing failed - check code and port")

        # Step 2: Connect on connection port (NOT 5555!) after successful pairing
        logger.info(f"[API] Pairing successful, connecting on port {request.connection_port}")
        device_id = await deps.adb_bridge.connect_device(request.pairing_host, request.connection_port)

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
