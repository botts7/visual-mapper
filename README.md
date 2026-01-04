# Visual Mapper

**Transform any Android device into a Home Assistant-integrated automation platform.**

[![Tests](https://img.shields.io/badge/tests-128%20passing-brightgreen.svg)](https://github.com/YOUR_USERNAME/visual-mapper/actions)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![Android](https://img.shields.io/badge/android-11%2B-green.svg)](https://developer.android.com)
[![Home Assistant](https://img.shields.io/badge/home%20assistant-ready-41BDF5.svg)](https://www.home-assistant.io/)

---

## What is Visual Mapper?

Visual Mapper is an open-source system that lets you **monitor, control, and automate** Android devices directly from Home Assistant. Think of it as an open-source alternative to Vysor or AirDroid, but designed specifically for home automation.

**Use Cases:**
- Create Home Assistant sensors from any Android app's UI (battery, media status, notifications)
- Automate repetitive tasks on tablets, phones, or Android-based devices
- Build custom dashboards that interact with Android devices
- Control legacy devices that only have Android apps (thermostats, cameras, etc.)

---

## The Hybrid Architecture

Visual Mapper uses a **three-component hybrid architecture** for maximum flexibility and power:

```
+-------------------+      HTTP/MQTT      +-------------------+
|   Android App     | <----------------> |   Python Server   |
| (Companion App)   |                    |    (FastAPI)      |
+-------------------+                    +-------------------+
        |                                         |
        | Accessibility                           | ML Training
        | Service                                 | (Optional)
        v                                         v
+-------------------+                    +-------------------+
|  Android Device   |                    |   ML Service      |
|   UI Elements     |                    |  (TensorFlow)     |
+-------------------+                    +-------------------+
```

| Component | Role | Technology |
|-----------|------|------------|
| **Android Companion App** | Captures UI state, executes actions, streams data | Kotlin, Accessibility Service |
| **Python Server** | Orchestrates flows, manages sensors, serves web UI | FastAPI, ADB, MQTT |
| **ML Service** (Optional) | Learns UI patterns for robust element detection | TensorFlow, scikit-learn |

**Why Hybrid?**
- **Android App** provides real-time access to UI elements via Accessibility Service
- **Python Server** handles complex logic, persistence, and Home Assistant integration
- **ML Service** improves reliability by learning to identify UI elements across app updates

---

## Quick Start

### Prerequisites
- Python 3.11 or higher
- Android device with Developer Options enabled
- Both devices on the same network

### 1. Clone and Install

```bash
git clone https://github.com/YOUR_USERNAME/visual-mapper.git
cd visual-mapper
pip install -r requirements.txt
```

### 2. Start the Server

```bash
python server.py
```

The web UI is now available at `http://localhost:8080`

### 3. Connect Your Android Device

**Option A: Install the Companion App (Recommended)**
1. Build the APK: `cd android-companion && ./gradlew assembleDebug`
2. Install: `adb install -r app/build/outputs/apk/debug/app-debug.apk`
3. Open the app and enter your server URL: `http://YOUR_COMPUTER_IP:8080`

**Option B: ADB Connection (No App Required)**
1. Enable USB Debugging on your Android device
2. Connect via USB or enable Wireless ADB
3. Navigate to `http://localhost:8080/devices.html`
4. Click "Add Device" and follow the prompts

---

## Running Tests

Visual Mapper has comprehensive test coverage with **128 automated tests** across:
- Python backend (FastAPI, ADB, MQTT)
- Frontend E2E (Playwright)
- JavaScript unit tests (Jest)

### Run the Full Test Suite

```bash
# Install Playwright browsers (first time only)
playwright install chromium

# Start the server in background (required for E2E tests)
python server.py &

# Run all tests
python -m pytest tests/ -v
```

### Run Specific Test Categories

```bash
# Backend unit tests only
python -m pytest tests/unit/ -v

# E2E tests only
python -m pytest tests/e2e/ -v

# With coverage report
python -m pytest tests/ -v --cov=. --cov-report=html
```

---

## Features

### Implemented

| Feature | Description | Status |
|---------|-------------|--------|
| **Screenshot Capture** | Real-time device screenshots with element detection | Stable |
| **Device Control** | Tap, swipe, type, scroll on devices | Stable |
| **Sensor Creation** | Create HA sensors from any UI element | Stable |
| **MQTT Integration** | Auto-discovery and state publishing | Stable |
| **Flow Automation** | Record and replay multi-step interactions | Stable |
| **Multi-Device** | Manage multiple Android devices | Stable |
| **WiFi ADB** | Wireless connection (Android 11+) | Stable |
| **Network Discovery** | Auto-scan for Android devices | Stable |
| **Dark Mode** | Theme toggle with system preference | Stable |

### Coming Soon

- Live device streaming with interactive overlays
- Plugin system for custom sensors and actions
- Official Home Assistant Add-on packaging
- Voice assistant integration

---

## Documentation

| Document | Description |
|----------|-------------|
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | Complete project context and architecture |
| [CONTRIBUTING.md](docs/architecture/61_CONTRIBUTING.md) | How to contribute |
| [MANUAL_RELEASE_TEST.md](MANUAL_RELEASE_TEST.md) | Manual testing checklist |
| [docs/](docs/) | Full documentation directory |

### For Developers

```
docs/
├── essential/          # Quick start guides
├── architecture/       # System design and patterns
├── guides/            # User and developer guides
├── reference/         # API reference
└── planning/          # Roadmap and plans
```

---

## Project Structure

```
visual-mapper/
├── server.py              # Main FastAPI server
├── www/                   # Web UI (HTML, CSS, JS)
├── android-companion/     # Android app (Kotlin)
├── tests/                 # Test suite (128 tests)
│   ├── unit/             # Unit tests
│   ├── e2e/              # End-to-end tests
│   └── integration/      # Integration tests
├── routes/               # API route handlers
├── utils/                # Utility modules
├── services/             # Business logic services
└── docs/                 # Documentation
```

---

## Environment Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key settings:
```ini
# Connection monitoring
CONNECTION_CHECK_INTERVAL=30      # Health check frequency (seconds)
CONNECTION_MAX_RETRY_DELAY=300    # Max reconnection delay (seconds)
CONNECTION_RETRY_ENABLED=true     # Auto-reconnect on disconnect
```

---

## Contributing

We welcome contributions! Please read our [Contributing Guide](docs/architecture/61_CONTRIBUTING.md) before submitting a pull request.

**Quick contribution checklist:**
- [ ] Fork the repository
- [ ] Create a feature branch
- [ ] Write tests for your changes
- [ ] Ensure all tests pass: `python -m pytest tests/ -v`
- [ ] Submit a pull request

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Acknowledgments

- [Home Assistant](https://www.home-assistant.io/) community
- [scrcpy](https://github.com/Genymobile/scrcpy) for inspiration
- Android Debug Bridge (ADB) developers

---

## Support

- **Issues:** [GitHub Issues](https://github.com/YOUR_USERNAME/visual-mapper/issues)
- **Discussions:** [GitHub Discussions](https://github.com/YOUR_USERNAME/visual-mapper/discussions)

---

**Version:** 1.0.0 | **Tests:** 128 Passing | **License:** MIT
