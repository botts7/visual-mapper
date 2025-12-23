# Visual Mapper - Detailed Troubleshooting Guide

**Version:** 1.0.0
**Last Updated:** 2025-12-23
**For:** Visual Mapper 0.0.5+

---

## 📋 Table of Contents

1. [Connection Issues](#connection-issues)
2. [Sensor Issues](#sensor-issues)
3. [Action Issues](#action-issues)
4. [MQTT Issues](#mqtt-issues)
5. [Performance Issues](#performance-issues)
6. [UI Issues](#ui-issues)
7. [Diagnostic Tools](#diagnostic-tools)
8. [Log Analysis](#log-analysis)

---

## Connection Issues

### Device Shows "Disconnected"

**Possible Causes:**
- ADB not enabled on device
- Device and server on different networks
- Firewall blocking port 5555
- Device IP changed
- ADB server crashed

**Diagnostics:**
```bash
# Test ADB connection from command line
adb devices

# Should show:
# List of devices attached
# 192.168.1.100:5555    device

# If empty, try:
adb connect 192.168.1.100:5555
```

**Solutions:**

**1. Enable ADB over WiFi:**
```bash
# Connect device via USB first
adb tcpip 5555
adb connect <DEVICE_IP>:5555
```

**2. Check device IP:**
- Android Settings → About Phone → Status → IP address
- Make sure it matches IP in Visual Mapper

**3. Restart ADB daemon:**
```bash
adb kill-server
adb start-server
```

**4. Check firewall on Android:**
- Some custom ROMs block ADB over WiFi by default
- Use USB connection instead

**5. Try different port:**
```bash
adb tcpip 5037
adb connect <DEVICE_IP>:5037
```

### Connection Works Then Disconnects

**Possible Causes:**
- Device going to sleep
- WiFi power saving
- ADB timeout

**Solutions:**

**1. Disable WiFi power saving (Android):**
- Settings → WiFi → Advanced → Keep Wi-Fi on during sleep → Always

**2. Disable battery optimization for ADB:**
- Settings → Apps → Show system apps → ADB → Battery → Don't optimize

**3. Use wired connection:**
- Keep device connected via USB (eliminates network issues)

**4. Increase ADB timeout:**
```bash
# Set longer timeout (seconds)
adb wait-for-device
```

### "Connection Refused" Error

**Possible Causes:**
- ADB not running on device
- Wrong port
- Firewall blocking

**Solutions:**

**1. Check ADB is running:**
```bash
adb shell "getprop init.svc.adbd"
# Should return: running
```

**2. Restart ADB on device:**
```bash
adb kill-server
adb start-server
adb tcpip 5555
```

**3. Check firewall:**
```bash
# Windows
netsh advfirewall firewall add rule name="ADB" dir=in action=allow protocol=TCP localport=5555

# Linux
sudo ufw allow 5555/tcp
```

---

## Sensor Issues

### Sensor Not Updating

**Diagnostics:**

**Check sensor status in logs:**
```bash
# Home Assistant add-on
# Add-on page → Logs tab

# Look for:
[SensorUpdater] Updating sensor: your_sensor_name
[SensorUpdater] Published sensor state: sensor_value
```

**Check MQTT messages:**
```bash
# Subscribe to MQTT topic
mosquitto_sub -h localhost -t "homeassistant/sensor/#" -v

# Should see messages like:
homeassistant/sensor/visual_mapper_device/config {"name": "..."}
visual_mapper/device/sensor/sensor_id/state "value"
```

**Solutions:**

**1. Sensor disabled:**
- Sensors page → Check toggle is ON

**2. Device disconnected:**
- Devices page → Verify connection

**3. MQTT broker offline:**
- Check broker status in Home Assistant

**4. Update interval too long:**
- Edit sensor → Reduce update interval to test

**5. Extraction method failing:**
- Edit sensor → Click "Preview Extraction"
- If fails, adjust bounding box or method

### Sensor Shows "Unknown" or "Unavailable"

**Possible Causes:**
- Extraction failed
- Device offline
- MQTT connection lost

**Solutions:**

**1. Check extraction preview:**
- Edit sensor → Preview Extraction
- If empty, extraction method is wrong

**2. Check device availability:**
- MQTT topic: `visual_mapper/<device_id>/availability`
- Should be: `online`

**3. Check sensor refresh:**
- Wait for next update cycle
- Or manually refresh device screenshot

**4. Re-create sensor:**
- Delete and recreate with fresh screenshot

### Wrong Value Extracted

**Possible Causes:**
- Bounding box too large/small
- Wrong extraction method
- Screen changed (app updated)

**Solutions:**

**1. Adjust bounding box:**
- Tighten box around exact text
- Avoid borders, backgrounds
- Use Draw Mode for precision

**2. Try different extraction method:**
```
Current: text
Try: ocr_tesseract (better accuracy)
Try: regex (pattern matching)
```

**3. Use extraction pipeline:**
```json
{
  "extraction_method": "pipeline",
  "extraction_config": {
    "steps": [
      {"method": "text"},
      {"method": "after", "delimiter": ":"},
      {"method": "regex", "pattern": "\\d+"}
    ]
  }
}
```

**4. Check screenshot quality:**
- Increase device brightness
- Use higher resolution device
- Ensure text is clear and large

### Sensor Extraction is Slow

**Possible Causes:**
- OCR Tesseract (slow but accurate)
- Large bounding box
- High update frequency

**Solutions:**

**1. Use faster extraction method:**
```
Fastest: text (simple OCR)
Medium: regex (pattern matching)
Slowest: ocr_tesseract (accurate but slow)
```

**2. Reduce bounding box size:**
- Smaller area = faster extraction

**3. Increase update interval:**
- 60s instead of 10s

**4. Disable unused sensors:**
- Only keep active sensors enabled

---

## Action Issues

### Action Button Does Nothing

**Diagnostics:**

**Check logs:**
```bash
# Look for:
[MQTTManager] Received action command: device/action_id
[ActionExecutor] Executing action: action_name
[ActionExecutor] Action completed successfully
```

**Test manually:**
- Actions page → Click "▶ Execute"
- If works manually but not from HA, MQTT issue

**Solutions:**

**1. Check action is enabled:**
- Actions page → Verify toggle is ON

**2. Check MQTT subscription:**
```bash
# Logs should show:
[MQTTManager] Subscribed to action command topic: visual_mapper/device/action/action_id/execute
```

**3. Test MQTT command manually:**
```bash
mosquitto_pub -h localhost -t "visual_mapper/device/action/action_id/execute" -m "EXECUTE"
```

**4. Re-create action:**
- Delete and recreate to refresh MQTT discovery

**5. Check device screen is on:**
- Actions won't work if device is locked/asleep

### Action Taps Wrong Location

**Possible Causes:**
- Screen resolution changed
- Coordinate offset bug
- Device rotated

**Solutions:**

**1. Re-capture with current screenshot:**
- Delete action
- Capture fresh screenshot
- Click exact location again

**2. Check device orientation:**
- Sensors/actions only work in orientation they were created in
- Lock device rotation

**3. Manual coordinate adjustment:**
- Edit action
- Adjust X/Y by ±10 pixels
- Test until accurate

**4. Use element selector instead:**
- Coming in Phase 8 - select elements instead of coordinates

### Macro Fails Partway Through

**Possible Causes:**
- Timing issue (app not loaded)
- Screen changed unexpectedly
- Action failed silently

**Solutions:**

**1. Add delays between steps:**
```json
{
  "action_type": "macro",
  "steps": [
    {"action_type": "launch_app", "package": "com.example.app"},
    {"action_type": "delay", "duration": 3000},  ← Increased delay
    {"action_type": "tap", "x": 100, "y": 200}
  ]
}
```

**2. Test each step individually:**
- Execute each action separately
- Verify each works before combining

**3. Add screen validation:**
- Coming in Phase 8 - validate screen before next step

**4. Use error handling:**
- Coming in Phase 9 - retry on failure

---

## MQTT Issues

### Sensors Not Appearing in Home Assistant

**Diagnostics:**

**Check MQTT integration:**
- Home Assistant → Settings → Devices & Services → MQTT
- Status should be "Configured"

**Check discovery enabled:**
- MQTT integration → Configure → Enable discovery

**Check discovery topic:**
```bash
mosquitto_sub -h localhost -t "homeassistant/#" -v

# Should see messages like:
homeassistant/sensor/visual_mapper_device/sensor_id/config {...}
```

**Solutions:**

**1. Enable MQTT discovery:**
- Home Assistant → MQTT integration settings
- Enable "Discovery"
- Prefix: `homeassistant` (default)

**2. Check MQTT broker:**
```bash
# Test connection
mosquitto_sub -h localhost -t "visual_mapper/#" -v

# Should see sensor updates
```

**3. Manually republish discovery:**
- Sensors page → Edit sensor → Save (republishes)

**4. Restart Home Assistant:**
- Sometimes discovery requires restart to process

**5. Check MQTT credentials:**
- Visual Mapper config must have correct MQTT username/password

### Actions Not Appearing as Buttons

**Possible Causes:**
- Button entity not discovered
- MQTT discovery failed
- Action ID contains invalid characters

**Solutions:**

**1. Check action discovery:**
```bash
mosquitto_sub -h localhost -t "homeassistant/button/#" -v

# Should see:
homeassistant/button/visual_mapper_device/action_id/config {...}
```

**2. Check entity registry:**
- Home Assistant → Developer Tools → States
- Filter: `button.visual_mapper`
- Should list all actions

**3. Re-create action:**
- Delete action
- Create new one with simple name (alphanumeric only)

**4. Check logs for errors:**
```bash
[MQTTManager] Failed to publish action discovery: ...
```

### MQTT Connection Drops

**Possible Causes:**
- Broker timeout
- Network issue
- Too many connections

**Solutions:**

**1. Increase broker timeout:**
```yaml
# Mosquitto config
max_keepalive 300
```

**2. Check broker logs:**
```bash
# Home Assistant → Add-ons → Mosquitto → Logs
```

**3. Restart MQTT broker:**
- Home Assistant → Add-ons → Mosquitto → Restart

**4. Use persistent connection:**
- Visual Mapper auto-reconnects, check logs for reconnection attempts

---

## Performance Issues

### High Battery Drain on Device

**Diagnostics:**

**Check sensor update frequency:**
- Count sensors × update frequency = total requests/second

**Example:**
- 10 sensors × 10s interval = screenshot every 10s
- Battery impact: High

**Solutions:**

**1. Increase update intervals:**
- Use 60s minimum for non-critical sensors
- Use 300s (5 min) for slow-changing data

**2. Disable unused sensors:**
- Only keep sensors you actually need enabled

**3. Use lock screen sensors:**
- Reading lock screen uses less power than waking device

**4. Keep device plugged in:**
- Ideal for wall-mounted tablets

**5. Reduce screenshot quality:**
- Coming in Phase 9 - configurable resolution

### Screenshot Capture is Slow

**Possible Causes:**
- High resolution device (4K screens)
- Slow ADB connection
- Network latency

**Solutions:**

**1. Use USB connection:**
- Much faster than WiFi

**2. Reduce device resolution:**
```bash
adb shell wm size 1080x1920  # Lower resolution
adb shell wm density 240      # Lower DPI
```

**3. Disable animations:**
```bash
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0
```

**4. Use wired Ethernet (if device supports):**
- Faster and more reliable than WiFi

### UI is Slow/Laggy

**Possible Causes:**
- Large screenshots
- Too many UI elements
- Browser rendering

**Solutions:**

**1. Use modern browser:**
- Chrome, Firefox, Edge (latest versions)

**2. Disable overlays when not needed:**
- Toggle off UI element overlay visualization

**3. Close unused tabs:**
- Visual Mapper uses WebSockets (memory intensive)

**4. Clear browser cache:**
- Old cached files may conflict

---

## UI Issues

### Screenshot Not Loading

**Possible Causes:**
- Device disconnected
- API error
- Cache issue

**Solutions:**

**1. Refresh page:**
- Hard refresh: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)

**2. Check browser console:**
- F12 → Console tab
- Look for errors

**3. Check API base:**
```javascript
// Browser console
console.log(window.API_BASE);
// Should show correct API URL
```

**4. Clear browser cache:**
- Settings → Clear browsing data

### Draw Mode Not Working

**Possible Causes:**
- JavaScript error
- Wrong page loaded
- Coordinate mapping broken

**Solutions:**

**1. Check console for errors:**
```javascript
// Browser console (F12)
// Look for errors when clicking Draw Mode
```

**2. Reload page:**
- Hard refresh: Ctrl+Shift+R

**3. Check coordinate mapper:**
```javascript
// Browser console
console.log(window.CoordinateMapper);
// Should not be undefined
```

**4. Check module loading:**
```javascript
// Look for in console:
[Init] CoordinateMapper loaded successfully
```

### Buttons Don't Respond

**Possible Causes:**
- JavaScript error
- Event listeners not attached
- API client not loaded

**Solutions:**

**1. Check console for errors:**
```javascript
// F12 → Console
// Look for errors
```

**2. Reload page:**
- Ctrl+Shift+R

**3. Check API client:**
```javascript
// Browser console
console.log(window.apiClient);
// Should show object with methods
```

**4. Check event listeners:**
```javascript
// Check if button has listener
document.getElementById('captureBtn').onclick
// Should not be null
```

---

## Diagnostic Tools

### Built-In Diagnostics

**Coming in Phase 7: diagnostic.html**

Will include:
- System health checks
- Connection diagnostics
- MQTT connectivity test
- Performance metrics
- Log viewer

**Current Workarounds:**

**1. Check device connection:**
```bash
# GET /api/adb/devices
curl http://localhost:3000/api/adb/devices
```

**2. Check sensors:**
```bash
# GET /api/sensors/{device_id}
curl http://localhost:3000/api/sensors/192.168.1.100:5555
```

**3. Test screenshot capture:**
```bash
# POST /api/adb/screenshot
curl -X POST http://localhost:3000/api/adb/screenshot \
  -H "Content-Type: application/json" \
  -d '{"device_id": "192.168.1.100:5555"}'
```

### External Diagnostic Tools

**1. MQTT Explorer:**
- Download: http://mqtt-explorer.com/
- Connect to broker
- View all topics and messages
- Test publish/subscribe

**2. ADB Logcat:**
```bash
# View Android device logs
adb logcat

# Filter for errors
adb logcat *:E

# Filter for specific app
adb logcat | grep "your.app.package"
```

**3. Browser DevTools:**
- F12 → Network tab
- See all API requests
- Check for failed requests
- View request/response data

**4. Wireshark (Advanced):**
- Capture network traffic
- Diagnose connection issues
- Check MQTT packet flow

---

## Log Analysis

### Understanding Visual Mapper Logs

**Log Levels:**
```
DEBUG   - Detailed information for debugging
INFO    - Normal operations
WARNING - Issues that don't stop operation
ERROR   - Errors that affect functionality
```

**Common Log Patterns:**

**Device Connection:**
```
[ADBBridge] Connecting to device: 192.168.1.100:5555
[ADBBridge] Device connected successfully
[SensorUpdater] Started update loop for 192.168.1.100:5555
```

**Sensor Update:**
```
[SensorUpdater] Updating sensor: battery_percentage
[TextExtractor] Extracting text from bounds: {x:100, y:50, width:80, height:30}
[TextExtractor] Extracted value: 85%
[MQTTManager] Published sensor state: sensor.visual_mapper_device_battery_percentage = 85%
```

**Action Execution:**
```
[MQTTManager] Received action command: 192.168.1.100:5555/tap_play_button payload=EXECUTE
[ActionExecutor] Executing action: Play Music (tap)
[ADBBridge] Sending tap command: x=540 y=1200
[ActionExecutor] Action completed successfully
```

**Errors to Watch For:**

**Connection Error:**
```
[ADBBridge] Failed to connect to device 192.168.1.100:5555: Connection refused
```
→ Device ADB not running or wrong IP

**MQTT Error:**
```
[MQTTManager] Failed to connect to MQTT broker: Connection refused
```
→ Broker offline or wrong credentials

**Extraction Error:**
```
[TextExtractor] Extraction failed: No text found in bounds
```
→ Bounding box wrong or screen changed

**Action Error:**
```
[ActionExecutor] Failed to execute action: Device not connected
```
→ Device offline when action attempted

### Enabling Debug Logging

**Home Assistant Add-on:**
```yaml
# Add-on configuration
log_level: debug
```

**Standalone:**
```python
# Edit server.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Getting Help

If you've tried all troubleshooting steps and still have issues:

**1. Gather Information:**
- Visual Mapper version
- Home Assistant version
- Android device model and OS version
- Error logs (last 50 lines)
- Screenshot of issue (if UI related)

**2. Check Existing Issues:**
- GitHub Issues: https://github.com/YOUR_USERNAME/visual-mapper/issues
- Search for similar problems

**3. Report New Issue:**
- Use GitHub issue template
- Include all gathered information
- Describe expected vs actual behavior

**4. Community Support:**
- Discord: [Link TBD]
- Home Assistant Forum: [Link TBD]

---

**Document Version:** 1.0.0
**Created:** 2025-12-23
**For Project Version:** Visual Mapper 0.0.5+

**Related Documentation:**
- [USER_GUIDE.md](USER_GUIDE.md) - Main user guide
- [MISSING_FEATURES.md](MISSING_FEATURES.md) - Known limitations
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Technical overview
