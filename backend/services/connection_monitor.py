"""
Connection Monitor Service - Device Connection Tracking and Auto-Recovery

Consolidated from utils/connection_monitor.py and services/connection_monitor.py.
Monitors device connections via MQTT and ADB, handles auto-reconnection,
and replays queued commands when devices come back online.

Features:
- Tracks device online/offline status via MQTT heartbeats
- ADB-based health checks for connected devices
- Auto-reconnection with exponential backoff
- Network scanning for devices with changed IPs
- Replays queued commands on reconnection
- Debounced status updates (prevents rapid on/off cycles)
- Integration with CommandQueue for offline resilience
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
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
    # ADB reconnection tracking
    stable_device_id: Optional[str] = None
    retry_count: int = 0
    retry_delay: float = 10.0


class ConnectionMonitor:
    """
    Monitors device connections and handles auto-recovery.

    Features:
    - MQTT-based status tracking from companion app heartbeats
    - ADB-based health checks and auto-reconnection
    - Command queue replay on reconnection
    - Exponential backoff for reconnection attempts

    Usage:
        monitor = ConnectionMonitor(
            adb_bridge=adb_bridge,
            mqtt_manager=mqtt_manager,
            device_migrator=device_migrator,
        )

        # Set command sender (how to send commands to device)
        async def send_command(device_id: str, command_type: str, payload: dict) -> bool:
            return await mqtt_manager.publish_command(device_id, command_type, payload)

        monitor.set_command_sender(send_command)

        # Start monitoring
        await monitor.start()
    """

    def __init__(
        self,
        adb_bridge=None,
        mqtt_manager=None,
        device_migrator=None,
        command_queue: Optional[CommandQueue] = None,
        debounce_seconds: float = 5.0,
        check_interval: int = 30,
        max_retry_delay: int = 300,
    ):
        """
        Initialize the connection monitor.

        Args:
            adb_bridge: ADB bridge for health checks and reconnection
            mqtt_manager: The MQTT manager instance
            device_migrator: Device migrator for network scanning
            command_queue: Optional command queue (uses singleton if not provided)
            debounce_seconds: Time to wait before considering device truly offline
            check_interval: Seconds between ADB health checks
            max_retry_delay: Maximum backoff delay for reconnection attempts
        """
        self.adb_bridge = adb_bridge
        self.mqtt_manager = mqtt_manager
        self.device_migrator = device_migrator
        self.command_queue = command_queue or get_command_queue()
        self.debounce_seconds = debounce_seconds
        self.check_interval = check_interval
        self.max_retry_delay = max_retry_delay

        # Device status tracking
        self._devices: Dict[str, DeviceStatus] = {}
        self._pending_offline: Dict[str, asyncio.Task] = {}

        # Command sender callback
        self._command_sender: Optional[Callable[[str, str, dict], Awaitable[bool]]] = (
            None
        )

        # Connection event callbacks
        self._on_connect_callbacks: list = []
        self._on_disconnect_callbacks: list = []

        # Running state
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None

    def set_command_sender(self, sender: Callable[[str, str, dict], Awaitable[bool]]):
        """
        Set the callback for sending commands to devices.

        Args:
            sender: Async function(device_id, command_type, payload) -> bool
        """
        self._command_sender = sender

    def on_device_connect(
        self, callback: Callable[[str, DeviceStatus], Awaitable[None]]
    ):
        """Register callback for device connection events"""
        self._on_connect_callbacks.append(callback)

    def on_device_disconnect(self, callback: Callable[[str], Awaitable[None]]):
        """Register callback for device disconnection events"""
        self._on_disconnect_callbacks.append(callback)

    def register_reconnect_callback(self, callback: Callable):
        """Register callback for device reconnections (legacy API)"""
        self._on_connect_callbacks.append(callback)

    def register_disconnect_callback(self, callback: Callable):
        """Register callback for device disconnections (legacy API)"""
        self._on_disconnect_callbacks.append(callback)

    async def start(self):
        """Start the connection monitor"""
        if self._running:
            logger.warning("[ConnectionMonitor] Already running")
            return

        self._running = True

        # Register for MQTT status updates (if mqtt_manager available)
        if self.mqtt_manager:
            self.mqtt_manager.set_companion_status_callback(self._on_status_update)

        # Start ADB health check loop
        self._monitor_task = asyncio.create_task(self._monitor_loop())

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info(
            f"[ConnectionMonitor] Started (check interval: {self.check_interval}s)"
        )

    async def stop(self):
        """Stop the connection monitor"""
        if not self._running:
            return

        self._running = False

        # Cancel monitor task
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await asyncio.wait_for(self._monitor_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

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

    async def add_device(self, device_id: str, stable_device_id: Optional[str] = None):
        """Add a device to monitor"""
        if device_id not in self._devices:
            self._devices[device_id] = DeviceStatus(
                device_id=device_id,
                online=True,
                last_seen=time.time(),
                stable_device_id=stable_device_id,
                retry_count=0,
                retry_delay=10.0,
            )
            logger.info(f"[ConnectionMonitor] Now monitoring {device_id}")

    async def remove_device(self, device_id: str):
        """Remove a device from monitoring"""
        if device_id in self._devices:
            del self._devices[device_id]
            logger.info(f"[ConnectionMonitor] Stopped monitoring {device_id}")

    def get_status_summary(self) -> dict:
        """Get summary of monitored devices"""
        online = [d for d, s in self._devices.items() if s.online]
        offline = [d for d, s in self._devices.items() if not s.online]

        return {
            "total_devices": len(self._devices),
            "online": len(online),
            "offline": len(offline),
            "online_devices": online,
            "offline_devices": offline,
            "details": {
                d: {
                    "state": "online" if s.online else "offline",
                    "last_seen": s.last_seen,
                    "retry_count": s.retry_count,
                    "stable_device_id": s.stable_device_id,
                }
                for d, s in self._devices.items()
            },
        }

    async def _monitor_loop(self):
        """Main ADB health check loop"""
        while self._running:
            try:
                await self._check_all_devices()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ConnectionMonitor] Monitor loop error: {e}")
                await asyncio.sleep(self.check_interval)

    async def _check_all_devices(self):
        """Check health of all monitored devices"""
        current_devices = list(self._devices.keys())
        if not current_devices:
            return

        logger.debug(
            f"[ConnectionMonitor] Running health checks for {len(current_devices)} devices"
        )

        for device_id in current_devices:
            try:
                is_online = await self._check_device_health(device_id)
                status = self._devices.get(device_id)
                if not status:
                    continue

                was_online = status.online

                # Log state changes
                if was_online and not is_online:
                    logger.info(
                        f"[ConnectionMonitor] Device {device_id} health check: online -> offline"
                    )
                elif not was_online and is_online:
                    logger.info(
                        f"[ConnectionMonitor] Device {device_id} health check: offline -> online"
                    )

                await self._handle_device_state(device_id, is_online)
            except Exception as e:
                logger.error(f"[ConnectionMonitor] Failed to check {device_id}: {e}")

    async def _check_device_health(self, device_id: str) -> bool:
        """Quick ADB health check for a device"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "devices",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                devices_output = stdout.decode()
                is_connected = f"{device_id}\tdevice" in devices_output
                return is_connected
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return False
        except FileNotFoundError:
            logger.error("[ConnectionMonitor] ADB command not found")
            return False
        except Exception as e:
            logger.debug(f"[ConnectionMonitor] Health check failed for {device_id}: {e}")
            return False

    async def _handle_device_state(self, device_id: str, is_online: bool):
        """Handle device state changes from ADB health checks"""
        status = self._devices.get(device_id)
        if not status:
            return

        was_online = status.online
        current_time = time.time()

        if is_online:
            status.last_seen = current_time

            if not was_online:
                logger.info(f"[ConnectionMonitor] ✅ Device {device_id} is back online")
                status.online = True
                status.retry_count = 0
                status.retry_delay = 10.0

                # Update MQTT availability
                if self.mqtt_manager:
                    await self.mqtt_manager.publish_availability(
                        device_id, online=True, stable_device_id=status.stable_device_id
                    )

                # Trigger reconnect callbacks
                for callback in self._on_connect_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(device_id, status)
                        else:
                            callback(device_id, status)
                    except Exception as e:
                        logger.error(f"[ConnectionMonitor] Reconnect callback failed: {e}")

                # Replay queued commands
                await self._replay_queued_commands(device_id)
            else:
                status.online = True

        else:
            if was_online:
                logger.warning(f"[ConnectionMonitor] ⚠️ Device {device_id} went offline")
                status.online = False
                status.retry_count = 0

                # Update MQTT availability
                if self.mqtt_manager:
                    await self.mqtt_manager.publish_availability(
                        device_id, online=False, stable_device_id=status.stable_device_id
                    )

                # Trigger disconnect callbacks
                for callback in self._on_disconnect_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(device_id)
                        else:
                            callback(device_id)
                    except Exception as e:
                        logger.error(f"[ConnectionMonitor] Disconnect callback failed: {e}")

                # Attempt reconnection
                await self._attempt_reconnection(device_id)

            elif not status.online:
                # Still offline - attempt recovery with backoff
                await self._attempt_reconnection(device_id)

    async def _attempt_reconnection(self, device_id: str):
        """Attempt to reconnect to an offline device with exponential backoff"""
        status = self._devices.get(device_id)
        if not status:
            return

        current_time = time.time()
        time_since_last_seen = current_time - status.last_seen

        # Check if we should retry based on backoff
        if status.retry_count > 0 and time_since_last_seen < status.retry_delay:
            return

        status.retry_count += 1
        retry_num = status.retry_count

        logger.info(
            f"[ConnectionMonitor] Attempting to reconnect to {device_id} "
            f"(attempt #{retry_num}, waited {time_since_last_seen:.0f}s)"
        )

        success = await self._try_direct_reconnect(device_id)

        if success:
            logger.info(f"[ConnectionMonitor] ✅ Successfully reconnected to {device_id}")
            status.online = True
            status.last_seen = current_time
            status.retry_count = 0
            status.retry_delay = 10.0

            if self.mqtt_manager:
                await self.mqtt_manager.publish_availability(
                    device_id, online=True, stable_device_id=status.stable_device_id
                )

            for callback in self._on_connect_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device_id, status)
                    else:
                        callback(device_id, status)
                except Exception as e:
                    logger.error(f"[ConnectionMonitor] Reconnect callback failed: {e}")

            await self._replay_queued_commands(device_id)
        else:
            # Exponential backoff
            status.retry_delay = min(status.retry_delay * 2, self.max_retry_delay)
            logger.debug(
                f"[ConnectionMonitor] Reconnection failed for {device_id}, "
                f"will retry in {status.retry_delay}s"
            )

            # After several failed attempts, try network scan
            if retry_num == 3 and status.stable_device_id and self.device_migrator:
                logger.info(
                    f"[ConnectionMonitor] Searching network for {device_id} "
                    f"with stable ID {status.stable_device_id}"
                )
                await self._scan_for_device(status.stable_device_id)

    async def _try_direct_reconnect(self, device_id: str) -> bool:
        """Try to reconnect to device at its known address"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "connect",
                device_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                stdout_str = stdout.decode().lower()

                if "connected" in stdout_str or "already connected" in stdout_str:
                    await asyncio.sleep(1)
                    return await self._check_device_health(device_id)
                return False
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return False
        except Exception as e:
            logger.debug(f"[ConnectionMonitor] Direct reconnect failed for {device_id}: {e}")
            return False

    async def _scan_for_device(self, stable_device_id: str):
        """Scan network to find a device with a specific stable ID"""
        try:
            logger.info(
                f"[ConnectionMonitor] Scanning network for device with stable ID {stable_device_id}"
            )
            if self.adb_bridge:
                await self.adb_bridge.discover_devices()
            logger.info("[ConnectionMonitor] Network scan complete")
        except Exception as e:
            logger.error(f"[ConnectionMonitor] Network scan failed: {e}")

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
            platform=status_data.get("platform", "android"),
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
            logger.warning(
                "[ConnectionMonitor] No command sender configured, skipping replay"
            )
            return

        try:
            commands = await self.command_queue.get_pending_commands(device_id)

            if not commands:
                logger.debug(f"[ConnectionMonitor] No pending commands for {device_id}")
                return

            logger.info(
                f"[ConnectionMonitor] Replaying {len(commands)} queued commands for {device_id}"
            )

            for cmd in commands:
                try:
                    await self.command_queue.mark_processing(cmd.command_id)

                    success = await self._command_sender(
                        device_id, cmd.command_type, cmd.payload
                    )

                    if success:
                        await self.command_queue.mark_completed(cmd.command_id)
                        logger.info(
                            f"[ConnectionMonitor] Replayed command {cmd.command_id} successfully"
                        )
                    else:
                        await self.command_queue.mark_failed(
                            cmd.command_id, "Send failed"
                        )
                        logger.warning(
                            f"[ConnectionMonitor] Failed to replay command {cmd.command_id}"
                        )

                except Exception as e:
                    await self.command_queue.mark_failed(cmd.command_id, str(e))
                    logger.error(
                        f"[ConnectionMonitor] Error replaying command {cmd.command_id}: {e}"
                    )

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
                        logger.error(
                            f"[ConnectionMonitor] Disconnect callback error: {e}"
                        )

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
                        logger.info(
                            f"[ConnectionMonitor] Device {device_id} stale, marking offline"
                        )
                        self.mark_device_offline(device_id)

                # Cleanup old commands
                deleted = await self.command_queue.cleanup_old_commands(24)
                if deleted > 0:
                    logger.info(
                        f"[ConnectionMonitor] Cleaned up {deleted} old commands"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ConnectionMonitor] Cleanup error: {e}")


# Singleton instance
_monitor_instance: Optional[ConnectionMonitor] = None


def get_connection_monitor(
    adb_bridge=None, mqtt_manager=None, device_migrator=None
) -> ConnectionMonitor:
    """Get or create the singleton connection monitor instance"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ConnectionMonitor(
            adb_bridge=adb_bridge,
            mqtt_manager=mqtt_manager,
            device_migrator=device_migrator,
        )
    return _monitor_instance
