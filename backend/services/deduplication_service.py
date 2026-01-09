"""
Deduplication Service - Unified duplicate detection for sensors, actions, and flows.

Provides:
- Similarity detection for new entities
- Merge recommendations
- Runtime session caching to avoid redundant operations
- Non-breaking: warnings and suggestions only, never blocks user actions
"""

import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


class EntityType(str, Enum):
    SENSOR = "sensor"
    ACTION = "action"
    FLOW = "flow"
    UI_ELEMENT = "ui_element"


class MatchReason(str, Enum):
    SAME_RESOURCE_ID = "same_resource_id"
    SAME_BOUNDS = "same_bounds"
    SAME_SCREEN = "same_screen"
    SAME_EXTRACTION = "same_extraction"
    SAME_ACTION_TYPE = "same_action_type"
    SAME_TARGET = "same_target"
    SAME_PARAMS = "same_params"
    OVERLAPPING_SENSORS = "overlapping_sensors"
    OVERLAPPING_SCREENS = "overlapping_screens"
    SIMILAR_NAME = "similar_name"


class Recommendation(str, Enum):
    USE_EXISTING = "use_existing"  # High similarity - recommend using existing
    MERGE = "merge"                 # Can be merged into one
    KEEP_BOTH = "keep_both"         # Different enough to keep both
    REVIEW = "review"               # User should review


@dataclass
class SimilarMatch:
    """Represents a potential duplicate match."""
    entity_id: str
    entity_type: EntityType
    entity_name: str
    similarity_score: float  # 0.0 - 1.0
    match_reasons: List[MatchReason]
    recommendation: Recommendation
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type.value,
            "entity_name": self.entity_name,
            "similarity_score": self.similarity_score,
            "match_reasons": [r.value for r in self.match_reasons],
            "recommendation": self.recommendation.value,
            "details": self.details
        }


@dataclass
class MergeResult:
    """Result of merging duplicate entities."""
    success: bool
    kept_id: str
    merged_ids: List[str]
    updated_references: int  # How many flows/sensors were updated
    message: str


