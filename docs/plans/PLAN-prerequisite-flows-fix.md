# Plan: Fix Prerequisite Flows System

## Problem Summary

The prerequisite flow system (for setting up streaming/accessibility permissions) has multiple interconnected issues that need systematic fixing.

## Issues Identified

### 1. Backend Issues
- [x] **Shell step type missing** - Added `shell` step type to flow_models.py and flow_executor.py
- [ ] **Server not restarted** - Changes not loaded yet

### 2. Frontend API Endpoint Issues
- [x] `/adb/shell` doesn't exist - Fixed to use `/shell/{device_id}/execute`
- [x] `/flows/{device_id}` wrong - Fixed to use `/flows` with device_id in body
- [x] Missing `flow_id` - Added generation of unique flow_id

### 3. UX/Flow Issues
- [x] **Transparent activity** - Made MediaProjectionRequestActivity transparent
- [x] **Activity not exported** - Changed to `exported="true"` for ADB launch
- [ ] **Can't click system dialogs** - System permission dialogs don't expose elements to uiautomator
- [ ] **Auto-click chicken-egg** - Auto-click requires accessibility, but we might be setting up accessibility

### 4. Architecture Issues
- **Circular dependency**: To set up streaming, you need to click "Start now". Auto-click can do this, but auto-click needs accessibility service. To set up accessibility, you need to navigate settings and toggle - which CAN be done via flow wizard clicks.

## Proposed Solution

### Phase 1: Fix Immediate Blockers (Do Now)
1. Restart backend to load `shell` step type
2. Test flow creation works

### Phase 2: Simplify Prerequisite Flows

The key insight: **Prerequisite flows don't need to be "recorded" in the traditional sense.**

For **streaming**:
- Flow = single shell command to launch MediaProjectionRequestActivity
- User manually taps "Start now" (or auto-click if accessibility enabled)
- No need to record the tap - it's a system dialog

For **accessibility**:
- Flow = shell command to open accessibility settings
- User must manually navigate and toggle (varies by device/Android version)
- Recording this is fragile anyway (different UI per device)

### Phase 3: New Approach - "Quick Setup" Instead of Recording

Instead of "recording" prerequisite flows, offer **pre-built flows**:

```javascript
const PREREQUISITE_FLOWS = {
    streaming: {
        name: "Setup: Streaming",
        steps: [{ step_type: "shell", command: "am start -n com.visualmapper.companion/.streaming.MediaProjectionRequestActivity" }]
    },
    accessibility: {
        name: "Setup: Accessibility",
        steps: [{ step_type: "shell", command: "am start -a android.settings.ACCESSIBILITY_SETTINGS" }]
    }
};
```

When user clicks "Create Flow" for a prerequisite:
1. Save the pre-built flow immediately (no recording needed)
2. Execute it to open the relevant screen
3. Show guidance: "Complete the setup on your device, then click Done"
4. Link flow to prerequisite type

### Phase 4: Improve Guidance

Update guidance to be clear:
- "This opens the permission dialog on your device"
- "Tap 'Start now' on your DEVICE (not in the wizard)"
- "When accessibility is enabled, this will auto-click for you"

## Implementation Steps

1. [ ] Restart backend server
2. [ ] Test shell step type works
3. [x] Update `saveAsPrerequisiteFlow` to save pre-built flow immediately
4. [x] Remove dependency on `wizard.flowSteps` for prerequisite flows
5. [x] Update guidance text to be clearer
6. [x] Add "Run Setup" button handler for re-running saved flows
7. [ ] Test full flow: create streaming prerequisite → saves → can be run later

## Files to Modify

- `backend/core/flows/flow_models.py` - Already done (shell step)
- `backend/core/flows/flow_executor.py` - Already done (shell executor)
- `frontend/www/js/modules/prerequisite-dialog.js` - Update save logic
- `frontend/www/js/modules/flow-wizard-step3.js` - Simplify prerequisite mode

## Success Criteria

1. User can create streaming prerequisite flow with one click
2. Flow saves successfully with shell step
3. Flow can be executed later (launches permission dialog)
4. Clear guidance tells user what to do on device
