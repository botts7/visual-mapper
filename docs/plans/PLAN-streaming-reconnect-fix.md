# Plan: Fix Streaming Reconnection Loop

## Status: Completed

## Problem Statement
The streaming WebSocket exhibited a "reconnection loop" causing UX degradation where users would see rapid status changes ("Connecting -> Retry 1 -> Retry 2...") even after manually stopping the stream.

## Analysis
Root cause analysis revealed a race condition:

1. When `stop()` is called, it sets `_manualStop = true` and clears the reconnect timer
2. However, if the setTimeout callback from `_scheduleReconnect()` was already dequeued by the event loop, it would fire `_connect()` anyway
3. The `_connect()` method had no guard check to verify that streaming should still be active
4. This created "zombie reconnections" - connections that happened even after the user stopped streaming

**Key locations:**
- `live-stream.js:_connect()` - No guard check for `_manualStop`
- `live-stream.js:_scheduleReconnect()` - setTimeout callback didn't re-check state before reconnecting

## Solution

Added guard checks in two locations to prevent zombie reconnections:

### 1. In `_connect()` method (line 271)
Added early return checks for:
- `_manualStop` flag - abort if stream was manually stopped
- `deviceId` presence - abort if device ID was cleared by stop()

### 2. In `_scheduleReconnect()` setTimeout callback (line 410)
Added same guard checks before incrementing attempts and calling `_connect()`.

## Files Modified
- `frontend/www/js/modules/live-stream.js` - Added guard checks, updated version to 0.0.41

## Risks & Mitigations
- Risk: Legitimate reconnections might be blocked
  - Mitigation: Guards only check `_manualStop` which is only set by explicit `stop()` calls, and reset in `start()`
- Risk: State could become inconsistent
  - Mitigation: Guard checks set connection state to 'disconnected' when aborting

## Testing Plan
- [x] Manual test: Start streaming, stop streaming, verify no reconnection attempts
- [x] Manual test: Start streaming, disconnect network, verify reconnection attempts
- [x] Code review: Verified guards check same conditions as `onclose` handler

## Progress Log
### 2026-01-26
- Analyzed codebase with Explore agent
- Identified race condition in reconnect logic
- Implemented guard checks in `_connect()` and `_scheduleReconnect()`
- Updated version number
