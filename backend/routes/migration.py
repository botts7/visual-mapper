"""
Migration Routes - Device Stable ID Migration

Provides endpoint for migrating device IDs to stable identifiers:
- Global migration using connected devices to update all sensors/flows
- Smart IP-based matching for devices that reconnect with different ports
- Automatic MQTT discovery republishing for updated sensors

This is critical for resilience when devices reconnect with different ports
(e.g., 192.168.1.100:5555 becomes 192.168.1.100:5556 after reconnect).
"""

from fastapi import APIRouter, HTTPException
import logging
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["migration"])


# =============================================================================
# GLOBAL MIGRATION ENDPOINT
# =============================================================================


@router.post("/migrate-stable-ids")
async def migrate_all_stable_ids():
    """
    Smart migration: Use connected devices to update ALL sensors/flows with matching IP.
    This handles the case where a device reconnects with a different port.

    How it works:
    1. Scans all connected devices to build IP -> stable_device_id map
    2. Updates all sensors with matching IP (if not already migrated)
    3. Updates all flows with matching IP (if not already migrated)
    4. Republishes MQTT discovery for updated sensors

    Returns:
        {
            "success": true,
            "sensors_migrated": 42,
            "sensors_skipped": 10,
            "flows_migrated": 5,
            "flows_skipped": 2,
            "ip_mappings": {"192.168.1.100": "abc123def456"},
            "message": "Migrated 42 sensors and 5 flows"
        }
    """
    deps = get_deps()
    try:
        logger.info("[API] Smart migration: Using connected devices to update all data")

        # Step 1: Build IP -> stable_device_id map from connected devices
        ip_to_stable = {}
        connected_devices = await deps.adb_bridge.get_devices()

        for device in connected_devices:
            device_id = device.get("id", "")
            if ":" in device_id:
                ip = device_id.split(":")[0]
                try:
                    stable_id = await deps.adb_bridge.get_device_serial(device_id)
                    if stable_id and not stable_id.startswith(ip.replace(".", "_")):
                        # Only use real hashed IDs, not fallback format
                        ip_to_stable[ip] = stable_id
                        logger.info(f"[API] Mapped {ip} -> {stable_id}")
                except Exception as e:
                    logger.warning(
                        f"[API] Could not get stable ID for {device_id}: {e}"
                    )

        if not ip_to_stable:
            return {
                "success": False,
                "message": "No connected devices with valid stable IDs found",
            }

        results = {
            "sensors_migrated": 0,
            "sensors_skipped": 0,
            "flows_migrated": 0,
            "flows_skipped": 0,
            "ip_mappings": ip_to_stable,
        }

        # Step 2: Update sensors with matching IP
        device_list = deps.sensor_manager.get_device_list()
        for device_id in device_list:
            if not device_id or ":" not in device_id:
                continue
            ip = device_id.split(":")[0]
            if ip not in ip_to_stable:
                continue

            stable_id = ip_to_stable[ip]
            sensors = deps.sensor_manager.get_all_sensors(device_id)

            for sensor in sensors:
                # Check if needs update (no stable_id or has fallback format)
                needs_update = (
                    not sensor.stable_device_id
                    or sensor.stable_device_id.startswith(ip.replace(".", "_"))
                )

                if needs_update:
                    sensor.stable_device_id = stable_id
                    deps.sensor_manager.update_sensor(sensor)
                    results["sensors_migrated"] += 1

                    # Republish MQTT discovery
                    if deps.mqtt_manager:
                        await deps.mqtt_manager.publish_discovery(sensor)
                else:
                    results["sensors_skipped"] += 1

        # Step 3: Update flows with matching IP
        if deps.flow_manager:
            all_flows = deps.flow_manager.get_all_flows()
            for flow in all_flows:
                if ":" not in flow.device_id:
                    continue
                ip = flow.device_id.split(":")[0]
                if ip not in ip_to_stable:
                    continue

                stable_id = ip_to_stable[ip]

                # Check if needs update
                needs_update = (
                    not flow.stable_device_id
                    or flow.stable_device_id.startswith(ip.replace(".", "_"))
                )

                if needs_update:
                    flow.stable_device_id = stable_id
                    deps.flow_manager.update_flow(flow)
                    results["flows_migrated"] += 1
                else:
                    results["flows_skipped"] += 1

        logger.info(f"[API] Migration complete: {results}")
        return {
            "success": True,
            **results,
            "message": f"Migrated {results['sensors_migrated']} sensors and {results['flows_migrated']} flows",
        }

    except Exception as e:
        logger.error(f"[API] Smart migration failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
