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
    """

    def __init__(self, data_dir: str = "data", config_dir: str = "config"):
        self.data_dir = Path(data_dir)
        self.config_dir = Path(config_dir)
        self.device_map: Dict[str, Set[str]] = (
            {}
        )  # stable_device_id -> set of device_ids
        self._load_device_mappings()

    def _load_device_mappings(self):
        """Load all known devices from sensor files"""
        logger.info("[DeviceMigrator] Loading known device mappings...")

        # Scan sensor files
        sensor_files = glob.glob(str(self.data_dir / "sensors_*.json"))
        for file_path in sensor_files:
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                    device_id = data.get("device_id")

                    # Get stable_device_id from first sensor
                    sensors = data.get("sensors", [])
                    if sensors and device_id:
                        stable_id = sensors[0].get("stable_device_id")
                        if stable_id:
                            if stable_id not in self.device_map:
                                self.device_map[stable_id] = set()
                            self.device_map[stable_id].add(device_id)
            except Exception as e:
                logger.debug(f"[DeviceMigrator] Failed to read {file_path}: {e}")

        logger.info(
            f"[DeviceMigrator] Loaded {len(self.device_map)} unique devices with {sum(len(ids) for ids in self.device_map.values())} total device IDs"
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

        # 3. Migrate flows
        flows_dir = self.config_dir / "flows"
        if flows_dir.exists():
            flow_files = glob.glob(
                str(
                    flows_dir
                    / f"flow_{old_device_id.replace(':', '_').replace('.', '_')}_*.json"
                )
            )
            for old_flow_file in flow_files:
                try:
                    with open(old_flow_file, "r") as f:
                        flow_data = json.load(f)

                    # Update device_id
                    flow_data["device_id"] = new_device_id

                    # Update flow_id
                    old_flow_id = flow_data.get("flow_id", "")
                    new_flow_id = old_flow_id.replace(
                        old_device_id.replace(":", "_").replace(".", "_"),
                        new_device_id.replace(":", "_").replace(".", "_"),
                    )
                    flow_data["flow_id"] = new_flow_id

                    # Write to new file
                    new_flow_file = str(flows_dir / f"{new_flow_id}.json")
                    with open(new_flow_file, "w") as f:
                        json.dump(flow_data, f, indent=2)

                    counts["flows"] += 1
                    logger.info(
                        f"[DeviceMigrator] Migrated flow {old_flow_id} to {new_flow_id}"
                    )
                except Exception as e:
                    logger.error(
                        f"[DeviceMigrator] Failed to migrate flow {old_flow_file}: {e}"
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
        """
        if not self.is_known_device(stable_device_id):
            logger.debug(
                f"[DeviceMigrator] Device {new_device_id} ({stable_device_id}) is new - no migration needed"
            )
            return None

        # Check if this exact device_id already exists
        if new_device_id in self.device_map.get(stable_device_id, set()):
            logger.debug(
                f"[DeviceMigrator] Device {new_device_id} already exists - no migration needed"
            )
            return None

        # Get the old device ID
        old_device_ids = self.find_device_by_stable_id(stable_device_id)
        if not old_device_ids:
            return None

        # Use the most recent old device ID
        old_device_id = sorted(old_device_ids)[-1]

        logger.info(
            f"[DeviceMigrator] Detected device address change: {old_device_id} -> {new_device_id}"
        )
        logger.info(f"[DeviceMigrator] Stable device ID: {stable_device_id}")

        # Perform migration
        counts = self.migrate_device_config(
            old_device_id, new_device_id, stable_device_id
        )
        return counts

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
