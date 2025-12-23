# System Architecture - Visual Mapper

**Purpose:** Complete system architecture for Visual Mapper rebuild from scratch.

**Target Version:** 0.1.0 (when all core features working)
**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## ⚠️ Important Notes

**This document describes the TARGET architecture for the complete rebuild.**

- **Code examples** are reference patterns from legacy system - **TEST BEFORE USING**
- **Not all features exist yet** - this is the blueprint for what we're building
- **Version 0.0.1** = starting point, **0.1.0** = all core features, **1.0.0** = community ready
- **Legacy code** (v4.6.0-beta.10) is reference only, may have bugs

---

## 🎯 System Overview

### **What is Visual Mapper?**

Visual Mapper is a Home Assistant addon that provides comprehensive Android device monitoring, automation, and control - a self-hosted alternative to commercial solutions like Vysor and AirDroid.

### **Core Capabilities (Target for v0.1.0)**

1. **Screenshot Capture** - High-quality Android screen capture with UI element extraction
2. **Live Streaming** - Real-time screen mirroring with interactive overlays (<100ms latency)
3. **Device Control** - Send taps, swipes, text input via ADB
4. **Sensor Creation** - Generate Home Assistant sensors from Android UI elements
5. **Action Automation** - Trigger device actions from HA automations
6. **Multi-Device Support** - Manage multiple Android devices simultaneously

### **Non-Goals (Out of Scope)**

- ❌ iOS/iPhone support (future consideration)
- ❌ Desktop Windows/Mac/Linux support (future consideration)
- ❌ Cloud synchronization (privacy-focused, local only)
- ❌ Commercial licensing (open-source only)

---

