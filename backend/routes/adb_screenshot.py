"""
ADB Screenshot Routes - Screenshot Capture and UI Element Extraction

Provides endpoints for capturing screenshots and extracting UI elements:
- Single screenshot capture (with optional UI elements)
- UI elements-only endpoint (fast for streaming)
- Stitched screenshot for scrollable pages
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
import base64
import io
from datetime import datetime
from typing import Optional
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adb", tags=["adb_screenshot"])


# Request models
class ScreenshotRequest(BaseModel):
    device_id: str
    quick: bool = False  # Quick mode: skip UI elements for faster preview


class ScreenshotStitchRequest(BaseModel):
    device_id: str
    max_scrolls: Optional[int] = 20
    scroll_ratio: Optional[float] = 0.75
    overlap_ratio: Optional[float] = 0.25
    stitcher_version: Optional[str] = "v2"
    debug: Optional[bool] = False


# =============================================================================
# SCREENSHOT CAPTURE ENDPOINTS
# =============================================================================

@router.post("/screenshot")
async def capture_screenshot(request: ScreenshotRequest):
    """Capture screenshot and UI elements from device

    Quick mode (quick=true): Only captures screenshot image, skips UI element extraction
    Normal mode (quick=false): Captures both screenshot and UI elements
    """
    deps = get_deps()
    try:
        # Verify device is connected
        devices = await deps.adb_bridge.get_devices()
        if not any(d.get('id') == request.device_id for d in devices):
            raise HTTPException(status_code=404, detail=f"Device not connected: {request.device_id}")

        mode = "quick" if request.quick else "full"
        logger.info(f"[API] Capturing {mode} screenshot from {request.device_id}")

        # Capture PNG screenshot
        screenshot_bytes = await deps.adb_bridge.capture_screenshot(request.device_id)

        # Extract UI elements (skip if quick mode)
        if request.quick:
            elements = []
            logger.info(f"[API] Quick screenshot captured: {len(screenshot_bytes)} bytes (UI elements skipped)")
        else:
            elements = await deps.adb_bridge.get_ui_elements(request.device_id)
            logger.info(f"[API] Full screenshot captured: {len(screenshot_bytes)} bytes, {len(elements)} UI elements")

        # Encode screenshot to base64
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        return {
            "screenshot": screenshot_base64,
            "elements": elements,
            "timestamp": datetime.now().isoformat(),
            "quick": request.quick
        }
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"[API] Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/elements/{device_id}")
async def get_elements_only(device_id: str):
    """Get UI elements without capturing screenshot (faster for streaming mode)"""
    deps = get_deps()
    try:
        logger.info(f"[API] Getting elements only from {device_id}")
        elements = await deps.adb_bridge.get_ui_elements(device_id)
        logger.info(f"[API] Got {len(elements)} elements")

        # Get current app/activity info for stale element detection
        current_package = None
        current_activity = None
        try:
            activity_info = await deps.adb_bridge.get_current_activity(device_id)
            if activity_info:
                current_package = activity_info.get('package')
                current_activity = activity_info.get('activity')
                logger.debug(f"[API] Current app: {current_package}/{current_activity}")
        except Exception as e:
            logger.debug(f"[API] Could not get current activity: {e}")

        # Infer device dimensions from element bounds
        # CRITICAL: When user manually switches apps during streaming, frontend needs
        # updated dimensions to correctly scale element overlays. We infer native device
        # resolution by finding max bounds across all elements.
        device_width = 1080  # Default
        device_height = 1920

        if elements:
            max_x = max_y = 0
            for el in elements:
                if el.get('bounds'):
                    bounds = el['bounds']
                    max_x = max(max_x, bounds.get('x', 0) + bounds.get('width', 0))
                    max_y = max(max_y, bounds.get('y', 0) + bounds.get('height', 0))

            # Only update if we found valid bounds
            if max_x > 100 and max_y > 100:
                # Round to common device dimensions (nearest 10 pixels)
                device_width = round(max_x / 10) * 10
                device_height = round(max_y / 10) * 10
                logger.debug(f"[API] Inferred device dimensions: {device_width}x{device_height}")

        return {
            "success": True,
            "elements": elements,
            "count": len(elements),
            "device_width": device_width,
            "device_height": device_height,
            "current_package": current_package,
            "current_activity": current_activity,
            "timestamp": datetime.now().isoformat()
        }
    except ValueError as e:
        logger.warning(f"[API] Elements request failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Elements failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/screenshot/stitch")
async def capture_stitched_screenshot(request: ScreenshotStitchRequest):
    """Capture full scrollable page by stitching multiple screenshots"""
    deps = get_deps()
    try:
        logger.info(f"[API] Capturing stitched screenshot from {request.device_id}")
        logger.debug(f"  max_scrolls={request.max_scrolls}, scroll_ratio={request.scroll_ratio}, overlap_ratio={request.overlap_ratio}")

        if not deps.screenshot_stitcher:
            logger.error(f"[API] ScreenshotStitcher not initialized")
            raise HTTPException(status_code=500, detail="Screenshot stitcher not available")

        # Capture scrolling screenshot using new modular implementation
        result = await deps.screenshot_stitcher.capture_scrolling_screenshot(
            request.device_id,
            max_scrolls=request.max_scrolls,
            scroll_ratio=request.scroll_ratio,
            overlap_ratio=request.overlap_ratio
        )

        # Convert PIL Image to base64
        img_buffer = io.BytesIO()
        result['image'].save(img_buffer, format='PNG')
        img_buffer.seek(0)
        screenshot_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')

        logger.info(f"[API] Stitched screenshot captured: {result['metadata']}")
        logger.info(f"[API] Combined elements: {len(result.get('elements', []))}")

        return {
            "screenshot": screenshot_base64,
            "elements": result.get('elements', []),
            "metadata": result['metadata'],
            "debug_screenshots": result.get('debug_screenshots', []),
            "timestamp": datetime.now().isoformat()
        }
    except ValueError as e:
        logger.error(f"[API] Stitched screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Stitched screenshot failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
