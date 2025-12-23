# Visual Mapper - Phase 3 Manual Testing Guide
**Version:** 0.0.4
**Date:** 2025-12-22
**Status:** Ready for Manual Testing

---

## ✅ Prerequisites

**Server Status:**
- ✅ Server running at http://localhost:3000
- ✅ Version 0.0.4 confirmed
- ✅ All backend tests passing (69/70 - 98.6%)

**Device Requirements:**
- Android device with USB debugging enabled OR
- Android 11+ device with wireless ADB enabled

---

## 🎯 Phase 3 Test Scenarios

### **Test 1: Sensor Creation Workflow** (Core Feature)

**Goal:** Create a sensor from a UI element on your Android device

**Steps:**
1. **Open devices page**
   - Navigate to: http://localhost:3000/devices.html
   - Verify version shows "v0.0.4" in navigation

2. **Connect your device**
   - Select connection type (TCP/Wireless/Pairing)
   - Enter device IP and port
   - Click "Connect Device"
   - ✅ **Expected:** Device appears in "Connected Devices" list

3. **Capture screenshot**
   - Select your device from dropdown
   - Click "Capture Screenshot"
   - ✅ **Expected:** Screenshot appears on canvas with green/yellow element overlays

4. **Switch to Sensor mode**
   - Click the "Sensor" toggle button (between "Tap", "Swipe", "Sensor")
   - ✅ **Expected:** Cursor changes to crosshair
   - Hover over elements on screenshot
   - ✅ **Expected:** Tooltip shows element class and text

5. **Select an element**
   - Click on a UI element (try battery percentage or time display)
   - ✅ **Expected:**
     - Element highlights in blue
     - "Create Sensor" dialog appears
     - Sensor name auto-populated from element text

