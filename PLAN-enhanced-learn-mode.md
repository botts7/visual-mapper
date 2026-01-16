# Enhanced Learn Mode Implementation Plan

## Problem Statement

Flow execution has critical issues that Learn Mode does not address:

1. **Tap failures silently succeed** - `_execute_tap()` always returns `True` even when navigation fails
2. **Flows report SUCCESS despite errors** - Screen mismatch warnings don't affect flow success status
3. **Element bounds drift unaddressed** - System logs "Element moved 769px" but doesn't auto-correct
4. **Manual runs skip everything** - "sensors not due" skips ALL steps including navigation verification
5. **Learn Mode only runs on success** - Failures aren't captured, so nothing improves

## Evidence from Logs

```
[11:38:53] INFO -   Element moved 769px - consider updating sensor bounds
[11:38:54] WARNING -   Screen didn't change after tap, retrying...
[11:38:56] WARNING - Screen mismatch during sensor capture. Expected: 'AirConditionerActivity', current: 'HomeTabActivity'
[11:39:06] ERROR - Timeout waiting for expected screen...
[11:39:09] INFO - [FlowExecutor] Flow completed successfully  <-- THIS IS WRONG!
```

## Root Cause Analysis

### Issue 1: `_execute_tap()` Always Returns True
```python
# flow_executor.py line 1592
return True  # Returns True even when retry failed!
```

### Issue 2: Learn Mode Only Captures Success
```python
# flow_executor.py line 729
if learn_mode and success:  # Only learns when step succeeds
```

### Issue 3: No Bounds Auto-Update
Element finder logs drift but doesn't update stored bounds:
```python
logger.info(f"  Element moved {distance}px - consider updating sensor bounds")
# No actual update!
```

### Issue 4: Page-Skip Blocks Manual Testing
```python
# Second manual run:
[Skip] Capture sensor: 22 (sensors not due for update)
[Skip] Tap content_group (sensors not due for update)
[Skip] Capture sensor: 31 (sensors not due for update)
# Steps executed: 4/4 but Sensors captured: 0
```

---

## Solution: Enhanced Learn Mode

### New Execution Modes

| Mode | Purpose | Behavior |
|------|---------|----------|
| `normal` | Production execution | Skip sensors not due, continue on warnings |
| `learn` | Improve navigation data | Capture UI elements, update graph |
| `strict` | Fail on navigation errors | Step fails if screen doesn't change |
| `repair` | Auto-fix bounds drift | Update bounds when elements found via fallback |

### Implementation Plan

---

## Phase 1: Fix Critical Bug - Tap Returns False on Failure

### File: `backend/core/flows/flow_executor.py`

**Change `_execute_tap()` to return False when navigation fails:**

```python
async def _execute_tap(self, device_id: str, step: FlowStep, result: FlowExecutionResult) -> bool:
    """
    Execute tap step with navigation verification

    Returns:
        True: Tap succeeded and screen changed (or no expected_activity specified)
        False: Tap failed to navigate to expected screen (when strict_navigation=True)
    """
    # ... existing tap code ...

    # After retry logic:
    if expected_activity:
        activity_after = await self.adb_bridge.get_current_activity(device_id)

        if not self._activity_matches(activity_after, expected_activity):
            logger.error(
                f"  Navigation FAILED: Expected {expected_activity.split('/')[-1]}, "
                f"still on {activity_after.split('/')[-1] if activity_after else 'unknown'}"
            )

            # In strict mode or learn mode, fail the step
            if getattr(result, 'strict_navigation', False) or getattr(result, 'learn_mode', False):
                return False

            # In normal mode, warn but continue (existing behavior)
            logger.warning("  Continuing despite navigation failure (strict_navigation=False)")

    return True
```

---

## Phase 2: Add Strict Mode for Flow Execution

### File: `backend/core/flows/flow_executor.py`

**Add `strict_mode` parameter to `execute_flow()`:**

```python
async def execute_flow(
    self,
    flow: SensorCollectionFlow,
    device_lock: Optional[asyncio.Lock] = None,
    learn_mode: bool = False,
    strict_mode: bool = False,  # NEW: Fail on navigation errors
    repair_mode: bool = False,  # NEW: Auto-update drifted bounds
) -> FlowExecutionResult:
    """
    Execute flow with configurable strictness

    Args:
        learn_mode: Capture UI elements at each screen
        strict_mode: Fail steps if navigation doesn't reach expected screen
        repair_mode: Auto-update element bounds when drift detected
    """
    result = FlowExecutionResult(...)
    result.strict_navigation = strict_mode
    result.learn_mode = learn_mode
    result.repair_mode = repair_mode

    # ... rest of execution ...
```

---

## Phase 3: Add Force Execute for Manual Testing

### File: `backend/core/flows/flow_executor.py`

**Add `force_execute` parameter to bypass sensor-due-check:**

