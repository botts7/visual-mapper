# Plan: Fix Companion App IP Matching Issues

## Status: Completed

## Problem Statement
Companion app frames were not being matched to ADB devices when the IP addresses differed. This happened because:
1. Companion app registers with its WiFi IP (e.g., `192.168.86.129`)
2. ADB connects to a different IP (e.g., `192.168.86.2:5555`)
3. The IP matching in `find_companion_for_device()` failed
4. Multi-device setups couldn't use the single-companion fallback

## Analysis
The matching algorithm only supported:
1. IP address match (failed when perspectives differ)
2. Single companion fallback (only worked with exactly 1 device)

Root cause: System assumed ADB IP == companion's self-reported IP, which isn't true when:
- ADB connects through WiFi debugging port
- NAT or subnet differences exist
- Backend sees different network perspective than device

## Solution

### 1. Added serial-based matching (new Strategy 2)
- Extended `find_companion_for_device()` to accept optional `adb_serial` parameter
- Added serial mapping dictionaries to `CompanionStreamReceiver`
- Serial matching is attempted between IP and single-companion fallback

### 2. Added serial mapping infrastructure
New methods in `companion_receiver.py`:
- `register_serial_mapping(adb_device_id, serial, companion_device_id)`
- `set_companion_serial(companion_device_id, serial)`
- `get_companion_by_serial(serial)`

### 3. Integrated serial lookup at call sites
Updated all `find_companion_for_device()` calls in `streaming.py` to:
- Get cached ADB serial via `adb_bridge.get_cached_serial()`
- Pass serial to matching function

### 4. Automatic serial registration from MQTT
When companion announces via MQTT with a `device_serial`:
- Automatically register the serial mapping
- Enables cross-subnet frame matching

## Files Modified

### `backend/core/streaming/companion_receiver.py`
- Added `_serial_to_companion` and `_companion_serials` dictionaries
- Added serial mapping methods
- Updated `find_companion_for_device()` with serial matching strategy

### `backend/routes/streaming.py`
- Updated all `find_companion_for_device()` calls to pass ADB serial
- Added serial info to debug status endpoint

### `backend/main.py`
- Added automatic serial registration from MQTT device announcements

## Matching Strategy (updated)

1. **IP address match** - Direct IP comparison (existing)
2. **Serial match** - Match by device hardware serial (new)
3. **Single companion fallback** - If only 1 companion, assume match (existing)

## Risks & Mitigations
- Risk: Serial not always available from MQTT
  - Mitigation: Graceful fallback to IP-only and single-companion strategies
- Risk: Serial cache may be empty on first connection
  - Mitigation: Serial is cached on first ADB command, then available for matching

## Testing Plan
- [x] Code review for consistency
- [ ] Manual test: Single device with IP mismatch (should match via fallback)
- [ ] Manual test: Multi-device with serial announcement (should match via serial)
- [ ] Check debug endpoint shows serial mappings

## Progress Log
### 2026-01-26
- Analyzed companion_receiver.py and streaming.py
- Identified IP matching limitation
- Implemented serial-based matching strategy
- Updated all call sites to pass ADB serial
- Added MQTT serial registration
