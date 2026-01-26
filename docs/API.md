# Visual Mapper API Documentation

> Version: 0.4.0-beta | Auto-generated API reference

## Overview

Visual Mapper provides a REST API for Android device monitoring and automation with Home Assistant integration.

**Base URL:** `http://localhost:3000/api`

**Authentication:** Most endpoints require the `X-Companion-Key` header.

---

## Quick Reference

| Category | Endpoint | Method | Description |
|----------|----------|--------|-------------|
| Devices | `/devices` | GET | List connected Android devices |
| Devices | `/devices/{id}/screenshot` | POST | Capture device screenshot |
| Devices | `/devices/{id}/tap` | POST | Execute tap at coordinates |
| Sensors | `/sensors` | GET | List all sensors |
| Sensors | `/sensors` | POST | Create a new sensor |
| Sensors | `/sensors/{id}` | GET | Get sensor by ID |
| Sensors | `/sensors/{id}` | PUT | Update sensor |
| Sensors | `/sensors/{id}` | DELETE | Delete sensor |
| Flows | `/flows` | GET | List all flows |
| Flows | `/flows` | POST | Create a new flow |
| Flows | `/flows/{id}/execute` | POST | Execute a flow |
| Streaming | `/stream/{device_id}` | WS | Live screen streaming (WebSocket) |

---

## Devices

### List Devices

```http
GET /api/devices
```

Returns all connected Android devices with their status.

**Response:**
```json
{
  "devices": [
    {
      "device_id": "192.168.1.100:5555",
      "serial": "ABCD1234",
      "model": "Pixel 6",
      "status": "device",
      "android_version": "14"
    }
  ]
}
```

### Capture Screenshot

```http
POST /api/adb/screenshot
Content-Type: application/json

{
  "device_id": "192.168.1.100:5555",
  "quick": false
}
```

**Response:**
```json
{
  "screenshot": "base64_encoded_png...",
  "elements": [...],
  "timestamp": 1706380800000
}
```

### Execute Tap

```http
POST /api/adb/tap
Content-Type: application/json

{
  "device_id": "192.168.1.100:5555",
  "x": 540,
  "y": 960
}
```

---

## Sensors

### Create Sensor

```http
POST /api/sensors
Content-Type: application/json

{
  "device_id": "192.168.1.100:5555",
  "friendly_name": "Battery Level",
  "sensor_type": "sensor",
  "device_class": "battery",
  "unit_of_measurement": "%",
  "source": {
    "source_type": "element",
    "element_text": "Battery: 85%"
  },
  "extraction_rule": {
    "method": "regex",
    "pattern": "(\\d+)%"
  }
}
```

### List Sensors

```http
GET /api/sensors
```

**Response:**
```json
{
  "sensors": [
    {
      "sensor_id": "uuid-here",
      "friendly_name": "Battery Level",
      "state": "85",
      "last_updated": "2024-01-27T12:00:00Z"
    }
  ]
}
```

---

## Flows

### Create Flow

```http
POST /api/flows
Content-Type: application/json

{
  "name": "Check Battery",
  "description": "Opens settings and captures battery level",
  "target_app": "com.android.settings",
  "steps": [
    {
      "step_type": "launch_app",
      "package": "com.android.settings"
    },
    {
      "step_type": "tap",
      "x": 540,
      "y": 200
    },
    {
      "step_type": "capture_sensors",
      "sensor_ids": ["sensor-uuid"]
    }
  ]
}
```

### Execute Flow

```http
POST /api/flows/{flow_id}/execute
Content-Type: application/json

{
  "device_id": "192.168.1.100:5555"
}
```

---

## Streaming

### WebSocket Stream

Connect to live device screen streaming:

```
ws://localhost:3000/api/stream/{device_id}?quality=medium
```

**Query Parameters:**
- `quality`: `high`, `medium`, `low`, `fast` (default: `fast`)
- `format`: `mjpeg` (default) or `json`

**Frame Format (MJPEG):**
```
[4 bytes: frame_number][4 bytes: capture_time_ms][JPEG data]
```

---

## Error Responses

All errors follow a consistent format:

```json
{
  "success": false,
  "error": {
    "message": "Human-readable error message",
    "type": "ErrorClassName",
    "code": "ERROR_CODE",
    "hint": "Troubleshooting suggestion (when available)",
    "docs": "/docs/relevant-page (when available)"
  }
}
```

### Common Error Codes

| Code | Status | Description |
|------|--------|-------------|
| `DEVICE_NOT_FOUND` | 404 | Device not connected or offline |
| `ADB_CONNECTION_ERROR` | 503 | ADB connection failed |
| `SENSOR_NOT_FOUND` | 404 | Sensor ID does not exist |
| `SENSOR_VALIDATION_ERROR` | 400 | Invalid sensor configuration |
| `HTTP_401` | 401 | Missing or invalid API key |

---

## Interactive Documentation

When the server is running, visit:
- **Swagger UI:** http://localhost:3000/docs
- **ReDoc:** http://localhost:3000/redoc
- **OpenAPI JSON:** http://localhost:3000/openapi.json

---

*Last updated: 2026-01-27*
