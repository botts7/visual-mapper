"""
Streaming Routes - Live Screenshot Streaming

Provides endpoints for live device streaming:
- HTTP stats endpoints for stream monitoring
- WebSocket JSON streaming (base64 encoded frames)
- WebSocket MJPEG streaming (binary frames, ~30% less bandwidth)

Supports quality presets: high, medium, low, fast
"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
import logging
import time
import asyncio
import base64
import io
from PIL import Image
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["streaming"])

# Quality presets: max_height, jpeg_quality, target_fps
QUALITY_PRESETS = {
    'high': {'max_height': None, 'jpeg_quality': 85, 'target_fps': 5, 'frame_delay': 0.2},
    'medium': {'max_height': 720, 'jpeg_quality': 75, 'target_fps': 10, 'frame_delay': 0.1},
    'low': {'max_height': 480, 'jpeg_quality': 65, 'target_fps': 15, 'frame_delay': 0.066},
    'fast': {'max_height': 360, 'jpeg_quality': 55, 'target_fps': 20, 'frame_delay': 0.05},
}

def resize_image_for_quality(img_bytes: bytes, quality: str) -> bytes:
    """Resize image based on quality preset. Returns JPEG bytes."""
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS['medium'])

    try:
        img = Image.open(io.BytesIO(img_bytes))

        # Resize if needed
        if preset['max_height'] and img.height > preset['max_height']:
            ratio = preset['max_height'] / img.height
            new_width = int(img.width * ratio)
            img = img.resize((new_width, preset['max_height']), Image.Resampling.LANCZOS)

        # Convert to JPEG
        output = io.BytesIO()
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.save(output, format='JPEG', quality=preset['jpeg_quality'], optimize=True)
        return output.getvalue()
    except Exception as e:
        logger.warning(f"[Quality] Resize failed: {e}, returning original")
        return img_bytes


# =============================================================================
# HTTP STREAMING STATS
# =============================================================================

@router.get("/stream/stats")
async def get_stream_isolation_stats():
    """Get streaming isolation statistics (separate from screenshots)"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "stream": deps.adb_bridge.get_stream_stats()}


