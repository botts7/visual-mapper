# Phase 2 Upgrade Plan - Enhanced ADB Connection

**Based on:** Visual Mapper v3 utils reference
**Current Version:** 0.0.2 (Phase 1)
**Target Version:** 0.0.3 (Phase 2)
**Last Updated:** 2025-12-22

---

## 🎯 Overview

Phase 1 implemented basic TCP/IP ADB connections using `adb-shell` library. Phase 2 will upgrade to the sophisticated multi-strategy approach from v3, supporting:

1. **Wireless Pairing (Android 11+)** with 6-digit codes
2. **TLS connections** on high ports (Android 11+ wireless debugging)
3. **Hybrid connection strategies** (Python ADB → Subprocess ADB → Network ADB)
4. **RSA key management** for persistent authentication
5. **Connection retry logic** with fallback strategies

---

## 📁 Files to Create/Update

### New Utility Files (from v3 reference)

**1. `utils/adb_connection.py`**
- Pure Python ADB using `AdbDeviceTcpAsync` (async version!)
- RSA key generation and management
- Wireless pairing via subprocess (Android 11+)
- TLS connection support (try TLS first, fallback to non-TLS)
- Connection locking with `asyncio.Lock()`
- Pull/push file operations

**Key Features:**
```python
- pair_with_code(pairing_host, pairing_port, pairing_code) → bool
- connect() → bool  # Auto-tries TLS first
- shell(command) → str
- pull(remote_path, local_path) → bool
- push(local_path, remote_path) → bool
```

**2. `utils/adb_manager.py`**
- Hybrid connection strategy manager
- Auto-detects best connection method:
  1. ADB Server addon (port 5037) - best
  2. Python ADB (port 5555) - good
  3. Subprocess ADB (high ports/TLS) - fallback
- Connection factory pattern

**Key Features:**
```python
- ensure_adb_available() → (bool, str)
- get_connection(host, port) → connection_instance
- test_adb(host, port) → bool
```

**3. `utils/adb_network.py`**
- Network ADB server connection (port 5037)
- Direct socket communication with ADB protocol
- Retry logic (MAX_RETRIES=3)
- Device transport switching

**Key Features:**
```python
- _send_adb_command(command) → str  # Low-level ADB protocol
- connect() → bool  # With retry logic
- shell(command) → str  # Via ADB server
```

**4. `utils/adb_subprocess.py`** (not yet reviewed, but referenced)
- Subprocess-based ADB for TLS connections
- Uses system `adb` binary when available
- For Android 11+ high-port connections

---

## 🔧 Changes to Existing Files

### `adb_bridge.py` → Enhanced Version

**Current (Phase 1):**
```python
class ADBBridge:
    def __init__(self):
        self.devices: Dict[str, AdbDeviceTcp] = {}  # Sync version
        self.signers: List[PythonRSASigner] = []  # Empty
```

**Phase 2 Upgrade:**
```python
from utils.adb_manager import ADBManager

class ADBBridge:
    def __init__(self):
        self.hass = None  # For standalone mode
        self.manager = ADBManager(self.hass)
        self.devices: Dict[str, connection] = {}  # Hybrid connections

    async def pair_device(self, pairing_host, pairing_port, pairing_code):
        """Wireless pairing for Android 11+"""
        conn = await self.manager.get_connection(pairing_host, pairing_port)
        if hasattr(conn, 'pair_with_code'):
            return await conn.pair_with_code(pairing_host, pairing_port, pairing_code)
        return False
```

### `server.py` → New Endpoints

