"""
MQTT Control Routes - MQTT Connection and Home Assistant Integration

Provides endpoints for controlling MQTT sensor updates and Home Assistant discovery:
- Start/stop/restart sensor update loops for devices
- Get MQTT connection status
- Manually publish/remove MQTT discovery messages for sensors
- Bulk publish discovery for all sensors on a device

Integrates with Home Assistant MQTT Discovery protocol for automatic
sensor registration and real-time state updates.
"""

from fastapi import APIRouter, HTTPException
import logging
import os
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mqtt", tags=["mqtt"])

# MQTT Configuration (from environment variables)
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_DISCOVERY_PREFIX = os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant")


# =============================================================================
# SENSOR UPDATE CONTROL
# =============================================================================


@router.post("/start/{device_id}")
async def start_sensor_updates(device_id: str):
    """Start sensor update loop for device"""
    deps = get_deps()
    if not deps.sensor_updater:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Starting sensor updates for {device_id}")
        success = await deps.sensor_updater.start_device_updates(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": (
                "Sensor updates started" if success else "Failed to start updates"
            ),
        }
    except Exception as e:
        logger.error(f"[API] Start updates failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop/{device_id}")
async def stop_sensor_updates(device_id: str):
    """Stop sensor update loop for device"""
    deps = get_deps()
    if not deps.sensor_updater:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Stopping sensor updates for {device_id}")
        success = await deps.sensor_updater.stop_device_updates(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": (
                "Sensor updates stopped" if success else "Failed to stop updates"
            ),
        }
    except Exception as e:
        logger.error(f"[API] Stop updates failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restart/{device_id}")
