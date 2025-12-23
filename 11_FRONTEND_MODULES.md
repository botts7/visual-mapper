# Frontend Modules - ES6 Architecture

**Purpose:** Complete guide to Visual Mapper's frontend ES6 module system.

**Starting Version:** 0.0.1
**Target Version:** 1.0.0
**Last Updated:** 2025-12-21

---

## ⚠️ Important Notes

**Code examples are LEGACY REFERENCE from v4.6.0-beta.X - TEST BEFORE USING!**

- These patterns worked in beta but may have bugs
- Always validate before relying on them
- This is the TARGET architecture for the rebuild
- Not all modules exist yet in v0.0.1

---

## 🎯 Module System Overview

Visual Mapper uses **vanilla ES6 modules** with a **dual export pattern**.

**Why ES6 Modules?**
- Native browser support (no build step)
- Tree-shaking benefits
- Clear dependency graph
- Isolated scopes

**Why Dual Exports?**
- Popup windows don't share ES6 scope
- Legacy code compatibility
- Dynamic loading support

---

## 📋 Module List (Target for v0.1.0)

| Module | Purpose | Status | Priority |
|--------|---------|--------|----------|
| init.js | Module loader & initialization | Foundation | Phase 0 |
| api-client.js | REST API wrapper | Foundation | Phase 0 |
| event-bus.js | Event system (pub/sub) | Foundation | Phase 0 |
| device-manager.js | Device connection/state | Screenshot | Phase 1 |
| screenshot-capture.js | Screenshot handling | Screenshot | Phase 1 |
| overlay-renderer.js | Canvas overlay drawing | Screenshot | Phase 1 |
| coordinate-mapper.js | Coord conversion | Control | Phase 2 |
| sensor-manager.js | Sensor CRUD | Sensors | Phase 3 |
| action-manager.js | Action automation | Actions | Phase 3 |
| websocket-client.js | WebSocket connection | Streaming | Phase 4 |

---

## 🔧 Dual Export Pattern

**⚠️ LEGACY REFERENCE - Test before using!**

```javascript
// www/js/modules/example-module.js

class ExampleModule {
    constructor(apiClient, eventBus) {
        this.apiClient = apiClient;
        this.eventBus = eventBus;
        this.state = {};
    }

    init() {
        console.log('[ExampleModule] Initialized');
        this.bindEvents();
    }

    bindEvents() {
        this.eventBus.on('example:event', (data) => {
            this.handleEvent(data);
        });
    }

    async doSomething() {
        const result = await this.apiClient.get('/api/endpoint');
        this.eventBus.emit('example:complete', result);
        return result;
    }
}

// ES6 export (for main window imports)
export default ExampleModule;

// Global export (for popups, legacy code)
window.ExampleModule = ExampleModule;
```

**Why both exports?**
1. ES6 `export default` - Modern, allows tree-shaking
2. `window.ExampleModule` - Popups, dynamic loading, backward compat

---

## 🚀 Module Loading (init.js)

**⚠️ LEGACY REFERENCE - Validate before using!**

```javascript
// www/js/init.js

const APP_VERSION = '0.0.1';

// CRITICAL: Cache busting on ALL imports!
const MODULES = [
    'modules/api-client.js',
    'modules/event-bus.js',
    'modules/device-manager.js',
    'modules/screenshot-capture.js',
    'modules/overlay-renderer.js',
    'modules/coordinate-mapper.js',
    'modules/sensor-manager.js',
    'modules/action-manager.js',
    'modules/websocket-client.js'
];

async function loadModules() {
    console.log(`[Init] Loading Visual Mapper ${APP_VERSION}`);
    const startTime = performance.now();

    for (const modulePath of MODULES) {
        try {
            // CRITICAL: Add ?v= for cache busting!
            await import(`./${modulePath}?v=${APP_VERSION}`);
            console.log(`[Init] ✅ ${modulePath}`);
        } catch (error) {
            console.error(`[Init] ❌ Failed to load ${modulePath}:`, error);
            // Don't stop loading other modules
        }
    }

    const loadTime = performance.now() - startTime;
    console.log(`[Init] Loaded in ${loadTime.toFixed(2)}ms`);
}

async function initApp() {
    // Wait for DOM
    if (document.readyState === 'loading') {
        await new Promise(resolve => {
            document.addEventListener('DOMContentLoaded', resolve);
        });
    }

    // Load all modules
    await loadModules();

    // Initialize singletons (global instances)
    if (window.ApiClient) {
        window.apiClient = new window.ApiClient();
    }

    if (window.EventBus) {
        window.eventBus = new window.EventBus();
    }

    if (window.DeviceManager) {
        window.deviceManager = new window.DeviceManager(
            window.apiClient,
            window.eventBus
        );
        await window.deviceManager.init();
    }

    console.log('[Init] ✅ App ready');
}

// Start app
initApp().catch(error => {
    console.error('[Init] Fatal error:', error);
});
```

**Key Points:**
- Cache busting with `?v=${APP_VERSION}` on every import
- DOM ready check before initialization
- Error handling doesn't stop other modules
- Global singleton pattern for shared services

---

## 📚 Module Specifications

### **1. api-client.js - REST API Wrapper**

**Purpose:** Centralize all API calls with HA ingress support

**⚠️ LEGACY REFERENCE:**

