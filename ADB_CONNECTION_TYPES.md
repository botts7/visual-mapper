# ADB Connection Types - Visual Mapper

**Version:** 0.0.2 (Phase 1)
**Last Updated:** 2025-12-22

---

## Overview

Visual Mapper supports multiple ADB connection methods for different Android versions and security requirements.

---

## ✅ Currently Supported (Phase 1)

### 1. **TCP/IP - Legacy (Port 5555)**

**Status:** ✅ Fully Implemented

**Use Case:** Traditional ADB over network (Android 4.0+)

**Setup:**
1. Enable USB debugging on Android device
2. Connect device to computer via USB
3. Run: `adb tcpip 5555`
4. Disconnect USB
5. Run: `adb connect <device-ip>:5555`
6. Use Visual Mapper to connect to `<device-ip>:5555`

**Pros:**
- Works on all Android versions with ADB support
- Well-established, stable connection
- No pairing required after initial USB setup

**Cons:**
- Requires initial USB connection
- Less secure (no encryption)
- Must manually enable each time device reboots

---

### 2. **Wireless ADB - Android 11+ (Port 5555)**

**Status:** ✅ Fully Implemented (same as TCP/IP)

**Use Case:** Modern Android devices with built-in wireless debugging

**Setup:**
1. Enable Developer Options on Android device
2. Go to: Settings → Developer Options → Wireless debugging
3. Enable "Wireless debugging"
4. Tap on "Wireless debugging" to see IP address and port
5. Use Visual Mapper to connect to shown IP:port

**Pros:**
- No USB cable required
- Built into Android 11+
- Easy toggle on/off from device settings

**Cons:**
- Android 11+ only
- Still uses port 5555 (less secure)
- Must re-enable after device reboot

**Note:** Currently uses the same TCP connection method as legacy ADB. True wireless pairing with QR codes coming in Phase 2.

---

## ⚠️ Planned for Future Phases

### 3. **Wireless Pairing - Android 11+ (Dynamic Port)**

**Status:** 🚧 Coming in Phase 2

**Use Case:** Secure wireless connection with pairing code

**Setup:**
1. Enable Developer Options
2. Go to: Settings → Developer Options → Wireless debugging
3. Tap "Pair device with pairing code"
4. Enter the 6-digit code and port shown on device
5. After pairing, use regular wireless connection

**Pros:**
- Most secure wireless method
- No USB required
- Pairing persists across reboots

**Cons:**
- Android 11+ only
- Requires pairing step
- More complex setup

**Implementation Plan:**
- Add pairing API endpoint
- Implement pairing handshake protocol
- Store pairing keys for reconnection

---

### 4. **TLS/Secure ADB (Custom Port)**

**Status:** 🚧 Coming in Phase 3+

**Use Case:** Enterprise/high-security environments

**Setup:**
1. Generate TLS certificates
2. Configure device with certificate
3. Configure Visual Mapper with matching certificate
4. Connect using secure connection

**Pros:**
- Encrypted connection
- Certificate-based authentication
- Suitable for enterprise deployments

**Cons:**
- Complex setup
- Requires certificate management
- Not common in typical use cases

**Implementation Plan:**
- Certificate generation utilities
- TLS handshake implementation
- Certificate storage and management

---

## 🔧 Current Implementation

**Phase 1 (v0.0.2):**
- ✅ TCP/IP connections (legacy and wireless)
- ✅ Connection management (connect, disconnect, list)
- ✅ Screenshot capture
- ✅ UI element extraction

**Phase 2 (v0.0.3) - Planned:**
- 🚧 Wireless pairing with code
- 🚧 QR code pairing
- 🚧 Persistent device connections
- 🚧 Auto-reconnect on network change

**Phase 3+ - Future:**
- 🚧 TLS/Secure ADB
- 🚧 USB connection support
- 🚧 Multiple simultaneous devices
- 🚧 Device discovery/scanning

---

## 📚 References

- [Android ADB Documentation](https://developer.android.com/studio/command-line/adb)
- [Wireless Debugging (Android 11+)](https://developer.android.com/studio/command-line/adb#wireless)
- [adb-shell Python Library](https://github.com/JeffLIrion/adb_shell)

---

**Document Version:** 1.0.0
**Created:** 2025-12-22
**Target Version:** Visual Mapper 0.0.2+
