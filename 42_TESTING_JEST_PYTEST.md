# Testing with Jest & pytest

**Purpose:** Unit testing for JavaScript and Python.

**Starting Version:** 0.0.6 (Phase 5)
**Last Updated:** 2025-12-21

---

## 🎯 Testing Strategy

**Test Pyramid:**
```
      E2E (Playwright)     - 10-20 tests
     Integration           - 30-50 tests
    Unit (Jest/pytest)     - 100+ tests
```

---

## 🟨 Jest (JavaScript Unit Tests)

### **Setup**

```bash
npm install --save-dev jest @jest/globals
```

### **jest.config.js**

```javascript
export default {
  testEnvironment: 'jsdom',
  testMatch: ['**/tests/unit/js/**/*.test.js'],
  collectCoverage: true,
  coverageDirectory: 'coverage',
  coverageThreshold: {
    global: {
      branches: 60,
      functions: 60,
      lines: 60,
      statements: 60
    }
  }
};
```

### **Example Test**

```javascript
// tests/unit/js/coordinate-mapper.test.js

import { describe, it, expect, beforeEach } from '@jest/globals';
import CoordinateMapper from '../../../www/js/modules/coordinate-mapper.js';

describe('CoordinateMapper', () => {
  let mapper;

  beforeEach(() => {
    mapper = new CoordinateMapper();
  });

  it('should calculate scale correctly', () => {
    mapper.setScale(800, 600, 1080, 1920);
    expect(mapper.scale).toBeCloseTo(0.312, 2);
  });

  it('should convert display to device coords', () => {
    mapper.setScale(800, 600, 1080, 1920);
    const result = mapper.displayToDevice(400, 300);
    expect(result.x).toBeGreaterThan(0);
    expect(result.y).toBeGreaterThan(0);
  });
});
```

---

## 🐍 pytest (Python Unit Tests)

### **Setup**

```bash
pip install pytest pytest-asyncio pytest-cov
```

### **pytest.ini**

```ini
[pytest]
testpaths = tests/unit/python tests/integration
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
```

### **Example Test**

```python
# tests/unit/python/test_adb_bridge.py

import pytest
from adb_bridge import ADBBridge

@pytest.fixture
def adb_bridge():
    return ADBBridge()

def test_parse_bounds(adb_bridge):
    result = adb_bridge._parse_bounds('[100,200][300,400]')
    assert result == {'x': 100, 'y': 200, 'width': 200, 'height': 200}

def test_parse_bounds_invalid(adb_bridge):
    result = adb_bridge._parse_bounds('invalid')
    assert result is None

@pytest.mark.asyncio
async def test_connect_device(adb_bridge, mocker):
    mock_device = mocker.Mock()
    mocker.patch('adb_bridge.AdbDeviceTcp', return_value=mock_device)

    device_id = await adb_bridge.connect_device('192.168.1.100', 5555)
    assert device_id == '192.168.1.100:5555'
    assert device_id in adb_bridge.devices
```

---

## 🧪 Running Tests

### **Jest**

```bash
# Run all tests
npm test

# Run specific test
npm test coordinate-mapper.test.js

# Watch mode
npm test -- --watch

# Coverage report
npm test -- --coverage
```

### **pytest**

```bash
# Run all tests
pytest

# Run specific test
pytest tests/unit/python/test_adb_bridge.py

# With coverage
pytest --cov=. --cov-report=html

# Verbose output
pytest -v
```

---

## 📊 Coverage Requirements

**Target:** >60% overall coverage

**Critical paths must have >80%:**
- API base detection
- Coordinate mapping
- Screenshot capture
- Device connection

---

## 📚 Related Documentation

- [41_TESTING_PLAYWRIGHT.md](41_TESTING_PLAYWRIGHT.md) - E2E testing
- [40_LOCAL_DEV_ENVIRONMENT.md](40_LOCAL_DEV_ENVIRONMENT.md) - Dev setup

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.6+
