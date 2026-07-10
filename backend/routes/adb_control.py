"""
ADB Control Routes - Device Control Operations

Provides endpoints for controlling Android devices remotely:
- Touch gestures (tap, swipe)
- Text input
- Hardware key events (back, home, custom keycodes)

Routes commands through companion app (WebSocket/MQTT) when available,
with ADB as fallback. This prevents stream interruption during operations.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import logging
from routes import get_deps
from routes.auth import verify_companion_auth
from core.command_router import command_router, CommandMethod

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/adb",
    tags=["adb_control"],
    dependencies=[Depends(verify_companion_auth)],
)


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
    """
    Simulate tap at coordinates on device.

    Routes through companion (WebSocket/MQTT) when available to prevent
    stream interruption, falls back to ADB.
    """
    deps = get_deps()
    try:
        # Ensure command router has dependencies
        command_router.set_deps(deps)

        logger.info(f"[API] Tap at ({request.x}, {request.y}) on {request.device_id}")

        result = await command_router.execute(
            request.device_id,
            "tap",
            {"x": request.x, "y": request.y}
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error or "Tap failed")

        return {
            "success": True,
            "device_id": request.device_id,
            "x": request.x,
            "y": request.y,
            "method": result.method.value,
            "latency_ms": round(result.latency_ms, 1),
            "message": f"Tapped at ({request.x}, {request.y}) via {result.method.value}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Tap failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/swipe")
async def swipe_device(request: SwipeRequest):
    """
    Simulate swipe gesture on device.

    Routes through companion (WebSocket/MQTT) when available to prevent
    stream interruption, falls back to ADB.
    """
    deps = get_deps()
    try:
        command_router.set_deps(deps)

        logger.info(
            f"[API] Swipe ({request.x1},{request.y1}) -> ({request.x2},{request.y2}) on {request.device_id}"
        )

        result = await command_router.execute(
            request.device_id,
            "swipe",
            {
                "x1": request.x1,
                "y1": request.y1,
                "x2": request.x2,
                "y2": request.y2,
                "duration": request.duration,
            }
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error or "Swipe failed")

        return {
            "success": True,
            "device_id": request.device_id,
            "from": {"x": request.x1, "y": request.y1},
            "to": {"x": request.x2, "y": request.y2},
            "duration": request.duration,
            "method": result.method.value,
            "latency_ms": round(result.latency_ms, 1),
            "message": f"Swiped via {result.method.value}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Swipe failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# INPUT CONTROL ENDPOINTS
# =============================================================================


@router.post("/text")
async def input_text(request: TextInputRequest):
    """
    Type text on device.

    Routes through companion (WebSocket/MQTT) when available.
    """
    deps = get_deps()
    try:
        command_router.set_deps(deps)

        logger.info(f"[API] Type text on {request.device_id}: {request.text[:20]}...")

        result = await command_router.execute(
            request.device_id,
            "input_text",
            {"text": request.text}
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error or "Text input failed")

        return {
            "success": True,
            "device_id": request.device_id,
            "text": request.text,
            "method": result.method.value,
            "latency_ms": round(result.latency_ms, 1),
            "message": f"Typed {len(request.text)} characters via {result.method.value}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Text input failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keyevent")
async def send_keyevent(request: KeyEventRequest):
    """
    Send hardware key event to device.

    Routes through companion (WebSocket/MQTT) when available.
    Supported keys: BACK, HOME, RECENTS, NOTIFICATIONS, etc.

    Exception: WAKEUP (224) always goes direct to ADB - it's just a keep-alive
    signal and shouldn't interrupt companion streaming.
    """
    deps = get_deps()
    try:
        # WAKEUP (224) bypasses CommandRouter - it's a keep-alive signal
        # that shouldn't go through companion WebSocket during streaming
        if request.keycode == 224:
            logger.debug(f"[API] WAKEUP key on {request.device_id} (direct ADB)")
            await deps.adb_bridge.keyevent(request.device_id, str(request.keycode))
            return {
                "success": True,
                "device_id": request.device_id,
                "keycode": request.keycode,
                "method": "adb",
                "latency_ms": 0,
                "message": "Sent WAKEUP via ADB (keep-alive)",
            }

        command_router.set_deps(deps)

        logger.info(f"[API] Key event {request.keycode} on {request.device_id}")

        # Convert keycode to string for companion
        key = str(request.keycode)
        # Map common keycodes to names for companion
        keycode_names = {
            4: "BACK",
            3: "HOME",
            187: "RECENTS",
        }
        if isinstance(request.keycode, int):
            key = keycode_names.get(request.keycode, str(request.keycode))

        result = await command_router.execute(
            request.device_id,
            "key_event",
            {"key": key}
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error or "Key event failed")

        return {
            "success": True,
            "device_id": request.device_id,
            "keycode": request.keycode,
            "method": result.method.value,
            "latency_ms": round(result.latency_ms, 1),
            "message": f"Sent key event via {result.method.value}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Key event failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONVENIENCE KEY ENDPOINTS
# =============================================================================


@router.post("/back")
async def send_back_key(request: dict):
    """Send BACK key event to device.

    Routes through companion (WebSocket/MQTT) when available to preserve streaming.
    """
    deps = get_deps()
    try:
        device_id = request.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id required")

        command_router.set_deps(deps)
        logger.info(f"[API] Back key on {device_id}")

        # Use CommandRouter for WebSocket -> MQTT -> ADB fallback
        result = await command_router.execute(device_id, "key_event", {"key": "BACK"})

        return {
            "success": result.success,
            "device_id": device_id,
            "message": "Back key sent",
            "method": result.method.value
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Back key failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/home")
async def send_home_key(request: dict):
    """Send HOME key event to device.

    Routes through companion (WebSocket/MQTT) when available to preserve streaming.
    """
    deps = get_deps()
    try:
        device_id = request.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id required")

        command_router.set_deps(deps)
        logger.info(f"[API] Home key on {device_id}")

        # Use CommandRouter for WebSocket -> MQTT -> ADB fallback
        result = await command_router.execute(device_id, "key_event", {"key": "HOME"})

        return {
            "success": result.success,
            "device_id": device_id,
            "message": "Home key sent",
            "method": result.method.value
        }
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
    """Wake the device screen.

    Routes through companion (WebSocket/MQTT) when available to avoid ADB interference.
    """
    deps = get_deps()
    try:
        import time
        command_router.set_deps(deps)

        logger.info(f"[API] Waking screen for {device_id}")

        # Use CommandRouter for WebSocket -> MQTT -> ADB fallback
        result = await command_router.execute(device_id, "wake_screen", {})

        return {
            "success": result.success,
            "device_id": device_id,
            "message": "Screen woken" if result.success else (result.error or "Failed to wake screen"),
            "method": result.method.value,
            "timestamp": time.time(),
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
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Sleep screen failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unlock/{device_id}")
async def unlock_device_screen(device_id: str):
    """Attempt to unlock the device screen (swipe-to-unlock only, not PIN/pattern).

    Routes through companion (WebSocket/MQTT) when available to avoid ADB interference.
    """
    deps = get_deps()
    try:
        import time
        command_router.set_deps(deps)

        logger.info(f"[API] Unlocking screen for {device_id}")

        # Use CommandRouter for WebSocket -> MQTT -> ADB fallback
        result = await command_router.execute(device_id, "unlock", {})

        return {
            "success": result.success,
            "device_id": device_id,
            "message": (
                "Unlock attempt completed" if result.success else (result.error or "Failed to unlock screen")
            ),
            "method": result.method.value,
            "note": "Only works for swipe-to-unlock, not PIN/pattern locked devices",
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Unlock screen failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ROUTING INFO
# =============================================================================


@router.get("/routing/{device_id}")
async def get_routing_info(device_id: str):
    """
    Get command routing information for a device.

    Shows which method (WebSocket, MQTT, ADB) will be used for commands.
    Useful for debugging connection issues.
    """
    deps = get_deps()
    try:
        import time

        command_router.set_deps(deps)
        info = command_router.get_routing_info(device_id)

        return {
            "success": True,
            **info,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Get routing info failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
