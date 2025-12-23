# Home Assistant Add-on: Visual Mapper

Monitor and control Android devices from Home Assistant using ADB. Create sensors from UI elements, automate device interactions, and integrate Android screens into your smart home.

![Visual Mapper Banner](https://via.placeholder.com/800x200?text=Visual+Mapper)

## About

Visual Mapper turns any Android device into a rich source of Home Assistant sensors and automation triggers. Perfect for:

- **Tablets mounted as dashboards**: Monitor battery, detect screen content, automate based on displayed apps
- **Android TVs**: Track what's playing, control apps, detect idle screens
- **Phones**: Monitor notifications, battery health, app usage
- **E-readers**: Detect current book/page, automate reading lights
- **Smart displays**: Extract weather data, calendar events, custom data from any app

## Features

### Device Control via ADB
- **Screenshot Capture**: High-speed screenshots with UI element detection
- **Device Interaction**: Tap, swipe, type text remotely
- **App Management**: Launch apps, switch between apps
- **Hardware Keys**: Home, Back, Recent Apps, Volume control
- **Wireless ADB**: Android 11+ wireless debugging support

### Sensor Creation
- **Visual Sensor Builder**: Click UI elements on screenshots to create sensors
- **Text Extraction**: Parse text from any on-screen element
- **Extraction Rules**: Regex patterns, numeric extraction, before/after parsing
- **Multiple Sensor Types**: Regular sensors (numeric/text) and binary sensors
- **Device Classes**: Battery, temperature, humidity, and 50+ Home Assistant device classes
- **MQTT Auto-Discovery**: Sensors appear automatically in Home Assistant

### Real-Time Updates
- **Configurable Intervals**: Update sensors every 5-3600 seconds
- **Background Processing**: Efficient screenshot + extraction pipeline
- **Availability Tracking**: Sensor shows unavailable if device disconnects
- **Error Handling**: Graceful degradation when extraction fails

### Web Interface
- **Device Management**: View connected devices, pair new ones
- **Screenshot View**: Live device screen with interactive overlays
- **Sensor Management**: Create, edit, enable/disable sensors
- **Testing Tools**: Preview sensor extractions before saving

## Installation

### Requirements

1. **MQTT Broker**: Install the Mosquitto broker add-on
   - Go to **Settings** → **Add-ons** → **Add-on Store**
   - Search for "Mosquitto broker" and install it
   - Start the add-on

2. **Android Device with ADB enabled**:
   - Go to **Settings** → **About Phone** → Tap **Build number** 7 times
   - Go to **Settings** → **Developer options** → Enable **USB debugging**
   - For wireless: Enable **Wireless debugging** (Android 11+)

### Add-on Installation

1. Add this repository to your Home Assistant add-on store
2. Install the "Visual Mapper" add-on
3. Configure the add-on (see Configuration section)
4. Start the add-on
5. Open the Web UI from the sidebar

## Configuration

### Basic Configuration

```yaml
adb_device_ip: ""  # Leave empty to pair via UI
adb_device_port: 5555
mqtt_broker: "core-mosquitto"
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
mqtt_discovery_prefix: "homeassistant"
auto_start_updates: true
log_level: info
```

### Configuration Options

#### `adb_device_ip` (optional)
IP address of your Android device. Leave empty to pair devices via the Web UI.

**Example**: `192.168.1.100`

####  `adb_device_port` (default: 5555)
Port for ADB wireless debugging.

#### `mqtt_broker` (required)
MQTT broker address. Use `core-mosquitto` for the Home Assistant Mosquitto add-on.

#### `mqtt_port` (default: 1883)
MQTT broker port (1883 for unencrypted, 8883 for TLS).

#### `mqtt_username` (optional)
MQTT authentication username. Leave empty if not using authentication.

#### `mqtt_password` (optional)
MQTT authentication password.

#### `mqtt_discovery_prefix` (default: "homeassistant")
MQTT discovery prefix. Only change if you've modified Home Assistant's discovery prefix.

#### `auto_start_updates` (default: true)
Automatically start publishing sensor updates when the add-on starts. Disable to manually control updates via the UI.

#### `log_level` (default: "info")
Logging level: `debug`, `info`, `warning`, `error`

## Usage

### 1. Connect Your Android Device

#### USB Connection
1. Connect your Android device via USB
2. Open Visual Mapper Web UI
3. Device should appear automatically

#### Wireless Connection (Android 11+)
1. On your Android device:
   - Go to **Developer Options** → **Wireless debugging**
   - Tap **Pair device with pairing code**
   - Note the pairing code, IP address, and port

2. In Visual Mapper Web UI:
   - Go to **Devices** page
   - Click **Pair Wireless Device**
   - Enter IP, port, and pairing code
   - Device will connect automatically

### 2. Create Sensors

1. **Capture Screenshot**:
   - Open the **Devices** page
   - Select your device
   - Click **Capture Screenshot**

2. **Select Element**:
   - Click **Sensor** mode
   - Hover over UI elements (they'll highlight)
   - Click the element you want to monitor

3. **Configure Sensor**:
   - **Name**: Friendly name (e.g., "Battery Level")
   - **Sensor Type**: Sensor or Binary Sensor
   - **Device Class**: Battery, temperature, etc.
   - **Update Interval**: How often to refresh (5-3600 seconds)
   - **Extraction Rules**:
     - **Regex**: Extract text matching pattern (e.g., `(\d+)%` for "94%")
     - **Extract Number**: Convert "94%" → 94
     - **Before/After**: Extract text before/after a substring

4. **Test & Save**:
   - Live preview shows extracted value
   - Click **Create Sensor**
   - Sensor appears in Home Assistant within 60 seconds

### 3. Manage Sensors

- **Sensors Page**: View all sensors, search by name/device
- **Enable/Disable**: Toggle sensors on/off
- **Delete**: Remove sensors (also removes from Home Assistant)
- **Edit**: Modify sensor configuration (coming soon)

### 4. Device Interaction

- **Tap Mode**: Click anywhere on the screenshot to tap device
- **Swipe Mode**: Drag to perform swipe gestures
- **Text Input**: Type text into focused fields
- **Hardware Keys**: Home, Back, Recent Apps, Volume Up/Down
- **Launch Apps**: Quick app launcher

## Examples

### Example 1: Tablet Battery Monitor

Monitor a wall-mounted tablet's battery level and charging state.

1. Capture screenshot showing battery icon (e.g., Settings → Battery)
2. Create sensor:
   - **Name**: "Tablet Battery"
   - **Device Class**: Battery
   - **Unit**: %
   - **Extraction**: Regex `(\d+)%`, Extract Number: Yes
3. Create binary sensor:
   - **Name**: "Tablet Charging"
   - **Device Class**: Battery Charging
   - **Extraction**: Regex `Charging|充电` (matches "Charging" text)

**Automation**:
```yaml
- alias: "Notify when tablet battery low"
  trigger:
    - platform: numeric_state
      entity_id: sensor.tablet_battery
      below: 20
  action:
    - service: notify.mobile_app
      data:
        message: "Wall tablet battery is low ({{ states('sensor.tablet_battery') }}%)"
```

### Example 2: Android TV Current App

Detect what app is currently running on Android TV.

1. Capture screenshot (any screen)
2. Visual Mapper automatically extracts active app from UI hierarchy
3. Create sensor:
   - **Name**: "TV Current App"
   - **Device Class**: None (text sensor)
   - **Extraction**: From element metadata (package name)

**Automation**:
```yaml
- alias: "Dim lights when Netflix is playing"
  trigger:
    - platform: state
      entity_id: sensor.tv_current_app
      to: "com.netflix.ninja"
  action:
    - service: light.turn_on
      target:
        entity_id: light.living_room
      data:
        brightness: 30
```

### Example 3: Weather Display Scraping

Extract temperature from a weather app display.

1. Open weather app showing current temperature
2. Capture screenshot
3. Create sensor:
   - **Name**: "Weather App Temperature"
   - **Device Class**: Temperature
   - **Unit**: °C
   - **Extraction**: Regex `(\d+)°`, Extract Number: Yes

### Example 4: Notification Counter

Count unread notifications from an app.

1. Capture screenshot showing notification badge (e.g., "5" on Messages icon)
2. Create sensor:
   - **Name**: "Unread Messages"
   - **Extraction**: Regex `(\d+)`, Extract Number: Yes

**Automation**:
```yaml
- alias: "Flash light when new message arrives"
  trigger:
    - platform: state
      entity_id: sensor.unread_messages
  condition:
    - condition: template
      value_template: "{{ trigger.to_state.state | int > trigger.from_state.state | int }}"
  action:
    - service: light.turn_on
      target:
        entity_id: light.notification_led
      data:
        flash: short
```

## Troubleshooting

### Device Not Detected

**USB Connection**:
- Ensure USB debugging is enabled on the device
- Check that the device is properly connected
- Try a different USB cable
- Accept the "Allow USB debugging" prompt on the device

**Wireless Connection**:
- Ensure device and Home Assistant are on the same network
- Check that wireless debugging is enabled
- Verify the IP address and port are correct
- Try pairing again with a fresh pairing code

### Sensors Not Appearing in Home Assistant

1. Check MQTT broker is running:
   - Go to **Settings** → **Add-ons** → **Mosquitto broker**
   - Ensure status is "Started"

2. Check MQTT integration is configured:
   - Go to **Settings** → **Devices & Services** → **MQTT**
   - Should show "Configured"
   - Enable MQTT discovery if disabled

3. Check sensor updates are running:
   - Open Visual Mapper Web UI
   - Go to **Sensors** page
   - Check "MQTT Status" shows "Running"

4. Check logs:
   - Go to **Settings** → **Add-ons** → **Visual Mapper** → **Log**
   - Look for MQTT connection errors

### Sensor Shows "Unavailable"

- Device is disconnected or powered off
- ADB connection lost (try reconnecting)
- Screenshot capture is failing
- Check logs for extraction errors

### Extraction Returns Wrong Value

1. **Check Live Preview**:
   - Edit sensor
   - Live preview shows what will be extracted
   - Adjust regex pattern until preview is correct

2. **Common Patterns**:
   - Extract number from "94%": `(\d+)%` with "Extract Number" enabled
   - Extract word before colon: `(.+?):`
   - Extract between quotes: `"(.+?)"`

3. **Test regex** at [regex101.com](https://regex101.com)

### Screenshots Are Slow

- Reduce screenshot resolution in device settings (if supported)
- Increase update intervals for sensors
- Use fewer sensors per device
- Check network speed (for wireless ADB)

## Support

- **Documentation**: [GitHub Wiki](https://github.com/yourusername/visual-mapper/wiki)
- **Issues**: [GitHub Issues](https://github.com/yourusername/visual-mapper/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/visual-mapper/discussions)
- **Home Assistant Community**: [Community Forum Thread](https://community.home-assistant.io)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

MIT License - See [LICENSE](LICENSE) for details.
