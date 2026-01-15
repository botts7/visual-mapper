"""
Device Migration Utility
Handles automatic device detection and configuration migration when IP/port changes
"""

import logging
import json
import glob
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class DeviceMigrator:
    """
    Automatically detects when a device changes IP/port and migrates configurations.
    Uses stable_device_id (Android serial number) to identify devices.

    When a device reconnects on a new IP/port, this migrator:
    1. Detects the change using stable_device_id
    2. Updates device_id field in flows so they continue working
    3. Updates device_id field in sensors
    """

    def __init__(self, data_dir: str = "data", config_dir: str = "config"):
        self.data_dir = Path(data_dir)
        self.config_dir = Path(config_dir)
        self.device_map: Dict[str, Set[str]] = (
            {}
        )  # stable_device_id -> set of device_ids
        self._load_device_mappings()

    def _load_device_mappings(self):
        """Load all known devices from DeviceIdentityResolver's mapping file"""
        logger.info("[DeviceMigrator] Loading known device mappings...")

        # Use DeviceIdentityResolver's mapping file as source of truth
        mapping_file = self.data_dir / "device_identity_map.json"
        if mapping_file.exists():
            try:
                with open(mapping_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Build device_map from conn_to_stable mapping
                conn_to_stable = data.get("conn_to_stable", {})
                for conn_id, stable_id in conn_to_stable.items():
                    if stable_id not in self.device_map:
                        self.device_map[stable_id] = set()
                    self.device_map[stable_id].add(conn_id)

                logger.info(
                    f"[DeviceMigrator] Loaded {len(self.device_map)} unique devices "
                    f"from device_identity_map.json"
                )
            except Exception as e:
                logger.error(f"[DeviceMigrator] Failed to read identity map: {e}")
        else:
            logger.info("[DeviceMigrator] No device_identity_map.json found, starting fresh")

        # Also scan flow files for stable_device_id mappings (fallback)
        flows_dir = self.config_dir / "flows"
        if flows_dir.exists():
            for flow_file in flows_dir.glob("flows_*.json"):
                try:
                    with open(flow_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    for flow in data.get("flows", []):
                        stable_id = flow.get("stable_device_id")
                        device_id = flow.get("device_id")
                        if stable_id and device_id:
                            if stable_id not in self.device_map:
                                self.device_map[stable_id] = set()
                            self.device_map[stable_id].add(device_id)
                except Exception as e:
                    logger.debug(f"[DeviceMigrator] Failed to scan {flow_file}: {e}")

        logger.info(
            f"[DeviceMigrator] Loaded {len(self.device_map)} unique devices with "
            f"{sum(len(ids) for ids in self.device_map.values())} total device IDs"
        )

    def find_device_by_stable_id(self, stable_device_id: str) -> Optional[List[str]]:
        """Find all known device IDs for a given stable device ID"""
        return list(self.device_map.get(stable_device_id, []))

    def is_known_device(self, stable_device_id: str) -> bool:
        """Check if this is a previously connected device"""
        return stable_device_id in self.device_map

    def get_primary_device_id(self, stable_device_id: str) -> Optional[str]:
        """Get the most recent device ID for a stable device ID"""
        device_ids = self.device_map.get(stable_device_id, set())
        if device_ids:
            # Return the last one (most recent based on file modification time)
            return sorted(device_ids)[-1]
        return None

    def migrate_device_config(
        self, old_device_id: str, new_device_id: str, stable_device_id: str
    ) -> Dict[str, int]:
        """
        Migrate all configurations from old device ID to new device ID.
        Returns counts of migrated items.
        """
        logger.info(
            f"[DeviceMigrator] Migrating device config from {old_device_id} to {new_device_id}"
        )
        counts = {"sensors": 0, "actions": 0, "flows": 0}

        # 1. Migrate sensor definitions
        old_sensor_file = (
            self.data_dir
            / f"sensors_{old_device_id.replace(':', '_').replace('.', '_')}.json"
        )
        new_sensor_file = (
            self.data_dir
            / f"sensors_{new_device_id.replace(':', '_').replace('.', '_')}.json"
        )

        if old_sensor_file.exists() and not new_sensor_file.exists():
            try:
                with open(old_sensor_file, "r") as f:
                    sensor_data = json.load(f)

                # Update device IDs in sensor data
                sensor_data["device_id"] = new_device_id
                for sensor in sensor_data.get("sensors", []):
                    # Update sensor_id
                    old_sensor_id = sensor.get("sensor_id", "")
                    new_sensor_id = old_sensor_id.replace(
                        old_device_id.replace(":", "_").replace(".", "_"),
                        new_device_id.replace(":", "_").replace(".", "_"),
                    )
                    sensor["sensor_id"] = new_sensor_id
                    sensor["device_id"] = new_device_id
                    counts["sensors"] += 1

                # Write to new file
                with open(new_sensor_file, "w") as f:
                    json.dump(sensor_data, f, indent=2)

                logger.info(
                    f"[DeviceMigrator] Migrated {counts['sensors']} sensors to {new_sensor_file}"
                )
            except Exception as e:
                logger.error(f"[DeviceMigrator] Failed to migrate sensors: {e}")

        # 2. Migrate action definitions
        old_actions_dir = (
            self.data_dir
            / f"actions_{old_device_id.replace(':', '_').replace('.', '_')}"
        )
        new_actions_dir = (
            self.data_dir
            / f"actions_{new_device_id.replace(':', '_').replace('.', '_')}"
        )

        if old_actions_dir.exists() and not new_actions_dir.exists():
            try:
                import shutil

                shutil.copytree(old_actions_dir, new_actions_dir)

                # Update device IDs in action files
                for action_file in new_actions_dir.glob("*.json"):
                    try:
                        with open(action_file, "r") as f:
                            action_data = json.load(f)

                        action_data["device_id"] = new_device_id

                        with open(action_file, "w") as f:
                            json.dump(action_data, f, indent=2)

                        counts["actions"] += 1
                    except Exception as e:
                        logger.error(
                            f"[DeviceMigrator] Failed to update action file {action_file}: {e}"
                        )

                logger.info(
                    f"[DeviceMigrator] Migrated {counts['actions']} actions to {new_actions_dir}"
                )
            except Exception as e:
                logger.error(f"[DeviceMigrator] Failed to migrate actions: {e}")

        # 3. Migrate flows - update device_id in all flows with matching stable_device_id
        flows_dir = self.config_dir / "flows"
        if flows_dir.exists():
            # Flow files are named flows_{stable_device_id}.json or flows_{sanitized_id}.json
            # We need to find flows that have matching stable_device_id inside
            for flow_file in flows_dir.glob("flows_*.json"):
                try:
                    with open(flow_file, "r", encoding="utf-8") as f:
                        flow_list_data = json.load(f)

                    modified = False

                    # Update device_id in the FlowList container
                    if flow_list_data.get("device_id") == old_device_id:
                        flow_list_data["device_id"] = new_device_id
                        modified = True

                    # Update device_id in each flow that has matching stable_device_id
                    for flow in flow_list_data.get("flows", []):
                        flow_stable_id = flow.get("stable_device_id")
                        flow_device_id = flow.get("device_id")

                        # Match by stable_device_id or old device_id
                        if flow_stable_id == stable_device_id or flow_device_id == old_device_id:
                            if flow_device_id != new_device_id:
                                logger.info(
                                    f"[DeviceMigrator] Updating flow '{flow.get('name', flow.get('flow_id'))}': "
                                    f"{flow_device_id} -> {new_device_id}"
                                )
                                flow["device_id"] = new_device_id
                                counts["flows"] += 1
                                modified = True

                    # Save if modified
                    if modified:
                        with open(flow_file, "w", encoding="utf-8") as f:
                            json.dump(flow_list_data, f, indent=2)
                        logger.info(f"[DeviceMigrator] Updated flow file: {flow_file.name}")

                except Exception as e:
                    logger.error(
                        f"[DeviceMigrator] Failed to migrate flows in {flow_file}: {e}"
                    )

        # 4. Update device mapping
        if stable_device_id not in self.device_map:
            self.device_map[stable_device_id] = set()
        self.device_map[stable_device_id].add(new_device_id)

        logger.info(
            f"[DeviceMigrator] Migration complete: {counts['sensors']} sensors, {counts['actions']} actions, {counts['flows']} flows"
        )
        return counts

    def check_and_migrate(
        self, new_device_id: str, stable_device_id: str
    ) -> Optional[Dict[str, int]]:
        """
        Check if device is known and migrate if needed.
        Returns migration counts if migration occurred, None otherwise.

        This method is called when a device connects. It checks if this stable_device_id
        has been seen before with a different connection_id, and if so, updates all
        flows/sensors to use the new connection_id.
        """
        # First, check if this exact device_id is already registered
        if new_device_id in self.device_map.get(stable_device_id, set()):
            logger.debug(
                f"[DeviceMigrator] Device {new_device_id} already registered - no migration needed"
            )
            return None

        # Check if we know this device by stable_id (has previous connections)
        old_device_ids = self.find_device_by_stable_id(stable_device_id)

        # If device_map doesn't have this stable_id, scan flow files directly
        # This handles the case where device_identity_map.json doesn't exist yet
        if not old_device_ids:
            old_device_ids = self._find_device_in_flows(stable_device_id)

        if not old_device_ids:
            logger.debug(
                f"[DeviceMigrator] Device {new_device_id} ({stable_device_id}) is new - no migration needed"
            )
            # Register this new device
            if stable_device_id not in self.device_map:
                self.device_map[stable_device_id] = set()
            self.device_map[stable_device_id].add(new_device_id)
            return None

        # Filter out the new device_id from old_device_ids
        old_device_ids = [did for did in old_device_ids if did != new_device_id]
        if not old_device_ids:
            logger.debug(
                f"[DeviceMigrator] Device {new_device_id} is the only known address - no migration needed"
            )
            return None

        # Use the most recent old device ID
        old_device_id = sorted(old_device_ids)[-1]

        logger.info(
            f"[DeviceMigrator] 🔄 Detected device address change: {old_device_id} -> {new_device_id}"
        )
        logger.info(f"[DeviceMigrator] Stable device ID: {stable_device_id}")

        # Perform migration
        counts = self.migrate_device_config(
            old_device_id, new_device_id, stable_device_id
        )
        return counts

    def _find_device_in_flows(self, stable_device_id: str) -> List[str]:
        """
        Scan flow files to find device_ids associated with a stable_device_id.
        This is a fallback when device_identity_map.json doesn't have the mapping.
        """
        device_ids = set()
        flows_dir = self.config_dir / "flows"

        if flows_dir.exists():
            for flow_file in flows_dir.glob("flows_*.json"):
                try:
                    with open(flow_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    for flow in data.get("flows", []):
                        if flow.get("stable_device_id") == stable_device_id:
                            device_id = flow.get("device_id")
                            if device_id:
                                device_ids.add(device_id)
                except Exception:
                    pass

        return list(device_ids)

    def get_all_known_device_ids(self) -> List[str]:
        """Get all known device IDs (for reconnection attempts)"""
        all_ids = set()
        for device_ids in self.device_map.values():
            all_ids.update(device_ids)
        return sorted(all_ids)

    def get_device_info(self) -> Dict[str, dict]:
        """Get information about all known devices"""
        info = {}
        for stable_id, device_ids in self.device_map.items():
            info[stable_id] = {
                "stable_device_id": stable_id,
                "known_addresses": sorted(device_ids),
                "current_address": sorted(device_ids)[-1] if device_ids else None,
            }
        return info
