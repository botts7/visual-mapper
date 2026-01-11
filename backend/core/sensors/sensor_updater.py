"""
Sensor Updater for Visual Mapper
Manages background tasks that periodically update sensor values from device screenshots
"""

import asyncio
import logging
from typing import Dict, Set, Optional
from datetime import datetime

from core.adb.adb_bridge import ADBBridge
from .sensor_manager import SensorManager
from .text_extractor import TextExtractor
from core.mqtt.mqtt_manager import MQTTManager

logger = logging.getLogger(__name__)


class SensorUpdater:
    """
    Manages sensor update loops for all devices
    Each device has its own background task that:
    1. Captures screenshot periodically
    2. Extracts UI elements
    3. Updates all enabled sensors for that device
    4. Publishes to MQTT
    """

    def __init__(
        self,
        adb_bridge: ADBBridge,
        sensor_manager: SensorManager,
        mqtt_manager: MQTTManager,
    ):
        self.adb_bridge = adb_bridge
        self.sensor_manager = sensor_manager
        self.mqtt_manager = mqtt_manager
        # Initialize text extractor for sensor value extraction
        self.text_extractor = TextExtractor()

        # Track running update tasks per device
        self._update_tasks: Dict[str, asyncio.Task] = {}
        self._running_devices: Set[str] = set()
        self._paused_devices: Set[str] = (
            set()
        )  # NEW: Devices with paused sensor updates

        logger.info("[SensorUpdater] Initialized")

    def _get_stable_device_id(self, device_id: str) -> Optional[str]:
        """
        Get stable_device_id from sensors for this device.
        Returns the stable_device_id if any sensor has it, else None.
        """
        sensors = self.sensor_manager.get_all_sensors(device_id)
        for sensor in sensors:
            if sensor.stable_device_id:
                return sensor.stable_device_id
        return None

    async def start_device_updates(self, device_id: str) -> bool:
        """Start sensor update loop for a device"""
        if device_id in self._running_devices:
            logger.warning(
                f"[SensorUpdater] Update loop already running for {device_id}"
            )
            return False

        try:
            # Get stable_device_id from sensors if available (survives IP/port changes)
            stable_device_id = self._get_stable_device_id(device_id)

            # Publish device online status
            await self.mqtt_manager.publish_availability(
                device_id, online=True, stable_device_id=stable_device_id
            )

            # Start background task
            task = asyncio.create_task(self._device_update_loop(device_id))
            self._update_tasks[device_id] = task
            self._running_devices.add(device_id)

            logger.info(f"[SensorUpdater] Started update loop for {device_id}")
            return True

        except Exception as e:
            logger.error(
                f"[SensorUpdater] Failed to start updates for {device_id}: {e}"
            )
            return False

    async def stop_device_updates(self, device_id: str) -> bool:
        """Stop sensor update loop for a device"""
        if device_id not in self._running_devices:
            logger.warning(f"[SensorUpdater] No update loop running for {device_id}")
            return False

        try:
            # Cancel task
            task = self._update_tasks.get(device_id)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Cleanup
            self._update_tasks.pop(device_id, None)
            self._running_devices.discard(device_id)

            # Get stable_device_id from sensors if available
            stable_device_id = self._get_stable_device_id(device_id)

            # Publish device offline status
            await self.mqtt_manager.publish_availability(
                device_id, online=False, stable_device_id=stable_device_id
            )

            logger.info(f"[SensorUpdater] Stopped update loop for {device_id}")
            return True

        except Exception as e:
            logger.error(f"[SensorUpdater] Failed to stop updates for {device_id}: {e}")
            return False

    async def restart_device_updates(self, device_id: str) -> bool:
        """Restart sensor update loop for a device"""
        await self.stop_device_updates(device_id)
        await asyncio.sleep(1)  # Brief delay
        return await self.start_device_updates(device_id)

    async def stop_all_updates(self):
        """Stop all sensor update loops"""
        logger.info("[SensorUpdater] Stopping all update loops...")
        for device_id in list(self._running_devices):
            await self.stop_device_updates(device_id)

    def is_running(self, device_id: str) -> bool:
        """Check if update loop is running for device"""
        return device_id in self._running_devices

    def get_running_devices(self) -> Set[str]:
        """Get set of devices with running update loops"""
        return self._running_devices.copy()

    def pause_device_updates(self, device_id: str) -> bool:
        """
        Pause sensor updates for a device (loop keeps running but skips cycles)
        Used during wizard editing and live streaming to avoid ADB contention
        """
        if device_id not in self._running_devices:
            logger.warning(
                f"[SensorUpdater] Cannot pause - no update loop running for {device_id}"
            )
            return False

        self._paused_devices.add(device_id)
        logger.info(f"[SensorUpdater] Paused sensor updates for {device_id}")
        return True

    def resume_device_updates(self, device_id: str) -> bool:
        """Resume sensor updates for a device"""
        if device_id not in self._paused_devices:
            logger.debug(f"[SensorUpdater] Device {device_id} was not paused")
            return False

        self._paused_devices.discard(device_id)
        logger.info(f"[SensorUpdater] Resumed sensor updates for {device_id}")
        return True

    def is_paused(self, device_id: str) -> bool:
        """Check if sensor updates are paused for device"""
        return device_id in self._paused_devices

    def get_paused_devices(self) -> Set[str]:
        """Get set of devices with paused sensor updates"""
        return self._paused_devices.copy()

    async def _device_update_loop(self, device_id: str):
        """
        Main update loop for a device
        Runs indefinitely until cancelled
        """
        logger.info(f"[SensorUpdater] Update loop started for {device_id}")

        while True:
            try:
                # Check if updates are paused (during wizard editing or streaming)
                if device_id in self._paused_devices:
                    await asyncio.sleep(1)  # Check again in 1 second
                    continue

                # Load enabled sensors for this device
                sensors = self.sensor_manager.get_all_sensors(device_id)
                enabled_sensors = [s for s in sensors if s.enabled]

                if not enabled_sensors:
                    logger.debug(
                        f"[SensorUpdater] No enabled sensors for {device_id}, waiting..."
                    )
                    await asyncio.sleep(30)  # Check every 30s if sensors are added
                    continue

                # Find minimum update interval
                min_interval = min(s.update_interval_seconds for s in enabled_sensors)
                logger.debug(
                    f"[SensorUpdater] {device_id}: {len(enabled_sensors)} enabled sensors, update interval={min_interval}s"
                )

                # Capture screenshot
                try:
                    screenshot_bytes = await self.adb_bridge.capture_screenshot(
                        device_id
                    )
                    logger.debug(
                        f"[SensorUpdater] {device_id}: Screenshot captured ({len(screenshot_bytes)} bytes)"
                    )
                except Exception as e:
                    logger.error(
                        f"[SensorUpdater] {device_id}: Failed to capture screenshot: {e}"
                    )
                    await asyncio.sleep(min_interval)
                    continue

                # Extract UI elements (bounds_only=True for 30-40% faster parsing)
                try:
                    ui_elements = await self.adb_bridge.get_ui_elements(
                        device_id, bounds_only=True
                    )
                    logger.debug(
                        f"[SensorUpdater] {device_id}: Extracted {len(ui_elements)} UI elements (fast mode)"
                    )
                except Exception as e:
                    logger.error(
                        f"[SensorUpdater] {device_id}: Failed to extract UI elements: {e}"
                    )
                    await asyncio.sleep(min_interval)
                    continue

                # Update each sensor
                for sensor in enabled_sensors:
                    try:
                        await self._update_sensor(sensor, screenshot_bytes, ui_elements)
                    except Exception as e:
                        logger.error(
                            f"[SensorUpdater] {device_id}: Failed to update sensor {sensor.sensor_id}: {e}"
                        )
                        # Continue with other sensors even if one fails

                # Wait until next update
                await asyncio.sleep(min_interval)

            except asyncio.CancelledError:
                logger.info(f"[SensorUpdater] Update loop cancelled for {device_id}")
                raise
            except Exception as e:
                logger.error(
                    f"[SensorUpdater] Unexpected error in update loop for {device_id}: {e}"
                )
                await asyncio.sleep(30)  # Wait before retrying

    async def _update_sensor(self, sensor, screenshot_bytes, ui_elements):
        """Update a single sensor and publish to MQTT"""
        try:
            # Extract value based on sensor source type
            if sensor.source.source_type == "element":
                # Extract text from element
                element = next(
                    (
                        el
                        for el in ui_elements
                        if el.get("resource_id") == sensor.source.element_resource_id
                    ),
                    None,
                )
                if not element:
                    # Use DEBUG level - this is expected when screen is off or app isn't on right screen
                    logger.debug(
                        f"[SensorUpdater] Element not found for sensor {sensor.sensor_id}"
                    )
                    # Use fallback value if configured
                    if sensor.extraction_rule.fallback_value:
                        extracted_value = sensor.extraction_rule.fallback_value
                    else:
                        return  # Skip update

                else:
                    # Get text from element
                    source_text = element.get("text", "")
                    if not source_text:
                        logger.warning(
                            f"[SensorUpdater] No text in element for sensor {sensor.sensor_id}"
                        )
                        if sensor.extraction_rule.fallback_value:
                            extracted_value = sensor.extraction_rule.fallback_value
                        else:
                            return

                    # Apply extraction rules
                    extracted_value = self.text_extractor.extract(
                        source_text, sensor.extraction_rule
                    )

            else:
                logger.warning(
                    f"[SensorUpdater] Unsupported source type: {sensor.source.source_type}"
                )
                return

            # Publish to MQTT
            attributes = {
                "last_updated": datetime.now().isoformat(),
                "source_element": sensor.source.element_resource_id,
                "extraction_method": sensor.extraction_rule.method,
                "device_id": sensor.device_id,
            }

            await self.mqtt_manager.publish_sensor_update(
                sensor, str(extracted_value), attributes
            )

            # Update sensor's current_value and last_updated in memory (for API)
            sensor.current_value = str(extracted_value)
            sensor.last_updated = datetime.now()
            self.sensor_manager.update_sensor(sensor)

            logger.debug(
                f"[SensorUpdater] Updated {sensor.sensor_id}: {extracted_value}"
            )

        except Exception as e:
            logger.error(
                f"[SensorUpdater] Failed to update sensor {sensor.sensor_id}: {e}"
            )
            raise
