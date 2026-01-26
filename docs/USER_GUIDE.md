# Visual Mapper User Guide

> Quick start guide for Visual Mapper v0.4.0-beta

## Table of Contents

1. [Getting Started](#getting-started)
2. [Connecting Devices](#connecting-devices)
3. [Flow Wizard](#flow-wizard)
4. [Creating Sensors](#creating-sensors)
5. [Live Streaming](#live-streaming)
6. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Requirements

- Android device with USB Debugging or Wireless Debugging enabled
- Python 3.11+ (backend)
- Modern web browser (frontend)
- Optional: Android Companion App for faster streaming

### Starting the Server

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 3000
```

Open http://localhost:3000 in your browser.

---

## Connecting Devices

### USB Connection

1. Enable USB Debugging on your Android device:
   - Settings > Developer Options > USB Debugging
2. Connect device via USB cable
3. Accept the RSA key prompt on device
4. Device appears automatically in Visual Mapper

### WiFi Connection

1. Enable Wireless Debugging on device:
   - Settings > Developer Options > Wireless debugging
2. Note the IP address and port shown
3. In Visual Mapper, go to Devices page
4. Click "Add Device" and enter IP:PORT (e.g., `192.168.1.100:5555`)

---

## Flow Wizard

The Flow Wizard lets you record automation sequences that can be scheduled or triggered.

### Recording a Flow

1. Go to **Flows** > **New Flow**
2. Select target device and app
3. Choose capture mode:
   - **Streaming**: Real-time view (recommended)
   - **Polling**: Screenshot-based (slower but works without companion app)
4. Interact with the device:
   - **Tap**: Click on elements to record taps
   - **Swipe**: Click and drag to record swipes
   - **Sensors**: Right-click elements to create sensors
5. Click **Done** when finished

### Flow Steps

| Step Type | Description |
|-----------|-------------|
| `launch_app` | Opens an app by package name |
| `tap` | Taps at coordinates or element |
| `swipe` | Swipes between two points |
| `wait` | Pauses execution for N seconds |
| `capture_sensors` | Reads values from defined sensors |

### Scheduling Flows

1. Open a saved flow
2. Click **Schedule**
3. Set interval (e.g., every 5 minutes)
4. Enable the schedule

---

## Creating Sensors

Sensors extract text values from Android UI elements and publish them to Home Assistant.

### From Flow Wizard

1. During recording, right-click any element with text
2. Select **Create Sensor**
3. Configure:
   - **Name**: Friendly name for Home Assistant
   - **Device Class**: battery, temperature, humidity, etc.
   - **Unit**: %, °C, etc.
   - **Extraction**: Regex pattern if needed

### Sensor Types

| Type | Description | Example |
|------|-------------|---------|
| `sensor` | Numeric/text value | Battery: 85% |
| `binary_sensor` | On/Off state | WiFi Connected |

### Extraction Methods

- **Exact**: Uses full element text
- **Regex**: Extracts specific pattern (e.g., `(\d+)%` for numbers)
- **Numeric**: Extracts first number found

---

## Live Streaming

Visual Mapper supports real-time screen streaming for monitoring and recording.

### Stream Quality Presets

| Preset | Resolution | FPS | Use Case |
|--------|-----------|-----|----------|
| `fast` | 480p | 18 | Flow recording |
| `low` | 480p | 18 | Monitoring |
| `medium` | 720p | 12 | Balance |
| `high` | Native | 5 | Screenshots |

### Companion App (Recommended)

The Android Companion App provides:
- **H.264 hardware encoding**: 10x faster than ADB capture
- **Fast UI tree**: 100-300ms vs 1-3 seconds
- **Background streaming**: Works even when screen is off

Install from: `android-companion/app/build/outputs/apk/debug/app-debug.apk`

---

## Troubleshooting

### Device Not Found

**Symptoms**: Device doesn't appear in list

**Solutions**:
1. Check USB cable / WiFi connection
2. Verify USB Debugging is enabled
3. Accept RSA key prompt on device
4. Try: `adb kill-server && adb start-server`

### Streaming Issues

**Symptoms**: Black screen or no frames

**Solutions**:
1. Try lower quality preset (fast/low)
2. Check if screen is on and unlocked
3. Disable battery optimization for Visual Mapper app
4. Install Companion App for better performance

### Sensor Not Updating

**Symptoms**: Sensor shows stale values

**Solutions**:
1. Verify element still exists (UI may have changed)
2. Check extraction regex matches current text
3. Re-record the flow with current app version
4. Check flow schedule is active

### Error: Device Locked

**Symptoms**: Actions fail with "device locked" error

**Solutions**:
1. Enable Auto-Unlock in device settings
2. Set PIN/password in Visual Mapper config
3. Manually unlock device before running flows

---

## Getting Help

- **API Documentation**: `/docs` (when server running)
- **GitHub Issues**: Report bugs and feature requests
- **Logs**: Check `backend/backend_log.txt` for errors

---

*Last updated: 2026-01-27*
