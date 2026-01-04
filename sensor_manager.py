"""
Visual Mapper - Sensor Manager
Version: 0.0.5 (Stable Device ID Support)

Manages sensor storage, CRUD operations, and persistence.

Uses stable_device_id (hardware serial) for file naming and sensor IDs
to ensure sensors persist across wireless debugging port changes.
"""

import json
import os
import uuid
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
import logging

from sensor_models import SensorDefinition, SensorList
from services.device_identity import get_device_identity_resolver

logger = logging.getLogger(__name__)


class SensorManager:
    """Manages sensor definitions for devices"""

    def __init__(self, data_dir: str = "data"):
        """
        Initialize sensor manager

        Args:
            data_dir: Directory to store sensor definition files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[SensorManager] Initialized with data_dir={self.data_dir}")

    def _get_sensor_file(self, device_id: str) -> Path:
        """
        Get sensor file path for device.

        Uses stable_device_id (hardware serial) for filename to ensure
        sensors persist across wireless debugging port changes.
        """
        resolver = get_device_identity_resolver(str(self.data_dir))
        safe_device_id = resolver.sanitize_for_filename(device_id)
        return self.data_dir / f"sensors_{safe_device_id}.json"

    def _load_sensor_list(self, device_id: str) -> SensorList:
        """Load sensor list from file"""
        sensor_file = self._get_sensor_file(device_id)

        if not sensor_file.exists():
            logger.info(f"[SensorManager] No sensor file for {device_id}, creating empty list")
            return SensorList(device_id=device_id, sensors=[])

        try:
            with open(sensor_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return SensorList(**data)
        except Exception as e:
            logger.error(f"[SensorManager] Failed to load sensors for {device_id}: {e}")
            return SensorList(device_id=device_id, sensors=[])

    def _save_sensor_list(self, sensor_list: SensorList) -> bool:
        """Save sensor list to file"""
        sensor_file = self._get_sensor_file(sensor_list.device_id)

        try:
            sensor_list.last_modified = datetime.now()
            with open(sensor_file, 'w', encoding='utf-8') as f:
                json.dump(
                    sensor_list.model_dump(mode='json'),
                    f,
                    indent=2,
                    default=str  # Handle datetime serialization
                )
            logger.info(f"[SensorManager] Saved {len(sensor_list.sensors)} sensors for {sensor_list.device_id}")
            return True
        except Exception as e:
            logger.error(f"[SensorManager] Failed to save sensors for {sensor_list.device_id}: {e}")
            return False

    def create_sensor(self, sensor: SensorDefinition) -> SensorDefinition:
        """
        Create a new sensor

        Args:
            sensor: Sensor definition (sensor_id will be generated if empty)

        Returns:
            Created sensor with generated ID

        Raises:
            ValueError: If sensor_id already exists
        """
        # Generate sensor ID if not provided
        if not sensor.sensor_id or sensor.sensor_id == "":
            sensor.sensor_id = self._generate_sensor_id(sensor.device_id)

        # Load existing sensors
        sensor_list = self._load_sensor_list(sensor.device_id)

        # Check for duplicate ID
        if any(s.sensor_id == sensor.sensor_id for s in sensor_list.sensors):
            raise ValueError(f"Sensor ID {sensor.sensor_id} already exists for device {sensor.device_id}")

        # Set timestamps
        now = datetime.now()
        sensor.created_at = now
        sensor.updated_at = now

        # Add to list
        sensor_list.sensors.append(sensor)

        # Save
        if not self._save_sensor_list(sensor_list):
            raise RuntimeError(f"Failed to save sensor {sensor.sensor_id}")

        logger.info(f"[SensorManager] Created sensor {sensor.sensor_id} for device {sensor.device_id}")
        return sensor

    def get_sensor(self, device_id: str, sensor_id: str) -> Optional[SensorDefinition]:
        """Get a specific sensor"""
        sensor_list = self._load_sensor_list(device_id)
        for sensor in sensor_list.sensors:
            if sensor.sensor_id == sensor_id:
                return sensor
        return None

    def get_all_sensors(self, device_id: Optional[str] = None) -> List[SensorDefinition]:
        """
        Get all sensors for a device (or all devices if device_id is None)

        Supports both network device_id (192.168.86.2:46747) and stable_device_id (c7028879b7a83aa7).
        This allows Android companion app to query using stable ID across IP/port changes.

        Args:
            device_id: Optional device ID filter. If None, returns all sensors across all devices.

        Returns:
            List of sensor definitions
        """
        # If no device_id, return all sensors from all devices
        if device_id is None:
            all_sensors = []
            for sensor_file in self.data_dir.glob("sensors_*.json"):
                try:
                    with open(sensor_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        file_sensor_list = SensorList(**data)
                        all_sensors.extend(file_sensor_list.sensors)
                except Exception as e:
                    logger.error(f"[SensorManager] Failed to load {sensor_file}: {e}")
            return all_sensors

        # First try direct file load (for network device_id)
        sensor_list = self._load_sensor_list(device_id)

        # If we found sensors in the direct file, return them
        if sensor_list.sensors:
            return sensor_list.sensors

        # Otherwise, search all sensor files for sensors matching stable_device_id
        # This handles queries with stable device ID (e.g., from Android app)
        matching_sensors = []
        for sensor_file in self.data_dir.glob("sensors_*.json"):
            try:
                with open(sensor_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    file_sensor_list = SensorList(**data)
                    # Check each sensor's stable_device_id
                    for sensor in file_sensor_list.sensors:
                        if sensor.stable_device_id == device_id:
                            matching_sensors.append(sensor)
            except Exception as e:
                logger.error(f"[SensorManager] Failed to load {sensor_file}: {e}")

        return matching_sensors

    def update_sensor(self, sensor: SensorDefinition) -> SensorDefinition:
        """
        Update an existing sensor

        Args:
            sensor: Updated sensor definition

        Returns:
            Updated sensor

        Raises:
            ValueError: If sensor doesn't exist
        """
        sensor_list = self._load_sensor_list(sensor.device_id)

        # Find and update sensor
        found = False
        for i, s in enumerate(sensor_list.sensors):
            if s.sensor_id == sensor.sensor_id:
                sensor.updated_at = datetime.now()
                sensor_list.sensors[i] = sensor
                found = True
                break

        if not found:
            raise ValueError(f"Sensor {sensor.sensor_id} not found for device {sensor.device_id}")

        # Save
        if not self._save_sensor_list(sensor_list):
            raise RuntimeError(f"Failed to update sensor {sensor.sensor_id}")

        logger.info(f"[SensorManager] Updated sensor {sensor.sensor_id}")
        return sensor

    def delete_sensor(self, device_id: str, sensor_id: str) -> bool:
        """
        Delete a sensor

        Args:
            device_id: Device ID
            sensor_id: Sensor ID

        Returns:
            True if deleted, False if not found
        """
        sensor_list = self._load_sensor_list(device_id)

        # Find and remove sensor
        original_count = len(sensor_list.sensors)
        sensor_list.sensors = [s for s in sensor_list.sensors if s.sensor_id != sensor_id]

        if len(sensor_list.sensors) == original_count:
            logger.warning(f"[SensorManager] Sensor {sensor_id} not found for deletion")
            return False

        # Save
        if not self._save_sensor_list(sensor_list):
            raise RuntimeError(f"Failed to delete sensor {sensor_id}")

        logger.info(f"[SensorManager] Deleted sensor {sensor_id}")
        return True

    def delete_all_sensors(self, device_id: str) -> int:
        """
        Delete all sensors for a device

        Returns:
            Number of sensors deleted
        """
        sensor_list = self._load_sensor_list(device_id)
        count = len(sensor_list.sensors)

        sensor_list.sensors = []
        self._save_sensor_list(sensor_list)

        logger.info(f"[SensorManager] Deleted {count} sensors for device {device_id}")
        return count

    def get_device_list(self) -> List[str]:
        """Get list of all device IDs with sensors"""
        devices = []
        for sensor_file in self.data_dir.glob("sensors_*.json"):
            try:
                with open(sensor_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    devices.append(data.get('device_id'))
            except Exception as e:
                logger.error(f"[SensorManager] Failed to read {sensor_file}: {e}")
        return devices

    def export_sensors(self, device_id: str) -> Dict:
        """Export all sensors for a device as JSON"""
        sensor_list = self._load_sensor_list(device_id)
        return sensor_list.model_dump(mode='json')

    def import_sensors(self, data: Dict, device_id: Optional[str] = None, replace: bool = False) -> int:
        """
        Import sensors from JSON data

        Args:
            data: SensorList JSON data
            device_id: Override device_id (if None, use device_id from data)
            replace: If True, replace existing sensors; if False, merge

        Returns:
            Number of sensors imported
        """
        try:
            imported_list = SensorList(**data)

            # Override device_id if provided
            if device_id:
                imported_list.device_id = device_id
                for sensor in imported_list.sensors:
                    sensor.device_id = device_id

            if replace:
                # Replace all sensors
                self._save_sensor_list(imported_list)
                count = len(imported_list.sensors)
            else:
                # Merge with existing sensors
                existing_list = self._load_sensor_list(imported_list.device_id)

                # Add new sensors (skip duplicates)
                existing_ids = {s.sensor_id for s in existing_list.sensors}
                added = 0
                for sensor in imported_list.sensors:
                    if sensor.sensor_id not in existing_ids:
                        existing_list.sensors.append(sensor)
                        added += 1

                self._save_sensor_list(existing_list)
                count = added

            logger.info(f"[SensorManager] Imported {count} sensors for device {imported_list.device_id}")
            return count

        except Exception as e:
            logger.error(f"[SensorManager] Failed to import sensors: {e}")
            raise ValueError(f"Invalid sensor data: {e}")

    def _generate_sensor_id(self, device_id: str) -> str:
        """
        Generate unique sensor ID.

        Uses stable_device_id (hardware serial) prefix for persistence
        across wireless debugging port changes.
        """
        resolver = get_device_identity_resolver(str(self.data_dir))
        safe_device_id = resolver.sanitize_for_filename(device_id)
        unique_id = str(uuid.uuid4())[:8]
        return f"{safe_device_id}_sensor_{unique_id}"
