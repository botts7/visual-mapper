# Testing with Playwright

**Purpose:** End-to-end testing with Playwright.

**Starting Version:** 0.0.6 (Phase 5)
**Last Updated:** 2025-12-21

---

## 🎯 What is Playwright?

**Browser automation for E2E testing:**
- Tests full user workflows
- Works with Chrome, Firefox, Safari
- Headless or visible mode
- Screenshots/videos on failure

---

## 🔧 Setup

### **Installation**

```bash
npm install --save-dev @playwright/test
npx playwright install
```

### **playwright.config.js**

```javascript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  retries: 2,
  use: {
    baseURL: 'http://localhost:3000',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});
```

---

## 📝 Example Tests

### **Navigation Test**

```javascript
// tests/e2e/navigation.spec.js

import { test, expect } from '@playwright/test';

test('should navigate between pages', async ({ page }) => {
  await page.goto('/');

  // Click Devices link
  await page.click('a[href="devices.html"]');
  await expect(page).toHaveURL(/devices\.html/);

  // Verify page loaded
  await expect(page.locator('h1')).toContainText('Devices');
});
```

### **Screenshot Capture Test**

```javascript
// tests/e2e/screenshot-capture.spec.js

import { test, expect } from '@playwright/test';

test('should capture screenshot', async ({ page }) => {
  await page.goto('/main.html');

  // Wait for device list to load
  await page.waitForSelector('#device-selector');

  // Select device
  await page.selectOption('#device-selector', '192.168.1.100:5555');

  // Click capture button
  await page.click('#capture-btn');

  // Wait for screenshot to appear
  await page.waitForSelector('#screenshot-canvas');

  // Verify canvas has content
  const canvas = await page.locator('#screenshot-canvas');
  await expect(canvas).toBeVisible();
});
```

---

## 🧪 Running Tests

```bash
# Run all tests
npx playwright test

# Run specific test
npx playwright test navigation.spec.js

# Run with browser visible
npx playwright test --headed

# Debug mode
npx playwright test --debug

# Generate report
npx playwright show-report
```

---

## 📚 Related Documentation

- [42_TESTING_JEST_PYTEST.md](42_TESTING_JEST_PYTEST.md) - Unit testing
- [40_LOCAL_DEV_ENVIRONMENT.md](40_LOCAL_DEV_ENVIRONMENT.md) - Dev setup

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.6+
