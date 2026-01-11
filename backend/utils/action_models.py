"""
Action Models for Visual Mapper

Defines Pydantic models for device actions that can be executed and saved.
"""

from typing import Optional, List, Dict, Any, Literal, ClassVar, Union, Annotated
from pydantic import BaseModel, Field, validator, Discriminator
from datetime import datetime


class ActionBase(BaseModel):
    """Base model for all action types"""

    name: str = Field(..., min_length=1, max_length=100, description="Action name")
    description: Optional[str] = Field(
        None, max_length=500, description="Action description"
    )
    device_id: str = Field(..., description="Target device ID")
    enabled: bool = Field(default=True, description="Whether action is enabled")


class TapAction(ActionBase):
    """Tap at specific coordinates"""

    action_type: Literal["tap"] = "tap"
    x: int = Field(..., ge=0, description="X coordinate")
    y: int = Field(..., ge=0, description="Y coordinate")

    @validator("x", "y")
    def validate_coordinates(cls, v):
        if v < 0:
            raise ValueError("Coordinates must be non-negative")
        if v > 10000:  # Reasonable max for any device
            raise ValueError("Coordinate value too large")
        return v


class SwipeAction(ActionBase):
    """Swipe from one point to another"""

    action_type: Literal["swipe"] = "swipe"
    x1: int = Field(..., ge=0, description="Start X coordinate")
    y1: int = Field(..., ge=0, description="Start Y coordinate")
    x2: int = Field(..., ge=0, description="End X coordinate")
    y2: int = Field(..., ge=0, description="End Y coordinate")
    duration: int = Field(
        default=300, ge=50, le=5000, description="Swipe duration in ms"
    )


class TextInputAction(ActionBase):
    """Type text into focused field"""

    action_type: Literal["text"] = "text"
    text: str = Field(..., min_length=1, max_length=1000, description="Text to type")

    @validator("text")
    def validate_text(cls, v):
        # Escape special characters for ADB
        # In actual implementation, this will be handled by the executor
        if not v.strip():
            raise ValueError("Text cannot be empty or whitespace only")
        return v


class KeyEventAction(ActionBase):
    """Press a hardware key"""

    action_type: Literal["keyevent"] = "keyevent"
    keycode: str = Field(
        ..., description="Android keycode (e.g., KEYCODE_HOME, KEYCODE_BACK)"
    )

    # Common keycodes (ClassVar to avoid Pydantic field conflict)
    VALID_KEYCODES: ClassVar[List[str]] = [
        "KEYCODE_HOME",
        "KEYCODE_BACK",
        "KEYCODE_MENU",
        "KEYCODE_VOLUME_UP",
        "KEYCODE_VOLUME_DOWN",
        "KEYCODE_VOLUME_MUTE",
        "KEYCODE_POWER",
        "KEYCODE_CAMERA",
        "KEYCODE_APP_SWITCH",
        "KEYCODE_ENTER",
        "KEYCODE_DEL",
        "KEYCODE_SPACE",
        "KEYCODE_DPAD_UP",
        "KEYCODE_DPAD_DOWN",
        "KEYCODE_DPAD_LEFT",
        "KEYCODE_DPAD_RIGHT",
        "KEYCODE_MEDIA_PLAY",
        "KEYCODE_MEDIA_PAUSE",
        "KEYCODE_MEDIA_PLAY_PAUSE",
        "KEYCODE_MEDIA_STOP",
        "KEYCODE_MEDIA_NEXT",
        "KEYCODE_MEDIA_PREVIOUS",
    ]

    @validator("keycode")
    def validate_keycode(cls, v):
        if not v.startswith("KEYCODE_"):
            raise ValueError("Keycode must start with 'KEYCODE_'")
        return v.upper()


class LaunchAppAction(ActionBase):
    """Launch an app by package name"""

    action_type: Literal["launch_app"] = "launch_app"
    package_name: str = Field(
        ..., description="Android package name (e.g., com.android.chrome)"
    )
    activity: Optional[str] = Field(
        None, description="Optional activity name to launch"
    )

    @validator("package_name")
    def validate_package(cls, v):
        # Basic package name validation (should contain at least one dot)
        if "." not in v:
            raise ValueError(
                "Package name must contain at least one dot (e.g., com.example.app)"
            )
        if v.startswith(".") or v.endswith("."):
            raise ValueError("Package name cannot start or end with a dot")
        return v.lower()


class DelayAction(ActionBase):
    """Wait for specified duration"""

    action_type: Literal["delay"] = "delay"
    duration: int = Field(
        ..., ge=10, le=60000, description="Delay duration in milliseconds"
    )


class MacroAction(ActionBase):
    """Execute a sequence of actions"""

    action_type: Literal["macro"] = "macro"
    actions: List[Dict[str, Any]] = Field(
        ..., min_items=1, description="List of actions to execute"
    )
    stop_on_error: bool = Field(
        default=False, description="Stop macro if any action fails"
    )

    @validator("actions")
    def validate_actions(cls, v):
        if not v:
            raise ValueError("Macro must contain at least one action")
        if len(v) > 50:
            raise ValueError("Macro cannot contain more than 50 actions")
        return v


