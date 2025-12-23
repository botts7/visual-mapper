# Visual Mapper - Missing Features & Future Enhancements

**Created:** 2025-12-23
**Current Version:** 0.0.5 (Phase 6 Complete)
**Purpose:** Comprehensive documentation of features NOT yet implemented

---

## 🚨 Critical Gap: Sensor Navigation System

### **Problem Statement**

**Current Limitation:** Sensors extract data from whatever screen is currently showing on the device. They do NOT automatically navigate to the correct app or screen.

**Impact:** Sensors will extract garbage data if the target app isn't open when the sensor update runs.

### **What's Missing**

Sensors currently **DO NOT**:
- ❌ Know which app to open before capturing
- ❌ Navigate to specific screens/pages within apps
- ❌ Validate they're on the correct screen before extracting
- ❌ Execute prerequisite actions to reach the target screen
- ❌ Return to home screen after capturing (to avoid leaving apps open)

### **Example Use Case (Broken Without Navigation)**

**Scenario:** User wants to monitor "Spotify - Now Playing Song Title"

**Current Behavior:**
1. User creates sensor with bounds for song title location
2. Sensor stores: `{bounds: {x: 200, y: 300, width: 400, height: 50}}`
3. Background update loop runs every 30s:
   - Captures screenshot of CURRENT screen (whatever is showing)
   - Extracts text from coordinates (200, 300)
   - **Problem:** If Spotify isn't open, extracts random text from another app!

**Expected Behavior (Not Implemented):**
1. Sensor stores: `{target_app: "com.spotify.music", bounds: {...}}`
2. Background update loop:
   - Opens Spotify app
   - Waits for app to load
   - Captures screenshot
   - Extracts text from correct location
   - Returns to home screen

### **Workarounds (Current)**

**Option 1: Kiosk Mode**
- Dedicate device to run single app in kiosk mode
- Sensor always captures from that app

**Option 2: Manual Action Triggers**
- Create HA automation that opens app before sensor updates
- Requires precise timing

**Option 3: Lock Screen Sensors Only**
- Only monitor data visible on lock screen
- Battery, time, notifications, etc.

### **Implementation Plan (Future Phase 8+)**

#### **1. Extend Sensor Model**
```python
# sensor_models.py additions needed

class SensorDefinition(BaseModel):
    # Existing fields...
    name: str
    bounds: Dict[str, int]
    extraction_method: str

    # NEW FIELDS NEEDED:
    target_app: Optional[str] = None  # Package name (e.g., "com.spotify.music")
    prerequisite_actions: List[str] = Field(default_factory=list)  # Action IDs to execute
    navigation_sequence: Optional[List[Dict]] = None  # Step-by-step navigation
    validation_element: Optional[Dict] = None  # Element to verify correct screen
    return_home_after: bool = True  # Go to home after capture
    max_navigation_attempts: int = 3  # Retry navigation if fails
    navigation_timeout: int = 10  # Max seconds to wait for screen
```

