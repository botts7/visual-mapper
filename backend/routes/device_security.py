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
import asyncio
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
    sleep_grace_period: int = 300  # Seconds before sleeping if another flow is due (default 5 min)


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
            notes=request.notes,
            sleep_grace_period=request.sleep_grace_period
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


@router.post("/{device_id}/auto-unlock")
async def auto_unlock_device(device_id: str):
    """
    Automatically unlock device using stored encrypted passcode.

    This endpoint is used by the flow wizard to automatically unlock
    devices when configured with auto_unlock strategy.

    Returns:
        {
            "success": bool,
            "message": str,
            "unlock_status": dict (failure_count, in_cooldown, etc.)
        }
    """
    deps = get_deps()
    try:
        # Check if device is connected
        devices = await deps.adb_bridge.get_devices()
        device_ids = [d.get('id') for d in devices]

        if device_id not in device_ids:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not connected")

        # Check unlock status first
        unlock_status = deps.adb_bridge.get_unlock_status(device_id)

        if unlock_status["in_cooldown"]:
            logger.warning(f"[API] Auto-unlock blocked - device {device_id} in cooldown")
            return {
                "success": False,
                "message": f"Unlock blocked - in cooldown for {unlock_status['cooldown_remaining_seconds']}s to prevent device lockout. Please unlock manually.",
                "unlock_status": unlock_status
            }

        # Step 1: Try swipe unlock first (fast, works for devices without passcode)
        try:
            await deps.adb_bridge.unlock_screen(device_id)
            await asyncio.sleep(0.3)

            # Check if swipe was enough
            is_locked = await deps.adb_bridge.is_locked(device_id)
            if not is_locked:
                logger.info(f"[API] Device {device_id} unlocked via swipe")
                return {"success": True, "message": "Device unlocked via swipe", "unlock_status": unlock_status}
        except Exception as e:
            logger.debug(f"[API] Swipe unlock attempt: {e}")

        # Step 2: Try passcode if configured
        config = deps.device_security_manager.get_lock_config(device_id)
        passcode = deps.device_security_manager.get_passcode(device_id) if config else None

        success = False
        if passcode and config.get('strategy') == "auto_unlock":
            # Attempt passcode unlock
            success = await deps.adb_bridge.unlock_device(device_id, passcode)

        # Get updated status after attempt
        unlock_status = deps.adb_bridge.get_unlock_status(device_id)

        if success:
            logger.info(f"[API] Auto-unlocked device {device_id}")
            return {"success": True, "message": "Device unlocked successfully", "unlock_status": unlock_status}
        else:
            logger.warning(f"[API] Auto-unlock failed for {device_id}")
            message = "Failed to unlock device"
            if unlock_status["in_cooldown"]:
                message = f"Unlock failed - max attempts reached. In cooldown for {unlock_status['cooldown_remaining_seconds']}s. Please unlock manually."
            elif unlock_status["failure_count"] > 0:
                remaining = unlock_status["max_attempts"] - unlock_status["failure_count"]
                message = f"Unlock failed - {remaining} attempt(s) remaining before cooldown"
            return {"success": False, "message": message, "unlock_status": unlock_status}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Error auto-unlocking {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{device_id}/unlock-status")
async def get_unlock_status(device_id: str):
    """
    Get unlock attempt status for device.

    Returns information about failed unlock attempts and cooldown status.
    Use this to check if the device needs manual intervention.

    Returns:
        {
            "device_id": str,
            "failure_count": int,
            "in_cooldown": bool,
            "cooldown_remaining_seconds": int,
            "locked_out": bool,
            "max_attempts": int
        }
    """
    deps = get_deps()
    try:
        status = deps.adb_bridge.get_unlock_status(device_id)
        return {
            "device_id": device_id,
            **status
        }
    except Exception as e:
        logger.error(f"[API] Error getting unlock status for {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{device_id}/reset-unlock-failures")
async def reset_unlock_failures(device_id: str):
    """
    Reset unlock failure count for device.

    Call this after manually unlocking the device to allow
    auto-unlock attempts again.

    Returns:
        {
            "success": bool,
            "message": str,
            "unlock_status": dict
        }
    """
    deps = get_deps()
    try:
        deps.adb_bridge.reset_unlock_failures(device_id)
        status = deps.adb_bridge.get_unlock_status(device_id)

        logger.info(f"[API] Reset unlock failures for {device_id}")
        return {
            "success": True,
            "message": "Unlock failures reset successfully",
            "unlock_status": status
        }
    except Exception as e:
        logger.error(f"[API] Error resetting unlock failures for {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
