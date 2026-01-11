"""
Sensor Management Routes - Home Assistant Sensor Creation and Management

Provides endpoints for managing Home Assistant sensors extracted from Android UI elements:
- CRUD operations for sensors (create, read, update, delete)
- Text extraction testing for sensor value parsing
- Stable device ID migration for resilience across IP/port changes
- MQTT integration for real-time sensor updates to Home Assistant

Sensors support comprehensive device classes, state classes, and units of measurement
as defined by Home Assistant's sensor platform.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
import logging
from routes import get_deps
from core.sensors.sensor_models import SensorDefinition, TextExtractionRule
from core.sensors.text_extractor import TextExtractor
from core.mqtt.ha_device_classes import (
    validate_unit_for_device_class,
    can_use_state_class,
    get_device_class_info,
    export_to_json as export_device_classes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sensors"])


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def validate_sensor_config(sensor: SensorDefinition) -> Optional[str]:
    """
    Validate sensor configuration for Home Assistant compatibility.
    Uses ha_device_classes.py for comprehensive validation.
    Returns error message if invalid, None if valid.
    """
    # Rule 1: Friendly name should not be empty
    if not sensor.friendly_name or sensor.friendly_name.strip() == "":
        return "Friendly name cannot be empty"

    # Rule 2: Binary sensors should NOT have state_class
    if sensor.sensor_type == "binary_sensor":
        if sensor.state_class and sensor.state_class != "none":
            return "Binary sensors cannot have state_class. Remove state_class or change sensor_type to 'sensor'."

    # Rule 3: Check if state_class is allowed for this device class
    if sensor.state_class and sensor.state_class != "none":
        if not can_use_state_class(sensor.device_class, sensor.sensor_type):
            device_info = get_device_class_info(sensor.device_class, sensor.sensor_type)
            if device_info:
                return f"Device class '{sensor.device_class}' ({device_info.description}) does not support state_class. Set state_class to 'none'."
            else:
                return f"Device class '{sensor.device_class}' does not support state_class. Set state_class to 'none'."

    # Rule 4: Sensors with state_class='measurement' MUST have unit_of_measurement
    if sensor.state_class == "measurement":
        if not sensor.unit_of_measurement:
            return "Sensors with state_class='measurement' must have a unit_of_measurement (e.g. %, °C, W). Either add a unit or change state_class to 'none'."

    # Rule 5: Validate unit matches device class expectations
    if (
        sensor.device_class
        and sensor.device_class != "none"
        and sensor.unit_of_measurement
    ):
        if not validate_unit_for_device_class(
            sensor.device_class, sensor.unit_of_measurement, sensor.sensor_type
        ):
            device_info = get_device_class_info(sensor.device_class, sensor.sensor_type)
            if device_info and device_info.valid_units:
                expected_units = (
                    ", ".join(device_info.valid_units)
                    if device_info.valid_units
                    else "no unit"
                )
                return f"Device class '{sensor.device_class}' expects units: {expected_units}. Got: '{sensor.unit_of_measurement}'"

    return None  # Valid


# =============================================================================
# SENSOR CRUD ENDPOINTS
# =============================================================================


@router.get("/sensors")
async def get_all_sensors():
    """Get all sensors across all devices (for dashboard stats)"""
    deps = get_deps()
    try:
        logger.info("[API] Getting all sensors")
        all_sensors = deps.sensor_manager.get_all_sensors()
        return [s.model_dump(mode="json") for s in all_sensors]
    except Exception as e:
        logger.error(f"[API] Get all sensors failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sensors")
async def create_sensor(sensor: SensorDefinition, auto_reuse: bool = True):
    """
    Create a new sensor or reuse an existing matching sensor.

    Args:
        sensor: Sensor definition to create
        auto_reuse: If True (default), automatically reuse existing sensor if a high-confidence
                   match is found (≥90% similarity). Set to False to always create new.

    Returns:
        {
            "success": True,
            "reused": bool,  # True if existing sensor was reused
            "sensor": {...},
            "message": str   # Description of what happened
        }
    """
    deps = get_deps()
    try:
        logger.info(
            f"[API] Creating sensor for device {sensor.device_id} (auto_reuse={auto_reuse})"
        )

        # Get stable device ID if not already set (survives IP/port changes)
        if not sensor.stable_device_id:
            try:
                stable_id = await deps.adb_bridge.get_device_serial(sensor.device_id)
                sensor.stable_device_id = stable_id
                logger.info(f"[API] Set stable_device_id for sensor: {stable_id}")
            except Exception as e:
                logger.warning(f"[API] Could not get stable device ID: {e}")

        # AUTO-REUSE: Check for existing matching sensor
        if auto_reuse:
            try:
                from routes.deduplication import get_dedup_service

                dedup_service = get_dedup_service()

                # Convert sensor to dict for comparison
                sensor_data = sensor.model_dump(mode="json")
                device_id = sensor.stable_device_id or sensor.device_id

                # Find matching sensor with ≥55% similarity (resource_id=35% + extraction=20% = 55%)
                match = dedup_service.find_matching_sensor(
                    device_id, sensor_data, threshold=0.55
                )

                if match:
                    logger.info(
                        f"[API] Auto-reusing existing sensor: {match.sensor_id} ({match.friendly_name})"
                    )
                    return {
                        "success": True,
                        "reused": True,
                        "sensor": match.model_dump(mode="json"),
                        "message": f"Reused existing sensor: {match.friendly_name}",
                    }
            except Exception as e:
                logger.warning(
                    f"[API] Auto-reuse check failed, creating new sensor: {e}"
                )

        # No match found or auto_reuse disabled - create new sensor
        created_sensor = deps.sensor_manager.create_sensor(sensor)

        # Publish MQTT discovery for the new sensor
        if deps.mqtt_manager:
            # Ensure device info is cached for friendly MQTT names
            device_id_for_info = (
                created_sensor.stable_device_id or created_sensor.device_id
            )
            try:
                model = await deps.adb_bridge.get_device_model(sensor.device_id)
                if model:
                    deps.mqtt_manager.set_device_info(device_id_for_info, model=model)
                    logger.info(f"[API] Cached device model for MQTT: {model}")
            except Exception as e:
                logger.debug(f"[API] Could not get device model: {e}")
            try:
                success = await deps.mqtt_manager.publish_discovery(created_sensor)
                if success:
                    logger.info(
                        f"[API] Published MQTT discovery for new sensor {created_sensor.sensor_id}"
                    )
                    # Also publish initial state if available
                    if created_sensor.current_value:
                        await deps.mqtt_manager.publish_state(
                            created_sensor, created_sensor.current_value
                        )
                else:
                    logger.warning(
                        f"[API] Failed to publish MQTT discovery for {created_sensor.sensor_id}"
                    )
            except Exception as e:
                logger.error(
                    f"[API] MQTT discovery failed for {created_sensor.sensor_id}: {e}"
                )

        return {
            "success": True,
            "reused": False,
            "sensor": created_sensor.model_dump(mode="json"),
            "message": f"Created new sensor: {created_sensor.friendly_name}",
        }
    except ValueError as e:
        logger.error(f"[API] Sensor creation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Sensor creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sensors/status/{device_id}")
async def get_sensor_update_status(device_id: str):
    """Get the status of sensor updates for a device (running, paused, stopped)"""
    deps = get_deps()
    try:
        if not deps.sensor_updater:
            return {
                "success": True,
                "device_id": device_id,
                "running": False,
                "paused": False,
                "status": "disabled",
            }

        is_running = deps.sensor_updater.is_running(device_id)
        is_paused = deps.sensor_updater.is_paused(device_id)

        if not is_running:
            status = "stopped"
        elif is_paused:
            status = "paused"
        else:
            status = "running"

        return {
            "success": True,
            "device_id": device_id,
            "running": is_running,
            "paused": is_paused,
            "status": status,
        }
    except Exception as e:
        logger.error(f"[API] Failed to get sensor update status for {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sensors/{device_id}")
async def get_sensors(device_id: str):
    """Get all sensors for a device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Getting sensors for device {device_id}")
        sensors = deps.sensor_manager.get_all_sensors(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "sensors": [s.model_dump(mode="json") for s in sensors],
            "count": len(sensors),
        }
    except Exception as e:
        logger.error(f"[API] Get sensors failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sensors/{device_id}/{sensor_id}")
