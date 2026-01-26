"""
Streaming Routes - Live Screenshot Streaming

Provides endpoints for live device streaming:
- HTTP stats endpoints for stream monitoring
- WebSocket JSON streaming (base64 encoded frames)
- WebSocket MJPEG streaming (binary frames, ~30% less bandwidth)

Supports quality presets: high, medium, low, fast
"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends
import logging
import time
import asyncio
import atexit
import base64
import io
import struct
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from routes import get_deps
from routes.auth import verify_companion_auth, verify_companion_ws

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
        "jpeg_quality": 60,  # Reduced for faster encoding
        "target_fps": 18,
        "frame_delay": 0.05,
    },
    "fast": {
        "max_height": 360,
        "jpeg_quality": 45,  # Reduced 55→45 for faster encoding
        "target_fps": 25,
        "frame_delay": 0.04,
    },
    "ultrafast": {
        "max_height": 240,
        "jpeg_quality": 40,  # Reduced 45→40 for fastest encoding
        "target_fps": 30,
        "frame_delay": 0.03,
    },
}

# Frame capture timeout - skip slow frames quickly to maintain responsiveness
FRAME_CAPTURE_TIMEOUT = 3.0  # 3s max per frame for WiFi ADB
FRAME_SKIP_DELAY = 0.1  # Wait time after skipping a frame (was 0.5s)
IMAGE_EXECUTOR = ThreadPoolExecutor(max_workers=4)  # Increased for better multi-client performance
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


async def _require_ws_auth(websocket: WebSocket) -> bool:
    """Enforce companion auth for WebSocket endpoints."""
    if await verify_companion_ws(websocket):
        return True
    await websocket.close(code=1008)
    return False


def create_mjpeg_frame(frame_number: int, capture_time: int, jpeg_bytes: bytes) -> bytes:
    """Create MJPEG frame with 8-byte header.

    Frame format: [frame_number:4][capture_time:4][jpeg_data]
    - frame_number: uint32 big-endian, monotonic frame counter
    - capture_time: uint32 big-endian, capture duration in milliseconds
    - jpeg_data: JPEG image bytes

    Args:
        frame_number: Monotonic frame counter
        capture_time: Capture/encode duration in milliseconds
        jpeg_bytes: JPEG image data

    Returns:
        Complete frame bytes with header
    """
    header = struct.pack(">II", frame_number, capture_time)
    return header + jpeg_bytes


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
        # Track when ADB capture is actively running for streaming-safe element refresh
        self._adb_capture_active: dict[str, bool] = {}
        # Cache latest frame per device for instant display on connect
        self._latest_frames: dict[str, bytes] = {}
        # Track producer lifecycle to prevent race conditions during cleanup
        # When a producer is stopping (in finally block), we must wait before creating new one
        self._producer_stopping: dict[str, asyncio.Event] = {}

    def is_adb_streaming(self, device_id: str) -> bool:
        """Check if ADB capture is actively running for device.

        Used by element refresh to avoid blocking streaming with uiautomator dump.
        """
        return self._adb_capture_active.get(device_id, False)

    def get_latest_frame(self, device_id: str) -> bytes | None:
        """Get the most recent frame for instant display on connect."""
        return self._latest_frames.get(device_id)

    def _broadcast_to_queues(self, queues: list, frame_data: bytes) -> int:
        """Broadcast frame to all subscriber queues.

        Uses non-blocking put with drop-oldest-if-full strategy.

        Args:
            queues: List of asyncio.Queue instances
            frame_data: Binary frame data to broadcast

        Returns:
            Number of queues successfully updated
        """
        queued_count = 0
        for q in queues:
            try:
                q.put_nowait(frame_data)
                queued_count += 1
            except asyncio.QueueFull:
                # Drop oldest frame, add new one
                try:
                    q.get_nowait()
                    q.put_nowait(frame_data)
                    queued_count += 1
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass  # Queue state changed between operations
        return queued_count

    async def subscribe(self, device_id: str, quality: str = "fast") -> asyncio.Queue:
        """Subscribe to frames from a device. Starts producer if needed."""
        logger.info(f"[SharedCapture] subscribe() called for {device_id}, acquiring lock...")

        # Wait for any stopping producer to fully complete before proceeding
        # This prevents race condition where .done() returns True but finally block is still running
        if device_id in self._producer_stopping:
            stopping_event = self._producer_stopping[device_id]
            logger.info(f"[SharedCapture] Waiting for producer {device_id} to finish stopping...")
            try:
                await asyncio.wait_for(stopping_event.wait(), timeout=3.0)
                logger.info(f"[SharedCapture] Producer {device_id} finished stopping")
            except asyncio.TimeoutError:
                logger.warning(f"[SharedCapture] Timeout waiting for producer {device_id} to stop, proceeding anyway")

        try:
            async with asyncio.timeout(5.0):
                async with self._lock:
                    logger.info(f"[SharedCapture] Lock acquired for {device_id}")

                    if device_id not in self._subscribers:
                        self._subscribers[device_id] = []
                        self._frame_counts[device_id] = 0

                    # Create bounded queue for this subscriber (drop old frames if slow)
                    queue: asyncio.Queue = asyncio.Queue(maxsize=3)
                    self._subscribers[device_id].append(queue)

                    # Start producer if not running
                    producer_exists = device_id in self._producers
                    producer_done = self._producers[device_id].done() if producer_exists else True
                    # Also check if producer is in stopping state (finally block executing)
                    producer_stopping = device_id in self._producer_stopping
                    logger.info(
                        f"[SharedCapture] subscribe({device_id}): producer_exists={producer_exists}, "
                        f"producer_done={producer_done}, producer_stopping={producer_stopping}"
                    )

                    if (not producer_exists or producer_done) and not producer_stopping:
                        # Clear any stale stopping event
                        if device_id in self._producer_stopping:
                            del self._producer_stopping[device_id]
                        self._producers[device_id] = asyncio.create_task(
                            self._producer_loop(device_id, quality)
                        )
                        logger.info(f"[SharedCapture] Started NEW producer for {device_id}")
                    elif producer_stopping:
                        logger.warning(f"[SharedCapture] Producer {device_id} still stopping, new producer will start later")
                    else:
                        logger.info(f"[SharedCapture] Producer already running for {device_id}")

                    logger.info(
                        f"[SharedCapture] New subscriber for {device_id}, "
                        f"total: {len(self._subscribers[device_id])}"
                    )
                    return queue
        except asyncio.TimeoutError:
            logger.error(f"[SharedCapture] TIMEOUT waiting for lock for {device_id}! Lock may be deadlocked.")
            raise

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

        logger.info(f"[SharedCapture] Producer loop STARTING for {device_id}, quality={quality}, frame_delay={frame_delay}")

        if deps.adb_bridge and hasattr(deps.adb_bridge, "start_stream"):
            deps.adb_bridge.start_stream(device_id)

        # Track that ADB capture is active for this device
        self._adb_capture_active[device_id] = True

        capture_attempts = 0
        try:
            while True:
                next_tick = await wait_for_next_tick(next_tick, frame_delay)

                # Check if we still have subscribers
                async with self._lock:
                    if device_id not in self._subscribers or not self._subscribers[device_id]:
                        logger.info(f"[SharedCapture] Producer loop exiting - no subscribers for {device_id}")
                        break
                    subscriber_count = len(self._subscribers[device_id])

                capture_attempts += 1
                try:
                    # Track capture start time for duration calculation
                    capture_start = time.monotonic()

                    # Capture frame
                    screenshot_bytes = await asyncio.wait_for(
                        capture_stream_frame(deps, device_id),
                        timeout=FRAME_CAPTURE_TIMEOUT,
                    )

                    # Log first few capture attempts
                    if capture_attempts <= 5:
                        logger.info(f"[SharedCapture] Capture attempt {capture_attempts} for {device_id}: {len(screenshot_bytes)} bytes")

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
                    # Calculate capture+encode duration in milliseconds
                    capture_time = int((time.monotonic() - capture_start) * 1000)

                    # Create frame data (same format as MJPEG v1)
                    frame_data = create_mjpeg_frame(frame_number, capture_time, jpeg_bytes)

                    # Cache frame for instant display on new connections
                    self._latest_frames[device_id] = frame_data

                    # Broadcast to all subscribers using consolidated helper
                    async with self._lock:
                        queues = self._subscribers.get(device_id, [])
                        self._broadcast_to_queues(queues, frame_data)

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
            # Signal that producer is stopping (finally block executing)
            # This prevents race condition where subscribe() creates new producer
            # while this one's cleanup is still in progress
            self._producer_stopping[device_id] = asyncio.Event()
            logger.info(f"[SharedCapture] Producer {device_id} entering cleanup (stopping=True)")

            try:
                # Clear ADB capture flag
                self._adb_capture_active[device_id] = False
                if deps.adb_bridge and hasattr(deps.adb_bridge, "stop_stream"):
                    deps.adb_bridge.stop_stream(device_id)
                logger.info(f"[SharedCapture] Producer {device_id} cleanup complete")
            finally:
                # Signal that producer cleanup is fully complete
                if device_id in self._producer_stopping:
                    self._producer_stopping[device_id].set()
                    # Don't delete the event here - subscribe() will clear it when starting new producer
                    logger.info(f"[SharedCapture] Producer {device_id} signaled cleanup done")

    def get_subscriber_device_ids(self) -> list[str]:
        """Get a safe copy of subscribed device IDs.

        This method returns a snapshot of current subscriber device IDs.
        Safe to call from synchronous callbacks that will later use inject_frame().
        The inject_frame method handles the case where a device_id no longer exists.
        """
        # Copy keys to a list - dict.keys() is a view that could change during iteration
        return list(self._subscribers.keys())

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
        # Cache frame for instant display on new connections
        self._latest_frames[device_id] = frame_data

        async with self._lock:
            if device_id not in self._subscribers:
                # DEBUG: Log when injection fails due to no subscribers
                logger.warning(
                    f"[SharedCapture] inject_frame SKIPPED for {device_id}: "
                    f"not in _subscribers (keys: {list(self._subscribers.keys())})"
                )
                return  # No subscribers for this device

            # Update frame count
            self._frame_counts[device_id] = self._frame_counts.get(device_id, 0) + 1
            frame_number = self._frame_counts[device_id]

            # Broadcast to all subscribers using consolidated helper
            queues = self._subscribers[device_id]
            queued_count = self._broadcast_to_queues(queues, frame_data)

            # Log first 10 frames and then periodically
            if frame_number <= 10 or frame_number % 60 == 0:
                logger.info(
                    f"[SharedCapture] Injected frame {frame_number} for {device_id}: "
                    f"{len(frame_data)} bytes, {queued_count}/{len(queues)} queued"
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
                logger.info(f"[SharedCapture] Created new subscriber entry for {device_id}")

            queue: asyncio.Queue = asyncio.Queue(maxsize=3)
            self._subscribers[device_id].append(queue)

            logger.info(
                f"[SharedCapture] New subscriber (no producer) for {device_id}, "
                f"queue_id={id(queue)}, total: {len(self._subscribers[device_id])}, "
                f"all_devices: {list(self._subscribers.keys())}"
            )
            return queue


# Global shared capture manager instance
shared_capture_manager = SharedCaptureManager()


# =============================================================================
# HTTP STREAMING STATS
# =============================================================================


@router.get("/stream/stats")
async def get_stream_isolation_stats(
    _auth: bool = Depends(verify_companion_auth),
):
    """Get streaming isolation statistics (separate from screenshots)"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "stream": deps.adb_bridge.get_stream_stats()}