```python
async def execute_flow(
    self,
    flow: SensorCollectionFlow,
    device_lock: Optional[asyncio.Lock] = None,
    learn_mode: bool = False,
    strict_mode: bool = False,
    repair_mode: bool = False,
    force_execute: bool = False,  # NEW: Skip page-skip optimization
) -> FlowExecutionResult:
```

**Update `_analyze_skippable_steps()`:**

```python
def _analyze_skippable_steps(self, flow, force_execute=False):
    """Identify steps that can be skipped"""
    if force_execute:
        return []  # Don't skip anything in force mode
    # ... existing logic ...
```

---

## Phase 4: Auto-Repair Element Bounds

### File: `backend/utils/element_finder.py`

**Add bounds update when element found via fallback:**

```python
def find_element(self, elements, target, sensor_manager=None, repair_mode=False):
    """
    Find element with optional auto-repair

    Args:
        repair_mode: If True, update stored bounds when element found via fallback
    """
    # ... existing find logic ...

    # If found via fallback strategy with significant drift:
    if found and strategy != 'exact_bounds' and repair_mode:
        drift_distance = self._calculate_drift(target_bounds, found_bounds)
        if drift_distance > 50:  # Only repair if drift > 50px
            logger.info(f"  [Repair] Auto-updating bounds (drift: {drift_distance}px)")
            self._update_stored_bounds(sensor_manager, target, found_bounds)
            result['bounds_repaired'] = True
            result['old_bounds'] = target_bounds
            result['new_bounds'] = found_bounds

    return result
```

### File: `backend/core/sensor_manager.py`

**Add method to update sensor bounds:**

```python
async def update_sensor_bounds(self, sensor_id: str, new_bounds: dict) -> bool:
    """
    Update stored bounds for a sensor

    Called by repair_mode when element drift is detected
    """
    sensor = self.get_sensor(sensor_id)
    if not sensor:
        return False

    old_bounds = sensor.element_bounds
    sensor.element_bounds = new_bounds
    sensor.bounds_updated_at = datetime.now().isoformat()
    sensor.bounds_drift_history.append({
        'old': old_bounds,
        'new': new_bounds,
        'updated_at': sensor.bounds_updated_at
    })

    self.save_sensors(sensor.device_id)
    logger.info(f"[SensorManager] Updated bounds for {sensor_id}")
    return True
```

---

## Phase 5: Learn from Failures

### File: `backend/core/flows/flow_executor.py`

**Capture failure data even when steps fail:**

```python
# In execute_flow(), after step execution:
if learn_mode:
    # Learn REGARDLESS of success (learn from failures too!)
    learn_step_types = {FlowStepType.TAP, FlowStepType.SWIPE, ...}
    if step.step_type in learn_step_types:
        try:
            learned = await self._learn_current_screen(flow.device_id, step_package)
            if learned:
                learned['step_success'] = success  # Track if step succeeded
                learned['step_type'] = step.step_type.value
                learned['expected_activity'] = step.expected_activity
                learned_screens.append(learned)

                # If step FAILED, log the failure context
                if not success:
                    logger.info(f"  [Learn Mode] Captured FAILURE context at: {learned.get('activity')}")
        except Exception as learn_err:
            logger.warning(f"  [Learn Mode] Failed to learn: {learn_err}")
```

---

## Phase 6: API Updates

### File: `backend/routes/flows.py`

**Update execute endpoint with new parameters:**

```python
@router.post("/flows/{device_id}/{flow_id}/execute")
async def execute_flow_on_demand(
    device_id: str,
    flow_id: str,
    learn_mode: bool = Query(default=False, description="Capture UI elements"),
    strict_mode: bool = Query(default=False, description="Fail on navigation errors"),
    repair_mode: bool = Query(default=False, description="Auto-update drifted bounds"),
    force_execute: bool = Query(default=False, description="Execute all steps, ignore sensor due times"),
    service: FlowService = Depends(get_flow_service),
):
    """
    Execute a flow on-demand with configurable modes
    """
    result = await service.execute_flow(
        device_id=device_id,
        flow_id=flow_id,
        learn_mode=learn_mode,
        strict_mode=strict_mode,
        repair_mode=repair_mode,
        force_execute=force_execute,
    )
    return result
```

---

## Phase 7: Frontend UI Updates

### File: `frontend/www/flows.html`

**Add mode checkboxes to flow execution UI:**

