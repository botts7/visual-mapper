# Backend API - FastAPI + ADB Bridge

**Purpose:** Complete guide to Visual Mapper's Python backend architecture.

**Starting Version:** 0.0.1
**Target Version:** 1.0.0
**Last Updated:** 2025-12-21

---

## ⚠️ Important Notes

**Code examples are LEGACY REFERENCE from v4.6.0-beta.X - TEST BEFORE USING!**

- These patterns worked in beta but may have bugs
- Always validate in your environment
- This is the TARGET architecture for rebuild
- Not all features exist yet in v0.0.1

---

## 🎯 Technology Stack

| Component | Technology | Version | Why? |
|-----------|-----------|---------|------|
| Framework | FastAPI | 0.104+ | Async, auto docs, fast |
| ADB Library | adb-shell | 0.4+ | Pure Python, no binaries |
| WebSocket | FastAPI WebSocket | Built-in | Native async support |
| ASGI Server | uvicorn | 0.24+ | Production ASGI server |
| HTTP Client | httpx | 0.25+ | Async HTTP client |

---

## 📁 Backend Structure

```
server.py                   # FastAPI app entry point
adb_bridge.py               # ADB communication layer
├── ADBBridge class         # Main ADB interface
├── Device management       # Connect/disconnect
├── Screenshot capture      # screencap command
├── UI element extraction   # uiautomator dump
└── Input simulation        # tap, swipe, type

config/
├── devices.yaml            # Device configurations
└── sensors.yaml            # Sensor definitions (Phase 3)

utils/
├── image_processing.py     # Screenshot manipulation
└── mqtt_client.py          # MQTT discovery (Phase 3)
```

---

## 🔧 FastAPI Application (server.py)

**⚠️ LEGACY REFERENCE:**

```python
# server.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from datetime import datetime
import base64

from adb_bridge import ADBBridge

app = FastAPI(
    title="Visual Mapper API",
    version="0.0.1",
    description="Android Device Monitoring & Automation for Home Assistant"
)

# CORS for HA ingress
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # HA handles auth
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
app.mount("/", StaticFiles(directory="www", html=True), name="www")

# Initialize ADB bridge
adb_bridge = ADBBridge()

# ========== Device Management ==========

@app.get("/api/adb/devices")
async def list_devices():
    """List all connected Android devices"""
    try:
        devices = await adb_bridge.get_devices()
        return {"devices": devices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/adb/connect")
async def connect_device(host: str, port: int = 5555):
    """Connect to Android device via TCP/IP"""
    try:
        device_id = await adb_bridge.connect_device(host, port)
        return {"device_id": device_id, "status": "connected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/adb/disconnect/{device_id}")
async def disconnect_device(device_id: str):
    """Disconnect from device"""
    try:
        await adb_bridge.disconnect_device(device_id)
        return {"status": "disconnected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== Screenshot Capture ==========

@app.post("/api/adb/screenshot")
async def capture_screenshot(device_id: str):
    """Capture screenshot with UI elements"""
    try:
        # Capture PNG screenshot
        screenshot_bytes = await adb_bridge.capture_screenshot(device_id)

        # Extract UI element hierarchy
        elements = await adb_bridge.get_ui_elements(device_id)

        return {
            "screenshot": base64.b64encode(screenshot_bytes).decode(),
            "elements": elements,
            "timestamp": datetime.now().isoformat(),
            "device_id": device_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== Device Control ==========

@app.post("/api/adb/tap")
async def tap(device_id: str, x: int, y: int):
    """Simulate tap at coordinates"""
    try:
        await adb_bridge.tap(device_id, x, y)
        return {"status": "success", "action": "tap", "x": x, "y": y}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/adb/swipe")
async def swipe(device_id: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
    """Simulate swipe gesture"""
    try:
        await adb_bridge.swipe(device_id, x1, y1, x2, y2, duration)
        return {"status": "success", "action": "swipe"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/adb/type")
async def type_text(device_id: str, text: str):
    """Type text on device"""
    try:
        await adb_bridge.type_text(device_id, text)
        return {"status": "success", "action": "type", "text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== WebSocket Streaming ==========

@app.websocket("/ws/stream/{device_id}")
async def stream_endpoint(websocket: WebSocket, device_id: str):
    """WebSocket endpoint for live streaming"""
    await websocket.accept()

    try:
        while True:
            # Capture frame
            screenshot = await adb_bridge.capture_screenshot(device_id)
            elements = await adb_bridge.get_ui_elements(device_id)

            # Send frame
            await websocket.send_json({
                "type": "frame",
                "screenshot": base64.b64encode(screenshot).decode(),
                "elements": elements,
                "timestamp": datetime.now().isoformat()
            })

            # 30 FPS
            await asyncio.sleep(1/30)

    except WebSocketDisconnect:
        print(f"[WebSocket] Client disconnected: {device_id}")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
        await websocket.close()

# ========== Health Check ==========

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "0.0.1",
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8099)
```

---

## 🔌 ADB Bridge (adb_bridge.py)

**⚠️ LEGACY REFERENCE:**

