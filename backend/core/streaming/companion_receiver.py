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
    last_frame_time: float = field(default_factory=time.time)  # Initialize to now, not 0
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

    Also supports bidirectional command routing:
    - send_command(): Send commands to companion via WebSocket
    - Command responses are routed back to CommandRouter
    """

    def __init__(self):
        self._streams: Dict[str, CompanionStreamStats] = {}
        self._frame_callbacks: Dict[str, Callable[[bytes], None]] = {}
        self._lock = asyncio.Lock()

        # WebSocket connections for command routing
        # Map: device_id -> {"websocket": ws, "send_fn": async callable}
        self._websocket_connections: Dict[str, Dict[str, Any]] = {}

        # Reference to command router for response handling
        self._command_router = None

        # Device serial mapping for cross-subnet matching
        # Maps ADB device serial -> companion device_id (for when IPs don't match)
        self._serial_to_companion: Dict[str, str] = {}
        # Maps companion device_id -> known serial (if provided during registration)
        self._companion_serials: Dict[str, str] = {}

    async def register_device(self, device_id: str) -> bool:
        """Register a device for companion streaming.

        Now allows re-registration even if device appears connected - this handles
        race conditions when companion reconnects quickly after disconnect.
        """
        async with self._lock:
            if device_id in self._streams and not self._streams[device_id].disconnected:
                # Device appears connected - check if it's stale (no recent frames)
                existing = self._streams[device_id]
                if existing.last_frame_time:
                    time_since_frame = time.time() - existing.last_frame_time
                    if time_since_frame > 5.0:  # No frames for 5 seconds = stale
                        logger.info(f"[CompanionReceiver] Device {device_id} stale ({time_since_frame:.1f}s since last frame), allowing re-register")
                    else:
                        logger.warning(f"[CompanionReceiver] Device {device_id} already streaming ({time_since_frame:.1f}s ago)")
                        return False
                else:
                    # Never received frames - allow re-register
                    logger.info(f"[CompanionReceiver] Device {device_id} registered but no frames, allowing re-register")

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

    def register_serial_mapping(self, adb_device_id: str, serial: str, companion_device_id: str):
        """
        Register a mapping between ADB device serial and companion device ID.

        This enables matching when the ADB device IP doesn't match the companion's IP
        (e.g., different network perspectives, NAT, or multi-subnet scenarios).

        Args:
            adb_device_id: The ADB connection ID (e.g., "192.0.2.10:5555")
            serial: The stable device serial (hardware serial)
            companion_device_id: The companion's device_id (e.g., "192_0_2_129_companion")
        """
        self._serial_to_companion[serial] = companion_device_id
        self._companion_serials[companion_device_id] = serial
        logger.info(
            f"[CompanionReceiver] Serial mapping: {serial} -> {companion_device_id} "
            f"(ADB: {adb_device_id})"
        )

    def set_companion_serial(self, companion_device_id: str, serial: str):
        """
        Set the serial for a companion device (usually from MQTT announcement).

        Args:
            companion_device_id: The companion's device_id
            serial: The device's hardware serial
        """
        self._companion_serials[companion_device_id] = serial
        self._serial_to_companion[serial] = companion_device_id
        logger.debug(f"[CompanionReceiver] Companion serial set: {companion_device_id} -> {serial}")

    def get_companion_by_serial(self, serial: str) -> Optional[str]:
        """
        Get companion device_id by serial number.

        Args:
            serial: The device's hardware serial

        Returns:
            Companion device_id if found, None otherwise
        """
        return self._serial_to_companion.get(serial)

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

        # Log periodically (more often for first 10 frames to debug issues)
        if stats.frames_received <= 10 or stats.frames_received % 60 == 0:
            payload_size = len(frame_data) - header_size
            dim_info = f"{width}x{height} ({stats.orientation})" if width > 0 else "no dims"
            codec_name = "H.264" if codec == StreamCodec.H264 else "JPEG"
            keyframe_info = ", KEYFRAME" if is_keyframe else ""
            logger.info(
                f"[CompanionReceiver] {device_id} recv#{stats.frames_received} hdr_frame#{frame_number}: "
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

    def _extract_ip(self, device_id: str) -> Optional[str]:
        """
        Extract IP address from various device ID formats.

        Supported formats:
        - 192.168.1.2:5555 (ADB format with port)
        - 192_168_1_2_5555 (underscore format)
        - 192.168.1.2 (IP only)
        """
        # Replace underscores with dots for normalization
        normalized = device_id.replace("_", ".")

        # Try to extract IP address
        import re
        ip_pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        match = re.search(ip_pattern, normalized)
        if match:
            return match.group(1)
        return None

    def find_companion_for_device(self, device_id: str, adb_serial: Optional[str] = None) -> Optional[str]:
        """
        Find a companion stream that matches the given device ID.

        Matching strategy (in order of priority):
        1. IP address match (ignoring port differences)
        2. Device serial match (for cross-subnet scenarios)
        3. Single active companion fallback (when only one companion is streaming)

        The fallback handles cases where:
        - Companion app uses tablet's WiFi IP (e.g., 192.0.2.129)
        - ADB connects through different IP (e.g., 192.0.2.10)

        Args:
            device_id: The ADB device ID (e.g., "192.0.2.10:5555")
            adb_serial: Optional device serial for cross-subnet matching

        Returns the companion device_id if found, None otherwise.
        """
        target_ip = self._extract_ip(device_id)

        # Collect all active companions
        active_companions = []
        for companion_id, stats in self._streams.items():
            if stats.disconnected:
                continue

            # Check if actively streaming OR recently connected
            time_since_connect = time.time() - stats.connect_time
            time_since_frame = time.time() - stats.last_frame_time
            if time_since_connect < 30.0 or time_since_frame < 5.0:
                active_companions.append((companion_id, stats))

        # Strategy 1: IP address match
        if target_ip:
            for companion_id, stats in active_companions:
                companion_ip = self._extract_ip(companion_id)
                if companion_ip == target_ip:
                    logger.debug(f"[CompanionReceiver] IP match: {device_id} -> {companion_id}")
                    return companion_id

        # Strategy 2: Serial number match (for cross-subnet scenarios)
        # This handles cases where ADB and companion see different IPs for the same device
        if adb_serial:
            # Check if we have a direct serial mapping
            companion_id = self._serial_to_companion.get(adb_serial)
            if companion_id and any(c[0] == companion_id for c in active_companions):
                logger.info(
                    f"[CompanionReceiver] Serial match: {device_id} (serial={adb_serial}) -> {companion_id}"
                )
                return companion_id

            # Check if any active companion has this serial
            for companion_id, stats in active_companions:
                companion_serial = self._companion_serials.get(companion_id)
                if companion_serial and companion_serial == adb_serial:
                    logger.info(
                        f"[CompanionReceiver] Serial match (companion-side): {device_id} -> {companion_id} "
                        f"(serial={adb_serial})"
                    )
                    return companion_id

        # Strategy 3: Single active companion fallback
        # If there's only one active companion, it's likely the right one
        # This handles IP mismatch between companion app and ADB
        if len(active_companions) == 1:
            companion_id, stats = active_companions[0]
            logger.info(
                f"[CompanionReceiver] Single companion fallback: {device_id} -> {companion_id} "
                f"(target_ip={target_ip}, companion_ip={self._extract_ip(companion_id)})"
            )
            return companion_id

        # No match found
        if len(active_companions) > 1:
            logger.warning(
                f"[CompanionReceiver] Multiple companions ({len(active_companions)}) but no IP/serial match for {device_id} "
                f"(serial={adb_serial}). Consider running serial mapping."
            )
        return None

    def is_streaming(self, device_id: str) -> bool:
        """Check if a device is actively streaming via companion app.

        Optimistic for fresh connections (< 2s) to handle timing issues where
        frontend checks before first frame arrives.
        """
        # First try exact match
        stats = self._streams.get(device_id)
        if stats and not stats.disconnected:
            time_since_connect = time.time() - stats.connect_time
            time_since_frame = time.time() - stats.last_frame_time if stats.last_frame_time > 0 else float('inf')

            # Optimistic for fresh connections (< 2s) - gives companion time to
            # initialize MediaProjection and send first frame
            if time_since_connect < 2.0:
                logger.debug(
                    f"[CompanionReceiver] Optimistic: {device_id} connected {time_since_connect:.1f}s ago"
                )
                return True

            # Consider active if connected recently (within 30s) OR received frames recently
            if time_since_connect < 30.0 or time_since_frame < 5.0:
                return True

        # Try IP-based match
        companion_id = self.find_companion_for_device(device_id)
        if companion_id:
            stats = self._streams.get(companion_id)
            if stats and not stats.disconnected:
                time_since_connect = time.time() - stats.connect_time
                time_since_frame = time.time() - stats.last_frame_time if stats.last_frame_time > 0 else float('inf')

                # Optimistic for fresh connections
                if time_since_connect < 2.0:
                    logger.debug(
                        f"[CompanionReceiver] Optimistic (IP match): {companion_id} connected {time_since_connect:.1f}s ago"
                    )
                    return True

                if time_since_connect < 30.0 or time_since_frame < 5.0:
                    return True
        return False

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
        # Try exact match first, then IP-based match
        stats = self._streams.get(device_id)
        if not stats:
            companion_id = self.find_companion_for_device(device_id)
            if companion_id:
                stats = self._streams.get(companion_id)
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


    # =========================================================================
    # WebSocket Command Routing
    # =========================================================================

    def set_command_router(self, router):
        """Set reference to command router for response handling."""
        self._command_router = router

    def register_websocket_connection(
        self,
        device_id: str,
        websocket: Any,
        send_fn: Callable
    ):
        """
        Register a WebSocket connection for command routing.

        Called by streaming.py when companion connects.

        Args:
            device_id: Device identifier
            websocket: WebSocket connection object
            send_fn: Async function to send JSON messages to companion
        """
        self._websocket_connections[device_id] = {
            "websocket": websocket,
            "send_fn": send_fn,
            "registered_at": time.time()
        }
        logger.info(f"[CompanionReceiver] Registered WebSocket for commands: {device_id}")

    def unregister_websocket_connection(self, device_id: str):
        """Unregister WebSocket connection when companion disconnects."""
        if device_id in self._websocket_connections:
            del self._websocket_connections[device_id]
            logger.info(f"[CompanionReceiver] Unregistered WebSocket: {device_id}")

            # Notify CommandRouter to skip MQTT for this device (companion likely crashed)
            try:
                from core.command_router import command_router
                command_router.unregister_websocket(device_id)
            except ImportError:
                pass

    def has_websocket_for_commands(self, device_id: str) -> bool:
        """Check if device has WebSocket available for commands."""
        # Check direct match
        if device_id in self._websocket_connections:
            return True

        # Check IP-based match
        companion_id = self.find_companion_for_device(device_id)
        if companion_id and companion_id in self._websocket_connections:
            return True

        return False

    async def send_command(
        self,
        device_id: str,
        command: Dict[str, Any]
    ) -> bool:
        """
        Send a command to the companion app via WebSocket.

        Args:
            device_id: Device identifier
            command: Command dict with type, request_id, command, params

        Returns:
            True if command was sent, False otherwise
        """
        import json

        # Find WebSocket connection for this device
        ws_info = self._websocket_connections.get(device_id)

        # Try IP-based match if direct match fails
        if not ws_info:
            companion_id = self.find_companion_for_device(device_id)
            if companion_id:
                ws_info = self._websocket_connections.get(companion_id)

        if not ws_info:
            logger.warning(f"[CompanionReceiver] No WebSocket for {device_id}")
            return False

        try:
            send_fn = ws_info.get("send_fn")
            if send_fn:
                await send_fn(command)
                logger.info(
                    f"[CompanionReceiver] Sent WS command to {device_id}: "
                    f"{command.get('command')} (id: {command.get('request_id')[:8]}...)"
                )
                return True
            else:
                logger.warning(f"[CompanionReceiver] No send_fn for {device_id}")
                return False

        except Exception as e:
            logger.error(f"[CompanionReceiver] Failed to send command: {e}")
            return False

    def handle_command_response(self, device_id: str, response: Dict[str, Any]):
        """
        Handle a command response from the companion app.

        Routes the response to CommandRouter for future resolution.

        Args:
            device_id: Device identifier
            response: Response dict with request_id, success, data, error
        """
        request_id = response.get("request_id")
        if not request_id:
            logger.warning(f"[CompanionReceiver] Response missing request_id: {response}")
            return

        # Route to command router
        if self._command_router:
            self._command_router.handle_websocket_response(request_id, response)
            logger.info(
                f"[CompanionReceiver] Got WS response for {request_id[:8]}...: "
                f"success={response.get('success')}"
            )
        else:
            logger.warning(
                f"[CompanionReceiver] No command router for response {request_id}"
            )


# Global singleton instance
companion_stream_manager = CompanionStreamReceiver()
