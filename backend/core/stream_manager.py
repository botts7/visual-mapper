"""
Stream Manager - Enhanced screenshot capture and streaming for Visual Mapper.

Provides multiple capture backends:
1. adbutils - Modern Python ADB library (faster for many devices)
2. adb_bridge - Existing subprocess-based capture (fallback)
3. subprocess scrcpy - If installed (highest performance)

Created for Phase 2 of the diagnostics/streaming enhancement plan.
"""

import asyncio
import subprocess
import shutil
import time
import logging
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from services.feature_manager import get_feature_manager

# Conditional OpenCV import for basic mode
feature_manager = get_feature_manager()
CV2_AVAILABLE = False
if feature_manager.is_enabled("real_icons_enabled"):
    try:
        import cv2
        CV2_AVAILABLE = True
    except ImportError:
        pass

logger = logging.getLogger(__name__)


class CaptureBackend(Enum):
    """Available capture backends."""
    ADBUTILS = "adbutils"
    ADB_BRIDGE = "adb_bridge"
    SCRCPY = "scrcpy"


@dataclass
class StreamMetrics:
    """Metrics for stream performance tracking."""
    frames_sent: int = 0
    frames_dropped: int = 0
    total_capture_time_ms: float = 0
    total_encode_time_ms: float = 0
    last_capture_time_ms: float = 0
    last_encode_time_ms: float = 0
    start_time: float = field(default_factory=time.time)
    errors: List[str] = field(default_factory=list)

    @property
    def fps(self) -> float:
        """Calculate current FPS."""
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            return self.frames_sent / elapsed
        return 0

    @property
    def avg_capture_time_ms(self) -> float:
        """Average capture time in milliseconds."""
        if self.frames_sent > 0:
            return self.total_capture_time_ms / self.frames_sent
        return 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "frames_sent": self.frames_sent,
            "frames_dropped": self.frames_dropped,
            "fps": round(self.fps, 2),
            "avg_capture_time_ms": round(self.avg_capture_time_ms, 1),
            "last_capture_time_ms": round(self.last_capture_time_ms, 1),
            "last_encode_time_ms": round(self.last_encode_time_ms, 1),
            "uptime_seconds": round(time.time() - self.start_time, 1),
            "recent_errors": self.errors[-5:] if self.errors else []
        }


@dataclass
class QualityPreset:
    """Quality preset for streaming."""
    name: str
    max_size: int  # Max dimension (0 = original)
    jpeg_quality: int  # JPEG quality (1-100)
    target_fps: int  # Target FPS


QUALITY_PRESETS = {
    # Values aligned with routes/streaming.py (authoritative source)
    "high": QualityPreset("high", 0, 85, 5),       # Native resolution, ~5 FPS
    "medium": QualityPreset("medium", 720, 75, 12), # 720p, ~12 FPS
    "low": QualityPreset("low", 480, 65, 18),       # 480p, ~18 FPS
    "fast": QualityPreset("fast", 360, 55, 25),     # 360p, ~25 FPS
    "ultrafast": QualityPreset("ultrafast", 240, 45, 30),  # 240p, ~30 FPS (WiFi)
}