```python
# adb_bridge.py

from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
import xml.etree.ElementTree as ET
import re
import asyncio

class ADBBridge:
    def __init__(self):
        self.devices = {}  # {device_id: AdbDeviceTcp}
        self.signers = []  # RSA signers for auth

    async def connect_device(self, host: str, port: int = 5555):
        """Connect to Android device via TCP/IP"""
        device_id = f"{host}:{port}"

        try:
            # Create ADB device
            device = AdbDeviceTcp(host, port, default_transport_timeout_s=9.)

            # Connect (may require device authorization)
            device.connect(rsa_keys=self.signers, auth_timeout_s=0.1)

            # Store device
            self.devices[device_id] = device

            print(f"[ADB] Connected to {device_id}")
            return device_id

        except Exception as e:
            raise ConnectionError(f"Failed to connect to {device_id}: {e}")

    async def disconnect_device(self, device_id: str):
        """Disconnect from device"""
        if device_id in self.devices:
            self.devices[device_id].close()
            del self.devices[device_id]
            print(f"[ADB] Disconnected from {device_id}")

    async def get_devices(self):
        """Get list of connected devices"""
        return [
            {
                "id": device_id,
                "state": "device",
                "connected": True
            }
            for device_id in self.devices.keys()
        ]

    async def capture_screenshot(self, device_id: str) -> bytes:
        """Capture PNG screenshot from device"""
        device = self.devices.get(device_id)
        if not device:
            raise ValueError(f"Device not connected: {device_id}")

        # Execute screencap command
        result = device.shell("screencap -p", decode=False)

        return result

    async def get_ui_elements(self, device_id: str):
        """Extract UI element hierarchy using uiautomator"""
        device = self.devices.get(device_id)
        if not device:
            raise ValueError(f"Device not connected: {device_id}")

        # Dump UI hierarchy to stdout
        xml_str = device.shell("uiautomator dump /dev/tty")

        # Parse XML
        try:
            root = ET.fromstring(xml_str)
            elements = []

            for node in root.iter('node'):
                bounds = self._parse_bounds(node.get('bounds', ''))
                if bounds:
                    element = {
                        'text': node.get('text', ''),
                        'resource_id': node.get('resource-id', ''),
                        'class': node.get('class', ''),
                        'content_desc': node.get('content-desc', ''),
                        'bounds': bounds,
                        'clickable': node.get('clickable') == 'true',
                        'visible': node.get('visible-to-user') == 'true'
                    }
                    elements.append(element)

            return elements

        except ET.ParseError as e:
            print(f"[ADB] Failed to parse UI dump: {e}")
            return []

    def _parse_bounds(self, bounds_str: str):
        """Parse bounds string '[x1,y1][x2,y2]' to {x, y, width, height}"""
        matches = re.findall(r'\[(\d+),(\d+)\]', bounds_str)
        if len(matches) == 2:
            x1, y1 = map(int, matches[0])
            x2, y2 = map(int, matches[1])
            return {
                'x': x1,
                'y': y1,
                'width': x2 - x1,
                'height': y2 - y1
            }
        return None

    async def tap(self, device_id: str, x: int, y: int):
        """Simulate tap at coordinates"""
        device = self.devices.get(device_id)
        if not device:
            raise ValueError(f"Device not connected: {device_id}")

        device.shell(f"input tap {x} {y}")

    async def swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        """Simulate swipe gesture"""
        device = self.devices.get(device_id)
        if not device:
            raise ValueError(f"Device not connected: {device_id}")

        device.shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")

    async def type_text(self, device_id: str, text: str):
        """Type text on device (escapes spaces)"""
        device = self.devices.get(device_id)
        if not device:
            raise ValueError(f"Device not connected: {device_id}")

        # Escape spaces
        escaped_text = text.replace(' ', '%s')
        device.shell(f"input text {escaped_text}")
```

---

## 📊 API Response Formats

### **Success Response**

```json
{
  "status": "success",
  "data": { },
  "timestamp": "2025-12-21T12:00:00Z"
}
```

### **Error Response**

```json
{
  "detail": "Error message here",
  "status_code": 500
}
```

---

## 🧪 Testing Backend

```python
# tests/unit/python/test_adb_bridge.py

import pytest
from adb_bridge import ADBBridge

@pytest.fixture
def adb_bridge():
    return ADBBridge()

@pytest.mark.asyncio
async def test_parse_bounds(adb_bridge):
    result = adb_bridge._parse_bounds('[100,200][300,400]')
    assert result == {'x': 100, 'y': 200, 'width': 200, 'height': 200}

@pytest.mark.asyncio
async def test_parse_bounds_invalid(adb_bridge):
    result = adb_bridge._parse_bounds('invalid')
    assert result is None
```

---

## 📚 Related Documentation

- [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md) - Overall architecture
- [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md) - Frontend modules
- [50_API_ENDPOINTS.md](50_API_ENDPOINTS.md) - Complete API reference
- [51_ADB_BRIDGE_METHODS.md](51_ADB_BRIDGE_METHODS.md) - ADB method details

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.1.0

**Read Next:** [20_CODE_PATTERN_API_BASE.md](20_CODE_PATTERN_API_BASE.md)
**Read Previous:** [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md)
