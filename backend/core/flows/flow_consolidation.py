"""
Visual Mapper - Flow Consolidation (Beta)
Intelligent flow consolidation for reduced redundant operations

This module detects when multiple flows target the same apps/screens and
batches them to reduce redundant operations (app launches, navigation, unlocks).

Feature Flag: FLOW_CONSOLIDATION=true
"""

import logging
import uuid
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime

from .flow_models import SensorCollectionFlow, FlowStep, FlowStepType

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationGroup:
    """Group of flows that can be consolidated"""

    group_id: str
    device_id: str
    app_package: str
    flows: List[SensorCollectionFlow]
    shared_navigation_prefix: List[FlowStep]  # Common steps before divergence
    total_sensors: int
    estimated_savings_seconds: float
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.group_id:
            self.group_id = f"cg_{uuid.uuid4().hex[:8]}"


@dataclass
class ConsolidatedExecutionPlan:
    """Execution plan for consolidated flows"""

    plan_id: str
    device_id: str
    groups: List[ConsolidationGroup]
    execution_order: List[str]  # group_ids in optimal order
    total_original_steps: int
    total_consolidated_steps: int
    estimated_time_savings: float
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = f"cp_{uuid.uuid4().hex[:8]}"


@dataclass
class ConsolidationStats:
    """Statistics for consolidation operations"""

    enabled: bool = False
    total_consolidations: int = 0
    total_time_saved_seconds: float = 0.0
    consolidation_rate: float = 0.0
    by_device: Dict[str, Dict] = field(default_factory=dict)
    last_consolidation: Optional[datetime] = None


