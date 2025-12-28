"""
Device Security Routes - Lock Screen Configuration & Encrypted Passcode Storage

Provides endpoints for managing device lock screen configurations:
- Get/save lock screen strategy (no_lock, smart_lock, auto_unlock, manual_only)
- Test unlock with passcode
- Encrypted passcode storage using PBKDF2 + Fernet

Security features:
- All passcodes encrypted at rest
- Per-device encryption keys derived from stable_device_id
- Security JSON files stored in data/security/ with 600 permissions (Unix)
- Passcodes never logged in decrypted form
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
from routes import get_deps
from utils.device_security import LockStrategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/device", tags=["device_security"])


# =============================================================================
# REQUEST MODELS
# =============================================================================

class DeviceSecurityRequest(BaseModel):
    strategy: str  # LockStrategy enum value
    passcode: Optional[str] = None
    notes: Optional[str] = None


class DeviceUnlockRequest(BaseModel):
    passcode: str


# =============================================================================
# LOCK SCREEN CONFIGURATION ENDPOINTS
# =============================================================================

@router.get("/{device_id}/security")
async def get_device_security(device_id: str):
    """
    Get lock screen configuration for device.

    Returns:
        {
            "config": {
                "device_id": str,
                "strategy": str (LockStrategy value),
                "notes": str,
                "has_passcode": bool
            }
        }
        Returns null config if no configuration exists
    """
    deps = get_deps()
    try:
        config = deps.device_security_manager.get_lock_config(device_id)
        return {"config": config}
    except Exception as e:
        logger.error(f"[API] Failed to get security config for {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{device_id}/security")
async def save_device_security(device_id: str, request: DeviceSecurityRequest):
    """
    Save lock screen configuration for device.

    Body:
        {
            "strategy": str (no_lock|smart_lock|auto_unlock|manual_only),
            "passcode": str (required for auto_unlock),
            "notes": str (optional)
        }

    Returns:
        {
            "success": true,
            "device_id": str,
            "strategy": str
        }
    """
    deps = get_deps()
    try:
        # Validate strategy
        try:
            strategy = LockStrategy(request.strategy)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid strategy: {request.strategy}. Must be one of: {[s.value for s in LockStrategy]}"
            )

        # Validate passcode requirement for auto_unlock
        if strategy == LockStrategy.AUTO_UNLOCK and not request.passcode:
            raise HTTPException(
                status_code=400,
                detail="Passcode is required for auto_unlock strategy"
            )

        # Save configuration
        success = deps.device_security_manager.save_lock_config(
            device_id=device_id,
            strategy=strategy,
            passcode=request.passcode,
            notes=request.notes
        )

        if success:
            logger.info(f"[API] Saved security config for {device_id}: strategy={strategy.value}")
            return {"success": True, "device_id": device_id, "strategy": strategy.value}
        else:
            raise HTTPException(status_code=500, detail="Failed to save configuration")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to save security config for {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{device_id}/unlock")
async def test_device_unlock(device_id: str, request: DeviceUnlockRequest):
    """
    Test unlocking device with provided passcode.

    This endpoint attempts to unlock the device and returns success/failure.
    Used for testing passcodes before saving them to the configuration.

    Body:
        {
            "passcode": str
        }

    Returns:
        {
            "success": bool,
            "message": str
        }
    """
    deps = get_deps()
    try:
        # Check if device is connected
        devices = await deps.adb_bridge.get_devices()
        device_ids = [d.get('id') for d in devices]

        if device_id not in device_ids:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not connected")

        # Attempt unlock
        success = await deps.adb_bridge.unlock_device(device_id, request.passcode)

        if success:
            logger.info(f"[API] Successfully unlocked device {device_id}")
            return {"success": True, "message": "Device unlocked successfully"}
        else:
            logger.warning(f"[API] Failed to unlock device {device_id}")
            return {"success": False, "message": "Failed to unlock device"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Error testing unlock for {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
