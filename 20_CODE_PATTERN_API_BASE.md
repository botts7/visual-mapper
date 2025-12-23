# Code Pattern: API Base Detection

**Purpose:** Detect Home Assistant ingress URL dynamically for API calls.

**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## ⚠️ LEGACY REFERENCE - Test Before Using!

This pattern worked in v4.6.0-beta.X but should be validated in your environment.

---

## 🎯 The Problem

**Home Assistant Ingress changes the URL structure:**

```
Development:     http://localhost:3000/api/devices
HA Ingress:      http://homeassistant.local:8123/api/hassio_ingress/RANDOM_TOKEN/api/devices
```

**Hardcoded `/api/` paths fail in HA ingress!**

---

## ✅ The Solution

**⚠️ LEGACY REFERENCE:**

```javascript
// Pattern from legacy - worked in beta.X, validate before using!

function getApiBase() {
    // 1. Check if already set (cached)
    if (window.API_BASE) {
        return window.API_BASE;
    }

    // 2. Check parent/opener window (for popups)
    if (window.opener?.API_BASE) {
        window.API_BASE = window.opener.API_BASE;
        return window.API_BASE;
    }

    // 3. Detect from current URL
    const url = window.location.href;

    // Match ingress pattern: /api/hassio_ingress/TOKEN
    const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);

    if (ingressMatch) {
        // HA Ingress mode
        window.API_BASE = ingressMatch[0] + '/api';
        console.log('[API] Detected HA ingress:', window.API_BASE);
        return window.API_BASE;
    }

    // 4. Fallback to root /api
    window.API_BASE = '/api';
    console.log('[API] Using default:', window.API_BASE);
    return window.API_BASE;
}

// Usage in API calls
async function fetchDevices() {
    const apiBase = getApiBase();
    const response = await fetch(`${apiBase}/adb/devices`);
    return await response.json();
}
```

---

## 🔍 How It Works

### **Step 1: Check Cache**
```javascript
if (window.API_BASE) return window.API_BASE;
```
- Avoid re-detecting on every call
- Performance optimization

### **Step 2: Check Opener Window**
```javascript
if (window.opener?.API_BASE) return window.opener.API_BASE;
```
- Popup windows inherit from parent
- Avoids duplication

### **Step 3: Regex Detection**
```javascript
const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
```
- Matches: `/api/hassio_ingress/ANYTHING_EXCEPT_SLASH`
- Extracts the ingress prefix

### **Step 4: Fallback**
```javascript
return '/api';
```
- Works for localhost development
- Works for direct access (no ingress)

---

## 🧪 Testing

```javascript
// Test different URL scenarios

// Localhost
window.location.href = 'http://localhost:3000/main.html';
console.log(getApiBase()); // Expected: '/api'

// HA Ingress
window.location.href = 'http://homeassistant:8123/api/hassio_ingress/abc123/main.html';
console.log(getApiBase()); // Expected: '/api/hassio_ingress/abc123/api'
```

---

## 📝 Integration with ApiClient

```javascript
class ApiClient {
    constructor() {
        this.baseUrl = getApiBase();
        console.log('[ApiClient] Base URL:', this.baseUrl);
    }

    async get(endpoint) {
        const url = `${this.baseUrl}${endpoint}`;
        console.log('[ApiClient] GET:', url);

        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`GET ${endpoint}: ${response.statusText}`);
        }
        return await response.json();
    }
}
```

---

## 🚨 Common Mistakes

### ❌ **Hardcoding API path**
```javascript
// WRONG - fails in HA ingress
fetch('/api/adb/devices');
```

### ✅ **Using dynamic detection**
```javascript
// CORRECT
const apiBase = getApiBase();
fetch(`${apiBase}/adb/devices`);
```

---

## 📚 Related Documentation

- [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md) - ApiClient module
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Critical requirements

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.1+