#### **2. Update Sensor Updater Loop**
```python
# sensor_updater.py enhancements needed

async def _update_single_sensor(self, sensor: SensorDefinition):
    """Update a single sensor value"""

    # NEW: Navigate to target screen
    if sensor.target_app or sensor.navigation_sequence:
        success = await self._navigate_to_screen(sensor)
        if not success:
            logger.error(f"[SensorUpdater] Failed to navigate to screen for sensor {sensor.name}")
            return None  # Skip this update

    # Existing: Capture and extract
    screenshot = await self.adb_bridge.capture_screenshot(sensor.device_id)
    elements = await self.adb_bridge.get_ui_elements(sensor.device_id)
    value = self.text_extractor.extract(screenshot, elements, sensor.bounds, sensor.extraction_method)

    # NEW: Return to home screen
    if sensor.return_home_after:
        await self.adb_bridge.keyevent(sensor.device_id, "KEYCODE_HOME")

    # Existing: Publish to MQTT
    await self.mqtt_manager.publish_sensor_state(sensor, value)

    return value

async def _navigate_to_screen(self, sensor: SensorDefinition) -> bool:
    """Navigate to the target screen for sensor capture"""

    # Step 1: Launch target app
    if sensor.target_app:
        logger.info(f"[SensorUpdater] Launching app: {sensor.target_app}")
        await self.adb_bridge.launch_app(sensor.device_id, sensor.target_app)
        await asyncio.sleep(2)  # Wait for app to open

    # Step 2: Execute prerequisite actions (if specified)
    if sensor.prerequisite_actions:
        logger.info(f"[SensorUpdater] Executing {len(sensor.prerequisite_actions)} prerequisite actions")
        for action_id in sensor.prerequisite_actions:
            await self.action_executor.execute_action_by_id(
                self.action_manager,
                sensor.device_id,
                action_id
            )
            await asyncio.sleep(0.5)  # Wait between actions

    # Step 3: Validate we're on the correct screen
    if sensor.validation_element:
        for attempt in range(sensor.max_navigation_attempts):
            is_valid = await self._validate_screen(sensor)
            if is_valid:
                logger.info(f"[SensorUpdater] Screen validated for sensor {sensor.name}")
                return True

            logger.warning(f"[SensorUpdater] Screen validation failed (attempt {attempt + 1}/{sensor.max_navigation_attempts})")
            await asyncio.sleep(1)

        return False  # Validation failed after all attempts

    return True  # No validation required, assume success

async def _validate_screen(self, sensor: SensorDefinition) -> bool:
    """Verify we're on the expected screen"""
    screenshot = await self.adb_bridge.capture_screenshot(sensor.device_id)
    elements = await self.adb_bridge.get_ui_elements(sensor.device_id)

    # Check if validation element exists
    validation = sensor.validation_element
    found = any(
        (not validation.get('text') or el.get('text') == validation.get('text')) and
        (not validation.get('class') or el.get('class') == validation.get('class')) and
        (not validation.get('resource_id') or el.get('resource_id') == validation.get('resource_id'))
        for el in elements
    )

    return found
```

#### **3. Enhance Sensor Creator UI**
```javascript
// www/js/modules/sensor-creator.js additions needed

class SensorCreator {
    // Existing methods...

    // NEW: Add target app selection
    _addTargetAppField() {
        // Dropdown populated from installed apps
        // GET /api/adb/apps?device_id={id}
    }

    // NEW: Add prerequisite actions selector
    _addPrerequisiteActionsField() {
        // Multi-select list of available actions
        // GET /api/actions/{device_id}
    }

    // NEW: Add validation element picker
    _addValidationElementPicker() {
        // Click on screenshot to select validation element
        // Stores element text/class/resource_id
    }

    // NEW: Add navigation sequence builder
    _addNavigationSequenceBuilder() {
        // Drag-and-drop interface to build action sequence
        // Similar to macro builder
    }
}
```

#### **4. API Endpoints Needed**
```python
# server.py additions needed

@app.get("/api/adb/apps")
async def list_installed_apps(device_id: str):
    """List all installed apps on device"""
    apps = await adb_bridge.get_installed_apps(device_id)
    return {"apps": apps}

@app.post("/api/sensors/validate-screen")
async def validate_sensor_screen(device_id: str, sensor_id: str):
    """Test if sensor can navigate to its target screen"""
    sensor = sensor_manager.get_sensor(device_id, sensor_id)
    success = await sensor_updater._navigate_to_screen(sensor)
    return {"success": success}
```

### **Timeline for Implementation**

- **Phase 7 (v0.1.0 → v1.0.0):** Documentation, community release
- **Phase 8 (v1.1.0):** **Sensor Navigation System** ← This feature
- **Phase 9 (v1.2.0):** Advanced automation (conditional sensors, scheduled actions)
- **Phase 10 (v1.3.0):** Live streaming (files 30 & 31)

### **Effort Estimate**

**Development Time:** 1-2 weeks
**Testing Time:** 1 week
**Documentation Time:** 2-3 days

**Total:** ~3-4 weeks for complete implementation

---

## 📋 Other Missing Features

### **1. Live Streaming (Files 30 & 31)**

**Status:** ❌ **NOT IMPLEMENTED** - Research documents only

**What's Missing:**
- WebRTC-based video streaming (<100ms latency)
- Real-time UI element overlays
- Interactive canvas compositor
- Click-through to device during streaming

**Priority:** Medium (nice-to-have, not critical)

**Timeline:** Phase 10+ (post-v1.0.0)

**Documentation:** See [30_LIVE_STREAMING_RESEARCH.md](30_LIVE_STREAMING_RESEARCH.md) and [31_LIVE_STREAMING_IMPLEMENTATION.md](31_LIVE_STREAMING_IMPLEMENTATION.md)

---