## 🏗️ High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Home Assistant (Supervisor)                     │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Visual Mapper Addon (Docker Container)         │ │
│  │                                                        │ │
│  │  ┌──────────────────┐  ┌──────────────────────────┐  │ │
│  │  │    Frontend       │  │      Backend             │  │ │
│  │  │    (nginx)        │  │      (FastAPI)           │  │ │
│  │  │    Port 3000      │  │      Port 8099           │  │ │
│  │  │                   │  │                          │  │ │
│  │  │  • Vanilla JS     │◄─┤  • Python 3.11+          │  │ │
│  │  │  • ES6 Modules    │  │  • ADB Bridge            │  │ │
│  │  │  • HTML5 Canvas   │  │  • WebSocket Server      │  │ │
│  │  │  • WebSocket      │  │  • Screenshot Service    │  │ │
│  │  │    Client         │  │  • Device Manager        │  │ │
│  │  └──────────────────┘  └──────────────────────────┘  │ │
│  │                                                        │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │          Live Streaming (Port 8100)              │ │ │
│  │  │  • WebRTC for H.264 video (low latency)          │ │ │
│  │  │  • WebSocket for UI element overlays             │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  │                                                        │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │              nginx Reverse Proxy                 │ │ │
│  │  │  /          → Frontend (port 3000)               │ │ │
│  │  │  /api/*     → Backend API (port 8099)            │ │ │
│  │  │  /stream/*  → Live Stream (port 8100)            │ │ │
│  │  │  /ws/*      → WebSocket (port 8099)              │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              MQTT Discovery (Optional)                 │ │
│  │  • Auto-register sensors in Home Assistant            │ │
│  │  • Real-time sensor updates                           │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                          ▲
                          │ ADB Protocol
                          │ (USB or TCP/IP)
                          ▼
              ┌─────────────────────────┐
              │   Android Device        │
              │   (ADB enabled)         │
              │   API Level 21+         │
              └─────────────────────────┘
```

---

## 📁 Project Structure

```
visual_mapper/
├── .build-version              # Version source of truth
├── config.yaml                 # Home Assistant addon config
├── Dockerfile                  # Container build
├── docker-compose.yml          # Production deployment
├── docker-compose.dev.yml      # Development environment
├── nginx.conf                  # Reverse proxy config
├── requirements.txt            # Python dependencies
│
├── server.py                   # Backend entry point
├── adb_bridge.py               # ADB protocol implementation
│
├── www/                        # Frontend (static files)
│   ├── index.html              # Landing page (redirects to main.html)
│   ├── main.html               # Dashboard
│   ├── devices.html            # Device management
│   ├── sensors.html            # Sensor management
│   ├── actions.html            # Action automation
│   ├── diagnostic.html         # System diagnostics
│   ├── dev.html                # Developer tools
│   ├── setup.html              # Initial setup wizard
│   │
│   ├── css/
│   │   ├── styles.css          # Main styles
│   │   └── dark-theme.css      # Dark mode
│   │
│   ├── js/
│   │   ├── init.js             # Module loader & initialization
│   │   │
│   │   └── modules/            # ES6 Modules (dual export pattern)
│   │       ├── api-client.js           # REST API wrapper
│   │       ├── event-bus.js            # Event system
│   │       ├── device-manager.js       # Device connection/state
│   │       ├── screenshot-capture.js   # Screenshot handling
│   │       ├── overlay-renderer.js     # Canvas overlay drawing
│   │       ├── coordinate-mapper.js    # Display↔Screenshot coords
│   │       ├── sensor-manager.js       # Sensor CRUD
│   │       ├── action-manager.js       # Action automation
│   │       └── websocket-client.js     # WebSocket connection
│   │
│   └── components/             # Reusable UI components
│       ├── nav-menu.html       # Navigation bar
│       ├── modal.html          # Modal dialog template
│       └── loading.html        # Loading spinner
│
├── tests/                      # Test suite
│   ├── unit/                   # Unit tests (Jest/pytest)
│   │   ├── js/                 # JavaScript unit tests
│   │   │   ├── api-client.test.js
│   │   │   ├── coordinate-mapper.test.js
│   │   │   └── ...
│   │   │
│   │   └── python/             # Python unit tests
│   │       ├── test_adb_bridge.py
│   │       ├── test_server.py
│   │       └── ...
│   │
│   ├── integration/            # Integration tests
│   │   ├── test_api_endpoints.py
│   │   ├── test_websocket.py
│   │   └── ...
│   │
│   └── e2e/                    # End-to-end tests (Playwright)
│       ├── navigation.spec.js
│       ├── screenshot-capture.spec.js
│       ├── live-stream.spec.js
│       └── ...
│
├── docs/                       # Documentation (these files!)
│   ├── PROJECT_OVERVIEW.md
│   ├── 00_START_HERE.md
│   ├── 01_CLAUDE_PERMISSIONS_SETUP.md
│   ├── 02_QUICK_START_GUIDE.md
│   ├── 10_SYSTEM_ARCHITECTURE.md     ← YOU ARE HERE
│   ├── 11_FRONTEND_MODULES.md
│   ├── 12_BACKEND_API.md
│   ├── 20-25_CODE_PATTERN_*.md
│   ├── 30-31_LIVE_STREAMING_*.md
│   ├── 40-42_TESTING_*.md
│   ├── 50-51_API_*.md
│   └── 60-61_*.md
│
├── .git/
│   └── hooks/
│       └── pre-commit          # Version sync automation
│
├── .vscode/
│   ├── devcontainer.json       # VS Code devcontainer
│   └── settings.json           # Project settings
│
└── .github/
    └── workflows/
        ├── tests.yml           # CI/CD pipeline
        └── release.yml         # Release automation
```

**Total Files (Target):** ~140 files
**Total Lines of Code (Target):** ~15,000 lines

---

## 🎨 Frontend Architecture

### **Technology Choices**

| Technology | Choice | Reason |
|------------|--------|--------|
| Framework | None (Vanilla JS) | Simplicity, no build process, small bundle |
| Module System | ES6 Modules | Native browser support, tree-shaking |
| UI Library | None | Custom lightweight components |
| State Management | EventBus pattern | Simple pub/sub for component communication |
| Styling | Plain CSS | No preprocessor needed for this scale |
| Build Process | None | Direct deployment, cache busting via version |

### **Module System (ES6 + Global)**

Visual Mapper uses a **dual export pattern**:

```javascript
// modules/example.js

class ExampleModule {
    constructor() {
        this.data = [];
    }

    init() {
        console.log('[ExampleModule] Initialized');
    }
}

// ES6 export (for main window imports)
export default ExampleModule;

// Global export (for popups, legacy code, dynamic loading)
window.ExampleModule = ExampleModule;
```

**Why dual exports?**
- ES6 modules don't share scope with popup windows
- Allows gradual migration from legacy code
- Enables dynamic loading when needed
- Maintains tree-shaking benefits

**⚠️ Warning:** This pattern is from legacy code - test it works in your environment before relying on it.

### **Initialization Sequence**

```javascript
// www/js/init.js (simplified reference - NOT guaranteed to work)

const APP_VERSION = '0.0.1';
const MODULES = [
    'modules/api-client.js',
    'modules/event-bus.js',
    'modules/device-manager.js',
    'modules/screenshot-capture.js',
    'modules/overlay-renderer.js',
    'modules/coordinate-mapper.js',
    'modules/sensor-manager.js',
    'modules/action-manager.js',
    'modules/websocket-client.js'
];

async function initApp() {
    console.log(`[Init] Starting Visual Mapper ${APP_VERSION}`);

    // Load all modules
    const startTime = performance.now();

    for (const modulePath of MODULES) {
        try {
            await import(`./${modulePath}?v=${APP_VERSION}`);
            console.log(`[Init] ✅ Loaded ${modulePath}`);
        } catch (error) {
            console.error(`[Init] ❌ Failed to load ${modulePath}:`, error);
        }
    }

    const loadTime = performance.now() - startTime;
    console.log(`[Init] All modules loaded in ${loadTime.toFixed(2)}ms`);

    // Initialize modules (if they have init methods)
    if (window.ApiClient) window.apiClient = new window.ApiClient();
    if (window.EventBus) window.eventBus = new window.EventBus();
    if (window.DeviceManager) window.deviceManager = new window.DeviceManager();

    console.log('[Init] ✅ Initialization complete');
}

// Start when DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
```

**⚠️ This is reference code from legacy system - validate it works before using!**

### **State Management (EventBus Pattern)**

```javascript
// modules/event-bus.js (reference pattern - test before using)

class EventBus {
    constructor() {
        this.listeners = new Map();
    }

    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    off(event, callback) {
        if (!this.listeners.has(event)) return;
        const callbacks = this.listeners.get(event);
        const index = callbacks.indexOf(callback);
        if (index > -1) {
            callbacks.splice(index, 1);
        }
    }

    emit(event, data) {
        if (!this.listeners.has(event)) return;
        this.listeners.get(event).forEach(callback => {
            try {
                callback(data);
            } catch (error) {
                console.error(`[EventBus] Error in ${event} handler:`, error);
            }
        });
    }
}

export default EventBus;
window.EventBus = EventBus;
```

**Usage Example:**
```javascript
// Device connected event
eventBus.emit('device:connected', { serial: '192.168.1.100:5555' });

// Listen for device events
eventBus.on('device:connected', (data) => {
    console.log('Device connected:', data.serial);
    updateDeviceList();
});
```

---

## 🔧 Backend Architecture

### **Technology Choices**

| Technology | Choice | Reason |
|------------|--------|--------|
| Framework | FastAPI | Async support, automatic OpenAPI docs, fast |
| ADB Library | adb-shell (pure Python) | No binary dependencies, works in containers |
| WebSocket | FastAPI WebSocket | Built-in, async, reliable |
| Database | None (state in memory) | Simple, fast, stateless addon |
| Config Storage | YAML files | Human-readable, HA standard |

### **API Structure**

```python
# server.py (simplified reference - test before using)

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import asyncio

app = FastAPI(
    title="Visual Mapper API",
    version="0.0.1"
)

# Serve frontend
app.mount("/", StaticFiles(directory="www", html=True), name="www")

# API endpoints
@app.get("/api/adb/devices")
async def list_devices():
    """List connected Android devices"""
    try:
        devices = await adb_bridge.get_devices()
        return {"devices": devices}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/api/adb/screenshot")
async def capture_screenshot(device_id: str):
    """Capture screenshot from device"""
    try:
        screenshot_bytes = await adb_bridge.capture_screenshot(device_id)
        elements = await adb_bridge.get_ui_elements(device_id)

        return {
            "screenshot": base64.b64encode(screenshot_bytes).decode(),
            "elements": elements,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# WebSocket for live streaming
@app.websocket("/ws/stream/{device_id}")
async def stream_endpoint(websocket: WebSocket, device_id: str):
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

            # Control frame rate
            await asyncio.sleep(1/30)  # 30 FPS

    except WebSocketDisconnect:
        print(f"[WebSocket] Client disconnected: {device_id}")
```

**⚠️ This is simplified reference code - actual implementation needs error handling, connection pooling, rate limiting, etc.**

### **ADB Bridge Architecture**

```python
# adb_bridge.py (reference structure - validate before using)

from adb_shell.adb_device import AdbDeviceTcp, AdbDeviceUsb
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
import xml.etree.ElementTree as ET

class ADBBridge:
    def __init__(self):
        self.devices = {}  # {device_id: AdbDevice}
        self.signers = []  # RSA signers for auth

    async def connect_device(self, host, port=5555):
        """Connect to Android device via TCP/IP"""
        device_id = f"{host}:{port}"

        try:
            device = AdbDeviceTcp(host, port, default_transport_timeout_s=9.)
            device.connect(rsa_keys=self.signers, auth_timeout_s=0.1)

            self.devices[device_id] = device
            return device_id
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {device_id}: {e}")

    async def capture_screenshot(self, device_id):
        """Capture PNG screenshot from device"""
        device = self.devices.get(device_id)
        if not device:
            raise ValueError(f"Device not connected: {device_id}")

        # Execute screencap command
        result = device.shell("screencap -p", decode=False)
        return result

    async def get_ui_elements(self, device_id):
        """Extract UI element hierarchy using uiautomator"""
        device = self.devices.get(device_id)
        if not device:
            raise ValueError(f"Device not connected: {device_id}")

        # Dump UI hierarchy
        xml_str = device.shell("uiautomator dump /dev/tty")

        # Parse XML
        root = ET.fromstring(xml_str)
        elements = []

        for node in root.iter('node'):
            element = {
                'text': node.get('text', ''),
                'resource_id': node.get('resource-id', ''),
                'class': node.get('class', ''),
                'bounds': self._parse_bounds(node.get('bounds', '')),
                'clickable': node.get('clickable') == 'true',
                'visible': node.get('visible-to-user') == 'true'
            }
            elements.append(element)

        return elements

    def _parse_bounds(self, bounds_str):
        """Parse bounds string '[x1,y1][x2,y2]' to {x, y, width, height}"""
        import re
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
```

**⚠️ Legacy reference code - may have bugs, test thoroughly!**

---

## 🌊 Data Flow

### **Screenshot Capture Flow**

```
User clicks "Capture Screenshot"
    ↓
Frontend: screenshot-capture.js
    ↓
POST /api/adb/screenshot
    ↓
Backend: server.py → adb_bridge.py
    ↓
ADB Command: screencap -p
    ↓
Android Device returns PNG bytes
    ↓
Backend: Parse PNG + Extract UI elements
    ↓
Return JSON: {screenshot: base64, elements: [...]}
    ↓
Frontend: Render on Canvas + Draw overlays
    ↓
User sees screenshot with clickable element boxes
```

### **Live Streaming Flow (Target Architecture)**

```
User clicks "Live View"
    ↓
Frontend: WebSocket connection to /ws/stream/{device_id}
    ↓
Backend: Accept WebSocket connection
    ↓
Start streaming loop (30 FPS):
    │
    ├─→ Capture screenshot via ADB
    ├─→ Extract UI elements via uiautomator
    ├─→ Send frame over WebSocket
    ├─→ Wait 33ms (30 FPS)
    └─→ Repeat
    ↓
Frontend: Receive frames
    ↓
Render on Canvas with overlays
    ↓
User sees live stream with interactive UI elements
```

**Note:** This is the TARGET architecture. Live streaming needs WebRTC integration for better performance (see 30_LIVE_STREAMING_RESEARCH.md).

### **Sensor Creation Flow**

```
User draws box on screenshot
    ↓
Frontend: coordinate-mapper.js converts display → screenshot coords
    ↓
POST /api/sensors/create
Body: {
    name: "Battery Percentage",
    device_id: "192.168.1.100:5555",
    bounds: {x: 100, y: 50, width: 80, height: 30},
    type: "text",
    refresh_interval: 60
}
    ↓
Backend: Create sensor definition
    ↓
MQTT Discovery: Publish sensor to Home Assistant
    ↓
Home Assistant: Sensor appears in entity list
    ↓
Periodic Updates:
    ├─→ Capture screenshot
    ├─→ Extract text from bounds
    ├─→ Publish MQTT update
    └─→ HA updates sensor state
```

---

## 🔐 Security Considerations

### **ADB Security**

- **Never expose ADB port (5555) publicly** - Local network only
- **Use ADB authentication** - RSA key pairs for device authorization
- **Validate all commands** - Sanitize inputs before shell execution
- **Rate limiting** - Prevent DoS via excessive screenshot requests

### **Web Security**

- **HTTPS only in production** - Use HA's ingress for SSL
- **CORS policies** - Restrict API access to HA ingress domain
- **Input validation** - Sanitize all user inputs
- **No credentials in code** - Use environment variables

### **Container Security**

- **Run as non-root** - Drop privileges in Dockerfile
- **Minimal base image** - Use Alpine Linux for smaller attack surface
- **No secrets in logs** - Redact sensitive data
- **Read-only filesystem** - Where possible

---

## 📊 Performance Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| Page Load Time | <500ms | Fast initial render |
| Screenshot Latency | <200ms | Responsive feel |
| Live Stream FPS | 30 FPS | Smooth video |
| Live Stream Latency | <100ms | Real-time interaction |
| API Response Time | <100ms | Snappy UI |
| Module Load Time | <150ms | Quick initialization |
| Memory Usage | <256MB | HA addon efficiency |
| CPU Usage (idle) | <5% | Low background load |

---

## 🧪 Testing Strategy

### **Test Pyramid**

```
           /\
          /  \         E2E Tests (Slow, High Confidence)
         /    \        - Full user workflows
        /------\       - Browser automation
       /        \      - 10-20 tests
      /          \
     /------------\    Integration Tests (Medium Speed)
    /              \   - API endpoint tests
   /                \  - WebSocket tests
  /------------------\ - 30-50 tests
 /                    \
/______________________\ Unit Tests (Fast, Many)
                         - Module function tests
                         - Pure function tests
                         - 100+ tests
```

**Test Coverage Target:** >60% overall, >80% for critical paths

See: [41_TESTING_PLAYWRIGHT.md](41_TESTING_PLAYWRIGHT.md) and [42_TESTING_JEST_PYTEST.md](42_TESTING_JEST_PYTEST.md)

---

## 🔄 Deployment Architecture

### **Development Environment**

```
Docker Compose (dev):
- Visual Mapper container (with hot reload)
- Mock Home Assistant
- Test database (if needed)
- Playwright test runner
```

### **Production Environment**

```
Home Assistant Supervisor:
- Visual Mapper addon container
- Real Home Assistant
- MQTT broker (optional)
```

### **CI/CD Pipeline**

```
GitHub Actions:
1. Run tests on every PR
2. Build Docker image on merge to develop
3. Tag release on merge to master
4. Publish to GitHub Container Registry
```

---

## 📝 Next Steps

Now that you understand the system architecture:

1. **Frontend Modules** → Read [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md)
2. **Backend API** → Read [12_BACKEND_API.md](12_BACKEND_API.md)
3. **Working Patterns** → Read files 20-25 (with disclaimer: test before using!)

---

## 📖 Related Documentation

- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Project goals and vision
- [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md) - Frontend architecture details
- [12_BACKEND_API.md](12_BACKEND_API.md) - Backend API details
- [60_SOLID_PRINCIPLES.md](60_SOLID_PRINCIPLES.md) - Architecture principles

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.1.0

**Read Next:** [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md)
**Read Previous:** [02_QUICK_START_GUIDE.md](02_QUICK_START_GUIDE.md)