class StreamManager:
    """
    Manages screen capture and streaming for Android devices.

    Supports multiple capture backends with automatic fallback.
    """

    def __init__(self, adb_bridge=None):
        """
        Initialize the stream manager.

        Args:
            adb_bridge: Reference to existing ADBBridge instance for fallback
        """
        self.adb_bridge = adb_bridge
        self.active_streams: Dict[str, asyncio.Task] = {}
        self.metrics: Dict[str, StreamMetrics] = {}
        self.callbacks: Dict[str, List[Callable]] = {}
        self._adbutils_devices: Dict[str, Any] = {}
        self._scrcpy_available: Optional[bool] = None

    def _check_scrcpy_available(self) -> bool:
        """Check if scrcpy is available in PATH."""
        if self._scrcpy_available is None:
            self._scrcpy_available = shutil.which("scrcpy") is not None
        return self._scrcpy_available

    def _get_adbutils_device(self, device_id: str):
        """Get adbutils device connection."""
        if device_id not in self._adbutils_devices:
            try:
                from adbutils import adb
                device = adb.device(serial=device_id)
                self._adbutils_devices[device_id] = device
            except Exception as e:
                logger.warning(f"Failed to connect via adbutils: {e}")
                return None
        return self._adbutils_devices.get(device_id)

    async def capture_screenshot_adbutils(self, device_id: str) -> Optional[bytes]:
        """
        Capture screenshot using adbutils library.

        May be faster than subprocess for some devices.
        """
        try:
            device = self._get_adbutils_device(device_id)
            if device is None:
                return None

            # adbutils screenshot returns PIL Image
            loop = asyncio.get_event_loop()
            pil_image = await loop.run_in_executor(None, device.screenshot)

            if pil_image:
                # Convert PIL to bytes
                import io
                buffer = io.BytesIO()
                pil_image.save(buffer, format='PNG')
                return buffer.getvalue()
            return None
        except Exception as e:
            logger.error(f"adbutils capture failed for {device_id}: {e}")
            return None

    async def capture_screenshot(
        self,
        device_id: str,
        quality: str = "medium",
        backend: CaptureBackend = CaptureBackend.ADB_BRIDGE
    ) -> Optional[bytes]:
        """
        Capture screenshot with quality settings.

        Args:
            device_id: ADB device identifier
            quality: Quality preset name (high, medium, low, fast)
            backend: Capture backend to use

        Returns:
            JPEG bytes or None on failure
        """
        preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["medium"])
        metrics = self.metrics.get(device_id, StreamMetrics())

        # Capture raw screenshot using isolated streaming method
        start_capture = time.time()
        raw_png = None

        try:
            if backend == CaptureBackend.ADBUTILS:
                raw_png = await self.capture_screenshot_adbutils(device_id)

            if raw_png is None and self.adb_bridge:
                # Use isolated stream capture (doesn't block screenshot operations)
                if hasattr(self.adb_bridge, 'capture_stream_frame'):
                    raw_png = await self.adb_bridge.capture_stream_frame(device_id)
                else:
                    # Fallback to regular capture for older versions
                    raw_png = await self.adb_bridge.capture_screenshot(device_id)

        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}")
            metrics.errors.append(str(e))
            return None

        capture_time = (time.time() - start_capture) * 1000
        metrics.last_capture_time_ms = capture_time
        metrics.total_capture_time_ms += capture_time

        if raw_png is None:
            return None

        # Encode to JPEG with quality settings
        start_encode = time.time()
        try:
            jpeg_bytes = await self._encode_jpeg(raw_png, preset)
            encode_time = (time.time() - start_encode) * 1000
            metrics.last_encode_time_ms = encode_time
            metrics.total_encode_time_ms += encode_time
            metrics.frames_sent += 1
            self.metrics[device_id] = metrics
            return jpeg_bytes
        except Exception as e:
            logger.error(f"JPEG encoding failed: {e}")
            metrics.errors.append(f"encode: {e}")
            return None

    async def _encode_jpeg(self, png_bytes: bytes, preset: QualityPreset) -> bytes:
        """Encode PNG to JPEG with quality settings."""
        from PIL import Image
        import io
        from services.feature_manager import get_feature_manager

        feature_manager = get_feature_manager()
        cv2_available = feature_manager.is_enabled("real_icons_enabled")

        loop = asyncio.get_event_loop()

        def encode_cv2():
            # Decode PNG
            nparr = np.frombuffer(png_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                raise ValueError("Failed to decode image")

            # Resize if needed
            if preset.max_size > 0:
                h, w = img.shape[:2]
                if max(h, w) > preset.max_size:
                    scale = preset.max_size / max(h, w)
                    new_size = (int(w * scale), int(h * scale))
                    img = cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)

            # Encode to JPEG
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, preset.jpeg_quality]
            _, jpeg = cv2.imencode('.jpg', img, encode_params)
            return jpeg.tobytes()

        def encode_pil():
            # Decode PNG using PIL
            img = Image.open(io.BytesIO(png_bytes))

            # Resize if needed
            if preset.max_size > 0:
                w, h = img.size
                if max(h, w) > preset.max_size:
                    scale = preset.max_size / max(h, w)
                    new_size = (int(w * scale), int(h * scale))
                    img = img.resize(new_size, Image.LANCZOS)

            # Convert to RGB (JPEGs don't support RGBA)
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Encode to JPEG
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=preset.jpeg_quality)
            return buffer.getvalue()

        if cv2_available:
            try:
                import cv2
                return await loop.run_in_executor(None, encode_cv2)
            except Exception as e:
                logger.warning(f"OpenCV JPEG encoding failed, falling back to PIL: {e}")

        return await loop.run_in_executor(None, encode_pil)

    async def start_stream(
        self,
        device_id: str,
        quality: str = "medium",
        on_frame: Optional[Callable[[bytes], None]] = None
    ) -> bool:
        """
        Start streaming for a device.

        Args:
            device_id: ADB device identifier
            quality: Quality preset name
            on_frame: Callback for each frame (JPEG bytes)

        Returns:
            True if stream started successfully
        """
        if device_id in self.active_streams:
            logger.warning(f"Stream already active for {device_id}")
            return False

        preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["medium"])
        self.metrics[device_id] = StreamMetrics()

        if on_frame:
            if device_id not in self.callbacks:
                self.callbacks[device_id] = []
            self.callbacks[device_id].append(on_frame)

        async def stream_loop():
            target_interval = 1.0 / preset.target_fps

            while True:
                try:
                    start = time.time()

                    jpeg = await self.capture_screenshot(device_id, quality)

                    if jpeg:
                        for callback in self.callbacks.get(device_id, []):
                            try:
                                callback(jpeg)
                            except Exception as e:
                                logger.error(f"Frame callback error: {e}")

                    # Maintain target FPS
                    elapsed = time.time() - start
                    sleep_time = max(0, target_interval - elapsed)
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                    else:
                        # Can't keep up with target FPS
                        metrics = self.metrics.get(device_id)
                        if metrics:
                            metrics.frames_dropped += 1

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Stream loop error: {e}")
                    await asyncio.sleep(1)  # Back off on error

        self.active_streams[device_id] = asyncio.create_task(stream_loop())

        # Notify adb_bridge that streaming started (for isolation tracking)
        if self.adb_bridge and hasattr(self.adb_bridge, 'start_stream'):
            self.adb_bridge.start_stream(device_id)

        logger.info(f"Started stream for {device_id} at {preset.name} quality")
        return True

    async def stop_stream(self, device_id: str):
        """Stop streaming for a device."""
        if device_id in self.active_streams:
            self.active_streams[device_id].cancel()
            try:
                await self.active_streams[device_id]
            except asyncio.CancelledError:
                pass
            del self.active_streams[device_id]

            # Notify adb_bridge that streaming stopped
            if self.adb_bridge and hasattr(self.adb_bridge, 'stop_stream'):
                self.adb_bridge.stop_stream(device_id)

            logger.info(f"Stopped stream for {device_id}")

        if device_id in self.callbacks:
            del self.callbacks[device_id]

    def add_callback(self, device_id: str, callback: Callable[[bytes], None]):
        """Add a frame callback for a device."""
        if device_id not in self.callbacks:
            self.callbacks[device_id] = []
        self.callbacks[device_id].append(callback)

    def remove_callback(self, device_id: str, callback: Callable[[bytes], None]):
        """Remove a frame callback."""
        if device_id in self.callbacks:
            try:
                self.callbacks[device_id].remove(callback)
            except ValueError:
                pass

    def get_metrics(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get streaming metrics for a device."""
        metrics = self.metrics.get(device_id)
        if metrics:
            return metrics.to_dict()
        return None

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all devices."""
        return {
            device_id: metrics.to_dict()
            for device_id, metrics in self.metrics.items()
        }

    async def benchmark_capture(
        self,
        device_id: str,
        iterations: int = 5
    ) -> Dict[str, Any]:
        """
        Benchmark capture performance for different backends.

        Args:
            device_id: ADB device identifier
            iterations: Number of captures per backend

        Returns:
            Dictionary with benchmark results
        """
        results = {
            "device_id": device_id,
            "iterations": iterations,
            "backends": {}
        }

        # Test adbutils backend
        try:
            times = []
            for _ in range(iterations):
                start = time.time()
                img = await self.capture_screenshot_adbutils(device_id)
                if img:
                    times.append((time.time() - start) * 1000)

            if times:
                results["backends"]["adbutils"] = {
                    "available": True,
                    "min_ms": round(min(times), 1),
                    "max_ms": round(max(times), 1),
                    "avg_ms": round(sum(times) / len(times), 1),
                    "successful": len(times)
                }
            else:
                results["backends"]["adbutils"] = {"available": False, "error": "No successful captures"}
        except Exception as e:
            results["backends"]["adbutils"] = {"available": False, "error": str(e)}

        # Test adb_bridge backend
        if self.adb_bridge:
            try:
                times = []
                for _ in range(iterations):
                    start = time.time()
                    img = await self.adb_bridge.capture_screenshot(device_id)
                    if img:
                        times.append((time.time() - start) * 1000)

                if times:
                    results["backends"]["adb_bridge"] = {
                        "available": True,
                        "min_ms": round(min(times), 1),
                        "max_ms": round(max(times), 1),
                        "avg_ms": round(sum(times) / len(times), 1),
                        "successful": len(times)
                    }
                else:
                    results["backends"]["adb_bridge"] = {"available": False, "error": "No successful captures"}
            except Exception as e:
                results["backends"]["adb_bridge"] = {"available": False, "error": str(e)}

        # Check scrcpy availability
        results["backends"]["scrcpy"] = {
            "available": self._check_scrcpy_available(),
            "note": "Install scrcpy for 30-60 FPS streaming"
        }

        # Recommend best backend
        best_backend = None
        best_time = float('inf')

        for name, data in results["backends"].items():
            if data.get("available") and "avg_ms" in data:
                if data["avg_ms"] < best_time:
                    best_time = data["avg_ms"]
                    best_backend = name

        results["recommended_backend"] = best_backend
        results["best_avg_ms"] = round(best_time, 1) if best_time < float('inf') else None

        return results


# Global instance
stream_manager: Optional[StreamManager] = None


def get_stream_manager(adb_bridge=None) -> StreamManager:
    """Get or create the global stream manager instance."""
    global stream_manager
    if stream_manager is None:
        stream_manager = StreamManager(adb_bridge)
    elif adb_bridge is not None and stream_manager.adb_bridge is None:
        stream_manager.adb_bridge = adb_bridge
    return stream_manager
