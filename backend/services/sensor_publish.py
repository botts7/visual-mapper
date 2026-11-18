"""
Sensor Publish - startup/republish rules for sensor MQTT messages.

Startup paths (device discovered, delayed publish for existing devices) used
to publish discovery AND the cached `current_value` from the sensors file for
every sensor. For a disabled sensor that cached value can be months old, and
on a shared broker the retained state overwrites a live value.

Rules:
- Discovery is always published (a disabled sensor keeps its HA entity and
  history; disabling in Visual Mapper should not delete it from HA).
- A cached state is only published for ENABLED sensors.
"""

import logging
from typing import Iterable

logger = logging.getLogger(__name__)


def should_publish_cached_state(sensor) -> bool:
    """Only enabled sensors with a cached value get their state republished."""
    return bool(getattr(sensor, "enabled", True) and sensor.current_value)


async def publish_sensor_on_startup(mqtt_manager, sensor, label: str = "initial") -> bool:
    """
    Publish discovery, then the cached state if allowed.

    Returns:
        True if a state was published
    """
    await mqtt_manager.publish_discovery(sensor)
    logger.debug(f"[Server] Published discovery for {sensor.sensor_id}")

    if not should_publish_cached_state(sensor):
        if sensor.current_value and not getattr(sensor, "enabled", True):
            logger.info(
                f"[Server] Skipped cached state for disabled sensor {sensor.sensor_id}"
            )
        return False

    await mqtt_manager.publish_state(sensor, sensor.current_value)
    logger.info(
        f"[Server] Published {label} state for {sensor.sensor_id}: {sensor.current_value}"
    )
    return True


def sensor_attributes(sensor) -> dict:
    """Attribute payload, same keys as the flow batch publish."""
    last_updated = getattr(sensor, "last_updated", None)
    source = getattr(sensor, "source", None)
    rule = getattr(sensor, "extraction_rule", None)
    return {
        "last_updated": last_updated.isoformat() if last_updated else None,
        "source_element": source.element_resource_id if source else None,
        "extraction_method": rule.method if rule else None,
        "device_id": sensor.device_id,
    }


async def republish_sensor_attributes(mqtt_manager, sensors: Iterable) -> int:
    """Republish attributes (with the current device_id) for enabled sensors."""
    count = 0
    for sensor in sensors:
        if not getattr(sensor, "enabled", True):
            continue
        try:
            if await mqtt_manager.publish_attributes(sensor, sensor_attributes(sensor)):
                count += 1
        except Exception as e:
            logger.warning(
                f"[Server] Failed to republish attributes for {sensor.sensor_id}: {e}"
            )
    return count
