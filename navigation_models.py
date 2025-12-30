"""
Visual Mapper - Navigation Models
Pydantic models for app navigation graph learning system

The navigation system learns how to navigate between screens in Android apps
through three methods:
1. Automatic learning during flow recording
2. Mining existing saved flows
3. Explicit teaching mode (manual)
"""

import hashlib
from typing import Dict, List, Optional, Literal, Any
from pydantic import BaseModel, Field
from datetime import datetime


class TransitionAction(BaseModel):
    """
    Defines the action that causes a screen transition
    """
    action_type: Literal["tap", "swipe", "keyevent", "go_back", "go_home", "text"] = Field(
        ..., description="Type of action that triggers transition"
    )

    # Tap coordinates
    x: Optional[int] = Field(None, description="X coordinate for tap")
    y: Optional[int] = Field(None, description="Y coordinate for tap")

    # Element identification (more reliable than coordinates)
    element_resource_id: Optional[str] = Field(None, description="Resource ID of tapped element")
    element_text: Optional[str] = Field(None, description="Text of tapped element")
    element_class: Optional[str] = Field(None, description="Class of tapped element")
    element_content_desc: Optional[str] = Field(None, description="Content description of element")

    # Swipe parameters
    start_x: Optional[int] = Field(None, description="Swipe start X")
    start_y: Optional[int] = Field(None, description="Swipe start Y")
    end_x: Optional[int] = Field(None, description="Swipe end X")
    end_y: Optional[int] = Field(None, description="Swipe end Y")
    swipe_direction: Optional[Literal["up", "down", "left", "right"]] = Field(
        None, description="Swipe direction if applicable"
    )

    # Keyevent
    keycode: Optional[str] = Field(None, description="Android keycode (e.g., KEYCODE_BACK)")

    # Text input
    text: Optional[str] = Field(None, description="Text to type")

    # Human-readable description
    description: Optional[str] = Field(None, description="Human-readable description of action")


class ScreenNode(BaseModel):
    """
    Represents a unique screen/state in the navigation graph

    A screen is identified by:
    - Activity name (primary)
    - UI landmarks (secondary, for sub-screen differentiation)
    """
    screen_id: str = Field(..., description="Unique ID (hash of activity + landmarks)")
    package: str = Field(..., description="App package name")
    activity: str = Field(..., description="Android activity name")

    # Human-readable identification
    display_name: Optional[str] = Field(None, description="Human-readable screen name")

    # UI landmarks for sub-screen identification
    ui_landmarks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Key UI elements that identify this screen (toolbar titles, tab labels, etc.)"
    )

    # Metadata
    learned_from: Literal["recording", "teaching", "mining"] = Field(
        "recording", description="How this screen was discovered"
    )
    first_seen: datetime = Field(default_factory=datetime.now)
    last_seen: datetime = Field(default_factory=datetime.now)
    visit_count: int = Field(0, description="Number of times this screen was visited")

    # Flags
    is_home_screen: bool = Field(False, description="Is this the app's home/main screen?")
    is_transient: bool = Field(False, description="Is this a transient screen (dialog, toast)?")


class ScreenTransition(BaseModel):
    """
    Represents a navigation edge from one screen to another
    """
    transition_id: str = Field(..., description="Unique transition ID")
    source_screen_id: str = Field(..., description="Source screen ID")
    target_screen_id: str = Field(..., description="Target screen ID")

    # The action that causes this transition
    action: TransitionAction = Field(..., description="Action that triggers this transition")

    # Statistics for pathfinding weight calculation
    success_rate: float = Field(1.0, ge=0.0, le=1.0, description="Success rate (0.0-1.0)")
    usage_count: int = Field(0, description="Number of times this transition was used")
    avg_transition_time_ms: int = Field(500, description="Average time to complete transition")

    # Metadata
    learned_from: Literal["recording", "teaching", "mining"] = Field(
        "recording", description="How this transition was learned"
    )
    created_at: datetime = Field(default_factory=datetime.now)
    last_used: datetime = Field(default_factory=datetime.now)
    last_success: Optional[bool] = Field(None, description="Did the last use succeed?")


