# Visual Mapper

**Home Assistant Addon for Android Device Monitoring & Automation**

![Version](https://img.shields.io/badge/version-0.0.3-blue.svg)
![Status](https://img.shields.io/badge/status-in_development-yellow.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

---

## 🎯 What is Visual Mapper?

Visual Mapper is an open-source Home Assistant addon that lets you monitor, control, and automate Android devices directly from your Home Assistant dashboard.

**Think:** Open-source alternative to Vysor/AirDroid, built for Home Assistant.

---

## ✨ Features

### **Current (v0.0.1)**
- 🚧 Project foundation and documentation
- 🚧 Building from scratch using Test-Driven Development

### **Planned (v1.0.0)**
- 📸 Screenshot capture with UI element detection
- 🎮 Device control (tap, swipe, type)
- 📊 HA sensor creation from device UI elements
- 🎥 Live device streaming with interactive overlays
- 🔌 Plugin system for custom sensors and actions
- 📱 Multi-device support

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
- [CLAUDE_START_PROMPT.md](CLAUDE_START_PROMPT.md) - Quick start for Claude sessions
- [00_START_HERE.md](00_START_HERE.md) - Documentation navigation
- [61_CONTRIBUTING.md](61_CONTRIBUTING.md) - Contribution guide

---

## 🏗️ Development Status

**Current Version:** 0.0.3
**Target Version:** 1.0.0
**Status:** Building from scratch

### **Roadmap**

- [ ] **Phase 0:** Foundation (v0.0.1)
- [ ] **Phase 1:** Screenshot Capture (v0.0.2)
- [ ] **Phase 2:** Device Control (v0.0.3)
- [ ] **Phase 3:** Sensor Creation (v0.0.4)
- [ ] **Phase 4:** Live Streaming (v0.0.5)
- [ ] **Phase 5:** Testing Infrastructure (v0.0.6)
- [ ] **Phase 6:** Polish (v0.1.0)
- [ ] **Phase 7:** Community Release (v1.0.0)

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

We welcome contributions! Please see [61_CONTRIBUTING.md](61_CONTRIBUTING.md) for guidelines.

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

This project is currently in early development (v0.0.1). The codebase is being rebuilt from scratch using Test-Driven Development.

**Not ready for production use.**

---

**Last Updated:** 2025-12-21
**Current Version:** 0.0.3
**Status:** 🚧 In Development
