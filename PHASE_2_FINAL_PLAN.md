# Phase 2 Final Implementation Plan - Wireless ADB Support

**Target Version:** 0.0.3
**Current Version:** 0.0.2
**Goal:** Full wireless ADB support for Android 11+

---

## 🎯 Architecture Decision: Adapt V3 with Improvements

**Verdict:** V3 code is very good (8/10) but has room for refinement.

**Approach:**
- ✅ Use V3 patterns and logic
- ✅ Refactor to eliminate code duplication
- ✅ Add abstract base class for type safety
- ✅ Improve error handling specificity
- ✅ Add comprehensive type hints

---

## 🔑 Key Architectural Insight

**Why Subprocess is REQUIRED for Wireless ADB:**

```
Android 11+ Wireless Debugging Flow:
┌─────────────────────────────────────────────────────────┐
│ 1. PAIRING (one-time)                                  │
│    User: Enable wireless debugging → Pair device       │
│    Device shows: IP:37899 + 6-digit code               │
│    Backend: adb pair 192.168.1.100:37899               │
│    Result: RSA keys exchanged                          │
│    ⚠️ SUBPROCESS REQUIRED - adb-shell has no API       │
├─────────────────────────────────────────────────────────┤
│ 2. CONNECTION (persistent)                             │
│    Device listens on: 192.168.1.100:45441 (TLS)       │
│    Backend: adb connect 192.168.1.100:45441            │
│    Result: Secure TLS connection established           │
│    ⚠️ SUBPROCESS REQUIRED - adb-shell has no TLS       │
└─────────────────────────────────────────────────────────┘
```

**Connection Strategy Priority:**
1. **NetworkADB** (port 5037) - Best, reuses ADB server
2. **SubprocessADB** (port ≠ 5555) - Required for TLS/wireless
3. **PythonADB** (port 5555) - Good for legacy non-TLS

---

## 📦 New Files to Create

### 1. `utils/base_connection.py` (NEW - not in V3)
**Purpose:** Abstract base class to eliminate duplication

```python
"""
Base ADB Connection - Abstract interface for all connection types.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

_LOGGER = logging.getLogger(__name__)


class BaseADBConnection(ABC):
    """Abstract base for all ADB connection types."""

    def __init__(self, hass, device_id: str):
        self.hass = hass
        self.device_id = device_id
        self._connected = False

    async def _run_in_executor(self, func, *args):
        """Run sync function in executor (shared implementation)."""
        if hasattr(self.hass, 'async_add_executor_job'):
            return await self.hass.async_add_executor_job(func, *args)
        else:
            return await asyncio.to_thread(func, *args)

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to device. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def shell(self, command: str) -> str:
        """Execute shell command. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def pull(self, remote_path: str, local_path: str) -> bool:
        """Pull file from device. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def push(self, local_path: str, remote_path: str) -> bool:
        """Push file to device. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def close(self):
        """Close connection. Must be implemented by subclasses."""
        pass

    @property
    def available(self) -> bool:
        """Check if connection is available."""
        return self._connected
```

### 2. `utils/adb_connection.py` (Adapted from V3)
**Changes from V3:**
- Inherit from `BaseADBConnection`
- Remove duplicated `_run_in_executor`
- Add specific exception types
- Full type hints

### 3. `utils/adb_subprocess.py` (Adapted from V3)
**Changes from V3:**
- Inherit from `BaseADBConnection`
- Remove duplicated `_run_in_executor`
- Add subprocess availability check
- Better error messages for missing ADB binary

### 4. `utils/adb_network.py` (Adapted from V3)
**Changes from V3:**
- Inherit from `BaseADBConnection`
- Remove duplicated `_run_in_executor`
- Extract constants to config

### 5. `utils/adb_manager.py` (Adapted from V3)
**Changes from V3:**
- Use base class type hints
- Add configuration dataclass
- Better logging

### 6. `utils/config.py` (NEW - not in V3)
**Purpose:** Centralize configuration

```python
"""
ADB Connection Configuration.
"""
from dataclasses import dataclass


@dataclass
class ADBConfig:
    """Configuration for ADB connections."""

    # Retry settings
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 2  # seconds
    CONNECTION_TIMEOUT: int = 10  # seconds

    # ADB server settings
    ADB_SERVER_HOST: str = "127.0.0.1"
    ADB_SERVER_PORT: int = 5037

    # Default ports
    DEFAULT_ADB_PORT: int = 5555

    # Key locations
    ADB_KEY_DIR: str = "~/.android"
    ADB_KEY_NAME: str = "adbkey"

    # Timeouts
    SHELL_TIMEOUT: int = 30
    AUTH_TIMEOUT: float = 10.0
    TRANSPORT_TIMEOUT: float = 9.0
```

