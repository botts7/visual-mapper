"""
Companion Stream Receiver - Receives video frames from Android companion app.

This module receives MediaProjection-based screen captures from the companion app
via WebSocket and injects them into the SharedCaptureManager for distribution
to web UI clients. This provides significantly lower latency than ADB capture.

Target latency: 50-150ms (vs 100-3000ms for WiFi ADB)
"""

import asyncio
import logging
import time
import struct
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CompanionStreamStats:
    """Statistics for a companion stream."""
    frames_received: int = 0
    bytes_received: int = 0
    last_frame_time: float = 0.0
    connect_time: float = field(default_factory=time.time)
    disconnected: bool = False
    last_error: Optional[str] = None
    # Frame dimensions from latest frame (for orientation detection)
    frame_width: int = 0
    frame_height: int = 0

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.connect_time

    @property
    def fps(self) -> float:
        if self.uptime_seconds > 1:
            return self.frames_received / self.uptime_seconds
        return 0.0

    @property
    def orientation(self) -> str:
        """Detect orientation from frame dimensions."""
        if self.frame_width == 0 or self.frame_height == 0:
            return "unknown"
        return "landscape" if self.frame_width > self.frame_height else "portrait"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frames_received": self.frames_received,
            "bytes_received": self.bytes_received,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "fps": round(self.fps, 2),
            "connected": not self.disconnected,
            "last_error": self.last_error,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "orientation": self.orientation
        }


class CompanionStreamReceiver:
    """
    Manages WebSocket connections from companion apps for video streaming.

    Receives MJPEG frames from companion apps and injects them into the
    SharedCaptureManager for distribution to all subscribed web clients.
    """

    def __init__(self):
        self._streams: Dict[str, CompanionStreamStats] = {}
        self._frame_callbacks: Dict[str, Callable[[bytes], None]] = {}
        self._lock = asyncio.Lock()

    async def register_device(self, device_id: str) -> bool:
        """Register a device for companion streaming."""
        async with self._lock:
            if device_id in self._streams and not self._streams[device_id].disconnected:
                logger.warning(f"[CompanionReceiver] Device {device_id} already streaming")
                return False

            self._streams[device_id] = CompanionStreamStats()
            logger.info(f"[CompanionReceiver] Registered device: {device_id}")
            return True

    async def unregister_device(self, device_id: str):
        """Unregister a device from companion streaming."""
        async with self._lock:
            if device_id in self._streams:
                self._streams[device_id].disconnected = True
                logger.info(f"[CompanionReceiver] Unregistered device: {device_id}")

            if device_id in self._frame_callbacks:
                del self._frame_callbacks[device_id]

    async def receive_frame(self, device_id: str, frame_data: bytes) -> bool:
        """
        Receive a frame from the companion app.

        Frame format v2: 12-byte header + JPEG data
        - Bytes 0-3: Frame number (uint32 big-endian)
        - Bytes 4-7: Capture time ms (uint32 big-endian)
        - Bytes 8-9: Width (uint16 big-endian)
        - Bytes 10-11: Height (uint16 big-endian)
        - Bytes 12+: JPEG image data

        Also supports legacy 8-byte header for backwards compatibility.

        Args:
            device_id: The device identifier
            frame_data: Binary frame data

        Returns:
            True if frame was processed successfully
        """
        if len(frame_data) < 14:  # 12-byte header + at least 2 bytes JPEG
            logger.warning(f"[CompanionReceiver] Frame too small: {len(frame_data)} bytes")
            return False

        stats = self._streams.get(device_id)
        if not stats:
            logger.warning(f"[CompanionReceiver] Unknown device: {device_id}")
            return False

        if stats.disconnected:
            return False

        # Parse header - try 12-byte format first (v2), fall back to 8-byte (v1)
        try:
            frame_number, capture_time, width, height = struct.unpack(">IIHH", frame_data[:12])
            header_size = 12
            # Sanity check dimensions (valid if reasonable and make the frame size match)
            if width < 100 or width > 4096 or height < 100 or height > 4096:
                # May be old 8-byte format - width/height look like JPEG marker bytes
                frame_number, capture_time = struct.unpack(">II", frame_data[:8])
                width, height = 0, 0
                header_size = 8
        except struct.error as e:
            logger.error(f"[CompanionReceiver] Invalid frame header: {e}")
            return False

        # Update stats
        stats.frames_received += 1
        stats.bytes_received += len(frame_data)
        stats.last_frame_time = time.time()
        if width > 0 and height > 0:
            stats.frame_width = width
            stats.frame_height = height

        # Log periodically (include orientation)
        if stats.frames_received == 1 or stats.frames_received % 60 == 0:
            jpeg_size = len(frame_data) - header_size
            dim_info = f"{width}x{height} ({stats.orientation})" if width > 0 else "no dims"
            logger.info(
                f"[CompanionReceiver] {device_id} frame {frame_number}: "
                f"{jpeg_size} bytes, {dim_info}, FPS: {stats.fps:.1f}"
            )

        # Invoke frame callback if registered (for SharedCaptureManager injection)
        callback = self._frame_callbacks.get(device_id)
        if callback:
            try:
                callback(frame_data)
            except Exception as e:
                logger.error(f"[CompanionReceiver] Frame callback error: {e}")
                stats.last_error = str(e)
                return False

        return True

    def set_frame_callback(self, device_id: str, callback: Callable[[bytes], None]):
        """
        Set a callback to receive frames for a device.

        The callback receives the complete frame data (header + JPEG).
        This is used to inject frames into SharedCaptureManager.
        """
        self._frame_callbacks[device_id] = callback
        logger.debug(f"[CompanionReceiver] Frame callback set for {device_id}")

    def remove_frame_callback(self, device_id: str):
        """Remove the frame callback for a device."""
        if device_id in self._frame_callbacks:
            del self._frame_callbacks[device_id]

    def is_streaming(self, device_id: str) -> bool:
        """Check if a device is actively streaming via companion app."""
        stats = self._streams.get(device_id)
        if not stats or stats.disconnected:
            return False

        # Consider active if received a frame in the last 5 seconds
        time_since_frame = time.time() - stats.last_frame_time
        return time_since_frame < 5.0

    def get_stats(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Get streaming statistics."""
        if device_id:
            stats = self._streams.get(device_id)
            if stats:
                return stats.to_dict()
            return {"error": "Device not found"}

        return {
            device_id: stats.to_dict()
            for device_id, stats in self._streams.items()
        }

    def get_active_devices(self) -> list:
        """Get list of devices actively streaming via companion."""
        return [
            device_id
            for device_id, stats in self._streams.items()
            if not stats.disconnected and self.is_streaming(device_id)
        ]


# Global singleton instance
companion_stream_manager = CompanionStreamReceiver()