### **2. Action Recording Mode**

**Status:** ❌ **NOT IMPLEMENTED**

**What It Would Do:**
- Record user interactions on device (taps, swipes, text input)
- Save recording as reusable action/macro
- Replay recorded actions

**Use Case:** Quickly create complex macros by demonstrating the workflow once

**Priority:** Low (can manually create actions via visual mode)

**Timeline:** Phase 9+ (post-v1.0.0)

---

### **3. Macro Builder UI**

**Status:** ⏳ **PARTIAL** - Can create macros via JSON, no drag-and-drop UI

**What's Missing:**
- Drag-and-drop action sequencing interface
- Visual macro editor
- Conditional logic in macros (if/else)
- Variables and parameters

**Current Workaround:** Create macros manually in [actions.html](www/actions.html) form

**Priority:** Medium (would improve UX significantly)

**Timeline:** Phase 9 (v1.2.0)

---

### **4. Scheduled Actions**

**Status:** ❌ **NOT IMPLEMENTED**

**What's Missing:**
- Cron-style scheduling for actions
- One-time scheduled actions
- Recurring action schedules

**Current Workaround:** Use Home Assistant automations to trigger actions via MQTT

**Priority:** Low (HA automations handle this)

**Timeline:** Phase 9+ (v1.2.0+)

---

### **5. Conditional Sensors**

**Status:** ❌ **NOT IMPLEMENTED**

**What's Missing:**
- Sensors that only update if certain conditions are met
- Template sensors with variables
- Sensor fallback values

**Current Workaround:** Handle conditionals in Home Assistant template sensors

**Priority:** Low (HA handles this well)

**Timeline:** Phase 9+ (v1.2.0+)

---

### **6. Screen Validation System**

**Status:** ❌ **NOT IMPLEMENTED**

**What's Missing:**
- Element presence detection
- Screen state verification
- Automatic retry on wrong screen

**Related To:** Sensor Navigation System (above)

**Priority:** High (needed for reliable sensor updates)

**Timeline:** Phase 8 (v1.1.0) - Along with sensor navigation

---

### **7. Diagnostic Page Completion**

**Status:** ⏳ **SKELETON EXISTS** - Basic structure, no functionality

**What's Missing:**
- System health checks
- Live log viewer
- Performance metrics dashboard
- ADB connection diagnostics
- MQTT connectivity test

**Current Workaround:** Check server logs manually

**Priority:** Low (developers can use server logs)

**Timeline:** Phase 7 or later (v1.0.0+)

---

### **8. Device Detail Page**

**Status:** ⏳ **SKELETON EXISTS** - Basic structure, no functionality

**What's Missing:**
- Per-device detailed view
- Device information display
- Device-specific settings
- Sensor/action management per device

**Current Workaround:** Use devices.html, sensors.html, actions.html

**Priority:** Low (existing pages cover functionality)

**Timeline:** Phase 7 or later (v1.0.0+)

---

### **9. User Documentation**

**Status:** ⏳ **PARTIAL** - Technical docs complete, user-facing docs missing

**What's Missing:**
- Getting started guide for end users
- Feature tutorials with screenshots
- Video tutorials
- FAQ document
- Troubleshooting guide

**Priority:** High (needed for v1.0.0 community release)

**Timeline:** Phase 7 (v1.0.0)

---

### **10. Plugin System**

**Status:** ❌ **NOT IMPLEMENTED**

**What's Missing:**
- Plugin API specification
- Plugin loader
- Custom sensor types via plugins
- Custom action types via plugins
- UI extension points

**Priority:** Medium (would enable community extensions)

**Timeline:** Phase 7 (v1.0.0)

---

### **11. Multi-User Support**

**Status:** ❌ **NOT IMPLEMENTED**

**What's Missing:**
- User accounts
- Role-based access control (RBAC)
- Per-user device assignments
- Activity logging per user

**Priority:** Low (single-user addon is primary use case)

**Timeline:** Post-v1.0.0 (future consideration)

---

### **12. Advanced Action Types**

**Status:** ⏳ **PARTIAL** - Basic actions work, advanced types missing

**What's Missing:**
- Wait for element to appear
- Conditional branching (if/else)
- Loops (repeat N times)
- Screenshot capture after action
- Error handling with retry logic
- Parameterized actions (template variables)

**Priority:** Medium (would make macros more powerful)

**Timeline:** Phase 9 (v1.2.0)

