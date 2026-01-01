# Visual Mapper

**Home Assistant Addon for Android Device Monitoring & Automation**

![Version](https://img.shields.io/badge/version-0.0.12-blue.svg)
![Status](https://img.shields.io/badge/status-in_development-yellow.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

---

## 🎯 What is Visual Mapper?

Visual Mapper is an open-source Home Assistant addon that lets you monitor, control, and automate Android devices directly from your Home Assistant dashboard.

**Think:** Open-source alternative to Vysor/AirDroid, built for Home Assistant.

---

## ✨ Features

### **Implemented (v0.0.5)**
- ✅ **Screenshot Capture** - Real-time device screenshots with UI element detection
- ✅ **Device Control** - Tap, swipe, type, and text input on devices
- ✅ **Sensor Creation** - Create Home Assistant sensors from Android UI elements
- ✅ **MQTT Integration** - Auto-discovery and state publishing to Home Assistant
- ✅ **Flow System** - Automated multi-step device interactions
- ✅ **Action Management** - Save and execute device actions
- ✅ **Multi-Device Support** - Manage multiple Android devices simultaneously
- ✅ **WiFi ADB** - Wireless connection with pairing support (Android 11+)
- ✅ **Network Device Discovery** - Auto-scan network for Android devices with version detection
- ✅ **Smart Connection Method** - Automatic Android version detection and connection recommendations
- ✅ **Performance Optimization** - 30-50% faster operations with batching and caching
- ✅ **App Management** - Browse and launch apps with icon support
- ✅ **Dark Mode** - Theme toggle with system preference detection

### **In Progress**
- 🚧 Testing Infrastructure - E2E, unit, and integration tests
- 🚧 Performance Metrics - Monitoring endpoints and dashboards

### **Planned (v1.0.0)**
- 🔌 Live device streaming with interactive overlays
- 🔌 Plugin system for custom sensors and actions
- 🔌 Home Assistant Add-on packaging
- 🔌 Advanced flow recording and playback

---

## 🚀 Quick Start

### **Prerequisites**
- Home Assistant OS or Supervised
- Android device with ADB enabled
- Network access between HA and Android device

### **Installation**
1. Add this repository to Home Assistant Addons
2. Install "Visual Mapper" addon
3. Configure device IP address
4. Start the addon

---

## 📖 Documentation

**For Users:**
- [Installation Guide](docs/installation.md) *(Coming soon)*
- [User Guide](docs/user-guide.md) *(Coming soon)*
- [FAQ](docs/faq.md) *(Coming soon)*

**For Developers:**
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Complete context
- [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) - 7-phase build plan
- [docs/essential/00_START_HERE.md](docs/essential/00_START_HERE.md) - Documentation navigation
- [docs/guides/CLAUDE_START_PROMPT.md](docs/guides/CLAUDE_START_PROMPT.md) - Quick start for Claude sessions
- [docs/architecture/61_CONTRIBUTING.md](docs/architecture/61_CONTRIBUTING.md) - Contribution guide
- [docs/reference/ADB_PERFORMANCE_ENHANCEMENTS.md](docs/reference/ADB_PERFORMANCE_ENHANCEMENTS.md) - Performance optimization guide

---

## 🏗️ Development Status

**Current Version:** 0.0.12
**Next Milestone:** v0.0.6 (Testing Infrastructure)
**Status:** Phase 4 Complete + Performance Enhancements

### **Roadmap**

- ✅ **Phase 0:** Foundation (v0.0.1) - Complete
- ✅ **Phase 1:** Screenshot Capture (v0.0.2) - Complete
- ✅ **Phase 2:** Device Control (v0.0.3) - Complete
- ✅ **Phase 3:** Sensor Creation (v0.0.4) - Complete
- ✅ **Phase 4:** MQTT Integration (v0.0.5) - Complete
- ✅ **Performance Phase 1:** 30-50% improvement - Complete
- 🚧 **Phase 5:** Testing Infrastructure (v0.0.6) - In Progress
- ⏳ **Phase 6:** HA Add-on Packaging (v0.1.0)
- ⏳ **Phase 7:** Community Release (v1.0.0)

**Recent Achievement:** Implemented Phase 1 performance optimizations with 30-50% speed improvements across sensor updates, MQTT publishing, and flow execution.

See [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) for detailed tasks.

---

## 🛠️ Technology Stack

**Frontend:**
- HTML5 + CSS3
- ES6 Modules (dual export pattern)
- Canvas API for rendering

**Backend:**
- Python 3.11+
- FastAPI (async web framework)
- adb-shell (pure Python ADB)

**Testing:**
- Playwright (E2E)
- Jest (JavaScript unit tests)
- pytest (Python unit tests)

**Deployment:**
- Docker
- Home Assistant Supervisor
- nginx reverse proxy

---

## 🤝 Contributing

We welcome contributions! Please see [docs/architecture/61_CONTRIBUTING.md](docs/architecture/61_CONTRIBUTING.md) for guidelines.

**Ways to contribute:**
- 🐛 Report bugs
- 💡 Suggest features
- 📝 Improve documentation
- 🔧 Submit pull requests
- 🔌 Create plugins

---

## 📜 License

MIT License - see [LICENSE](LICENSE) for details.

By contributing, you agree to license your contributions under the same license.

---

## 🙏 Acknowledgments

- Home Assistant community
- Android Debug Bridge (ADB) developers
- scrcpy and ws-scrcpy projects for inspiration

---

## 📞 Support

- **GitHub Issues:** [Report bugs or request features](https://github.com/yourusername/visual-mapper/issues)
- **GitHub Discussions:** [Ask questions or share ideas](https://github.com/yourusername/visual-mapper/discussions)
- **Home Assistant Forum:** *(Coming soon)*

---

## ⚠️ Development Notice

This project is currently in active development (v0.0.5). Core features are functional but the project is not yet production-ready.

**Status:** Beta testing phase - suitable for development/testing environments only.

**Current Capabilities:**
- ✅ Stable screenshot capture and device control
- ✅ Functional sensor creation and MQTT integration
- ✅ Working flow automation system
- 🚧 Testing infrastructure in progress
- ⏳ Official HA Add-on packaging pending

---

**Last Updated:** 2025-12-27
**Current Version:** 0.0.12
**Status:** 🚀 Phase 4 Complete + Performance Enhanced
