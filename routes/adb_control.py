"""
ADB Control Routes - Device Control Operations

Provides endpoints for controlling Android devices remotely:
- Touch gestures (tap, swipe)
- Text input
- Hardware key events (back, home, custom keycodes)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adb", tags=["adb_control"])


# Request models
class TapRequest(BaseModel):
    device_id: str
    x: int
    y: int


class SwipeRequest(BaseModel):
    device_id: str
    x1: int
    y1: int
    x2: int
    y2: int
    duration: int = 300


class TextInputRequest(BaseModel):
    device_id: str
    text: str


class KeyEventRequest(BaseModel):
    device_id: str
    keycode: int


# =============================================================================
# TOUCH CONTROL ENDPOINTS
# =============================================================================

@router.post("/tap")
async def tap_device(request: TapRequest):
    """Simulate tap at coordinates on device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Tap at ({request.x}, {request.y}) on {request.device_id}")
        await deps.adb_bridge.tap(request.device_id, request.x, request.y)
        return {
            "success": True,
            "device_id": request.device_id,
            "x": request.x,
            "y": request.y,
            "message": f"Tapped at ({request.x}, {request.y})"
        }
    except Exception as e:
        logger.error(f"[API] Tap failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/swipe")
async def swipe_device(request: SwipeRequest):
    """Simulate swipe gesture on device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Swipe ({request.x1},{request.y1}) -> ({request.x2},{request.y2}) on {request.device_id}")
        await deps.adb_bridge.swipe(
            request.device_id,
            request.x1, request.y1,
            request.x2, request.y2,
            request.duration
        )
        return {
            "success": True,
            "device_id": request.device_id,
            "from": {"x": request.x1, "y": request.y1},
            "to": {"x": request.x2, "y": request.y2},
            "duration": request.duration,
            "message": f"Swiped from ({request.x1},{request.y1}) to ({request.x2},{request.y2})"
        }
    except Exception as e:
        logger.error(f"[API] Swipe failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# INPUT CONTROL ENDPOINTS
# =============================================================================

@router.post("/text")
async def input_text(request: TextInputRequest):
    """Type text on device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Type text on {request.device_id}: {request.text[:20]}...")
        await deps.adb_bridge.type_text(request.device_id, request.text)
        return {
            "success": True,
            "device_id": request.device_id,
            "text": request.text,
            "message": f"Typed {len(request.text)} characters"
        }
    except Exception as e:
        logger.error(f"[API] Text input failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keyevent")
async def send_keyevent(request: KeyEventRequest):
    """Send hardware key event to device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Key event {request.keycode} on {request.device_id}")
        await deps.adb_bridge.keyevent(request.device_id, request.keycode)
        return {
            "success": True,
            "device_id": request.device_id,
            "keycode": request.keycode,
            "message": f"Sent key event: {request.keycode}"
        }
    except Exception as e:
        logger.error(f"[API] Key event failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONVENIENCE KEY ENDPOINTS
# =============================================================================

@router.post("/back")
async def send_back_key(request: dict):
    """Send BACK key event to device (convenience endpoint)"""
    deps = get_deps()
    try:
        device_id = request.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id required")
        logger.info(f"[API] Back key on {device_id}")
        await deps.adb_bridge.keyevent(device_id, "KEYCODE_BACK")
        return {"success": True, "device_id": device_id, "message": "Back key sent"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Back key failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/home")
async def send_home_key(request: dict):
    """Send HOME key event to device (convenience endpoint)"""
    deps = get_deps()
    try:
        device_id = request.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id required")
        logger.info(f"[API] Home key on {device_id}")
        await deps.adb_bridge.keyevent(device_id, "KEYCODE_HOME")
        return {"success": True, "device_id": device_id, "message": "Home key sent"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Home key failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# POWER/SCREEN CONTROL
# =============================================================================

@router.post("/wake/{device_id}")
async def wake_device_screen(device_id: str):
    """Wake the device screen"""
    deps = get_deps()
    try:
        import time
        logger.info(f"[API] Waking screen for {device_id}")
        success = await deps.adb_bridge.ensure_screen_on(device_id, timeout_ms=3000)
        return {
            "success": success,
            "device_id": device_id,
            "message": "Screen woken" if success else "Failed to wake screen",
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Wake screen failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sleep/{device_id}")
async def sleep_device_screen(device_id: str):
    """Put the device screen to sleep"""
    deps = get_deps()
    try:
        import time
        logger.info(f"[API] Sleeping screen for {device_id}")
        success = await deps.adb_bridge.sleep_screen(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": "Screen put to sleep" if success else "Failed to sleep screen",
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Sleep screen failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unlock/{device_id}")
async def unlock_device_screen(device_id: str):
    """Attempt to unlock the device screen (swipe-to-unlock only, not PIN/pattern)"""
    deps = get_deps()
    try:
        import time
        logger.info(f"[API] Unlocking screen for {device_id}")
        success = await deps.adb_bridge.unlock_screen(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": "Unlock attempt completed" if success else "Failed to unlock screen",
            "note": "Only works for swipe-to-unlock, not PIN/pattern locked devices",
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Unlock screen failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
