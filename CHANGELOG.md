# Changelog

All notable changes to the Visual Mapper Home Assistant add-on will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Action creation system for reusable device interactions
- Live streaming mode with <100ms latency
- HA metadata API integration (device classes, icons, units)
- Entity preview before sensor creation
- Template testing for Jinja2 expressions
- Sensor history visualization
- Export/import sensor definitions

## [0.0.6] - 2025-12-23

### Added
- **Testing Infrastructure** (Phase 5 Complete!)
  - Comprehensive test suite: 183+ tests (71 backend + 29 E2E + 83 Jest)
  - GitHub Actions CI/CD pipeline with 7 jobs
  - Pre-commit hooks for code quality (Black, Flake8, Prettier, Bandit)
  - Code coverage reporting with Codecov (~60% overall)
  - Testing documentation (TESTING.md) with examples and troubleshooting
  - E2E tests for navigation and device workflows (gracefully skip without device)
  - Frontend JavaScript unit tests (Jest + Babel)

- **Home Assistant Add-on Packaging**
  - Enhanced config.yaml with HA ingress support
  - Add-on localization (translations/en.yaml)
  - User documentation (DOCS.md) with examples
  - CHANGELOG.md for version tracking

### Changed
- Updated project plan to Phase 6 (HA Add-on Packaging & Polish)
- Overall project progress: 92% (Phases 0-5 complete)

## [0.0.5] - 2025-12-22

### Added
- **MQTT Integration** (Phase 4 Complete!)
  - MQTT auto-discovery for sensors (homeassistant/sensor/...)
  - Background sensor update loop with configurable intervals
  - MQTT state publishing with attributes
  - Availability tracking (online/offline)
  - Support for sensor and binary_sensor types
  - Binary sensor ON/OFF value conversion
  - Error handling and graceful degradation
  - MQTT control endpoints (start/stop/restart updates)
  - 14/14 unit tests for MQTT manager

### Changed
- Deferred MQTT integration tests to Phase 5 (require HA instance)

## [0.0.4] - 2025-12-21

### Added
- **Sensor Creation System** (Phase 3 Complete!)
  - Visual sensor definition via screenshot element selection
  - Element selector module with hover effects and click handling
  - Sensor creator dialog with live preview
  - Text extraction engine with 6 methods + pipeline support
  - Extraction rules: regex, before/after, numeric extraction, unit parsing
  - Sensor storage (JSON files per device)
  - Sensor CRUD operations (create, read, update, delete)
  - Sensor management page (sensors.html) with search/filter
  - Hierarchical dropdowns: Sensor Type → Device Class → Unit/Icon
  - Enable/disable sensor toggle
  - Device class validation and suggestions
  - 38 backend tests (sensor manager + text extraction)

- **Frontend-Backend Parity Improvements**
  - Text extraction preview calls backend API for accurate results
  - Frontend mirrors backend extraction capabilities
  - 78% of parity violations fixed (18/23)

- **Performance Optimizations**
  - Parallel API calls for device list + metadata (5-10x faster)
  - Smart search with auto-loading and live results preview

- **Device Management Enhancements**
  - App list and launch functionality
  - Device metadata display (model name, active app)
  - Icon rendering throughout app (MDI icons)

### Changed
- Manual testing guide created (MANUAL_TESTING_GUIDE.md)
- Backend automated tests: 69/70 passing (98.6% success rate)

## [0.0.3] - 2025-12-20

### Added
- **Device Control System** (Phase 2 Complete!)
  - Interactive canvas with tap, swipe, and text input modes
  - Device control module with coordinate transformation
  - Visual feedback: tap circles, swipe arrows
  - ADB input commands: tap, swipe, type, keyevents
  - Hardware key controls (Home, Back, Recent Apps, Volume)
  - UI element overlay system with green/yellow bounding boxes
  - Overlay filters: clickable/non-clickable/size/text-only
  - Auto-refresh screenshot feature (1s-10s intervals)
  - Smart pause during user interactions
  - Wireless ADB pairing support (Android 11+)

### Fixed
- ADB timeout issues with async locking
- Duplicate request prevention
- Coordinate mapping accuracy (no offset bugs)

## [0.0.2] - 2025-12-19

### Added
- **Screenshot Capture System** (Phase 1 Complete!)
  - ADB connection manager (USB + WiFi)
  - Screenshot capture endpoint (<500ms)
  - UI element extraction via uiautomator
  - Coordinate mapping with scale factor calculation
  - Screenshot display on HTML5 canvas with aspect ratio preservation
  - 22 automated tests (ADB + API integration)

### Changed
- XML parsing for UI hierarchy
- JSON response format for elements (bounds, text, resource-id)

## [0.0.1] - 2025-12-18

### Added
- **Foundation** (Phase 0 Complete!)
  - Project structure with clean architecture
  - Dockerfile with non-root user
  - Nginx reverse proxy (ports 3000, 8099, 8100)
  - Basic HTML skeleton with navigation
  - Cache busting on all file references (`?v=0.0.1`)
  - Version sync git pre-commit hook
  - Single source of truth: `.build-version`
  - Auto-sync to: config.yaml, Dockerfile, HTML, init.js
  - First automated test suite
  - No console errors on any page

### Changed
- Starting from v0.0.1 (fresh rebuild, not legacy v4.6.0-beta.X)

## Legacy v4.6.0-beta.X (Reference Only)

**Note**: Legacy system (v4.6.0-beta.X) is for reference only. This rebuild (v0.0.1+) is a complete rewrite with:
- ✅ Proper testing (183+ tests vs. 0 tests in legacy)
- ✅ Clean architecture
- ✅ No navigation regression
- ✅ No version accumulation bug
- ✅ No module loading failures

**Known Legacy Issues (Avoided in Rebuild)**:
- Navigation broken in late beta versions
- Version numbers accumulated in HTML
- dev.html coordinate offset bug
- Live streaming never worked
- Zero automated tests

---

[Unreleased]: https://github.com/yourusername/visual-mapper/compare/v0.0.6...HEAD
[0.0.6]: https://github.com/yourusername/visual-mapper/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/yourusername/visual-mapper/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/yourusername/visual-mapper/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/yourusername/visual-mapper/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/yourusername/visual-mapper/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/yourusername/visual-mapper/releases/tag/v0.0.1
