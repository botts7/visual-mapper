# Changelog

## 0.2.70

- Feature: Q-table ML training now learns from ALL navigation sources
- Navigation Learn page transitions now update Q-table via MQTT
- Flow Wizard (step 3) transitions now update Q-table via MQTT
- Rewards: +1.0 for new screen navigation, -0.5 for same-screen taps
- Source tagged as "navigation_learn" to distinguish from Android companion app

## 0.2.69

- Fix: Element overlay mismatch in polling mode (splash screen showing with next screen's elements)
- Backend detects screen changes during screenshot+elements capture
- If activity changes during capture, elements are cleared to prevent mismatch
- Frontend handles screen_changed flag and triggers immediate retry

## 0.2.68

- Fix: Smart Suggestions false positives - "BYD SEALION 7" no longer becomes "7 A"
- Short indicators (like "a" for amps) now require word boundaries
- Unit assignment only happens with strong indicator matches
- UI: Replaced "Also try:" buttons with cleaner dropdown selector
- Dropdown shows sensor name options with location icons

## 0.2.67

- Fix: Home screen tagging now properly clears old home flag when new home is selected
- Fix: Only one screen can be marked as home (no more multiple home icons)
- ML Server auto-start now persists across app restarts
- Fix: Screens dropdown no longer gets cut off by panel overflow
- Dropdown now uses fixed positioning to escape parent overflow:hidden

## 0.2.66

- Canvas now defaults to fit-height (shows full device screen without horizontal stretching)
- Companion app integration for fast UI element fetching (100-300ms vs 1-3s)
- Automatic fallback to ADB uiautomator when companion app unavailable
- Stream quality default changed from 'medium' to 'fast' for better WiFi compatibility
- Lower resolution (360p) + higher FPS target = more responsive on slow connections

## 0.2.42-0.2.65

- Fix Play Store icon cache path issue in addon (use DATA_DIR instead of hardcoded 'data/')
- Fix element overlay misalignment on screen change (clear immediately, not after stabilization)
- Progressive icon/name refresh improvements
- Black formatting on Python files
- Various bug fixes and performance improvements

## 0.2.41

- Consolidate Smart Suggestions to inline tab (removed modal overlay)
- Smart Suggestions button now switches to Suggestions tab instead of opening modal
- Added "Also try:" alternative name buttons to inline suggestions
- Hover over suggestion to highlight element on screenshot
- Auto-refresh icons when background prefetch completes
- Auto-refresh app names when background prefetch completes
- Queue stats polling starts automatically on Step 2 load
- Centralized version management via utils/version.py

## 0.2.37-0.2.40

- Fix version display issues (centralized APP_VERSION from .build-version)
- Remove hardcoded versions from main.py, health.py, performance.py, mqtt_manager.py
- Fix frontend/backend sync between repos
- Docker cache busting improvements

## 0.2.36

- Version sync fixes
- Module import cache busting updates

## 0.2.35

- MAJOR: Embed code directly in addon repo (no more git clone during build)
- Fixes deployment caching issues - what you push is what gets deployed
- Fix Play Store icon/name fetching (asyncio.to_thread() for blocking calls)
- Smart Suggestions: "Also try" alternatives and hover highlight working

## 0.2.34

- Fix Play Store icon/name fetching (blocking sync calls in async context)
- Wrap google_play_scraper calls with asyncio.to_thread() to prevent event loop blocking
- Icons and app names now fetch correctly in background workers

## 0.2.31

- Update ALL JS module imports for complete cache bust
- Pre-commit hook now auto-updates all ?v= params
- Fixes "Also try" alternatives and hover highlight features

## 0.2.30

- Add missing hover-highlight CSS for smart suggestions
- Fix smart suggestions hover-to-highlight on screenshot
- Update module import versions for cache busting

## 0.2.28

- Fix app icons not loading while in flow wizard (wizard was blocking icon fetch)
- Allow Play Store icon fetch to continue during wizard (only skip APK extraction)
- Icons now load while browsing apps in step 2

## 0.2.27

- Fix browser caching of flow wizard modules (update all import versions)
- Ensures "Also try" alternatives and hover highlights load correctly

## 0.2.26

- Fix smart suggestions not showing alternative names (module cache bust)
- Add icon prefetch when flow wizard step 2 loads
- Fix screens dropdown text clipping in step 3

## 0.2.25

- Fix ML Training Server not starting (add paho-mqtt 1.6.1 dependency)
- Fix Set Home Screen not clearing previous home screen
- Fix element property names for smart suggestions (resource_id, content_desc)

## 0.2.24

- Fix Learn Navigation duplicate screens issue (hash mismatch)
- Fix Set Home Screen button not working (API parameter issue)
- Skip splash screens when auto-setting home screen
- Improve feedback during learn mode (pause/resume status)

## 0.2.23

- Hover over suggestion to highlight element on screenshot
- Add edit button for capture_sensors steps in flow review
- Click to edit linked sensor directly from flow step

## 0.2.22

- Add multiple name suggestions for smart sensors
- Show "Also try" alternatives when auto-detected name is wrong
- Click alternative to swap names (above/below/left sources shown)

## 0.2.21

- Fix false navigation warnings for splash→main screen transitions
- Auto-prefetch app icons and names on device connection
- Improved flow wizard splash screen detection

## 0.2.20

- Remove Coral TPU from addon (Alpine/musl incompatible with libedgetpu)
- Document Coral limitation (requires Debian-based standalone deployment)

## 0.2.19

- Fix navbar text wrapping (white-space: nowrap)

## 0.2.18

- Version alignment

## 0.2.17

- Auto-start ML server when ml_training_mode is "local"

## 0.2.16

- Add Coral Edge TPU support to Docker container
- Install libedgetpu runtime and pycoral in Dockerfile
- Add libusb and udev for USB device support

## 0.2.14

- Add MQTT username/password arguments to ML server

## 0.2.13

- Fix feature_manager None check in ML imports

## 0.2.12

- Fix ML server standalone mode (feature_manager import optional)
- Show ML start errors in UI
- Fix ML server script path

## 0.2.11

- Show ML start error messages in UI alert

## 0.2.10

- Improved ML server start with logging and error capture
- MQTT auth passed to ML server

## 0.2.9

- Fix ML training server script path

## 0.2.8

- Force Docker cache bust for new files
- Services page now visible in navbar

## 0.2.6

- Add Coral Edge TPU support for ML acceleration
- Hardware accelerator status in Services UI
- ML data export/import/reset from UI

## 0.2.4

- Add ML Training configuration options
- Add translations for ML settings

## 0.2.0

- ML Training Server with multiple deployment options
- Android Companion App support
- Flow sync between server and Android
- Smart screen sleep prevention

## 0.1.x

- Initial releases
- Android device control via ADB
- Sensor creation from UI elements
- MQTT integration with Home Assistant
- Flow automation
- Web UI dashboard
