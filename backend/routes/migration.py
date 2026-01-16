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


@router.post("/cleanup-duplicates")
async def cleanup_duplicate_flow_files():
    """
    Clean up duplicate flow files caused by device IP/port changes.

    When a device reconnects with a new port (e.g., 192.168.1.100:5555 -> :42519),
    flow files may be duplicated. This endpoint:
    1. Identifies flow files for the same device (same IP, different ports)
    2. Consolidates flows into a single file per device
    3. Removes empty/orphaned flow files

    Returns:
        {
            "success": true,
            "files_consolidated": 2,
            "files_removed": 1,
            "flows_deduplicated": 4,
            "details": [...]
        }
    """
    deps = get_deps()
    try:
        logger.info("[API] Starting duplicate flow file cleanup")
        from pathlib import Path
        import json

        results = {
            "files_consolidated": 0,
            "files_removed": 0,
            "flows_deduplicated": 0,
            "details": [],
        }

        # Get flows directory
        flows_dir = Path(deps.flow_manager.storage_dir)
        if not flows_dir.exists():
            return {"success": True, "message": "No flows directory found", **results}

        # Group flow files by IP address
        ip_to_files = {}
        for flow_file in flows_dir.glob("flows_*.json"):
            # Extract IP from filename (e.g., flows_192_168_1_100_5555.json)
            filename = flow_file.stem.replace("flows_", "")
            parts = filename.split("_")
            if len(parts) >= 4:
                # Reconstruct IP (first 4 parts)
                ip = ".".join(parts[:4])
                if ip not in ip_to_files:
                    ip_to_files[ip] = []
                ip_to_files[ip].append(flow_file)

        # Process each IP that has multiple flow files
        for ip, files in ip_to_files.items():
            if len(files) <= 1:
                continue

            logger.info(f"[API] Found {len(files)} flow files for IP {ip}")

            # Find the file with the most recent flows (by last_executed)
            best_file = None
            best_time = ""
            all_flows = {}  # flow_id -> (flow_data, source_file)

            for flow_file in files:
                try:
                    with open(flow_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    for flow in data.get("flows", []):
                        flow_id = flow.get("flow_id")
                        if not flow_id:
                            continue

                        exec_time = flow.get("last_executed") or ""
                        exec_count = flow.get("execution_count") or 0

                        # Keep the flow with most recent execution
                        existing = all_flows.get(flow_id)
                        if existing is None:
                            all_flows[flow_id] = (flow, flow_file)
                        else:
                            existing_flow, _ = existing
                            existing_time = existing_flow.get("last_executed") or ""
                            existing_count = existing_flow.get("execution_count") or 0
                            if exec_time > existing_time or (
                                exec_time == existing_time and exec_count > existing_count
                            ):
                                all_flows[flow_id] = (flow, flow_file)
                                results["flows_deduplicated"] += 1

                        # Track the file with most recent activity
                        if exec_time > best_time:
                            best_time = exec_time
                            best_file = flow_file

                except Exception as e:
                    logger.error(f"[API] Failed to read {flow_file}: {e}")

            if not best_file or not all_flows:
                continue

            # Get the current device_id from the best file
            try:
                with open(best_file, "r", encoding="utf-8") as f:
                    best_data = json.load(f)
                current_device_id = best_data.get("device_id", "")
            except Exception:
                current_device_id = ""

            # Update all flows to use the current device_id
            consolidated_flows = []
            for flow_id, (flow, source_file) in all_flows.items():
                if current_device_id:
                    flow["device_id"] = current_device_id
                consolidated_flows.append(flow)

            # Save consolidated flows to best file
            consolidated_data = {
                "device_id": current_device_id,
                "flows": consolidated_flows,
            }
            with open(best_file, "w", encoding="utf-8") as f:
                json.dump(consolidated_data, f, indent=2)

            results["details"].append({
                "ip": ip,
                "kept_file": best_file.name,
                "flows_count": len(consolidated_flows),
            })

            # Delete other files
            for flow_file in files:
                if flow_file != best_file:
                    try:
                        flow_file.unlink()
                        results["files_removed"] += 1
                        logger.info(f"[API] Removed duplicate file: {flow_file.name}")
                    except Exception as e:
                        logger.error(f"[API] Failed to remove {flow_file}: {e}")

            results["files_consolidated"] += 1

        logger.info(f"[API] Duplicate cleanup complete: {results}")
        return {
            "success": True,
            "message": f"Consolidated {results['files_consolidated']} device(s), "
                       f"removed {results['files_removed']} files, "
                       f"deduplicated {results['flows_deduplicated']} flows",
            **results,
        }

    except Exception as e:
        logger.error(f"[API] Duplicate cleanup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
