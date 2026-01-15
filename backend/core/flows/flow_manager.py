"""
Visual Mapper - Flow Manager (Phase 8)
Manages sensor collection flows - both simple and advanced

Uses stable_device_id (hardware serial) for file naming to ensure
flows persist across wireless debugging port changes.
"""

import json
import logging
import os
from typing import Dict, List, Optional
from pathlib import Path

from .flow_models import SensorCollectionFlow, FlowList, sensor_to_simple_flow
from services.device_identity import get_device_identity_resolver

logger = logging.getLogger(__name__)


class FlowManager:
    """
    Manages sensor collection flows
    Supports both simple mode (auto-generated) and advanced mode (user-created)
    """

    def __init__(
        self,
        storage_dir: str = "config/flows",
        template_dir: str = "config/flow_templates",
        data_dir: str = "data",
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Template storage directory (Phase 9)
        self.template_dir = Path(template_dir)
        self.template_dir.mkdir(parents=True, exist_ok=True)

        # Data directory for device identity mapping
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache: device_id -> FlowList
        self._flows: Dict[str, FlowList] = {}

        # Template cache: template_id -> template data
        self._templates: Dict[str, Dict] = {}

        logger.info(
            f"[FlowManager] Initialized with storage: {self.storage_dir.absolute()}, "
            f"templates: {self.template_dir.absolute()}, data_dir: {self.data_dir.absolute()}"
        )

    def reload_flows(self, device_id: str = None):
        """
        Clear cached flows and reload from disk.

        Called after device migration to pick up updated device_id fields.

        Args:
            device_id: If specified, only reload flows for this device.
                      If None, clear all cached flows.
        """
        if device_id:
            # Clear specific device cache
            if device_id in self._flows:
                del self._flows[device_id]
            logger.info(f"[FlowManager] Cleared cache for device {device_id}")
        else:
            # Clear all caches
            self._flows.clear()
            logger.info("[FlowManager] Cleared all flow caches")

    # Alias for backward compatibility with main.py
    def _load_all_flows(self):
        """Alias for reload_flows() - clears cache to force reload from disk"""
        self.reload_flows()

    def _get_flow_file(self, device_id: str) -> Path:
        """
        Get flow file path for device.

        Uses stable_device_id (hardware serial) for filename to ensure
        flows persist across wireless debugging port changes.
        """
        resolver = get_device_identity_resolver(str(self.data_dir))
        safe_device_id = resolver.sanitize_for_filename(device_id)
        return self.storage_dir / f"flows_{safe_device_id}.json"

    def _load_flows(self, device_id: str) -> FlowList:
        """Load flows from disk"""
        flow_file = self._get_flow_file(device_id)

        if not flow_file.exists():
            return FlowList(device_id=device_id, flows=[])

        try:
            with open(flow_file, "r") as f:
                data = json.load(f)
                return FlowList(**data)
        except Exception as e:
            logger.error(f"[FlowManager] Failed to load flows for {device_id}: {e}")
            return FlowList(device_id=device_id, flows=[])

    def _save_flows(self, device_id: str, flow_list: FlowList):
        """Save flows to disk"""
        flow_file = self._get_flow_file(device_id)

        try:
            # Ensure parent directory exists
            flow_file.parent.mkdir(parents=True, exist_ok=True)
            with open(flow_file, "w") as f:
                json.dump(flow_list.dict(), f, indent=2, default=str)
            logger.info(
                f"[FlowManager] Saved {len(flow_list.flows)} flows to {flow_file.absolute()}"
            )
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

            logger.info(
                f"[FlowManager] Created flow {flow.flow_id} for {flow.device_id}"
            )
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

    def get_device_flows(self, device_id: str) -> List[SensorCollectionFlow]:
        """
        Get all flows for a specific device

        Supports both network device_id (192.168.1.2:46747) and stable_device_id (c7028879b7a83aa7).
        This allows Android companion app to query using stable ID across IP/port changes.
        """
        # First try direct file load (for network device_id)
        if device_id not in self._flows:
            self._flows[device_id] = self._load_flows(device_id)

        flows_from_file = self._flows[device_id].flows

        # If we found flows in the direct file, return them
        if flows_from_file:
            return flows_from_file

        # Otherwise, search all flow files for flows matching stable_device_id
        # This handles queries with stable device ID (e.g., from Android app)
        matching_flows = []
        for flow_file in self.storage_dir.glob("flows_*.json"):
            try:
                with open(flow_file, "r") as f:
                    data = json.load(f)
                    flow_list = FlowList(**data)
                    # Check each flow's stable_device_id
                    for flow in flow_list.flows:
                        if flow.stable_device_id == device_id:
                            matching_flows.append(flow)
            except Exception as e:
                logger.error(f"[FlowManager] Failed to load {flow_file}: {e}")

        return matching_flows

    def get_all_flows(self) -> List[SensorCollectionFlow]:
        """
        Get all flows across all devices

        Returns:
            List of all flows from all devices
        """
        all_flows = []

        # Get all device flow files
        for flow_file in self.storage_dir.glob("flows_*.json"):
            try:
                with open(flow_file, "r") as f:
                    data = json.load(f)
                    flow_list = FlowList(**data)
                    all_flows.extend(flow_list.flows)
            except Exception as e:
                logger.error(f"[FlowManager] Failed to load {flow_file}: {e}")

        return all_flows

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
                logger.info(
                    f"[FlowManager] Created simple flow for sensor {sensor.sensor_id}"
                )
                return flow
            return None

        except Exception as e:
            logger.error(f"[FlowManager] Failed to create simple flow: {e}")
            return None

    def get_enabled_flows(self, device_id: str) -> List[SensorCollectionFlow]:
        """Get all enabled flows for a device"""
        all_flows = self.get_device_flows(device_id)
        return [f for f in all_flows if f.enabled]

    def get_flows_for_sensor(
        self, device_id: str, sensor_id: str
    ) -> List[SensorCollectionFlow]:
        """
        Find all flows that capture a specific sensor
        Useful for determining if a sensor is already in a flow
        """
        all_flows = self.get_device_flows(device_id)
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
        simple_flows = [
            f for f in self.get_all_flows(device_id) if f.flow_id.startswith("simple_")
        ]

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
                logger.info(
                    f"[FlowManager] Optimization opportunity: {len(flows)} sensors for {app}"
                )
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
                logger.warning(
                    f"[FlowManager] Device ID mismatch in import, updating to {device_id}"
                )
                flow_list.device_id = device_id

            # Save
            self._flows[device_id] = flow_list
            self._save_flows(device_id, flow_list)

            logger.info(
                f"[FlowManager] Imported {len(flow_list.flows)} flows for {device_id}"
            )
            return True

        except Exception as e:
            logger.error(f"[FlowManager] Failed to import flows: {e}")
            return False

    # ============================================================================
    # Phase 9: Flow Templates
    # ============================================================================

    def _get_template_file(self, template_id: str) -> Path:
        """Get template file path"""
        safe_id = template_id.replace(":", "_").replace(".", "_").replace(" ", "_")
        return self.template_dir / f"{safe_id}.json"

    def save_template(
        self,
        template_id: str,
        name: str,
        description: str,
        steps: List[Dict],
        tags: Optional[List[str]] = None,
        category: Optional[str] = "custom",
    ) -> bool:
        """
        Save a flow as a reusable template

        Args:
            template_id: Unique template identifier
            name: Human-readable template name
            description: Template description
            steps: List of flow steps (as dicts)
            category: Template category (e.g., "navigation", "data_collection", "custom")
            tags: Optional list of tags for filtering

        Returns:
            True if saved successfully
        """
        try:
            from datetime import datetime

            template = {
                "template_id": template_id,
                "name": name,
                "description": description,
                "steps": steps,
                "category": category,
                "tags": tags or [],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "version": "1.0.0",
            }

            # Save to file
            template_file = self._get_template_file(template_id)
            with open(template_file, "w") as f:
                json.dump(template, f, indent=2)

            # Update cache
            self._templates[template_id] = template

            logger.info(f"[FlowManager] Saved template: {template_id} ({name})")
            return True

        except Exception as e:
            logger.error(f"[FlowManager] Failed to save template {template_id}: {e}")
            return False

    def get_template(self, template_id: str) -> Optional[Dict]:
        """Get a specific template by ID (checks builtin templates first)"""
        # Check cache first
        if template_id in self._templates:
            return self._templates[template_id]

        # Check builtin templates
        for builtin in self.get_builtin_templates():
            if builtin.get("template_id") == template_id:
                self._templates[template_id] = builtin
                return builtin

        # Load from file
        template_file = self._get_template_file(template_id)
        if template_file.exists():
            try:
                with open(template_file, "r") as f:
                    template = json.load(f)
                    self._templates[template_id] = template
                    return template
            except Exception as e:
                logger.error(
                    f"[FlowManager] Failed to load template {template_id}: {e}"
                )

        return None

    def list_templates(
        self, category: str = None, tags: List[str] = None
    ) -> List[Dict]:
        """
        List all available templates (builtin + user-created), optionally filtered

        Args:
            category: Filter by category
            tags: Filter by tags (any match)

        Returns:
            List of template metadata (without full steps for performance)
        """
        templates = []

        # First, add built-in templates
        for builtin in self.get_builtin_templates():
            # Apply filters
            if category and builtin.get("category") != category:
                continue

            if tags:
                builtin_tags = set(builtin.get("tags", []))
                if not builtin_tags.intersection(set(tags)):
                    continue

            templates.append(
                {
                    "template_id": builtin.get("template_id"),
                    "name": builtin.get("name"),
                    "description": builtin.get("description"),
                    "category": builtin.get("category"),
                    "tags": builtin.get("tags", []),
                    "step_count": len(builtin.get("steps", [])),
                    "steps": builtin.get("steps", []),  # Include steps for preview
                    "builtin": True,
                }
            )

        # Load user templates from disk
        for template_file in self.template_dir.glob("*.json"):
            try:
                with open(template_file, "r") as f:
                    template = json.load(f)

                    # Apply filters
                    if category and template.get("category") != category:
                        continue

                    if tags:
                        template_tags = set(template.get("tags", []))
                        if not template_tags.intersection(set(tags)):
                            continue

                    # Return metadata with steps for preview
                    templates.append(
                        {
                            "template_id": template.get("template_id"),
                            "name": template.get("name"),
                            "description": template.get("description"),
                            "category": template.get("category"),
                            "tags": template.get("tags", []),
                            "step_count": len(template.get("steps", [])),
                            "steps": template.get("steps", []),
                            "created_at": template.get("created_at"),
                            "version": template.get("version"),
                            "builtin": False,
                        }
                    )

            except Exception as e:
                logger.warning(
                    f"[FlowManager] Failed to load template {template_file}: {e}"
                )

        return sorted(
            templates, key=lambda t: (not t.get("builtin", False), t.get("name", ""))
        )

    def delete_template(self, template_id: str) -> bool:
        """Delete a template"""
        try:
            template_file = self._get_template_file(template_id)

            if template_file.exists():
                template_file.unlink()

            # Remove from cache
            self._templates.pop(template_id, None)

            logger.info(f"[FlowManager] Deleted template: {template_id}")
            return True

        except Exception as e:
            logger.error(f"[FlowManager] Failed to delete template {template_id}: {e}")
            return False

    def create_flow_from_template(
        self,
        template_id: str,
        device_id: str,
        flow_name: str = None,
        flow_id: str = None,
        variable_overrides: Dict[str, str] = None,
    ) -> Optional[SensorCollectionFlow]:
        """
        Create a new flow from a template

        Args:
            template_id: Template to use
            device_id: Target device ID
            flow_name: Optional custom flow name
            flow_id: Optional custom flow ID
            variable_overrides: Optional variable substitutions (e.g., {"app_package": "com.example"})

        Returns:
            New SensorCollectionFlow or None if failed
        """
        template = self.get_template(template_id)
        if not template:
            logger.error(f"[FlowManager] Template not found: {template_id}")
            return None

        try:
            import uuid

            # Generate IDs if not provided
            if not flow_id:
                flow_id = f"from_template_{template_id}_{uuid.uuid4().hex[:8]}"

            if not flow_name:
                flow_name = (
                    f"{template.get('name', 'Template')} - {device_id.split(':')[0]}"
                )

            # Deep copy steps and apply variable overrides
            steps_json = json.dumps(template.get("steps", []))

            if variable_overrides:
                for var_name, var_value in variable_overrides.items():
                    steps_json = steps_json.replace(f"${{{var_name}}}", var_value)

            steps = json.loads(steps_json)

            # Create flow
            from .flow_models import FlowStep

            flow = SensorCollectionFlow(
                flow_id=flow_id,
                device_id=device_id,
                name=flow_name,
                description=f"Created from template: {template.get('name')}",
                steps=[FlowStep(**step) for step in steps],
                enabled=True,
            )

            logger.info(
                f"[FlowManager] Created flow from template: {flow_id} from {template_id}"
            )
            return flow

        except Exception as e:
            logger.error(f"[FlowManager] Failed to create flow from template: {e}")
            return None

    def save_flow_as_template(
        self,
        device_id: str,
        flow_id: str,
        template_name: str,
        template_id: str = None,
        category: str = "custom",
        tags: List[str] = None,
    ) -> bool:
        """
        Save an existing flow as a template

        Args:
            device_id: Source device ID
            flow_id: Source flow ID
            template_name: Name for the template
            template_id: Optional template ID (auto-generated if not provided)
            category: Template category
            tags: Optional tags

        Returns:
            True if saved successfully
        """
        flow = self.get_flow(device_id, flow_id)
        if not flow:
            logger.error(f"[FlowManager] Flow not found: {flow_id}")
            return False

        if not template_id:
            import uuid

            template_id = f"template_{uuid.uuid4().hex[:8]}"

        # Convert steps to dicts
        steps = [step.dict() for step in flow.steps]

        return self.save_template(
            template_id=template_id,
            name=template_name,
            description=f"Template created from flow: {flow.name}",
            steps=steps,
            category=category,
            tags=tags,
        )

    def get_builtin_templates(self) -> List[Dict]:
        """
        Get list of built-in templates

        Returns pre-defined common flow patterns
        """
        return [
            {
                "template_id": "builtin_open_app_wait",
                "name": "Open App and Wait",
                "description": "Launch an app and wait for it to load",
                "category": "navigation",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "${app_package}",
                        "description": "Launch app",
                    },
                    {
                        "step_type": "wait",
                        "duration": 2000,
                        "description": "Wait for app to load",
                    },
                ],
                "tags": ["basic", "app_launch"],
            },
            {
                "template_id": "builtin_scroll_capture",
                "name": "Scroll and Capture",
                "description": "Scroll down and capture sensors",
                "category": "data_collection",
                "steps": [
                    {
                        "step_type": "swipe",
                        "start_x": 540,
                        "start_y": 1500,
                        "end_x": 540,
                        "end_y": 500,
                        "duration": 500,
                        "description": "Scroll down",
                    },
                    {
                        "step_type": "wait",
                        "duration": 1000,
                        "description": "Wait for content",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": ["${sensor_id}"],
                        "description": "Capture sensor",
                    },
                ],
                "tags": ["scroll", "capture"],
            },
            {
                "template_id": "builtin_loop_scroll",
                "name": "Loop Scroll and Capture",
                "description": "Scroll multiple times and capture data each time",
                "category": "data_collection",
                "steps": [
                    {
                        "step_type": "loop",
                        "iterations": 3,
                        "loop_variable": "scroll_count",
                        "loop_steps": [
                            {
                                "step_type": "swipe",
                                "start_x": 540,
                                "start_y": 1500,
                                "end_x": 540,
                                "end_y": 500,
                                "duration": 500,
                            },
                            {"step_type": "wait", "duration": 1000},
                            {
                                "step_type": "capture_sensors",
                                "sensor_ids": ["${sensor_id}"],
                            },
                        ],
                    }
                ],
                "tags": ["loop", "scroll", "capture"],
            },
            {
                "template_id": "builtin_conditional_check",
                "name": "Conditional Element Check",
                "description": "Check if element exists and act accordingly",
                "category": "logic",
                "steps": [
                    {
                        "step_type": "conditional",
                        "condition": "element_exists:text=${check_text}",
                        "true_steps": [
                            {
                                "step_type": "tap",
                                "x": "${tap_x}",
                                "y": "${tap_y}",
                                "description": "Element found - tap it",
                            }
                        ],
                        "false_steps": [
                            {
                                "step_type": "wait",
                                "duration": 2000,
                                "description": "Element not found - wait",
                            }
                        ],
                    }
                ],
                "tags": ["conditional", "element_check"],
            },
            {
                "template_id": "builtin_refresh_capture",
                "name": "Refresh and Capture",
                "description": "Pull to refresh and capture updated data",
                "category": "data_collection",
                "steps": [
                    {"step_type": "pull_refresh", "description": "Pull to refresh"},
                    {
                        "step_type": "wait",
                        "duration": 2000,
                        "description": "Wait for refresh",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": ["${sensor_id}"],
                        "description": "Capture refreshed data",
                    },
                ],
                "tags": ["refresh", "capture"],
            },
        ]

    def get_bundled_app_flows(self) -> List[Dict]:
        """
        Get pre-made flows for common apps that users can install

        These are ready-to-use flows for popular apps. Users select their app
        and can install a complete flow with one click.

        Returns:
            List of bundled app flow definitions
        """
        return [
            # =================================================================
            # WEATHER APPS
            # =================================================================
            {
                "bundle_id": "weather_generic_basic",
                "app_package": "com.weather.Weather",
                "app_name": "Weather (Generic)",
                "name": "Weather Basic Capture",
                "description": "Capture current temperature and conditions from any weather app",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.weather.Weather",
                        "description": "Open weather app",
                    },
                    {
                        "step_type": "wait",
                        "duration": 3000,
                        "description": "Wait for data to load",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture weather data",
                    },
                ],
                "sensors": [],
                "tags": ["weather", "temperature", "basic"],
            },
            # =================================================================
            # SMART HOME / EV APPS
            # =================================================================
            {
                "bundle_id": "tesla_vehicle_status",
                "app_package": "com.teslamotors.tesla",
                "app_name": "Tesla",
                "name": "Tesla Vehicle Status",
                "description": "Capture Tesla vehicle status - battery, range, climate",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.teslamotors.tesla",
                        "description": "Open Tesla app",
                    },
                    {
                        "step_type": "wait",
                        "duration": 5000,
                        "description": "Wait for vehicle data",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture vehicle status",
                    },
                ],
                "sensors": [],
                "tags": ["ev", "tesla", "vehicle", "battery"],
            },
            # =================================================================
            # FITNESS / HEALTH APPS
            # =================================================================
            {
                "bundle_id": "fitbit_daily_stats",
                "app_package": "com.fitbit.FitbitMobile",
                "app_name": "Fitbit",
                "name": "Fitbit Daily Stats",
                "description": "Capture daily steps, heart rate, and sleep data",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.fitbit.FitbitMobile",
                        "description": "Open Fitbit",
                    },
                    {
                        "step_type": "wait",
                        "duration": 4000,
                        "description": "Wait for sync",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture daily stats",
                    },
                ],
                "sensors": [],
                "tags": ["fitness", "health", "steps", "heart_rate"],
            },
            {
                "bundle_id": "samsung_health_stats",
                "app_package": "com.sec.android.app.shealth",
                "app_name": "Samsung Health",
                "name": "Samsung Health Daily Stats",
                "description": "Capture steps, heart rate, and activity from Samsung Health",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.sec.android.app.shealth",
                        "description": "Open Samsung Health",
                    },
                    {
                        "step_type": "wait",
                        "duration": 4000,
                        "description": "Wait for data",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture health stats",
                    },
                ],
                "sensors": [],
                "tags": ["fitness", "health", "samsung", "steps"],
            },
            # =================================================================
            # MUSIC / MEDIA APPS
            # =================================================================
            {
                "bundle_id": "spotify_now_playing",
                "app_package": "com.spotify.music",
                "app_name": "Spotify",
                "name": "Spotify Now Playing",
                "description": "Capture currently playing track info",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.spotify.music",
                        "description": "Open Spotify",
                    },
                    {
                        "step_type": "wait",
                        "duration": 2000,
                        "description": "Wait for app",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture now playing",
                    },
                ],
                "sensors": [],
                "tags": ["music", "spotify", "media", "now_playing"],
            },
            # =================================================================
            # FINANCE / BANKING APPS
            # =================================================================
            {
                "bundle_id": "robinhood_portfolio",
                "app_package": "com.robinhood.android",
                "app_name": "Robinhood",
                "name": "Robinhood Portfolio Value",
                "description": "Capture portfolio value and daily change",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.robinhood.android",
                        "description": "Open Robinhood",
                    },
                    {
                        "step_type": "wait",
                        "duration": 4000,
                        "description": "Wait for data",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture portfolio",
                    },
                ],
                "sensors": [],
                "tags": ["finance", "stocks", "portfolio", "investing"],
            },
            # =================================================================
            # UTILITY APPS
            # =================================================================
            {
                "bundle_id": "speedtest_result",
                "app_package": "org.zwanoo.android.speedtest",
                "app_name": "Speedtest by Ookla",
                "name": "Run Speed Test",
                "description": "Run internet speed test and capture results",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "org.zwanoo.android.speedtest",
                        "description": "Open Speedtest",
                    },
                    {
                        "step_type": "wait",
                        "duration": 2000,
                        "description": "Wait for app",
                    },
                    {
                        "step_type": "tap",
                        "x": 540,
                        "y": 1200,
                        "description": "Tap GO button",
                    },
                    {
                        "step_type": "wait",
                        "duration": 45000,
                        "description": "Wait for test to complete",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture speed results",
                    },
                ],
                "sensors": [],
                "tags": ["network", "speedtest", "internet", "utility"],
            },
            # =================================================================
            # HOME AUTOMATION APPS
            # =================================================================
            {
                "bundle_id": "smartthings_status",
                "app_package": "com.samsung.android.oneconnect",
                "app_name": "SmartThings",
                "name": "SmartThings Device Status",
                "description": "Capture SmartThings device states",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.samsung.android.oneconnect",
                        "description": "Open SmartThings",
                    },
                    {
                        "step_type": "wait",
                        "duration": 3000,
                        "description": "Wait for devices",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture device states",
                    },
                ],
                "sensors": [],
                "tags": ["smarthome", "iot", "samsung", "automation"],
            },
            {
                "bundle_id": "tuya_device_status",
                "app_package": "com.tuya.smart",
                "app_name": "Tuya Smart",
                "name": "Tuya Device Status",
                "description": "Capture Tuya/Smart Life device states",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.tuya.smart",
                        "description": "Open Tuya",
                    },
                    {
                        "step_type": "wait",
                        "duration": 3000,
                        "description": "Wait for devices",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": [],
                        "description": "Capture device states",
                    },
                ],
                "sensors": [],
                "tags": ["smarthome", "iot", "tuya", "automation"],
            },
        ]