class NavigationGraph(BaseModel):
    """
    Complete navigation graph for an app

    Stores all known screens and transitions for a specific app package.
    Used by FlowExecutor to navigate to required screens.
    """
    graph_id: str = Field(..., description="Unique graph ID")
    package: str = Field(..., description="App package name")

    # Optional device binding (for device-specific navigation)
    device_id: Optional[str] = Field(None, description="Device ID if device-specific")
    stable_device_id: Optional[str] = Field(None, description="Stable device ID")

    # Graph data
    screens: Dict[str, ScreenNode] = Field(
        default_factory=dict,
        description="Screen nodes keyed by screen_id"
    )
    transitions: List[ScreenTransition] = Field(
        default_factory=list,
        description="All known transitions"
    )

    # Special screens
    home_screen_id: Optional[str] = Field(
        None, description="The app's home/launch screen (fallback anchor)"
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    version: int = Field(1, description="Graph version for migrations")

    # Statistics
    total_recordings: int = Field(0, description="Flows that contributed to this graph")
    total_navigations: int = Field(0, description="Times this graph was used for navigation")


class NavigationPath(BaseModel):
    """
    Represents a path from one screen to another

    Returned by pathfinding algorithms
    """
    from_screen_id: str
    to_screen_id: str
    transitions: List[ScreenTransition] = Field(
        default_factory=list,
        description="Ordered list of transitions to execute"
    )
    total_cost: float = Field(0.0, description="Path cost (lower is better)")
    estimated_time_ms: int = Field(0, description="Estimated time to traverse path")

    @property
    def hop_count(self) -> int:
        """Number of transitions in this path"""
        return len(self.transitions)


class LearnTransitionRequest(BaseModel):
    """
    Request model for learning a screen transition
    Used by flow recorder to report observed transitions
    """
    # Before state
    before_activity: str = Field(..., description="Activity before action")
    before_package: str = Field(..., description="Package before action")
    before_ui_elements: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="UI elements before action (for landmark extraction)"
    )

    # After state
    after_activity: str = Field(..., description="Activity after action")
    after_package: str = Field(..., description="Package after action")
    after_ui_elements: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="UI elements after action"
    )

    # The action performed
    action: TransitionAction = Field(..., description="Action that was performed")

    # Optional metadata
    device_id: Optional[str] = Field(None, description="Device ID")
    transition_time_ms: Optional[int] = Field(None, description="How long the transition took")


# ============================================================================
# Helper Functions
# ============================================================================

def compute_screen_id(activity: str, ui_landmarks: List[Dict[str, Any]] = None) -> str:
    """
    Generate a deterministic screen ID from activity and UI landmarks

    Args:
        activity: Android activity name
        ui_landmarks: List of landmark elements (optional)

    Returns:
        16-character hex hash
    """
    if ui_landmarks is None:
        ui_landmarks = []

    # Extract landmark strings
    landmark_strs = []
    for landmark in ui_landmarks:
        # Priority: text > resource_id > content_desc
        # Handle both underscore and hyphen variants
        text = landmark.get('text', '')
        resource_id = landmark.get('resource_id', '') or landmark.get('resource-id', '')
        content_desc = landmark.get('content_desc', '') or landmark.get('content-desc', '')

        if text:
            landmark_strs.append(f"text:{text}")
        elif resource_id:
            landmark_strs.append(f"id:{resource_id}")
        elif content_desc:
            landmark_strs.append(f"desc:{content_desc}")

    # Sort for determinism
    landmark_strs.sort()

    # Create hash input
    hash_input = f"{activity}|{','.join(landmark_strs)}"

    # Generate hash
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def extract_ui_landmarks(ui_elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract landmark elements from UI element list

    Landmarks are elements that help identify a specific screen:
    - Toolbar/ActionBar titles
    - Tab labels
    - Unique titles and headers
    - Navigation drawer items

    Args:
        ui_elements: Full list of UI elements

    Returns:
        Filtered list of landmark elements
    """
    landmarks = []

    for el in ui_elements:
        # Handle both underscore and hyphen variants (ADB uses hyphen, some parsers use underscore)
        resource_id = el.get('resource_id', '') or el.get('resource-id', '') or ''
        class_name = el.get('class', '') or ''
        text = el.get('text', '') or ''
        content_desc = el.get('content_desc', '') or el.get('content-desc', '') or ''

        # Skip empty elements
        if not text and not content_desc:
            continue

        # Toolbar titles (high priority)
        if 'toolbar' in resource_id.lower() or 'action_bar' in resource_id.lower():
            landmarks.append({
                'type': 'toolbar',
                'text': text,
                'resource_id': resource_id
            })
            continue

        # Tab labels
        if 'tab' in resource_id.lower() or 'TabLayout' in class_name:
            landmarks.append({
                'type': 'tab',
                'text': text,
                'resource_id': resource_id
            })
            continue

        # Title-like TextViews (heuristic: short text, likely a header)
        if 'TextView' in class_name and text:
            # Titles are usually short (< 50 chars) and don't contain newlines
            if len(text) < 50 and '\n' not in text:
                # Check for title-like resource IDs
                if any(kw in resource_id.lower() for kw in ['title', 'header', 'name', 'label']):
                    landmarks.append({
                        'type': 'title',
                        'text': text,
                        'resource_id': resource_id
                    })

    # Deduplicate
    seen = set()
    unique_landmarks = []
    for lm in landmarks:
        key = (lm.get('text'), lm.get('resource_id'))
        if key not in seen:
            seen.add(key)
            unique_landmarks.append(lm)

    return unique_landmarks


def generate_transition_id(source_id: str, target_id: str, action: TransitionAction) -> str:
    """
    Generate a unique transition ID

    Args:
        source_id: Source screen ID
        target_id: Target screen ID
        action: The transition action

    Returns:
        Unique transition ID
    """
    # Include action details in hash for uniqueness
    action_key = f"{action.action_type}"
    if action.x is not None and action.y is not None:
        action_key += f"_{action.x}_{action.y}"
    if action.element_resource_id:
        action_key += f"_{action.element_resource_id}"
    if action.swipe_direction:
        action_key += f"_{action.swipe_direction}"

    hash_input = f"{source_id}|{target_id}|{action_key}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
