"""
Visual Mapper - Flow Models (Phase 8)
Advanced sensor collection flows for efficient multi-sensor capture
"""

from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


class FlowStepType(str):
    """Types of steps in a flow"""

    LAUNCH_APP = "launch_app"
    WAIT = "wait"
    TAP = "tap"
    SWIPE = "swipe"
    TEXT = "text"
    KEYEVENT = "keyevent"
    EXECUTE_ACTION = "execute_action"
    CAPTURE_SENSORS = "capture_sensors"
    VALIDATE_SCREEN = "validate_screen"
    GO_HOME = "go_home"
    GO_BACK = "go_back"
    CONDITIONAL = "conditional"
    PULL_REFRESH = "pull_refresh"
    RESTART_APP = "restart_app"
    STITCH_CAPTURE = "stitch_capture"
    SCREENSHOT = "screenshot"  # Capture screenshot at current screen
    # Screen power control (headless mode)
    WAKE_SCREEN = "wake_screen"
    SLEEP_SCREEN = "sleep_screen"
    ENSURE_SCREEN_ON = "ensure_screen_on"
    # Phase 9: Advanced flow control
    LOOP = "loop"  # Repeat nested steps N times
    SET_VARIABLE = "set_variable"  # Store value in variable context
    INCREMENT = "increment"  # Increment a numeric variable
    BREAK_LOOP = "break_loop"  # Exit current loop early
    CONTINUE_LOOP = "continue_loop"  # Skip to next iteration


class FlowStep(BaseModel):
    """Single step in a sensor collection flow"""

    step_type: str = Field(..., description="Type of step to execute")

    # App launching
    package: Optional[str] = Field(None, description="Package name for launch_app")

    # Wait/delay
    duration: Optional[int] = Field(
        None, description="Duration in milliseconds for wait step"
    )

    # Tap
    x: Optional[int] = Field(None, description="X coordinate for tap")
    y: Optional[int] = Field(None, description="Y coordinate for tap")
    element: Optional[Dict[str, Any]] = Field(
        None,
        description="Element metadata for tap actions (text, resource_id, class, bounds)",
    )

    # Swipe
    start_x: Optional[int] = None
    start_y: Optional[int] = None
    end_x: Optional[int] = None
    end_y: Optional[int] = None

    # Text input
    text: Optional[str] = Field(None, description="Text to type")

    # Keyevent
    keycode: Optional[str] = Field(None, description="Android keycode")

    # Action execution
    action_id: Optional[str] = Field(None, description="Action ID to execute")

    # Sensor capture
    sensor_ids: Optional[List[str]] = Field(
        None, description="List of sensor IDs to capture at this step"
    )

    # Screen validation
    validation_element: Optional[Dict[str, Any]] = Field(
        None, description="Element to verify presence"
    )

    # Conditional
    condition: Optional[str] = Field(
        None, description="Condition to evaluate (if/else)"
    )
    true_steps: Optional[List["FlowStep"]] = Field(
        None, description="Steps if condition is true"
    )
    false_steps: Optional[List["FlowStep"]] = Field(
        None, description="Steps if condition is false"
    )

    # Loop (Phase 9)
    iterations: Optional[int] = Field(
        None, ge=1, le=100, description="Number of times to repeat loop_steps"
    )
    loop_steps: Optional[List["FlowStep"]] = Field(
        None, description="Steps to repeat in loop"
    )
    loop_variable: Optional[str] = Field(
        None, description="Variable name for loop counter (0-indexed)"
    )

    # Variables (Phase 9)
    variable_name: Optional[str] = Field(
        None, description="Variable name for set_variable/increment"
    )
    variable_value: Optional[str] = Field(
        None, description="Value to set (can include ${var} references)"
    )
    increment_by: Optional[int] = Field(
        1, description="Amount to increment variable by"
    )

    # Retry logic
    retry_on_failure: bool = Field(False, description="Retry this step if it fails")
    max_retries: int = Field(3, ge=1, le=10, description="Max retry attempts")

    # Description for UI
    description: Optional[str] = Field(
        None, description="Human-readable description of this step"
    )

    # State validation (Phase 8 - Hybrid: XML + Screenshot + Activity)
    expected_ui_elements: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Expected UI elements (text, class, resource-id) for state validation",
    )
    expected_activity: Optional[str] = Field(
        None, description="Expected Android activity name for state validation"
    )
    expected_screenshot: Optional[str] = Field(
        None, description="Base64 encoded screenshot (fallback validation)"
    )
    state_match_threshold: float = Field(
        0.80,
        ge=0.0,
        le=1.0,
        description="Similarity threshold for state matching (0.0-1.0)",
    )
    validate_state: bool = Field(
        True, description="Whether to validate state before executing this step"
    )
    recovery_action: str = Field(
        "force_restart_app",
        description="Recovery action on state mismatch: force_restart_app, skip_step, fail",
    )
    ui_elements_required: int = Field(
        1, ge=1, description="Minimum number of expected UI elements that must match"
    )

    # Screen awareness (Phase 1 - Activity Tracking)
    screen_activity: Optional[str] = Field(
        None, description="Activity when step was recorded (e.g., 'MainActivity')"
    )
    screen_package: Optional[str] = Field(
        None, description="Package when step was recorded (e.g., 'com.example.app')"
    )

    # Navigation (Phase 9 - Navigation Learning)
    expected_screen_id: Optional[str] = Field(
        None, description="Screen ID this step should start on (from navigation graph)"
    )
    navigation_required: bool = Field(
        False, description="If true, navigate to expected_screen_id before executing"
    )

    # Timestamp validation for refresh actions (ensure data actually updated)
    validate_timestamp: bool = Field(
        False, description="Validate timestamp element changed after refresh"
    )
    timestamp_element: Optional[Dict[str, Any]] = Field(
        None,
        description="Element containing 'last updated' timestamp (bounds, text, resource-id)",
    )
    refresh_max_retries: int = Field(
        3, ge=1, le=10, description="Max refresh attempts if timestamp unchanged"
    )
    refresh_retry_delay: int = Field(
        2000, ge=500, le=10000, description="Delay in ms between refresh retries"
    )


