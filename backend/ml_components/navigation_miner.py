"""
Visual Mapper - Navigation Miner
Extracts navigation patterns from existing saved flows

Analyzes flow steps to discover:
- Screen transitions (activity changes between steps)
- Navigation actions (taps, swipes that cause transitions)
- Home screens (first screen after launch_app)
"""

import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

from navigation_models import TransitionAction
from navigation_manager import NavigationManager
from core.flows import FlowManager
from core.flows import SensorCollectionFlow, FlowStep

logger = logging.getLogger(__name__)


class NavigationMiner:
    """
    Mines navigation patterns from existing flows

    Analyzes saved flows to build navigation graphs without requiring
    new recordings. Useful for bootstrapping navigation knowledge.
    """

    def __init__(
        self, navigation_manager: NavigationManager, flow_manager: FlowManager = None
    ):
        """
        Initialize NavigationMiner

        Args:
            navigation_manager: NavigationManager to store discovered patterns
            flow_manager: FlowManager to load flows (optional, uses default if None)
        """
        self.nav_manager = navigation_manager
        self.flow_manager = flow_manager or FlowManager()

    def mine_package(
        self, package: str, device_id: str = None, limit: int = None
    ) -> Dict[str, Any]:
        """
        Mine all flows for a package and build navigation graph

        Args:
            package: App package name to mine
            device_id: Optional device ID filter
            limit: Max flows to process

        Returns:
            Mining results summary
        """
        logger.info(f"[NavigationMiner] Mining flows for package: {package}")

        # Get all flows
        all_flows = self._get_flows_for_package(package, device_id)

        if limit:
            all_flows = all_flows[:limit]

        if not all_flows:
            logger.warning(f"[NavigationMiner] No flows found for {package}")
            return {
                "package": package,
                "flows_processed": 0,
                "screens_discovered": 0,
                "transitions_discovered": 0,
            }

        screens_before = (
            len(self.nav_manager.get_graph(package).screens)
            if self.nav_manager.get_graph(package)
            else 0
        )
        transitions_before = (
            len(self.nav_manager.get_graph(package).transitions)
            if self.nav_manager.get_graph(package)
            else 0
        )

        for flow in all_flows:
            self._mine_flow(flow)

        graph = self.nav_manager.get_graph(package)
        screens_after = len(graph.screens) if graph else 0
        transitions_after = len(graph.transitions) if graph else 0

        result = {
            "package": package,
            "flows_processed": len(all_flows),
            "screens_discovered": screens_after - screens_before,
            "transitions_discovered": transitions_after - transitions_before,
            "total_screens": screens_after,
            "total_transitions": transitions_after,
        }

        logger.info(f"[NavigationMiner] Mining complete: {result}")
        return result

    def _get_flows_for_package(
        self, package: str, device_id: str = None
    ) -> List[SensorCollectionFlow]:
        """Get all flows that use the specified package"""
        flows = []

        # Get all device IDs
        try:
            all_device_ids = self.flow_manager.get_all_device_ids()
        except Exception as e:
            logger.error(f"[NavigationMiner] Failed to get device IDs: {e}")
            return []

        for did in all_device_ids:
            if device_id and did != device_id:
                continue

            device_flows = self.flow_manager.get_flows_for_device(did)
            for flow in device_flows:
                # Check if any step uses this package
                if self._flow_uses_package(flow, package):
                    flows.append(flow)

        return flows

    def _flow_uses_package(self, flow: SensorCollectionFlow, package: str) -> bool:
        """Check if a flow uses the specified package"""
        for step in flow.steps:
            # Check launch_app step
            if step.step_type == "launch_app" and step.package == package:
                return True
            # Check screen_package field
            if step.screen_package == package:
                return True
        return False

    def _mine_flow(self, flow: SensorCollectionFlow):
        """
        Extract navigation patterns from a single flow

        Analyzes consecutive steps to find screen transitions.
        """
        logger.debug(f"[NavigationMiner] Mining flow: {flow.name} ({flow.flow_id})")

        prev_step = None
        prev_screen_id = None
        current_package = None

        for i, step in enumerate(flow.steps):
            # Track package from launch_app
            if step.step_type == "launch_app" and step.package:
                current_package = step.package

                # After launch, next step should be home screen
                if i + 1 < len(flow.steps):
                    next_step = flow.steps[i + 1]
                    if (
                        next_step.screen_activity
                        and next_step.screen_package == current_package
                    ):
                        # Mark as home screen
                        self.nav_manager.set_home_screen(
                            package=current_package,
                            activity=next_step.screen_activity,
                            ui_elements=[],  # No UI elements from mined flows
                        )
                continue

            # Skip steps without screen info
            if not step.screen_activity or not step.screen_package:
                prev_step = step
                continue

            # Add this screen
            screen = self.nav_manager.add_screen(
                package=step.screen_package,
                activity=step.screen_activity,
                ui_elements=[],
                learned_from="mining",
            )
            current_screen_id = screen.screen_id

            # Check for transition from previous step
            if prev_step and prev_screen_id and prev_screen_id != current_screen_id:
                # Found a transition!
                action = self._extract_action_from_step(prev_step)
                if action:
                    self.nav_manager.add_transition(
                        package=step.screen_package,
                        source_screen_id=prev_screen_id,
                        target_screen_id=current_screen_id,
                        action=action,
                        learned_from="mining",
                    )

            prev_step = step
            prev_screen_id = current_screen_id

    def _extract_action_from_step(self, step: FlowStep) -> Optional[TransitionAction]:
        """
        Extract TransitionAction from a FlowStep

        Converts flow step data into a TransitionAction for storage.
        """
        if step.step_type == "tap":
            return TransitionAction(
                action_type="tap", x=step.x, y=step.y, description=step.description
            )

        elif step.step_type == "swipe":
            direction = self._infer_swipe_direction(step)
            return TransitionAction(
                action_type="swipe",
                start_x=step.start_x,
                start_y=step.start_y,
                end_x=step.end_x,
                end_y=step.end_y,
                swipe_direction=direction,
                description=step.description,
            )

        elif step.step_type == "go_back":
            return TransitionAction(
                action_type="go_back",
                keycode="KEYCODE_BACK",
                description="Press back button",
            )

        elif step.step_type == "go_home":
            return TransitionAction(
                action_type="go_home",
                keycode="KEYCODE_HOME",
                description="Press home button",
            )

        elif step.step_type == "keyevent":
            return TransitionAction(
                action_type="keyevent",
                keycode=step.keycode,
                description=step.description,
            )

        # No action for wait, capture_sensors, etc.
        return None

    def _infer_swipe_direction(self, step: FlowStep) -> Optional[str]:
        """Infer swipe direction from coordinates"""
        if not all([step.start_x, step.start_y, step.end_x, step.end_y]):
            return None

        dx = step.end_x - step.start_x
        dy = step.end_y - step.start_y

        # Determine primary direction
        if abs(dx) > abs(dy):
            return "right" if dx > 0 else "left"
        else:
            return "down" if dy > 0 else "up"

    def mine_all_packages(self) -> Dict[str, Any]:
        """
        Mine all packages across all flows

        Discovers and mines every package found in saved flows.
        """
        logger.info("[NavigationMiner] Mining all packages...")

        packages = set()

        # Discover all packages
        try:
            all_device_ids = self.flow_manager.get_all_device_ids()
        except Exception as e:
            logger.error(f"[NavigationMiner] Failed to get device IDs: {e}")
            return {"error": str(e)}

        for device_id in all_device_ids:
            flows = self.flow_manager.get_flows_for_device(device_id)
            for flow in flows:
                for step in flow.steps:
                    if step.step_type == "launch_app" and step.package:
                        packages.add(step.package)
                    if step.screen_package:
                        packages.add(step.screen_package)

        # Mine each package
        results = {}
        for package in packages:
            results[package] = self.mine_package(package)

        return {"packages_mined": len(packages), "results": results}
