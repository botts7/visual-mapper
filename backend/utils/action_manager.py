"""
Action Manager for Visual Mapper

Handles storage, retrieval, and management of device actions.
Similar to sensor_manager.py but for actions.
"""

import json
import os
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from utils.action_models import (
    ActionDefinition,
    ActionType,
    TapAction,
    SwipeAction,
    TextInputAction,
    KeyEventAction,
    LaunchAppAction,
    DelayAction,
    MacroAction,
)
from utils.error_handler import (
    VisualMapperError,
    logger,
    ErrorContext,
    ActionNotFoundError,
    ActionValidationError
)


class ActionManager:
    """Manages action storage and retrieval"""

    def __init__(self, data_dir: str = "data"):
        """
        Initialize Action Manager

        Args:
            data_dir: Directory to store action definitions
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        logger.info(f"ActionManager initialized with data_dir: {self.data_dir}")

    def _get_actions_file(self, device_id: str) -> Path:
        """Get the actions file path for a device"""
        return self.data_dir / f"actions_{device_id}.json"

    def _load_actions(self, device_id: str) -> List[ActionDefinition]:
        """Load actions from file"""
        actions_file = self._get_actions_file(device_id)

        if not actions_file.exists():
            return []

        try:
            with open(actions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [ActionDefinition(**action) for action in data]
        except Exception as e:
            logger.error(f"Error loading actions for device {device_id}: {e}")
            return []

    def _save_actions(self, device_id: str, actions: List[ActionDefinition]):
        """Save actions to file"""
        actions_file = self._get_actions_file(device_id)

        try:
            with open(actions_file, 'w', encoding='utf-8') as f:
                data = [action.dict() for action in actions]
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Saved {len(actions)} actions for device {device_id}")
        except Exception as e:
            logger.error(f"Error saving actions for device {device_id}: {e}")
            raise VisualMapperError(f"Failed to save actions: {e}")

    def create_action(
        self,
        device_id: str,
        action: ActionType,
        tags: List[str] = None,
        source_app: str = None,
        # Navigation configuration (optional)
        target_app: str = None,
        prerequisite_actions: List[str] = None,
        navigation_sequence: List[Dict[str, Any]] = None,
        validation_element: Dict[str, Any] = None,
        return_home_after: bool = False,
        max_navigation_attempts: int = 3,
        navigation_timeout: int = 10
    ) -> ActionDefinition:
        """
        Create a new action

        Args:
            device_id: Target device ID
            action: Action configuration
            tags: Optional tags for organization
            source_app: App package name where action was created
            target_app: Package to launch before executing (optional navigation)
            prerequisite_actions: Action IDs to execute first (optional navigation)
            navigation_sequence: Navigation steps to reach target screen (optional)
            validation_element: Element to verify correct screen (optional)
            return_home_after: Return to home after execution
            max_navigation_attempts: Max navigation retry attempts
            navigation_timeout: Timeout for screen validation

        Returns:
            Created ActionDefinition

        Raises:
            ActionValidationError: If validation fails
        """
        with ErrorContext("creating action", ActionValidationError):
            # Generate unique ID
            action_id = str(uuid.uuid4())

            # Create action definition with navigation config
            action_def = ActionDefinition(
                id=action_id,
                action=action,
                tags=tags or [],
                source_app=source_app,
                # Navigation fields
                target_app=target_app,
                prerequisite_actions=prerequisite_actions or [],
                navigation_sequence=navigation_sequence,
                validation_element=validation_element,
                return_home_after=return_home_after,
                max_navigation_attempts=max_navigation_attempts,
                navigation_timeout=navigation_timeout,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )

            # Load existing actions
            actions = self._load_actions(device_id)

            # Add new action
            actions.append(action_def)

            # Save
            self._save_actions(device_id, actions)

            logger.info(f"Created action {action_id} for device {device_id}: {action.action_type}")
            return action_def

    def get_action(self, device_id: str, action_id: str) -> ActionDefinition:
        """
        Get a specific action

        Args:
            device_id: Device ID
            action_id: Action ID

        Returns:
            ActionDefinition

        Raises:
            ActionNotFoundError: If action not found
        """
        actions = self._load_actions(device_id)

        for action in actions:
            if action.id == action_id:
                return action

        raise ActionNotFoundError(action_id)

    def list_actions(self, device_id: Optional[str] = None) -> List[ActionDefinition]:
        """
        List all actions for a device (or all devices)

        Supports both network device_id (192.168.1.2:46747) and stable_device_id (c7028879b7a83aa7).
        This allows Android companion app to query using stable ID across IP/port changes.

        Args:
            device_id: Optional device ID filter (network or stable)

        Returns:
            List of ActionDefinitions
        """
        if device_id:
            # First try direct file load (for network device_id)
            actions_from_file = self._load_actions(device_id)

            # If we found actions in the direct file, return them
            if actions_from_file:
                return actions_from_file

            # Otherwise, search all action files for actions matching stable_device_id
            # This handles queries with stable device ID (e.g., from Android app)
            matching_actions = []
            for actions_file in self.data_dir.glob("actions_*.json"):
                try:
                    with open(actions_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        file_actions = [ActionDefinition(**action) for action in data]
                        # Check each action's stable_device_id
                        for action in file_actions:
                            if action.stable_device_id == device_id:
                                matching_actions.append(action)
                except Exception as e:
                    logger.error(f"Error loading {actions_file}: {e}")

            return matching_actions

        # Load from all device files (no device_id filter)
        all_actions = []
        for actions_file in self.data_dir.glob("actions_*.json"):
            try:
                with open(actions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    all_actions.extend([ActionDefinition(**action) for action in data])
            except Exception as e:
                logger.error(f"Error loading {actions_file}: {e}")

        return all_actions

    def update_action(
        self,
        device_id: str,
        action_id: str,
        action: Optional[ActionType] = None,
        enabled: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        # Navigation configuration (all optional for partial updates)
        target_app: Optional[str] = None,
        prerequisite_actions: Optional[List[str]] = None,
        navigation_sequence: Optional[List[Dict[str, Any]]] = None,
        validation_element: Optional[Dict[str, Any]] = None,
        return_home_after: Optional[bool] = None,
        max_navigation_attempts: Optional[int] = None,
        navigation_timeout: Optional[int] = None
    ) -> ActionDefinition:
        """
        Update an existing action

        Args:
            device_id: Device ID
            action_id: Action ID
            action: Optional new action configuration
            enabled: Optional enabled status
            tags: Optional new tags
            target_app: Optional package to launch before executing
            prerequisite_actions: Optional action IDs to execute first
            navigation_sequence: Optional navigation steps
            validation_element: Optional screen validation element
            return_home_after: Optional return home flag
            max_navigation_attempts: Optional max navigation retries
            navigation_timeout: Optional validation timeout

        Returns:
            Updated ActionDefinition

        Raises:
            ActionNotFoundError: If action not found
        """
        actions = self._load_actions(device_id)

        for i, existing_action in enumerate(actions):
            if existing_action.id == action_id:
                # Update basic fields
                if action is not None:
                    existing_action.action = action
                if enabled is not None:
                    existing_action.action.enabled = enabled
                if tags is not None:
                    existing_action.tags = tags

                # Update navigation fields (only if provided)
                if target_app is not None:
                    existing_action.target_app = target_app
                if prerequisite_actions is not None:
                    existing_action.prerequisite_actions = prerequisite_actions
                if navigation_sequence is not None:
                    existing_action.navigation_sequence = navigation_sequence
                if validation_element is not None:
                    existing_action.validation_element = validation_element
                if return_home_after is not None:
                    existing_action.return_home_after = return_home_after
                if max_navigation_attempts is not None:
                    existing_action.max_navigation_attempts = max_navigation_attempts
                if navigation_timeout is not None:
                    existing_action.navigation_timeout = navigation_timeout

                existing_action.updated_at = datetime.now()

                # Save
                self._save_actions(device_id, actions)

                logger.info(f"Updated action {action_id} for device {device_id}")
                return existing_action

        raise ActionNotFoundError(action_id)

    def delete_action(self, device_id: str, action_id: str):
        """
        Delete an action

        Args:
            device_id: Device ID
            action_id: Action ID

        Raises:
            ActionNotFoundError: If action not found
        """
        actions = self._load_actions(device_id)

        original_count = len(actions)
        actions = [a for a in actions if a.id != action_id]

        if len(actions) == original_count:
            raise ActionNotFoundError(action_id)

        self._save_actions(device_id, actions)
        logger.info(f"Deleted action {action_id} for device {device_id}")

    def record_execution(
        self,
        device_id: str,
        action_id: str,
        success: bool,
        result_message: str
    ):
        """
        Record action execution result

        Args:
            device_id: Device ID
            action_id: Action ID
            success: Whether execution succeeded
            result_message: Result message
        """
        try:
            actions = self._load_actions(device_id)

            for action in actions:
                if action.id == action_id:
                    action.execution_count += 1
                    action.last_executed = datetime.now()
                    action.last_result = "success" if success else f"error: {result_message}"
                    break

            self._save_actions(device_id, actions)
        except Exception as e:
            logger.error(f"Error recording execution for action {action_id}: {e}")

    def get_actions_by_tag(self, device_id: str, tag: str) -> List[ActionDefinition]:
        """Get all actions with a specific tag"""
        actions = self._load_actions(device_id)
        return [a for a in actions if tag in a.tags]

    def get_enabled_actions(self, device_id: str) -> List[ActionDefinition]:
        """Get all enabled actions for a device"""
        actions = self._load_actions(device_id)
        return [a for a in actions if a.action.enabled]

    def export_actions(self, device_id: str) -> str:
        """Export actions as JSON string"""
        actions = self._load_actions(device_id)
        return json.dumps([action.dict() for action in actions], indent=2, default=str)

    def import_actions(self, device_id: str, actions_json: str) -> int:
        """
        Import actions from JSON string

        Args:
            device_id: Target device ID
            actions_json: JSON string of actions

        Returns:
            Number of actions imported

        Raises:
            ActionValidationError: If import fails
        """
        try:
            data = json.loads(actions_json)
            imported_actions = [ActionDefinition(**action) for action in data]

            # Load existing actions
            existing_actions = self._load_actions(device_id)

            # Add imported actions (with new IDs to avoid conflicts)
            for action in imported_actions:
                action.id = str(uuid.uuid4())
                action.created_at = datetime.now()
                action.updated_at = datetime.now()
                existing_actions.append(action)

            # Save
            self._save_actions(device_id, existing_actions)

            logger.info(f"Imported {len(imported_actions)} actions for device {device_id}")
            return len(imported_actions)

        except json.JSONDecodeError as e:
            raise ActionValidationError(f"Invalid JSON: {e}")
        except Exception as e:
            raise ActionValidationError(f"Import failed: {e}")
