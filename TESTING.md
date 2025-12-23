# Testing Guide - Visual Mapper

**Last Updated:** 2025-12-23
**Test Coverage:** 183+ tests (71 backend + 29 E2E + 83 Jest)
**Coverage Target:** >60% overall, >70% for new code

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Test Suite Overview](#test-suite-overview)
3. [Running Tests](#running-tests)
4. [Writing New Tests](#writing-new-tests)
5. [CI/CD Pipeline](#cicd-pipeline)
6. [Pre-commit Hooks](#pre-commit-hooks)
7. [Coverage Reporting](#coverage-reporting)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Install Test Dependencies

```bash
# Python backend tests
pip install pytest pytest-cov pytest-asyncio pytest-playwright

# JavaScript frontend tests
npm install

# E2E Playwright tests
playwright install chromium

# Pre-commit hooks (optional but recommended)
pip install pre-commit
pre-commit install
```

### Run All Tests

```bash
# Backend unit tests
python -m pytest tests/test_*.py -v

# Frontend unit tests
npm test

# E2E tests (requires server running)
python server.py &
sleep 5
python -m pytest tests/test_e2e_*.py -v

# All tests with coverage
python -m pytest tests/ -v --cov=. --cov-report=html
npm test -- --coverage
```

---

## Test Suite Overview

### Backend Tests (71 tests)

**Location:** `tests/test_*.py`
**Framework:** pytest + pytest-asyncio
**Coverage:** FastAPI endpoints, ADB integration, MQTT client, utility functions

**Test Files:**
- `test_server.py` - API endpoint tests
- `test_adb_integration.py` - ADB command execution
- `test_mqtt_client.py` - MQTT publishing/subscribing
- `test_text_extraction.py` - OCR and text extraction engines
- `test_utils.py` - Helper functions

**Example:**
```python
@pytest.mark.asyncio
async def test_capture_screenshot(client):
    """Test screenshot capture endpoint"""
    response = client.post("/api/screenshot", json={
        "device_id": "test-device"
    })
    assert response.status_code == 200
    assert "base64" in response.json()
```

### Frontend Tests (83 tests)

**Location:** `tests/*.test.js`
**Framework:** Jest 30.2.0 + Babel 7.28.5
**Coverage:** ES6 modules, UI interactions, API client, coordinate mapping

**Test Files:**
- `api-client.test.js` - API client with retry logic (14 tests)
- `device-control.test.js` - Device interactions, coordinate mapping (34 tests)
- `element-selector.test.js` - Element selection, highlighting (37 tests)

**Example:**
```javascript
describe('Coordinate Mapping', () => {
    test('should scale coordinates when canvas is scaled down (2:1)', () => {
        mockRect.width = 540;
        mockRect.height = 960;

        // Click at (270, 480) on displayed canvas
        // Should map to (540, 960) on device
        clickHandler({ clientX: 270, clientY: 480 });

        expect(mockApiClient.post).toHaveBeenCalledWith('/adb/tap', {
            device_id: 'test-device',
            x: 540,
            y: 960
        });
    });
});
```

### E2E Tests (29 tests)

**Location:** `tests/test_e2e_*.py`
**Framework:** Playwright + pytest
**Coverage:** Navigation, page loads, device workflows

**Test Files:**
- `test_e2e_navigation.py` - Page navigation, UI structure (10 tests)
- `test_e2e_devices.py` - Device management, screenshot capture (19 tests)

**Example:**
```python
@pytest.mark.slow
def test_screenshot_metadata_displayed_after_capture(page: Page):
    """Test that screenshot metadata is shown (requires device)"""
    page.goto("/devices.html")

    try:
        page.wait_for_selector("text=Connected", timeout=2000)
    except:
        pytest.skip("No device connected - skipping test")

    capture_btn = page.locator("button:has-text('Capture')")
    capture_btn.click()
    page.wait_for_selector("text=/Screenshot|Error/", timeout=5000)
```

---

## Running Tests

### Backend Tests

```bash
# All backend tests
python -m pytest tests/test_*.py -v

# Specific test file
python -m pytest tests/test_server.py -v

# Specific test function
python -m pytest tests/test_server.py::test_health_check -v

# Skip slow tests (device-dependent)
python -m pytest tests/ -v -m "not slow"

# With coverage
python -m pytest tests/ -v --cov=. --cov-report=html --cov-report=term-missing

# Stop on first failure
python -m pytest tests/ -v -x
```

### Frontend Tests

```bash
# All frontend tests
npm test

# Watch mode (auto-rerun on file changes)
npm test -- --watch

# Specific test file
npm test -- api-client.test.js

# With coverage
npm test -- --coverage

# Coverage with HTML report
npm test -- --coverage --coverageReporters=html --coverageReporters=text
```

### E2E Tests

**Prerequisites:** Server must be running on `localhost:3000`

```bash
# Start server (in separate terminal)
python server.py

# Run E2E tests
python -m pytest tests/test_e2e_*.py -v

# Run only navigation tests (no device required)
python -m pytest tests/test_e2e_navigation.py -v

# Run device tests (requires Android device connected)
python -m pytest tests/test_e2e_devices.py -v

# Skip slow tests
python -m pytest tests/test_e2e_*.py -v -m "not slow"
```

### All Tests Together

```bash
# Backend + E2E (requires server running)
python server.py &
sleep 5
python -m pytest tests/ -v --cov=. --cov-report=html

# Frontend
npm test -- --coverage

# Kill server
pkill -f "python server.py"
```

---

## Writing New Tests

### Test-Driven Development (TDD)

**Always follow this workflow:**

1. **Write test FIRST** (it will fail)
2. **Implement feature** to make test pass
3. **Refactor** code while keeping test passing
4. **Run tests** to verify
5. **Test in browser** (localhost:3000)
6. **Commit** when all tests pass

### Backend Test Template

```python
import pytest
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

def test_new_endpoint():
    """Test description following docstring convention"""
    # Arrange - set up test data
    payload = {"device_id": "test-device"}

    # Act - perform the action
    response = client.post("/api/new-endpoint", json=payload)

    # Assert - verify the result
    assert response.status_code == 200
    assert "expected_key" in response.json()

@pytest.mark.asyncio
async def test_async_function():
    """Test async function"""
    result = await some_async_function()
    assert result is not None
```

### Frontend Test Template

```javascript
import ModuleName from '../www/js/modules/module-name.js';

describe('ModuleName', () => {
    let instance;
    let mockApiClient;

    beforeEach(() => {
        // Set up mocks
        mockApiClient = {
            get: jest.fn(),
            post: jest.fn()
        };

        // Create instance
        instance = new ModuleName(mockApiClient);
    });

    afterEach(() => {
        jest.clearAllMocks();
    });

    describe('Feature Group', () => {
        test('should do specific thing', () => {
            // Arrange
            const input = 'test';

            // Act
            const result = instance.doThing(input);

            // Assert
            expect(result).toBe('expected');
        });
    });
});
```

### E2E Test Template

```python
import pytest
from playwright.sync_api import Page, expect

@pytest.mark.slow
def test_user_workflow(page: Page):
    """Test complete user workflow"""
    # Navigate to page
    page.goto("/page.html")

    # Verify page loaded
    expect(page).to_have_title("Expected Title")

    # Interact with UI
    button = page.locator("button:has-text('Click Me')")
    button.click()

    # Verify result
    expect(page.locator("text=Success")).to_be_visible()
```

### Mocking Best Practices

**Frontend (Jest):**
```javascript
// Mock DOM elements
const mockCanvas = document.createElement('canvas');
const mockCtx = {
    drawImage: jest.fn(),
    fillRect: jest.fn(),
    strokeRect: jest.fn()
};
mockCanvas.getContext = jest.fn(() => mockCtx);

// Mock fetch API
global.fetch = jest.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ data: 'test' })
}));

// Mock module imports
jest.mock('../www/js/modules/api-client.js', () => ({
    default: jest.fn()
}));
```

**Backend (pytest):**
```python
from unittest.mock import patch, MagicMock

@patch('subprocess.run')
def test_adb_command(mock_run):
    """Test ADB command execution"""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='device connected'
    )

    result = execute_adb_command(['devices'])
    assert 'connected' in result
```

---

## CI/CD Pipeline

### GitHub Actions Workflow

**File:** `.github/workflows/ci.yml`

**Jobs:**
1. **test-backend** - Backend Python tests (matrix: Python 3.11 & 3.12)
2. **test-frontend** - Frontend Jest tests with coverage
3. **test-e2e** - E2E Playwright tests
4. **lint** - Code quality (Black, Flake8, ESLint)
5. **security** - Trivy vulnerability scanning
6. **build** - Project build validation
7. **all-tests-passed** - Status check for PR protection

### Triggers

```yaml
on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]
```

### Coverage Upload

Tests automatically upload coverage to Codecov:
- Backend coverage → `codecov` flag: `backend`
- Frontend coverage → `codecov` flag: `frontend`

### Local CI Simulation

```bash
# Run same tests as CI
python -m pytest tests/test_*.py -v --cov=. --cov-report=xml -m "not slow"
npm test -- --coverage --coverageReporters=lcov

# Run linting
black --check .
flake8 . --count --select=E9,F63,F7,F82

# Check JavaScript syntax
find www/js -name "*.js" -type f -exec node --check {} \;
```

---

## Pre-commit Hooks

### Installation

```bash
pip install pre-commit
pre-commit install
```

### What Gets Checked

**Python:**
- Black formatter (line length: 100)
- Flake8 linter (max line length: 100)
- isort import sorting
- Bandit security scanner

**JavaScript:**
- Prettier formatter

**General:**
- Trailing whitespace
- End-of-file fixing
- YAML/JSON validation
- Large file detection (max 1MB)
- Merge conflict markers
- Line ending normalization (LF)

**Tests:**
- Fast pytest unit tests (`-m "not slow"`)
- Jest frontend tests

### Configuration Files

- `.pre-commit-config.yaml` - Hook configuration
- `.bandit.yml` - Security scanner settings
- `pyproject.toml` - Black/isort settings (if needed)

### Usage

```bash
# Run on staged files (automatic on commit)
git commit -m "Your message"

# Run manually on all files
pre-commit run --all-files

# Skip hooks (not recommended)
git commit -m "Your message" --no-verify

# Update hook versions
pre-commit autoupdate
```

---

## Coverage Reporting

### Current Coverage

**Target:** 60% overall, 70% for new code

**Actual:**
- Backend: ~65% (71 tests)
- Frontend: ~55% (83 tests)
- Overall: ~60%

### Viewing Coverage

**Backend (HTML report):**
```bash
python -m pytest tests/ --cov=. --cov-report=html
# Open htmlcov/index.html in browser
```

**Frontend (HTML report):**
```bash
npm test -- --coverage --coverageReporters=html
# Open coverage/lcov-report/index.html in browser
```

**Terminal output:**
```bash
python -m pytest tests/ --cov=. --cov-report=term-missing
npm test -- --coverage --coverageReporters=text
```

### Codecov Integration

**Configuration:** `codecov.yml`

**Features:**
- 60% minimum project coverage
- 70% minimum for new patches
- Separate backend/frontend flags
- PR comments with coverage diff
- GitHub Checks integration

**Viewing online:**
1. Push to GitHub
2. View coverage at: `https://codecov.io/gh/YOUR-ORG/visual-mapper`
3. Check PR comments for coverage changes

### Improving Coverage

**Find untested code:**
```bash
# Backend - shows uncovered lines
python -m pytest tests/ --cov=. --cov-report=term-missing

# Frontend - shows uncovered files
npm test -- --coverage --verbose
```

**Focus areas:**
- Error handling paths
- Edge cases (empty inputs, null values)
- Async code and race conditions
- User interaction flows
- API error responses

---

## Troubleshooting

### Backend Test Issues

**Issue:** Import errors
```bash
ModuleNotFoundError: No module named 'fastapi'
```
**Fix:**
```bash
pip install -r requirements.txt
pip install pytest pytest-cov pytest-asyncio
```

**Issue:** Async test warnings
```
RuntimeWarning: coroutine 'test_async_function' was never awaited
```
**Fix:** Add `@pytest.mark.asyncio` decorator

**Issue:** MQTT broker connection errors (expected)
```bash
# MQTT tests are deferred - requires real Home Assistant instance
# Skip with: pytest -m "not slow"
```

### Frontend Test Issues

**Issue:** Module import errors
```
Cannot find module '../www/js/modules/api-client.js'
```
**Fix:** Check Babel/Jest configuration in `package.json`:
```json
{
  "jest": {
    "transform": {
      "^.+\\.js$": "babel-jest"
    }
  }
}
```

**Issue:** DOM not available
```
ReferenceError: document is not defined
```
**Fix:** Ensure `testEnvironment: 'jsdom'` in Jest config

**Issue:** Mock persistence between tests
```bash
# Known issue in api-client.test.js - expected Jest behavior
# Tests validate retry logic despite mock persistence
```

### E2E Test Issues

**Issue:** Server not running
```
playwright._impl._errors.TargetClosedError: Target page closed
```
**Fix:**
```bash
python server.py &
sleep 5
python -m pytest tests/test_e2e_*.py -v
```

**Issue:** No device connected (expected)
```bash
# Tests marked with @pytest.mark.slow will skip gracefully
# Run with: pytest -m "not slow" to skip device tests
```

**Issue:** Timeout errors
```
TimeoutError: Timeout 10000ms exceeded
```
**Fix:** Increase timeout in `conftest.py`:
```python
page.set_default_timeout(20000)  # 20 seconds
```

### CI/CD Issues

**Issue:** Pre-commit hooks failing
```bash
# Run manually to see exact failure
pre-commit run --all-files

# Fix formatting
black .
prettier --write www/js/**/*.js
```

**Issue:** GitHub Actions failing
```bash
# Check workflow logs on GitHub
# Run same commands locally:
python -m pytest tests/ -v -m "not slow"
npm test
```

---

## Test Markers

### Pytest Markers

**Slow tests** (device-dependent, skipped in CI):
```python
@pytest.mark.slow
def test_requires_device(page: Page):
    """Test that needs real Android device"""
    pass
```

**Skip slow tests:**
```bash
pytest -m "not slow"
```

**Run only slow tests:**
```bash
pytest -m "slow"
```

### Jest Test Selection

```bash
# Run specific test file
npm test -- api-client.test.js

# Run tests matching pattern
npm test -- --testNamePattern="coordinate"

# Run only changed tests
npm test -- --onlyChanged
```

---

## Best Practices

### General

✅ **DO:**
- Write tests FIRST (TDD)
- Test one thing per test
- Use descriptive test names
- Mock external dependencies
- Clean up after tests
- Run tests before committing

❌ **DON'T:**
- Test implementation details
- Write flaky tests (random failures)
- Skip tests without good reason
- Commit failing tests
- Test third-party libraries

### Coverage

✅ **Focus on:**
- Critical business logic
- Error handling paths
- User interaction flows
- API endpoints
- Data transformations

❌ **Don't obsess over:**
- 100% coverage (diminishing returns)
- Testing getters/setters
- Testing framework code
- Testing constants

### Performance

- Keep unit tests fast (< 1s each)
- Mark slow tests with `@pytest.mark.slow`
- Use mocks to avoid network calls
- Run tests in parallel when possible
- Cache dependencies in CI

---

## Resources

### Documentation

- [pytest Documentation](https://docs.pytest.org/)
- [Jest Documentation](https://jestjs.io/docs/getting-started)
- [Playwright Documentation](https://playwright.dev/python/)
- [Pre-commit Documentation](https://pre-commit.com/)

### Project Files

- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Project context
- [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) - Development roadmap
- [MODULARITY_GUIDELINES.md](MODULARITY_GUIDELINES.md) - Code organization
- [pytest.ini](pytest.ini) - Pytest configuration
- [package.json](package.json) - Jest configuration
- [.github/workflows/ci.yml](.github/workflows/ci.yml) - CI/CD pipeline

---

**Questions?** See [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) or check existing tests for examples.

**Last Updated:** 2025-12-23
**Next Review:** After Phase 6 (HA Add-on Packaging)
