"""
Prerequisite Flows - Registry and management for prerequisite/setup flows

Prerequisite flows are special flows that enable required services like:
- Accessibility service
- Companion app streaming
- Overlay permissions

These flows can be created once and auto-run when entering features that need them.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

# Prerequisite flow types and their metadata
PREREQUISITE_TYPES = {
    "enable_accessibility": {
        "name": "Enable Accessibility Service",
        "description": "Navigate to Settings and enable Visual Mapper accessibility service",
        "check_fn": "check_accessibility_enabled",
        "required_by": ["flow_wizard", "streaming", "auto_click", "element_watcher"],
        "guidance_steps": [
            "Open Settings app",
            "Navigate to Accessibility",
            "Find 'Visual Mapper' in the list",
            "Toggle the service ON",
            "Confirm the permission dialog"
        ]
    },
    "start_streaming": {
        "name": "Start Companion Streaming",
        "description": "Open companion app and start screen streaming",
        "check_fn": "check_streaming_active",
        "required_by": ["flow_wizard_streaming", "live_stream"],
        "guidance_steps": [
            "Open Visual Mapper Companion app",
            "Tap 'Start Streaming' button",
            "Approve the screen capture permission",
            "Wait for streaming to start"
        ]
    },
    "grant_overlay_permission": {
        "name": "Grant Overlay Permission",
        "description": "Enable 'Display over other apps' permission",
        "check_fn": "check_overlay_permission",
        "required_by": ["overlay_recording", "touch_visualization"],
        "guidance_steps": [
            "Open Settings app",
            "Navigate to Apps > Special app access",
            "Find 'Display over other apps'",
            "Select Visual Mapper Companion",
            "Enable the permission"
        ]
    }
}


class PrerequisiteFlowManager:
    """
    Manages prerequisite flows and their configuration per device.

    Storage format (config/prerequisite_flows_{device_id}.json):
    {
        "enable_accessibility": {
            "flow_id": "abc123",
            "auto_run": true,
            "last_run": "2024-01-26T...",
            "success_count": 5,
            "fail_count": 0
        },
        ...
    }
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.config_dir = self.data_dir / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _get_config_path(self, device_id: str) -> Path:
        """Get path to device prerequisite config file."""
        # Sanitize device_id for filesystem
        safe_id = device_id.replace(":", "_").replace("/", "_")
        return self.config_dir / f"prerequisite_flows_{safe_id}.json"

    def _load_config(self, device_id: str) -> Dict[str, Any]:
        """Load prerequisite config for a device."""
        config_path = self._get_config_path(device_id)
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading prerequisite config for {device_id}: {e}")
        return {}

    def _save_config(self, device_id: str, config: Dict[str, Any]) -> bool:
        """Save prerequisite config for a device."""
        config_path = self._get_config_path(device_id)
        try:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving prerequisite config for {device_id}: {e}")
            return False

    def get_prerequisite_types(self) -> Dict[str, Any]:
        """Get all available prerequisite types."""
        return PREREQUISITE_TYPES

    def get_prerequisite_config(self, device_id: str, prereq_type: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific prerequisite on a device."""
        config = self._load_config(device_id)
        return config.get(prereq_type)

    def get_all_prerequisites(self, device_id: str) -> Dict[str, Any]:
        """Get all prerequisite configs for a device."""
        return self._load_config(device_id)

    def link_flow(self, device_id: str, prereq_type: str, flow_id: str) -> bool:
        """
        Link an existing flow as the prerequisite flow for a type.

        Args:
            device_id: The device identifier
            prereq_type: Type of prerequisite (e.g., 'enable_accessibility')
            flow_id: The flow ID to link

        Returns:
            True if successful
        """
        if prereq_type not in PREREQUISITE_TYPES:
            logger.error(f"Unknown prerequisite type: {prereq_type}")
            return False

        config = self._load_config(device_id)

        if prereq_type not in config:
            config[prereq_type] = {}

        config[prereq_type]["flow_id"] = flow_id
        config[prereq_type]["linked_at"] = datetime.now().isoformat()

        logger.info(f"Linked flow {flow_id} to prerequisite {prereq_type} for {device_id}")
        return self._save_config(device_id, config)

    def unlink_flow(self, device_id: str, prereq_type: str) -> bool:
        """Remove flow link from a prerequisite."""
        config = self._load_config(device_id)

        if prereq_type in config and "flow_id" in config[prereq_type]:
            del config[prereq_type]["flow_id"]
            if "linked_at" in config[prereq_type]:
                del config[prereq_type]["linked_at"]
            return self._save_config(device_id, config)

        return True

    def set_auto_run(self, device_id: str, prereq_type: str, enabled: bool) -> bool:
        """
        Enable or disable auto-run for a prerequisite.

        When auto_run is true, the flow will automatically run when entering
        a feature that requires this prerequisite.
        """
        if prereq_type not in PREREQUISITE_TYPES:
            logger.error(f"Unknown prerequisite type: {prereq_type}")
            return False

        config = self._load_config(device_id)

        if prereq_type not in config:
            config[prereq_type] = {}

        config[prereq_type]["auto_run"] = enabled

        logger.info(f"Set auto_run={enabled} for {prereq_type} on {device_id}")
        return self._save_config(device_id, config)

    def record_run(self, device_id: str, prereq_type: str, success: bool) -> bool:
        """Record that a prerequisite flow was run."""
        config = self._load_config(device_id)

        if prereq_type not in config:
            config[prereq_type] = {}

        config[prereq_type]["last_run"] = datetime.now().isoformat()

        if success:
            config[prereq_type]["success_count"] = config[prereq_type].get("success_count", 0) + 1
        else:
            config[prereq_type]["fail_count"] = config[prereq_type].get("fail_count", 0) + 1

        return self._save_config(device_id, config)

    def get_guidance_steps(self, prereq_type: str) -> List[str]:
        """Get the guidance steps for creating a prerequisite flow."""
        if prereq_type in PREREQUISITE_TYPES:
            return PREREQUISITE_TYPES[prereq_type].get("guidance_steps", [])
        return []


# Singleton instance
_prerequisite_manager: Optional[PrerequisiteFlowManager] = None


def get_prerequisite_manager(data_dir: str = "data") -> PrerequisiteFlowManager:
    """Get or create the prerequisite flow manager singleton."""
    global _prerequisite_manager
    if _prerequisite_manager is None:
        _prerequisite_manager = PrerequisiteFlowManager(data_dir)
    return _prerequisite_manager


def init_prerequisite_manager(data_dir: str = "data") -> PrerequisiteFlowManager:
    """Initialize the prerequisite flow manager (call at startup)."""
    global _prerequisite_manager
    _prerequisite_manager = PrerequisiteFlowManager(data_dir)
    logger.info("[PrerequisiteFlows] Manager initialized")
    return _prerequisite_manager
