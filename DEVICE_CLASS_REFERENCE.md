# Home Assistant Device Class Reference System

## Overview

Visual Mapper now includes a comprehensive local reference for Home Assistant device classes, units, and icons. This eliminates the need to pull this data from Home Assistant's API and works in both standalone and add-on modes.

## Files

### `ha_device_classes.py`

Contains complete definitions for:
- **28 sensor device classes** (battery, temperature, humidity, power, etc.)
- **28 binary sensor device classes** (door, motion, occupancy, etc.)
- **Valid units** for each device class
- **Default icons** (Material Design Icons)
- **State class compatibility** rules

### API Endpoint: `/api/device-classes`

Returns JSON with all device class metadata:
```json
{
  "sensor_device_classes": {
    "battery": {
      "name": "Battery",
      "description": "Percentage of battery that is left",
      "valid_units": ["%"],
      "default_icon": "mdi:battery",
      "state_class_allowed": true
    },
    "temperature": {
      "name": "Temperature",
      "description": "Temperature measurement",
      "valid_units": ["°C", "°F", "K"],
      "default_icon": "mdi:thermometer",
      "state_class_allowed": true
    },
    ...
  },
  "binary_sensor_device_classes": {
    "door": {
      "name": "Door",
      "description": "On means open, Off means closed",
      "default_icon": "mdi:door",
      "state_class_allowed": false
    },
    ...
  },
  "state_classes": {
    "measurement": "For values that are measured and can fluctuate",
    "total": "For monotonically increasing values",
    ...
  }
}
```

## Usage

### Backend Validation

The validation function in `server.py` now uses the device class reference:

```python
from ha_device_classes import (
    validate_unit_for_device_class,
    can_use_state_class,
    get_device_class_info
)

def validate_sensor_config(sensor: SensorDefinition) -> Optional[str]:
    # Rule: Check if state_class is allowed for this device class
    if sensor.state_class and sensor.state_class != "none":
        if not can_use_state_class(sensor.device_class, sensor.sensor_type):
            return "Device class does not support state_class"

    # Rule: Validate unit matches device class expectations
    if not validate_unit_for_device_class(sensor.device_class, sensor.unit, sensor.sensor_type):
        device_info = get_device_class_info(sensor.device_class, sensor.sensor_type)
        return f"Expected units: {device_info.valid_units}"
```

### Frontend Usage (Planned)

The frontend can fetch device classes and use them for:

1. **Dropdown Options**: Populate device class dropdowns with all available options
2. **Unit Suggestions**: Show valid units based on selected device class
3. **Icon Previews**: Display default icon for each device class
4. **Validation**: Client-side validation before submitting sensor config
5. **Auto-Complete**: Suggest appropriate device class based on sensor name

Example frontend code:
```javascript
// Fetch device classes on page load
const deviceClasses = await fetch('/api/device-classes').then(r => r.json());

// Populate dropdown
const sensorClasses = deviceClasses.sensor_device_classes;
for (const [key, info] of Object.entries(sensorClasses)) {
  console.log(`${info.name}: ${info.description}`);
  console.log(`Valid units: ${info.valid_units.join(', ')}`);
  console.log(`Icon: ${info.default_icon}`);
}

// When user selects a device class, show valid units
function onDeviceClassChange(deviceClass) {
  const info = sensorClasses[deviceClass];
  if (info) {
    // Update unit dropdown to only show valid units
    updateUnitDropdown(info.valid_units);
    // Show icon preview
    showIconPreview(info.default_icon);
    // Enable/disable state_class based on compatibility
    stateClassField.disabled = !info.state_class_allowed;
  }
}
```

## Sensor Device Classes Included

### Energy & Power
- battery, power, energy, voltage, current, power_factor

### Environmental
- temperature, humidity, pressure, illuminance, pm25, pm10, aqi, carbon_dioxide, carbon_monoxide

### Distance & Speed
- distance, speed

### Data & Storage
- data_rate, data_size

### Time
- duration, timestamp

### Other
- sound_pressure, weight, volume, monetary, frequency, signal_strength, none (generic)

## Binary Sensor Device Classes Included

- battery, battery_charging, carbon_monoxide, cold, connectivity
- door, garage_door, gas, heat, light, lock
- moisture, motion, moving, occupancy, opening
- plug, power, presence, problem, running, safety
- smoke, sound, tamper, update, vibration, window

## Validation Rules

The reference enforces these rules:

1. **Binary sensors** cannot have `state_class`
2. **Text sensors** (device_class="none") cannot have `state_class`
3. **Measurement sensors** must have `unit_of_measurement`
4. **Device class units** must match expected values (e.g., battery must use "%")
5. **Friendly name** cannot be empty

## Why Local Reference Instead of HA API?

### Advantages of Local Reference:
✅ Works in standalone mode (no HA connection required)
✅ Works in add-on mode without extra API calls
✅ No network latency
✅ Consistent behavior across environments
✅ Easier to test and validate
✅ Can be updated independently of HA version

### Disadvantages of HA API Approach:
❌ Requires HA connection (doesn't work standalone)
❌ May require add-on mode with special permissions
❌ Network latency for each request
❌ Dependent on HA version and API changes
❌ More complex error handling

## Maintenance

To update the device class reference:

1. Check [Home Assistant Device Class Documentation](https://www.home-assistant.io/integrations/sensor/#device-class)
2. Update `ha_device_classes.py` with new device classes or units
3. Test validation with new device classes
4. Frontend will automatically pick up changes via `/api/device-classes` endpoint

## Future Enhancements

Potential improvements:
- Add device class categories/groups for better UI organization
- Include example sensor names for each device class
- Add support for custom device classes
- Include state value suggestions (e.g., binary sensor states)
- Add unit conversion helpers
- Include value range validation (e.g., battery 0-100%)

---

**Last Updated**: 2025-12-23
**Based on**: Home Assistant 2025.1 Device Classes
