# Home Assistant Integration Roadmap

**Phase 6: HA Add-on Packaging & Metadata Integration**

## Overview
When Visual Mapper becomes a Home Assistant add-on, we'll integrate with HA's metadata APIs to provide smart suggestions and validation.

## HA Metadata Integration Features

### 1. Device Class Auto-Suggestions
**Current:** Hardcoded dropdown in sensor-creator.js
**Future:** Fetch from HA's device class registry

```javascript
// Fetch available device classes from HA
const deviceClasses = await fetch('/api/device_classes').then(r => r.json());
// Returns: { sensor: ['battery', 'temperature', ...], binary_sensor: ['door', 'motion', ...] }
```

**Benefits:**
- Always up-to-date with latest HA device classes
- No need to maintain hardcoded lists
- Supports custom device classes from integrations

### 2. Icon Suggestions Based on Device Class
**Current:** User manually types MDI icon
**Future:** Auto-suggest icons based on selected device class

```javascript
const iconMap = {
    battery: 'mdi:battery',
    temperature: 'mdi:thermometer',
    humidity: 'mdi:water-percent',
    power: 'mdi:flash',
    // ... fetched from HA
};
```

**Benefits:**
- Consistent iconography with HA
- Less typing for users
- Visual preview of icon in dropdown

### 3. Unit of Measurement Suggestions
**Current:** Free-text input with placeholder examples
**Future:** Dropdown with device-class-appropriate units

```javascript
const unitMap = {
    battery: ['%'],
    temperature: ['°C', '°F', 'K'],
    speed: ['km/h', 'mph', 'm/s'],
    distance: ['m', 'km', 'mi', 'ft'],
    // ... fetched from HA
};
```

**Benefits:**
- Standardized units across HA
- Prevents typos
- Still allows custom units for edge cases

### 4. State Class Recommendations
**Current:** Hardcoded to "measurement"
**Future:** Suggest appropriate state_class based on device_class

```javascript
const stateClassMap = {
    energy: 'total_increasing',
    battery: 'measurement',
    timestamp: 'measurement',
    // ...
};
```

## Implementation Plan

### Step 1: Create HA API Client Module
```javascript
// www/js/modules/ha-api-client.js
class HomeAssistantAPIClient {
    async getDeviceClasses() { }
    async getIconSuggestions(deviceClass) { }
    async getUnitSuggestions(deviceClass) { }
    async getStateClassSuggestion(deviceClass) { }
}
```

### Step 2: Update sensor-creator.js
- Replace hardcoded device classes with HA API calls
- Add icon picker with auto-suggestions
- Add unit dropdown with custom input option
- Auto-set state_class based on device_class

### Step 3: Add HA Ingress Support
- Detect if running as HA add-on
- Use HA's authentication
- Respect HA's API base URL

### Step 4: Add Validation
- Validate sensor configs against HA's schema
- Warn about deprecated device classes
- Suggest migrations for old configs

## Compatibility

**Standalone Mode (Current):**
- Continue to work without HA
- Use hardcoded fallbacks
- Manual input for all fields

**HA Add-on Mode (Future):**
- Auto-detect HA environment
- Fetch metadata from HA APIs
- Smart suggestions & validation

## Future Enhancements

1. **Entity Preview:** Show how sensor will appear in HA before creating
2. **Template Testing:** Test Jinja2 templates against sample data
3. **Entity Categories:** Group sensors by category (diagnostic, config, etc.)
4. **Area Assignment:** Assign sensors to HA areas/floors
5. **Custom Component Integration:** Register as custom component for deeper integration

---

**Status:** Planned for Phase 6 (v0.1.0)
**Priority:** High
**Dependencies:** HA Add-on packaging completed
