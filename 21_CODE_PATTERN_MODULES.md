# Code Pattern: Dual Export (ES6 + Global)

**Purpose:** Module pattern that works in both ES6 and popup windows.

**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## ⚠️ LEGACY REFERENCE - Test Before Using!

This pattern worked in v4.6.0-beta.X but validate in your environment.

---

## 🎯 The Problem

**ES6 modules don't share scope with popup windows:**

```javascript
// main.html loads module
import MyModule from './modules/my-module.js';

// popup.html opened from main.html
window.MyModule  // undefined! Different scope!
```

---

## ✅ The Solution: Dual Export

**⚠️ LEGACY REFERENCE:**

```javascript
// www/js/modules/my-module.js

class MyModule {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.data = [];
    }

    async fetchData() {
        this.data = await this.apiClient.get('/endpoint');
        return this.data;
    }
}

// ES6 export (for module imports)
export default MyModule;

// Global export (for popups, legacy code)
window.MyModule = MyModule;
```

**Usage:**

```javascript
// In main window (ES6 import)
import MyModule from './modules/my-module.js';
const module = new MyModule(apiClient);

// In popup window (global access)
const module = new window.MyModule(window.opener.apiClient);
```

---

## 🔧 Complete Module Template

```javascript
// www/js/modules/template.js

class TemplateModule {
    constructor(dependencies) {
        this.deps = dependencies;
        this.state = {};
    }

    init() {
        // DOM ready check
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.bindEvents());
        } else {
            this.bindEvents();
        }
    }

    bindEvents() {
        const element = document.getElementById('my-element');
        if (!element) {
            console.error('[TemplateModule] Element not found');
            return;
        }
        element.addEventListener('click', () => this.handleClick());
    }

    handleClick() {
        console.log('[TemplateModule] Clicked');
    }

    async doSomething() {
        try {
            const result = await this.deps.apiClient.get('/endpoint');
            return result;
        } catch (error) {
            console.error('[TemplateModule] Error:', error);
            throw error;
        }
    }
}

// Dual export
export default TemplateModule;
window.TemplateModule = TemplateModule;
```

---

## 📚 Related Documentation

- [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md) - Module system
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Critical requirements

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.1+
