"""
Connection Monitor - Runtime Device Health & Auto-Recovery
Monitors connected devices and automatically recovers from disconnections

Phase 2 Enhancement: Added command queue replay on device reconnection
"""

import asyncio
import logging
import time
from typing import Dict, Set, Optional, Callable
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Command queue import (lazy to avoid circular imports)
_command_queue = None


def _get_command_queue():
    """Lazy load command queue to avoid circular imports"""
    global _command_queue
    if _command_queue is None:
        try:
            from services.command_queue import get_command_queue

            _command_queue = get_command_queue()
        except ImportError:
            logger.warning("[ConnectionMonitor] CommandQueue not available")
            _command_queue = False  # Mark as unavailable
    return _command_queue if _command_queue else None


class ConnectionMonitor:
    """
    Monitors device connections and automatically recovers from failures.

    Features:
    - Periodic health checks
    - Auto-reconnection with exponential backoff
    - Network scanning for offline devices
    - MQTT availability updates
    - Connection event callbacks
    """

    def __init__(
        self,
        adb_bridge,
        device_migrator=None,
        mqtt_manager=None,
        check_interval: int = 30,  # seconds
        max_retry_delay: int = 300,  # 5 minutes max backoff
    ):
        self.adb_bridge = adb_bridge
        self.device_migrator = device_migrator
        self.mqtt_manager = mqtt_manager
        self.check_interval = check_interval
        self.max_retry_delay = max_retry_delay

        # Device status tracking
        self.device_status: Dict[str, dict] = (
            {}
        )  # {device_id: {state, last_seen, retry_count, retry_delay}}

        # Monitoring state
        self._running = False
        self._monitor_task = None

        # Callbacks
        self._on_device_reconnected = []
        self._on_device_disconnected = []

    def register_reconnect_callback(self, callback: Callable):
        """Register callback for device reconnections"""
        self._on_device_reconnected.append(callback)

    def register_disconnect_callback(self, callback: Callable):
        """Register callback for device disconnections"""
        self._on_device_disconnected.append(callback)

    async def _replay_queued_commands(self, device_id: str):
        """
        Phase 2: Replay any queued commands for a device that just came online.

        Commands are queued when the device is offline and replayed on reconnection.
        """
        queue = _get_command_queue()
        if not queue:
            return

        try:
            commands = await queue.get_pending_commands(device_id)
            if not commands:
                logger.debug(f"[ConnectionMonitor] No queued commands for {device_id}")
                return

            logger.info(
                f"[ConnectionMonitor] Replaying {len(commands)} queued commands for {device_id}"
            )

            for cmd in commands:
                try:
                    await queue.mark_processing(cmd.command_id)

                    # Execute command based on type
                    success = await self._execute_queued_command(device_id, cmd)

                    if success:
                        await queue.mark_completed(cmd.command_id)
                        logger.info(
                            f"[ConnectionMonitor] Replayed command {cmd.command_id} successfully"
                        )
                    else:
                        await queue.mark_failed(cmd.command_id, "Execution failed")
                        logger.warning(
                            f"[ConnectionMonitor] Failed to replay command {cmd.command_id}"
                        )

                except Exception as e:
                    await queue.mark_failed(cmd.command_id, str(e))
                    logger.error(
                        f"[ConnectionMonitor] Error replaying command {cmd.command_id}: {e}"
                    )

        except Exception as e:
            logger.error(
                f"[ConnectionMonitor] Error getting queued commands for {device_id}: {e}"
            )

    async def _execute_queued_command(self, device_id: str, cmd) -> bool:
        """Execute a queued command on the device"""
        try:
            command_type = cmd.command_type
            payload = cmd.payload

            # Route command to appropriate handler
            if command_type == "execute_flow" and self.mqtt_manager:
                # Send flow execution request via MQTT
                topic = f"visual_mapper/{device_id}/commands/execute_flow"
                await self.mqtt_manager.publish(topic, payload)
                return True

            elif command_type == "sync_sensors" and self.mqtt_manager:
                # Send sensor sync request via MQTT
                topic = f"visual_mapper/{device_id}/commands/sync_sensors"
                await self.mqtt_manager.publish(topic, payload)
                return True

            elif command_type == "update_config" and self.mqtt_manager:
                # Send config update via MQTT
                topic = f"visual_mapper/{device_id}/commands/config"
                await self.mqtt_manager.publish(topic, payload)
                return True

            else:
                logger.warning(
                    f"[ConnectionMonitor] Unknown command type: {command_type}"
                )
                return False

        except Exception as e:
            logger.error(f"[ConnectionMonitor] Error executing command: {e}")
            return False

    async def start(self):
        """Start connection monitoring"""
        if self._running:
            logger.warning("[ConnectionMonitor] Already running")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(
            f"[ConnectionMonitor] Started (check interval: {self.check_interval}s)"
        )

    async def stop(self):
        """Stop connection monitoring"""
        if not self._running:
            return

        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                # Add timeout to prevent hanging on shutdown
                await asyncio.wait_for(self._monitor_task, timeout=5.0)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                logger.warning("[ConnectionMonitor] Stop timed out, forcing shutdown")
        logger.info("[ConnectionMonitor] Stopped")

    async def add_device(self, device_id: str, stable_device_id: Optional[str] = None):
        """Add a device to monitor"""
        if device_id not in self.device_status:
            self.device_status[device_id] = {
                "state": "online",
                "last_seen": time.time(),
                "retry_count": 0,
                "retry_delay": 10,  # Start with 10 second delay
                "stable_device_id": stable_device_id,
            }
            logger.info(f"[ConnectionMonitor] Now monitoring {device_id}")

    async def remove_device(self, device_id: str):
        """Remove a device from monitoring"""
        if device_id in self.device_status:
            del self.device_status[device_id]
            logger.info(f"[ConnectionMonitor] Stopped monitoring {device_id}")

    async def _monitor_loop(self):
        """Main monitoring loop"""
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
        current_devices = list(self.device_status.keys())
        # Only log when there are devices to check (avoid spam in production)
        if current_devices:
            logger.debug(
                f"[ConnectionMonitor] Running health checks for {len(current_devices)} devices"
            )

        for device_id in current_devices:
            try:
                is_online = await self._check_device_health(device_id)
                # Only log state changes, not every check
                status = self.device_status.get(device_id)
                if status and status["state"] == "online" and not is_online:
                    logger.info(
                        f"[ConnectionMonitor] Device {device_id} health check: online -> offline"
                    )
                elif status and status["state"] == "offline" and is_online:
                    logger.info(
                        f"[ConnectionMonitor] Device {device_id} health check: offline -> online"
                    )
                await self._handle_device_state(device_id, is_online)
            except Exception as e:
                logger.error(f"[ConnectionMonitor] Failed to check {device_id}: {e}")

    async def _check_device_health(self, device_id: str) -> bool:
        """
        Quick health check for a device.
        Returns True if device is responsive, False otherwise.
        """
        try:
            # Check if device is in ADB devices list with "device" status
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "devices",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                devices_output = stdout.decode()

                # Device should appear as "device_id\tdevice" (not "offline" or "unauthorized")
                is_connected = f"{device_id}\tdevice" in devices_output

                if not is_connected:
                    logger.debug(
                        f"[ConnectionMonitor] Device {device_id} not in devices list or not ready"
                    )
                    logger.debug(
                        f"[ConnectionMonitor] ADB devices output: {devices_output}"
                    )

                return is_connected

            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.debug(
                    f"[ConnectionMonitor] Health check timeout for {device_id}"
                )
                return False
        except FileNotFoundError:
            logger.error("[ConnectionMonitor] ADB command not found")
            return False
        except Exception as e:
            logger.debug(
                f"[ConnectionMonitor] Health check failed for {device_id}: {e}"
            )
            return False

    async def _handle_device_state(self, device_id: str, is_online: bool):
        """Handle device state changes"""
        status = self.device_status.get(device_id)
        if not status:
            logger.warning(f"[ConnectionMonitor] No status found for {device_id}")
            return

        previous_state = status["state"]
        current_time = time.time()

        # Only log at DEBUG level for detailed troubleshooting
        if previous_state != ("online" if is_online else "offline"):
            logger.debug(
                f"[ConnectionMonitor] State transition for {device_id}: {previous_state} -> {'online' if is_online else 'offline'}"
            )

        if is_online:
            # Device is responsive
            status["last_seen"] = current_time

            if previous_state == "offline":
                # Device came back online!
                logger.info(f"[ConnectionMonitor] ✅ Device {device_id} is back online")
                status["state"] = "online"
                status["retry_count"] = 0
                status["retry_delay"] = 10

                # Update MQTT availability (use stable_device_id if available)
                if self.mqtt_manager:
                    stable_id = status.get("stable_device_id")
                    await self.mqtt_manager.publish_availability(
                        device_id, online=True, stable_device_id=stable_id
                    )

                # Trigger reconnect callbacks
                for callback in self._on_device_reconnected:
                    try:
                        await callback(device_id)
                    except Exception as e:
                        logger.error(
                            f"[ConnectionMonitor] Reconnect callback failed: {e}"
                        )

                # Phase 2: Replay any queued commands
                await self._replay_queued_commands(device_id)
            else:
                status["state"] = "online"

        else:
            # Device is not responsive
            if previous_state == "online":
                # Device just went offline
                logger.warning(f"[ConnectionMonitor] ⚠️ Device {device_id} went offline")
                status["state"] = "offline"
                status["retry_count"] = 0

                # Update MQTT availability (use stable_device_id if available)
                if self.mqtt_manager:
                    stable_id = status.get("stable_device_id")
                    await self.mqtt_manager.publish_availability(
                        device_id, online=False, stable_device_id=stable_id
                    )

                # Trigger disconnect callbacks
                for callback in self._on_device_disconnected:
                    try:
                        await callback(device_id)
                    except Exception as e:
                        logger.error(
                            f"[ConnectionMonitor] Disconnect callback failed: {e}"
                        )

                # Immediately attempt reconnection
                await self._attempt_reconnection(device_id)

            elif previous_state == "offline":
                # Still offline - attempt recovery with backoff
                await self._attempt_reconnection(device_id)

    async def _attempt_reconnection(self, device_id: str):
        """Attempt to reconnect to an offline device"""
        status = self.device_status.get(device_id)
        if not status:
            logger.warning(
                f"[ConnectionMonitor] Cannot retry {device_id} - no status found"
            )
            return

        current_time = time.time()
        time_since_last_seen = current_time - status["last_seen"]

        # Check if we should retry based on backoff
        if status["retry_count"] > 0:
            if time_since_last_seen < status["retry_delay"]:
                logger.debug(
                    f"[ConnectionMonitor] Skipping retry for {device_id}: waited {time_since_last_seen:.0f}s, need {status['retry_delay']}s"
                )
                return  # Not time to retry yet

        status["retry_count"] += 1
        retry_num = status["retry_count"]

        logger.info(
            f"[ConnectionMonitor] Attempting to reconnect to {device_id} (attempt #{retry_num}, waited {time_since_last_seen:.0f}s)"
        )

        # Try direct reconnection
        success = await self._try_direct_reconnect(device_id)

        if success:
            logger.info(
                f"[ConnectionMonitor] ✅ Successfully reconnected to {device_id}"
            )
            status["state"] = "online"
            status["last_seen"] = current_time
            status["retry_count"] = 0
            status["retry_delay"] = 10

            if self.mqtt_manager:
                stable_id = status.get("stable_device_id")
                await self.mqtt_manager.publish_availability(
                    device_id, online=True, stable_device_id=stable_id
                )

            for callback in self._on_device_reconnected:
                try:
                    await callback(device_id)
                except Exception as e:
                    logger.error(f"[ConnectionMonitor] Reconnect callback failed: {e}")

            # Phase 2: Replay any queued commands
            await self._replay_queued_commands(device_id)
        else:
            # Exponential backoff
            status["retry_delay"] = min(status["retry_delay"] * 2, self.max_retry_delay)
            logger.debug(
                f"[ConnectionMonitor] Reconnection failed for {device_id}, will retry in {status['retry_delay']}s"
            )

            # After several failed attempts, try network scan (if we have stable ID)
            if (
                retry_num == 3
                and status.get("stable_device_id")
                and self.device_migrator
            ):
                logger.info(
                    f"[ConnectionMonitor] Searching network for {device_id} with stable ID {status['stable_device_id']}"
                )
                await self._scan_for_device(status["stable_device_id"])

    async def _try_direct_reconnect(self, device_id: str) -> bool:
        """Try to reconnect to device at its known address"""
        try:
            # Use async subprocess
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "connect",
                device_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=10.0
                )
                stdout_str = stdout.decode().lower()

                if "connected" in stdout_str or "already connected" in stdout_str:
                    # Verify device is actually responsive
                    await asyncio.sleep(1)
                    return await self._check_device_health(device_id)

                return False
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return False
        except Exception as e:
            logger.debug(
                f"[ConnectionMonitor] Direct reconnect failed for {device_id}: {e}"
            )
            return False

    async def _scan_for_device(self, stable_device_id: str):
        """
        Scan network to find a device with a specific stable ID.
        This handles cases where device IP/port changed.
        """
        try:
            logger.info(
                f"[ConnectionMonitor] Scanning network for device with stable ID {stable_device_id}"
            )

            # Trigger ADB discovery (will find devices and auto-migrate if needed)
            await self.adb_bridge.discover_devices()

            logger.info(f"[ConnectionMonitor] Network scan complete")
        except Exception as e:
            logger.error(f"[ConnectionMonitor] Network scan failed: {e}")

    def get_status_summary(self) -> dict:
        """Get summary of monitored devices"""
        online = [d for d, s in self.device_status.items() if s["state"] == "online"]
        offline = [d for d, s in self.device_status.items() if s["state"] == "offline"]

        return {
            "total_devices": len(self.device_status),
            "online": len(online),
            "offline": len(offline),
            "online_devices": online,
            "offline_devices": offline,
            "details": self.device_status,
        }
