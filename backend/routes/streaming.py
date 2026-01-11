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
# Note: frame_delay is the MINIMUM time between frames (target = 1/fps)
# Lower values = faster streaming but more CPU usage
QUALITY_PRESETS = {
    "high": {
        "max_height": None,
        "jpeg_quality": 85,
        "target_fps": 5,
        "frame_delay": 0.15,
    },
    "medium": {
        "max_height": 720,
        "jpeg_quality": 75,
        "target_fps": 12,
        "frame_delay": 0.08,
    },
    "low": {
        "max_height": 480,
        "jpeg_quality": 65,
        "target_fps": 18,
        "frame_delay": 0.05,
    },
    "fast": {
        "max_height": 360,
        "jpeg_quality": 55,
        "target_fps": 25,
        "frame_delay": 0.04,
    },
    "ultrafast": {
        "max_height": 240,
        "jpeg_quality": 45,
        "target_fps": 30,
        "frame_delay": 0.03,
    },
}

# Frame capture timeout - skip slow frames quickly to maintain responsiveness
FRAME_CAPTURE_TIMEOUT = 3.0  # 3s max per frame for WiFi ADB
FRAME_SKIP_DELAY = 0.1  # Wait time after skipping a frame (was 0.5s)


def resize_image_for_quality(img_bytes: bytes, quality: str) -> bytes:
    """Resize image based on quality preset. Returns JPEG bytes.

    Raises exception on failure - caller should skip frame rather than send full-res.
    """
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["medium"])

    img = Image.open(io.BytesIO(img_bytes))

    # Resize if needed
    if preset["max_height"] and img.height > preset["max_height"]:
        ratio = preset["max_height"] / img.height
        new_width = int(img.width * ratio)
        img = img.resize((new_width, preset["max_height"]), Image.Resampling.LANCZOS)

    # Convert to JPEG
    output = io.BytesIO()
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(output, format="JPEG", quality=preset["jpeg_quality"], optimize=True)
    return output.getvalue()


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
    quality = websocket.query_params.get("quality", "medium")
    if quality not in QUALITY_PRESETS:
        quality = "medium"
    preset = QUALITY_PRESETS[quality]

    logger.info(
        f"[WS-Stream] Client connected for device: {device_id}, quality: {quality} (target {preset['target_fps']} FPS)"
    )

    frame_number = 0
    device_width, device_height = 1080, 1920  # Defaults

    try:
        # Send config IMMEDIATELY with default dimensions (don't wait for slow capture)
        # This prevents client timeout on slow WiFi connections
        await websocket.send_json(
            {
                "type": "config",
                "width": device_width,
                "height": device_height,
                "quality": quality,
                "target_fps": preset["target_fps"],
            }
        )
        logger.info(
            f"[WS-Stream] Sent initial config with default dimensions: {device_width}x{device_height}"
        )

        while True:
            frame_number += 1
            capture_start = time.time()

            try:
                # Capture screenshot with short timeout for responsiveness
                # Skip slow frames quickly to maintain stream fluidity
                try:
                    screenshot_bytes = await asyncio.wait_for(
                        deps.adb_bridge.capture_screenshot(
                            device_id, force_refresh=True
                        ),
                        timeout=FRAME_CAPTURE_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[WS-Stream] Frame {frame_number}: Capture timeout (>{FRAME_CAPTURE_TIMEOUT}s), skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                capture_time = (time.time() - capture_start) * 1000  # ms

                # Skip if invalid/empty screenshot
                if len(screenshot_bytes) < 1000:
                    logger.warning(
                        f"[WS-Stream] Frame {frame_number}: Screenshot too small ({len(screenshot_bytes)} bytes), skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                # Resize and convert to JPEG based on quality preset
                # Always convert to JPEG even for 'high' - PNG is 4-5x larger
                try:
                    processed_bytes = resize_image_for_quality(
                        screenshot_bytes, quality
                    )
                except Exception as convert_error:
                    logger.warning(
                        f"[WS-Stream] Frame {frame_number}: JPEG conversion failed: {convert_error}, skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                # Debug: Log periodically
                if frame_number <= 3 or frame_number % 100 == 0:
                    logger.info(
                        f"[WS-Stream] Frame {frame_number}: {len(screenshot_bytes)} -> {len(processed_bytes)} bytes ({quality})"
                    )

                # Encode and send
                screenshot_base64 = base64.b64encode(processed_bytes).decode("utf-8")

                # Determine image type
                is_jpeg = processed_bytes[:2] == b"\xff\xd8"
                image_prefix = (
                    "data:image/jpeg;base64," if is_jpeg else "data:image/png;base64,"
                )

                await websocket.send_json(
                    {
                        "type": "frame",
                        "image": screenshot_base64,
                        "elements": [],  # Empty - elements fetched on-demand via Refresh Elements button
                        "timestamp": time.time(),
                        "capture_ms": round(capture_time, 1),
                        "frame_number": frame_number,
                    }
                )

                # Sleep based on quality preset (adaptive - skip sleep if already behind)
                elapsed = time.time() - capture_start
                if elapsed < preset["frame_delay"]:
                    await asyncio.sleep(preset["frame_delay"] - elapsed)

            except Exception as capture_error:
                logger.warning(f"[WS-Stream] Capture error: {capture_error}")
                # Send error frame but keep connection alive
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": str(capture_error),
                        "timestamp": time.time(),
                    }
                )
                await asyncio.sleep(1)  # Wait before retry

    except WebSocketDisconnect:
        logger.info(f"[WS-Stream] Client disconnected: {device_id}")
    except Exception as e:
        logger.error(f"[WS-Stream] Connection error: {e}")
    finally:
        logger.info(
            f"[WS-Stream] Stream ended for device: {device_id}, frames sent: {frame_number}"
        )


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
    quality = websocket.query_params.get("quality", "medium")
    if quality not in QUALITY_PRESETS:
        quality = "medium"
    preset = QUALITY_PRESETS[quality]

    logger.info(
        f"[WS-MJPEG] Client connected for device: {device_id}, quality: {quality} (target {preset['target_fps']} FPS)"
    )

    frame_number = 0
    device_width, device_height = 1080, 1920  # Defaults

    try:
        # Send config IMMEDIATELY with default dimensions (don't wait for slow capture)
        # This prevents client timeout on slow WiFi connections
        await websocket.send_json(
            {
                "type": "config",
                "format": "mjpeg",
                "width": device_width,
                "height": device_height,
                "quality": quality,
                "target_fps": preset["target_fps"],
                "message": "MJPEG binary streaming ready. Subsequent frames are binary.",
            }
        )
        logger.info(
            f"[WS-MJPEG] Sent initial config with default dimensions: {device_width}x{device_height}"
        )

        while True:
            frame_number += 1
            capture_start = time.time()

            try:
                # Capture screenshot with short timeout for responsiveness
                # Skip slow frames quickly to maintain stream fluidity
                try:
                    screenshot_bytes = await asyncio.wait_for(
                        deps.adb_bridge.capture_screenshot(
                            device_id, force_refresh=True
                        ),
                        timeout=FRAME_CAPTURE_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[WS-MJPEG] Frame {frame_number}: Capture timeout (>{FRAME_CAPTURE_TIMEOUT}s), skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                capture_time = int((time.time() - capture_start) * 1000)  # ms as int

                # Skip if invalid/empty screenshot
                if len(screenshot_bytes) < 1000:
                    logger.warning(
                        f"[WS-MJPEG] Frame {frame_number}: Screenshot too small ({len(screenshot_bytes)} bytes), skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                # Resize and convert to JPEG based on quality preset
                try:
                    jpeg_bytes = resize_image_for_quality(screenshot_bytes, quality)
                    # Verify resize worked - if result is larger than input, skip frame
                    if len(jpeg_bytes) > len(screenshot_bytes) * 0.9:
                        logger.warning(
                            f"[WS-MJPEG] Frame {frame_number}: Resize may have failed (output larger than input), skipping"
                        )
                        await asyncio.sleep(FRAME_SKIP_DELAY)
                        continue
                except Exception as convert_error:
                    logger.warning(
                        f"[WS-MJPEG] Frame {frame_number}: JPEG conversion failed: {convert_error}, skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                # Create binary frame with header
                # Header: 4 bytes frame_number + 4 bytes capture_time
                header = struct.pack(">II", frame_number, capture_time)
                frame_data = header + jpeg_bytes

                # Send binary frame
                await websocket.send_bytes(frame_data)

                # Log periodically
                if frame_number <= 3 or frame_number % 60 == 0:
                    logger.info(
                        f"[WS-MJPEG] Frame {frame_number}: {len(jpeg_bytes)} bytes JPEG, {capture_time}ms capture, quality={quality}"
                    )

                # Sleep based on quality preset (adaptive - skip sleep if already behind)
                elapsed = time.time() - capture_start
                if elapsed < preset["frame_delay"]:
                    await asyncio.sleep(preset["frame_delay"] - elapsed)

            except Exception as capture_error:
                logger.warning(f"[WS-MJPEG] Capture error: {capture_error}")
                # Send error as JSON (not binary)
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": str(capture_error),
                        "timestamp": time.time(),
                    }
                )
                await asyncio.sleep(1)  # Wait before retry

    except WebSocketDisconnect:
        logger.info(f"[WS-MJPEG] Client disconnected: {device_id}")
    except Exception as e:
        logger.error(f"[WS-MJPEG] Connection error: {e}")
    finally:
        logger.info(
            f"[WS-MJPEG] Stream ended for device: {device_id}, frames sent: {frame_number}"
        )
