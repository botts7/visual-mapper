# Visual Mapper - User Guide

**Version:** 0.0.5
**Last Updated:** 2025-12-23
**For:** End Users & Home Assistant Enthusiasts

---

## 📖 Table of Contents

1. [What is Visual Mapper?](#what-is-visual-mapper)
2. [Getting Started](#getting-started)
3. [Device Management](#device-management)
4. [Creating Sensors](#creating-sensors)
5. [Creating Actions](#creating-actions)
6. [Home Assistant Integration](#home-assistant-integration)
7. [Troubleshooting](#troubleshooting)
8. [FAQ](#faq)
9. [Known Limitations](#known-limitations)

---

## What is Visual Mapper?

Visual Mapper turns any Android device into a **smart sensor and automation endpoint** for Home Assistant.

### What Can You Do?

**Extract Data (Sensors):**
- Monitor battery level, WiFi status, or any on-screen text
- Track app notifications (weather, delivery status, etc.)
- Read data from apps without APIs (smart thermostat readings, security camera status)

**Control Devices (Actions):**
- Tap buttons in apps automatically
- Type text, swipe gestures
- Launch apps, navigate screens
- Create multi-step automation sequences

**Real-World Examples:**
- ✅ Read room temperature from a smart thermostat app
- ✅ Extract "Now Playing" song from Spotify
- ✅ Monitor delivery notifications
- ✅ Automate tap sequences (e.g., "Unlock door" button in security app)
- ✅ Type messages or search queries
- ✅ Control smart home devices through their manufacturer apps

---

## Getting Started

### Prerequisites

1. **Home Assistant** installed and running
2. **MQTT Broker** (Mosquitto add-on recommended)
3. **Android Device** with:
   - USB debugging enabled
   - Connected to same network as Home Assistant
   - ADB over WiFi enabled (optional, but recommended)

### Installation

#### Option 1: Home Assistant Add-on (Recommended)

1. Open Home Assistant → Settings → Add-ons → Add-on Store
2. Click ⋮ (three dots) → Repositories
3. Add repository URL: `https://github.com/YOUR_USERNAME/visual-mapper-addon`
4. Install "Visual Mapper" add-on
5. Configure MQTT settings in add-on configuration
6. Start the add-on

#### Option 2: Docker (Advanced)

```bash
docker run -d \
  --name visual-mapper \
  --network host \
  -e MQTT_BROKER=192.168.1.100 \
  -e MQTT_PORT=1883 \
  -e MQTT_USER=your_user \
  -e MQTT_PASSWORD=your_password \
  -v /path/to/config:/app/config \
  visual-mapper:latest
```

#### Option 3: Standalone Python (Developers)

```bash
git clone https://github.com/YOUR_USERNAME/visual-mapper.git
cd visual-mapper
pip install -r requirements.txt
python server.py
```

### Enable ADB on Android

1. Open **Settings** on Android device
2. Go to **About Phone** → Tap **Build Number** 7 times
3. Go back → **Developer Options** → Enable **USB Debugging**
4. Connect device to computer via USB
5. Accept the "Allow USB Debugging" prompt on device

### Enable ADB over WiFi (Recommended)

**Method 1: Using USB First**
```bash
# Connect device via USB first
adb tcpip 5555
adb connect <DEVICE_IP>:5555
# Now you can disconnect USB cable
```

**Method 2: Using Wireless ADB (Android 11+)**
1. Settings → Developer Options → Wireless Debugging
2. Enable Wireless Debugging
3. Tap "Pair device with pairing code"
4. Note the IP address and port

---

## Device Management

### Connecting Your First Device

1. **Open Visual Mapper UI:**
   - Home Assistant Add-on: Click "Open Web UI" in add-on page
   - Standalone: Navigate to `http://localhost:3000`

2. **Navigate to Devices Page:**
   - Click "Devices" in the sidebar

3. **Connect Device:**
   - **Option A: Auto-Discovery** (if on same network)
     - Wait for device to appear in "Discovered Devices"
     - Click "Connect"

   - **Option B: Manual Connection**
     - Click "Add Device Manually"
     - Enter device IP address (e.g., `192.168.1.100:5555`)
     - Click "Connect"

4. **Verify Connection:**
   - Device card should show "Connected" status (green)
   - Screenshot should appear automatically
   - Device info should populate (model, Android version, battery)

### Device Status Indicators

| Status | Meaning |
|--------|---------|
| 🟢 Connected | Device is reachable and responsive |
| 🟡 Connecting | Attempting to establish connection |
| 🔴 Disconnected | Device is offline or unreachable |
| ⚠️ Error | Connection error (check logs) |

### Multi-Device Support

Visual Mapper supports **unlimited devices** simultaneously:
- Each device has its own sensors and actions
- Switch between devices using the device selector dropdown
- All devices update in background independently

---

## Creating Sensors

Sensors extract data from your Android device screen and publish it to Home Assistant.

### Step-by-Step: Create a Battery Sensor

**1. Navigate to Sensors Page**
- Click "Sensors" in sidebar
- Select your device from dropdown

**2. Capture Screenshot**
- Ensure battery percentage is visible on screen
- Click "Capture Screenshot" button
- Screenshot appears in viewer

**3. Define Sensor Bounds**
- Click "Enable Draw Mode" button (turns purple)
- Click and drag a rectangle around the battery percentage text
- Make sure the box tightly fits the text
- Click "Disable Draw Mode" when done

**4. Configure Sensor**
- **Name:** `Battery Percentage` (required)
- **Extraction Method:** Select `text` (for plain text extraction)
- **Device Class:** Select `battery` (optional, for HA icon)
- **Unit of Measurement:** `%` (optional)
- **Update Interval:** `60` seconds (how often to refresh)
- **Unique ID:** Auto-generated (leave default)

**5. Preview Extraction**
- Click "Preview Extraction" button
- Verify the extracted value matches what you see on screen
- If not, adjust the bounding box or try a different extraction method

**6. Create Sensor**
- Click "Create Sensor" button
- Sensor is saved and starts updating automatically
- Check Home Assistant → Developer Tools → States to see the new sensor

### Extraction Methods

Visual Mapper supports multiple text extraction engines:

| Method | Best For | Example |
|--------|----------|---------|
| **text** | Plain text, numbers | `Battery: 85%` → `85%` |
| **ocr_tesseract** | Complex fonts, small text | Handwritten notes |
| **regex** | Pattern matching | Extract numbers only: `\d+` |
| **before** | Text before a delimiter | `Battery: 85%` → `85` (before `%`) |
| **after** | Text after a delimiter | `Temp: 72°F` → `72°F` (after `:`) |
| **between** | Text between two strings | `[Status: OK]` → `OK` (between `[` and `]`) |

### Advanced: Multi-Step Extraction Pipeline

For complex extractions, use a pipeline:

```json
{
  "extraction_method": "pipeline",
  "extraction_config": {
    "steps": [
      {"method": "text"},
      {"method": "after", "delimiter": ":"},
      {"method": "before", "delimiter": "%"},
      {"method": "regex", "pattern": "\\d+"}
    ]
  }
}
```

**Example:**
Input: `Battery Level: 85% Charged`
→ Step 1 (text): `Battery Level: 85% Charged`
→ Step 2 (after `:`): `85% Charged`
→ Step 3 (before `%`): `85`
→ Step 4 (regex `\d+`): `85`

### Sensor Management

**Edit Sensor:**
1. Go to Sensors page
2. Find sensor in list
3. Click "✏️ Edit" button
4. Modify settings
5. Click "Update Sensor"

**Delete Sensor:**
1. Go to Sensors page
2. Find sensor in list
3. Click "🗑 Delete" button
4. Confirm deletion

**Enable/Disable Sensor:**
1. Go to Sensors page
2. Toggle the switch next to sensor name
3. Disabled sensors won't update (saves battery)

---

## Creating Actions

Actions send commands to your Android device (taps, swipes, text input, etc.).

### Step-by-Step: Create a "Play Music" Button

**1. Navigate to Actions Page**
- Click "Actions" in sidebar
- Select your device from dropdown

**2. Capture Screenshot**
- Open the music app on your device
- Ensure the "Play" button is visible
- Click "Capture Screenshot" in Visual Mapper

**3. Define Action Target**
- Click "Enable Draw Mode"
- Click on the "Play" button location
- Note the coordinates (shown in status bar)

**4. Configure Action**
- **Action Type:** Select `tap`
- **Name:** `Play Music` (required)
- **Description:** `Tap the play button in Spotify` (optional)
- **Coordinates:** Auto-filled from your click
- **Enabled:** Check the box

**5. Test Action**
- Click "Test Action" button
- Verify the action executes on device
- If wrong, adjust coordinates or action type

**6. Save Action**
- Click "Create Action" button
- Action is saved and published to Home Assistant as a button entity

### Action Types

| Type | Description | Parameters |
|------|-------------|------------|
| **tap** | Single tap at coordinates | `x`, `y` |
| **long_press** | Long press (hold) | `x`, `y`, `duration` (ms) |
| **swipe** | Swipe gesture | `start_x`, `start_y`, `end_x`, `end_y`, `duration` |
| **text** | Type text | `text` |
| **keyevent** | Press hardware key | `keycode` (e.g., `KEYCODE_HOME`) |
| **launch_app** | Open app by package | `package` (e.g., `com.spotify.music`) |
| **delay** | Wait before next action | `duration` (ms) |
| **macro** | Multi-step sequence | `steps` (array of actions) |

### Creating a Macro (Multi-Step Action)

Macros combine multiple actions into a sequence:

**Example: "Open Spotify and Play Music"**

```json
{
  "action_type": "macro",
  "name": "Open Spotify and Play",
  "steps": [
    {
      "action_type": "launch_app",
      "package": "com.spotify.music"
    },
    {
      "action_type": "delay",
      "duration": 2000
    },
    {
      "action_type": "tap",
      "x": 540,
      "y": 1200
    }
  ]
}
```

**How to Create:**
1. Go to Actions page
2. Click "Create Macro" button
3. Add action steps one by one
4. Test each step individually
5. Save macro

### Action Management

**Execute Action Manually:**
- Go to Actions page
- Click "▶ Execute" button next to action
- Action runs immediately

**Edit Action:**
- Click "✏️ Edit" button
- Modify settings (currently basic prompts, advanced UI coming in Phase 9)
- Save changes

**Delete Action:**
- Click "🗑 Delete" button
- Confirm deletion

---

## Home Assistant Integration

### MQTT Discovery

Visual Mapper uses **MQTT Discovery** to automatically register sensors and actions with Home Assistant.

**Prerequisites:**
1. MQTT broker running (Mosquitto add-on)
2. MQTT integration enabled in HA
3. Discovery enabled in MQTT integration settings

**Sensor Discovery:**
- Sensors appear in: **Settings → Devices & Services → MQTT**
- Entity ID format: `sensor.visual_mapper_{device}_{sensor_name}`
- Device: `Visual Mapper {device_id}`

**Action Discovery:**
- Actions appear as **Button entities** in HA
- Entity ID format: `button.visual_mapper_{device}_{action_name}`
- Press button in HA → Action executes on device

### Using Sensors in Automations

**Example: Low Battery Alert**

```yaml
automation:
  - alias: "Tablet Low Battery Alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.visual_mapper_tablet_battery
        below: 20
    action:
      - service: notify.mobile_app
        data:
          message: "Tablet battery is low ({{ states('sensor.visual_mapper_tablet_battery') }}%)"
```

**Example: Temperature Monitoring**

```yaml
automation:
  - alias: "Room Too Hot"
    trigger:
      - platform: numeric_state
        entity_id: sensor.visual_mapper_thermostat_temperature
        above: 78
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room
        data:
          temperature: 72
```

### Using Actions in Automations

**Example: Play Music When Home**

```yaml
automation:
  - alias: "Play Music When Arriving Home"
    trigger:
      - platform: state
        entity_id: person.john
        to: "home"
    action:
      - service: button.press
        target:
          entity_id: button.visual_mapper_tablet_play_music
```

**Example: Lock Door at Night**

```yaml
automation:
  - alias: "Lock Door at Night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: button.press
        target:
          entity_id: button.visual_mapper_phone_lock_door
```

### Lovelace Dashboard Cards

**Sensor Card:**
```yaml
type: entities
title: Tablet Sensors
entities:
  - entity: sensor.visual_mapper_tablet_battery
  - entity: sensor.visual_mapper_tablet_temperature
  - entity: sensor.visual_mapper_tablet_spotify_song
```

**Action Buttons:**
```yaml
type: horizontal-stack
cards:
  - type: button
    entity: button.visual_mapper_tablet_play_music
    name: Play
    icon: mdi:play
  - type: button
    entity: button.visual_mapper_tablet_pause_music
    name: Pause
    icon: mdi:pause
  - type: button
    entity: button.visual_mapper_tablet_next_track
    name: Next
    icon: mdi:skip-next
```

---

## Troubleshooting

### Device Won't Connect

**Symptoms:** Device shows "Disconnected" or "Error" status

**Solutions:**
1. **Check ADB is enabled:**
   - Settings → Developer Options → USB Debugging (ON)

2. **Check WiFi connection:**
   - Device and Visual Mapper must be on same network

3. **Check firewall:**
   - Port 5555 must be open on Android device

4. **Restart ADB on device:**
   ```bash
   adb kill-server
   adb start-server
   adb connect <DEVICE_IP>:5555
   ```

5. **Check Visual Mapper logs:**
   - Home Assistant: Add-on page → Logs tab
   - Standalone: Check terminal output

### Sensor Not Updating

**Symptoms:** Sensor value is stale or shows "unknown"

**Solutions:**
1. **Check sensor is enabled:**
   - Go to Sensors page → Verify toggle is ON

2. **Check device is connected:**
   - Devices page → Device should show "Connected"

3. **Check extraction preview:**
   - Edit sensor → Click "Preview Extraction"
   - If preview fails, extraction method may be wrong

4. **Check MQTT connection:**
   - Home Assistant → Settings → Integrations → MQTT → Check status

5. **Check sensor update interval:**
   - Short intervals (<5s) may cause issues
   - Increase to 30-60 seconds

### Action Not Executing

**Symptoms:** Pressing button in HA does nothing

**Solutions:**
1. **Check action is enabled:**
   - Actions page → Verify action is enabled

2. **Test action manually:**
   - Actions page → Click "▶ Execute" button
   - If fails, coordinates may be wrong

3. **Check MQTT subscription:**
   - Visual Mapper logs should show "Subscribed to action command topic"

4. **Check device screen is on:**
   - Actions won't work if screen is off or locked

5. **Re-create action:**
   - Delete and recreate with fresh screenshot

### Poor Extraction Accuracy

**Symptoms:** Sensor extracts wrong text or garbage values

**Solutions:**
1. **Adjust bounding box:**
   - Make box tighter around text
   - Avoid including background/borders

2. **Try different extraction method:**
   - `text` → Basic OCR
   - `ocr_tesseract` → Advanced OCR
   - `regex` → Pattern matching

3. **Improve screenshot quality:**
   - Increase device screen brightness
   - Use higher resolution device
   - Ensure text is large and clear

4. **Use extraction pipeline:**
   - Chain methods together (e.g., `text` → `regex`)

5. **Check preview before saving:**
   - Always preview extraction to verify accuracy

### High Battery Drain

**Symptoms:** Android device battery drains quickly

**Solutions:**
1. **Increase sensor update intervals:**
   - Use 60s or higher instead of 5-10s

2. **Disable unused sensors:**
   - Only enable sensors you actually need

3. **Use device on charger:**
   - Ideal for wall-mounted tablets

4. **Reduce screenshot frequency:**
   - Settings → Adjust global refresh rate

5. **Use lock screen sensors only:**
   - Sensors that read lock screen use less power

---

## FAQ

### Q: Can I use Visual Mapper without Home Assistant?

**A:** Not currently. Visual Mapper is designed specifically for Home Assistant integration via MQTT. However, you could manually subscribe to MQTT topics using any MQTT client.

### Q: Does Visual Mapper work on iOS devices?

**A:** No. Visual Mapper requires ADB (Android Debug Bridge), which is Android-only.

### Q: Can I control devices remotely (outside my home network)?

**A:** Yes, if you expose Home Assistant externally (via Nabu Casa Cloud or VPN). Visual Mapper device must remain on your local network.

### Q: How many devices can I connect?

**A:** Unlimited. Each device runs independently with its own sensors and actions.

### Q: Can I extract data from apps without APIs?

**A:** Yes! That's the main purpose. Visual Mapper uses OCR to read on-screen text from any app.

### Q: Will sensor extraction work if the app UI changes?

**A:** No. If the app updates and moves elements, you'll need to re-create sensors with new coordinates. This is documented in [MISSING_FEATURES.md](MISSING_FEATURES.md) - automatic screen validation is planned for Phase 8.

### Q: Can actions navigate to different apps/screens automatically?

**A:** Not yet. You must manually ensure the correct screen is showing, or create a macro that navigates first. Automatic navigation is planned for Phase 8 (Sensor Navigation System).

### Q: Is Visual Mapper secure?

**A:** Yes, all data stays local on your network. No cloud services are used. However, ensure your Home Assistant instance is secured properly.

### Q: Can I share sensor/action configurations with others?

**A:** Yes! Use the Export/Import feature on Sensors/Actions pages. A plugin system for sharing templates is planned for Phase 7.

### Q: Does Visual Mapper support rooted devices?

**A:** Visual Mapper works on both rooted and non-rooted devices. Root is not required.

---

## Known Limitations

### Critical Limitation: Sensor Navigation ⚠️

**Sensors capture from whatever screen is currently showing.**

**Impact:**
If you create a sensor for "Spotify Song Title" but Spotify isn't open when the sensor updates, it will extract garbage data from whatever app is showing.

**Workarounds:**
1. **Kiosk Mode:** Dedicate device to run single app fullscreen
2. **Lock Screen Sensors:** Only monitor data visible on lock screen (battery, time, notifications)
3. **Manual HA Automations:** Create automation that opens app before sensor updates
4. **Macros:** Create action macro that navigates to app first

**Future Fix:**
Phase 8 (v1.1.0) will add automatic sensor navigation - sensors will know which app to open before capturing.

See [MISSING_FEATURES.md](MISSING_FEATURES.md) for complete list of limitations.

### Other Limitations

- **No live streaming** (Phase 10 - v1.3.0)
- **No macro builder UI** (Phase 9 - v1.2.0)
- **No action recording mode** (Phase 9+)
- **No scheduled actions** (use HA automations instead)
- **No conditional sensors** (use HA template sensors instead)

---

## Next Steps

**Now that you've read this guide:**

1. ✅ Connect your first device
2. ✅ Create a simple sensor (battery percentage)
3. ✅ Create a simple action (tap button)
4. ✅ Test sensor in Home Assistant automations
5. ✅ Test action from Home Assistant dashboard
6. ✅ Join the community (Discord/GitHub) for templates and support

**Need More Help?**
- 📚 Read [FEATURE_SPECIFICATIONS.md](FEATURE_SPECIFICATIONS.md) for complete feature list
- 🔧 Read [TROUBLESHOOTING_DETAILED.md](TROUBLESHOOTING_DETAILED.md) for advanced fixes
- 💬 Join Discord: [Link TBD]
- 🐛 Report bugs: [GitHub Issues](https://github.com/YOUR_USERNAME/visual-mapper/issues)

---

**Document Version:** 1.0.0
**Created:** 2025-12-23
**For Project Version:** Visual Mapper 0.0.5+

**Related Documentation:**
- [MISSING_FEATURES.md](MISSING_FEATURES.md) - Known gaps and future features
- [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) - Development roadmap
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Technical overview
