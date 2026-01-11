# Visual Mapper v0.2.31 - Transform Android Devices into HA Sensors & Automation

Hey everyone! I've been working on an open-source project that I think could be useful for the community, and I'm looking for testers and contributors to help improve it.

## What is Visual Mapper?

Visual Mapper lets you **create Home Assistant sensors from any Android app's UI** and **automate device interactions** - all without modifying the Android app itself. It works by connecting to your Android device via ADB and reading the screen/UI elements.

**Example Use Cases:**
- Create a sensor from your EV app showing battery %, range, charging status
- Monitor your robot vacuum's status from its Android app
- Read values from legacy devices that only have Android apps (old thermostats, cameras, etc.)
- Automate repetitive tasks: "Open app → Navigate to screen → Capture value → Return home"

## How It Works

1. Connect your Android device via WiFi ADB (Android 11+) or USB
2. Use the visual Flow Wizard to record navigation steps
3. Select UI elements to capture as sensors (or use Smart Suggestions for auto-detection)
4. Schedule flows to run periodically (e.g., every 5 minutes)
5. Sensors auto-publish to HA via MQTT with auto-discovery

## Current Features (v0.2.32)

| Feature | Status |
|---------|--------|
| WiFi ADB connection (Android 11+) | ✅ Working |
| USB ADB connection | ✅ Working |
| Screenshot capture & element detection | ✅ Working |
| Visual Flow Wizard (record & replay) | ✅ Working |
| **Smart Suggestions** (AI-powered sensor detection) | ✅ New |
| **Learn App Navigation** (screen mapping) | ✅ New |
| Sensor creation from UI elements | ✅ Working |
| MQTT auto-discovery to Home Assistant | ✅ Working |
| Scheduled flow execution | ✅ Working |
| Multi-device support | ✅ Working |
| Live screen streaming | ✅ Working |
| Auto-unlock (PIN/passcode) | ✅ Working |
| Smart screen sleep prevention | ✅ Working |
| Play Store app icons & names | ✅ Working |
| ML Training Server (optional) | ✅ Working |
| Android Companion App | ✅ Working |

## Screenshots

Flow Wizard UI
![image|690x358](upload://A8NXKeKfFImnvuaND0XEBmAcPj5.jpeg)

Flow Management
![image|690x405](upload://uBU3OZJyFHW2usiHVwAT4cFEF1x.png)

Sensor creation dialog
![image|398x500](upload://3nfRApAOovevl5GefdEoZP6r9wd.png)

Dashboard
![image|690x489](upload://ckK1odWSIar3l7wwFUSPARQZeL7.png)

HA sensors created
![image|690x450](upload://5F3V4boChrpxdsJLkV9gBoxugdi.png)

## Android Companion App

The optional Android companion app provides enhanced automation via Accessibility Service instead of ADB. This gives you reliable, native access to UI elements without ADB connection issues.

**[Download APK](https://github.com/botts7/visual-mapper-android/releases)** (v0.2.0 - Signed)

### Features

| Feature | Status |
|---------|--------|
| **Accessibility Service** | |
| UI element capture & interaction | ✅ Working |
| Gesture dispatch (tap, swipe, scroll) | ✅ Working |
| Pull-to-refresh automation | ✅ Working |
| Text input automation | ✅ Working |
| Screen wake/sleep control | ✅ Working |
| Key event simulation | ✅ Working |
| **Flow Execution** | |
| All step types (TAP, SWIPE, TEXT_INPUT, WAIT, etc.) | ✅ Working |
| Conditional logic (if element exists, if text matches) | ✅ Working |
| Screen wake/sleep steps | ✅ Working |
| **ML & Navigation** | |
| TensorFlow Lite with NNAPI/GPU acceleration | ✅ Working |
| Q-Learning exploration with Room persistence | ✅ Working |
| Dijkstra path planning with reliability weighting | ✅ Working |
| On-device model inference | ✅ Working |
| **Server Integration** | |
| MQTT sensor publishing to Home Assistant | ✅ Working |
| Bidirectional flow sync with server | ✅ Working |
| Real-time status updates | ✅ Working |
| **Security** | |
| Encrypted storage | ✅ Working |
| Audit logging | ✅ Working |
| Privacy controls & app exclusions | ✅ Working |

### When to Use the Companion App

- Device doesn't support WiFi ADB reliably
- Want ML-assisted app exploration (learns optimal paths)
- Need more reliable UI interaction than ADB provides
- Want flows to run even when HA server is offline
- Need Accessibility Service features not available via ADB

## ML Training Server

The ML Training Server enables real-time Q-learning from Android exploration data. The Android app explores your apps and learns optimal navigation paths over time.

**Deployment Options:**

| Option | Description |
|--------|-------------|
| **Local (in add-on)** | Enable in add-on config - ML runs alongside Visual Mapper |
| **Remote** | Run on a separate machine with GPU/NPU for better training |
| **Dev machine** | Use included scripts to run ML training with full hardware acceleration |

**Hardware Acceleration:**

| Accelerator | Platform | Use Case |
|-------------|----------|----------|
| Coral Edge TPU | USB/M.2/PCIe | Raspberry Pi, Linux servers |
| DirectML (NPU) | Windows ARM/x64 | Windows laptops with NPU |
| CUDA (GPU) | NVIDIA GPUs | High-performance servers |
| CPU | All platforms | Fallback, always available |

```yaml
# Add-on config to enable local ML training
ml_training_mode: "local"  # or "remote" or "disabled"
ml_use_dqn: true           # Use Deep Q-Network (better learning)
```

## Installation

### Home Assistant Add-on (Recommended)
Add this repository to your HA add-on store:
```
https://github.com/botts7/visual-mapper-addon
```

### Docker (Standalone)
```bash
docker run -d --name visual-mapper \
  --network host \
  -e MQTT_BROKER=your-mqtt-broker \
  ghcr.io/botts7/visual-mapper:latest
```

### Android Companion App (Optional)
Download from: https://github.com/botts7/visual-mapper-android/releases

## Requirements

- Android device with **Developer Options** and **Wireless Debugging** enabled (Android 11+)
- Both devices on the same network
- MQTT broker (Mosquitto) for HA integration

## Current State / Known Limitations

This is **beta software** - it works, but there are rough edges:

- **Samsung devices**: Lock screen handling now mostly working
- **Element detection**: Sometimes UI elements move between app updates
- **ADB stability**: WiFi connections can drop occasionally (auto-reconnect implemented)

## What I'm Looking For

### Testers
- Try it with different Android devices (especially non-Samsung)
- Test with various Android apps
- Report bugs and edge cases

### Contributors
- Python/FastAPI backend
- JavaScript frontend
- Android/Kotlin development
- Documentation

## Links

| Resource | Link |
|----------|------|
| Main Repository | https://github.com/botts7/visual-mapper |
| HA Add-on Repository | https://github.com/botts7/visual-mapper-addon |
| Android Companion App | https://github.com/botts7/visual-mapper-android |
| Issues / Bug Reports | https://github.com/botts7/visual-mapper/issues |

## Recent Changelog

**v0.2.32** - Fix Play Store icon/name fetching (asyncio thread pool)
**v0.2.31** - Complete cache bust, auto-version JS modules
**v0.2.28** - Fix app icons during wizard, Play Store fetch
**v0.2.25** - ML Training Server fixes, Set Home Screen fix
**v0.2.24** - Learn Navigation fixes, splash screen detection
**v0.2.23** - Hover highlight, edit sensors from flow review
