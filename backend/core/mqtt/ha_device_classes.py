"""
Home Assistant Device Class Reference
Comprehensive list of device classes, units, icons, and validation rules
Based on Home Assistant official documentation (2025-01-01)
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class DeviceClassInfo:
    """Device class metadata"""

    name: str
    description: str
    valid_units: List[str]
    default_icon: str
    state_class_allowed: bool = True  # Whether state_class can be used
    sensor_type: str = "sensor"  # "sensor" or "binary_sensor"


# Standard Sensor Device Classes
SENSOR_DEVICE_CLASSES: Dict[str, DeviceClassInfo] = {
    # Energy & Power
    "battery": DeviceClassInfo(
        name="Battery",
        description="Percentage of battery that is left",
        valid_units=["%"],
        default_icon="mdi:battery",
        state_class_allowed=True,
    ),
    "power": DeviceClassInfo(
        name="Power",
        description="Power measurement",
        valid_units=["W", "kW"],
        default_icon="mdi:flash",
        state_class_allowed=True,
    ),
    "energy": DeviceClassInfo(
        name="Energy",
        description="Energy consumption",
        valid_units=["Wh", "kWh", "MWh", "GWh"],
        default_icon="mdi:lightning-bolt",
        state_class_allowed=True,
    ),
    "voltage": DeviceClassInfo(
        name="Voltage",
        description="Voltage measurement",
        valid_units=["V", "mV"],
        default_icon="mdi:sine-wave",
        state_class_allowed=True,
    ),
    "current": DeviceClassInfo(
        name="Current",
        description="Current measurement",
        valid_units=["A", "mA"],
        default_icon="mdi:current-ac",
        state_class_allowed=True,
    ),
    "power_factor": DeviceClassInfo(
        name="Power Factor",
        description="Power factor",
        valid_units=["%", ""],
        default_icon="mdi:angle-acute",
        state_class_allowed=True,
    ),
    # Environmental
    "temperature": DeviceClassInfo(
        name="Temperature",
        description="Temperature measurement",
        valid_units=["°C", "°F", "K"],
        default_icon="mdi:thermometer",
        state_class_allowed=True,
    ),
    "humidity": DeviceClassInfo(
        name="Humidity",
        description="Relative humidity",
        valid_units=["%"],
        default_icon="mdi:water-percent",
        state_class_allowed=True,
    ),
    "pressure": DeviceClassInfo(
        name="Pressure",
        description="Atmospheric pressure",
        valid_units=["Pa", "hPa", "kPa", "bar", "mbar", "mmHg", "inHg", "psi"],
        default_icon="mdi:gauge",
        state_class_allowed=True,
    ),
    "illuminance": DeviceClassInfo(
        name="Illuminance",
        description="Light level",
        valid_units=["lx"],
        default_icon="mdi:brightness-5",
        state_class_allowed=True,
    ),
    "pm25": DeviceClassInfo(
        name="PM2.5",
        description="Particulate matter <= 2.5 μm",
        valid_units=["µg/m³"],
        default_icon="mdi:air-filter",
        state_class_allowed=True,
    ),
    "pm10": DeviceClassInfo(
        name="PM10",
        description="Particulate matter <= 10 μm",
        valid_units=["µg/m³"],
        default_icon="mdi:air-filter",
        state_class_allowed=True,
    ),
    "aqi": DeviceClassInfo(
        name="Air Quality Index",
        description="Air quality index",
        valid_units=[""],
        default_icon="mdi:air-filter",
        state_class_allowed=True,
    ),
    "carbon_dioxide": DeviceClassInfo(
        name="Carbon Dioxide",
        description="CO2 concentration",
        valid_units=["ppm"],
        default_icon="mdi:molecule-co2",
        state_class_allowed=True,
    ),
    "carbon_monoxide": DeviceClassInfo(
        name="Carbon Monoxide",
        description="CO concentration",
        valid_units=["ppm"],
        default_icon="mdi:molecule-co",
        state_class_allowed=True,
    ),
    # Distance & Speed
    "distance": DeviceClassInfo(
        name="Distance",
        description="Generic distance",
        valid_units=["km", "m", "cm", "mm", "mi", "yd", "in"],
        default_icon="mdi:arrow-left-right",
        state_class_allowed=True,
    ),
    "speed": DeviceClassInfo(
        name="Speed",
        description="Generic speed",
        valid_units=["m/s", "km/h", "mph", "mm/d", "in/d", "in/h"],
        default_icon="mdi:speedometer",
        state_class_allowed=True,
    ),
    # Data & Storage
    "data_rate": DeviceClassInfo(
        name="Data Rate",
        description="Data transfer rate",
        valid_units=[
            "bit/s",
            "kbit/s",
            "Mbit/s",
            "Gbit/s",
            "B/s",
            "kB/s",
            "MB/s",
            "GB/s",
        ],
        default_icon="mdi:transfer",
        state_class_allowed=True,
    ),
    "data_size": DeviceClassInfo(
        name="Data Size",
        description="Data storage size",
        valid_units=["bit", "kbit", "Mbit", "Gbit", "B", "kB", "MB", "GB", "TB", "PB"],
        default_icon="mdi:database",
        state_class_allowed=True,
    ),
    # Time & Duration
    "duration": DeviceClassInfo(
        name="Duration",
        description="Time duration",
        valid_units=["d", "h", "min", "s", "ms"],
        default_icon="mdi:progress-clock",
        state_class_allowed=True,
    ),
    "timestamp": DeviceClassInfo(
        name="Timestamp",
        description="Datetime object or timestamp string",
        valid_units=[""],
        default_icon="mdi:clock",
        state_class_allowed=False,  # Timestamps don't use state_class
    ),
    # Sound
    "sound_pressure": DeviceClassInfo(
        name="Sound Pressure",
        description="Sound pressure level",
        valid_units=["dB", "dBA"],
        default_icon="mdi:ear-hearing",
        state_class_allowed=True,
    ),
    # Weight & Volume
    "weight": DeviceClassInfo(
        name="Weight",
        description="Generic weight",
        valid_units=["kg", "g", "mg", "µg", "oz", "lb"],
        default_icon="mdi:weight",
        state_class_allowed=True,
    ),
    "volume": DeviceClassInfo(
        name="Volume",
        description="Generic volume",
        valid_units=["L", "mL", "gal", "fl. oz.", "m³", "ft³"],
        default_icon="mdi:cup-water",
        state_class_allowed=True,
    ),
    # Money
    "monetary": DeviceClassInfo(
        name="Monetary Value",
        description="Currency amount",
        valid_units=["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CNY", "INR"],
        default_icon="mdi:currency-usd",
        state_class_allowed=True,
    ),
    # Frequency
    "frequency": DeviceClassInfo(
        name="Frequency",
        description="Frequency measurement",
        valid_units=["Hz", "kHz", "MHz", "GHz"],
        default_icon="mdi:sine-wave",
        state_class_allowed=True,
    ),
    # Signal Strength
    "signal_strength": DeviceClassInfo(
        name="Signal Strength",
        description="Signal strength indication",
        valid_units=["dB", "dBm"],
        default_icon="mdi:wifi",
        state_class_allowed=True,
    ),
    # Generic/None
    "none": DeviceClassInfo(
        name="Generic Sensor",
        description="Generic sensor with no specific class",
        valid_units=[""],  # Any unit allowed
        default_icon="mdi:gauge",
        state_class_allowed=False,  # Text sensors should not have state_class
    ),
}


# Binary Sensor Device Classes
BINARY_SENSOR_DEVICE_CLASSES: Dict[str, DeviceClassInfo] = {
    "battery": DeviceClassInfo(
        name="Battery",
        description="On means low, Off means normal",
        valid_units=[],
        default_icon="mdi:battery",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "battery_charging": DeviceClassInfo(
        name="Battery Charging",
        description="On means charging, Off means not charging",
        valid_units=[],
        default_icon="mdi:battery-charging",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "carbon_monoxide": DeviceClassInfo(
        name="Carbon Monoxide",
        description="On means CO detected, Off means no CO",
        valid_units=[],
        default_icon="mdi:smoke-detector",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "cold": DeviceClassInfo(
        name="Cold",
        description="On means cold, Off means normal",
        valid_units=[],
        default_icon="mdi:snowflake",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "connectivity": DeviceClassInfo(
        name="Connectivity",
        description="On means connected, Off means disconnected",
        valid_units=[],
        default_icon="mdi:connection",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "door": DeviceClassInfo(
        name="Door",
        description="On means open, Off means closed",
        valid_units=[],
        default_icon="mdi:door",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "garage_door": DeviceClassInfo(
        name="Garage Door",
        description="On means open, Off means closed",
        valid_units=[],
        default_icon="mdi:garage",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "gas": DeviceClassInfo(
        name="Gas",
        description="On means gas detected, Off means no gas",
        valid_units=[],
        default_icon="mdi:gas-cylinder",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "heat": DeviceClassInfo(
        name="Heat",
        description="On means hot, Off means normal",
        valid_units=[],
        default_icon="mdi:fire",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "light": DeviceClassInfo(
        name="Light",
        description="On means light detected, Off means no light",
        valid_units=[],
        default_icon="mdi:brightness-5",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "lock": DeviceClassInfo(
        name="Lock",
        description="On means unlocked, Off means locked",
        valid_units=[],
        default_icon="mdi:lock",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "moisture": DeviceClassInfo(
        name="Moisture",
        description="On means moisture detected, Off means dry",
        valid_units=[],
        default_icon="mdi:water",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "motion": DeviceClassInfo(
        name="Motion",
        description="On means motion detected, Off means no motion",
        valid_units=[],
        default_icon="mdi:motion-sensor",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "moving": DeviceClassInfo(
        name="Moving",
        description="On means moving, Off means stationary",
        valid_units=[],
        default_icon="mdi:axis-arrow",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "occupancy": DeviceClassInfo(
        name="Occupancy",
        description="On means occupied, Off means not occupied",
        valid_units=[],
        default_icon="mdi:home-account",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "opening": DeviceClassInfo(
        name="Opening",
        description="On means open, Off means closed",
        valid_units=[],
        default_icon="mdi:square",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "plug": DeviceClassInfo(
        name="Plug",
        description="On means plugged in, Off means unplugged",
        valid_units=[],
        default_icon="mdi:power-plug",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "power": DeviceClassInfo(
        name="Power",
        description="On means powered, Off means no power",
        valid_units=[],
        default_icon="mdi:power",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "presence": DeviceClassInfo(
        name="Presence",
        description="On means home, Off means away",
        valid_units=[],
        default_icon="mdi:home",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "problem": DeviceClassInfo(
        name="Problem",
        description="On means problem detected, Off means OK",
        valid_units=[],
        default_icon="mdi:alert-circle",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "running": DeviceClassInfo(
        name="Running",
        description="On means running, Off means not running",
        valid_units=[],
        default_icon="mdi:run",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "safety": DeviceClassInfo(
        name="Safety",
        description="On means unsafe, Off means safe",
        valid_units=[],
        default_icon="mdi:shield-check",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "smoke": DeviceClassInfo(
        name="Smoke",
        description="On means smoke detected, Off means no smoke",
        valid_units=[],
        default_icon="mdi:smoke-detector",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "sound": DeviceClassInfo(
        name="Sound",
        description="On means sound detected, Off means no sound",
        valid_units=[],
        default_icon="mdi:music-note",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "tamper": DeviceClassInfo(
        name="Tamper",
        description="On means tampering detected, Off means no tampering",
        valid_units=[],
        default_icon="mdi:shield-alert",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "update": DeviceClassInfo(
        name="Update",
        description="On means update available, Off means up-to-date",
        valid_units=[],
        default_icon="mdi:package-up",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "vibration": DeviceClassInfo(
        name="Vibration",
        description="On means vibration detected, Off means no vibration",
        valid_units=[],
        default_icon="mdi:vibrate",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
    "window": DeviceClassInfo(
        name="Window",
        description="On means open, Off means closed",
        valid_units=[],
        default_icon="mdi:window-open",
        state_class_allowed=False,
        sensor_type="binary_sensor",
    ),
}


# State Class Options
STATE_CLASSES = {
    "measurement": "For values that are measured and can fluctuate (e.g., temperature, power)",
    "total": "For monotonically increasing values (e.g., energy consumed, data transferred)",
    "total_increasing": "For monotonically increasing values that can be reset (e.g., daily energy)",
    "none": "No state class (for text sensors or when statistical tracking is not needed)",
}


def get_device_class_info(
    device_class: str, sensor_type: str = "sensor"
) -> Optional[DeviceClassInfo]:
    """Get device class metadata"""
    if sensor_type == "binary_sensor":
        return BINARY_SENSOR_DEVICE_CLASSES.get(device_class)
    else:
        return SENSOR_DEVICE_CLASSES.get(device_class)


def get_valid_units(device_class: str, sensor_type: str = "sensor") -> List[str]:
    """Get valid units for a device class"""
    info = get_device_class_info(device_class, sensor_type)
    return info.valid_units if info else []


def get_default_icon(device_class: str, sensor_type: str = "sensor") -> str:
    """Get default icon for a device class"""
    info = get_device_class_info(device_class, sensor_type)
    return info.default_icon if info else "mdi:gauge"


def can_use_state_class(device_class: str, sensor_type: str = "sensor") -> bool:
    """Check if state_class is allowed for this device class"""
    info = get_device_class_info(device_class, sensor_type)
    return info.state_class_allowed if info else False


def validate_unit_for_device_class(
    device_class: str, unit: str, sensor_type: str = "sensor"
) -> bool:
    """
    Validate if a unit is valid for a device class.
    Returns True if valid, False if invalid.
    For device_class="none", any unit is allowed.
    """
    if device_class == "none":
        return True  # Any unit allowed for generic sensors

    valid_units = get_valid_units(device_class, sensor_type)
    if not valid_units:
        return True  # If no valid units defined, allow any

    # Empty string in valid_units means "no unit required"
    if "" in valid_units and not unit:
        return True

    return unit in valid_units


def get_all_sensor_device_classes() -> List[str]:
    """Get list of all sensor device classes"""
    return list(SENSOR_DEVICE_CLASSES.keys())


def get_all_binary_sensor_device_classes() -> List[str]:
    """Get list of all binary sensor device classes"""
    return list(BINARY_SENSOR_DEVICE_CLASSES.keys())


def export_to_json() -> dict:
    """Export device class reference to JSON-serializable format"""
    return {
        "sensor_types": [
            {
                "value": "sensor",
                "name": "Sensor",
                "description": "Numeric or text sensor with optional unit of measurement",
            },
            {
                "value": "binary_sensor",
                "name": "Binary Sensor",
                "description": "On/Off or True/False sensor (e.g., door, motion, connectivity)",
            },
        ],
        "sensor_device_classes": {
            key: {
                "name": val.name,
                "description": val.description,
                "valid_units": val.valid_units,
                "default_icon": val.default_icon,
                "state_class_allowed": val.state_class_allowed,
            }
            for key, val in SENSOR_DEVICE_CLASSES.items()
        },
        "binary_sensor_device_classes": {
            key: {
                "name": val.name,
                "description": val.description,
                "default_icon": val.default_icon,
                "state_class_allowed": val.state_class_allowed,
            }
            for key, val in BINARY_SENSOR_DEVICE_CLASSES.items()
        },
        "state_classes": STATE_CLASSES,
    }
