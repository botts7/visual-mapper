"""
Connection Monitor Service - Device Connection Tracking and Queue Replay

Phase 2 Refactor: Monitors device connections via MQTT and replays
queued commands when devices come back online.

Features:
- Tracks device online/offline status
- Replays queued commands on reconnection
- Debounced status updates (prevents rapid on/off cycles)
- Integration with CommandQueue for offline resilience
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
from datetime import datetime

from services.command_queue import get_command_queue, CommandQueue

logger = logging.getLogger(__name__)


@dataclass
class DeviceStatus:
    """Tracked status for a device"""
    device_id: str
    online: bool
    last_seen: float
    app_version: Optional[str] = None
    capabilities: list = None
    platform: str = "unknown"


class ConnectionMonitor:
    """
    Monitors device connections and replays queued commands.

    Usage:
        monitor = ConnectionMonitor(mqtt_manager)

        # Set command sender (how to send commands to device)
        async def send_command(device_id: str, command_type: str, payload: dict) -> bool:
            return await mqtt_manager.publish_command(device_id, command_type, payload)

        monitor.set_command_sender(send_command)

        # Start monitoring
        await monitor.start()
    """

    def __init__(
        self,
        mqtt_manager,
        command_queue: Optional[CommandQueue] = None,
        debounce_seconds: float = 5.0
    ):
        """
        Initialize the connection monitor.

        Args:
            mqtt_manager: The MQTT manager instance
            command_queue: Optional command queue (uses singleton if not provided)
            debounce_seconds: Time to wait before considering device truly offline
        """
        self.mqtt_manager = mqtt_manager
        self.command_queue = command_queue or get_command_queue()
        self.debounce_seconds = debounce_seconds

        # Device status tracking
        self._devices: Dict[str, DeviceStatus] = {}
        self._pending_offline: Dict[str, asyncio.Task] = {}

        # Command sender callback
        self._command_sender: Optional[Callable[[str, str, dict], Awaitable[bool]]] = None

        # Connection event callbacks
        self._on_connect_callbacks: list = []
        self._on_disconnect_callbacks: list = []

        # Running state
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None

    def set_command_sender(self, sender: Callable[[str, str, dict], Awaitable[bool]]):
        """
        Set the callback for sending commands to devices.

        Args:
            sender: Async function(device_id, command_type, payload) -> bool
        """
        self._command_sender = sender

    def on_device_connect(self, callback: Callable[[str, DeviceStatus], Awaitable[None]]):
        """Register callback for device connection events"""
        self._on_connect_callbacks.append(callback)

    def on_device_disconnect(self, callback: Callable[[str], Awaitable[None]]):
        """Register callback for device disconnection events"""
        self._on_disconnect_callbacks.append(callback)

    async def start(self):
        """Start the connection monitor"""
        if self._running:
            logger.warning("[ConnectionMonitor] Already running")
            return

        self._running = True

        # Register for MQTT status updates
        self.mqtt_manager.set_companion_status_callback(self._on_status_update)

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("[ConnectionMonitor] Started monitoring device connections")

    async def stop(self):
        """Stop the connection monitor"""
        self._running = False

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cancel pending offline tasks
        for task in self._pending_offline.values():
            task.cancel()
        self._pending_offline.clear()

        logger.info("[ConnectionMonitor] Stopped")

    def _on_status_update(self, device_id: str, status_data: dict):
        """Handle device status update from MQTT (sync callback)"""
        # Schedule async handling
        asyncio.create_task(self._handle_status_update(device_id, status_data))

    async def _handle_status_update(self, device_id: str, status_data: dict):
        """Handle device status update (async)"""
        now = time.time()
        was_online = device_id in self._devices and self._devices[device_id].online

        # Cancel any pending offline transition
        if device_id in self._pending_offline:
            self._pending_offline[device_id].cancel()
            del self._pending_offline[device_id]

        # Update device status
        status = DeviceStatus(
            device_id=device_id,
            online=True,
            last_seen=now,
            app_version=status_data.get("app_version"),
            capabilities=status_data.get("capabilities", []),
            platform=status_data.get("platform", "android")
        )
        self._devices[device_id] = status

        # If device just came online, replay queued commands
        if not was_online:
            logger.info(f"[ConnectionMonitor] Device {device_id} came online")
            await self._on_device_connected(device_id, status)

    async def _on_device_connected(self, device_id: str, status: DeviceStatus):
        """Handle device coming online"""
        # Notify callbacks
        for callback in self._on_connect_callbacks:
            try:
                await callback(device_id, status)
            except Exception as e:
                logger.error(f"[ConnectionMonitor] Connect callback error: {e}")

        # Replay queued commands
        await self._replay_queued_commands(device_id)

    async def _replay_queued_commands(self, device_id: str):
        """Replay queued commands for a device"""
        if not self._command_sender:
            logger.warning("[ConnectionMonitor] No command sender configured, skipping replay")
            return

        try:
            commands = await self.command_queue.get_pending_commands(device_id)

            if not commands:
                logger.debug(f"[ConnectionMonitor] No pending commands for {device_id}")
                return

            logger.info(f"[ConnectionMonitor] Replaying {len(commands)} queued commands for {device_id}")

            for cmd in commands:
                try:
                    await self.command_queue.mark_processing(cmd.command_id)

                    success = await self._command_sender(
                        device_id,
                        cmd.command_type,
                        cmd.payload
                    )

                    if success:
                        await self.command_queue.mark_completed(cmd.command_id)
                        logger.info(f"[ConnectionMonitor] Replayed command {cmd.command_id} successfully")
                    else:
                        await self.command_queue.mark_failed(cmd.command_id, "Send failed")
                        logger.warning(f"[ConnectionMonitor] Failed to replay command {cmd.command_id}")

                except Exception as e:
                    await self.command_queue.mark_failed(cmd.command_id, str(e))
                    logger.error(f"[ConnectionMonitor] Error replaying command {cmd.command_id}: {e}")

        except Exception as e:
            logger.error(f"[ConnectionMonitor] Error getting queued commands: {e}")

    def mark_device_offline(self, device_id: str):
        """Mark a device as offline (with debounce)"""
        if device_id in self._pending_offline:
            return  # Already pending

        async def delayed_offline():
            await asyncio.sleep(self.debounce_seconds)

            if device_id in self._devices:
                self._devices[device_id].online = False

                # Notify callbacks
                for callback in self._on_disconnect_callbacks:
                    try:
                        await callback(device_id)
                    except Exception as e:
                        logger.error(f"[ConnectionMonitor] Disconnect callback error: {e}")

                logger.info(f"[ConnectionMonitor] Device {device_id} marked offline")

            if device_id in self._pending_offline:
                del self._pending_offline[device_id]

        self._pending_offline[device_id] = asyncio.create_task(delayed_offline())

    def is_device_online(self, device_id: str) -> bool:
        """Check if a device is currently online"""
        status = self._devices.get(device_id)
        return status is not None and status.online

    def get_device_status(self, device_id: str) -> Optional[DeviceStatus]:
        """Get current status for a device"""
        return self._devices.get(device_id)

    def get_all_online_devices(self) -> Dict[str, DeviceStatus]:
        """Get all currently online devices"""
        return {
            device_id: status
            for device_id, status in self._devices.items()
            if status.online
        }

    async def _cleanup_loop(self):
        """Periodic cleanup of stale device status and old commands"""
        while self._running:
            try:
                await asyncio.sleep(300)  # Every 5 minutes

                # Check for stale devices (no heartbeat in 2 minutes)
                stale_threshold = time.time() - 120
                for device_id, status in list(self._devices.items()):
                    if status.online and status.last_seen < stale_threshold:
                        logger.info(f"[ConnectionMonitor] Device {device_id} stale, marking offline")
                        self.mark_device_offline(device_id)

                # Cleanup old commands
                deleted = await self.command_queue.cleanup_old_commands(24)
                if deleted > 0:
                    logger.info(f"[ConnectionMonitor] Cleaned up {deleted} old commands")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ConnectionMonitor] Cleanup error: {e}")


# Singleton instance
_monitor_instance: Optional[ConnectionMonitor] = None


def get_connection_monitor(mqtt_manager=None) -> ConnectionMonitor:
    """Get or create the singleton connection monitor instance"""
    global _monitor_instance
    if _monitor_instance is None:
        if mqtt_manager is None:
            raise ValueError("mqtt_manager required for first initialization")
        _monitor_instance = ConnectionMonitor(mqtt_manager)
    return _monitor_instance
