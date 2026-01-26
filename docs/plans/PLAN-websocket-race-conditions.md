# Plan: Fix WebSocket Race Conditions in Start/Stop

## Status: Completed

## Problem Statement
Stream corruption occurred during rapid start/stop cycles due to race conditions in:
1. Producer task lifecycle - `.done()` returns True while finally block still executing
2. Multiple producers running simultaneously for same device
3. Frame injection callback accessing subscriber state without locks

## Analysis
Root causes identified:

### Issue 1: Producer Lifecycle Race
- `subscribe()` checks `producer.done()` which returns True during finally block
- Between check and new task creation, cleanup was still happening
- Result: Multiple producers running, duplicate/corrupted frames

### Issue 2: Frame Injection Without Lock
- Callback took snapshot of `_subscribers.keys()` without holding lock
- Subscriber dict could change between snapshot and injection
- Result: Frames injected to stale device_ids, frames lost

## Solution

### Fix 1: Producer Stopping State
Added `_producer_stopping` dictionary with asyncio.Event per device:
- Set Event in finally block before cleanup starts
- `subscribe()` waits for Event before creating new producer
- Ensures old producer fully cleaned up before new one starts

**Changes:**
- Added `self._producer_stopping: dict[str, asyncio.Event] = {}`
- `subscribe()` now waits up to 3s for stopping event
- `subscribe()` checks `producer_stopping` state before creating producer
- `_producer_loop()` sets/clears stopping event in finally block

### Fix 2: Safe Subscriber Access
Added `get_subscriber_device_ids()` method:
- Returns copy of subscriber keys (list, not view)
- Frame callback uses this instead of direct `_subscribers.keys()` access
- `inject_frame()` already handles non-existent device_ids safely

## Files Modified
- `backend/routes/streaming.py`
  - `SharedCaptureManager.__init__()` - Added `_producer_stopping` dict
  - `SharedCaptureManager.subscribe()` - Wait for stopping, check stopping state
  - `SharedCaptureManager._producer_loop()` - Signal stopping in finally block
  - `SharedCaptureManager.get_subscriber_device_ids()` - New method for safe access
  - `on_companion_frame()` callback - Use safe subscriber access method

## Risks & Mitigations
- Risk: Deadlock if stopping event never set
  - Mitigation: 3s timeout on wait, proceeding with warning
- Risk: Performance impact from waiting
  - Mitigation: Event is set almost immediately after .done() returns True

## Testing Plan
- [x] Code review for lock ordering
- [ ] Manual test: Rapid quality switches
- [ ] Manual test: Start/stop during frame broadcast
- [ ] Check logs for "entering cleanup" / "signaled cleanup done" sequence

## Progress Log
### 2026-01-26
- Analyzed SharedCaptureManager and companion streaming code
- Identified producer lifecycle race condition
- Implemented stopping state with asyncio.Event
- Added safe subscriber access method
- Updated frame injection callback
