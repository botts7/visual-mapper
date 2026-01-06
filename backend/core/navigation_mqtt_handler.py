"""
Navigation MQTT Handler

Handles navigation learning messages from Android companion app via MQTT.
Receives screen transitions and updates navigation graphs.
"""

import json
import logging
from typing import Callable, Optional, Dict, Any

from ml_components.navigation_models import LearnTransitionRequest, TransitionAction
from core.navigation_manager import NavigationManager

logger = logging.getLogger(__name__)


class NavigationMqttHandler:
    """
    Handles MQTT messages for navigation learning from Android companion apps.

    Subscribes to: visual_mapper/{device_id}/navigation/learn
    Receives transition data and calls NavigationManager.learn_from_transition()
    """

    def __init__(self, navigation_manager: NavigationManager):
        """
        Initialize the navigation MQTT handler.

        Args:
            navigation_manager: NavigationManager instance for learning transitions
        """
        self.navigation_manager = navigation_manager
        self._stats = {
            "transitions_received": 0,
            "transitions_learned": 0,
            "transitions_failed": 0
        }
        logger.info("[NavigationMqttHandler] Initialized")

    async def handle_learn_transition(self, device_id: str, payload: str) -> bool:
        """
        Handle a navigation learning message from the companion app.

        Args:
            device_id: The device ID (sanitized from MQTT topic)
            payload: JSON payload containing transition data

        Returns:
            True if transition was learned successfully, False otherwise
        """
        self._stats["transitions_received"] += 1

        try:
            data = json.loads(payload)
            logger.debug(f"[NavigationMqttHandler] Received transition from {device_id}: "
                        f"{data.get('before_activity')} -> {data.get('after_activity')}")

            # Parse action from payload
            action_data = data.get("action", {})
            action = TransitionAction(
                action_type=action_data.get("action_type", "tap"),
                x=action_data.get("x"),
                y=action_data.get("y"),
                element_resource_id=action_data.get("element_resource_id"),
                element_text=action_data.get("element_text"),
                element_class=action_data.get("element_class"),
                element_content_desc=action_data.get("element_content_desc"),
                start_x=action_data.get("start_x"),
                start_y=action_data.get("start_y"),
                end_x=action_data.get("end_x"),
                end_y=action_data.get("end_y"),
                swipe_direction=action_data.get("swipe_direction"),
                keycode=action_data.get("keycode"),
                text=action_data.get("text"),
                description=action_data.get("description")
            )

            # Build LearnTransitionRequest
            request = LearnTransitionRequest(
                before_activity=data.get("before_activity", ""),
                before_package=data.get("before_package", ""),
                before_ui_elements=data.get("before_ui_elements", []),
                after_activity=data.get("after_activity", ""),
                after_package=data.get("after_package", data.get("before_package", "")),
                after_ui_elements=data.get("after_ui_elements", []),
                action=action,
                device_id=device_id,
                transition_time_ms=data.get("transition_time_ms")
            )

            # Learn the transition
            success = self.navigation_manager.learn_from_transition(request)

            if success:
                self._stats["transitions_learned"] += 1
                logger.info(f"[NavigationMqttHandler] Learned transition: "
                           f"{request.before_activity} -> {request.after_activity} "
                           f"via {action.action_type}")
            else:
                self._stats["transitions_failed"] += 1
                logger.warning(f"[NavigationMqttHandler] Failed to learn transition: "
                              f"{request.before_activity} -> {request.after_activity}")

            return success

        except json.JSONDecodeError as e:
            self._stats["transitions_failed"] += 1
            logger.error(f"[NavigationMqttHandler] Invalid JSON payload: {e}")
            return False
        except Exception as e:
            self._stats["transitions_failed"] += 1
            logger.error(f"[NavigationMqttHandler] Error processing transition: {e}")
            return False

    def get_stats(self) -> Dict[str, int]:
        """
        Get statistics about navigation learning.

        Returns:
            Dict with transition counts
        """
        return self._stats.copy()

    def reset_stats(self):
        """Reset statistics counters."""
        self._stats = {
            "transitions_received": 0,
            "transitions_learned": 0,
            "transitions_failed": 0
        }
        logger.info("[NavigationMqttHandler] Stats reset")