async def restart_sensor_updates(device_id: str):
    """Restart sensor update loop for device"""
    deps = get_deps()
    if not deps.sensor_updater:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Restarting sensor updates for {device_id}")
        success = await deps.sensor_updater.restart_device_updates(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": (
                "Sensor updates restarted" if success else "Failed to restart updates"
            ),
        }
    except Exception as e:
        logger.error(f"[API] Restart updates failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# MQTT STATUS
# =============================================================================


@router.get("/status")
async def mqtt_status():
    """Get MQTT connection status and running devices"""
    deps = get_deps()
    if not deps.mqtt_manager or not deps.sensor_updater:
        return {
            "connected": False,
            "broker": MQTT_BROKER,
            "port": MQTT_PORT,
            "running_devices": [],
            "message": "MQTT not initialized",
        }

    return {
        "connected": deps.mqtt_manager.is_connected,
        "broker": MQTT_BROKER,
        "port": MQTT_PORT,
        "discovery_prefix": MQTT_DISCOVERY_PREFIX,
        "running_devices": list(deps.sensor_updater.get_running_devices()),
        "message": (
            "MQTT connected" if deps.mqtt_manager.is_connected else "MQTT disconnected"
        ),
    }


# =============================================================================
# MQTT DISCOVERY MANAGEMENT
# =============================================================================


@router.post("/publish-discovery/{device_id}/{sensor_id}")
async def publish_sensor_discovery(device_id: str, sensor_id: str):
    """Manually publish MQTT discovery for a sensor"""
    deps = get_deps()
    if not deps.mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Publishing discovery for {device_id}/{sensor_id}")
        sensor = deps.sensor_manager.get_sensor(device_id, sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")

        success = await deps.mqtt_manager.publish_discovery(sensor)
        return {
            "success": success,
            "device_id": device_id,
            "sensor_id": sensor_id,
            "message": (
                "Discovery published" if success else "Failed to publish discovery"
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Publish discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/remove-discovery/{device_id}/{sensor_id}")
async def remove_sensor_discovery(device_id: str, sensor_id: str):
    """Remove MQTT discovery for a sensor (unpublish from HA)"""
    deps = get_deps()
    if not deps.mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Removing discovery for {device_id}/{sensor_id}")
        sensor = deps.sensor_manager.get_sensor(device_id, sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")

        success = await deps.mqtt_manager.remove_discovery(sensor)
        return {
            "success": success,
            "device_id": device_id,
            "sensor_id": sensor_id,
            "message": "Discovery removed" if success else "Failed to remove discovery",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Remove discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/publish-discovery-all/{device_id}")
async def publish_all_sensor_discoveries(device_id: str, in_flows_only: bool = True):
    """
    Publish MQTT discovery for sensors on a device.

    Args:
        device_id: The device ID
        in_flows_only: If True (default), only publish sensors that are referenced in enabled flows.
                      If False, publish ALL sensors on the device.
    """
    deps = get_deps()
    if not deps.mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(
            f"[API] Publishing discovery for sensors on {device_id} (in_flows_only={in_flows_only})"
        )
        sensors = deps.sensor_manager.get_all_sensors(device_id)

        # Filter to only sensors in enabled flows if requested
        if in_flows_only and deps.flow_manager:
            sensors_in_flows = set()
            all_flows = deps.flow_manager.get_all_flows()
            for flow in all_flows:
                if flow.enabled:  # Only consider enabled flows
                    for step in flow.steps:
                        if step.step_type == "capture_sensors":
                            sensors_in_flows.update(step.sensor_ids or [])

            original_count = len(sensors)
            sensors = [s for s in sensors if s.sensor_id in sensors_in_flows]
            logger.info(
                f"[API] Filtered to {len(sensors)}/{original_count} sensors in enabled flows"
            )

        if not sensors:
            return {
                "success": True,
                "device_id": device_id,
                "published_count": 0,
                "message": "No sensors found for device",
            }

        # Ensure device info is cached for friendly MQTT names
        # Try to get model from first sensor's connection or ADB
        if sensors and deps.adb_bridge:
            first_sensor = sensors[0]
            try:
                # Try the original device_id (IP:port) to get model via ADB
                model = await deps.adb_bridge.get_device_model(first_sensor.device_id)
                if model:
                    # Cache using stable_device_id if available
                    cache_id = first_sensor.stable_device_id or device_id
                    deps.mqtt_manager.set_device_info(cache_id, model=model)
                    logger.info(f"[API] Cached device model for MQTT: {model}")
            except Exception as e:
                logger.debug(f"[API] Could not get device model for {device_id}: {e}")

        published_count = 0
        failed_sensors = []

        for sensor in sensors:
            try:
                success = await deps.mqtt_manager.publish_discovery(sensor)
                if success:
                    published_count += 1
                    logger.info(f"[API] Published discovery for {sensor.sensor_id}")
                else:
                    failed_sensors.append(sensor.sensor_id)
            except Exception as e:
                logger.error(
                    f"[API] Failed to publish discovery for {sensor.sensor_id}: {e}"
                )
                failed_sensors.append(sensor.sensor_id)

        return {
            "success": True,
            "device_id": device_id,
            "total_sensors": len(sensors),
            "published_count": published_count,
            "failed_sensors": failed_sensors,
            "message": f"Published {published_count}/{len(sensors)} sensor discoveries",
        }
    except Exception as e:
        logger.error(f"[API] Bulk publish discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DEVICE INFO (FOR FRIENDLY MQTT NAMES)
# =============================================================================


@router.post("/device-info/{device_id}")
async def set_device_info(device_id: str, info: dict):
    """
    Set device info for friendly MQTT device names in Home Assistant

    Body:
        model: Device model (e.g., "SM X205", "Galaxy Tab A7")
        friendly_name: Custom name (overrides model)
        app_name: App context (e.g., "BYD", "Spotify")

    Example:
        POST /api/mqtt/device-info/192.168.1.2:46747
        {"model": "Galaxy Tab A7", "app_name": "BYD"}

    Result in HA: Device name becomes "Galaxy Tab A7 - BYD"
    """
    deps = get_deps()
    if not deps.mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        deps.mqtt_manager.set_device_info(
            device_id,
            model=info.get("model"),
            friendly_name=info.get("friendly_name"),
            app_name=info.get("app_name"),
        )

        # Return current display name
        display_name = deps.mqtt_manager.get_device_display_name(device_id)

        return {
            "success": True,
            "device_id": device_id,
            "display_name": display_name,
            "message": f"Device info updated. MQTT device name: {display_name}",
        }
    except Exception as e:
        logger.error(f"[API] Set device info failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/device-info/{device_id}")
async def get_device_info(device_id: str):
    """Get current device info and display name"""
    deps = get_deps()
    if not deps.mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        info = deps.mqtt_manager._device_info.get(device_id, {})
        display_name = deps.mqtt_manager.get_device_display_name(device_id)

        return {"device_id": device_id, "info": info, "display_name": display_name}
    except Exception as e:
        logger.error(f"[API] Get device info failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
