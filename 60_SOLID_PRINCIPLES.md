# SOLID Principles for Visual Mapper

**Purpose:** Apply SOLID principles to Visual Mapper architecture.

**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## 🎯 What is SOLID?

**Five principles for maintainable object-oriented code:**

1. **S**ingle Responsibility Principle
2. **O**pen/Closed Principle
3. **L**iskov Substitution Principle
4. **I**nterface Segregation Principle
5. **D**ependency Inversion Principle

---

## 1️⃣ Single Responsibility Principle (SRP)

**"A class should have one, and only one, reason to change."**

### ❌ **Bad Example:**

```javascript
class ScreenshotModule {
    captureScreenshot() { }
    renderOnCanvas() { }
    saveToFile() { }
    sendToAPI() { }
    // Too many responsibilities!
}
```

### ✅ **Good Example:**

```javascript
class ScreenshotCapture {
    async capture(deviceId) { /* Only captures */ }
}

class ScreenshotRenderer {
    render(canvas, image) { /* Only renders */ }
}

class ScreenshotStorage {
    save(filename, data) { /* Only saves */ }
}
```

**Applied in Visual Mapper:**
- `ApiClient` - Only handles API calls
- `EventBus` - Only handles events
- `CoordinateMapper` - Only handles coordinate conversion

---

## 2️⃣ Open/Closed Principle (OCP)

**"Software entities should be open for extension, but closed for modification."**

### ✅ **Example: Plugin Architecture**

```javascript
class SensorProcessor {
    constructor() {
        this.processors = [];
    }

    registerProcessor(processor) {
        this.processors.push(processor);
    }

    process(element) {
        for (const processor of this.processors) {
            if (processor.canProcess(element)) {
                return processor.process(element);
            }
        }
    }
}

// Extend without modifying original class
class TextSensorProcessor {
    canProcess(element) {
        return element.type === 'text';
    }

    process(element) {
        return element.text;
    }
}

// Register plugin
sensorProcessor.registerProcessor(new TextSensorProcessor());
```

**Target for Phase 7:** Plugin system for custom sensors and actions.

---

## 3️⃣ Liskov Substitution Principle (LSP)

**"Derived classes must be substitutable for their base classes."**

### ✅ **Example:**

```javascript
class Device {
    async connect() { throw new Error('Not implemented'); }
    async disconnect() { throw new Error('Not implemented'); }
}

class AndroidDevice extends Device {
    async connect() {
        // Implements base contract
        return await this.adbConnect();
    }

    async disconnect() {
        // Implements base contract
        return await this.adbDisconnect();
    }
}

// Can substitute Device with AndroidDevice
function manageDevice(device) {
    await device.connect();  // Works for any Device subclass
}
```

---

## 4️⃣ Interface Segregation Principle (ISP)

**"Many client-specific interfaces are better than one general-purpose interface."**

### ❌ **Bad Example:**

```javascript
class DeviceManager {
    screenshot() { }
    tap() { }
    swipe() { }
    getSensors() { }
    getActions() { }
    // Too many methods!
}
```

### ✅ **Good Example:**

```javascript
class ScreenshotCapture {
    screenshot() { }
}

class DeviceControl {
    tap() { }
    swipe() { }
}

class SensorManager {
    getSensors() { }
}

// Clients only use what they need
```

---

## 5️⃣ Dependency Inversion Principle (DIP)

**"Depend on abstractions, not concretions."**

### ❌ **Bad Example:**

```javascript
class ScreenshotModule {
    constructor() {
        this.api = new ApiClient();  // Tight coupling!
    }
}
```

### ✅ **Good Example:**

```javascript
class ScreenshotModule {
    constructor(apiClient) {
        this.api = apiClient;  // Injected dependency
    }
}

// Usage
const apiClient = new ApiClient();
const screenshot = new ScreenshotModule(apiClient);
```

**Applied in Visual Mapper:**
All modules accept dependencies via constructor (see [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md)).

---

## 🎯 Applying SOLID to Visual Mapper

### **Current Architecture (Phase 0-2)**
- Modules follow SRP
- Dependency injection used
- EventBus for loose coupling

### **Target Architecture (Phase 7)**
- Plugin system (OCP)
- Abstract base classes (LSP)
- Segregated interfaces (ISP)
- Full dependency inversion (DIP)

---

## 📚 Related Documentation

- [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md) - System design
- [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md) - Module system
- [61_CONTRIBUTING.md](61_CONTRIBUTING.md) - Contribution guidelines

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.1+
