"""
Companion Stream Receiver - Receives video frames from Android companion app.

This module receives MediaProjection-based screen captures from the companion app
via WebSocket and injects them into the SharedCaptureManager for distribution
to web UI clients. This provides significantly lower latency than ADB capture.

Supports two codecs:
- JPEG (codec=0): Software encoding, universal compatibility
- H.264 (codec=1): Hardware encoding, 3-5x faster, requires WebCodecs on client

Target latency: 50-150ms (vs 100-3000ms for WiFi ADB)
"""

import asyncio
import logging
import time
import struct
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


class StreamCodec(IntEnum):
    """Codec types for companion streaming."""
    JPEG = 0
    H264 = 1


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
    # Codec tracking
    codec: StreamCodec = StreamCodec.JPEG
    keyframes_received: int = 0
    # H.264 SPS/PPS for new client initialization
    sps_data: Optional[bytes] = None
    pps_data: Optional[bytes] = None

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
            "orientation": self.orientation,
            "codec": "H.264" if self.codec == StreamCodec.H264 else "JPEG",
            "keyframes_received": self.keyframes_received,
            "has_sps_pps": self.sps_data is not None and self.pps_data is not None
        }


class CompanionStreamReceiver:
    """
    Manages WebSocket connections from companion apps for video streaming.

    Receives frames from companion apps (JPEG or H.264 encoded) and injects
    them into the SharedCaptureManager for distribution to all subscribed
    web clients.

    Supported codecs:
    - JPEG: Software encoding, universal browser compatibility
    - H.264: Hardware encoding via MediaCodec, 3-5x faster encoding,
             requires WebCodecs API on client for decoding
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

        Supports multiple frame formats:

        1. H.264 format (16-byte header):
           - Bytes 0-3: Frame number (uint32 big-endian)
           - Bytes 4-7: Timestamp ms (uint32 big-endian)
           - Bytes 8-9: Width (uint16 big-endian)
           - Bytes 10-11: Height (uint16 big-endian)
           - Byte 12: Flags (bit 0 = keyframe, bit 1 = has_sps_pps)
           - Byte 13: Codec (0 = JPEG, 1 = H.264)
           - Bytes 14-15: Reserved
           If has_sps_pps flag set:
             - 2 bytes: SPS length, then SPS data
             - 2 bytes: PPS length, then PPS data
           Then frame data (NAL units)

        2. JPEG v2 format (12-byte header):
           - Bytes 0-3: Frame number (uint32 big-endian)
           - Bytes 4-7: Capture time ms (uint32 big-endian)
           - Bytes 8-9: Width (uint16 big-endian)
           - Bytes 10-11: Height (uint16 big-endian)
           - Bytes 12+: JPEG image data

        3. Legacy JPEG format (8-byte header):
           - Bytes 0-3: Frame number (uint32 big-endian)
           - Bytes 4-7: Capture time ms (uint32 big-endian)
           - Bytes 8+: JPEG image data

        Args:
            device_id: The device identifier
            frame_data: Binary frame data

        Returns:
            True if frame was processed successfully
        """
        if len(frame_data) < 10:  # Minimum header + some data
            logger.warning(f"[CompanionReceiver] Frame too small: {len(frame_data)} bytes")
            return False

        stats = self._streams.get(device_id)
        if not stats:
            logger.warning(f"[CompanionReceiver] Unknown device: {device_id}")
            return False

        if stats.disconnected:
            return False

        # Parse header - detect format by checking codec byte at position 13
        frame_number = 0
        capture_time = 0
        width = 0
        height = 0
        header_size = 8
        is_keyframe = False
        codec = StreamCodec.JPEG

        try:
            # Try 16-byte H.264 format first (has codec byte at position 13)
            if len(frame_data) >= 16:
                frame_number, capture_time, width, height, flags, codec_byte, _ = struct.unpack(
                    ">IIHHBBH", frame_data[:16]
                )

                # Validate codec byte (0 or 1 are valid)
                if codec_byte in (0, 1) and 100 <= width <= 4096 and 100 <= height <= 4096:
                    codec = StreamCodec(codec_byte)
                    is_keyframe = bool(flags & 0x01)
                    has_sps_pps = bool(flags & 0x02)
                    header_size = 16

                    # Extract SPS/PPS if present (H.264 keyframes)
                    if has_sps_pps and codec == StreamCodec.H264:
                        offset = 16
                        if len(frame_data) > offset + 2:
                            sps_len = struct.unpack(">H", frame_data[offset:offset+2])[0]
                            offset += 2
                            if len(frame_data) > offset + sps_len:
                                stats.sps_data = frame_data[offset:offset+sps_len]
                                offset += sps_len
                                if len(frame_data) > offset + 2:
                                    pps_len = struct.unpack(">H", frame_data[offset:offset+2])[0]
                                    offset += 2
                                    if len(frame_data) > offset + pps_len:
                                        stats.pps_data = frame_data[offset:offset+pps_len]
                                        offset += pps_len
                                        header_size = offset
                else:
                    # Not 16-byte format, try 12-byte JPEG format
                    frame_number, capture_time, width, height = struct.unpack(">IIHH", frame_data[:12])
                    if 100 <= width <= 4096 and 100 <= height <= 4096:
                        header_size = 12
                        codec = StreamCodec.JPEG
                    else:
                        # Fall back to 8-byte legacy format
                        frame_number, capture_time = struct.unpack(">II", frame_data[:8])
                        width, height = 0, 0
                        header_size = 8
                        codec = StreamCodec.JPEG
            else:
                # Too short for 16-byte, try 12-byte then 8-byte
                if len(frame_data) >= 12:
                    frame_number, capture_time, width, height = struct.unpack(">IIHH", frame_data[:12])
                    if 100 <= width <= 4096 and 100 <= height <= 4096:
                        header_size = 12
                    else:
                        frame_number, capture_time = struct.unpack(">II", frame_data[:8])
                        width, height = 0, 0
                        header_size = 8
                else:
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
        stats.codec = codec
        if width > 0 and height > 0:
            stats.frame_width = width
            stats.frame_height = height
        if is_keyframe:
            stats.keyframes_received += 1

        # Log periodically
        if stats.frames_received == 1 or stats.frames_received % 60 == 0:
            payload_size = len(frame_data) - header_size
            dim_info = f"{width}x{height} ({stats.orientation})" if width > 0 else "no dims"
            codec_name = "H.264" if codec == StreamCodec.H264 else "JPEG"
            keyframe_info = ", KEYFRAME" if is_keyframe else ""
            logger.info(
                f"[CompanionReceiver] {device_id} frame {frame_number}: "
                f"{codec_name}, {payload_size} bytes, {dim_info}, FPS: {stats.fps:.1f}{keyframe_info}"
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

    def get_codec_info(self, device_id: str) -> Dict[str, Any]:
        """
        Get codec information for a device.

        Returns codec type, and SPS/PPS data if H.264 is being used.
        This info is needed by clients to initialize their decoder.
        """
        stats = self._streams.get(device_id)
        if not stats:
            return {"codec": "unknown", "has_init_data": False}

        if stats.codec == StreamCodec.H264:
            return {
                "codec": "h264",
                "has_init_data": stats.sps_data is not None and stats.pps_data is not None,
                "sps": stats.sps_data.hex() if stats.sps_data else None,
                "pps": stats.pps_data.hex() if stats.pps_data else None,
                "width": stats.frame_width,
                "height": stats.frame_height
            }
        else:
            return {
                "codec": "jpeg",
                "has_init_data": True,  # JPEG doesn't need init data
                "width": stats.frame_width,
                "height": stats.frame_height
            }


# Global singleton instance
companion_stream_manager = CompanionStreamReceiver()
