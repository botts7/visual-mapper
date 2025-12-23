# API Endpoints Reference

**Purpose:** Complete REST API documentation for Visual Mapper.

**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## 🎯 Base URL

**Development:** `http://localhost:8099/api`
**HA Ingress:** Detected dynamically (see [20_CODE_PATTERN_API_BASE.md](20_CODE_PATTERN_API_BASE.md))

---

## 📋 Endpoint Categories

1. Device Management
2. Screenshot Capture
3. Device Control
4. Sensor Management (Phase 3)
5. Action Management (Phase 3)
6. Health & Status

---

## 🔌 Device Management

### **GET /api/adb/devices**

List all connected devices.

**Response:**
```json
{
  "devices": [
    {
      "id": "192.168.1.100:5555",
      "state": "device",
      "connected": true
    }
  ]
}
```

### **POST /api/adb/connect**

Connect to device via TCP/IP.

**Request:**
```json
{
  "host": "192.168.1.100",
  "port": 5555
}
```

**Response:**
```json
{
  "device_id": "192.168.1.100:5555",
  "status": "connected"
}
```

### **POST /api/adb/disconnect/{device_id}**

Disconnect from device.

**Response:**
```json
{
  "status": "disconnected"
}
```

---

## 📸 Screenshot Capture

### **POST /api/adb/screenshot**

Capture screenshot with UI elements.

**Request:**
```json
{
  "device_id": "192.168.1.100:5555"
}
```

**Response:**
```json
{
  "screenshot": "base64_encoded_png...",
  "elements": [
    {
      "text": "Settings",
      "resource_id": "com.android.settings:id/title",
      "class": "android.widget.TextView",
      "bounds": {"x": 100, "y": 200, "width": 300, "height": 50},
      "clickable": true,
      "visible": true
    }
  ],
  "timestamp": "2025-12-21T12:00:00Z",
  "device_id": "192.168.1.100:5555"
}
```

---

## 🎮 Device Control

### **POST /api/adb/tap**

Simulate tap at coordinates.

**Request:**
```json
{
  "device_id": "192.168.1.100:5555",
  "x": 540,
  "y": 960
}
```

**Response:**
```json
{
  "status": "success",
  "action": "tap",
  "x": 540,
  "y": 960
}
```

### **POST /api/adb/swipe**

Simulate swipe gesture.

**Request:**
```json
{
  "device_id": "192.168.1.100:5555",
  "x1": 540,
  "y1": 1500,
  "x2": 540,
  "y2": 500,
  "duration": 300
}
```

**Response:**
```json
{
  "status": "success",
  "action": "swipe"
}
```

### **POST /api/adb/type**

Type text on device.

**Request:**
```json
{
  "device_id": "192.168.1.100:5555",
  "text": "Hello World"
}
```

**Response:**
```json
{
  "status": "success",
  "action": "type",
  "text": "Hello World"
}
```

---

## 🏥 Health & Status

### **GET /api/health**

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "version": "0.0.1",
  "timestamp": "2025-12-21T12:00:00Z"
}
```

---

## ⚠️ Error Responses

**Format:**
```json
{
  "detail": "Error message",
  "status_code": 500
}
```

**Common Status Codes:**
- 200: Success
- 400: Bad Request
- 404: Not Found
- 500: Internal Server Error

---

## 📚 Related Documentation

- [12_BACKEND_API.md](12_BACKEND_API.md) - Backend architecture
- [51_ADB_BRIDGE_METHODS.md](51_ADB_BRIDGE_METHODS.md) - ADB methods

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.1+