# IMPORTANT: Companion routes must come BEFORE {device_id} routes to avoid path conflicts
@router.get("/stream/companion/stats")
async def get_companion_stream_stats(
    _auth: bool = Depends(verify_companion_auth),
):
    """Get statistics about companion app streaming."""
    return {
        "success": True,
        "version": "v2",  # Marker to confirm new code deployed
        "companion_streams": companion_stream_manager.get_stats(),
        "active_devices": companion_stream_manager.get_active_devices()
    }


@router.get("/stream/companion/{device_id}/status")
async def get_companion_device_status(
    device_id: str, _auth: bool = Depends(verify_companion_auth)
):
    """Get companion streaming status for a specific device."""
    is_streaming = companion_stream_manager.is_streaming(device_id)
    stats = companion_stream_manager.get_stats(device_id)

    # Get ADB serial for cross-subnet matching
    deps = get_deps()
    adb_serial = None
    if deps.adb_bridge:
        adb_serial = deps.adb_bridge.get_cached_serial(device_id)

    # Debug info: check IP and serial matching
    found_companion = companion_stream_manager.find_companion_for_device(device_id, adb_serial=adb_serial)
    all_streams = list(companion_stream_manager._streams.keys())

    # Extended debug: check each stream's state
    stream_debug = {}
    target_ip = companion_stream_manager._extract_ip(device_id)
    for cid, cstats in companion_stream_manager._streams.items():
        companion_ip = companion_stream_manager._extract_ip(cid)
        time_since_frame = time.time() - cstats.last_frame_time
        stream_debug[cid] = {
            "disconnected": cstats.disconnected,
            "ip": companion_ip,
            "ip_matches": companion_ip == target_ip,
            "time_since_frame": round(time_since_frame, 1),
            "frame_check_ok": time_since_frame < 5.0,
            "last_frame_time": cstats.last_frame_time
        }

    return {
        "success": True,
        "device_id": device_id,
        "companion_streaming": is_streaming,
        "stats": stats,
        "debug": {
            "target_ip": target_ip,
            "adb_serial": adb_serial,
            "found_companion_id": found_companion,
            "all_registered_streams": all_streams,
            "stream_details": stream_debug,
            "serial_mappings": {
                "serial_to_companion": dict(companion_stream_manager._serial_to_companion),
                "companion_serials": dict(companion_stream_manager._companion_serials)
            }
        }
    }


