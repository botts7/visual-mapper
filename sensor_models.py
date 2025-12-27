"""
Visual Mapper - Sensor Models
Version: 0.0.4 (Phase 3)

Pydantic models for sensor definitions and text extraction.
"""

from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class ExtractionMethod(str, Enum):
    """Text extraction method"""
    EXACT = "exact"  # Use exact text from UI element
    REGEX = "regex"  # Apply regex pattern
    NUMERIC = "numeric"  # Extract numbers only
    BEFORE = "before"  # Extract text before substring
    AFTER = "after"  # Extract text after substring
    BETWEEN = "between"  # Extract text between two substrings


class SensorType(str, Enum):
    """Home Assistant sensor type"""
    SENSOR = "sensor"  # Regular sensor (numeric or text)
    BINARY_SENSOR = "binary_sensor"  # On/off sensor


class DeviceClass(str, Enum):
    """Home Assistant device classes"""
    # Sensor device classes
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    BATTERY = "battery"
    POWER = "power"
    ENERGY = "energy"
    VOLTAGE = "voltage"
    CURRENT = "current"
    SPEED = "speed"
    DISTANCE = "distance"
    DURATION = "duration"
    TIMESTAMP = "timestamp"
    MONETARY = "monetary"

    # Binary sensor device classes
    BATTERY_CHARGING = "battery_charging"
    CONNECTIVITY = "connectivity"
    DOOR = "door"
    GARAGE_DOOR = "garage_door"
    LOCK = "lock"
    MOTION = "motion"
    OCCUPANCY = "occupancy"
    OPENING = "opening"
    PLUG = "plug"
    POWER_BINARY = "power"
    PRESENCE = "presence"
    RUNNING = "running"
    SAFETY = "safety"
    SMOKE = "smoke"
    SOUND = "sound"
    VIBRATION = "vibration"
    WINDOW = "window"

    # Generic
    NONE = "none"


class StateClass(str, Enum):
    """Home Assistant state class"""
    MEASUREMENT = "measurement"  # Instantaneous value
    TOTAL = "total"  # Cumulative value (resets)
    TOTAL_INCREASING = "total_increasing"  # Cumulative value (never decreases)


class TextExtractionRule(BaseModel):
    """Text extraction and parsing rule"""
    method: ExtractionMethod = ExtractionMethod.EXACT
    regex_pattern: Optional[str] = None  # For REGEX method
    before_text: Optional[str] = None  # For BEFORE method
    after_text: Optional[str] = None  # For AFTER method
    between_start: Optional[str] = None  # For BETWEEN method
    between_end: Optional[str] = None  # For BETWEEN method
    extract_numeric: bool = False  # Extract numeric value only
    remove_unit: bool = False  # Remove unit suffix (e.g., "94%" → "94")
    fallback_value: Optional[str] = None  # Value if extraction fails
    pipeline: Optional[List[Dict[str, Any]]] = None  # Multi-step extraction pipeline

    class Config:
        use_enum_values = True


class ElementBounds(BaseModel):
    """UI element bounds (x, y, width, height)"""
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)


class SensorSource(BaseModel):
    """Source of sensor data (UI element or custom bounds)"""
    source_type: Literal["element", "bounds"] = "element"
    element_index: Optional[int] = None  # Index in UI hierarchy
    element_text: Optional[str] = None  # Text content (for reference)
    element_class: Optional[str] = None  # Android class name
    element_resource_id: Optional[str] = None  # Android resource ID
    custom_bounds: Optional[ElementBounds] = None  # For manual selection


class SensorDefinition(BaseModel):
    """Complete sensor definition"""
    # Identity
    sensor_id: Optional[str] = Field(None, description="Unique sensor ID (auto-generated if not provided)")
    device_id: str = Field(..., description="Device this sensor belongs to")

    # Basic Configuration
    friendly_name: str = Field(..., min_length=1, max_length=100)
    sensor_type: SensorType = SensorType.SENSOR
    device_class: DeviceClass = DeviceClass.NONE
    unit_of_measurement: Optional[str] = None
    state_class: Optional[StateClass] = None
    icon: str = "mdi:cellphone"  # Material Design Icon

    # Data Source
    source: SensorSource

    # Text Extraction
    extraction_rule: TextExtractionRule

    # Update Configuration
    update_interval_seconds: int = Field(default=60, ge=5, le=3600)  # 5s - 1hr
    enabled: bool = True

    # Navigation Configuration (Phase 8 - v1.1.0)
    target_app: Optional[str] = Field(None, description="Package name to open before capture (e.g. com.spotify.music)")
    prerequisite_actions: List[str] = Field(default_factory=list, description="Action IDs to execute before capture")
    navigation_sequence: Optional[List[Dict[str, Any]]] = Field(None, description="Step-by-step navigation commands")
    validation_element: Optional[Dict[str, Any]] = Field(None, description="Element to verify correct screen (text, class, resource_id)")
    return_home_after: bool = Field(True, description="Return to home screen after capture")
    max_navigation_attempts: int = Field(3, ge=1, le=10, description="Max retries if navigation fails")
    navigation_timeout: int = Field(10, ge=1, le=60, description="Max seconds to wait for screen")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Current State (runtime, not persisted)
    current_value: Optional[str] = None
    last_updated: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "sensor_id": "battery_level_001",
                "device_id": "192.168.1.100:5555",
                "friendly_name": "Phone Battery Level",
                "sensor_type": "sensor",
                "device_class": "battery",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:battery",
                "source": {
                    "source_type": "element",
                    "element_index": 5,
                    "element_text": "94%",
                    "element_class": "android.widget.TextView"
                },
                "extraction_rule": {
                    "method": "numeric",
                    "extract_numeric": True,
                    "remove_unit": True
                },
                "update_interval_seconds": 60,
                "enabled": True
            }
        }


class SensorList(BaseModel):
    """List of sensors for a device"""
    device_id: str
    sensors: List[SensorDefinition] = []
    version: str = "0.0.5"
    last_modified: datetime = Field(default_factory=datetime.now)


class SensorStateUpdate(BaseModel):
    """Sensor state update for MQTT"""
    sensor_id: str
    state: str
    attributes: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.now)


class MQTTDiscoveryConfig(BaseModel):
    """Home Assistant MQTT discovery configuration"""
    name: str
    unique_id: str
    state_topic: str
    availability_topic: str
    device_class: Optional[str] = None
    unit_of_measurement: Optional[str] = None
    state_class: Optional[str] = None
    icon: Optional[str] = None
    json_attributes_topic: Optional[str] = None
    device: Dict[str, Any]  # Device info for HA

    class Config:
        use_enum_values = True
