# Quick Start Guide - Building from Scratch

**Purpose:** Development workflow for building Visual Mapper from v0.0.1.

**Starting Version:** 0.0.1
**Target Version:** 1.0.0
**Last Updated:** 2025-12-21

---

## ⚠️ Important Context

**We are building Visual Mapper from scratch starting at v0.0.1**, not continuing from v4.6.0-beta.10.

- The legacy system (beta.X) had fundamental issues
- We're using best practices from the start
- All code examples should be tested before using
- Following Test-Driven Development (TDD)

---

## 🎯 Prerequisites

Before starting, ensure you've read:
1. ✅ [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Complete project context (why from scratch)
2. ✅ [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) - Build plan and current phase
3. ✅ [00_START_HERE.md](00_START_HERE.md) - Documentation navigation
4. ✅ [01_CLAUDE_PERMISSIONS_SETUP.md](01_CLAUDE_PERMISSIONS_SETUP.md) - Permissions configured (by user)

---

## 🚀 Getting Started

### **Step 1: Verify Project Location**

```bash
# Windows
cd "C:\Users\botts\Downloads\Visual Mapper"

# Verify files exist
dir

# Expected structure (building this from scratch):
# www/          - Frontend files (will build)
# server.py     - Backend API (will build)
# config.yaml   - HA addon config (will build)
# Dockerfile    - Container build (will build)
# .build-version - Version source of truth (will create)
# docs/         - Documentation (exists)
```

### **Step 2: Check Current Phase**

```bash
# Read the build plan to see what phase we're in
cat NEW_PROJECT_PLAN.md
```

**Current Phase:** Phase 0: Foundation (v0.0.1)

**First Tasks:**
- Setup project structure
- Create Dockerfile
- Implement version sync
- Write first test

### **Step 3: Understand the Plan**

**Read NEW_PROJECT_PLAN.md to understand:**
- What we're building in each phase
- Current task checklists
- Success criteria for each phase
- Issues to avoid from legacy system

### **Step 4: Review Legacy Issues to Avoid**

Check [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) "Lessons from Legacy System" section:

**Legacy Issues We're Avoiding:**
1. No automated tests → Writing tests FIRST (TDD)
2. Inconsistent cache busting → Cache busting on ALL file references
3. Version management crisis → Single source of truth (.build-version)
4. Navigation regression → Systematic testing
5. Live streaming never worked → Proper research and planning (see 30-31 docs)
6. Module loading failures → Proper `type="module"` attributes
7. dev.html bugs → Null safety, DOM ready checks

**What Worked in Legacy (can reference):**
1. Dual export pattern (ES6 + global)
2. API base detection for HA ingress
3. Coordinate mapping
4. FastAPI backend
5. adb-shell library

⚠️ **Test any legacy code before using!**

---

## 📋 Development Workflow (TDD Approach)

Visual Mapper uses **Test-Driven Development** - write tests FIRST, then implement:

```
┌─────────────────────────────────────────┐
│  1. Check NEW_PROJECT_PLAN.md            │
│     (Understand current phase/task)     │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  2. Read Relevant Documentation          │
│     (Architecture, patterns, etc.)      │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  3. Write Failing Test FIRST             │
│     (Define expected behavior)          │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  4. Implement Feature                    │
│     (Reference legacy patterns 20-25)   │
│     ⚠️ Test legacy code before using!   │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  5. Run Tests Automatically              │
│     (Claude validates - no user needed) │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  6. Test on localhost:3000               │
│     (Claude validates - no user needed) │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  7. Report to User: "Ready for HA"       │
│     (Ask user to validate)              │
└──────────────┬──────────────────────────┘
               ↓
         User provides feedback:
         ✅ Works → Proceed to commit
         🟡 Issues → Iterate
         🔴 Broken → Provide console errors
               ↓
┌─────────────────────────────────────────┐
│  8. Bump Version (if user-facing)        │
│     (Edit .build-version line 1)        │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  9. Git Commit (requires user approval)  │
│     (Pre-commit hook syncs versions)    │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  10. Update NEW_PROJECT_PLAN.md          │
│      (Mark task complete, update %)     │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  11. Git Push (requires user approval)   │
│      (Optional - user decides when)     │
└─────────────────────────────────────────┘
```

---

## 🛠️ Common Commands Cheat Sheet

### **File Operations (Auto-Approved)**

```bash
# List files
ls
ls www/
ls www/js/modules/

# Read files
cat .build-version
cat www/main.html
cat www/js/init-v4.js

# Current directory
pwd
```

### **Git Operations (Read-Only = Auto-Approved)**

```bash
# Check status
git status

# View changes
git diff
git diff www/diagnostic.html

# View commit history
git log --oneline -10

# View specific commit
git show HEAD

# List branches
git branch

# Switch branches (read-only)
git checkout develop
git checkout feature/my-branch
```

### **Git Operations (Write = Requires User Approval)**

```bash
# Create commit (REQUIRES APPROVAL)
git add .
git commit -m "fix: diagnostic.html API base detection

- Added getApiBase() function for HA ingress
- Fixes JSON parse error on /api/apps/discover

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"

# Push to remote (REQUIRES APPROVAL)
git push origin develop
git push origin master
```

### **Testing (Auto-Approved Once Configured)**

```bash
# Run all tests
npm test

# Run unit tests only
npm run test:unit

# Run E2E tests only
npm run test:e2e

# Python tests
pytest

# Playwright tests
playwright test
playwright test --headed  # With browser visible
```

### **Docker Operations (Read-Only = Auto-Approved)**

```bash
# List containers
docker ps
docker ps -a

# View logs
docker logs visual-mapper-v4

# Execute command in container
docker exec visual-mapper-v4 ls /app
```

### **Local API Testing (Auto-Approved)**

```bash
# Test frontend
curl http://localhost:3000

# Test API endpoints
curl http://localhost:8099/api/adb/devices
curl http://localhost:8099/api/adb/screenshot

# Test WebSocket (using websocat or similar)
# websocat ws://localhost:8099/ws/stream
```

---

## 📝 Example: Fixing a Bug

### **Scenario:** Fix a bug (example from legacy system)

⚠️ **Note:** dev.html doesn't exist yet in v0.0.1. This is a reference example from legacy code.

#### **Step 1: Gather Information**

```bash
# Read the file
cat www/dev.html | grep -A 10 "device-selector"

# Check related module
cat www/js/modules/device-selector.js

# Check if module is loaded
cat www/js/init-v4.js | grep DeviceSelector
```

#### **Step 2: Identify the Issue**

**User reported:** "Select device dropdown not responding"

**Need:** Browser console errors from user

**Ask user:**
> "Can you open dev.html in your Home Assistant, open browser DevTools (F12), and share any console errors you see when clicking the device selector?"

#### **Step 3: Write Failing Test**

```javascript
// tests/e2e/dev-page.spec.js
const { test, expect } = require('@playwright/test');

test('device selector dropdown should open on click', async ({ page }) => {
  await page.goto('http://localhost:3000/dev.html');

  // Wait for page to load
  await page.waitForSelector('#device-selector');

  // Click dropdown
  await page.click('#device-selector');

  // Dropdown should be visible
  await expect(page.locator('#device-selector-options')).toBeVisible();

  // Should show at least one device
  const deviceCount = await page.locator('.device-option').count();
  expect(deviceCount).toBeGreaterThan(0);
});
```

Run test (should fail):
```bash
playwright test tests/e2e/dev-page.spec.js
```

#### **Step 4: Analyze Root Cause**

Based on user's console errors, suppose we find:
```
TypeError: Cannot read property 'addEventListener' of null
  at DeviceSelector.init (device-selector.js:25)
```

**Issue:** Element doesn't exist when script runs

#### **Step 5: Implement Fix**

Read the working pattern:
```bash
cat 21_CODE_PATTERN_MODULES.md
```

Apply the fix using documented pattern:
```javascript
// www/js/modules/device-selector.js
class DeviceSelector {
    init() {
        // WAIT for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.bindEvents());
        } else {
            this.bindEvents();
        }
    }

    bindEvents() {
        const selector = document.getElementById('device-selector');
        if (!selector) {
            console.error('[DeviceSelector] Element #device-selector not found');
            return;
        }
        selector.addEventListener('click', () => this.toggleDropdown());
    }
}
```

#### **Step 6: Run Tests**

```bash
# Run specific test
playwright test tests/e2e/dev-page.spec.js

# Expected: ✅ Test passes
```

#### **Step 7: Test Locally**

```bash
# Start dev server (if not running)
# npm run dev

# Test manually
curl http://localhost:3000/dev.html | grep "device-selector"

# Or open in browser
# http://localhost:3000/dev.html
```

#### **Step 8: Ask User to Validate**

> "Fixed device selector issue in dev.html. The dropdown now waits for DOM ready before binding events. Can you test in your Home Assistant and confirm the selector works?"

**User tests and responds:**
- ✅ "Works perfectly!" → Proceed to commit
- 🟡 "Works but slow" → Optimize
- 🔴 "Still broken" → Get new console errors, iterate

#### **Step 9: Bump Version**

```bash
# Edit .build-version
echo "4.6.0-beta.11" > .build-version
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> .build-version
echo "REBUILD_ID: 4.6.0-beta.11-BUILD-$(date +%s)" >> .build-version
```

#### **Step 10: Commit**

```bash
git add .
git commit -m "fix(dev.html): Device selector not responding

- Added DOM ready check before binding events
- Added null check for element
- Added error logging for debugging

Fixes #1 - dev.html device selector not working

Tested:
- ✅ Playwright E2E test passes
- ✅ Manual test on localhost:3000
- ✅ User validated in HA ingress

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"
```

**Git hook will automatically:**
- Sync version to config.yaml
- Sync version to Dockerfile
- Sync version to www/main.html
- Sync version to www/js/init-v4.js

#### **Step 11: Push**

```bash
# Push to develop first
git push origin develop

# If tests pass, merge to master
git checkout master
git merge develop
git push origin master
```

#### **Step 12: User Updates HA**

User follows [HA_UPDATE_INSTRUCTIONS.md](HA_UPDATE_INSTRUCTIONS.md) to update addon to beta.11

---

## 📝 Example: Adding a New Feature

### **Scenario:** Add export button to sensor list

#### **Step 1: Read Documentation**

```bash
# Understand architecture
cat 10_SYSTEM_ARCHITECTURE.md | grep -A 20 "sensors.html"

# Review SOLID principles
cat 60_SOLID_PRINCIPLES.md | grep -A 10 "Single Responsibility"

# Check working patterns
cat 21_CODE_PATTERN_MODULES.md
```

#### **Step 2: Write Test First (TDD)**

```javascript
// tests/e2e/sensor-export.spec.js
const { test, expect } = require('@playwright/test');

test('should export sensors to JSON', async ({ page }) => {
  await page.goto('http://localhost:3000/sensors.html');

  // Wait for sensors to load
  await page.waitForSelector('.sensor-list');

  // Click export button
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.click('#export-sensors-btn')
  ]);

  // Verify download
  expect(download.suggestedFilename()).toBe('sensors_export.json');

  // Verify JSON structure
  const path = await download.path();
  const content = require('fs').readFileSync(path, 'utf8');
  const sensors = JSON.parse(content);

  expect(Array.isArray(sensors)).toBe(true);
  expect(sensors.length).toBeGreaterThan(0);
  expect(sensors[0]).toHaveProperty('name');
  expect(sensors[0]).toHaveProperty('type');
});
```

Run test (should fail - feature doesn't exist yet):
```bash
playwright test tests/e2e/sensor-export.spec.js
# Expected: ❌ Fails (button doesn't exist)
```

#### **Step 3: Implement Feature**

**Add UI button:**
```html
<!-- www/sensors.html -->
<button id="export-sensors-btn" class="btn-export">
    Export Sensors
</button>
```

**Add module function:**
```javascript
// www/js/modules/sensor-manager.js
class SensorManager {
    async exportSensors() {
        try {
            const sensors = await this.apiClient.get('/sensors');

            const dataStr = JSON.stringify(sensors, null, 2);
            const blob = new Blob([dataStr], { type: 'application/json' });
            const url = URL.createObjectURL(blob);

            const a = document.createElement('a');
            a.href = url;
            a.download = 'sensors_export.json';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

            console.log('[SensorManager] Exported sensors successfully');
        } catch (error) {
            console.error('[SensorManager] Export failed:', error);
            alert('Failed to export sensors: ' + error.message);
        }
    }
}

// Export both ways (dual export pattern)
export default SensorManager;
window.SensorManager = SensorManager;
```

**Bind event:**
```javascript
// www/sensors.html or in module init
document.getElementById('export-sensors-btn')?.addEventListener('click', () => {
    window.sensorManager.exportSensors();
});
```

#### **Step 4: Run Tests**

```bash
playwright test tests/e2e/sensor-export.spec.js
# Expected: ✅ Test passes
```

#### **Step 5: Test Locally**

```bash
# Open in browser
# http://localhost:3000/sensors.html
# Click "Export Sensors" button
# Verify JSON file downloads
```

#### **Step 6: Ask User to Validate**

> "Added export feature to sensors.html. Can you test in your HA and confirm the export button downloads a valid JSON file?"

#### **Step 7-12: Same as Bug Fix Example**

- Bump version
- Commit with descriptive message
- Push to develop → master
- User updates HA addon
- User validates in production

---

## 🎯 Development Best Practices

### **Do:**

1. ✅ **Read documentation first**
   - Check 00-25 files for relevant patterns
   - Don't reinvent the wheel

2. ✅ **Write tests before code (TDD)**
   - Failing test defines expected behavior
   - Passing test proves it works

3. ✅ **Use working patterns**
   - Dual export pattern for modules
   - API base detection for HA ingress
   - Coordinate mapping for drawing
   - See files 20-25

4. ✅ **Test automatically**
   - Run tests before asking user
   - Claude can test on localhost:3000 without approval

5. ✅ **Ask user for final validation**
   - User tests in real HA environment
   - User provides console errors if issues

6. ✅ **Bump version for user-facing changes**
   - Edit .build-version
   - Git hook syncs to all files

7. ✅ **Write descriptive commits**
   - Use conventional commit format
   - Explain what, why, and how
   - Include test results

8. ✅ **Update PROGRESS_TRACKER.md**
   - Mark completed tasks
   - Add new issues found
   - Update status

### **Don't:**

1. ❌ **Skip testing**
   - Causes regressions
   - Wastes user's time

2. ❌ **Assume patterns**
   - Always check documentation
   - Working code is in files 20-25

3. ❌ **Make breaking changes**
   - Discuss with user first
   - Consider backward compatibility

4. ❌ **Commit untested code**
   - Tests must pass first
   - User must validate

5. ❌ **Use bash for file operations**
   - Use Read/Write/Edit tools
   - Bash is for commands only

6. ❌ **Create unnecessary files**
   - Edit existing files first
   - Only create when required

7. ❌ **Skip version bumps**
   - HA won't detect updates
   - Users will be confused

8. ❌ **Force push to master**
   - Blocked by permissions
   - Never override user's work

---

## 🔍 Troubleshooting

### **Issue: Tests Failing**

**Solution:**
```bash
# Check test output
npm test

# Run specific test file
playwright test tests/e2e/navigation.spec.js

# Run with browser visible
playwright test --headed

# Check test logs
cat playwright-report/index.html
```

### **Issue: API Not Responding**

**Solution:**
```bash
# Check if server running
curl http://localhost:8099/api/adb/devices

# If not running, user needs to start it
# (Claude cannot start server without approval)

# Check logs
docker logs visual-mapper-v4
```

### **Issue: Version Not Syncing**

**Solution:**
```bash
# Check .build-version
cat .build-version

# Check git hook exists
cat .git/hooks/pre-commit

# Test hook manually
.git/hooks/pre-commit

# Verify sync worked
git diff config.yaml Dockerfile www/main.html www/js/init-v4.js
```

### **Issue: Module Not Loading**

**Solution:**
```bash
# Check module exists
ls www/js/modules/

# Check init-v4.js loads it
cat www/js/init-v4.js | grep "module-name"

# Check for console errors
# (Ask user to provide browser console output)

# Verify dual export pattern
cat www/js/modules/module-name.js | grep "window\."
```

### **Issue: HA Ingress Not Working**

**Solution:**
```bash
# Check API base detection
cat www/diagnostic.html | grep getApiBase

# Verify pattern matches working code
cat 20_CODE_PATTERN_API_BASE.md

# Test regex pattern
# const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
```

---

## 📚 Next Steps

Now that you understand the development workflow:

1. **Understand Architecture** → Read [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md)
2. **Learn Working Patterns** → Read files 20-25
3. **Setup Local Environment** → Read [40_LOCAL_DEV_ENVIRONMENT.md](40_LOCAL_DEV_ENVIRONMENT.md)
4. **Start Coding** → Pick an issue from PROGRESS_TRACKER.md

---

## 🎉 You're Ready to Develop!

You now know:
- ✅ Development workflow (TDD)
- ✅ Common commands
- ✅ How to fix bugs systematically
- ✅ How to add features with tests
- ✅ Best practices (do's and don'ts)
- ✅ Troubleshooting techniques

**Next Action:** Read [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md) to understand the complete system

---

## 📝 Quick Reference

### **File Locations**
```
.build-version          - Version source of truth
www/                    - Frontend files
www/js/modules/         - ES6 modules
www/js/init-v4.js       - Module loader
server.py               - Backend API
adb_bridge.py           - ADB integration
tests/                  - Test files
PROGRESS_TRACKER.md     - Current status
```

### **Key Commands**
```bash
git status              - Check status
git diff                - View changes
npm test                - Run tests
curl localhost:3000     - Test frontend
curl localhost:8099/api - Test API
```

### **Documentation Files**
```
PROJECT_OVERVIEW.md     - Start here (overview)
00_START_HERE.md        - Navigation guide
01-02                   - Quick start
10-12                   - Architecture
20-25                   - Working patterns
30-31                   - Live streaming
40-42                   - Testing
50-51                   - API reference
60-61                   - Best practices
```

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**For Project Version:** Visual Mapper 0.0.1+

---

**Read Next:** [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md)
**Read Previous:** [01_CLAUDE_PERMISSIONS_SETUP.md](01_CLAUDE_PERMISSIONS_SETUP.md)