class SensorCollectionFlow(BaseModel):
    """
    Advanced flow for collecting multiple sensors efficiently
    One flow can navigate through multiple screens and capture many sensors
    """

    # Identity
    flow_id: str = Field(..., description="Unique flow ID (generated)")
    device_id: str = Field(..., description="Device this flow belongs to")
    stable_device_id: Optional[str] = Field(
        None, description="Stable device identifier (hashed Android ID)"
    )

    # Basic Configuration
    name: str = Field(..., min_length=1, max_length=100, description="Flow name")
    description: Optional[str] = Field(None, description="Flow description")

    # Flow Steps
    steps: List[FlowStep] = Field(..., description="Ordered list of steps to execute")

    # Update Configuration
    update_interval_seconds: int = Field(
        default=60, ge=5, le=3600, description="How often to run this flow"
    )
    enabled: bool = Field(True, description="Enable/disable this flow")

    # Error Handling
    stop_on_error: bool = Field(False, description="Stop flow if any step fails")
    max_flow_retries: int = Field(
        3, ge=1, le=10, description="Retry entire flow on failure"
    )
    flow_timeout: int = Field(
        60, ge=10, le=300, description="Max seconds for entire flow"
    )

    # Execution Start
    start_from_current_screen: bool = Field(
        False, description="If true, skip app restart and begin from current screen"
    )

    # Execution Method (Phase 1 - Execution Routing)
    execution_method: Literal["server", "android", "auto"] = Field(
        default="server",
        description="Where to execute this flow: server (ADB), android (companion app), or auto (smart routing)",
    )
    preferred_executor: str = Field(
        default="android", description="Preferred executor when using auto mode"
    )
    fallback_executor: str = Field(
        default="server", description="Fallback executor if preferred fails"
    )

    # Headless Mode (Screen Power Control)
    auto_wake_before: bool = Field(
        True, description="Auto-wake screen before flow execution"
    )
    auto_sleep_after: bool = Field(
        True, description="Auto-sleep screen after flow completion"
    )
    verify_screen_on: bool = Field(
        True, description="Fail flow if screen fails to wake"
    )
    wake_timeout_ms: int = Field(
        3000, ge=1000, le=10000, description="Max time to wait for screen wake"
    )

    # Backtrack (Return to Start) - For faster subsequent runs
    backtrack_after: bool = Field(
        True,
        description="Navigate back to starting screen after flow completes (enables faster next run)",
    )
    backtrack_to_app_home: bool = Field(
        False,
        description="If true, backtrack to app home instead of first capture screen",
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Runtime State
    last_executed: Optional[datetime] = None
    last_success: Optional[bool] = None
    last_error: Optional[str] = None
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "flow_id": "spotify_collection_001",
                "device_id": "192.168.1.100:5555",
                "name": "Spotify Multi-Sensor Collection",
                "description": "Collect Now Playing, Artist, and Volume from Spotify",
                "steps": [
                    {
                        "step_type": "launch_app",
                        "package": "com.spotify.music",
                        "description": "Launch Spotify",
                    },
                    {
                        "step_type": "wait",
                        "duration": 2000,
                        "description": "Wait for app to load",
                    },
                    {
                        "step_type": "validate_screen",
                        "validation_element": {
                            "text": "Now Playing",
                            "class": "android.widget.TextView",
                        },
                        "retry_on_failure": True,
                        "max_retries": 3,
                        "description": "Verify Now Playing screen",
                    },
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": ["spotify_song", "spotify_artist"],
                        "description": "Capture song and artist from Now Playing screen",
                    },
                    {
                        "step_type": "execute_action",
                        "action_id": "spotify_goto_settings",
                        "description": "Navigate to settings",
                    },
                    {"step_type": "wait", "duration": 1000},
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": ["spotify_volume"],
                        "description": "Capture volume from settings",
                    },
                    {"step_type": "go_home", "description": "Return to home screen"},
                ],
                "update_interval_seconds": 60,
                "enabled": True,
                "stop_on_error": False,
                "max_flow_retries": 3,
                "flow_timeout": 60,
            }
        }
    )


