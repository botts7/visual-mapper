# Visual Mapper - Setup & Troubleshooting Guide

**Version:** 0.0.2 (Phase 1)
**Last Updated:** 2025-12-22

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Android Device Setup](#android-device-setup)
3. [Visual Mapper Setup](#visual-mapper-setup)
4. [Connection Methods](#connection-methods)
5. [Verification Steps](#verification-steps)
6. [Troubleshooting](#troubleshooting)
7. [Common Issues](#common-issues)

---

## Prerequisites

### System Requirements

**Visual Mapper Server:**
- Python 3.11 or higher
- Windows, macOS, or Linux
- Network connection to Android device

**Android Device:**
- Android 5.0 (Lollipop) or higher
- Developer Options enabled
- USB Debugging enabled
- Same network as Visual Mapper server (for wireless)

---

## Android Device Setup

### Step 1: Enable Developer Options

1. Go to **Settings** → **About phone**
2. Find **Build number** (may be in Software Information)
3. Tap **Build number** 7 times
4. Enter your PIN/password if prompted
5. You should see "You are now a developer!"

### Step 2: Enable USB Debugging

1. Go to **Settings** → **Developer Options**
2. Enable **USB debugging**
3. (Optional) Enable **Stay awake** to prevent screen timeout

### Step 3A: Setup for Legacy TCP/IP (All Android versions)

**Requirements:** USB cable and computer with ADB tools

1. Connect device to computer via USB
2. On device, allow USB debugging when prompted
3. On computer, open terminal/command prompt
4. Run: `adb devices` (verify device shows up)
5. Run: `adb tcpip 5555`
6. Disconnect USB cable
7. Find device IP address:
   - Go to **Settings** → **Wi-Fi**
   - Tap on connected network
   - Note the IP address (e.g., 192.168.1.100)
8. On computer, run: `adb connect <device-ip>:5555`
9. Verify with: `adb devices`

**Important:** This connection will reset when device reboots. You'll need to repeat steps 1-5 via USB after each reboot.

### Step 3B: Setup for Wireless ADB (Android 11+)

**No USB cable required!**

1. Ensure device and Visual Mapper are on same Wi-Fi network
2. Go to **Settings** → **Developer Options**
3. Find and enable **Wireless debugging**
4. Tap on **Wireless debugging** to see connection details
5. Note the IP address and port (e.g., 192.168.1.100:5555)
6. Use these in Visual Mapper's connection form

**Important:** This will reset when device reboots or wireless debugging is toggled off.

---

## Visual Mapper Setup

### Installation

```bash
# Clone or download Visual Mapper
cd "C:\Users\<your-username>\Downloads\Visual Mapper"

# Install Python dependencies
pip install -r requirements.txt

# Start the server
python server.py
```

### Verify Server is Running

1. You should see:
   ```
   [2025-12-22 XX:XX:XX] INFO - [ADBBridge] Initialized (Phase 1 - full implementation)
   [2025-12-22 XX:XX:XX] INFO - Starting Visual Mapper v0.0.1
   [2025-12-22 XX:XX:XX] INFO - Frontend: http://localhost:3000
   [2025-12-22 XX:XX:XX] INFO - API: http://localhost:8099/api
   INFO:     Uvicorn running on http://0.0.0.0:8099 (Press CTRL+C to quit)
   ```

2. Test API endpoint:
   ```bash
   curl http://localhost:8099/api/health
   ```

   Should return:
   ```json
   {"status":"ok","version":"0.0.1","message":"Visual Mapper is running"}
   ```

3. Open browser: http://localhost:8099/devices.html

---

## Connection Methods

### Method 1: TCP/IP - Legacy (Recommended for First-Time Setup)

**Best for:** All Android versions, most reliable

1. Follow [Step 3A: Setup for Legacy TCP/IP](#step-3a-setup-for-legacy-tcpip-all-android-versions)
2. In Visual Mapper:
   - Select "TCP/IP - Legacy (Port 5555)"
   - Enter device IP address
   - Port: 5555
   - Click "Connect Device"

### Method 2: Wireless ADB - Android 11+

**Best for:** Modern devices, no USB cable needed

1. Follow [Step 3B: Setup for Wireless ADB](#step-3b-setup-for-wireless-adb-android-11)
2. In Visual Mapper:
   - Select "Wireless ADB - Android 11+ (Port 5555)"
   - Enter device IP address from wireless debugging screen
   - Enter port from wireless debugging screen (usually 5555)
   - Click "Connect Device"

---

## Verification Steps

### 1. Check Device Connection

After clicking "Connect Device", you should see:
```
✓ Connected: 192.168.1.100:5555 (TCP/IP)
```

### 2. Verify Device Appears in List

The "Connected Devices" section should show:
```
192.168.1.100:5555 - device     [Disconnect]
```

### 3. Test Screenshot Capture

1. Select the connected device from dropdown
2. Click "Capture Screenshot"
3. You should see:
   ```
   ✓ Screenshot captured: X UI elements detected
   ```
4. Device screen should appear on canvas with green/yellow overlays

### 4. Test API Directly

```bash
# List connected devices
curl http://localhost:8099/api/adb/devices

# Should return:
# {"devices":[{"id":"192.168.1.100:5555","state":"device","connected":true}]}
```

---

## Troubleshooting

### Server Won't Start

**Error:** `Address already in use` or `Port 8099 already in use`

**Solution:**
```bash
# Windows PowerShell
taskkill /F /IM python.exe

# Linux/macOS
killall python
```

Then restart: `python server.py`

---

**Error:** `ModuleNotFoundError: No module named 'adb_shell'`

**Solution:**
```bash
pip install -r requirements.txt
```

---

### Device Connection Fails

**Error:** `Connection failed: Connection timed out`

**Possible Causes:**

1. **Device not on same network**
   - Verify both device and server are on same Wi-Fi network
   - Check device IP hasn't changed (DHCP)

2. **Firewall blocking**
   - Windows: Allow Python through Windows Firewall
   - macOS: System Preferences → Security & Privacy → Firewall → Allow Python
   - Linux: `sudo ufw allow 5555/tcp`

3. **Wrong IP or port**
   - Double-check device IP address in Wi-Fi settings
   - Verify port is 5555 for standard ADB

4. **ADB not enabled**
   - Ensure USB debugging is ON
   - For wireless: Ensure Wireless debugging is ON
   - Try toggling it off and on again

**Solutions:**

```bash
# Test connection manually with ADB tools
adb connect <device-ip>:5555
adb devices

# If this works but Visual Mapper doesn't, check server logs
```

---

**Error:** `Device not authorized`

**Solution:**
1. Disconnect device
2. On Android device, go to Settings → Developer Options
3. Tap "Revoke USB debugging authorizations"
4. Reconnect and authorize when prompted

---

### Screenshot Capture Fails

**Error:** `✗ Capture failed: Device not connected`

**Solution:**
1. Click "Disconnect" on the device
2. Reconnect using the connection form
3. Wait for "✓ Connected" message
4. Try screenshot again

---

**Error:** `✗ Capture failed: sh: screencap: not found`

**Cause:** Very old Android version without screencap

**Solution:** Update Android to version 5.0+ or use a different device

---

**Screenshot appears but no UI elements**

**Cause:** uiautomator XML parsing issue

**Check:**
1. Look at server logs for errors
2. Verify device is not in secure screen (lock screen, payment screen)
3. Try on a regular app screen (e.g., Settings app)

---

### Common Issues

#### Canvas Shows Black Screen

**Cause:** Browser caching old JavaScript

**Solution:**
1. Hard refresh: Ctrl+F5 (Windows) or Cmd+Shift+R (Mac)
2. Clear browser cache
3. Close and reopen browser tab

---

#### UI Element Overlays Not Showing

**Cause:** JavaScript module loading issue

**Solution:**
1. Open browser DevTools (F12)
2. Check Console tab for errors
3. Look for module loading errors
4. If found, hard refresh (Ctrl+F5)

---

#### Connection Drops Randomly

**Cause:** Wi-Fi power saving or network interruption

**Solution:**
1. On Android: Settings → Developer Options → Disable "Wi-Fi scan throttling"
2. On Android: Settings → Developer Options → Enable "Stay awake"
3. Ensure device doesn't go to sleep
4. Use static IP instead of DHCP

---

## Advanced Debugging

### Enable Verbose Logging

**Server-side:**
Edit `server.py` line 20:
```python
level=logging.DEBUG  # Changed from INFO
```

**Browser-side:**
Open DevTools (F12) → Console tab

---

### Check Network Connectivity

```bash
# Ping device
ping <device-ip>

# Check if ADB port is open
telnet <device-ip> 5555

# Or with PowerShell
Test-NetConnection -ComputerName <device-ip> -Port 5555
```

---

### Verify ADB Shell Access

```bash
# Connect with standard ADB
adb connect <device-ip>:5555

# Run test command
adb shell "screencap -p | base64"

# Should output base64-encoded PNG data
```

---

## Getting Help

If you're still experiencing issues:

1. **Check server logs** - Look for error messages in terminal
2. **Check browser console** - F12 → Console tab
3. **Test with standard ADB** - Verify device works with `adb` command
4. **Report issue** - Include:
   - Android version
   - Connection method used
   - Server logs
   - Browser console errors
   - Steps to reproduce

---

## Next Steps

Once connected successfully:

1. ✅ Capture screenshots
2. ✅ View UI element hierarchy
3. ⏭️ Phase 2: Device control (tap, swipe, type)
4. ⏭️ Phase 3: Home Assistant sensors
5. ⏭️ Phase 4: Live streaming

---

**Document Version:** 1.0.0
**Created:** 2025-12-22
**For:** Visual Mapper v0.0.2+
