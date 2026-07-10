# Visual Mapper - Technical Review Report

**Date:** January 26, 2026
**Version:** 0.4.0-beta (development branch: `beta-auth`)
**Prepared for:** External Team Review

---

## Executive Summary

Visual Mapper is an open-source platform that transforms Android devices into Home Assistant-integrated automation endpoints. It allows users to create sensors from any Android app's UI, automate device interactions, and control legacy Android-only devices from Home Assistant.

**Current State:** Active development with significant new features in beta testing. Core functionality is stable; several advanced features need testing and refinement.

---

## 1. System Architecture

### 1.1 Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │ Flow Wizard │  │   Sensors   │  │   Devices   │  │ Live Stream│ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │
│                     Frontend (HTML/CSS/JS ES6 Modules)               │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ REST API / WebSocket
┌───────────────────────────────┴─────────────────────────────────────┐
│                         PYTHON BACKEND                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ FastAPI  │  │ ADB Core │  │   MQTT   │  │ Streaming│            │
│  │ Routes   │  │  Bridge  │  │ Manager  │  │ Pipeline │            │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │  Flows   │  │ Sensors  │  │ Actions  │  │    ML    │            │
│  │ Engine   │  │ Manager  │  │ Executor │  │ Training │            │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Android Device│     │  Android Device │     │  Home Assistant │
│   (via ADB)   │     │ (Companion App) │     │     (MQTT)      │
└───────────────┘     └─────────────────┘     └─────────────────┘
```

### 1.2 Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Backend | Python, FastAPI, Uvicorn | 3.11+ |
| Frontend | Vanilla JS (ES6 modules), CSS3 | Modern browsers |
| Android | Kotlin, Accessibility Service | Android 11+ |
| Communication | ADB, MQTT, WebSocket, REST | - |
| Container | Docker (Home Assistant Add-on) | - |

### 1.3 Data Flow

1. **Device Connection:** ADB (USB/WiFi) or Companion App (MQTT/HTTP)
2. **Screen Capture:** ADB screencap or Companion MediaProjection
3. **Element Detection:** ADB uiautomator or Companion Accessibility Service
4. **Sensor Updates:** Polling or event-driven via MQTT
5. **Home Assistant:** MQTT auto-discovery publishes sensors/entities

---

## 2. Core Features

### 2.1 Working Well

| Feature | Status | Notes |
|---------|--------|-------|
| **ADB Device Connection** | Stable | USB and WiFi (Android 11+) |
| **Screenshot Capture** | Stable | Multiple backends (adbutils, subprocess) |
| **Element Detection** | Stable | UI tree parsing, bounds extraction |
| **Sensor Creation** | Stable | Text extraction, regex patterns, HA integration |
| **MQTT Publishing** | Stable | Auto-discovery, state updates |
| **Flow Recording** | Stable | Tap, swipe, wait, text input steps |
| **Flow Execution** | Stable | Sequential step execution |
| **Flow Scheduling** | Stable | Interval-based execution |
| **Dark Mode** | Stable | System preference detection |
| **Multi-Device Support** | Stable | Concurrent device management |

### 2.2 Working with Known Issues

| Feature | Status | Known Issues |
|---------|--------|--------------|
| **Live Streaming** | Functional | Reconnection loops when companion stops |
| **Companion App Integration** | Functional | IP matching issues across subnets |
| **Flow Wizard** | Functional | Complex state management in step 3 |
| **Element Overlays** | Functional | Occasional misalignment on rotation |
| **Navigation Learning** | Functional | ML training integration incomplete |

### 2.3 In Development / Needs Testing

| Feature | Status | Notes |
|---------|--------|-------|
| **Prerequisite Flows** | New | Auto-detect missing services, guided setup |
| **Element Watchers** | New | One-click element monitoring |
| **Auto-Sensors** | New | Zero-config common sensors |
| **Region Capture** | New | Screen region to MQTT camera |
| **Command Router** | New | Route commands to companion |
| **Authentication** | Partial | Added to control endpoints, needs audit |

---

## 3. Frontend Pages

| Page | Purpose | Status |
|------|---------|--------|
| `index.html` | Dashboard/landing | Stable |
| `devices.html` | Device management, connection | Stable |
| `sensors.html` | Sensor list, create, edit | Stable |
| `flows.html` | Flow list, execute, schedule | Stable |
| `flow-wizard.html` | Visual flow creation (4 steps) | Functional |
| `live-stream.html` | Real-time device viewing | Functional |
| `actions.html` | Action management | Stable |
| `services.html` | Backend services control | Functional |
| `navigation-learn.html` | App navigation mapping | Beta |
| `performance.html` | Diagnostics and benchmarks | Stable |
| `diagnostic.html` | System diagnostics | Stable |

---

## 4. API Endpoints (32 Route Modules)

### Core Endpoints
- `/api/adb/*` - Device info, control, screenshots, apps
- `/api/sensors/*` - CRUD for sensors
- `/api/flows/*` - CRUD and execution for flows
- `/api/actions/*` - CRUD for actions
- `/api/mqtt/*` - MQTT status and control

### Streaming Endpoints
- `/api/stream/*` - Streaming configuration
- `/ws/stream-mjpeg/{device_id}` - MJPEG WebSocket
- `/ws/stream-mjpeg-v2/{device_id}` - Shared pipeline MJPEG

### New/Beta Endpoints
- `/api/prerequisites/*` - Prerequisite flow management
- `/api/element-watchers/*` - Element watcher CRUD
- `/api/auto-sensors/*` - Auto-sensor discovery
- `/api/region-capture/*` - Region capture management
- `/api/companion/*` - Companion app communication

---

## 5. Known Issues & Technical Debt

### 5.1 Critical Issues

| Issue | Impact | Location |
|-------|--------|----------|
| **Streaming reconnection loop** | UX degradation | `live-stream.js:~390` |
| **Companion IP mismatch** | Companion frames not matched to device | `companion_receiver.py` |
| **WebSocket race conditions** | Stream corruption on rapid start/stop | `streaming.py` |

### 5.2 Medium Priority Issues

| Issue | Impact | Location |
|-------|--------|----------|
| **Large file sizes** | Maintainability | `flow-wizard-step3.js` (257KB) |
| **Memory usage** | Performance on many devices | `mqtt_manager.py` |
| **Auth coverage gaps** | Security | Various route files |
| **Error handling inconsistency** | User confusion | Multiple files |

### 5.3 Technical Debt

1. **Monolithic JS files** - `flow-wizard-step3.js` needs further modularization
2. **Duplicate code** - Stream handling logic in multiple places
3. **Inconsistent error responses** - Some endpoints return different error formats
4. **Missing tests** - Test directories created but sparse coverage
5. **Hardcoded values** - Some timeouts and thresholds not configurable

---

## 6. Security Considerations

### 6.1 Implemented

- Token-based authentication for companion app
- Auth middleware for control endpoints (tap, swipe, etc.)
- CORS configuration (configurable origins)
- WebSocket authentication for streaming

### 6.2 Needs Review

- [ ] Complete auth audit across all endpoints
- [ ] Rate limiting on sensitive endpoints
- [ ] Input validation consistency
- [ ] Secrets management (currently in .env)
- [ ] Log sanitization (device IDs, IPs)

---

## 7. Performance Characteristics

### 7.1 Benchmarks (Typical)

| Operation | ADB (WiFi) | Companion App |
|-----------|------------|---------------|
| Screenshot capture | 300-800ms | 50-150ms |
| Element tree fetch | 1-3s | 100-300ms |
| Tap execution | 50-100ms | 20-50ms |
| Stream latency | 200-500ms | 50-150ms |

### 7.2 Resource Usage

- **Backend memory:** ~150-300MB (varies with devices)
- **CPU:** Low idle, spikes during screenshot/OCR
- **Network:** Depends on streaming quality (1-10 Mbps)

---

## 8. Deployment Options

### 8.1 Home Assistant Add-on (Recommended)
- Docker-based
- Automatic MQTT integration
- Managed by Supervisor

### 8.2 Standalone Docker
```bash
docker build -t visual-mapper .
docker run -p 8080:8080 --network host visual-mapper
```

### 8.3 Direct Python
```bash
cd backend
pip install -r requirements.txt
python main.py
```

---

## 9. Configuration

### 9.1 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MQTT_BROKER` | localhost | MQTT server address |
| `MQTT_PORT` | 1883 | MQTT server port |
| `MQTT_USER` | (none) | MQTT authentication |
| `MQTT_PASSWORD` | (none) | MQTT authentication |
| `DATA_DIR` | data/ | Persistent storage location |
| `CONNECTION_CHECK_INTERVAL` | 30 | Device health check interval (s) |

### 9.2 Key Configuration Files

- `config/settings.json` - Global settings
- `config/sensors/{device_id}.json` - Per-device sensors
- `config/flows/{device_id}/` - Per-device flows
- `config/navigation/{device_id}.json` - Navigation graphs

---

## 10. Testing Status

### 10.1 Test Coverage

| Area | Coverage | Notes |
|------|----------|-------|
| Backend unit tests | Low | `backend/tests/` - scaffolding only |
| Frontend tests | None | `frontend/tests/` - empty |
| Integration tests | None | `tests/` - scaffolding only |
| Manual testing | Primary | See `docs/TESTING_PLAN_v0.4.0-beta.md` |

### 10.2 Recommended Test Areas

1. **Streaming reliability** - Start/stop/reconnect cycles
2. **Multi-device scenarios** - 3+ devices simultaneously
3. **Flow execution edge cases** - Network failures, locked devices
4. **Authentication** - Token validation, expiration
5. **MQTT integration** - HA discovery, state sync

---

## 11. Documentation

| Document | Location | Status |
|----------|----------|--------|
| README | `/README.md` | Current |
| Changelog | `/CHANGELOG.md` | Current |
| Testing Plan | `/docs/TESTING_PLAN_v0.4.0-beta.md` | Draft |
| API Documentation | (None) | Needed |
| User Guide | (None) | Needed |
| Architecture Docs | (None) | Needed |

---

## 12. Recommendations for Review Team

### 12.1 Priority Areas to Review

1. **Streaming pipeline** (`backend/routes/streaming.py`, `frontend/www/js/modules/live-stream.js`)
   - Complex state management
   - WebSocket lifecycle
   - Companion/ADB fallback logic

2. **Flow Wizard Step 3** (`frontend/www/js/modules/flow-wizard-step3.js`)
   - 257KB file, needs modularization assessment
   - State preservation across step navigation
   - Prerequisite check integration

3. **Authentication system** (`backend/routes/auth.py`, route files)
   - Coverage completeness
   - Token handling
   - CORS configuration

4. **MQTT Manager** (`backend/core/mqtt/mqtt_manager.py`)
   - Memory management with many devices
   - Subscription cleanup
   - Thread safety

### 12.2 Questions for Discussion

1. Should the monolithic JS files be split into smaller modules?
2. Is the current auth approach sufficient for production?
3. What test coverage level is acceptable for release?
4. Should WebSocket streaming be replaced with WebRTC?
5. Is the companion app integration architecture scalable?

### 12.3 Suggested Next Steps

1. **Stabilize streaming** - Fix reconnection loops before other work
2. **Complete auth audit** - Document and test all endpoints
3. **Add integration tests** - At minimum for critical paths
4. **API documentation** - Generate OpenAPI/Swagger docs
5. **Performance profiling** - Identify memory leaks and bottlenecks

---

## 13. File Inventory (Uncommitted Changes)

### Modified Files (36)
```
backend/core/adb/adb_bridge.py
backend/core/mqtt/mqtt_manager.py (+876 lines)
backend/core/streaming/companion_receiver.py (+297 lines)
backend/main.py (+111 lines)
backend/routes/streaming.py (+736 lines)
frontend/www/js/modules/flow-wizard-step3.js (+689 lines)
frontend/www/js/modules/live-stream.js (+685 lines)
frontend/www/css/flow-wizard.css (+401 lines)
... and 28 more
```

### New Files (14)
```
backend/core/flows/prerequisite_flows.py
backend/routes/prerequisites.py
backend/routes/element_watchers.py
backend/routes/auto_sensors.py
backend/routes/region_capture.py
backend/core/command_router.py
backend/core/element_watcher.py
backend/core/region_capture.py
backend/services/auto_sensors.py
frontend/www/js/modules/prerequisite-checker.js
frontend/www/js/modules/prerequisite-dialog.js
scripts/run_tests.ps1
scripts/run_tests.sh
```

---

## 14. Contact & Resources

- **Repository:** https://github.com/botts7/visual-mapper
- **Android App:** https://github.com/botts7/visual-mapper-android
- **HA Add-on:** https://github.com/botts7/visual-mapper-addon
- **Issues:** https://github.com/botts7/visual-mapper/issues

---

*Report generated: January 26, 2026*