async def get_sensor(device_id: str, sensor_id: str):
    """Get a specific sensor"""
    deps = get_deps()
    try:
        logger.info(f"[API] Getting sensor {sensor_id} for device {device_id}")
        sensor = deps.sensor_manager.get_sensor(device_id, sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")
        return {"success": True, "sensor": sensor.model_dump(mode="json")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Get sensor failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/sensors")
async def update_sensor(sensor: SensorDefinition):
    """Update an existing sensor"""
    deps = get_deps()
    try:
        logger.info(f"[API] Updating sensor {sensor.sensor_id}")

        # Validate sensor configuration
        validation_error = validate_sensor_config(sensor)
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        updated_sensor = deps.sensor_manager.update_sensor(sensor)

        # Republish MQTT discovery to update Home Assistant (if MQTT enabled)
        mqtt_updated = False
        if deps.mqtt_manager and deps.mqtt_manager.is_connected:
            try:
                mqtt_updated = await deps.mqtt_manager.publish_discovery(updated_sensor)
                if mqtt_updated:
                    logger.info(
                        f"[API] Republished MQTT discovery for {sensor.sensor_id}"
                    )
                    # Also publish current state if available
                    if updated_sensor.current_value:
                        await deps.mqtt_manager.publish_state(
                            updated_sensor, updated_sensor.current_value
                        )
                else:
                    logger.warning(
                        f"[API] Failed to republish MQTT discovery for {sensor.sensor_id}"
                    )
            except Exception as e:
                logger.error(f"[API] MQTT republish failed for {sensor.sensor_id}: {e}")

        return {
            "success": True,
            "sensor": updated_sensor.model_dump(mode="json"),
            "mqtt_updated": mqtt_updated,
        }
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"[API] Sensor update failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Sensor update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sensors/{device_id}/{sensor_id}")
async def delete_sensor(device_id: str, sensor_id: str):
    """Delete a sensor and remove from Home Assistant"""
    deps = get_deps()
    try:
        logger.info(f"[API] Deleting sensor {sensor_id} for device {device_id}")

        # Get sensor before deleting (need it for MQTT removal)
        sensor = deps.sensor_manager.get_sensor(device_id, sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")

        # Remove from Home Assistant via MQTT (if MQTT is enabled)
        mqtt_removed = False
        if deps.mqtt_manager and deps.mqtt_manager.is_connected:
            try:
                mqtt_removed = await deps.mqtt_manager.remove_discovery(sensor)
                if mqtt_removed:
                    logger.info(f"[API] Removed sensor {sensor_id} from Home Assistant")
                else:
                    logger.warning(
                        f"[API] Failed to remove sensor {sensor_id} from Home Assistant"
                    )
            except Exception as e:
                logger.error(f"[API] MQTT removal failed for {sensor_id}: {e}")

        # Delete from local storage
        success = deps.sensor_manager.delete_sensor(device_id, sensor_id)
        if not success:
            raise HTTPException(
                status_code=500, detail=f"Failed to delete sensor {sensor_id}"
            )

        return {
            "success": True,
            "mqtt_removed": mqtt_removed,
            "message": f"Sensor {sensor_id} deleted"
            + (" and removed from Home Assistant" if mqtt_removed else ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Delete sensor failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sensors/{device_id}/cleanup/orphaned")
async def cleanup_orphaned_sensors(device_id: str, confirm: bool = False):
    """
    Delete all orphaned sensors (sensors not used in any flow)

    CAUTION: This is a destructive operation. Use preview=true first to see what would be deleted.
    Pass confirm=true to actually delete.
    """
    if not confirm:
        # Preview mode - just show what would be deleted
        deps = get_deps()
        all_sensors = deps.sensor_manager.get_all_sensors(device_id)
        all_flows = deps.flow_manager.get_all_flows() if deps.flow_manager else []
        flows = [
            f
            for f in all_flows
            if f.device_id == device_id or f.stable_device_id == device_id
        ]
        used_sensor_ids = set()
        for flow in flows:
            for step in flow.steps:
                if step.step_type == "capture_sensors" and step.sensor_ids:
                    used_sensor_ids.update(step.sensor_ids)
        orphaned = [s for s in all_sensors if s.sensor_id not in used_sensor_ids]
        return {
            "preview": True,
            "would_delete": len(orphaned),
            "would_keep": len(all_sensors) - len(orphaned),
            "orphaned_ids": [s.sensor_id for s in orphaned[:20]],
            "message": f"Would delete {len(orphaned)} orphaned sensors. Add ?confirm=true to actually delete.",
        }
    deps = get_deps()
    try:
        logger.info(f"[API] Cleaning up orphaned sensors for device {device_id}")

        # Get all sensors for this device
        all_sensors = deps.sensor_manager.get_all_sensors(device_id)
        if not all_sensors:
            return {"deleted": 0, "message": "No sensors found"}

        # Get all flows to find used sensor IDs
        all_flows = deps.flow_manager.get_all_flows() if deps.flow_manager else []
        # Filter to flows for this device (by device_id or stable_device_id)
        flows = [
            f
            for f in all_flows
            if f.device_id == device_id or f.stable_device_id == device_id
        ]
        used_sensor_ids = set()

        for flow in flows:
            for step in flow.steps:
                if step.step_type == "capture_sensors" and step.sensor_ids:
                    used_sensor_ids.update(step.sensor_ids)

        logger.info(
            f"[API] Found {len(all_sensors)} total sensors, {len(flows)} flows, {len(used_sensor_ids)} sensor IDs used in flows"
        )

        # Find orphaned sensors
        orphaned = [s for s in all_sensors if s.sensor_id not in used_sensor_ids]
        logger.info(f"[API] Found {len(orphaned)} orphaned sensors to delete")

        # Log some examples
        if orphaned:
            logger.info(
                f"[API] Example orphaned: {[s.sensor_id for s in orphaned[:5]]}"
            )

        # Delete orphaned sensors
        deleted_count = 0
        failed = []
        for sensor in orphaned:
            try:
                # Remove from MQTT/Home Assistant first
                if deps.mqtt_manager and deps.mqtt_manager.is_connected:
                    try:
                        await deps.mqtt_manager.remove_discovery(sensor)
                    except Exception as e:
                        logger.warning(
                            f"[API] MQTT removal failed for {sensor.sensor_id}: {e}"
                        )

                # Delete from storage - use the sensor's actual device_id
                success = deps.sensor_manager.delete_sensor(
                    sensor.device_id, sensor.sensor_id
                )
                if success:
                    deleted_count += 1
                else:
                    failed.append(sensor.sensor_id)
            except Exception as e:
                logger.error(f"[API] Failed to delete {sensor.sensor_id}: {e}")
                failed.append(sensor.sensor_id)

        return {
            "deleted": deleted_count,
            "failed": len(failed),
            "failed_ids": failed[:10],  # Return first 10 failed IDs
            "message": f"Deleted {deleted_count} orphaned sensors"
            + (f", {len(failed)} failed" if failed else ""),
        }

    except Exception as e:
        logger.error(f"[API] Cleanup orphaned sensors failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TEXT EXTRACTION TESTING
# =============================================================================


@router.post("/test/extract")
async def test_extraction(request: dict):
    """Test text extraction with a rule (for preview in sensor creation UI)

    Request body:
    {
        "text": "Battery: 94%",
        "extraction_rule": {
            "method": "numeric",
            "extract_numeric": true,
            ...
        }
    }

    Response:
    {
        "success": true,
        "extracted_value": "94",
        "original_text": "Battery: 94%"
    }
    """
    try:
        text = request.get("text", "")
        rule_data = request.get("extraction_rule", {})

        # Create TextExtractionRule from dict
        extraction_rule = TextExtractionRule(**rule_data)

        # Create text extractor and extract
        extractor = TextExtractor()
        result = extractor.extract(text, extraction_rule)

        return {
            "success": True,
            "extracted_value": result,
            "original_text": text,
            "method_used": extraction_rule.method,
        }
    except Exception as e:
        logger.error(f"[API] Test extraction failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "extracted_value": request.get("extraction_rule", {}).get(
                "fallback_value", ""
            ),
            "original_text": request.get("text", ""),
        }


# =============================================================================
# MIGRATION ENDPOINTS
# =============================================================================


@router.post("/sensors/migrate-stable-ids")
async def migrate_sensor_stable_ids():
    """
    Migrate existing sensors to use stable_device_id.
    This ensures sensors survive device IP/port changes.
    """
    deps = get_deps()
    try:
        logger.info("[API] Migrating sensors to stable device IDs")
        migrated = 0
        failed = 0
        already_set = 0
        devices_processed = 0

        # Get all devices with sensors
        device_list = deps.sensor_manager.get_device_list()
        logger.info(f"[API] Found {len(device_list)} devices with sensors")

        for device_id in device_list:
            if not device_id:
                continue
            devices_processed += 1

            # Get all sensors for this device
            sensors = deps.sensor_manager.get_all_sensors(device_id)

            # Get stable ID for this device
            try:
                stable_id = await deps.adb_bridge.get_device_serial(device_id)
            except Exception as e:
                logger.warning(f"[API] Could not get stable ID for {device_id}: {e}")
                failed += len(sensors)
                continue

            # Update each sensor
            for sensor in sensors:
                if sensor.stable_device_id:
                    already_set += 1
                    continue

                try:
                    sensor.stable_device_id = stable_id
                    deps.sensor_manager.update_sensor(sensor)
                    migrated += 1
                    logger.debug(
                        f"[API] Migrated sensor {sensor.sensor_id} to stable ID {stable_id}"
                    )

                    # Republish MQTT discovery with new stable ID
                    if deps.mqtt_manager:
                        await deps.mqtt_manager.publish_discovery(sensor)
                except Exception as e:
                    logger.error(
                        f"[API] Failed to migrate sensor {sensor.sensor_id}: {e}"
                    )
                    failed += 1

        if migrated > 0:
            logger.info(
                f"[API] Republished MQTT discoveries for {migrated} migrated sensors"
            )

        return {
            "success": True,
            "devices_processed": devices_processed,
            "migrated": migrated,
            "already_set": already_set,
            "failed": failed,
            "message": f"Migrated {migrated} sensors across {devices_processed} devices",
        }
    except Exception as e:
        logger.error(f"[API] Sensor migration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SENSOR UPDATE CONTROL (PAUSE/RESUME)
# =============================================================================


@router.post("/sensors/pause/{device_id}")
async def pause_sensor_updates(device_id: str):
    """
    Pause sensor updates for a device (loop keeps running but skips update cycles).
    Used during wizard editing and live streaming to avoid ADB contention.

    The sensor update loop continues running but skips capture cycles,
    allowing quick resume without restarting the entire loop.
    """
    deps = get_deps()
    try:
        if not deps.sensor_updater:
            raise HTTPException(status_code=503, detail="SensorUpdater not initialized")

        success = deps.sensor_updater.pause_device_updates(device_id)
        if success:
            logger.info(f"[API] Paused sensor updates for {device_id}")
            return {
                "success": True,
                "device_id": device_id,
                "paused": True,
                "message": f"Sensor updates paused for {device_id}",
            }
        else:
            return {
                "success": False,
                "device_id": device_id,
                "paused": False,
                "message": f"No sensor update loop running for {device_id}",
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to pause sensor updates for {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sensors/resume/{device_id}")
async def resume_sensor_updates(device_id: str):
    """
    Resume sensor updates for a device after pause.
    Call this when exiting wizard or stopping live streaming.
    """
    deps = get_deps()
    try:
        if not deps.sensor_updater:
            raise HTTPException(status_code=503, detail="SensorUpdater not initialized")

        success = deps.sensor_updater.resume_device_updates(device_id)
        if success:
            logger.info(f"[API] Resumed sensor updates for {device_id}")
            return {
                "success": True,
                "device_id": device_id,
                "paused": False,
                "message": f"Sensor updates resumed for {device_id}",
            }
        else:
            return {
                "success": False,
                "device_id": device_id,
                "message": f"Device {device_id} was not paused",
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to resume sensor updates for {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
