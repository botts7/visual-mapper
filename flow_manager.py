"""
Visual Mapper - Flow Manager (Phase 8)
Manages sensor collection flows - both simple and advanced
"""

import json
import logging
import os
from typing import Dict, List, Optional
from pathlib import Path

from flow_models import SensorCollectionFlow, FlowList, sensor_to_simple_flow

logger = logging.getLogger(__name__)


class FlowManager:
    """
    Manages sensor collection flows
    Supports both simple mode (auto-generated) and advanced mode (user-created)
    """

    def __init__(self, storage_dir: str = "config/flows"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache: device_id -> FlowList
        self._flows: Dict[str, FlowList] = {}

        logger.info(f"[FlowManager] Initialized with storage: {self.storage_dir}")

    def _get_flow_file(self, device_id: str) -> Path:
        """Get flow file path for device"""
        safe_device_id = device_id.replace(":", "_").replace(".", "_")
        return self.storage_dir / f"flows_{safe_device_id}.json"

    def _load_flows(self, device_id: str) -> FlowList:
        """Load flows from disk"""
        flow_file = self._get_flow_file(device_id)

        if not flow_file.exists():
            return FlowList(device_id=device_id, flows=[])

        try:
            with open(flow_file, 'r') as f:
                data = json.load(f)
                return FlowList(**data)
        except Exception as e:
            logger.error(f"[FlowManager] Failed to load flows for {device_id}: {e}")
            return FlowList(device_id=device_id, flows=[])

    def _save_flows(self, device_id: str, flow_list: FlowList):
        """Save flows to disk"""
        flow_file = self._get_flow_file(device_id)

        try:
            with open(flow_file, 'w') as f:
                json.dump(flow_list.dict(), f, indent=2, default=str)
            logger.debug(f"[FlowManager] Saved {len(flow_list.flows)} flows for {device_id}")
        except Exception as e:
            logger.error(f"[FlowManager] Failed to save flows for {device_id}: {e}")

    def create_flow(self, flow: SensorCollectionFlow) -> bool:
        """Create a new flow"""
        try:
            # Load existing flows
            if flow.device_id not in self._flows:
                self._flows[flow.device_id] = self._load_flows(flow.device_id)

            flow_list = self._flows[flow.device_id]

            # Check for duplicate flow_id
            if any(f.flow_id == flow.flow_id for f in flow_list.flows):
                logger.error(f"[FlowManager] Flow {flow.flow_id} already exists")
                return False

            # Add flow
            flow_list.flows.append(flow)

            # Save
            self._save_flows(flow.device_id, flow_list)

            logger.info(f"[FlowManager] Created flow {flow.flow_id} for {flow.device_id}")
            return True

        except Exception as e:
            logger.error(f"[FlowManager] Failed to create flow: {e}")
            return False

    def get_flow(self, device_id: str, flow_id: str) -> Optional[SensorCollectionFlow]:
        """Get a specific flow"""
        if device_id not in self._flows:
            self._flows[device_id] = self._load_flows(device_id)

        flow_list = self._flows[device_id]
        return next((f for f in flow_list.flows if f.flow_id == flow_id), None)

    def get_all_flows(self, device_id: str) -> List[SensorCollectionFlow]:
        """Get all flows for a device"""
        if device_id not in self._flows:
            self._flows[device_id] = self._load_flows(device_id)

        return self._flows[device_id].flows

    def update_flow(self, flow: SensorCollectionFlow) -> bool:
        """Update an existing flow"""
        try:
            if flow.device_id not in self._flows:
                self._flows[flow.device_id] = self._load_flows(flow.device_id)

            flow_list = self._flows[flow.device_id]

            # Find and replace
            for i, f in enumerate(flow_list.flows):
                if f.flow_id == flow.flow_id:
                    flow_list.flows[i] = flow
                    self._save_flows(flow.device_id, flow_list)
                    logger.info(f"[FlowManager] Updated flow {flow.flow_id}")
                    return True

            logger.error(f"[FlowManager] Flow {flow.flow_id} not found")
            return False

        except Exception as e:
            logger.error(f"[FlowManager] Failed to update flow: {e}")
            return False

    def delete_flow(self, device_id: str, flow_id: str) -> bool:
        """Delete a flow"""
        try:
            if device_id not in self._flows:
                self._flows[device_id] = self._load_flows(device_id)

            flow_list = self._flows[device_id]

            # Remove flow
            initial_count = len(flow_list.flows)
            flow_list.flows = [f for f in flow_list.flows if f.flow_id != flow_id]

            if len(flow_list.flows) == initial_count:
                logger.error(f"[FlowManager] Flow {flow_id} not found")
                return False

            self._save_flows(device_id, flow_list)
            logger.info(f"[FlowManager] Deleted flow {flow_id}")
            return True

        except Exception as e:
            logger.error(f"[FlowManager] Failed to delete flow: {e}")
            return False

    def create_simple_flow_from_sensor(self, sensor) -> Optional[SensorCollectionFlow]:
        """
        Create a simple auto-generated flow from a sensor with navigation config
        This is the "Simple Mode" - one sensor per flow
        """
        try:
            flow = sensor_to_simple_flow(sensor)
            if self.create_flow(flow):
                logger.info(f"[FlowManager] Created simple flow for sensor {sensor.sensor_id}")
                return flow
            return None

        except Exception as e:
            logger.error(f"[FlowManager] Failed to create simple flow: {e}")
            return None

    def get_enabled_flows(self, device_id: str) -> List[SensorCollectionFlow]:
        """Get all enabled flows for a device"""
        all_flows = self.get_all_flows(device_id)
        return [f for f in all_flows if f.enabled]

    def get_flows_for_sensor(self, device_id: str, sensor_id: str) -> List[SensorCollectionFlow]:
        """
        Find all flows that capture a specific sensor
        Useful for determining if a sensor is already in a flow
        """
        all_flows = self.get_all_flows(device_id)
        matching_flows = []

        for flow in all_flows:
            for step in flow.steps:
                if step.step_type == "capture_sensors" and step.sensor_ids:
                    if sensor_id in step.sensor_ids:
                        matching_flows.append(flow)
                        break

        return matching_flows

    def optimize_flows(self, device_id: str) -> List[SensorCollectionFlow]:
        """
        Analyze existing simple flows and suggest optimized advanced flows
        Groups sensors by target_app to reduce redundant navigation

        Returns: List of suggested optimized flows
        """
        # Get all simple flows (auto-generated from sensors)
        simple_flows = [f for f in self.get_all_flows(device_id) if f.flow_id.startswith("simple_")]

        # Group by target app
        app_groups: Dict[str, List[SensorCollectionFlow]] = {}

        for flow in simple_flows:
            # Find launch_app step
            target_app = None
            for step in flow.steps:
                if step.step_type == "launch_app":
                    target_app = step.package
                    break

            if target_app:
                if target_app not in app_groups:
                    app_groups[target_app] = []
                app_groups[target_app].append(flow)

        # Suggest optimized flows
        suggested = []

        for app, flows in app_groups.items():
            if len(flows) > 1:  # Only optimize if multiple sensors for same app
                logger.info(f"[FlowManager] Optimization opportunity: {len(flows)} sensors for {app}")
                # TODO: Create optimized flow combining all sensors
                # This would require more sophisticated merging logic

        return suggested

    def export_flows(self, device_id: str) -> Dict:
        """Export all flows for backup/sharing"""
        if device_id not in self._flows:
            self._flows[device_id] = self._load_flows(device_id)

        return self._flows[device_id].dict()

    def import_flows(self, device_id: str, data: Dict) -> bool:
        """Import flows from backup/sharing"""
        try:
            flow_list = FlowList(**data)

            # Ensure device_id matches
            if flow_list.device_id != device_id:
                logger.warning(f"[FlowManager] Device ID mismatch in import, updating to {device_id}")
                flow_list.device_id = device_id

            # Save
            self._flows[device_id] = flow_list
            self._save_flows(device_id, flow_list)

            logger.info(f"[FlowManager] Imported {len(flow_list.flows)} flows for {device_id}")
            return True

        except Exception as e:
            logger.error(f"[FlowManager] Failed to import flows: {e}")
            return False
