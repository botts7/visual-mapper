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
import atexit
import base64
import io
from concurrent.futures import ThreadPoolExecutor
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
IMAGE_EXECUTOR = ThreadPoolExecutor(max_workers=2)
atexit.register(IMAGE_EXECUTOR.shutdown, wait=False)


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


async def resize_image_for_quality_async(img_bytes: bytes, quality: str) -> bytes:
    """Run PIL resize/encode off the event loop to avoid stalling other clients."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        IMAGE_EXECUTOR, resize_image_for_quality, img_bytes, quality
    )


async def capture_stream_frame(
    deps, device_id: str, timeout: float = FRAME_CAPTURE_TIMEOUT
) -> bytes:
    """Capture a streaming frame with the fastest available backend."""
    if not deps.adb_bridge:
        return b""
    if hasattr(deps.adb_bridge, "capture_stream_frame"):
        return await deps.adb_bridge.capture_stream_frame(
            device_id, timeout=timeout
        )
    return await deps.adb_bridge.capture_screenshot(
        device_id, force_refresh=True, timeout=timeout
    )


async def wait_for_next_tick(next_tick: float, frame_delay: float) -> float:
    """Drift-resistant pacing using a monotonic clock."""
    now = time.monotonic()
    if now < next_tick:
        await asyncio.sleep(next_tick - now)
        return next_tick + frame_delay
    if now - next_tick > frame_delay:
        return now + frame_delay
    return next_tick + frame_delay


# =============================================================================
# SHARED CAPTURE PIPELINE (MJPEG v2)
# Single producer per device, broadcasts to all subscribers
# =============================================================================


class SharedCaptureManager:
    """Manages shared capture pipelines per device.

    Instead of each WebSocket connection running its own capture loop,
    a single producer captures frames and broadcasts to all subscribers.
    This eliminates per-frame ADB handshake overhead for multiple clients.
    """

    def __init__(self):
        self._producers: dict[str, asyncio.Task] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._frame_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, device_id: str, quality: str = "fast") -> asyncio.Queue:
        """Subscribe to frames from a device. Starts producer if needed."""
        async with self._lock:
            if device_id not in self._subscribers:
                self._subscribers[device_id] = []
                self._frame_counts[device_id] = 0

            # Create bounded queue for this subscriber (drop old frames if slow)
            queue: asyncio.Queue = asyncio.Queue(maxsize=3)
            self._subscribers[device_id].append(queue)

            # Start producer if not running
            if device_id not in self._producers or self._producers[device_id].done():
                self._producers[device_id] = asyncio.create_task(
                    self._producer_loop(device_id, quality)
                )
                logger.info(f"[SharedCapture] Started producer for {device_id}")

            logger.info(
                f"[SharedCapture] New subscriber for {device_id}, "
                f"total: {len(self._subscribers[device_id])}"
            )
            return queue

    async def unsubscribe(self, device_id: str, queue: asyncio.Queue):
        """Unsubscribe from a device. Stops producer if no subscribers left."""
        async with self._lock:
            if device_id in self._subscribers:
                try:
                    self._subscribers[device_id].remove(queue)
                except ValueError:
                    pass

                logger.info(
                    f"[SharedCapture] Subscriber left {device_id}, "
                    f"remaining: {len(self._subscribers[device_id])}"
                )

                # Stop producer if no subscribers
                if not self._subscribers[device_id]:
                    if device_id in self._producers:
                        self._producers[device_id].cancel()
                        try:
                            await self._producers[device_id]
                        except asyncio.CancelledError:
                            pass
                        del self._producers[device_id]
                        logger.info(f"[SharedCapture] Stopped producer for {device_id}")
                    del self._subscribers[device_id]
                    if device_id in self._frame_counts:
                        del self._frame_counts[device_id]

    async def _producer_loop(self, device_id: str, quality: str):
        """Single capture loop that broadcasts to all subscribers."""
        deps = get_deps()
        preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["fast"])
        frame_delay = preset["frame_delay"]
        next_tick = time.monotonic()

        if deps.adb_bridge and hasattr(deps.adb_bridge, "start_stream"):
            deps.adb_bridge.start_stream(device_id)

        try:
            while True:
                next_tick = await wait_for_next_tick(next_tick, frame_delay)

                # Check if we still have subscribers
                async with self._lock:
                    if device_id not in self._subscribers or not self._subscribers[device_id]:
                        break

                try:
                    # Capture frame
                    screenshot_bytes = await asyncio.wait_for(
                        capture_stream_frame(deps, device_id),
                        timeout=FRAME_CAPTURE_TIMEOUT,
                    )

                    if len(screenshot_bytes) < 1000:
                        await asyncio.sleep(FRAME_SKIP_DELAY)
                        continue

                    # Process frame
                    jpeg_bytes = await resize_image_for_quality_async(
                        screenshot_bytes, quality
                    )

                    # Increment frame count
                    self._frame_counts[device_id] = self._frame_counts.get(device_id, 0) + 1
                    frame_number = self._frame_counts[device_id]
                    capture_time = int(time.monotonic() * 1000) % (2**32)

                    # Create frame data (same format as MJPEG v1)
                    import struct
                    header = struct.pack(">II", frame_number, capture_time)
                    frame_data = header + jpeg_bytes

                    # Broadcast to all subscribers
                    async with self._lock:
                        queues = self._subscribers.get(device_id, [])
                        for q in queues:
                            try:
                                # Non-blocking put - drop frame if queue full
                                q.put_nowait(frame_data)
                            except asyncio.QueueFull:
                                # Drop oldest frame, add new one
                                try:
                                    q.get_nowait()
                                    q.put_nowait(frame_data)
                                except:
                                    pass

                    # Log periodically
                    if frame_number <= 3 or frame_number % 60 == 0:
                        logger.info(
                            f"[SharedCapture] {device_id} frame {frame_number}: "
                            f"{len(jpeg_bytes)} bytes, {len(queues)} subscribers"
                        )

                except asyncio.TimeoutError:
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                except Exception as e:
                    logger.warning(f"[SharedCapture] Capture error: {e}")
                    await asyncio.sleep(FRAME_SKIP_DELAY)

        except asyncio.CancelledError:
            logger.info(f"[SharedCapture] Producer cancelled for {device_id}")
        finally:
            if deps.adb_bridge and hasattr(deps.adb_bridge, "stop_stream"):
                deps.adb_bridge.stop_stream(device_id)

    def get_stats(self) -> dict:
        """Get stats about active producers and subscribers."""
        return {
            "active_devices": list(self._producers.keys()),
            "subscribers": {
                device_id: len(subs)
                for device_id, subs in self._subscribers.items()
            },
            "frame_counts": dict(self._frame_counts),
        }

    async def inject_frame(self, device_id: str, frame_data: bytes):
        """
        Inject a frame from an external source (like companion app).

        This allows the companion app to push frames that get distributed
        to all subscribers for that device without starting the ADB producer.

        Args:
            device_id: The device identifier
            frame_data: Binary frame data (8-byte header + JPEG)
        """
        async with self._lock:
            if device_id not in self._subscribers:
                return  # No subscribers for this device

            # Update frame count
            self._frame_counts[device_id] = self._frame_counts.get(device_id, 0) + 1
            frame_number = self._frame_counts[device_id]

            # Broadcast to all subscribers
            queues = self._subscribers[device_id]
            for q in queues:
                try:
                    q.put_nowait(frame_data)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                        q.put_nowait(frame_data)
                    except:
                        pass

            # Log periodically
            if frame_number == 1 or frame_number % 60 == 0:
                logger.info(
                    f"[SharedCapture] Injected frame {frame_number} for {device_id}: "
                    f"{len(frame_data)} bytes, {len(queues)} subscribers"
                )

    async def subscribe_without_producer(self, device_id: str) -> asyncio.Queue:
        """
        Subscribe to frames for a device without starting the ADB producer.

        Use this when frames will be provided by an external source
        (like the companion app) via inject_frame().
        """
        async with self._lock:
            if device_id not in self._subscribers:
                self._subscribers[device_id] = []
                self._frame_counts[device_id] = 0

            queue: asyncio.Queue = asyncio.Queue(maxsize=3)
            self._subscribers[device_id].append(queue)

            logger.info(
                f"[SharedCapture] New subscriber (no producer) for {device_id}, "
                f"total: {len(self._subscribers[device_id])}"
            )
            return queue


# Global shared capture manager instance
shared_capture_manager = SharedCaptureManager()


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
    if deps.adb_bridge and hasattr(deps.adb_bridge, "start_stream"):
        deps.adb_bridge.start_stream(device_id)

    # Parse quality from query string (default 'fast' for WiFi compatibility)
    quality = websocket.query_params.get("quality", "fast")
    if quality not in QUALITY_PRESETS:
        quality = "fast"
    preset = QUALITY_PRESETS[quality]

    logger.info(
        f"[WS-Stream] Client connected for device: {device_id}, quality: {quality} (target {preset['target_fps']} FPS)"
    )

    frame_number = 0
    device_width, device_height = 1080, 1920  # Defaults
    next_tick = time.monotonic()

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
            next_tick = await wait_for_next_tick(next_tick, preset["frame_delay"])
            frame_number += 1
            capture_start = time.monotonic()

            try:
                # Capture screenshot with short timeout for responsiveness
                # Skip slow frames quickly to maintain stream fluidity
                try:
                    screenshot_bytes = await asyncio.wait_for(
                        capture_stream_frame(deps, device_id),
                        timeout=FRAME_CAPTURE_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[WS-Stream] Frame {frame_number}: Capture timeout (>{FRAME_CAPTURE_TIMEOUT}s), skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                capture_time = (time.monotonic() - capture_start) * 1000  # ms

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
                    processed_bytes = await resize_image_for_quality_async(
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
        if deps.adb_bridge and hasattr(deps.adb_bridge, "stop_stream"):
            deps.adb_bridge.stop_stream(device_id)
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
    if deps.adb_bridge and hasattr(deps.adb_bridge, "start_stream"):
        deps.adb_bridge.start_stream(device_id)

    # Parse quality from query string (default 'fast' for WiFi compatibility)
    quality = websocket.query_params.get("quality", "fast")
    if quality not in QUALITY_PRESETS:
        quality = "fast"
    preset = QUALITY_PRESETS[quality]

    logger.info(
        f"[WS-MJPEG] Client connected for device: {device_id}, quality: {quality} (target {preset['target_fps']} FPS)"
    )

    frame_number = 0
    device_width, device_height = 1080, 1920  # Defaults
    next_tick = time.monotonic()

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
            next_tick = await wait_for_next_tick(next_tick, preset["frame_delay"])
            frame_number += 1
            capture_start = time.monotonic()

            try:
                # Capture screenshot with short timeout for responsiveness
                # Skip slow frames quickly to maintain stream fluidity
                try:
                    screenshot_bytes = await asyncio.wait_for(
                        capture_stream_frame(deps, device_id),
                        timeout=FRAME_CAPTURE_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[WS-MJPEG] Frame {frame_number}: Capture timeout (>{FRAME_CAPTURE_TIMEOUT}s), skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                capture_time = int((time.monotonic() - capture_start) * 1000)  # ms as int

                # Skip if invalid/empty screenshot
                if len(screenshot_bytes) < 1000:
                    logger.warning(
                        f"[WS-MJPEG] Frame {frame_number}: Screenshot too small ({len(screenshot_bytes)} bytes), skipping"
                    )
                    await asyncio.sleep(FRAME_SKIP_DELAY)
                    continue

                # Resize and convert to JPEG based on quality preset
                try:
                    jpeg_bytes = await resize_image_for_quality_async(
                        screenshot_bytes, quality
                    )
                    # Verify resize worked - only skip if output is significantly larger than input
                    # (PNG->JPEG should always shrink; only skip on clear failure)
                    if len(jpeg_bytes) > len(screenshot_bytes) * 1.5:
                        logger.warning(
                            f"[WS-MJPEG] Frame {frame_number}: Resize may have failed (output 50%+ larger than input), skipping"
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
        if deps.adb_bridge and hasattr(deps.adb_bridge, "stop_stream"):
            deps.adb_bridge.stop_stream(device_id)
        logger.info(
            f"[WS-MJPEG] Stream ended for device: {device_id}, frames sent: {frame_number}"
        )


# =============================================================================
# WEBSOCKET MJPEG V2 - SHARED CAPTURE PIPELINE
# =============================================================================


@router.websocket("/ws/stream-mjpeg-v2/{device_id}")
async def stream_device_mjpeg_v2(websocket: WebSocket, device_id: str):
    """
    WebSocket endpoint for MJPEG v2 streaming with shared capture pipeline.

    Uses a single capture producer per device that broadcasts to all subscribers.
    This eliminates per-frame ADB handshake overhead when multiple clients connect.

    Wire format is identical to MJPEG v1 for client compatibility:
    - First message: JSON config
    - Subsequent messages: Binary JPEG with 8-byte header (frame_number, capture_time)

    Query params:
    - quality: 'high', 'medium', 'low', 'fast', 'ultrafast' (default: fast)
    """
    await websocket.accept()

    # Parse quality from query string
    quality = websocket.query_params.get("quality", "fast")
    if quality not in QUALITY_PRESETS:
        quality = "fast"
    preset = QUALITY_PRESETS[quality]

    logger.info(
        f"[WS-MJPEG-v2] Client connected for device: {device_id}, quality: {quality} "
        f"(target {preset['target_fps']} FPS, shared pipeline)"
    )

    device_width, device_height = 1080, 1920  # Defaults
    frames_received = 0
    queue = None

    try:
        # Send config immediately
        await websocket.send_json(
            {
                "type": "config",
                "format": "mjpeg-v2",
                "width": device_width,
                "height": device_height,
                "quality": quality,
                "target_fps": preset["target_fps"],
                "message": "MJPEG v2 (shared pipeline) ready. Subsequent frames are binary.",
            }
        )

        # Subscribe to shared capture pipeline
        queue = await shared_capture_manager.subscribe(device_id, quality)

        # Consume frames from queue and send to client
        while True:
            try:
                # Wait for next frame with timeout
                frame_data = await asyncio.wait_for(queue.get(), timeout=5.0)
                await websocket.send_bytes(frame_data)
                frames_received += 1

                # Log periodically
                if frames_received <= 3 or frames_received % 60 == 0:
                    logger.info(
                        f"[WS-MJPEG-v2] {device_id}: Sent frame {frames_received}, "
                        f"{len(frame_data)} bytes"
                    )

            except asyncio.TimeoutError:
                # No frame in 5s - send keepalive or check connection
                try:
                    await websocket.send_json({"type": "keepalive", "timestamp": time.time()})
                except:
                    break

    except WebSocketDisconnect:
        logger.info(f"[WS-MJPEG-v2] Client disconnected: {device_id}")
    except Exception as e:
        logger.error(f"[WS-MJPEG-v2] Connection error: {e}")
    finally:
        if queue:
            await shared_capture_manager.unsubscribe(device_id, queue)
        logger.info(
            f"[WS-MJPEG-v2] Stream ended for device: {device_id}, frames sent: {frames_received}"
        )


@router.get("/stream/shared/stats")
async def get_shared_capture_stats():
    """Get statistics about the shared capture pipeline."""
    return {"success": True, "shared_capture": shared_capture_manager.get_stats()}


# =============================================================================
# COMPANION APP STREAMING - Receives frames from Android companion app
# =============================================================================

# Import companion receiver
from core.streaming.companion_receiver import companion_stream_manager


@router.websocket("/ws/companion-stream/{device_id}")
async def companion_stream(websocket: WebSocket, device_id: str):
    """
    WebSocket endpoint for receiving screen captures from Android companion app.

    The companion app uses MediaProjection to capture the screen and streams
    MJPEG frames to this endpoint. Frames are then injected into the
    SharedCaptureManager for distribution to all web UI clients.

    Wire format (same as MJPEG):
    - Binary JPEG with 8-byte header
        - Bytes 0-3: Frame number (uint32 big-endian)
        - Bytes 4-7: Capture time ms (uint32 big-endian)
        - Bytes 8+: JPEG image data

    Quality control messages (JSON to companion):
    - {"type": "quality", "quality": "fast"}
    - {"type": "pause"}
    - {"type": "resume"}
    """
    await websocket.accept()

    # Register device with companion receiver
    registered = await companion_stream_manager.register_device(device_id)
    if not registered:
        logger.warning(f"[Companion-Stream] Device {device_id} already streaming")
        await websocket.send_json({
            "type": "error",
            "message": "Device already streaming from companion"
        })
        await websocket.close()
        return

    logger.info(f"[Companion-Stream] Companion app connected for device: {device_id}")

    # Track frames for SharedCaptureManager injection
    frames_received = 0

    # Set up frame callback to inject into SharedCaptureManager
    def on_companion_frame(frame_data: bytes):
        """Inject companion frame into SharedCaptureManager for web clients."""
        nonlocal frames_received
        frames_received += 1

        # Get subscribers for this device
        if device_id in shared_capture_manager._subscribers:
            queues = shared_capture_manager._subscribers[device_id]
            for q in queues:
                try:
                    q.put_nowait(frame_data)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                        q.put_nowait(frame_data)
                    except:
                        pass

    companion_stream_manager.set_frame_callback(device_id, on_companion_frame)

    try:
        # Send config to companion app
        await websocket.send_json({
            "type": "config",
            "message": "Companion stream ready. Send binary MJPEG frames.",
            "quality": "fast"
        })

        while True:
            try:
                # Receive frame from companion app
                message = await websocket.receive()

                if "bytes" in message:
                    # Binary frame data
                    frame_data = message["bytes"]
                    await companion_stream_manager.receive_frame(device_id, frame_data)

                elif "text" in message:
                    # JSON control message from companion
                    import json
                    try:
                        data = json.loads(message["text"])
                        msg_type = data.get("type", "")
                        if msg_type == "stats":
                            # Companion requesting stats
                            stats = companion_stream_manager.get_stats(device_id)
                            await websocket.send_json({
                                "type": "stats",
                                "data": stats
                            })
                        elif msg_type == "ping":
                            await websocket.send_json({"type": "pong", "timestamp": time.time()})
                    except json.JSONDecodeError:
                        pass

            except WebSocketDisconnect:
                logger.info(f"[Companion-Stream] Companion disconnected: {device_id}")
                break
            except Exception as e:
                logger.error(f"[Companion-Stream] Error receiving frame: {e}")
                break

    except Exception as e:
        logger.error(f"[Companion-Stream] Connection error: {e}")
    finally:
        # Cleanup
        companion_stream_manager.remove_frame_callback(device_id)
        await companion_stream_manager.unregister_device(device_id)
        logger.info(
            f"[Companion-Stream] Stream ended for device: {device_id}, "
            f"frames received: {frames_received}"
        )


@router.get("/stream/companion/stats")
async def get_companion_stream_stats():
    """Get statistics about companion app streaming."""
    return {
        "success": True,
        "version": "v2",  # Marker to confirm new code deployed
        "companion_streams": companion_stream_manager.get_stats(),
        "active_devices": companion_stream_manager.get_active_devices()
    }


@router.get("/stream/companion/{device_id}/status")
async def get_companion_device_status(device_id: str):
    """Get companion streaming status for a specific device."""
    is_streaming = companion_stream_manager.is_streaming(device_id)
    stats = companion_stream_manager.get_stats(device_id)

    return {
        "success": True,
        "device_id": device_id,
        "companion_streaming": is_streaming,
        "stats": stats
    }