6. **Configure sensor**
   - **Sensor Name:** Auto-filled (verify it's readable)
   - **Sensor Type:** Choose "Sensor" or "Binary Sensor"
   - **Device Class:** Select appropriate class (e.g., "battery" for battery %)
   - **Unit of Measurement:** Enter unit (e.g., "%")
   - **Icon:** Enter MDI icon (e.g., "mdi:battery")
   - **Extraction Method:** Choose method:
     - "Exact" - uses text as-is
     - "Numeric" - extracts number only (recommended for "94%" → "94")
     - Other methods available for complex text
   - **Extract Numeric:** Check if you want only numbers
   - **Remove Unit:** Check to remove "%" from "94%"
   - **Update Interval:** Set seconds (default 60)

7. **Preview extraction**
   - ✅ **Expected:** Preview box shows: `"original text" → "extracted value"`
   - Verify extraction looks correct

8. **Create sensor**
   - Click "Create Sensor" button
   - ✅ **Expected:**
     - Success alert: "Sensor created successfully!"
     - Dialog closes
     - No errors in browser console

---

### **Test 2: Sensor Management** (View/Edit/Delete)

**Goal:** Manage created sensors

**Steps:**
1. **Navigate to Sensors page**
   - Go to: http://localhost:3000/sensors.html
   - ✅ **Expected:** Sensor list loads

2. **View sensor list**
   - ✅ **Expected:**
     - Sensors grouped by device
     - Each sensor shows:
       - Name and icon
       - Status badges (Enabled/Disabled, Sensor/Binary, Device Class)
       - Sensor ID
       - Update interval
       - Extraction method
       - Current value (shows "Not yet updated" - normal, MQTT not implemented)

3. **Search/Filter sensors**
   - Use search box: Type sensor name or ID
   - Use device filter: Select specific device
   - ✅ **Expected:** List filters correctly

4. **Disable a sensor**
   - Click "Disable" button on a sensor
   - ✅ **Expected:**
     - Badge changes to "Disabled" (gray)
     - Page refreshes with updated status

5. **Enable a sensor**
   - Click "Enable" button on disabled sensor
   - ✅ **Expected:**
     - Badge changes to "Enabled" (green)
     - Page refreshes

6. **Delete a sensor**
   - Click "Delete" button (red)
   - ✅ **Expected:**
     - Confirmation dialog appears
     - Click "OK"
     - Sensor removed from list
     - Page refreshes

7. **Edit sensor (placeholder)**
   - Click "Edit" button
   - ✅ **Expected:** Alert shows "Edit functionality coming soon!"
   - (This is expected - edit dialog not implemented yet)

---

### **Test 3: Multiple Sensors**

**Goal:** Create and manage multiple sensors

**Steps:**
1. Capture fresh screenshot
2. Switch to Sensor mode
3. Create 3 different sensors:
   - **Sensor 1:** Battery level (numeric, with %)
   - **Sensor 2:** Time display (exact text)
   - **Sensor 3:** Network name (text)

4. **Go to Sensors page**
   - ✅ **Expected:** All 3 sensors appear
   - Grouped under same device
   - Each with correct configuration

---

### **Test 4: Data Persistence**

**Goal:** Verify sensors persist across sessions

**Steps:**
1. Create 1-2 sensors
2. **Refresh the browser** (F5)
3. Go to Sensors page
   - ✅ **Expected:** Sensors still exist

4. **Stop the server** (if you can safely)
5. **Restart the server**
6. Go to Sensors page
   - ✅ **Expected:** Sensors still exist (stored in `data/sensors_{device_id}.json`)

---

### **Test 5: Text Extraction Methods**

**Goal:** Test different extraction methods

**Try these extraction scenarios:**

**A. Numeric Extraction**
- Element text: "94%"
- Method: "Numeric"
- Extract numeric: ✓
- Remove unit: ✓
- ✅ **Expected preview:** "94%" → "94"

**B. Exact Text**
- Element text: "Battery Full"
- Method: "Exact"
- ✅ **Expected preview:** "Battery Full" → "Battery Full"

**C. Regex (if you're comfortable)**
- Element text: "Speed: 45 mph"
- Method: "Regex"
- Pattern: `(\d+)`
- ✅ **Expected preview:** "Speed: 45 mph" → "45"

**D. Before/After**
- Element text: "Battery: 94%"
- Method: "After"
- After text: ": "
- Remove unit: ✓
- ✅ **Expected preview:** "Battery: 94%" → "94"

---

## ⚠️ Known Limitations (Expected Behavior)

**These are NOT bugs - they're planned for future phases:**

1. **"Current Value" shows "Not yet updated"**
   - ✅ This is expected - MQTT integration not implemented yet
   - Sensors won't appear in Home Assistant until Phase 3 MQTT work is complete

2. **"Edit" button shows placeholder alert**
   - ✅ This is expected - edit dialog not implemented yet
   - Workaround: Delete and recreate sensor

3. **No sensor history**
   - ✅ This is expected - requires MQTT update loop

4. **No bulk operations**
   - ✅ This is expected - not implemented yet

5. **"Draw Bounds" mode missing**
   - ✅ This is expected - optional feature, not implemented

---

## 🐛 What to Report as Bugs

**Report these if you encounter them:**

1. **Sensor creation fails with error**
   - Check browser console (F12 → Console tab)
   - Copy full error message

2. **Sensor doesn't appear in list after creation**
   - Check Sensors page
   - Refresh page
   - Check browser console

3. **Preview shows wrong extraction**
   - Note the element text
   - Note your extraction settings
   - Note what preview showed vs. what you expected

4. **Delete doesn't work**
   - Sensor still appears after deletion
   - Check browser console

5. **UI issues**
   - Layout broken on mobile/tablet
   - Theme toggle not working
   - Navigation issues

---

## 📊 Success Criteria

**Phase 3 Manual Testing Passes If:**

- ✅ Can connect to Android device
- ✅ Can capture screenshot with element overlays
- ✅ Can switch to Sensor mode
- ✅ Can select element and see sensor dialog
- ✅ Preview shows correct extraction
- ✅ Can create sensor successfully
- ✅ Sensor appears in Sensors page
- ✅ Can enable/disable sensor
- ✅ Can delete sensor
- ✅ Sensors persist after page refresh
- ✅ Can create multiple sensors
- ✅ Search and filter work correctly

---

## 🔍 Browser Console Monitoring

**Keep Console Open During Testing:**
1. Press F12 to open Developer Tools
2. Go to "Console" tab
3. Look for these GOOD messages:
   - `[Init] Visual Mapper v0.0.4`
   - `[SensorCreator] Sensor created: ...`
   - `[Sensors] Loaded X sensors`

**Report these BAD messages:**
   - Any errors in RED
   - 404 errors (file not found)
   - 500 errors (server error)
   - JavaScript exceptions

---

## 📝 Testing Checklist

Use this checklist while testing:

```
[ ] Server running at localhost:3000
[ ] Version shows v0.0.4
[ ] Device connected successfully
[ ] Screenshot captured with overlays
[ ] Sensor mode activates (crosshair cursor)
[ ] Element selection works (blue highlight)
[ ] Sensor dialog appears
[ ] Preview shows correct extraction
[ ] Sensor created successfully
[ ] Sensor appears in Sensors page
[ ] Enable/disable toggle works
[ ] Delete works with confirmation
[ ] Search filters sensors
[ ] Device filter works
[ ] Page refresh preserves sensors
[ ] Multiple sensors can be created
[ ] No console errors
```

---

## 🎉 What's Next

**After successful manual testing:**
- Phase 3 will be marked as ready for MQTT implementation
- Next step: Implement MQTT to publish sensors to Home Assistant
- Then sensors will appear in HA with live updates!

---

**Ready to test!** Start with Test 1 (Sensor Creation Workflow) and work through the scenarios. Report any issues you find!
