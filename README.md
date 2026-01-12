# Visual Mapper

**Transform any Android device into a Home Assistant-integrated automation platform.**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![Android](https://img.shields.io/badge/android-11%2B-green.svg)](https://developer.android.com)
[![Home Assistant](https://img.shields.io/badge/home%20assistant-ready-41BDF5.svg)](https://www.home-assistant.io/)
[![Sponsor](https://img.shields.io/badge/sponsor-GitHub%20Sponsors-ea4aaa.svg?logo=github)](https://github.com/sponsors/botts7)

---

## What is Visual Mapper?

Visual Mapper is an open-source system that lets you **monitor, control, and automate** Android devices directly from Home Assistant. Create sensors from any app's UI, automate device interactions, and integrate legacy Android-only devices into your smart home.

**Use Cases:**
- Create Home Assistant sensors from any Android app's UI (battery, media status, notifications)
- Automate repetitive tasks on tablets, phones, or Android-based devices
- Build custom dashboards that interact with Android devices
- Control legacy devices that only have Android apps (thermostats, cameras, etc.)

---

## Architecture

Visual Mapper uses a **hybrid architecture** with three components:

```
+-------------------+      HTTP/MQTT      +-------------------+
|   Android App     | <----------------> |   Python Server   |
| (Companion App)   |                    |    (FastAPI)      |
+-------------------+                    +-------------------+
        |                                         |
        | Accessibility                           | MQTT
        | Service                                 |
        v                                         v
+-------------------+                    +-------------------+
|  Android Device   |                    |  Home Assistant   |
|   UI Elements     |                    |                   |
+-------------------+                    +-------------------+
```

| Component | Role | Technology |
|-----------|------|------------|
| **Python Server** | Orchestrates flows, manages sensors, serves web UI | FastAPI, ADB, MQTT |
| **Android Companion App** | Captures UI state, executes actions locally | Kotlin, Accessibility Service |
| **Home Assistant Add-on** | Easy deployment and integration | Docker |

---

## Quick Start

### Prerequisites
- Python 3.11+
- Android device with Developer Options enabled
- Both devices on the same network

### 1. Clone and Install

```bash
git clone https://github.com/botts7/visual-mapper.git
cd visual-mapper/backend
pip install -r requirements.txt
```

### 2. Start the Server

```bash
python main.py
```

Web UI available at `http://localhost:8080`

### 3. Connect Your Android Device

**Option A: WiFi ADB (Recommended)**
1. Enable Developer Options on your Android device
2. Enable Wireless Debugging (Android 11+)
3. Navigate to `http://localhost:8080/devices.html`
4. Use Network Discovery or enter device IP manually

**Option B: USB ADB**
1. Enable USB Debugging on your Android device
2. Connect via USB cable
3. Device will appear automatically in the web UI

---

## Features

| Feature | Description |
|---------|-------------|
| **Screenshot Capture** | Real-time device screenshots with element detection |
| **Device Control** | Tap, swipe, type, scroll on devices |
| **Sensor Creation** | Create HA sensors from any UI element |
| **MQTT Integration** | Auto-discovery and state publishing to Home Assistant |
| **Flow Automation** | Record and replay multi-step interactions |
| **Flow Wizard** | Visual step-by-step flow creation |
| **Smart Flows** | AI-assisted flow generation from app screens |
| **Multi-Device** | Manage multiple Android devices |
| **WiFi ADB** | Wireless connection (Android 11+) |
| **Network Discovery** | Auto-scan for Android devices |
| **Live Streaming** | Real-time device screen streaming |
| **Dark Mode** | Theme toggle with system preference |

---

## Project Structure

```
visual-mapper/
├── backend/
│   ├── main.py            # FastAPI server entry point
│   ├── core/              # Core modules (ADB, MQTT, sensors, flows)
│   ├── routes/            # API route handlers
│   ├── services/          # Business logic
│   ├── utils/             # Utility modules
│   └── Dockerfile         # Container build
├── frontend/
│   └── www/               # Web UI (HTML, CSS, JS)
├── config/                # Configuration files
└── README.md
```

---

## Related Repositories

| Repository | Description |
|------------|-------------|
| [visual-mapper](https://github.com/botts7/visual-mapper) | Main server application (this repo) |
| [visual-mapper-android](https://github.com/botts7/visual-mapper-android) | Android companion app |
| [visual-mapper-addon](https://github.com/botts7/visual-mapper-addon) | Home Assistant add-on |

---

## Environment Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key settings:
```ini
MQTT_BROKER=localhost
MQTT_PORT=1883
CONNECTION_CHECK_INTERVAL=30
CONNECTION_RETRY_ENABLED=true
```

---

## Docker

```bash
cd backend
docker build -t visual-mapper .
docker run -p 8080:8080 --network host visual-mapper
```

---

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Support

- **Issues:** [GitHub Issues](https://github.com/botts7/visual-mapper/issues)

---

**Version:** 0.2.74 | **License:** MIT