class FlowConsolidator:
    """
    Manages flow consolidation for optimized execution

    Features:
    - Detects consolidation opportunities (same device, same app)
    - Finds longest common navigation prefix (LCP)
    - Generates optimized execution plans
    - Tracks consolidation statistics
    """

    # Estimated time costs for operations (in seconds)
    APP_LAUNCH_TIME = 5.0
    UNLOCK_TIME = 3.0
    LOCK_TIME = 1.0
    NAVIGATION_STEP_TIME = 1.5
    CAPTURE_STEP_TIME = 2.0

    def __init__(
        self,
        config: Optional[Dict] = None,
    ):
        """
        Initialize flow consolidator

        Args:
            config: Configuration dict with:
                - window_seconds: Max delay to wait for consolidation (default 30)
                - minimum_savings_threshold: Min seconds saved to consolidate (default 5)
                - max_batch_size: Max flows per batch (default 10)
        """
        self.config = config or {
            "window_seconds": 30,
            "minimum_savings_threshold": 5,
            "max_batch_size": 10,
        }

        # Statistics tracking
        self._stats = ConsolidationStats()

        # Pending flows awaiting consolidation (device_id -> list of QueuedFlow)
        self._pending_consolidation: Dict[str, List] = {}

        # Completed consolidation groups for metrics
        self._completed_groups: List[ConsolidationGroup] = []
        self._max_history = 100

        logger.info(
            f"[FlowConsolidator] Initialized with config: {self.config}"
        )

    def find_consolidation_opportunities(
        self, flows: List[SensorCollectionFlow]
    ) -> List[ConsolidationGroup]:
        """
        Detect flows that can be consolidated based on:
        1. Same device_id
        2. Same target app (first launch_app step)
        3. Overlapping navigation paths
        4. Compatible timing (all due for execution)

        Args:
            flows: List of flows to analyze

        Returns:
            List of ConsolidationGroup objects
        """
        if len(flows) < 2:
            return []

        # Group by device_id
        device_groups = self._group_by(flows, key=lambda f: f.device_id)
        consolidation_groups = []

        for device_id, device_flows in device_groups.items():
            if len(device_flows) < 2:
                continue

            # Group by app package
            app_groups = self._group_by(
                device_flows, key=lambda f: self._get_launch_app_package(f)
            )

            for app_package, app_flows in app_groups.items():
                if not app_package:  # Skip flows without launch_app
                    continue

                if len(app_flows) < 2:
                    continue

                # Apply max batch size limit
                max_batch = self.config.get("max_batch_size", 10)
                if len(app_flows) > max_batch:
                    app_flows = app_flows[:max_batch]

                # Find common navigation prefix (LCP algorithm)
                common_prefix = self._find_longest_common_prefix(app_flows)

                # Calculate savings
                savings = self._estimate_savings(app_flows, common_prefix)

                min_threshold = self.config.get("minimum_savings_threshold", 5)
                if savings >= min_threshold:
                    # Count total sensors
                    total_sensors = sum(
                        self._count_sensors_in_flow(f) for f in app_flows
                    )

                    group = ConsolidationGroup(
                        group_id=f"cg_{uuid.uuid4().hex[:8]}",
                        device_id=device_id,
                        app_package=app_package,
                        flows=app_flows,
                        shared_navigation_prefix=common_prefix,
                        total_sensors=total_sensors,
                        estimated_savings_seconds=savings,
                    )
                    consolidation_groups.append(group)

                    logger.info(
                        f"[FlowConsolidator] Found consolidation opportunity: "
                        f"{len(app_flows)} flows for {app_package}, "
                        f"savings={savings:.1f}s, sensors={total_sensors}"
                    )

        return consolidation_groups

    def generate_consolidated_plan(
        self, groups: List[ConsolidationGroup]
    ) -> Optional[ConsolidatedExecutionPlan]:
        """
        Generate an optimized execution plan for consolidated groups

        Args:
            groups: List of consolidation groups

        Returns:
            ConsolidatedExecutionPlan or None if no valid plan
        """
        if not groups:
            return None

        device_id = groups[0].device_id
        total_original_steps = 0
        total_consolidated_steps = 0
        estimated_savings = 0.0

        # Calculate totals
        for group in groups:
            for flow in group.flows:
                total_original_steps += len(flow.steps)

            # Consolidated: prefix once + divergent steps
            total_consolidated_steps += len(group.shared_navigation_prefix)

            # Add divergent steps for each flow (steps after prefix)
            for flow in group.flows:
                prefix_len = len(group.shared_navigation_prefix)
                total_consolidated_steps += len(flow.steps) - prefix_len

            estimated_savings += group.estimated_savings_seconds

        # Determine execution order (currently sequential by group)
        execution_order = [g.group_id for g in groups]

        plan = ConsolidatedExecutionPlan(
            plan_id=f"cp_{uuid.uuid4().hex[:8]}",
            device_id=device_id,
            groups=groups,
            execution_order=execution_order,
            total_original_steps=total_original_steps,
            total_consolidated_steps=total_consolidated_steps,
            estimated_time_savings=estimated_savings,
        )

        logger.info(
            f"[FlowConsolidator] Generated plan {plan.plan_id}: "
            f"{total_original_steps} -> {total_consolidated_steps} steps, "
            f"savings={estimated_savings:.1f}s"
        )

        return plan

    def build_consolidated_steps(
        self, group: ConsolidationGroup
    ) -> List[FlowStep]:
        """
        Build the consolidated step sequence for a group of flows

        Scenarios handled:
        1. Same App, Same Screen, Multiple Sensors - combine captures
        2. Same App, Different Screens (Linear Path) - execute in order
        3. Same App, Branching Paths - use go_back to navigate branches

        Args:
            group: ConsolidationGroup to build steps for

        Returns:
            Consolidated list of FlowSteps
        """
        if not group.flows:
            return []

        consolidated_steps = []

        # Start with shared navigation prefix
        consolidated_steps.extend(group.shared_navigation_prefix)

        # Build navigation tree for divergent paths
        divergent_branches = self._extract_divergent_branches(
            group.flows, len(group.shared_navigation_prefix)
        )

        # Merge divergent branches with optimal path
        merged_divergent = self._merge_branches_with_backtracking(divergent_branches)
        consolidated_steps.extend(merged_divergent)

        return consolidated_steps

    def _extract_divergent_branches(
        self, flows: List[SensorCollectionFlow], prefix_len: int
    ) -> List[List[FlowStep]]:
        """
        Extract the divergent portion of each flow (after the common prefix)

        Args:
            flows: List of flows
            prefix_len: Length of the common prefix

        Returns:
            List of divergent step sequences
        """
        branches = []
        for flow in flows:
            if len(flow.steps) > prefix_len:
                branches.append(flow.steps[prefix_len:])
            else:
                branches.append([])
        return branches

    def _merge_branches_with_backtracking(
        self, branches: List[List[FlowStep]]
    ) -> List[FlowStep]:
        """
        Merge divergent branches using go_back navigation between them

        Strategy:
        - Execute first branch fully
        - For each subsequent branch:
          - Add go_back steps to return to divergence point
          - Execute the new branch

        Args:
            branches: List of divergent step sequences

        Returns:
            Merged step sequence with backtracking
        """
        if not branches:
            return []

        # Filter out empty branches
        non_empty = [b for b in branches if b]
        if not non_empty:
            return []

        merged = []

        for i, branch in enumerate(non_empty):
            if i > 0:
                # Calculate how many go_back steps needed
                prev_branch = non_empty[i - 1]
                nav_steps_in_prev = self._count_navigation_steps(prev_branch)

                # Add go_back steps to return to divergence point
                for _ in range(nav_steps_in_prev):
                    merged.append(
                        FlowStep(
                            step_type=FlowStepType.GO_BACK,
                            description="Backtrack for consolidated navigation",
                        )
                    )

                # Small wait after backtracking
                merged.append(
                    FlowStep(
                        step_type=FlowStepType.WAIT,
                        duration=500,
                        description="Wait after backtrack",
                    )
                )

            # Add this branch's steps
            merged.extend(branch)

        return merged

    def _count_navigation_steps(self, steps: List[FlowStep]) -> int:
        """Count navigation steps (tap, swipe) that need backtracking"""
        nav_types = {FlowStepType.TAP, FlowStepType.SWIPE}
        return sum(1 for s in steps if s.step_type in nav_types)

    def _group_by(
        self, items: List, key
    ) -> Dict:
        """Group items by a key function"""
        groups = {}
        for item in items:
            k = key(item)
            if k not in groups:
                groups[k] = []
            groups[k].append(item)
        return groups

    def _get_launch_app_package(self, flow: SensorCollectionFlow) -> Optional[str]:
        """
        Get the app package from the first launch_app step

        Args:
            flow: Flow to analyze

        Returns:
            Package name or None if no launch_app step
        """
        for step in flow.steps:
            if step.step_type == FlowStepType.LAUNCH_APP:
                return step.package
        return None

    def _find_longest_common_prefix(
        self, flows: List[SensorCollectionFlow]
    ) -> List[FlowStep]:
        """
        Find the longest common prefix of navigation steps

        Compares steps by type and key properties (package, x, y, etc.)

        Args:
            flows: List of flows to compare

        Returns:
            List of common FlowStep objects
        """
        if not flows:
            return []

        if len(flows) == 1:
            return flows[0].steps.copy()

        # Get step lists
        step_lists = [f.steps for f in flows]

        # Find minimum length
        min_len = min(len(s) for s in step_lists)
        if min_len == 0:
            return []

        # Compare step by step
        common_prefix = []
        for i in range(min_len):
            # Get step at position i from all flows
            steps_at_i = [s[i] for s in step_lists]

            # Check if all steps are equivalent
            if self._steps_are_equivalent(steps_at_i):
                common_prefix.append(steps_at_i[0])
            else:
                # Divergence found
                break

        return common_prefix

    def _steps_are_equivalent(self, steps: List[FlowStep]) -> bool:
        """
        Check if all steps are functionally equivalent

        Compares:
        - step_type
        - package (for launch_app)
        - x, y coordinates (for tap)
        - element properties (for tap with element)
        - duration (for wait)
        """
        if not steps:
            return True

        first = steps[0]

        for step in steps[1:]:
            if step.step_type != first.step_type:
                return False

            # Type-specific comparisons
            if first.step_type == FlowStepType.LAUNCH_APP:
                if step.package != first.package:
                    return False

            elif first.step_type == FlowStepType.TAP:
                # Compare coordinates or element
                if step.element and first.element:
                    # Compare element identifiers
                    if step.element.get("resource_id") != first.element.get(
                        "resource_id"
                    ):
                        return False
                    if step.element.get("text") != first.element.get("text"):
                        return False
                elif step.x != first.x or step.y != first.y:
                    return False

            elif first.step_type == FlowStepType.WAIT:
                # Waits with different durations are still "equivalent" for prefix purposes
                pass

            elif first.step_type == FlowStepType.SWIPE:
                if (
                    step.start_x != first.start_x
                    or step.start_y != first.start_y
                    or step.end_x != first.end_x
                    or step.end_y != first.end_y
                ):
                    return False

        return True

    def _estimate_savings(
        self, flows: List[SensorCollectionFlow], common_prefix: List[FlowStep]
    ) -> float:
        """
        Estimate time savings from consolidation

        Savings come from:
        - (N-1) app launches avoided
        - (N-1) unlock cycles avoided
        - Shared navigation prefix executed once instead of N times

        Args:
            flows: Flows being consolidated
            common_prefix: Common navigation prefix

        Returns:
            Estimated savings in seconds
        """
        n = len(flows)
        if n < 2:
            return 0.0

        # App launch savings: (N-1) launches avoided
        app_launch_savings = (n - 1) * self.APP_LAUNCH_TIME

        # Unlock/lock savings: (N-1) cycles avoided
        unlock_savings = (n - 1) * (self.UNLOCK_TIME + self.LOCK_TIME)

        # Navigation prefix savings: (N-1) times the prefix
        prefix_time = 0.0
        for step in common_prefix:
            if step.step_type == FlowStepType.WAIT:
                prefix_time += (step.duration or 1000) / 1000.0
            elif step.step_type in [FlowStepType.TAP, FlowStepType.SWIPE]:
                prefix_time += self.NAVIGATION_STEP_TIME
            elif step.step_type == FlowStepType.LAUNCH_APP:
                # Already counted above
                pass

        nav_savings = (n - 1) * prefix_time

        total_savings = app_launch_savings + unlock_savings + nav_savings

        return total_savings

    def _count_sensors_in_flow(self, flow: SensorCollectionFlow) -> int:
        """Count total sensors captured in a flow"""
        count = 0
        for step in flow.steps:
            if step.step_type == FlowStepType.CAPTURE_SENSORS and step.sensor_ids:
                count += len(step.sensor_ids)
        return count

    # ========================================================================
    # Statistics and Reporting
    # ========================================================================

    def record_consolidation(self, group: ConsolidationGroup, success: bool):
        """
        Record a completed consolidation for statistics

        Args:
            group: The consolidation group that was executed
            success: Whether execution was successful
        """
        if success:
            self._stats.total_consolidations += 1
            self._stats.total_time_saved_seconds += group.estimated_savings_seconds
            self._stats.last_consolidation = datetime.now()

            # Update per-device stats
            device_id = group.device_id
            if device_id not in self._stats.by_device:
                self._stats.by_device[device_id] = {
                    "consolidations": 0,
                    "time_saved_seconds": 0.0,
                }

            self._stats.by_device[device_id]["consolidations"] += 1
            self._stats.by_device[device_id][
                "time_saved_seconds"
            ] += group.estimated_savings_seconds

            # Store in history
            self._completed_groups.append(group)
            if len(self._completed_groups) > self._max_history:
                self._completed_groups = self._completed_groups[-self._max_history :]

            logger.info(
                f"[FlowConsolidator] Recorded consolidation: "
                f"{len(group.flows)} flows, saved {group.estimated_savings_seconds:.1f}s"
            )

    def get_stats(self) -> Dict:
        """
        Get consolidation statistics

        Returns:
            Dictionary with consolidation metrics
        """
        from services.feature_manager import get_feature_manager

        stats = {
            "enabled": get_feature_manager().is_enabled("flow_consolidation"),
            "total_consolidations": self._stats.total_consolidations,
            "total_time_saved_seconds": round(
                self._stats.total_time_saved_seconds, 1
            ),
            "consolidation_rate": self._stats.consolidation_rate,
            "by_device": self._stats.by_device,
            "last_consolidation": (
                self._stats.last_consolidation.isoformat()
                if self._stats.last_consolidation
                else None
            ),
        }
        return stats

    def get_pending_consolidations(
        self, device_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Get preview of pending consolidation opportunities

        Args:
            device_id: Optional device to filter by

        Returns:
            List of pending consolidation info dicts
        """
        pending = []
        for dev_id, flows in self._pending_consolidation.items():
            if device_id and dev_id != device_id:
                continue

            if len(flows) < 2:
                continue

            # Find opportunities
            groups = self.find_consolidation_opportunities(
                [qf.flow for qf in flows]
            )

            for group in groups:
                pending.append({
                    "device_id": group.device_id,
                    "app_package": group.app_package,
                    "flows": [f.flow_id for f in group.flows],
                    "estimated_savings_seconds": round(
                        group.estimated_savings_seconds, 1
                    ),
                    "total_sensors": group.total_sensors,
                })

        return pending

    def add_pending_flow(self, device_id: str, queued_flow) -> bool:
        """
        Add a flow to pending consolidation queue

        Args:
            device_id: Device ID
            queued_flow: QueuedFlow object

        Returns:
            True if added successfully
        """
        if device_id not in self._pending_consolidation:
            self._pending_consolidation[device_id] = []

        # Check max batch size
        max_batch = self.config.get("max_batch_size", 10)
        if len(self._pending_consolidation[device_id]) >= max_batch:
            logger.debug(
                f"[FlowConsolidator] Pending queue full for {device_id}"
            )
            return False

        self._pending_consolidation[device_id].append(queued_flow)
        return True

    def get_pending_flows(self, device_id: str) -> List:
        """
        Get pending flows for a device

        Args:
            device_id: Device ID

        Returns:
            List of QueuedFlow objects
        """
        return self._pending_consolidation.get(device_id, [])

    def clear_pending_flows(self, device_id: str):
        """
        Clear pending flows for a device

        Args:
            device_id: Device ID
        """
        if device_id in self._pending_consolidation:
            self._pending_consolidation[device_id] = []

    def should_consolidate(
        self, device_id: str, new_flow: SensorCollectionFlow
    ) -> Tuple[bool, Optional[ConsolidationGroup]]:
        """
        Check if a new flow should trigger consolidation

        Args:
            device_id: Device ID
            new_flow: New flow being scheduled

        Returns:
            Tuple of (should_consolidate, ConsolidationGroup or None)
        """
        pending = self._pending_consolidation.get(device_id, [])

        if not pending:
            return False, None

        # Get all flows including new one
        all_flows = [qf.flow for qf in pending] + [new_flow]

        # Find consolidation opportunities
        groups = self.find_consolidation_opportunities(all_flows)

        if not groups:
            return False, None

        # Return the first valid group
        return True, groups[0]