@router.get("/stream/{device_id}/stats")
async def get_device_stream_stats(device_id: str):
    """Get streaming stats for a specific device"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "stream": deps.adb_bridge.get_stream_stats(device_id)}


# =============================================================================
# WEBSOCKET JSON STREAMING
# =============================================================================

@router.websocket("/ws/stream/{device_id}")
async def stream_device(websocket: WebSocket, device_id: str):
    """
    WebSocket endpoint for live screenshot streaming.

    Query params:
    - quality: 'high', 'medium', 'low', 'fast' (default: medium)

    Message format (JSON):
    {
        "type": "frame",
        "image": "<base64 JPEG>",
        "elements": [...],
        "timestamp": 1234567890.123,
        "capture_ms": 150,
        "frame_number": 1
    }
    """
    deps = get_deps()
    await websocket.accept()

    # Parse quality from query string
    quality = websocket.query_params.get('quality', 'medium')
    if quality not in QUALITY_PRESETS:
        quality = 'medium'
    preset = QUALITY_PRESETS[quality]

    logger.info(f"[WS-Stream] Client connected for device: {device_id}, quality: {quality} (target {preset['target_fps']} FPS)")

    frame_number = 0

    try:
        # Capture initial screenshot to get native device dimensions
        try:
            init_screenshot = await deps.adb_bridge.capture_screenshot(device_id)
            if len(init_screenshot) > 1000:
                init_img = Image.open(io.BytesIO(init_screenshot))
                device_width, device_height = init_img.size
                # Send config with native device dimensions
                await websocket.send_json({
                    "type": "config",
                    "width": device_width,
                    "height": device_height,
                    "quality": quality,
                    "target_fps": preset['target_fps']
                })
                logger.info(f"[WS-Stream] Device dimensions: {device_width}x{device_height}")
        except Exception as init_err:
            logger.warning(f"[WS-Stream] Failed to get device dimensions: {init_err}")

        while True:
            frame_number += 1
            capture_start = time.time()

            try:
                # Capture screenshot with per-frame timeout (3 seconds max)
                # This prevents a single slow capture from blocking the stream
                try:
                    screenshot_bytes = await asyncio.wait_for(
                        deps.adb_bridge.capture_screenshot(device_id),
                        timeout=3.0  # 3 second max per frame
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[WS-Stream] Frame {frame_number}: Capture timeout (>3s), skipping")
                    await asyncio.sleep(0.5)
                    continue

                capture_time = (time.time() - capture_start) * 1000  # ms

                # Skip if invalid/empty screenshot
                if len(screenshot_bytes) < 1000:
                    logger.warning(f"[WS-Stream] Frame {frame_number}: Screenshot too small ({len(screenshot_bytes)} bytes), skipping")
                    await asyncio.sleep(0.5)
                    continue

                # Resize based on quality (also converts to JPEG)
                if quality != 'high':
                    processed_bytes = resize_image_for_quality(screenshot_bytes, quality)
                else:
                    processed_bytes = screenshot_bytes

                # Debug: Log periodically
                if frame_number <= 3 or frame_number % 100 == 0:
                    logger.info(f"[WS-Stream] Frame {frame_number}: {len(screenshot_bytes)} -> {len(processed_bytes)} bytes ({quality})")

                # Encode and send
                screenshot_base64 = base64.b64encode(processed_bytes).decode('utf-8')

                # Determine image type
                is_jpeg = processed_bytes[:2] == b'\xff\xd8'
                image_prefix = 'data:image/jpeg;base64,' if is_jpeg else 'data:image/png;base64,'

                await websocket.send_json({
                    "type": "frame",
                    "image": screenshot_base64,
                    "elements": [],  # Empty - elements fetched on-demand via Refresh Elements button
                    "timestamp": time.time(),
                    "capture_ms": round(capture_time, 1),
                    "frame_number": frame_number
                })

                # Sleep based on quality preset
                sleep_time = max(0.03, preset['frame_delay'] - (time.time() - capture_start))
                await asyncio.sleep(sleep_time)

            except Exception as capture_error:
                logger.warning(f"[WS-Stream] Capture error: {capture_error}")
                # Send error frame but keep connection alive
                await websocket.send_json({
                    "type": "error",
                    "message": str(capture_error),
                    "timestamp": time.time()
                })
                await asyncio.sleep(1)  # Wait before retry

    except WebSocketDisconnect:
        logger.info(f"[WS-Stream] Client disconnected: {device_id}")
    except Exception as e:
        logger.error(f"[WS-Stream] Connection error: {e}")
    finally:
        logger.info(f"[WS-Stream] Stream ended for device: {device_id}, frames sent: {frame_number}")


# =============================================================================
# WEBSOCKET MJPEG BINARY STREAMING
# =============================================================================

@router.websocket("/ws/stream-mjpeg/{device_id}")
async def stream_device_mjpeg(websocket: WebSocket, device_id: str):
    """
    WebSocket endpoint for live MJPEG binary streaming.

    Sends raw JPEG binary frames instead of base64 JSON for ~30% bandwidth reduction.

    Query params:
    - quality: 'high', 'medium', 'low', 'fast' (default: medium)

    Message format (Binary + JSON header):
    - First message: JSON config {"width": 1200, "height": 1920, "format": "jpeg"}
    - Subsequent messages: Binary JPEG data with 8-byte header
        - Bytes 0-3: Frame number (uint32 big-endian)
        - Bytes 4-7: Capture time ms (uint32 big-endian)
        - Bytes 8+: JPEG image data
    """
    import struct
    deps = get_deps()

    await websocket.accept()

    # Parse quality from query string
    quality = websocket.query_params.get('quality', 'medium')
    if quality not in QUALITY_PRESETS:
        quality = 'medium'
    preset = QUALITY_PRESETS[quality]

    logger.info(f"[WS-MJPEG] Client connected for device: {device_id}, quality: {quality} (target {preset['target_fps']} FPS)")

    frame_number = 0

    try:
        # Capture initial screenshot to get native device dimensions
        device_width, device_height = 1080, 1920  # Defaults
        try:
            init_screenshot = await deps.adb_bridge.capture_screenshot(device_id)
            if len(init_screenshot) > 1000:
                init_img = Image.open(io.BytesIO(init_screenshot))
                device_width, device_height = init_img.size
                logger.info(f"[WS-MJPEG] Device dimensions: {device_width}x{device_height}")
        except Exception as init_err:
            logger.warning(f"[WS-MJPEG] Failed to get device dimensions: {init_err}")

        # Send initial config as JSON with device dimensions
        await websocket.send_json({
            "type": "config",
            "format": "mjpeg",
            "width": device_width,
            "height": device_height,
            "quality": quality,
            "target_fps": preset['target_fps'],
            "message": "MJPEG binary streaming ready. Subsequent frames are binary."
        })

        while True:
            frame_number += 1
            capture_start = time.time()

            try:
                # Capture screenshot with per-frame timeout (3 seconds max)
                # This prevents a single slow capture from blocking the stream
                try:
                    screenshot_bytes = await asyncio.wait_for(
                        deps.adb_bridge.capture_screenshot(device_id),
                        timeout=3.0  # 3 second max per frame
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[WS-MJPEG] Frame {frame_number}: Capture timeout (>3s), skipping")
                    await asyncio.sleep(0.5)
                    continue

                capture_time = int((time.time() - capture_start) * 1000)  # ms as int

                # Skip if invalid/empty screenshot
                if len(screenshot_bytes) < 1000:
                    logger.warning(f"[WS-MJPEG] Frame {frame_number}: Screenshot too small ({len(screenshot_bytes)} bytes), skipping")
                    await asyncio.sleep(0.5)
                    continue

                # Resize and convert to JPEG based on quality preset
                try:
                    jpeg_bytes = resize_image_for_quality(screenshot_bytes, quality)
                except Exception as convert_error:
                    logger.warning(f"[WS-MJPEG] JPEG conversion failed: {convert_error}, sending PNG")
                    jpeg_bytes = screenshot_bytes  # Fallback to PNG

                # Create binary frame with header
                # Header: 4 bytes frame_number + 4 bytes capture_time
                header = struct.pack('>II', frame_number, capture_time)
                frame_data = header + jpeg_bytes

                # Send binary frame
                await websocket.send_bytes(frame_data)

                # Log periodically
                if frame_number <= 3 or frame_number % 60 == 0:
                    logger.info(f"[WS-MJPEG] Frame {frame_number}: {len(jpeg_bytes)} bytes JPEG, {capture_time}ms capture, quality={quality}")

                # Use frame delay from quality preset
                sleep_time = max(0.05, preset['frame_delay'] - (time.time() - capture_start))
                await asyncio.sleep(sleep_time)

            except Exception as capture_error:
                logger.warning(f"[WS-MJPEG] Capture error: {capture_error}")
                # Send error as JSON (not binary)
                await websocket.send_json({
                    "type": "error",
                    "message": str(capture_error),
                    "timestamp": time.time()
                })
                await asyncio.sleep(1)  # Wait before retry

    except WebSocketDisconnect:
        logger.info(f"[WS-MJPEG] Client disconnected: {device_id}")
    except Exception as e:
        logger.error(f"[WS-MJPEG] Connection error: {e}")
    finally:
        logger.info(f"[WS-MJPEG] Stream ended for device: {device_id}, frames sent: {frame_number}")