class StepResult(BaseModel):
    """Result of executing a single step"""

    step_index: int
    step_type: str
    description: Optional[str] = None
    success: bool
    error_message: Optional[str] = None
    # For capture_sensors: {sensor_id: {name: str, value: any}}
    # For execute_action: {action_id: str, action_name: str, result: str}
    details: Dict[str, Any] = {}


class FlowExecutionResult(BaseModel):
    """Result of executing a flow"""

    flow_id: str
    success: bool
    executed_steps: int
    failed_step: Optional[int] = None
    error_message: Optional[str] = None
    captured_sensors: Dict[str, Any] = {}  # sensor_id -> value
    captured_screenshots: List[Dict[str, Any]] = []  # Screenshots captured during flow
    step_results: List[StepResult] = []  # Per-step results with values
    learned_screens: List[Dict[str, Any]] = (
        []
    )  # Screens learned during Learn Mode execution
    execution_time_ms: int
    timestamp: datetime = Field(default_factory=datetime.now)


class FlowList(BaseModel):
    """List of flows for a device"""

    device_id: str
    flows: List[SensorCollectionFlow] = []
    version: str = "0.0.40"
    last_modified: datetime = Field(default_factory=datetime.now)


# Simple mode: Auto-generate flow from sensor navigation config
def sensor_to_simple_flow(sensor) -> SensorCollectionFlow:
    """
    Convert a sensor with navigation config to a simple single-sensor flow
    This allows backward compatibility with simple mode
    """
    steps = []

    # Step 1: Launch app if specified
    if sensor.target_app:
        steps.append(
            FlowStep(
                step_type=FlowStepType.LAUNCH_APP,
                package=sensor.target_app,
                description=f"Launch {sensor.target_app}",
            )
        )

        # Wait for app to load
        steps.append(
            FlowStep(
                step_type=FlowStepType.WAIT,
                duration=2000,
                description="Wait for app to load",
            )
        )

    # Step 2: Execute prerequisite actions
    for action_id in sensor.prerequisite_actions:
        steps.append(
            FlowStep(
                step_type=FlowStepType.EXECUTE_ACTION,
                action_id=action_id,
                description=f"Execute action {action_id}",
            )
        )

        # Brief wait between actions
        steps.append(FlowStep(step_type=FlowStepType.WAIT, duration=500))

    # Step 3: Execute navigation sequence if specified
    if sensor.navigation_sequence:
        for nav_step in sensor.navigation_sequence:
            steps.append(FlowStep(**nav_step))

    # Step 4: Validate screen if specified
    if sensor.validation_element:
        steps.append(
            FlowStep(
                step_type=FlowStepType.VALIDATE_SCREEN,
                validation_element=sensor.validation_element,
                retry_on_failure=True,
                max_retries=sensor.max_navigation_attempts,
                description="Validate correct screen",
            )
        )

    # Step 5: Capture this sensor
    steps.append(
        FlowStep(
            step_type=FlowStepType.CAPTURE_SENSORS,
            sensor_ids=[sensor.sensor_id],
            description=f"Capture {sensor.friendly_name}",
        )
    )

    # Step 6: Go home if specified
    if sensor.return_home_after:
        steps.append(
            FlowStep(
                step_type=FlowStepType.GO_HOME, description="Return to home screen"
            )
        )

    # Create flow
    return SensorCollectionFlow(
        flow_id=f"simple_{sensor.sensor_id}",
        device_id=sensor.device_id,
        name=f"Simple Flow: {sensor.friendly_name}",
        description=f"Auto-generated simple flow for sensor {sensor.friendly_name}",
        steps=steps,
        update_interval_seconds=sensor.update_interval_seconds,
        enabled=sensor.enabled,
        flow_timeout=sensor.navigation_timeout,
    )
