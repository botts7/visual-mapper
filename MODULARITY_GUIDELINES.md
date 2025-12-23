# Visual Mapper - Modularity Guidelines

**Version:** 1.0.0
**Last Updated:** 2025-12-22
**Applies To:** All new code from Phase 2 onward

---

## 🎯 Core Principle

> **"MODULARITY IS REQUIRED: Always keep code modular, clean, reusable, and easier to maintain. Create separate module files for distinct functionality rather than inline everything."**

---

## ✅ When to Create a Module

Create a new module when **ANY** of these conditions are met:

1. **Size**: Functionality exceeds **50 lines** of code
2. **Reusability**: Logic will be used across multiple pages
3. **Responsibility**: Code has a distinct, single responsibility
4. **State**: Contains stateful logic (intervals, timers, state variables)
5. **Complexity**: Contains complex business logic

---

## 📂 Module Structure

### **Location**
```
www/js/modules/
├── [module-name].js
```

### **Template**
```javascript
/**
 * Visual Mapper - [Module Name]
 * Version: 0.0.X (Phase X)
 *
 * [Brief description of what this module does]
 */

class ModuleName {
    constructor(dependencies) {
        // Store dependencies
        this.dependency = dependencies;

        // Initialize state
        this.state = {};

        console.log('[ModuleName] Initialized');
    }

    /**
     * Public method description
     * @param {type} param - Description
     * @returns {type} Description
     */
    publicMethod(param) {
        // Implementation
    }

    /**
     * Private method (prefix with _)
     * @private
     */
    _privateMethod() {
        // Implementation
    }

    /**
     * Get current state
     * @returns {Object} State object
     */
    getState() {
        return { ...this.state };
    }
}

// ES6 export
export default ModuleName;

// Global export for non-module usage
window.ModuleName = ModuleName;
```

---

## 📋 Current Module Inventory

| Module | Size | Purpose | Phase |
|--------|------|---------|-------|
| `api-client.js` | ~120 lines | API communication | Phase 0 |
| `screenshot-capture.js` | ~240 lines | Screenshot rendering & overlays | Phase 1 |
| `device-control.js` | ~200 lines | Tap/swipe/type controls | Phase 2 |
| `auto-refresh.js` | 154 lines | Auto-refresh with pause/resume | Phase 2 |
| `activity-monitor.js` | 117 lines | Page change detection | Phase 2 |
| `device-manager.js` | 142 lines | Device connection/selection | Phase 2 |
| `overlay-filters.js` | 120 lines | Filter control binding | Phase 2 |

**Total**: 7 modules, ~1,093 lines of modular code

---

## 🎨 HTML Page Guidelines

### **DO:**
- ✅ Import modules at the top
- ✅ Initialize module instances
- ✅ Wire up UI event handlers (< 200 lines total inline code)
- ✅ Keep page-specific initialization code inline
- ✅ Use modules for complex logic

### **DON'T:**
- ❌ Write complex business logic inline
- ❌ Duplicate functionality across pages
- ❌ Exceed 300 lines of inline JavaScript
- ❌ Manage complex state in global variables
- ❌ Write inline code that could be reused

---

## 🔄 Module Dependencies

### **Import Example**
```javascript
import APIClient from './js/modules/api-client.js?v=0.0.8';
import ScreenshotCapture from './js/modules/screenshot-capture.js?v=0.0.8';
import AutoRefresh from './js/modules/auto-refresh.js?v=0.0.8';

const apiClient = new APIClient();
const screenshotCapture = new ScreenshotCapture(apiClient, canvas);
const autoRefresh = new AutoRefresh(screenshotCapture);
```

### **Dependency Injection**
Always pass dependencies via constructor:
```javascript
class MyModule {
    constructor(apiClient, otherDependency) {
        this.apiClient = apiClient;
        this.other = otherDependency;
    }
}
```

**Don't** import dependencies inside the module (creates tight coupling).

---

## 📝 Naming Conventions

### **Module Files**
- Use kebab-case: `auto-refresh.js`, `device-manager.js`
- Be descriptive: `activity-monitor.js` not `monitor.js`

### **Class Names**
- Use PascalCase: `AutoRefresh`, `DeviceManager`
- Match file name: `auto-refresh.js` → `AutoRefresh`

### **Methods**
- Use camelCase: `startMonitoring()`, `getState()`
- Private methods prefix with `_`: `_internalHelper()`

---

## 🧪 Testing Strategy

Each module should be:
1. **Unit testable**: Mock dependencies via constructor
2. **Isolated**: No global state or side effects
3. **Documented**: JSDoc comments for all public methods

**Future (Phase 5)**:
```javascript
// tests/modules/auto-refresh.test.js
import AutoRefresh from '../../www/js/modules/auto-refresh.js';

describe('AutoRefresh', () => {
    it('should start auto-refresh with interval', () => {
        // Test implementation
    });
});
```

---

## 📊 Size Limits

| Scope | Max Lines | Action if Exceeded |
|-------|-----------|-------------------|
| Single module | 300 lines | Split into sub-modules |
| HTML inline JS | 300 lines | Extract to modules |
| Single function | 50 lines | Refactor into smaller functions |

---

## 🚀 Phase 3+ Module Plan

As we implement sensor creation, we'll add:

### **Sensor Creation Modules**
- `element-selector.js` - Element selection mode (~150 lines)
- `sensor-creator.js` - Sensor definition UI (~200 lines)
- `sensor-manager.js` - CRUD operations (~180 lines)
- `text-extractor.js` - Extraction rule UI (~160 lines)

**Keeps pages maintainable as we scale to v1.0.0!**

---

## ✅ Benefits

1. **Maintainability**: Each module < 300 lines (easy to understand)
2. **Reusability**: Use modules across pages (devices.html, sensors.html, etc.)
3. **Testability**: Mock dependencies, test in isolation
4. **Scalability**: Add features without bloating pages
5. **Collaboration**: Team members can work on different modules
6. **Debugging**: Easier to trace issues to specific modules

---

## 📚 Examples

### **Before Modularization**
```javascript
// devices.html - 666 lines (400+ inline JavaScript)
<script>
    let autoRefreshInterval = null;
    let isCapturing = false;
    // ... 400 more lines of inline code
</script>
```

### **After Modularization**
```javascript
// devices.html - 641 lines (200 inline, rest in modules)
<script type="module">
    import AutoRefresh from './js/modules/auto-refresh.js?v=0.0.8';

    const autoRefresh = new AutoRefresh(screenshotCapture);
    autoRefresh.start(interval, deviceId, callback);
</script>
```

**Result**: 4 reusable modules (~530 lines) + cleaner HTML

---

**Document Version:** 1.0.0
**Created:** 2025-12-22
**Next Review:** After Phase 3 complete
**Enforcement:** Required for all new code