@router.get("/stream/companion/{device_id}/codec")
async def get_companion_codec_info(
    device_id: str, _auth: bool = Depends(verify_companion_auth)
):
    """
    Get codec information for companion streaming.

    Returns the current codec (JPEG or H.264) and initialization data
    needed by clients to set up their decoder. For H.264, this includes
    the SPS/PPS NAL units in hex format.
    """
    codec_info = companion_stream_manager.get_codec_info(device_id)
    return {
        "success": True,
        "device_id": device_id,
        **codec_info
    }


@router.get("/stream/shared/stats")
async def get_shared_capture_stats(
    _auth: bool = Depends(verify_companion_auth),
):
    """Get statistics about the shared capture pipeline."""
    return {"success": True, "shared_capture": shared_capture_manager.get_stats()}


@router.get("/stream/{device_id}/stats")
async def get_device_stream_stats(
    device_id: str, _auth: bool = Depends(verify_companion_auth)
):
    """Get streaming stats for a specific device"""
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "stream": deps.adb_bridge.get_stream_stats(device_id)}


async def _adb_click_media_projection_dialog(adb_bridge, device_id: str) -> dict:
    """
    Use ADB to find and click the "Start now" button on MediaProjection dialog.

    This is a fallback when the accessibility service auto-click fails.

    Returns:
        dict with success status and details
    """
    import subprocess
    import re

    try:
        # Step 1: Dump UI hierarchy
        logger.info(f"[ADB Fallback] Dumping UI hierarchy for {device_id}")
        result = subprocess.run(
            ["adb", "-s", device_id, "exec-out", "uiautomator", "dump", "/dev/tty"],
            capture_output=True,
            text=True,
            timeout=10
        )

        ui_xml = result.stdout
        if not ui_xml or "hierarchy" not in ui_xml:
            return {"success": False, "error": "Failed to dump UI hierarchy"}

        # Step 2: Look for "Start now" or "Start" button
        # Pattern: text="Start now" ... bounds="[x1,y1][x2,y2]"
        button_patterns = [
            r'text="Start now"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            r'text="Start"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            r'text="시작"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',  # Korean
        ]

        for pattern in button_patterns:
            match = re.search(pattern, ui_xml)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                center_x = (x1 + x2) // 2
                center_y = (y1 + y2) // 2

                logger.info(f"[ADB Fallback] Found button at bounds [{x1},{y1}][{x2},{y2}], tapping at ({center_x}, {center_y})")

                # Step 3: Tap the button
                tap_result = subprocess.run(
                    ["adb", "-s", device_id, "shell", "input", "tap", str(center_x), str(center_y)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if tap_result.returncode == 0:
                    return {
                        "success": True,
                        "method": "adb_tap",
                        "coordinates": {"x": center_x, "y": center_y},
                        "bounds": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
                    }
                else:
                    return {"success": False, "error": f"ADB tap failed: {tap_result.stderr}"}

        # Button not found in UI
        return {"success": False, "error": "MediaProjection dialog button not found in UI hierarchy"}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "ADB command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _resolve_current_adb_device_id(adb_bridge, device_id: str) -> str:
    """
    Resolve the current ADB device ID by matching IP address.
    WiFi ADB ports can change when device reconnects - this finds the current port.

    Returns the current device_id or the original if not found.
    """
    import re

    # Extract IP from provided device ID
    ip_match = re.match(r'^(\d+\.\d+\.\d+\.\d+)', device_id)
    if not ip_match:
        return device_id  # Not IP-based, return as-is

    target_ip = ip_match.group(1)

    try:
        # Get current connected devices
        devices = await adb_bridge.list_devices()

        # Find device with matching IP
        for dev in devices:
            dev_id = dev.get('device_id', '')
            if dev_id.startswith(target_ip + ':'):
                if dev_id != device_id:
                    logger.info(f"[API] Device ID resolved: {device_id} -> {dev_id}")
                return dev_id

        return device_id  # No match found, use original
    except Exception as e:
        logger.warning(f"[API] Failed to resolve device ID: {e}")
        return device_id


@router.post("/stream/companion/{device_id}/restart")
async def restart_companion_streaming(
    device_id: str, _auth: bool = Depends(verify_companion_auth)
):
    """
    Restart streaming on the companion app via MQTT.

    This sends commands to:
    1. restart_streaming - triggers MediaProjection permission dialog
    2. click_media_projection_dialog - auto-clicks "Start now" button

    Useful when companion streaming has stopped and needs to be restarted remotely.
    """
    deps = get_deps()
    if not deps.mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT Manager not initialized")

    # Resolve current ADB device ID (WiFi ADB ports can change)
    original_device_id = device_id
    if deps.adb_bridge:
        device_id = await _resolve_current_adb_device_id(deps.adb_bridge, device_id)

    logger.info(f"[API] Restart companion streaming for {device_id} (original: {original_device_id})")

    # Check MQTT connection status
    mqtt_connected = deps.mqtt_manager.is_connected
    logger.info(f"[API] MQTT broker connected: {mqtt_connected}")

    # Convert device ID to companion format for logging
    companion_device_id = deps.mqtt_manager._get_companion_device_id(device_id)
    logger.info(f"[API] Device ID conversion: {device_id} -> {companion_device_id}")

    # Check if companion is detected as connected
    device_connected = deps.mqtt_manager.is_device_connected(device_id)
    logger.info(f"[API] Companion device detected: {device_connected}")

    try:
        # Step 1: Send restart_streaming command
        restart_result = await deps.mqtt_manager._request_action(
            device_id, "restart_streaming", {}, timeout=5.0
        )

        if not restart_result:
            logger.warning(f"[API] restart_streaming command timed out for {device_id}")
            return {
                "success": False,
                "error": f"restart_streaming command timed out - companion may not be connected via MQTT",
                "debug": {
                    "mqtt_broker_connected": mqtt_connected,
                    "device_id_raw": device_id,
                    "device_id_companion": companion_device_id,
                    "device_detected_in_mqtt": device_connected
                }
            }

        logger.info(f"[API] restart_streaming result: {restart_result}")

        # Step 2: Wait a moment for the MediaProjection dialog to appear
        await asyncio.sleep(1.5)

        # Step 3: Try to auto-click the permission dialog
        click_result = await deps.mqtt_manager._request_action(
            device_id, "click_media_projection_dialog", {}, timeout=5.0
        )

        # Check if click_result indicates actual click success vs just restart initiated
        # The click handler should report about clicking the button, not "Streaming restart initiated"
        click_actually_worked = (
            click_result and
            click_result.get("success") and
            "clicked" in str(click_result.get("data", {})).lower()
        )

        if click_actually_worked:
            logger.info(f"[API] Auto-clicked MediaProjection dialog: {click_result}")
            return {
                "success": True,
                "message": "Streaming restarted and permission dialog auto-approved",
                "restart_result": restart_result,
                "click_result": click_result
            }

        # Step 4: Accessibility auto-click failed or returned wrong response, try ADB fallback
        logger.info(f"[API] Accessibility auto-click may have failed, trying ADB fallback: {click_result}")

        adb_click_result = None
        if deps.adb_bridge:
            try:
                adb_click_result = await _adb_click_media_projection_dialog(deps.adb_bridge, device_id)
                if adb_click_result and adb_click_result.get("success"):
                    logger.info(f"[API] ADB fallback succeeded: {adb_click_result}")
                    return {
                        "success": True,
                        "message": "Streaming restarted - permission dialog clicked via ADB fallback",
                        "restart_result": restart_result,
                        "click_result": click_result,
                        "adb_fallback": adb_click_result
                    }
            except Exception as e:
                logger.warning(f"[API] ADB fallback failed: {e}")
                adb_click_result = {"success": False, "error": str(e)}

        logger.info(f"[API] Could not auto-click dialog (may need manual approval)")
        return {
            "success": True,
            "message": "Streaming restart initiated - permission dialog may need manual approval",
            "restart_result": restart_result,
            "click_result": click_result,
            "adb_fallback": adb_click_result
        }

    except Exception as e:
        logger.error(f"[API] Failed to restart companion streaming: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream/companion/debug")
async def debug_companion_mqtt(_auth: bool = Depends(verify_companion_auth)):
    """
    Debug endpoint to show MQTT state for companion devices.
    """
    deps = get_deps()

    result = {
        "mqtt_connected": False,
        "announced_devices": [],
        "device_capabilities": {},
        "device_info": {},
        "companion_streams": [],
    }

    try:
        if deps.mqtt_manager:
            result["mqtt_connected"] = deps.mqtt_manager.is_connected

            # Get announced devices
            try:
                result["announced_devices"] = deps.mqtt_manager.get_announced_devices()
            except Exception as e:
                result["announced_devices_error"] = str(e)

            # Get device capabilities
            if hasattr(deps.mqtt_manager, "_device_capabilities"):
                result["device_capabilities"] = {k: list(v) if isinstance(v, (list, set)) else v for k, v in deps.mqtt_manager._device_capabilities.items()}

            # Get device info
            if hasattr(deps.mqtt_manager, "_device_info"):
                result["device_info"] = dict(deps.mqtt_manager._device_info)

        if deps.companion_receiver:
            try:
                result["companion_streams"] = deps.companion_receiver.get_active_devices()
            except Exception as e:
                result["companion_streams_error"] = str(e)

    except Exception as e:
        result["error"] = str(e)

    return result


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
    if not await _require_ws_auth(websocket):
        return
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

    if not await _require_ws_auth(websocket):
        return
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
        # Check if companion streaming is active for this device
        companion_active = companion_stream_manager.is_streaming(device_id)

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
                "companion_active": companion_active,
                "message": f"MJPEG binary streaming ready ({'companion' if companion_active else 'ADB'}).",
            }
        )
        logger.info(
            f"[WS-MJPEG] Sent initial config with default dimensions: {device_width}x{device_height} (companion: {companion_active})"
        )

        # If companion streaming is active, subscribe to shared capture manager instead
        if companion_active:
            # Get ADB serial for cross-subnet matching
            adb_serial = None
            if deps.adb_bridge:
                adb_serial = deps.adb_bridge.get_cached_serial(device_id)

            # Find the actual companion device_id (may differ from ADB device_id)
            companion_device_id = companion_stream_manager.find_companion_for_device(
                device_id, adb_serial=adb_serial
            ) or device_id
            logger.info(f"[WS-MJPEG] Using companion stream for {device_id} (companion_id: {companion_device_id}, serial: {adb_serial})")
            queue = await shared_capture_manager.subscribe_without_producer(companion_device_id)

            # Consume frames from companion stream with fallback to ADB
            consecutive_timeouts = 0
            max_timeouts_before_fallback = 3  # 15 seconds of no frames = fallback to ADB

            while True:
                try:
                    frame_data = await asyncio.wait_for(queue.get(), timeout=5.0)
                    await websocket.send_bytes(frame_data)
                    frame_number += 1
                    consecutive_timeouts = 0  # Reset on successful frame

                    if frame_number <= 3 or frame_number % 60 == 0:
                        logger.info(f"[WS-MJPEG] Companion frame {frame_number}: {len(frame_data)} bytes")

                except asyncio.TimeoutError:
                    consecutive_timeouts += 1

                    # Check if companion is still available
                    if not companion_stream_manager.is_streaming(device_id) or consecutive_timeouts >= max_timeouts_before_fallback:
                        logger.info(f"[WS-MJPEG] Companion unavailable for {device_id}, falling back to ADB (timeouts: {consecutive_timeouts})")
                        await shared_capture_manager.unsubscribe(companion_device_id, queue)
                        # Notify frontend
                        await websocket.send_json({
                            "type": "source_change",
                            "source": "adb",
                            "message": "Companion disconnected, switching to ADB"
                        })
                        break  # Exit companion loop to fall through to ADB

                    try:
                        await websocket.send_json({"type": "keepalive", "timestamp": time.time()})
                    except (WebSocketDisconnect, RuntimeError, ConnectionError):
                        await shared_capture_manager.unsubscribe(companion_device_id, queue)
                        raise WebSocketDisconnect(code=1000, reason="Client disconnect")

            # Fall through to ADB capture loop below

        # ADB-based capture loop (also used as fallback from companion)
        # Check for companion availability every 30 frames
        companion_check_interval = 30
        companion_device_id = None
        queue = None

        while True:
            next_tick = await wait_for_next_tick(next_tick, preset["frame_delay"])
            frame_number += 1
            capture_start = time.monotonic()

            # Periodically check if companion streaming became available
            if frame_number % companion_check_interval == 0:
                if companion_stream_manager.is_streaming(device_id):
                    logger.info(f"[WS-MJPEG] Companion now available for {device_id}, switching from ADB")
                    # Notify frontend of source change
                    await websocket.send_json({
                        "type": "source_change",
                        "source": "companion",
                        "message": "Switched to companion streaming for faster performance"
                    })
                    # Get ADB serial for cross-subnet matching
                    adb_serial = None
                    if deps.adb_bridge:
                        adb_serial = deps.adb_bridge.get_cached_serial(device_id)

                    # Switch to companion mode
                    companion_device_id = companion_stream_manager.find_companion_for_device(
                        device_id, adb_serial=adb_serial
                    ) or device_id
                    queue = await shared_capture_manager.subscribe_without_producer(companion_device_id)

                    # Companion streaming loop
                    try:
                        while True:
                            try:
                                frame_data = await asyncio.wait_for(queue.get(), timeout=5.0)
                                await websocket.send_bytes(frame_data)
                                frame_number += 1
                                if frame_number % 60 == 0:
                                    logger.info(f"[WS-MJPEG] Companion frame {frame_number}: {len(frame_data)} bytes")
                            except asyncio.TimeoutError:
                                # Check if companion still available
                                if not companion_stream_manager.is_streaming(device_id):
                                    logger.info(f"[WS-MJPEG] Companion disconnected, switching back to ADB")
                                    break
                                try:
                                    await websocket.send_json({"type": "keepalive", "timestamp": time.time()})
                                except (WebSocketDisconnect, RuntimeError, ConnectionError):
                                    raise WebSocketDisconnect(code=1000, reason="Client disconnect")
                    finally:
                        if queue:
                            await shared_capture_manager.unsubscribe(companion_device_id, queue)
                            queue = None
                    # After companion ends, notify frontend and continue with ADB
                    await websocket.send_json({
                        "type": "source_change",
                        "source": "adb",
                        "message": "Switched back to ADB streaming"
                    })
                    continue  # Continue with ADB capture

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

                # Create binary frame with header using consolidated helper
                frame_data = create_mjpeg_frame(frame_number, capture_time, jpeg_bytes)

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
        # Cleanup based on which mode was used
        if 'queue' in dir() and queue is not None:
            # Companion mode - unsubscribe from shared capture
            unsub_device_id = companion_device_id if 'companion_device_id' in dir() else device_id
            await shared_capture_manager.unsubscribe(unsub_device_id, queue)
        elif deps.adb_bridge and hasattr(deps.adb_bridge, "stop_stream"):
            # ADB mode - stop ADB stream
            deps.adb_bridge.stop_stream(device_id)
        source = "companion" if 'queue' in dir() and queue is not None else "ADB"
        logger.info(
            f"[WS-MJPEG] Stream ended for device: {device_id}, frames sent: {frame_number}, source: {source}"
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
    if not await _require_ws_auth(websocket):
        return
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
        # Check if companion streaming is active for this device
        companion_active = companion_stream_manager.is_streaming(device_id)
        codec_info = companion_stream_manager.get_codec_info(device_id) if companion_active else {}

        # Send config immediately
        await websocket.send_json(
            {
                "type": "config",
                "format": "mjpeg-v2",
                "width": device_width,
                "height": device_height,
                "quality": quality,
                "target_fps": preset["target_fps"],
                "companion_active": companion_active,
                "codec": codec_info.get("codec", "jpeg"),
                "message": f"MJPEG v2 ({'companion' if companion_active else 'ADB'} pipeline) ready.",
            }
        )

        # Send cached frame immediately for instant display on connect
        # This eliminates waiting for the first live frame to arrive
        cached_frame = shared_capture_manager.get_latest_frame(device_id)
        if cached_frame:
            await websocket.send_bytes(cached_frame)
            logger.info(f"[WS-MJPEG-v2] Sent cached frame on connect for {device_id} ({len(cached_frame)} bytes)")

        # Subscribe to shared capture pipeline
        # If companion is streaming, don't start ADB producer - companion frames will be cross-injected
        # IMPORTANT: Always subscribe to the ORIGINAL device_id because:
        # 1. Cross-injection delivers frames to the ADB device_id (e.g., 192.168.86.2:42519)
        # 2. Not to the companion_device_id (e.g., 192_168_86_2_companion)
        using_companion = False
        if companion_active:
            logger.info(f"[WS-MJPEG-v2] Using companion stream for {device_id} (no ADB producer)")
            queue = await shared_capture_manager.subscribe_without_producer(device_id)
            using_companion = True
        else:
            logger.info(f"[WS-MJPEG-v2] Using ADB capture for {device_id} (starting producer)")
            logger.info(f"[WS-MJPEG-v2] About to call shared_capture_manager.subscribe()...")
            try:
                queue = await shared_capture_manager.subscribe(device_id, quality)
                logger.info(f"[WS-MJPEG-v2] Subscribed to ADB capture for {device_id}, queue={queue}")
            except Exception as e:
                logger.error(f"[WS-MJPEG-v2] subscribe() FAILED: {e}")
                import traceback
                logger.error(traceback.format_exc())
                raise

        # Consume frames from queue and send to client
        consecutive_timeouts = 0
        max_timeouts_before_fallback = 1  # 5 seconds of no frames = fallback to ADB (fast fallback)

        while True:
            try:
                # Wait for next frame with timeout
                frame_data = await asyncio.wait_for(queue.get(), timeout=5.0)
                await websocket.send_bytes(frame_data)
                frames_received += 1
                consecutive_timeouts = 0  # Reset on successful frame

                # Log periodically
                if frames_received <= 3 or frames_received % 60 == 0:
                    logger.info(
                        f"[WS-MJPEG-v2] {device_id}: Sent frame {frames_received}, "
                        f"{len(frame_data)} bytes ({'companion' if using_companion else 'ADB'})"
                    )

                # Check if companion became available (when using ADB fallback)
                # Check every 30 frames (~3 seconds at 10fps)
                if not using_companion and frames_received % 30 == 0:
                    if companion_stream_manager.is_streaming(device_id):
                        logger.info(f"[WS-MJPEG-v2] Companion reconnected for {device_id}, switching from ADB")
                        # Unsubscribe from ADB queue (stops producer)
                        old_queue = queue
                        await shared_capture_manager.unsubscribe(device_id, old_queue)
                        # Subscribe without producer (companion will inject frames)
                        queue = await shared_capture_manager.subscribe_without_producer(device_id)
                        logger.info(
                            f"[WS-MJPEG-v2] Switched to companion mode: old_queue={id(old_queue)}, "
                            f"new_queue={id(queue)}, queue_size={queue.qsize()}"
                        )
                        using_companion = True
                        # Notify client
                        await websocket.send_json({
                            "type": "source_change",
                            "source": "companion",
                            "message": "Companion streaming restored - faster mode active"
                        })

            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                logger.debug(
                    f"[WS-MJPEG-v2] Timeout #{consecutive_timeouts} for {device_id}, "
                    f"mode={'companion' if using_companion else 'ADB'}, queue_size={queue.qsize()}"
                )

                # Send keepalive to maintain connection and detect client disconnect
                try:
                    await websocket.send_json({"type": "keepalive"})
                except Exception:
                    logger.info(f"[WS-MJPEG-v2] Client disconnected for {device_id}")
                    break

                # If using companion and no frames for too long, fallback to ADB
                if using_companion and consecutive_timeouts >= max_timeouts_before_fallback:
                    if not companion_stream_manager.is_streaming(device_id):
                        logger.info(f"[WS-MJPEG-v2] Companion disconnected for {device_id}, switching to ADB")
                        # Unsubscribe from companion queue
                        await shared_capture_manager.unsubscribe(device_id, queue)
                        # Subscribe with ADB producer
                        queue = await shared_capture_manager.subscribe(device_id, quality)
                        using_companion = False
                        consecutive_timeouts = 0
                        # Notify client with helpful message
                        await websocket.send_json({
                            "type": "source_change",
                            "source": "adb",
                            "message": "Companion stopped (app launch via ADB). Tap 'Start Streaming' on tablet to restore fast mode.",
                            "reason": "app_launch"
                        })
                        continue

                # Send keepalive or check connection
                try:
                    await websocket.send_json({"type": "keepalive", "timestamp": time.time()})
                except (WebSocketDisconnect, RuntimeError, ConnectionError):
                    break  # WebSocket closed or connection lost

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

    Also supports bidirectional command routing:
    - Backend sends: {"type": "command", "request_id": "uuid", "command": "tap", "params": {...}}
    - Companion responds: {"type": "command_response", "request_id": "uuid", "success": true, ...}

    Wire format for frames (same as MJPEG):
    - Binary JPEG with 8-byte header
        - Bytes 0-3: Frame number (uint32 big-endian)
        - Bytes 4-7: Capture time ms (uint32 big-endian)
        - Bytes 8+: JPEG image data

    Quality control messages (JSON to companion):
    - {"type": "quality", "quality": "fast"}
    - {"type": "pause"}
    - {"type": "resume"}
    """
    if not await _require_ws_auth(websocket):
        return
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

    # Create send function for command routing
    async def send_json_to_companion(data: dict):
        """Send JSON message to companion app."""
        await websocket.send_json(data)

    # Register WebSocket for command routing
    companion_stream_manager.register_websocket_connection(
        device_id, websocket, send_json_to_companion
    )

    # Connect command router to companion receiver
    try:
        from core.command_router import command_router
        companion_stream_manager.set_command_router(command_router)
    except ImportError:
        logger.warning("[Companion-Stream] CommandRouter not available")

    # Track frames for SharedCaptureManager injection
    frames_received = 0

    # Set up frame callback to inject into SharedCaptureManager
    # Use asyncio.create_task to properly call async inject_frame with locking
    def on_companion_frame(frame_data: bytes):
        """Inject companion frame into SharedCaptureManager for web clients."""
        nonlocal frames_received
        frames_received += 1

        # Schedule async injection with proper locking
        try:
            # Get safe snapshot of subscriber device IDs
            # Using method instead of direct access to avoid race conditions
            subscribers = shared_capture_manager.get_subscriber_device_ids()

            # Count how many queues we're injecting to
            injections = 0

            # Helper to handle task exceptions
            def handle_inject_exception(task, target_id):
                try:
                    exc = task.exception()
                    if exc:
                        logger.error(f"[Companion-Stream] inject_frame failed for {target_id}: {exc}")
                except asyncio.CancelledError:
                    pass
                except asyncio.InvalidStateError:
                    pass  # Task not done yet

            # Inject under companion's device_id first
            if device_id in subscribers:
                task = asyncio.create_task(shared_capture_manager.inject_frame(device_id, frame_data))
                task.add_done_callback(lambda t, did=device_id: handle_inject_exception(t, did))
                injections += 1

            # CRITICAL FIX: Also inject to all devices that match this companion
            # This handles IP mismatch between companion (e.g., 192.168.86.129)
            # and ADB device (e.g., 192.168.86.2:5555)
            for subscriber_device_id in subscribers:
                if subscriber_device_id == device_id:
                    continue  # Already injected above

                # Get ADB serial for cross-subnet matching
                # Uses cached serial to avoid async calls in sync callback
                adb_serial = None
                try:
                    deps = get_deps()
                    if deps.adb_bridge:
                        adb_serial = deps.adb_bridge.get_cached_serial(subscriber_device_id)
                except Exception:
                    pass  # Fallback to IP-only matching

                # Check if this subscriber's companion matches us
                matched_companion = companion_stream_manager.find_companion_for_device(
                    subscriber_device_id, adb_serial=adb_serial
                )

                if matched_companion == device_id:
                    task = asyncio.create_task(
                        shared_capture_manager.inject_frame(subscriber_device_id, frame_data)
                    )
                    task.add_done_callback(lambda t, did=subscriber_device_id: handle_inject_exception(t, did))
                    injections += 1
                    # Log first few cross-injections
                    if frames_received <= 5:
                        logger.info(
                            f"[Companion-Stream] Cross-injecting frame to {subscriber_device_id} "
                            f"(companion: {device_id})"
                        )

            # DEBUG: Log injection summary periodically
            if frames_received <= 5 or frames_received % 60 == 0:
                logger.info(
                    f"[Companion-Stream] Frame {frames_received} from {device_id}: "
                    f"{len(frame_data)} bytes, {injections} injections, subscribers: {subscribers}"
                )

            # Warn if no injections happened (frames being lost)
            if injections == 0 and frames_received <= 10:
                logger.warning(
                    f"[Companion-Stream] Frame {frames_received} NOT injected! "
                    f"No subscribers match. companion_id={device_id}, subscribers={subscribers}"
                )

        except RuntimeError as e:
            # No running event loop (shouldn't happen in WebSocket context)
            logger.error(f"[Companion-Stream] RuntimeError in callback: {e}")

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
                        elif msg_type == "command_response":
                            # Route command response to CommandRouter
                            companion_stream_manager.handle_command_response(device_id, data)
                            logger.debug(
                                f"[Companion-Stream] Command response from {device_id}: "
                                f"request_id={data.get('request_id')}, success={data.get('success')}"
                            )
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
        companion_stream_manager.unregister_websocket_connection(device_id)
        await companion_stream_manager.unregister_device(device_id)
        logger.info(
            f"[Companion-Stream] Stream ended for device: {device_id}, "
            f"frames received: {frames_received}"
        )