---

## 🔧 Changes to Existing Files

### `adb_bridge.py` → Enhanced with Manager

**Current (Phase 1):**
```python
class ADBBridge:
    def __init__(self):
        self.devices: Dict[str, AdbDeviceTcp] = {}  # Sync, single type
        self.signers: List[PythonRSASigner] = []  # Manual management
```

**Phase 2:**
```python
from utils.adb_manager import ADBManager
from utils.base_connection import BaseADBConnection

class ADBBridge:
    def __init__(self):
        self.hass = None  # Standalone mode
        self.manager = ADBManager(self.hass)
        self.devices: Dict[str, BaseADBConnection] = {}  # Hybrid connections

    async def pair_device(self, pairing_host: str, pairing_port: int, pairing_code: str) -> bool:
        """Wireless pairing for Android 11+."""
        conn = await self.manager.get_connection(pairing_host, pairing_port)
        if hasattr(conn, 'pair_with_code'):
            return await conn.pair_with_code(pairing_host, pairing_port, pairing_code)
        return False

    async def connect_device(self, host: str, port: int = 5555) -> str:
        """Connect using optimal strategy."""
        device_id = f"{host}:{port}"

        if device_id in self.devices:
            return device_id

        # Get optimal connection type from manager
        conn = await self.manager.get_connection(host, port)

        if await conn.connect():
            self.devices[device_id] = conn
            return device_id
        else:
            raise ConnectionError(f"Failed to connect to {device_id}")
```

### `server.py` → Add Pairing Endpoint

```python
class PairingRequest(BaseModel):
    pairing_host: str
    pairing_port: int
    pairing_code: str  # 6 digits

@app.post("/api/adb/pair")
async def pair_device(request: PairingRequest):
    """Pair with Android 11+ device using wireless pairing."""
    try:
        # Step 1: Pair with pairing port
        success = await adb_bridge.pair_device(
            request.pairing_host,
            request.pairing_port,
            request.pairing_code
        )

        if not success:
            raise HTTPException(status_code=500, detail="Pairing failed")

        # Step 2: Connect on port 5555 after successful pairing
        device_id = await adb_bridge.connect_device(request.pairing_host, 5555)

        return {
            "success": True,
            "device_id": device_id,
            "message": "Paired and connected successfully"
        }

    except Exception as e:
        logger.error(f"[API] Pairing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### `www/devices.html` → Enable Pairing

**Remove placeholder:**
```javascript
// OLD (lines 227-230):
// TODO: Implement pairing API endpoint
status.textContent = '⚠ Wireless pairing coming in Phase 2';
status.className = 'status warning';
return;

// NEW:
const response = await apiClient.post('/adb/pair', {
    pairing_host: pairingHost,
    pairing_port: pairingPort,
    pairing_code: pairingCode
});

status.textContent = `✓ Paired and connected: ${response.device_id}`;
status.className = 'status success';
await loadDevices();
```

### `www/js/modules/api-client.js` → Add Pairing Method

```javascript
/**
 * Pair with Android 11+ device using wireless pairing
 */
async pairDevice(pairingHost, pairingPort, pairingCode) {
    return this.post('/adb/pair', {
        pairing_host: pairingHost,
        pairing_port: pairingPort,
        pairing_code: pairingCode
    });
}
```

---

## 🧪 Testing Strategy

### Unit Tests to Add

**1. `tests/unit/python/test_base_connection.py`**
```python
def test_base_connection_abstract():
    """Verify base class cannot be instantiated."""
    with pytest.raises(TypeError):
        BaseADBConnection(None, "test:5555")

def test_run_in_executor_hass_mode():
    """Test executor with HA instance."""
    # Mock HA instance
    # Verify async_add_executor_job called

def test_run_in_executor_standalone_mode():
    """Test executor in standalone mode."""
    # Mock standalone mode
    # Verify asyncio.to_thread called
```

**2. `tests/unit/python/test_adb_subprocess.py`**
```python
@pytest.mark.asyncio
async def test_subprocess_connect_success():
    """Test subprocess connection success."""
    # Mock subprocess.run for adb connect
    # Verify connection established

@pytest.mark.asyncio
async def test_subprocess_missing_binary():
    """Test error when adb binary not found."""
    # Mock subprocess to fail
    # Verify proper error handling
```

**3. `tests/unit/python/test_adb_manager.py`**
```python
@pytest.mark.asyncio
async def test_manager_selects_network_adb():
    """Test manager chooses NetworkADB when port 5037 open."""
    # Mock port 5037 available
    # Verify NetworkADBConnection returned

