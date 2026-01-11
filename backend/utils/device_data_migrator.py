"""
Device Data Migrator - Migrates sensors and flows to use stable device IDs

This utility migrates existing data files from IP:port based naming
to stable_device_id (hardware serial) based naming.

Usage:
    python -m utils.device_data_migrator --dry-run  # Preview changes
    python -m utils.device_data_migrator            # Execute migration
"""

import json
import logging
import os
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class DeviceDataMigrator:
    """Migrates sensor and flow data to use stable device IDs"""

    def __init__(self, data_dir: str = "data", flows_dir: str = "config/flows"):
        self.data_dir = Path(data_dir)
        self.flows_dir = Path(flows_dir)
        self.backup_dir = self.data_dir / "migration_backups"

        # Mapping of old IDs to new stable IDs
        self.id_mappings: Dict[str, str] = {}

        # Track what was migrated
        self.migrated_files: List[str] = []
        self.errors: List[str] = []

    def discover_device_mappings(self, device_serial_map: Dict[str, str]) -> Dict[str, str]:
        """
        Discover mappings between old device IDs (IP:port or hash) and new stable IDs.

        Args:
            device_serial_map: Known mappings like {"192.168.1.2:46747": "R9YT50J4S9D"}

        Returns:
            Complete mapping including derived legacy hashes
        """
        import hashlib

        mappings = dict(device_serial_map)

        # For each known mapping, also map the sanitized versions
        for conn_id, stable_id in list(device_serial_map.items()):
            # Sanitized version of connection ID (used in filenames)
            sanitized = conn_id.replace(":", "_").replace(".", "_")
            mappings[sanitized] = stable_id

            # Try to find the android_id hash if stored
            # The stable_device_id in old files might be the hash
            # We can't reverse the hash, but we can detect and map it

        logger.info(f"[Migrator] Discovered {len(mappings)} ID mappings")
        return mappings

    def migrate_sensors(
        self,
        device_serial_map: Dict[str, str],
        dry_run: bool = True
    ) -> List[Dict]:
        """
        Migrate sensor files to use stable device IDs.

        Args:
            device_serial_map: Mapping of connection_id -> stable_device_id
            dry_run: If True, only report what would change without modifying

        Returns:
            List of migration results
        """
        results = []
        mappings = self.discover_device_mappings(device_serial_map)

        # Find all sensor files
        sensor_files = list(self.data_dir.glob("sensors_*.json"))
        logger.info(f"[Migrator] Found {len(sensor_files)} sensor files")

        for sensor_file in sensor_files:
            result = self._migrate_sensor_file(sensor_file, mappings, dry_run)
            if result:
                results.append(result)

        return results

    def _migrate_sensor_file(
        self,
        sensor_file: Path,
        mappings: Dict[str, str],
        dry_run: bool
    ) -> Optional[Dict]:
        """Migrate a single sensor file"""
        try:
            with open(sensor_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            original_device_id = data.get("device_id", "")
            changes = []

            # Determine the new stable ID
            new_stable_id = None
            for old_pattern, stable_id in mappings.items():
                if old_pattern in original_device_id or old_pattern in sensor_file.name:
                    new_stable_id = stable_id
                    break

            if not new_stable_id:
                # Check if any sensor has a stable_device_id that maps
                for sensor in data.get("sensors", []):
                    old_stable = sensor.get("stable_device_id", "")
                    if old_stable in mappings:
                        new_stable_id = mappings[old_stable]
                        break

            if not new_stable_id:
                logger.debug(f"[Migrator] No mapping found for {sensor_file.name}")
                return None

            # Calculate new filename
            new_filename = f"sensors_{new_stable_id}.json"
            new_path = self.data_dir / new_filename

            if sensor_file.name == new_filename:
                logger.debug(f"[Migrator] {sensor_file.name} already migrated")
                return None

            changes.append(f"Rename: {sensor_file.name} -> {new_filename}")

            # Update sensors within file
            for i, sensor in enumerate(data.get("sensors", [])):
                old_sensor_id = sensor.get("sensor_id", "")
                old_device_id = sensor.get("device_id", "")

                # Update sensor_id prefix if it contains old ID pattern
                new_sensor_id = self._update_sensor_id(old_sensor_id, mappings, new_stable_id)
                if new_sensor_id != old_sensor_id:
                    sensor["sensor_id"] = new_sensor_id
                    changes.append(f"  sensor[{i}].sensor_id: {old_sensor_id} -> {new_sensor_id}")

                # Update device_id to use connection format but keep it for backwards compat
                # Actually, we should keep device_id as connection_id for ADB operations

                # Update stable_device_id to new hardware serial
                old_stable = sensor.get("stable_device_id", "")
                if old_stable != new_stable_id:
                    sensor["stable_device_id"] = new_stable_id
                    changes.append(f"  sensor[{i}].stable_device_id: {old_stable} -> {new_stable_id}")

            result = {
                "file": str(sensor_file),
                "old_filename": sensor_file.name,
                "new_filename": new_filename,
                "stable_id": new_stable_id,
                "changes": changes,
                "sensor_count": len(data.get("sensors", []))
            }

            if not dry_run:
                # Backup original
                self._backup_file(sensor_file)

                # Write updated data
                with open(sensor_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)

                # Rename file
                if sensor_file.name != new_filename:
                    if new_path.exists():
                        # Merge with existing file
                        self._merge_sensor_files(sensor_file, new_path)
                        sensor_file.unlink()
                    else:
                        sensor_file.rename(new_path)

                self.migrated_files.append(str(sensor_file))
                result["status"] = "migrated"
            else:
                result["status"] = "dry_run"

            return result

        except Exception as e:
            error = f"Error migrating {sensor_file}: {e}"
            logger.error(f"[Migrator] {error}")
            self.errors.append(error)
            return {"file": str(sensor_file), "status": "error", "error": str(e)}

    def _update_sensor_id(
        self,
        sensor_id: str,
        mappings: Dict[str, str],
        new_stable_id: str
    ) -> str:
        """Update sensor_id to use stable device ID prefix"""
        # Pattern: 192_168_86_2_46747_sensor_xxxx
        # Should become: R9YT50J4S9D_sensor_xxxx

        for old_pattern, stable_id in mappings.items():
            # Sanitized patterns (used in sensor_id)
            sanitized = old_pattern.replace(":", "_").replace(".", "_")
            if sensor_id.startswith(sanitized):
                # Replace the prefix
                suffix = sensor_id[len(sanitized):]
                return f"{new_stable_id}{suffix}"

        # If no pattern matched, try to extract just the sensor suffix
        match = re.search(r'_sensor_([a-f0-9]+)$', sensor_id)
        if match:
            return f"{new_stable_id}_sensor_{match.group(1)}"

        return sensor_id

    def _merge_sensor_files(self, source: Path, target: Path):
        """Merge sensors from source into target file"""
        try:
            with open(source, 'r', encoding='utf-8') as f:
                source_data = json.load(f)
            with open(target, 'r', encoding='utf-8') as f:
                target_data = json.load(f)

            # Get existing sensor IDs
            existing_ids = {s.get("sensor_id") for s in target_data.get("sensors", [])}

            # Add non-duplicate sensors
            for sensor in source_data.get("sensors", []):
                if sensor.get("sensor_id") not in existing_ids:
                    target_data.setdefault("sensors", []).append(sensor)
                    logger.info(f"[Migrator] Merged sensor {sensor.get('sensor_id')}")

            with open(target, 'w', encoding='utf-8') as f:
                json.dump(target_data, f, indent=2)

        except Exception as e:
            logger.error(f"[Migrator] Failed to merge {source} into {target}: {e}")

    def migrate_flows(
        self,
        device_serial_map: Dict[str, str],
        dry_run: bool = True
    ) -> List[Dict]:
        """Migrate flow files to use stable device IDs"""
        results = []
        mappings = self.discover_device_mappings(device_serial_map)

        flow_files = list(self.flows_dir.glob("flows_*.json"))
        logger.info(f"[Migrator] Found {len(flow_files)} flow files")

        for flow_file in flow_files:
            result = self._migrate_flow_file(flow_file, mappings, dry_run)
            if result:
                results.append(result)

        return results

    def _migrate_flow_file(
        self,
        flow_file: Path,
        mappings: Dict[str, str],
        dry_run: bool
    ) -> Optional[Dict]:
        """Migrate a single flow file"""
        try:
            with open(flow_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            original_device_id = data.get("device_id", "")
            changes = []

            # Determine the new stable ID
            new_stable_id = None
            for old_pattern, stable_id in mappings.items():
                if old_pattern in original_device_id or old_pattern in flow_file.name:
                    new_stable_id = stable_id
                    break

            if not new_stable_id:
                logger.debug(f"[Migrator] No mapping found for {flow_file.name}")
                return None

            # Calculate new filename
            new_filename = f"flows_{new_stable_id}.json"
            new_path = self.flows_dir / new_filename

            if flow_file.name == new_filename:
                logger.debug(f"[Migrator] {flow_file.name} already migrated")
                return None

            changes.append(f"Rename: {flow_file.name} -> {new_filename}")

            result = {
                "file": str(flow_file),
                "old_filename": flow_file.name,
                "new_filename": new_filename,
                "stable_id": new_stable_id,
                "changes": changes,
                "flow_count": len(data.get("flows", []))
            }

            if not dry_run:
                self._backup_file(flow_file)

                if flow_file.name != new_filename:
                    if new_path.exists():
                        # Would need to merge - for now just warn
                        logger.warning(f"[Migrator] Target {new_filename} exists, skipping rename")
                    else:
                        flow_file.rename(new_path)

                self.migrated_files.append(str(flow_file))
                result["status"] = "migrated"
            else:
                result["status"] = "dry_run"

            return result

        except Exception as e:
            error = f"Error migrating {flow_file}: {e}"
            logger.error(f"[Migrator] {error}")
            self.errors.append(error)
            return {"file": str(flow_file), "status": "error", "error": str(e)}

    def _backup_file(self, file_path: Path):
        """Create backup of file before migration"""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{file_path.name}.{timestamp}.bak"
        shutil.copy2(file_path, backup_path)
        logger.debug(f"[Migrator] Backed up {file_path.name} to {backup_path.name}")

    def run_migration(
        self,
        device_serial_map: Dict[str, str],
        dry_run: bool = True
    ) -> Dict:
        """
        Run full migration of sensors and flows.

        Args:
            device_serial_map: Mapping like {"192.168.1.2:46747": "R9YT50J4S9D"}
            dry_run: If True, only report changes without modifying

        Returns:
            Migration report
        """
        logger.info(f"[Migrator] Starting migration (dry_run={dry_run})")

        sensor_results = self.migrate_sensors(device_serial_map, dry_run)
        flow_results = self.migrate_flows(device_serial_map, dry_run)

        report = {
            "dry_run": dry_run,
            "timestamp": datetime.now().isoformat(),
            "device_mappings": device_serial_map,
            "sensors": {
                "files_processed": len(sensor_results),
                "results": sensor_results
            },
            "flows": {
                "files_processed": len(flow_results),
                "results": flow_results
            },
            "migrated_files": self.migrated_files,
            "errors": self.errors
        }

        return report


def main():
    """CLI entry point"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Migrate device data to stable IDs")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying")
    parser.add_argument("--device-map", type=str, help="JSON file with device mappings")
    parser.add_argument("--conn-id", type=str, help="Connection ID (e.g., 192.168.1.2:46747)")
    parser.add_argument("--stable-id", type=str, help="Stable device ID (e.g., R9YT50J4S9D)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Build device map
    device_map = {}

    if args.device_map:
        with open(args.device_map, 'r') as f:
            device_map = json.load(f)
    elif args.conn_id and args.stable_id:
        device_map[args.conn_id] = args.stable_id
    else:
        print("Error: Provide either --device-map or both --conn-id and --stable-id")
        sys.exit(1)

    migrator = DeviceDataMigrator()
    report = migrator.run_migration(device_map, dry_run=args.dry_run)

    print("\n" + "=" * 60)
    print("MIGRATION REPORT")
    print("=" * 60)
    print(f"Mode: {'DRY RUN' if report['dry_run'] else 'EXECUTED'}")
    print(f"Timestamp: {report['timestamp']}")
    print(f"\nDevice Mappings:")
    for conn, stable in report['device_mappings'].items():
        print(f"  {conn} -> {stable}")

    print(f"\nSensors: {report['sensors']['files_processed']} files")
    for r in report['sensors']['results']:
        print(f"  [{r.get('status', 'unknown')}] {r.get('old_filename', 'unknown')}")
        for change in r.get('changes', []):
            print(f"    {change}")

    print(f"\nFlows: {report['flows']['files_processed']} files")
    for r in report['flows']['results']:
        print(f"  [{r.get('status', 'unknown')}] {r.get('old_filename', 'unknown')}")
        for change in r.get('changes', []):
            print(f"    {change}")

    if report['errors']:
        print(f"\nErrors: {len(report['errors'])}")
        for e in report['errors']:
            print(f"  - {e}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
