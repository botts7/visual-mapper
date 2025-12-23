# ADB Bridge Methods Reference

**Purpose:** Complete documentation of ADB bridge Python methods.

**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## 🎯 ADBBridge Class

**File:** `adb_bridge.py`

---

## 🔧 Connection Methods

### **connect_device(host, port=5555)**

Connect to Android device via TCP/IP.

**Parameters:**
- `host` (str): Device IP address
- `port` (int): ADB port (default: 5555)

**Returns:**
- `device_id` (str): Format "host:port"

**Raises:**
- `ConnectionError`: If connection fails

**Example:**
```python
device_id = await adb_bridge.connect_device('192.168.1.100', 5555)
# Returns: '192.168.1.100:5555'
```

### **disconnect_device(device_id)**

Disconnect from device.

**Parameters:**
- `device_id` (str): Device identifier

**Example:**
```python
await adb_bridge.disconnect_device('192.168.1.100:5555')
```

### **get_devices()**

Get list of connected devices.

**Returns:**
- `list`: Array of device dicts

**Example:**
```python
devices = await adb_bridge.get_devices()
# [{"id": "...", "state": "device", "connected": true}]
```

---

## 📸 Screenshot Methods

### **capture_screenshot(device_id)**

Capture PNG screenshot from device.

**Parameters:**
- `device_id` (str): Device identifier

**Returns:**
- `bytes`: PNG image bytes

**Example:**
```python
png_bytes = await adb_bridge.capture_screenshot('192.168.1.100:5555')
```

### **get_ui_elements(device_id)**

Extract UI element hierarchy.

**Parameters:**
- `device_id` (str): Device identifier

**Returns:**
- `list`: Array of element dicts

**Example:**
```python
elements = await adb_bridge.get_ui_elements('192.168.1.100:5555')
# [{"text": "...", "bounds": {...}, "clickable": true, ...}]
```

---

## 🎮 Control Methods

### **tap(device_id, x, y)**

Simulate tap at coordinates.

**Parameters:**
- `device_id` (str): Device identifier
- `x` (int): X coordinate
- `y` (int): Y coordinate

**Example:**
```python
await adb_bridge.tap('192.168.1.100:5555', 540, 960)
```

### **swipe(device_id, x1, y1, x2, y2, duration=300)**

Simulate swipe gesture.

**Parameters:**
- `device_id` (str): Device identifier
- `x1, y1` (int): Start coordinates
- `x2, y2` (int): End coordinates
- `duration` (int): Swipe duration in ms

**Example:**
```python
await adb_bridge.swipe('192.168.1.100:5555', 540, 1500, 540, 500, 300)
```

### **type_text(device_id, text)**

Type text on device.

**Parameters:**
- `device_id` (str): Device identifier
- `text` (str): Text to type (spaces auto-escaped)

**Example:**
```python
await adb_bridge.type_text('192.168.1.100:5555', 'Hello World')
```

---

## 🔧 Helper Methods

### **_parse_bounds(bounds_str)**

Parse UI element bounds string.

**Parameters:**
- `bounds_str` (str): Format "[x1,y1][x2,y2]"

**Returns:**
- `dict`: {"x": int, "y": int, "width": int, "height": int} or None

**Example:**
```python
bounds = adb_bridge._parse_bounds('[100,200][300,400]')
# {"x": 100, "y": 200, "width": 200, "height": 200}
```

---

## 📚 Related Documentation

- [12_BACKEND_API.md](12_BACKEND_API.md) - Backend architecture
- [50_API_ENDPOINTS.md](50_API_ENDPOINTS.md) - API endpoints

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.1+