@pytest.mark.asyncio
async def test_manager_selects_subprocess_for_high_port():
    """Test manager chooses SubprocessADB for TLS ports."""
    # Request port 45441 (TLS)
    # Verify SubprocessADBConnection returned
```

### Integration Tests

**`tests/integration/test_wireless_pairing.py`**
```python
@pytest.mark.asyncio
async def test_full_wireless_pairing_flow():
    """Test complete wireless pairing and connection."""
    # 1. Mock pairing subprocess (adb pair)
    # 2. Verify pairing success
    # 3. Mock connection on port 5555
    # 4. Verify device connected
    # 5. Test screenshot capture works
```

---

## 📋 Implementation Checklist

### Phase 2.1: Core Utilities (Base Class Approach)
- [ ] Create `utils/` directory
- [ ] Create `utils/config.py` with centralized settings
- [ ] Create `utils/base_connection.py` with abstract base class
- [ ] Adapt `utils/adb_connection.py` from V3 (inherit from base)
- [ ] Adapt `utils/adb_subprocess.py` from V3 (inherit from base)
- [ ] Adapt `utils/adb_network.py` from V3 (inherit from base)
- [ ] Adapt `utils/adb_manager.py` from V3 (use base class types)
- [ ] Write unit tests for each utility (test base class first)

### Phase 2.2: ADB Bridge Upgrade
- [ ] Update `adb_bridge.py` to use ADBManager
- [ ] Add `pair_device()` method
- [ ] Update `connect_device()` to use hybrid strategy
- [ ] Update `capture_screenshot()` to work with all connection types
- [ ] Update `get_ui_elements()` to work with all connection types
- [ ] Update existing tests

### Phase 2.3: API Endpoints
- [ ] Add `POST /api/adb/pair` endpoint
- [ ] Add `PairingRequest` Pydantic model
- [ ] Add pairing response handling
- [ ] Write API endpoint tests

### Phase 2.4: Frontend
- [ ] Remove "coming in Phase 2" placeholder in devices.html
- [ ] Implement pairing handler in devices.html
- [ ] Add `pairDevice()` to api-client.js
- [ ] Add pairing status feedback UI
- [ ] Test UI flow

### Phase 2.5: Documentation
- [ ] Update SETUP_GUIDE.md with pairing instructions
- [ ] Update ADB_CONNECTION_TYPES.md (mark pairing as ✅)
- [ ] Add troubleshooting for pairing issues
- [ ] Document RSA key location
- [ ] Add "Installing ADB binary" section

### Phase 2.6: Testing & Validation
- [ ] All unit tests passing
- [ ] Integration tests passing
- [ ] Test with Android 11+ device (wireless pairing)
- [ ] Test with legacy device (port 5555)
- [ ] Test TLS connection on high port
- [ ] Test connection retry logic
- [ ] Verify works in standalone mode
- [ ] Test in Home Assistant addon (user validation)

---

## 🚀 Benefits of This Approach

### Improvements Over Direct V3 Copy:

1. ✅ **No Code Duplication** - Base class eliminates repeated `_run_in_executor`
2. ✅ **Type Safety** - Abstract base class enforces interface consistency
3. ✅ **Better Configuration** - Centralized config instead of scattered constants
4. ✅ **Testability** - Base class can be tested independently
5. ✅ **Extensibility** - Easy to add new connection types (e.g., USB ADB)

### V3 Strengths We Keep:

1. ✅ **Hybrid Connection Strategy** - Auto-detects best method
2. ✅ **Async Throughout** - AdbDeviceTcpAsync for performance
3. ✅ **TLS Support** - Android 11+ wireless debugging
4. ✅ **Wireless Pairing** - Subprocess-based pairing flow
5. ✅ **RSA Key Management** - Auto-generation and persistence
6. ✅ **Retry Logic** - Connection resilience

---

## 🎯 Success Criteria

**Phase 2 is complete when:**
- [ ] User can pair Android 11+ device with 6-digit code
- [ ] Connection persists after pairing (survives device reboot)
- [ ] TLS connections work on high ports (e.g., 45441)
- [ ] Legacy port 5555 still works
- [ ] ADB server addon is auto-detected if available
- [ ] All tests pass (>60% coverage maintained)
- [ ] Documentation is complete
- [ ] User validates in real Home Assistant

---

**Implementation Start:** Ready when user approves
**Estimated Completion:** Phase 2.1-2.6 (incremental with TDD)
**Next Phase:** Phase 3 - Device Control (v0.0.4)
