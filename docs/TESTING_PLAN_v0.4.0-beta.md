# Visual Mapper v0.4.0-beta - Comprehensive Testing Plan

This document outlines the testing procedures for all enhancements implemented in the v0.4.0-beta release.

---

## Table of Contents

1. [Initial Plan Improvements](#1-initial-plan-improvements)
   - 1.1 Duplicate Sensor Name Check
   - 1.2 Retry Button in Flow Results Modal
   - 1.3 Error Messages with Troubleshooting Hints
   - 1.4 Regex Pattern Validation
2. [Critical Priority Enhancements](#2-critical-priority-enhancements)
   - 2.1 Specific Exception Handling
   - 2.2 Dynamic Screen Dimensions
   - 2.3 Device Registry Persistence
3. [High Priority Enhancements](#3-high-priority-enhancements)
   - 3.1 Action Edit Dialog
   - 3.2 localStorage Error Handling
   - 3.3 Flow Optimization for Multiple Sensors
4. [Medium Priority Enhancements](#4-medium-priority-enhancements)
   - 4.1 Toast Notifications
   - 4.2 Centralized Debug Logging
   - 4.3 Dynamic triggered_by Parameter

---

## 1. Initial Plan Improvements

### 1.1 Duplicate Sensor Name Check

**Files Modified:**
- `backend/routes/sensors.py`
- `frontend/www/js/modules/sensor-creator.js`

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| DSN-01 | Create sensor with unique name | 1. Open sensor creator<br>2. Enter unique name "Test Sensor 1"<br>3. Submit | Sensor created successfully |
| DSN-02 | Create sensor with duplicate name | 1. Create sensor "Temperature"<br>2. Try creating another "Temperature" on same device | Error: "A sensor named 'Temperature' already exists" |
| DSN-03 | Case-insensitive duplicate check | 1. Create sensor "Battery Level"<br>2. Try creating "battery level" | Error: Should catch case-insensitive duplicates |
| DSN-04 | Edit sensor - keep same name | 1. Edit existing sensor<br>2. Keep same name, change other fields<br>3. Save | Should save successfully (exclude self) |
| DSN-05 | Different devices - same name | 1. Create sensor "Power" on Device A<br>2. Create sensor "Power" on Device B | Both should succeed (different devices) |

**Verification Steps:**
```bash
# Backend API test
curl -X POST "http://localhost:8080/api/sensors/device123" \
  -H "Content-Type: application/json" \
  -d '{"friendly_name": "Test Sensor", ...}'

# Try duplicate
curl -X POST "http://localhost:8080/api/sensors/device123" \
  -H "Content-Type: application/json" \
  -d '{"friendly_name": "Test Sensor", ...}'
# Should return 400 error
```

---

### 1.2 Retry Button in Flow Results Modal

**Files Modified:**
- `frontend/www/js/modules/flow-execution.js`
- `frontend/www/css/styles.css`

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| RB-01 | Retry button appears on failure | 1. Execute a flow that fails<br>2. Check results modal | "Retry Flow" button visible |
| RB-02 | Retry button not shown on success | 1. Execute a flow successfully<br>2. Check results modal | No retry button shown |
| RB-03 | Retry button re-executes flow | 1. Execute failing flow<br>2. Click "Retry Flow"<br>3. Observe | Modal closes, flow executes again |
| RB-04 | Multiple retries work | 1. Execute failing flow<br>2. Retry multiple times | Each retry executes correctly |

**Verification Steps:**
1. Disconnect a device to simulate flow failure
2. Execute a flow targeting that device
3. Verify retry button appears in the modal
4. Click retry and verify flow attempts execution again

---

### 1.3 Error Messages with Troubleshooting Hints

**Files Modified:**
- `backend/utils/error_handler.py` (new file)
- `backend/core/flows/flow_executor.py`
- `backend/core/flows/flow_models.py`
- `frontend/www/js/modules/flow-execution.js`
- `frontend/www/css/styles.css`

**Test Cases:**

| ID | Test Case | Trigger Condition | Expected Hint |
|----|-----------|-------------------|---------------|
| EH-01 | Device locked error | Run flow on locked device | "Enable AUTO_UNLOCK in device settings..." |
| EH-02 | Device offline error | Run flow on disconnected device | "Check that the device is on the same network..." |
| EH-03 | Element not found | Run flow with outdated element | "The app UI may have changed..." |
| EH-04 | Timeout error | Run flow that exceeds timeout | "Increase the flow timeout..." |
| EH-05 | Regex pattern error | Create sensor with bad regex | "Check your regex syntax..." |

**Verification Steps:**
1. Trigger each error condition
2. Verify error_hint field in API response
3. Verify hint displays in frontend modal with warning styling

```bash
# Check error hint in response
curl -X POST "http://localhost:8080/api/flows/device123/flow456/execute"
# Should include "error_hint" in response on failure
```

---

### 1.4 Regex Pattern Validation

**Files Modified:**
- `backend/routes/sensors.py`
- `frontend/www/js/modules/sensor-creator.js`
- `frontend/www/css/styles.css`

**Test Cases:**

| ID | Test Case | Input Pattern | Expected Result |
|----|-----------|---------------|-----------------|
| RV-01 | Valid simple regex | `\d+` | Accepted |
| RV-02 | Valid complex regex | `(\d+)°([CF])` | Accepted |
| RV-03 | Invalid unclosed bracket | `[unclosed` | Error: "Invalid regex pattern..." |
| RV-04 | Invalid unmatched paren | `(test` | Error: "unbalanced parenthesis" |
| RV-05 | Real-time validation | Type invalid pattern | Input shows red border immediately |

**Verification Steps:**
```javascript
// In browser console, test regex validation
try {
  new RegExp('[invalid');
} catch (e) {
  console.log('Caught:', e.message);
}
```

---

## 2. Critical Priority Enhancements

### 2.1 Specific Exception Handling

**Files Modified:**
- `backend/core/adb/adb_helpers.py`
- `backend/routes/streaming.py`
- `backend/routes/performance.py`
- `backend/routes/device.py`
- `backend/core/flows/flow_manager.py`
- Multiple other backend files

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| EX-01 | ADB connection failure | 1. Disconnect device<br>2. Attempt ADB operation | Proper OSError handling, no bare except |
| EX-02 | JSON decode error | 1. Corrupt a flows.json file<br>2. Load flows | Proper JSONDecodeError handling |
| EX-03 | File not found | 1. Delete a config file<br>2. Start server | Proper FileNotFoundError handling |
| EX-04 | Timeout error | 1. Set very short timeout<br>2. Execute slow operation | Proper asyncio.TimeoutError handling |

**Verification Steps:**
```bash
# Check no bare except clauses remain
grep -r "except:" backend/ --include="*.py" | grep -v "except Exception"
# Should return no results
```

---

### 2.2 Dynamic Screen Dimensions

**Files Modified:**
- `backend/core/adb/adb_helpers.py`

**Test Cases:**

| ID | Test Case | Device | Expected Result |
|----|-----------|--------|-----------------|
| SD-01 | Standard 1080x2400 device | Pixel 4 | Returns (1080, 2400) |
| SD-02 | Different resolution | Samsung Tab | Returns actual dimensions |
| SD-03 | Dimension caching | Same device, multiple calls | Uses cached value (no ADB call) |
| SD-04 | Fallback on failure | Invalid device | Returns default (1080, 2400) |

**Verification Steps:**
```bash
# Test via ADB directly
adb -s device_id shell wm size
# Should return "Physical size: WIDTHxHEIGHT"
```

```python
# API test
from backend.core.adb.adb_helpers import ADBHelpers
helpers = ADBHelpers(adb_bridge)
dimensions = await helpers.get_screen_dimensions("device_id")
print(f"Screen: {dimensions[0]}x{dimensions[1]}")
```

---

### 2.3 Device Registry Persistence

**Files Modified:**
- `backend/routes/device_registration.py`

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| DR-01 | Register device persists | 1. Register new device<br>2. Restart server<br>3. Check registry | Device still registered |
| DR-02 | Unregister device persists | 1. Unregister device<br>2. Restart server | Device not in registry |
| DR-03 | Update device persists | 1. Update device info<br>2. Restart server | Updated info preserved |
| DR-04 | Corrupted file recovery | 1. Corrupt registry file<br>2. Start server | Empty registry, no crash |

**Verification Steps:**
```bash
# Check registry file
cat data/device_registry.json

# Verify structure
{
  "device_id_1": {
    "device_id": "192.168.1.100:5555",
    "friendly_name": "Pixel 4",
    ...
  }
}
```

---

## 3. High Priority Enhancements

### 3.1 Action Edit Dialog

**Files Modified:**
- `frontend/www/js/modules/flow-wizard.js`

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| AE-01 | Open edit dialog | 1. In flow wizard, click edit on action step<br>2. Dialog opens | Shows current action values |
| AE-02 | Edit tap action | 1. Edit tap action<br>2. Change coordinates<br>3. Save | Coordinates updated |
| AE-03 | Edit swipe action | 1. Edit swipe action<br>2. Change start/end points<br>3. Save | Swipe parameters updated |
| AE-04 | Edit text action | 1. Edit text input action<br>2. Change text<br>3. Save | Text value updated |
| AE-05 | Cancel edit | 1. Open edit dialog<br>2. Make changes<br>3. Cancel | No changes saved |

**Verification Steps:**
1. Open flow wizard with existing flow
2. Click pencil/edit icon on an action step
3. Verify dialog shows correct fields for action type
4. Modify values and save
5. Verify step updated in flow

---

### 3.2 localStorage Error Handling

**Files Modified:**
- `frontend/www/js/modules/storage-utils.js` (new file)
- `frontend/www/js/modules/theme-toggle.js`

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| LS-01 | Normal storage | 1. Set a value<br>2. Get the value | Value retrieved correctly |
| LS-02 | Storage disabled | 1. Disable localStorage in browser<br>2. Try to save/load | Graceful fallback, no error |
| LS-03 | Quota exceeded | 1. Fill localStorage<br>2. Try to add more | Fails silently, returns default |
| LS-04 | JSON parse error | 1. Store invalid JSON<br>2. Call getJSON | Returns default value, no crash |

**Verification Steps:**
```javascript
// In browser console
StorageUtils.setItem('test', 'value');
console.log(StorageUtils.getItem('test')); // 'value'

StorageUtils.setJSON('obj', {a: 1});
console.log(StorageUtils.getJSON('obj')); // {a: 1}

// Test availability
console.log(StorageUtils.isAvailable()); // true/false
```

---

### 3.3 Flow Optimization for Multiple Sensors

**Files Modified:**
- `backend/core/flows/flow_manager.py`
- `backend/core/flows/flow_models.py`

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| FO-01 | Optimize single app flows | 1. Create 3 flows for Spotify<br>2. Call optimize API | Creates 1 combined flow |
| FO-02 | Keep separate apps separate | 1. Create flows for Spotify + Nest<br>2. Optimize | 2 optimized flows (1 per app) |
| FO-03 | Preserve source tracking | 1. Optimize flows<br>2. Check optimized flow | optimization_source lists original IDs |
| FO-04 | Combined sensor capture | 1. Run optimized flow<br>2. Check results | All sensors captured in one run |

**Verification Steps:**
```bash
# Check flow optimization
curl -X POST "http://localhost:8080/api/flows/device123/optimize"
# Should return optimized flow IDs

# Verify optimization_source in flow
curl "http://localhost:8080/api/flows/device123/optimized_flow_id"
```

---

## 4. Medium Priority Enhancements

### 4.1 Toast Notifications

**Files Modified:**
- `frontend/www/js/modules/action-manager.js`
- `frontend/www/js/modules/device-security.js`

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| TN-01 | Success toast | 1. Perform successful action<br>2. Observe | Green toast appears briefly |
| TN-02 | Error toast | 1. Perform failing action<br>2. Observe | Red toast with error message |
| TN-03 | Warning toast | 1. Trigger warning condition<br>2. Observe | Yellow/amber toast |
| TN-04 | Toast auto-dismiss | 1. Trigger any toast<br>2. Wait 3 seconds | Toast disappears automatically |
| TN-05 | Fallback when unavailable | 1. Remove showToast from window<br>2. Trigger notification | Falls back to console.log |

**Verification Steps:**
1. Open action manager
2. Perform various operations
3. Verify toast notifications appear instead of alert() dialogs

---

### 4.2 Centralized Debug Logging

**Files Modified:**
- `frontend/www/js/modules/debug-logger.js` (new file)
- `frontend/www/js/modules/flow-execution.js`
- `frontend/www/js/modules/sensor-creator.js`
- `frontend/www/js/modules/action-manager.js`

**Test Cases:**

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| DL-01 | Default log level | 1. Load page<br>2. Check console | INFO and above shown |
| DL-02 | Set log level | 1. Run `vmDebug.setLevel('DEBUG')`<br>2. Trigger debug logs | DEBUG logs now visible |
| DL-03 | Disable logging | 1. Run `vmDebug.disable()`<br>2. Trigger logs | No logs appear |
| DL-04 | Module prefix | 1. Check log output | Shows [timestamp] [ModuleName] format |
| DL-05 | Log level persistence | 1. Set level<br>2. Refresh page | Level persists via localStorage |

**Verification Steps:**
```javascript
// In browser console
vmDebug.help();  // Shows available commands
vmDebug.setLevel('TRACE');  // Enable verbose logging
vmDebug.disable();  // Disable all logging
vmDebug.enable();  // Re-enable logging
vmDebug.getLevel();  // Check current level
```

---

### 4.3 Dynamic triggered_by Parameter

**Files Modified:**
- `backend/core/flows/flow_executor.py`
- `backend/services/flow_service.py`
- `backend/routes/flows.py`

**Test Cases:**

| ID | Test Case | Trigger Source | Expected triggered_by Value |
|----|-----------|----------------|----------------------------|
| TB-01 | Manual UI execution | Click execute in UI | "manual" |
| TB-02 | API call | POST /flows/.../execute | "api" (or "manual" default) |
| TB-03 | Scheduler execution | Scheduled flow runs | "scheduler" |
| TB-04 | Test execution | Test flow button | "test" |

**Verification Steps:**
```bash
# Execute with custom triggered_by
curl -X POST "http://localhost:8080/api/flows/device123/flow456/execute?triggered_by=test"

# Check execution history
curl "http://localhost:8080/api/flows/device123/flow456/history"
# Should show triggered_by value in history entries
```

---

## Testing Checklist

### Pre-Testing Setup
- [ ] Fresh database/data directory
- [ ] Backend server running
- [ ] Frontend served (development or built)
- [ ] At least one Android device connected

### Critical Tests (Must Pass)
- [ ] EX-01 through EX-04 (Exception handling)
- [ ] SD-01 through SD-04 (Screen dimensions)
- [ ] DR-01 through DR-04 (Device registry)

### High Priority Tests
- [ ] DSN-01 through DSN-05 (Duplicate sensor)
- [ ] RB-01 through RB-04 (Retry button)
- [ ] EH-01 through EH-05 (Error hints)
- [ ] RV-01 through RV-05 (Regex validation)
- [ ] AE-01 through AE-05 (Action edit)
- [ ] LS-01 through LS-04 (localStorage)
- [ ] FO-01 through FO-04 (Flow optimization)

### Medium Priority Tests
- [ ] TN-01 through TN-05 (Toast notifications)
- [ ] DL-01 through DL-05 (Debug logging)
- [ ] TB-01 through TB-04 (triggered_by)

---

## Regression Testing

After all enhancements, verify these core features still work:

1. **Device Management**
   - [ ] Connect to device via ADB
   - [ ] View device screen
   - [ ] Execute shell commands

2. **Sensor Management**
   - [ ] Create sensor from UI element
   - [ ] Edit existing sensor
   - [ ] Delete sensor
   - [ ] View sensor values

3. **Flow Management**
   - [ ] Create new flow
   - [ ] Edit flow steps
   - [ ] Execute flow manually
   - [ ] View flow results

4. **MQTT Integration**
   - [ ] Connect to MQTT broker
   - [ ] Publish sensor values
   - [ ] Home Assistant discovery

---

## Bug Reporting Template

If a test fails, create an issue with:

```markdown
## Test ID: [e.g., DSN-02]

### Description
[Brief description of what was tested]

### Steps to Reproduce
1. [Step 1]
2. [Step 2]
3. [Step 3]

### Expected Result
[What should happen]

### Actual Result
[What actually happened]

### Screenshots/Logs
[Attach if applicable]

### Environment
- Backend Version:
- Browser:
- Device:
```

---

## Sign-off

| Phase | Tester | Date | Status |
|-------|--------|------|--------|
| Critical Priority | | | |
| High Priority | | | |
| Medium Priority | | | |
| Regression | | | |
| Final Sign-off | | | |