---

## 📊 Priority Matrix

| Feature | Priority | Impact | Effort | Timeline |
|---------|----------|--------|--------|----------|
| **Sensor Navigation** | 🔴 Critical | High | Medium | Phase 8 (v1.1.0) |
| **User Documentation** | 🟠 High | High | Low | Phase 7 (v1.0.0) |
| **Plugin System** | 🟠 High | Medium | High | Phase 7 (v1.0.0) |
| **Macro Builder UI** | 🟡 Medium | Medium | Medium | Phase 9 (v1.2.0) |
| **Advanced Actions** | 🟡 Medium | Medium | Medium | Phase 9 (v1.2.0) |
| **Live Streaming** | 🟡 Medium | High | High | Phase 10+ (v1.3.0) |
| **Diagnostic Page** | 🟢 Low | Low | Low | Phase 7+ |
| **Device Detail Page** | 🟢 Low | Low | Low | Phase 7+ |
| **Scheduled Actions** | 🟢 Low | Low | Low | Phase 9+ |
| **Multi-User Support** | ⚪ Future | Low | High | Post-v1.0.0 |

---

## 🎯 Recommended Next Steps

### **Immediate (Phase 7 - v1.0.0)**
1. ✅ Complete Phase 6 (polish & optimization) - **DONE!**
2. 📝 Write user documentation
3. 🧩 Design plugin system
4. 🧪 Beta test with real users
5. 🐛 Fix bugs from beta testing
6. 🚀 Release v1.0.0

### **Short-Term (Phase 8 - v1.1.0)**
1. 🔴 **Implement Sensor Navigation System** ← Critical gap!
2. Test with real-world use cases (Spotify, weather apps, etc.)
3. Document workarounds for current limitations
4. Release v1.1.0

### **Medium-Term (Phase 9 - v1.2.0)**
1. Macro Builder UI (drag-and-drop)
2. Advanced action types (conditionals, loops, wait-for-element)
3. Complete diagnostic.html
4. Release v1.2.0

### **Long-Term (Phase 10+ - v1.3.0+)**
1. Live Streaming (WebRTC-based)
2. Action Recording Mode
3. Cloud sync (optional)
4. Mobile app
5. Multi-user support

---

## 📝 Current Limitations (Document for Users)

**For v0.1.0 Beta Release, clearly document these limitations:**

### **Sensor System**
⚠️ **Sensors capture from whatever screen is currently showing**
- Workaround: Use kiosk mode, lock screen sensors, or manual HA automations

### **Live Streaming**
⚠️ **No real-time streaming yet**
- Workaround: Use screenshot capture with auto-refresh

### **Action System**
⚠️ **No advanced action types (wait-for-element, conditionals, loops)**
- Workaround: Use simple action sequences, handle logic in HA

### **Multi-Device**
⚠️ **All devices managed from single UI**
- Workaround: Use device selector dropdown

### **Performance**
⚠️ **Screenshot-based sensor updates use more battery than native apps**
- Workaround: Increase update intervals, use on plugged-in devices

---

## 🔄 Version Roadmap

```
v0.0.5 ← CURRENT (Phase 6 Complete)
  ↓
v0.1.0 (Phase 7) - Beta release with user docs + plugin system
  ↓
v1.0.0 (Phase 7) - Public release after beta testing
  ↓
v1.1.0 (Phase 8) - Sensor Navigation System ← Fixes critical gap
  ↓
v1.2.0 (Phase 9) - Advanced actions + macro builder UI
  ↓
v1.3.0 (Phase 10) - Live streaming
  ↓
v2.0.0 (Future) - Major architectural changes (multi-user, cloud sync)
```

---

**Document Version:** 1.0.0
**Created:** 2025-12-23
**Last Updated:** 2025-12-23
**Maintained By:** Project team

**Related Documents:**
- [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) - Overall project roadmap
- [PHASE_6_COMPLETE.md](PHASE_6_COMPLETE.md) - Phase 6 completion report
- [FEATURE_SPECIFICATIONS.md](FEATURE_SPECIFICATIONS.md) - Complete feature wishlist
- [30_LIVE_STREAMING_RESEARCH.md](30_LIVE_STREAMING_RESEARCH.md) - Live streaming research
- [31_LIVE_STREAMING_IMPLEMENTATION.md](31_LIVE_STREAMING_IMPLEMENTATION.md) - Live streaming implementation plan