# Union type for all action types with discriminator
ActionType = Annotated[
    Union[
        TapAction,
        SwipeAction,
        TextInputAction,
        KeyEventAction,
        LaunchAppAction,
        DelayAction,
        MacroAction,
    ],
    Field(discriminator="action_type"),
]


class ActionDefinition(BaseModel):
    """Complete action definition with metadata"""

    id: str = Field(..., description="Unique action ID")
    action: ActionType = Field(..., description="Action configuration")
    stable_device_id: Optional[str] = Field(
        None, description="Stable device identifier (hashed Android ID)"
    )
    source_app: Optional[str] = Field(
        None,
        description="App package name where action was created (e.g., com.android.chrome)",
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.now, description="Last update timestamp"
    )
    execution_count: int = Field(
        default=0, ge=0, description="Number of times executed"
    )
    last_executed: Optional[datetime] = Field(
        None, description="Last execution timestamp"
    )
    last_result: Optional[str] = Field(
        None, description="Last execution result (success/error)"
    )
    tags: List[str] = Field(
        default_factory=list, description="Action tags for organization"
    )

    # Navigation Configuration (mirrors SensorDefinition pattern)
    # When set, action will navigate to correct screen before executing
    target_app: Optional[str] = Field(
        None,
        description="Package name to launch before executing action (e.g., com.spotify.music)",
    )
    prerequisite_actions: List[str] = Field(
        default_factory=list,
        description="Action IDs to execute before this action (e.g., navigate to screen)",
    )
    navigation_sequence: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Step-by-step navigation commands to reach target screen (tap, swipe, wait)",
    )
    validation_element: Optional[Dict[str, Any]] = Field(
        None,
        description="Element to verify correct screen before executing (text, class, resource_id)",
    )
    return_home_after: bool = Field(
        False,  # Default False for actions (unlike sensors)
        description="Return to home screen after action execution",
    )
    max_navigation_attempts: int = Field(
        3, ge=1, le=10, description="Max retries if navigation/validation fails"
    )
    navigation_timeout: int = Field(
        10, ge=1, le=60, description="Max seconds to wait for screen validation"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ActionExecutionRequest(BaseModel):
    """Request to execute an action"""

    action_id: Optional[str] = Field(
        None, description="Action ID to execute (if saved)"
    )
    action: Optional[ActionType] = Field(
        None, description="Inline action to execute (if not saved)"
    )

    @validator("action")
    def validate_action_or_id(cls, v, values):
        if v is None and values.get("action_id") is None:
            raise ValueError("Either action_id or action must be provided")
        if v is not None and values.get("action_id") is not None:
            raise ValueError("Provide either action_id or action, not both")
        return v


class ActionExecutionResult(BaseModel):
    """Result of action execution"""

    success: bool
    message: str
    execution_time: float = Field(..., description="Execution time in milliseconds")
    action_id: Optional[str] = None
    action_type: str
    details: Optional[Dict[str, Any]] = None


class ActionListResponse(BaseModel):
    """Response for listing actions"""

    actions: List[ActionDefinition]
    total: int
    device_id: Optional[str] = None


class ActionCreateRequest(BaseModel):
    """Request to create a new action"""

    action: ActionType
    tags: List[str] = Field(default_factory=list)
    source_app: Optional[str] = Field(
        None, description="App package name where action was created"
    )

    # Navigation Configuration (optional)
    target_app: Optional[str] = Field(
        None, description="Package to launch before executing"
    )
    prerequisite_actions: List[str] = Field(
        default_factory=list, description="Action IDs to execute first"
    )
    navigation_sequence: Optional[List[Dict[str, Any]]] = Field(
        None, description="Navigation steps"
    )
    validation_element: Optional[Dict[str, Any]] = Field(
        None, description="Screen validation element"
    )
    return_home_after: bool = Field(False, description="Return home after execution")
    max_navigation_attempts: int = Field(3, ge=1, le=10)
    navigation_timeout: int = Field(10, ge=1, le=60)


class ActionUpdateRequest(BaseModel):
    """Request to update an existing action"""

    action: Optional[ActionType] = None
    enabled: Optional[bool] = None
    tags: Optional[List[str]] = None

    # Navigation Configuration (all optional for partial updates)
    target_app: Optional[str] = None
    prerequisite_actions: Optional[List[str]] = None
    navigation_sequence: Optional[List[Dict[str, Any]]] = None
    validation_element: Optional[Dict[str, Any]] = None
    return_home_after: Optional[bool] = None
    max_navigation_attempts: Optional[int] = None
    navigation_timeout: Optional[int] = None


# MQTT Service Discovery Models


class ActionServiceDiscovery(BaseModel):
    """MQTT discovery payload for action services"""

    name: str
    unique_id: str
    device_id: str
    icon: str = "mdi:play"
    entity_category: str = "config"
    command_topic: str
    availability_topic: str
    payload_available: str = "online"
    payload_not_available: str = "offline"