**Add Pairing Endpoint:**
```python
class PairingRequest(BaseModel):
    pairing_host: str
    pairing_port: int
    pairing_code: str  # 6 digits

@app.post("/api/adb/pair")
async def pair_device(request: PairingRequest):
    """Pair with device using wireless pairing code"""
    try:
        success = await adb_bridge.pair_device(
            request.pairing_host,
            request.pairing_port,
            request.pairing_code
        )

        if success:
            # After pairing, connect on standard port
            device_id = await adb_bridge.connect_device(
                request.pairing_host,
                5555  # Standard port after pairing
            )
            return {"success": True, "device_id": device_id}
        else:
            raise HTTPException(status_code=500, detail="Pairing failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Frontend Updates

**`www/devices.html` JavaScript:**
```javascript
// Update pairing handler (currently shows "coming in Phase 2")
if (connectionType === 'pairing') {
    const pairingCode = document.getElementById('pairingCode').value.trim();
    const pairingHost = document.getElementById('pairingHost').value.trim();
    const pairingPort = parseInt(document.getElementById('pairingPort').value);

    // Validate inputs
    if (!pairingCode || !pairingHost || !pairingPort) {
        status.textContent = 'Please fill in all pairing fields';
        status.className = 'status error';
        return;
    }

    status.textContent = `Pairing with ${pairingHost}:${pairingPort}...`;
    status.className = 'status';

    // Call pairing API
    const response = await apiClient.post('/adb/pair', {
        pairing_host: pairingHost,
        pairing_port: pairingPort,
        pairing_code: pairingCode
    });

    status.textContent = `✓ Paired and connected: ${response.device_id}`;
    status.className = 'status success';

    await loadDevices();
}
```

**`www/js/modules/api-client.js`:**
```javascript
/**
 * Pair with Android 11+ device using wireless pairing
 * @param {string} pairingHost - Device IP
 * @param {number} pairingPort - Pairing port
 * @param {string} pairingCode - 6-digit code
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

## 🔑 Key Improvements from v3

### 1. **Async ADB Library**
Phase 1 uses `AdbDeviceTcp` (sync), Phase 2 uses `AdbDeviceTcpAsync` (async)
- Better performance
- Non-blocking operations
- Proper async/await throughout

### 2. **TLS Support**
```python
# Try TLS first (Android 11+ wireless)
try:
    await device.connect(rsa_keys=[signer], auth_timeout_s=10.0)
except:
    # Fallback to non-TLS (legacy port 5555)
    await device.connect(rsa_keys=[signer])
```

### 3. **RSA Key Management**
```python
# Generate keys if they don't exist
adbkey_path = "~/.android/adbkey"
if not os.path.isfile(adbkey_path):
    keygen(adbkey_path)

# Load and use for all connections
with open(adbkey_path) as f:
    priv = f.read()
with open(adbkey_path + '.pub') as f:
    pub = f.read()
signer = PythonRSASigner(pub, priv)
```

### 4. **Connection Strategy**
```python
if await check_adb_server():  # Port 5037
    return NetworkADBConnection(hass, device_id)
elif port != 5555:  # High port = TLS
    return SubprocessADBConnection(hass, device_id)
else:  # Standard port 5555
    return PythonADBConnection(hass, host, port)
```

### 5. **Wireless Pairing Flow**
```python
# Android 11+ pairing sequence:
# 1. User enables "Wireless debugging" on device
# 2. Taps "Pair device with pairing code"
# 3. Device shows: IP, pairing port (e.g., 37899), 6-digit code
# 4. User enters in Visual Mapper UI
# 5. Backend runs: adb pair <ip>:<port> with code as stdin
# 6. If successful, connect on port 5555
```

---

## 📦 Dependencies to Add

Update `requirements.txt`:
```python
# Change from sync to async version
adb-shell==0.4.4  # Keep current
# Or upgrade to async:
# adb-shell[async]==0.4.4

# Current dependencies (no changes needed)
fastapi==0.104.1
uvicorn[standard]==0.24.0
websockets==12.0
pydantic==2.5.0
python-multipart==0.0.6
pyyaml==6.0.1
```

---

## 🧪 Testing Strategy

### Unit Tests to Add

**1. `tests/unit/python/test_adb_connection.py`**
- Test RSA key generation
- Test TLS connection with fallback
- Test wireless pairing (mock subprocess)
- Test async operations

**2. `tests/unit/python/test_adb_manager.py`**
- Test connection strategy selection
- Test ADB server detection
- Test connection factory

**3. `tests/unit/python/test_adb_network.py`**
- Test ADB protocol communication
- Test retry logic
- Test device transport switching

### Integration Tests

**`tests/integration/test_pairing_flow.py`**
```python
async def test_wireless_pairing_android11():
    """Test complete pairing flow"""
    # 1. Pair with code
    paired = await adb_bridge.pair_device("192.168.1.100", 37899, "123456")
    assert paired

    # 2. Connect on port 5555
    device_id = await adb_bridge.connect_device("192.168.1.100", 5555)
    assert device_id == "192.168.1.100:5555"

    # 3. Test screenshot
    screenshot = await adb_bridge.capture_screenshot(device_id)
    assert len(screenshot) > 0
```

---

## 📋 Implementation Checklist

### Phase 2.1: Core Utilities
- [ ] Create `utils/` directory
- [ ] Copy and adapt `utils/adb_connection.py` from v3
- [ ] Copy and adapt `utils/adb_manager.py` from v3
- [ ] Copy and adapt `utils/adb_network.py` from v3
- [ ] Read and implement `utils/adb_subprocess.py` (if needed)
- [ ] Write unit tests for each utility

### Phase 2.2: ADB Bridge Upgrade
- [ ] Update `adb_bridge.py` to use ADBManager
- [ ] Add `pair_device()` method
- [ ] Switch from sync to async ADB library
- [ ] Add connection strategy logging
- [ ] Update existing tests

### Phase 2.3: API Endpoints
- [ ] Add `POST /api/adb/pair` endpoint
- [ ] Add `PairingRequest` model
- [ ] Add pairing response handling
- [ ] Write API endpoint tests

### Phase 2.4: Frontend
- [ ] Update pairing handler in `devices.html`
- [ ] Add `pairDevice()` to API client
- [ ] Remove "coming in Phase 2" warning
- [ ] Add pairing status feedback
- [ ] Test UI flow

### Phase 2.5: Documentation
- [ ] Update SETUP_GUIDE.md with pairing instructions
- [ ] Update ADB_CONNECTION_TYPES.md (mark pairing as ✅)
- [ ] Add troubleshooting for pairing issues
- [ ] Document RSA key location

### Phase 2.6: Testing & Validation
- [ ] Test with Android 11+ device (wireless pairing)
- [ ] Test with legacy device (port 5555)
- [ ] Test TLS connection on high port
- [ ] Test connection retry logic
- [ ] Test in Home Assistant addon

---

## 🚀 Benefits of Phase 2

1. ✅ **No USB cable required** for Android 11+
2. ✅ **Persistent pairing** survives device reboots
3. ✅ **Secure connections** with RSA keys
4. ✅ **TLS support** for modern Android
5. ✅ **Multiple connection strategies** with auto-fallback
6. ✅ **Better error handling** with retry logic
7. ✅ **Async operations** for better performance

---

## 📊 Version Progression

**Phase 1 (v0.0.2):** ✅ Complete
- Basic TCP/IP connections (port 5555)
- Screenshot capture
- UI element extraction
- Frontend with connection UI

**Phase 2 (v0.0.3):** 🚧 Planned
- Wireless pairing (Android 11+)
- TLS connections
- Hybrid connection strategies
- RSA key management

**Phase 3 (v0.0.4):** ⏭️ Future
- Home Assistant sensor creation
- Device state monitoring
- Automation triggers

---

**Document Version:** 1.0.0
**Created:** 2025-12-22
**Reference:** Y:\visual_mapper_v3_copy\utils\*