```html
<div class="execution-modes" style="margin-top: 12px; padding: 12px; background: #f5f5f5; border-radius: 8px;">
    <strong>Execution Modes:</strong>

    <label class="checkbox-label" style="margin-top: 8px;">
        <input type="checkbox" id="flowForceExecute">
        <strong>Force Execute</strong> - Run all steps (ignore sensor timers)
    </label>

    <label class="checkbox-label">
        <input type="checkbox" id="flowStrictMode">
        <strong>Strict Mode</strong> - Fail if navigation doesn't work
    </label>

    <label class="checkbox-label">
        <input type="checkbox" id="flowRepairMode">
        <strong>Repair Mode</strong> - Auto-fix element bounds drift
    </label>

    <label class="checkbox-label">
        <input type="checkbox" id="flowLearnMode">
        <strong>Learn Mode</strong> - Capture UI elements for future improvement
    </label>
</div>
```

### File: `frontend/www/js/modules/flow-manager.js`

**Update execute function to pass new parameters:**

```javascript
async executeFlow(deviceId, flowId, options = {}) {
    const params = new URLSearchParams();
    if (options.learnMode) params.append('learn_mode', 'true');
    if (options.strictMode) params.append('strict_mode', 'true');
    if (options.repairMode) params.append('repair_mode', 'true');
    if (options.forceExecute) params.append('force_execute', 'true');

    const url = `${API_BASE}/flows/${encodeURIComponent(deviceId)}/${flowId}/execute?${params}`;
    const response = await fetch(url, { method: 'POST' });
    return response.json();
}
```

---

## Phase 8: Execution Result Improvements

### File: `backend/core/flows/models.py`

**Add detailed failure info to FlowExecutionResult:**

```python
@dataclass
class FlowExecutionResult:
    flow_id: str
    success: bool
    executed_steps: int
    captured_sensors: Dict[str, Any]
    execution_time_ms: int
    error_message: Optional[str] = None
    step_results: List[StepResult] = field(default_factory=list)

    # NEW: Enhanced tracking
    navigation_failures: List[Dict] = field(default_factory=list)  # Steps where navigation failed
    bounds_repaired: List[Dict] = field(default_factory=list)  # Elements with auto-repaired bounds
    learned_screens: List[Dict] = field(default_factory=list)  # Screens captured in learn mode
    partial_success: bool = False  # True if some steps succeeded but flow had issues
```

---

## Testing Plan

### Test 1: Strict Mode Fails on Navigation Error
```bash
# Execute with strict_mode=true
curl -X POST "http://localhost:18085/api/flows/device/flow_id/execute?strict_mode=true"

# Expected: Flow fails when tap doesn't navigate to expected screen
# Result.success = False
# Result.navigation_failures contains the failed step
```

### Test 2: Force Execute Runs All Steps
```bash
# Execute with force_execute=true (even if sensors not due)
curl -X POST "http://localhost:18085/api/flows/device/flow_id/execute?force_execute=true"

# Expected: ALL steps execute, no "[Skip]" messages
# Sensors captured: 2 (not 0)
```

### Test 3: Repair Mode Fixes Bounds
```bash
# Execute with repair_mode=true when element has drifted
curl -X POST "http://localhost:18085/api/flows/device/flow_id/execute?repair_mode=true"

# Expected:
# - Element found via fallback strategy
# - Bounds auto-updated
# - Result.bounds_repaired contains the repair info
# - Future runs use correct bounds
```

### Test 4: Learn Mode Captures Failure Context
```bash
# Execute with learn_mode=true when navigation fails
curl -X POST "http://localhost:18085/api/flows/device/flow_id/execute?learn_mode=true&strict_mode=true"

# Expected:
# - Screen captured even when tap fails
# - Result.learned_screens[].step_success = false
# - Navigation graph updated with failure context
```

---

## Recommended Default Modes by Context

| Context | force_execute | strict_mode | repair_mode | learn_mode |
|---------|---------------|-------------|-------------|------------|
| Scheduled (production) | false | false | true | false |
| Manual test | true | true | false | true |
| Debug/troubleshoot | true | true | false | true |
| New flow validation | true | true | true | true |

---

## Implementation Order

1. **Phase 1**: Fix `_execute_tap()` return value (CRITICAL BUG FIX)
2. **Phase 2**: Add `strict_mode` parameter
3. **Phase 3**: Add `force_execute` parameter (fixes manual testing)
4. **Phase 4**: Add `repair_mode` with auto-bounds update
5. **Phase 5**: Learn from failures (not just successes)
6. **Phase 6**: API endpoint updates
7. **Phase 7**: Frontend UI updates
8. **Phase 8**: Enhanced result tracking

---

## Version Bump

After implementation: `0.4.0-beta.3.21`

---

## Summary

The Enhanced Learn Mode addresses:

| Problem | Solution |
|---------|----------|
| Tap always returns True | Return False when navigation fails (strict_mode) |
| Manual runs skip everything | force_execute bypasses sensor-due-check |
| Bounds drift not fixed | repair_mode auto-updates bounds |
| Only learn from success | Learn from failures too |
| Flow reports success despite errors | partial_success + navigation_failures tracking |

This transforms Learn Mode from a passive data collector into an active self-healing system.
