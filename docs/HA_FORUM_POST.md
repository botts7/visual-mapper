# Visual Mapper v0.4.0 - Transform Android Devices into HA Sensors & Automation

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
3. Select UI elements to capture as sensors
4. Schedule flows to run periodically (e.g., every 5 minutes)
5. Sensors auto-publish to HA via MQTT with auto-discovery

## Current Features (v0.4.0)

| Feature | Status |
|---------|--------|
| WiFi ADB connection (Android 11+) | ✅ Working |
| USB ADB connection | ✅ Working |
| Screenshot capture & element detection | ✅ Working |
| Visual Flow Wizard (record & replay) | ✅ Working |
| Sensor creation from UI elements | ✅ Working |
| MQTT auto-discovery to Home Assistant | ✅ Working |
| Scheduled flow execution | ✅ Working |
| Multi-device support | ✅ Working |
| Live screen streaming (MJPEG v2) | ✅ Working |
| Auto-unlock (PIN/passcode) | ✅ Working |
| Smart screen sleep prevention | ✅ Working |
| ML Training Server (optional) | ✅ Working |
| Android Companion App | ✅ Working |
| Dark mode UI | ✅ Working |
| Full-width responsive UI | ✅ New |
| Mobile/tablet support | ✅ New |

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

**[Download APK](https://github.com/botts7/visual-mapper-android/releases)** (v0.3.1 - Signed)

### Features

| Feature | Status |
|---------|--------|
| **Screen Streaming** | |
| MediaProjection low-latency capture (50-150ms) | ✅ New |
| Adaptive FPS based on battery state | ✅ New |
| WebSocket MJPEG binary protocol | ✅ New |
| Orientation change handling | ✅ New |
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

For machines with hardware accelerators:
```bash
# Windows with NPU
.\scripts\run_ml_dev.ps1 -Broker 192.168.x.x -DQN -UseNPU

# Linux/Raspberry Pi with Coral Edge TPU
./scripts/run_ml_dev.sh --broker 192.168.x.x --use-coral

# Linux with NVIDIA GPU
./scripts/run_ml_dev.sh --broker 192.168.x.x --dqn
```

## Installation Options

### 1. Home Assistant Add-on (Recommended)
Add this repository to your HA add-on store:
```
https://github.com/botts7/visual-mapper-addon
```

### 2. Docker (Standalone)
```bash
docker run -d --name visual-mapper \
  --network host \
  -e MQTT_BROKER=your-mqtt-broker \
  ghcr.io/botts7/visual-mapper:latest
```

### 3. Manual Installation
```bash
git clone https://github.com/botts7/visual-mapper.git
cd visual-mapper/backend
pip install -r requirements.txt
python main.py
```

### 4. Android Companion App (Optional)
Download from: https://github.com/botts7/visual-mapper-android/releases

Enable "Install from unknown sources" in Android settings to install.

## Requirements

- Android device with **Developer Options** and **Wireless Debugging** enabled (Android 11+)
- Both devices on the same network
- MQTT broker (Mosquitto) for HA integration

**For Companion App:**
- Android 8.0+ (API 26)
- Accessibility Service permission
- Optional: Notification access for richer automation

## Current State / Known Limitations

This is **beta software** - it works, but there are rough edges:

- **Samsung devices**: Required extra work for lock screen handling (now mostly working)
- **Element detection**: Sometimes UI elements move between app updates
- **ADB stability**: WiFi connections can drop occasionally (auto-reconnect implemented)
- **Documentation**: Still being written

## What I'm Looking For

### Testers
- Try it with different Android devices (especially non-Samsung)
- Test with various Android apps
- Report bugs and edge cases
- Suggest UX improvements
- Test the Android companion app on different devices

### Contributors
- Python/FastAPI backend
- JavaScript frontend
- Android/Kotlin development
- Machine Learning improvements
- Documentation
- UI/UX design

## Links

| Resource | Link |
|----------|------|
| Main Repository | https://github.com/botts7/visual-mapper |
| HA Add-on Repository | https://github.com/botts7/visual-mapper-addon |
| Android Companion App | https://github.com/botts7/visual-mapper-android |
| **Download Android APK** | https://github.com/botts7/visual-mapper-android/releases |
| Issues / Bug Reports | https://github.com/botts7/visual-mapper/issues |
| ML Training Docs | https://github.com/botts7/visual-mapper/blob/main/docs/ML_TRAINING.md |

---

## Changelog

### v0.4.0 (Latest)
- **Full-Width Layout**: All pages now use full viewport width with 24px edge padding - no more wasted screen space
- **Mobile Responsive Design**: Flows and Navigation Learn pages now work properly on mobile/tablet devices
- **Elements Tab Redesign**: Card-based layout matching Smart tab style with type icons, alternative names dropdown, current value display, and collapsible grouped tree structure
- **UI Consistency**: All container widths now consistent across dashboard, flows, performance, and flow wizard pages

### Android Companion App v0.3.1
- **MediaProjection Screen Streaming**: Low-latency capture (50-150ms vs 100-3000ms ADB)
- **Adaptive FPS**: 25 FPS when charging, 20/12/5 FPS on battery based on level
- **WebSocket MJPEG Protocol**: Binary streaming compatible with backend SharedCaptureManager
- **Orientation Handling**: Automatically recreates VirtualDisplay when device rotates
- **WebSocket URL Fix**: Corrected /api prefix for companion WebSocket endpoint

### v0.3.1
- **Dynamic Cache Busting**: All pages now use session-based cache busting - no more stale CSS/JS
- **Dark Mode Everywhere**: Dark mode support added to all pages with instant theme switching (no flash)
- **Dev Tools Improvements**: Version info now fetched dynamically from API
- **Diagnostic Page**: Dynamic CSS and module loading
- **Flow Tab Fix**: Fixed button visibility in dark mode

### v0.2.97
- **Adaptive Backend Sampling**: Fixed monotonic counter vs capped timing lists
- **Async Streaming**: stopStreaming() now properly awaited in all callers
- **Capture Mode Fix**: setCaptureMode race condition resolved
- **Sensor Edit**: Fixed API path for editing sensors
- **Persistent Shell**: Now default for UI dumps (faster than per-command subprocess)

### v0.2.86
- **Edit Buttons**: Added edit button for sensor and action flow steps in Step 3 and Step 4
- Click pencil icon to edit linked sensor or action directly from flow step

### v0.2.80
- **MJPEG v2 Streaming**: Shared capture pipeline with single producer per device
- **SharedCaptureManager**: Broadcasts to all subscribers, eliminates per-frame ADB handshake overhead
- New endpoint: `/ws/stream-mjpeg-v2/{device_id}`

### v0.2.66
- **Companion App Integration**: Fast UI element fetching (100-300ms vs 1-3s)
- **Canvas Fit Mode**: Defaults to fit-height (shows full device screen)
- **Stream Quality**: Default changed to 'fast' for better WiFi compatibility

### v0.2.6
- **Coral Edge TPU**: Hardware acceleration support for Raspberry Pi and Linux servers
- **Hardware Accelerators UI**: Services page shows available accelerators
- **ML Training Server**: Multiple deployment options (local, remote, dev)