class ExecutionSession:
    """
    Tracks what has been captured/executed in current cycle.
    Prevents redundant operations within a single execution run.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or datetime.now().isoformat()
        self.captured_sensors: Dict[str, Any] = {}  # sensor_id -> value
        self.executed_actions: Set[str] = set()     # action_ids
        self.visited_screens: Set[str] = set()      # activity names
        self.started_at = datetime.now()

    def get_cached_sensor(self, sensor_id: str) -> Tuple[bool, Any]:
        """Check if sensor was already captured this session."""
        if sensor_id in self.captured_sensors:
            return True, self.captured_sensors[sensor_id]
        return False, None

    def cache_sensor(self, sensor_id: str, value: Any):
        """Cache a captured sensor value."""
        self.captured_sensors[sensor_id] = value

    def was_action_executed(self, action_id: str) -> bool:
        """Check if action was already executed this session."""
        return action_id in self.executed_actions

    def mark_action_executed(self, action_id: str):
        """Mark action as executed."""
        self.executed_actions.add(action_id)

    def was_screen_visited(self, activity: str) -> bool:
        """Check if screen was already visited."""
        return activity in self.visited_screens

    def mark_screen_visited(self, activity: str):
        """Mark screen as visited."""
        self.visited_screens.add(activity)

    def get_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        return {
            "session_id": self.session_id,
            "sensors_cached": len(self.captured_sensors),
            "actions_executed": len(self.executed_actions),
            "screens_visited": len(self.visited_screens),
            "duration_ms": int((datetime.now() - self.started_at).total_seconds() * 1000)
        }


class DeduplicationService:
    """
    Central service for detecting and managing duplicates.

    Design principles:
    - Non-breaking: Never blocks user actions, only warns/suggests
    - Configurable thresholds
    - Consistent patterns across entity types
    """

    # Similarity thresholds
    HIGH_SIMILARITY = 0.85   # Recommend using existing
    MEDIUM_SIMILARITY = 0.60 # Suggest review
    LOW_SIMILARITY = 0.40    # Likely different, keep both

    # Bounds tolerance in pixels
    BOUNDS_TOLERANCE = 15

    def __init__(self, sensor_manager=None, action_manager=None, flow_manager=None):
        self.sensor_manager = sensor_manager
        self.action_manager = action_manager
        self.flow_manager = flow_manager

        # Active execution sessions (for runtime caching)
        self._sessions: Dict[str, ExecutionSession] = {}

        logger.info("[DeduplicationService] Initialized")

    # =========================================================================
    # SENSOR DEDUPLICATION
    # =========================================================================

    def find_matching_sensor(
        self,
        device_id: str,
        new_sensor_data: Dict[str, Any],
        threshold: float = 0.90
    ) -> Optional[Any]:
        """
        Find an existing sensor that matches the new sensor data.
        Returns the matching sensor if confidence >= threshold, else None.

        This is used for auto-reuse: when creating a sensor, if a high-confidence
        match exists, we return it instead of creating a duplicate.

        Args:
            device_id: Device identifier
            new_sensor_data: New sensor data being created
            threshold: Minimum similarity score for auto-match (default: 0.90)

        Returns:
            Matching SensorDefinition if found, else None
        """
        logger.info(f"[Dedup] find_matching_sensor called for device: {device_id}")

        if not self.sensor_manager:
            logger.warning("[Dedup] No sensor_manager available, cannot check for matches")
            return None

        try:
            existing_sensors = self.sensor_manager.get_all_sensors(device_id)
            logger.info(f"[Dedup] Found {len(existing_sensors)} existing sensors for device {device_id}")

            if not existing_sensors:
                logger.info("[Dedup] No existing sensors to compare against")
                return None

            # Log new sensor key fields for debugging
            new_rid = new_sensor_data.get('source', {}).get('element_resource_id', '') or new_sensor_data.get('element_resource_id', '')
            new_screen = new_sensor_data.get('source', {}).get('screen_activity', '') or new_sensor_data.get('screen_activity', '')
            logger.info(f"[Dedup] New sensor: resource_id={new_rid}, screen={new_screen}")

            best_match = None
            best_score = 0.0
            best_reasons = []
            highest_score_found = 0.0  # Track highest score even if below threshold

            for existing_obj in existing_sensors:
                existing = existing_obj.model_dump() if hasattr(existing_obj, 'model_dump') else existing_obj
                score, reasons = self._calculate_sensor_similarity(new_sensor_data, existing)

                existing_name = existing.get('friendly_name', 'Unknown')
                existing_rid = existing.get('source', {}).get('element_resource_id', '') if existing.get('source') else ''
                logger.info(f"[Dedup] Compared with '{existing_name}' (rid={existing_rid}): score={score:.2f}, reasons={[r.value for r in reasons]}")

                # Track highest score found regardless of threshold
                if score > highest_score_found:
                    highest_score_found = score

                if score >= threshold and score > best_score:
                    best_score = score
                    best_match = existing_obj
                    best_reasons = reasons

            if best_match:
                sensor_name = best_match.friendly_name if hasattr(best_match, 'friendly_name') else 'Unknown'
                logger.info(f"[Dedup] Auto-match found: {sensor_name} (score: {best_score:.2f}, reasons: {[r.value for r in best_reasons]})")
                return best_match

            logger.info(f"[Dedup] No match found above threshold {threshold} (highest score: {highest_score_found:.2f})")
            return None

        except Exception as e:
            logger.error(f"[Dedup] Error finding matching sensor: {e}", exc_info=True)
            return None

    def find_similar_sensors(
        self,
        device_id: str,
        new_sensor: Dict[str, Any],
        threshold: Optional[float] = None
    ) -> List[SimilarMatch]:
        """
        Find sensors similar to the one being created.

        Args:
            device_id: Device identifier
            new_sensor: New sensor data being created
            threshold: Minimum similarity score (default: LOW_SIMILARITY)

        Returns:
            List of similar sensors, sorted by similarity (highest first)
        """
        threshold = threshold or self.LOW_SIMILARITY
        matches = []

        if not self.sensor_manager:
            return matches

        try:
            existing_sensors = self.sensor_manager.get_all_sensors(device_id)

            for existing_obj in existing_sensors:
                # Convert SensorDefinition to dict for comparison
                existing = existing_obj.model_dump() if hasattr(existing_obj, 'model_dump') else existing_obj
                score, reasons = self._calculate_sensor_similarity(new_sensor, existing)

                if score >= threshold:
                    recommendation = self._get_recommendation(score)
                    sensor_name = existing.get('name') or existing.get('friendly_name', 'Unnamed')
                    matches.append(SimilarMatch(
                        entity_id=existing.get('sensor_id', ''),
                        entity_type=EntityType.SENSOR,
                        entity_name=sensor_name,
                        similarity_score=score,
                        match_reasons=reasons,
                        recommendation=recommendation,
                        details={
                            "existing_name": sensor_name,
                            "existing_value": existing.get('current_value'),
                            "existing_screen": existing.get('screen_activity'),
                            "existing_resource_id": existing.get('resource_id'),
                            "match_reason": reasons[0].value if reasons else "similar configuration"
                        }
                    ))

            # Sort by similarity score (highest first)
            matches.sort(key=lambda m: m.similarity_score, reverse=True)

            if matches:
                logger.info(f"[Dedup] Found {len(matches)} similar sensors for new sensor")

        except Exception as e:
            logger.error(f"[Dedup] Error finding similar sensors: {e}")

        return matches

    def _calculate_sensor_similarity(
        self,
        new_sensor: Dict[str, Any],
        existing: Dict[str, Any]
    ) -> Tuple[float, List[MatchReason]]:
        """
        Calculate similarity score between two sensors.

        Weights (updated for smart auto-reuse):
        - element_resource_id: 35%
        - extraction_rule.method: 20% (different extraction = different sensor)
        - screen_activity: 20%
        - bounds: 15%
        - element_class: 5%
        - friendly_name: 5%
        """
        score = 0.0
        reasons = []

        # Helper to get nested source values
        def get_source_value(sensor: Dict, key: str, fallback_key: str = None) -> str:
            source = sensor.get('source', {}) or {}
            value = source.get(key, '') or sensor.get(key, '')
            if not value and fallback_key:
                value = source.get(fallback_key, '') or sensor.get(fallback_key, '')
            return str(value).strip() if value else ''

        # Same resource_id (35%)
        new_rid = get_source_value(new_sensor, 'element_resource_id', 'resource_id')
        existing_rid = get_source_value(existing, 'element_resource_id', 'resource_id')
        if new_rid and existing_rid and new_rid == existing_rid:
            score += 0.35
            reasons.append(MatchReason.SAME_RESOURCE_ID)

        # Same extraction method (20%) - CRITICAL: different extraction = different sensor
        new_extract = new_sensor.get('extraction_rule', {})
        existing_extract = existing.get('extraction_rule', {})
        if isinstance(new_extract, dict) and isinstance(existing_extract, dict):
            new_method = new_extract.get('method', '')
            existing_method = existing_extract.get('method', '')
            if new_method and existing_method and new_method == existing_method:
                score += 0.20
                reasons.append(MatchReason.SAME_EXTRACTION)
        else:
            # Fallback to flat extraction_method field
            new_method = new_sensor.get('extraction_method', '')
            existing_method = existing.get('extraction_method', '')
            if new_method and existing_method and new_method == existing_method:
                score += 0.20
                reasons.append(MatchReason.SAME_EXTRACTION)

        # Same screen/activity (20%)
        new_screen = get_source_value(new_sensor, 'screen_activity', 'activity')
        existing_screen = get_source_value(existing, 'screen_activity', 'activity')
        if new_screen and existing_screen:
            # Extract activity name (last part after dot)
            new_activity = new_screen.split('.')[-1] if '.' in new_screen else new_screen
            existing_activity = existing_screen.split('.')[-1] if '.' in existing_screen else existing_screen
            if new_activity == existing_activity:
                score += 0.20
                reasons.append(MatchReason.SAME_SCREEN)

        # Similar bounds (15%) - with ±20px tolerance
        new_bounds = new_sensor.get('source', {}).get('custom_bounds') or new_sensor.get('bounds', {})
        existing_bounds = existing.get('source', {}).get('custom_bounds') or existing.get('bounds', {})
        if new_bounds and existing_bounds:
            if self._bounds_overlap(new_bounds, existing_bounds, tolerance=20):
                score += 0.15
                reasons.append(MatchReason.SAME_BOUNDS)

        # Same element class (5%)
        new_class = get_source_value(new_sensor, 'element_class')
        existing_class = get_source_value(existing, 'element_class')
        if new_class and existing_class and new_class == existing_class:
            score += 0.05

        # Similar name (5%)
        new_name = (new_sensor.get('name', '') or new_sensor.get('friendly_name', '') or '').lower()
        existing_name = (existing.get('name', '') or existing.get('friendly_name', '') or '').lower()
        if new_name and existing_name:
            if new_name == existing_name or new_name in existing_name or existing_name in new_name:
                score += 0.05
                reasons.append(MatchReason.SIMILAR_NAME)

        return min(score, 1.0), reasons

    def _bounds_overlap(self, bounds1: Dict, bounds2: Dict, tolerance: int = None) -> bool:
        """Check if two bounds overlap within tolerance."""
        tolerance = tolerance or self.BOUNDS_TOLERANCE
        try:
            # Handle different bounds formats
            if 'x' in bounds1:
                x1, y1 = bounds1.get('x', 0), bounds1.get('y', 0)
                w1, h1 = bounds1.get('width', 0), bounds1.get('height', 0)
            elif 'left' in bounds1:
                x1, y1 = bounds1.get('left', 0), bounds1.get('top', 0)
                w1 = bounds1.get('right', 0) - x1
                h1 = bounds1.get('bottom', 0) - y1
            else:
                return False

            if 'x' in bounds2:
                x2, y2 = bounds2.get('x', 0), bounds2.get('y', 0)
                w2, h2 = bounds2.get('width', 0), bounds2.get('height', 0)
            elif 'left' in bounds2:
                x2, y2 = bounds2.get('left', 0), bounds2.get('top', 0)
                w2 = bounds2.get('right', 0) - x2
                h2 = bounds2.get('bottom', 0) - y2
            else:
                return False

            # Check if centers are close
            center1_x = x1 + w1 / 2
            center1_y = y1 + h1 / 2
            center2_x = x2 + w2 / 2
            center2_y = y2 + h2 / 2

            dx = abs(center1_x - center2_x)
            dy = abs(center1_y - center2_y)

            return dx <= tolerance and dy <= tolerance

        except Exception:
            return False

    # =========================================================================
    # ACTION DEDUPLICATION
    # =========================================================================

    def find_similar_actions(
        self,
        device_id: str,
        new_action: Dict[str, Any],
        threshold: Optional[float] = None
    ) -> List[SimilarMatch]:
        """
        Find actions similar to the one being created.
        """
        threshold = threshold or self.LOW_SIMILARITY
        matches = []

        if not self.action_manager:
            return matches

        try:
            existing_actions = self.action_manager.get_actions(device_id)

            for existing in existing_actions:
                score, reasons = self._calculate_action_similarity(new_action, existing)

                if score >= threshold:
                    recommendation = self._get_recommendation(score)
                    action_name = existing.get('name') or existing.get('action', {}).get('name', 'Unnamed Action')
                    action_type = existing.get('action_type') or existing.get('action', {}).get('action_type', 'unknown')
                    matches.append(SimilarMatch(
                        entity_id=existing.get('id') or existing.get('action_id', ''),
                        entity_type=EntityType.ACTION,
                        entity_name=action_name,
                        similarity_score=score,
                        match_reasons=reasons,
                        recommendation=recommendation,
                        details={
                            "existing_name": action_name,
                            "existing_type": action_type,
                            "existing_target": existing.get('target_element'),
                            "match_reason": reasons[0].value if reasons else "similar configuration"
                        }
                    ))

            matches.sort(key=lambda m: m.similarity_score, reverse=True)

        except Exception as e:
            logger.error(f"[Dedup] Error finding similar actions: {e}")

        return matches

    def _calculate_action_similarity(
        self,
        new_action: Dict[str, Any],
        existing: Dict[str, Any]
    ) -> Tuple[float, List[MatchReason]]:
        """Calculate similarity score between two actions."""
        score = 0.0
        reasons = []

        # Handle nested action structure (action may be inside 'action' key)
        existing_data = existing.get('action', existing)
        new_data = new_action.get('action', new_action)

        # Same action type (35%)
        new_type = new_data.get('action_type', '')
        existing_type = existing_data.get('action_type', '')
        if new_type and existing_type and new_type == existing_type:
            score += 0.35
            reasons.append(MatchReason.SAME_ACTION_TYPE)

            # For tap actions, check coordinates (25%)
            if new_type == 'tap':
                new_x, new_y = new_data.get('x'), new_data.get('y')
                ex_x, ex_y = existing_data.get('x'), existing_data.get('y')
                if new_x is not None and new_y is not None and ex_x is not None and ex_y is not None:
                    dx = abs(new_x - ex_x)
                    dy = abs(new_y - ex_y)
                    if dx <= self.BOUNDS_TOLERANCE and dy <= self.BOUNDS_TOLERANCE:
                        score += 0.25
                        reasons.append(MatchReason.SAME_TARGET)

            # For swipe actions, check start/end coordinates (25%)
            elif new_type == 'swipe':
                new_x1, new_y1 = new_data.get('x1'), new_data.get('y1')
                new_x2, new_y2 = new_data.get('x2'), new_data.get('y2')
                ex_x1, ex_y1 = existing_data.get('x1'), existing_data.get('y1')
                ex_x2, ex_y2 = existing_data.get('x2'), existing_data.get('y2')
                if all(v is not None for v in [new_x1, new_y1, new_x2, new_y2, ex_x1, ex_y1, ex_x2, ex_y2]):
                    d_start = abs(new_x1 - ex_x1) + abs(new_y1 - ex_y1)
                    d_end = abs(new_x2 - ex_x2) + abs(new_y2 - ex_y2)
                    if d_start <= self.BOUNDS_TOLERANCE * 2 and d_end <= self.BOUNDS_TOLERANCE * 2:
                        score += 0.25
                        reasons.append(MatchReason.SAME_TARGET)

            # For keyevent actions, check keycode (25%)
            elif new_type == 'keyevent':
                if new_data.get('keycode') == existing_data.get('keycode'):
                    score += 0.25
                    reasons.append(MatchReason.SAME_PARAMS)

            # For launch_app actions, check package (25%)
            elif new_type == 'launch_app':
                if new_data.get('package_name') == existing_data.get('package_name'):
                    score += 0.25
                    reasons.append(MatchReason.SAME_TARGET)

            # For text actions, check text content (25%)
            elif new_type == 'text':
                new_text = (new_data.get('text') or '').strip().lower()
                ex_text = (existing_data.get('text') or '').strip().lower()
                if new_text and ex_text and new_text == ex_text:
                    score += 0.25
                    reasons.append(MatchReason.SAME_PARAMS)

        # Same target element - fallback for resource_id based matching (20%)
        new_target = new_data.get('target_element', {})
        existing_target = existing_data.get('target_element', {})
        if new_target and existing_target:
            if new_target.get('resource_id') == existing_target.get('resource_id'):
                score += 0.20
                if MatchReason.SAME_TARGET not in reasons:
                    reasons.append(MatchReason.SAME_TARGET)

        # Same screen (20%)
        new_screen = new_data.get('screen_activity', '')
        existing_screen = existing_data.get('screen_activity', '')
        if new_screen and existing_screen and new_screen == existing_screen:
            score += 0.20
            reasons.append(MatchReason.SAME_SCREEN)

        # Similar name (5%)
        new_name = (new_data.get('name') or '').lower()
        ex_name = (existing_data.get('name') or '').lower()
        if new_name and ex_name and (new_name == ex_name or new_name in ex_name or ex_name in new_name):
            score += 0.05
            reasons.append(MatchReason.SIMILAR_NAME)

        return min(score, 1.0), reasons

    # =========================================================================
    # FLOW OVERLAP DETECTION
    # =========================================================================

    def find_overlapping_flows(
        self,
        device_id: str,
        new_flow: Dict[str, Any],
        threshold: Optional[float] = None
    ) -> List[SimilarMatch]:
        """
        Find flows that overlap with the one being created.
        """
        threshold = threshold or self.LOW_SIMILARITY
        matches = []

        if not self.flow_manager:
            return matches

        try:
            existing_flows = self.flow_manager.get_device_flows(device_id)

            for existing in existing_flows:
                # Skip disabled flows
                if not existing.enabled:
                    continue

                score, reasons = self._calculate_flow_overlap(new_flow, existing)

                if score >= threshold:
                    recommendation = self._get_recommendation(score)
                    matches.append(SimilarMatch(
                        entity_id=existing.flow_id,
                        entity_type=EntityType.FLOW,
                        entity_name=existing.name,
                        similarity_score=score,
                        match_reasons=reasons,
                        recommendation=recommendation,
                        details={
                            "existing_sensors": self._get_flow_sensor_ids(existing),
                            "existing_screens": self._get_flow_screens(existing),
                        }
                    ))

            matches.sort(key=lambda m: m.similarity_score, reverse=True)

        except Exception as e:
            logger.error(f"[Dedup] Error finding overlapping flows: {e}")

        return matches

    def _calculate_flow_overlap(
        self,
        new_flow: Dict[str, Any],
        existing
    ) -> Tuple[float, List[MatchReason]]:
        """Calculate overlap between two flows."""
        score = 0.0
        reasons = []

        # Get sensors from both flows
        new_sensors = set(self._get_flow_sensor_ids_from_dict(new_flow))
        existing_sensors = set(self._get_flow_sensor_ids(existing))

        if new_sensors and existing_sensors:
            overlap = new_sensors & existing_sensors
            if overlap:
                overlap_ratio = len(overlap) / max(len(new_sensors), len(existing_sensors))
                score += overlap_ratio * 0.50
                reasons.append(MatchReason.OVERLAPPING_SENSORS)

        # Get screens from both flows
        new_screens = set(self._get_flow_screens_from_dict(new_flow))
        existing_screens = set(self._get_flow_screens(existing))

        if new_screens and existing_screens:
            overlap = new_screens & existing_screens
            if overlap:
                overlap_ratio = len(overlap) / max(len(new_screens), len(existing_screens))
                score += overlap_ratio * 0.50
                reasons.append(MatchReason.OVERLAPPING_SCREENS)

        return min(score, 1.0), reasons

    def _get_flow_sensor_ids(self, flow) -> List[str]:
        """Extract sensor IDs from a flow object."""
        sensor_ids = []
        for step in flow.steps:
            if step.step_type == "capture_sensors":
                sensor_ids.extend(step.sensor_ids or [])
        return sensor_ids

    def _get_flow_sensor_ids_from_dict(self, flow: Dict) -> List[str]:
        """Extract sensor IDs from a flow dict."""
        sensor_ids = []
        for step in flow.get('steps', []):
            if step.get('step_type') == 'capture_sensors':
                sensor_ids.extend(step.get('sensor_ids', []))
        return sensor_ids

    def _get_flow_screens(self, flow) -> List[str]:
        """Extract screen activities from a flow object."""
        screens = []
        for step in flow.steps:
            if hasattr(step, 'expected_screen_id') and step.expected_screen_id:
                screens.append(step.expected_screen_id)
            if hasattr(step, 'screen_activity') and step.screen_activity:
                screens.append(step.screen_activity)
        return screens

    def _get_flow_screens_from_dict(self, flow: Dict) -> List[str]:
        """Extract screen activities from a flow dict."""
        screens = []
        for step in flow.get('steps', []):
            if step.get('expected_screen_id'):
                screens.append(step['expected_screen_id'])
            if step.get('screen_activity'):
                screens.append(step['screen_activity'])
        return screens

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_recommendation(self, score: float) -> Recommendation:
        """Get recommendation based on similarity score."""
        if score >= self.HIGH_SIMILARITY:
            return Recommendation.USE_EXISTING
        elif score >= self.MEDIUM_SIMILARITY:
            return Recommendation.MERGE
        elif score >= self.LOW_SIMILARITY:
            return Recommendation.REVIEW
        else:
            return Recommendation.KEEP_BOTH

    # =========================================================================
    # EXECUTION SESSION MANAGEMENT
    # =========================================================================

    def create_session(self, session_id: str = None) -> ExecutionSession:
        """Create a new execution session for caching."""
        session = ExecutionSession(session_id)
        self._sessions[session.session_id] = session
        logger.debug(f"[Dedup] Created execution session: {session.session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[ExecutionSession]:
        """Get an existing session."""
        return self._sessions.get(session_id)

    def end_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """End a session and return stats."""
        session = self._sessions.pop(session_id, None)
        if session:
            stats = session.get_stats()
            logger.info(f"[Dedup] Session ended: {stats}")
            return stats
        return None

    def cleanup_old_sessions(self, max_age_seconds: int = 300):
        """Remove sessions older than max_age."""
        now = datetime.now()
        expired = []
        for sid, session in self._sessions.items():
            age = (now - session.started_at).total_seconds()
            if age > max_age_seconds:
                expired.append(sid)

        for sid in expired:
            self.end_session(sid)

        if expired:
            logger.info(f"[Dedup] Cleaned up {len(expired)} expired sessions")

    # =========================================================================
    # OPTIMIZATION SUGGESTIONS
    # =========================================================================

    def get_optimization_suggestions(self, device_id: str) -> Dict[str, Any]:
        """
        Get all optimization suggestions for a device.

        Returns:
            {
                "sensors": [{"group": [...], "recommendation": "merge"}],
                "actions": [...],
                "flows": [...]
            }
        """
        suggestions = {
            "sensors": [],
            "actions": [],
            "flows": [],
            "summary": {
                "total_duplicates": 0,
                "potential_savings": 0
            }
        }

        # Find duplicate sensors
        if self.sensor_manager:
            sensor_groups = self._find_sensor_duplicate_groups(device_id)
            suggestions["sensors"] = sensor_groups
            suggestions["summary"]["total_duplicates"] += sum(len(g["items"]) - 1 for g in sensor_groups)

        # Find duplicate actions
        if self.action_manager:
            action_groups = self._find_action_duplicate_groups(device_id)
            suggestions["actions"] = action_groups
            suggestions["summary"]["total_duplicates"] += sum(len(g["items"]) - 1 for g in action_groups)

        # Find overlapping flows
        if self.flow_manager:
            flow_overlaps = self._find_flow_overlaps(device_id)
            suggestions["flows"] = flow_overlaps

        return suggestions

    def _find_sensor_duplicate_groups(self, device_id: str) -> List[Dict]:
        """Find groups of duplicate sensors."""
        groups = []
        try:
            sensors = self.sensor_manager.get_all_sensors(device_id)
            processed = set()

            for sensor in sensors:
                sid = sensor.get('sensor_id')
                if sid in processed:
                    continue

                # Find similar sensors
                similar = self.find_similar_sensors(device_id, sensor, threshold=self.MEDIUM_SIMILARITY)
                similar_ids = [m.entity_id for m in similar if m.entity_id != sid]

                if similar_ids:
                    group = {
                        "items": [sid] + similar_ids,
                        "names": [sensor.get('name', 'Unnamed')] + [m.entity_name for m in similar],
                        "recommendation": "merge",
                        "keep_suggestion": sid  # Suggest keeping the first one
                    }
                    groups.append(group)
                    processed.add(sid)
                    processed.update(similar_ids)

        except Exception as e:
            logger.error(f"[Dedup] Error finding sensor duplicates: {e}")

        return groups

    def _find_action_duplicate_groups(self, device_id: str) -> List[Dict]:
        """Find groups of duplicate actions."""
        groups = []
        try:
            actions = self.action_manager.get_actions(device_id)
            processed = set()

            for action in actions:
                aid = action.get('action_id')
                if aid in processed:
                    continue

                similar = self.find_similar_actions(device_id, action, threshold=self.MEDIUM_SIMILARITY)
                similar_ids = [m.entity_id for m in similar if m.entity_id != aid]

                if similar_ids:
                    group = {
                        "items": [aid] + similar_ids,
                        "names": [action.get('name', 'Unnamed')] + [m.entity_name for m in similar],
                        "recommendation": "merge",
                        "keep_suggestion": aid
                    }
                    groups.append(group)
                    processed.add(aid)
                    processed.update(similar_ids)

        except Exception as e:
            logger.error(f"[Dedup] Error finding action duplicates: {e}")

        return groups

    def _find_flow_overlaps(self, device_id: str) -> List[Dict]:
        """Find overlapping flows."""
        overlaps = []
        try:
            flows = self.flow_manager.get_device_flows(device_id)
            processed = set()

            for flow in flows:
                if flow.flow_id in processed or not flow.enabled:
                    continue

                flow_dict = flow.dict()
                similar = self.find_overlapping_flows(device_id, flow_dict, threshold=self.MEDIUM_SIMILARITY)
                similar_ids = [m.entity_id for m in similar if m.entity_id != flow.flow_id]

                if similar_ids:
                    overlap = {
                        "items": [flow.flow_id] + similar_ids,
                        "names": [flow.name] + [m.entity_name for m in similar],
                        "recommendation": "consolidate",
                        "overlap_details": [m.details for m in similar]
                    }
                    overlaps.append(overlap)
                    processed.add(flow.flow_id)
                    processed.update(similar_ids)

        except Exception as e:
            logger.error(f"[Dedup] Error finding flow overlaps: {e}")

        return overlaps
