"""
Device Registration Routes - Android Companion App Registration

Provides endpoints for registering Android companion app devices.
Persists device registry to data/device_registry.json
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
import json
import os
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["device_registration"])

# Registry file path
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
REGISTRY_FILE = DATA_DIR / "device_registry.json"


# Request/Response models
class DeviceRegistration(BaseModel):
    deviceId: str
    deviceName: str
    platform: str
    appVersion: str
    capabilities: List[str]


class DeviceInfo(BaseModel):
    deviceId: str
    deviceName: str
    platform: str
    appVersion: str
    capabilities: List[str]
    registeredAt: Optional[str]
    lastHeartbeat: Optional[str] = None
    registered: bool = True
    source: Optional[str] = "companion"
    connectionType: Optional[str] = None
    connected: Optional[bool] = None


# =============================================================================
# DEVICE REGISTRY PERSISTENCE
# =============================================================================

def _load_registry() -> Dict[str, "DeviceInfo"]:
    """Load device registry from file"""
    if not REGISTRY_FILE.exists():
        return {}

    try:
        with open(REGISTRY_FILE, "r") as f:
            data = json.load(f)

        registry = {}
        for device_id, device_data in data.items():
            registry[device_id] = DeviceInfo(**device_data)
        logger.info(f"[Device Registration] Loaded {len(registry)} devices from {REGISTRY_FILE}")
        return registry
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"[Device Registration] Failed to load registry: {e}")
        return {}


def _save_registry():
    """Save device registry to file"""
    try:
        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Convert DeviceInfo objects to dicts
        data = {
            device_id: device.model_dump() if hasattr(device, "model_dump") else device.dict()
            for device_id, device in registered_devices.items()
        }

        with open(REGISTRY_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.debug(f"[Device Registration] Saved {len(data)} devices to {REGISTRY_FILE}")
    except (OSError, TypeError) as e:
        logger.error(f"[Device Registration] Failed to save registry: {e}")


# Load existing registry on module import
registered_devices: Dict[str, DeviceInfo] = _load_registry()


@router.post("/register")
async def register_device(device: DeviceRegistration):
    """
    Register Android companion app device

    Called when the companion app first connects to the server.
    Stores device information and capabilities.
    """
    try:
        logger.info(
            f"[Device Registration] Registering device: {device.deviceId} ({device.deviceName})"
        )

        device_info = DeviceInfo(
            deviceId=device.deviceId,
            deviceName=device.deviceName,
            platform=device.platform,
            appVersion=device.appVersion,
            capabilities=device.capabilities,
            registeredAt=datetime.now().isoformat(),
            lastHeartbeat=None,
            registered=True,
            source="companion",
        )

        registered_devices[device.deviceId] = device_info

        # Persist to file
        _save_registry()

        logger.info(
            f"[Device Registration] Device registered successfully: {device.deviceId}"
        )
        logger.info(
            f"[Device Registration] Capabilities: {', '.join(device.capabilities)}"
        )

        return {
            "success": True,
            "deviceId": device.deviceId,
            "message": f"Device {device.deviceName} registered successfully",
            "registeredAt": device_info.registeredAt,
        }

    except Exception as e:
        logger.error(f"[Device Registration] Failed to register device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{device_id}/heartbeat")
async def device_heartbeat(device_id: str):
    """
    Receive heartbeat from companion app

    Called periodically by the companion app to indicate it's still active.
    """
    try:
        if device_id in registered_devices:
            registered_devices[device_id].lastHeartbeat = datetime.now().isoformat()
            logger.debug(f"[Heartbeat] Received from device: {device_id}")
            return {"success": True, "message": "Heartbeat received"}
        else:
            logger.warning(f"[Heartbeat] Unknown device: {device_id}")
            return {"success": False, "message": "Device not registered"}

    except Exception as e:
        logger.error(f"[Heartbeat] Failed to process heartbeat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_registered_devices():
    """
    Get list of all registered companion app devices
    """
    return {
        "devices": list(registered_devices.values()),
        "count": len(registered_devices),
    }


@router.get("/{device_id}")
async def get_device_info(device_id: str):
    """
    Get information about a specific registered device
    """
    if device_id not in registered_devices:
        deps = get_deps()
        if deps.adb_bridge:
            try:
                devices = await deps.adb_bridge.get_devices()
                match = next(
                    (dev for dev in devices if dev.get("id") == device_id), None
                )
                if match:
                    return DeviceInfo(
                        deviceId=device_id,
                        deviceName=match.get("model") or device_id,
                        platform="android",
                        appVersion="unknown",
                        capabilities=[],
                        registeredAt=None,
                        lastHeartbeat=None,
                        registered=False,
                        source="adb",
                        connectionType=match.get("connection_type"),
                        connected=match.get("connected"),
                    )
            except Exception as e:
                logger.warning(
                    f"[Device Registration] ADB fallback lookup failed for {device_id}: {e}"
                )
        raise HTTPException(status_code=404, detail="Device not found")

    return registered_devices[device_id]


@router.delete("/{device_id}")
async def unregister_device(device_id: str):
    """
    Unregister a companion app device
    """
    if device_id not in registered_devices:
        raise HTTPException(status_code=404, detail="Device not found")

    device = registered_devices.pop(device_id)

    # Persist to file
    _save_registry()

    logger.info(f"[Device Registration] Device unregistered: {device_id}")

    return {"success": True, "message": f"Device {device.deviceName} unregistered"}