```javascript
class ApiClient {
    constructor() {
        this.baseUrl = this.detectApiBase();
    }

    detectApiBase() {
        // Check if already set
        if (window.API_BASE) return window.API_BASE;
        if (window.opener?.API_BASE) return window.opener.API_BASE;

        // Detect HA ingress path
        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
        if (ingressMatch) {
            return ingressMatch[0] + '/api';
        }

        // Fallback
        return '/api';
    }

    async get(endpoint) {
        const response = await fetch(`${this.baseUrl}${endpoint}`);
        if (!response.ok) {
            throw new Error(`GET ${endpoint}: ${response.statusText}`);
        }
        return await response.json();
    }

    async post(endpoint, data) {
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            throw new Error(`POST ${endpoint}: ${response.statusText}`);
        }
        return await response.json();
    }
}

export default ApiClient;
window.ApiClient = ApiClient;
```

### **2. event-bus.js - Event System**

**Purpose:** Decouple modules with pub/sub pattern

**⚠️ LEGACY REFERENCE:**

```javascript
class EventBus {
    constructor() {
        this.listeners = new Map();
    }

    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    off(event, callback) {
        if (!this.listeners.has(event)) return;
        const callbacks = this.listeners.get(event);
        const index = callbacks.indexOf(callback);
        if (index > -1) {
            callbacks.splice(index, 1);
        }
    }

    emit(event, data) {
        if (!this.listeners.has(event)) return;
        this.listeners.get(event).forEach(callback => {
            try {
                callback(data);
            } catch (error) {
                console.error(`[EventBus] Error in ${event} handler:`, error);
            }
        });
    }
}

export default EventBus;
window.EventBus = EventBus;
```

### **3. coordinate-mapper.js - Coordinate Conversion**

**Purpose:** Convert between display coords and screenshot coords

**⚠️ LEGACY REFERENCE:**

```javascript
class CoordinateMapper {
    constructor() {
        this.scale = 1.0;
        this.offsetX = 0;
        this.offsetY = 0;
    }

    setScale(canvasWidth, canvasHeight, imageWidth, imageHeight) {
        const scaleX = canvasWidth / imageWidth;
        const scaleY = canvasHeight / imageHeight;
        this.scale = Math.min(scaleX, scaleY);

        // Calculate offset to center image
        const scaledWidth = imageWidth * this.scale;
        const scaledHeight = imageHeight * this.scale;
        this.offsetX = (canvasWidth - scaledWidth) / 2;
        this.offsetY = (canvasHeight - scaledHeight) / 2;
    }

    displayToDevice(x, y) {
        return {
            x: Math.round((x - this.offsetX) / this.scale),
            y: Math.round((y - this.offsetY) / this.scale)
        };
    }

    deviceToDisplay(x, y) {
        return {
            x: Math.round((x * this.scale) + this.offsetX),
            y: Math.round((y * this.scale) + this.offsetY)
        };
    }
}

export default CoordinateMapper;
window.CoordinateMapper = CoordinateMapper;
```

---

## 🎯 Critical Requirements

### **1. Cache Busting - EVERYWHERE**

```html
<!-- In HTML -->
<script type="module" src="js/init.js?v=0.0.1"></script>
```

```javascript
// In dynamic imports
await import(`./modules/api-client.js?v=${APP_VERSION}`);
```

### **2. DOM Ready Checks**

```javascript
// ALWAYS check element exists
const element = document.getElementById('my-element');
if (!element) {
    console.error('[Module] Element not found');
    return;
}
```

### **3. Error Handling**

```javascript
try {
    await module.doSomething();
} catch (error) {
    console.error('[Module] Error:', error);
    // Show user-friendly message
    alert('Operation failed: ' + error.message);
}
```

---

## 📝 Module Development Checklist

When creating a new module:

- [ ] Use dual export pattern (ES6 + global)
- [ ] Accept dependencies via constructor
- [ ] Add null checks for DOM elements
- [ ] Wrap async calls in try/catch
- [ ] Emit events for state changes
- [ ] Add console logging with [ModuleName] prefix
- [ ] Write unit tests BEFORE implementation
- [ ] Document public methods
- [ ] Test in popup windows
- [ ] Test cache busting works

---

## 🧪 Testing Modules

```javascript
// tests/unit/js/example-module.test.js
import { describe, it, expect, beforeEach } from '@jest/globals';
import ExampleModule from '../../../www/js/modules/example-module.js';

describe('ExampleModule', () => {
    let module;
    let mockApiClient;
    let mockEventBus;

    beforeEach(() => {
        mockApiClient = {
            get: jest.fn(),
            post: jest.fn()
        };
        mockEventBus = {
            on: jest.fn(),
            emit: jest.fn()
        };
        module = new ExampleModule(mockApiClient, mockEventBus);
    });

    it('should initialize', () => {
        module.init();
        expect(mockEventBus.on).toHaveBeenCalled();
    });

    it('should handle events', async () => {
        mockApiClient.get.mockResolvedValue({ data: 'test' });
        await module.doSomething();
        expect(mockEventBus.emit).toHaveBeenCalledWith('example:complete', expect.any(Object));
    });
});
```

---

## 📚 Related Documentation

- [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md) - Overall architecture
- [12_BACKEND_API.md](12_BACKEND_API.md) - API endpoints
- [20_CODE_PATTERN_API_BASE.md](20_CODE_PATTERN_API_BASE.md) - HA ingress detection
- [21_CODE_PATTERN_MODULES.md](21_CODE_PATTERN_MODULES.md) - Module patterns

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.1.0

**Read Next:** [12_BACKEND_API.md](12_BACKEND_API.md)
**Read Previous:** [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md)
