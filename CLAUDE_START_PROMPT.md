# Claude Start Prompt - Visual Mapper Rebuild

**For New Claude Code Sessions Starting Fresh**

**Date:** 2025-12-21
**Project:** Visual Mapper - Home Assistant Android Device Monitor
**Starting Version:** 0.0.1
**Target Version:** 1.0.0

---

## 🎯 Your Mission

Build Visual Mapper from scratch (v0.0.1 → v1.0.0) - a Home Assistant addon for Android device monitoring, automation, and control.

**Think:** Open-source alternative to Vysor/AirDroid

---

## 📖 READ THESE FILES FIRST (IN ORDER)

### **1. PROJECT_OVERVIEW.md** ← START HERE
**Why:** Complete context - what we're building, why from scratch, critical requirements

**Key Takeaways:**
- Starting at v0.0.1 (NOT continuing v4.6.0-beta.X)
- Legacy code = reference only, test before using!
- **CRITICAL:** Cache busting on ALL file references (`?v=`)
- **CRITICAL:** Dual export pattern (ES6 + global window)
- **CRITICAL:** API base detection for HA ingress
- 7-phase development roadmap (Phase 0-7)

### **2. NEW_PROJECT_PLAN.md** ← YOUR TASK LIST
**Why:** Detailed build plan with tasks, checklists, success criteria

**Current Status:**
- Phase 0: Foundation (NOT STARTED - 0%)
- You'll work through Phase 0 → Phase 7

**Your Job:**
- Follow task checklists
- Mark tasks complete as you go
- Update progress percentages
- Reference code patterns (files 20-25)

### **3. DOCUMENTATION_STATUS.md** ← WHAT EXISTS
**Why:** Shows what documentation is complete vs. in progress

**Files Created:**
- PROJECT_OVERVIEW.md ✅
- NEW_PROJECT_PLAN.md ✅
- DOCUMENTATION_STATUS.md ✅
- 00-02, 10 (need minor updates)
- 11-61 (placeholders or not created yet)

---

## ⚙️ Development Workflow

```
1. Read PROJECT_OVERVIEW.md (understand context)
   ↓
2. Read NEW_PROJECT_PLAN.md (see current phase tasks)
   ↓
3. Read relevant architecture/pattern docs (10-25)
   ↓
4. Write test FIRST (TDD approach)
   ↓
5. Implement feature using proven patterns
   ↓
6. Run tests (automatic - you have permission)
   ↓
7. Test on localhost:3000 (automatic)
   ↓
8. Report to user: "Ready for HA validation"
   ↓
9. User tests in real Home Assistant
   ↓
10. User provides feedback (approve/iterate)
    ↓
11. Bump version if user-facing change
    ↓
12. Git commit (requires user approval)
    ↓
13. Update NEW_PROJECT_PLAN.md progress
```

---

## 🚨 CRITICAL REQUIREMENTS (Never Skip These!)

### **1. Cache Busting - EVERYWHERE**

```html
<!-- EVERY HTML file needs this -->
<meta name="version" content="0.0.1" data-build="2025-12-21">
<link rel="stylesheet" href="styles.css?v=0.0.1">
<script src="js/init.js?v=0.0.1"></script>
```

```javascript
// EVERY module import needs version
await import(`./modules/api-client.js?v=${APP_VERSION}`);
```

**Why:** Home Assistant ingress caches aggressively. Without `?v=`, users get old code.

### **2. Dual Export Pattern**

```javascript
// EVERY module must do BOTH:
class MyModule {
    // ... code ...
}

export default MyModule;        // ES6 export
window.MyModule = MyModule;     // Global export
```

**Why:** Popup windows don't share ES6 module scope. Legacy code needs global access.

### **3. API Base Detection**

```javascript
function getApiBase() {
    if (window.API_BASE) return window.API_BASE;
    if (window.opener?.API_BASE) return window.opener.API_BASE;

    const url = window.location.href;
    const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
    if (ingressMatch) return ingressMatch[0] + '/api';

    return '/api';
}
```

**Why:** HA ingress changes URLs dynamically. Hardcoded `/api/` fails in production.

### **4. DOM Ready Checks**

```javascript
// ALWAYS check element exists
const element = document.getElementById('my-element');
if (!element) {
    console.error('[Module] Element not found');
    return;
}

// OR wait for DOM
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
```

**Why:** Scripts may run before DOM loads. `null.addEventListener()` crashes.

### **5. Version Sync via Git Hook**

Single source of truth: `.build-version`

Git hook auto-syncs to:
- config.yaml
- Dockerfile
- all HTML files
- init.js

**Regex must match:** `[0-9.]*[^\"]*` (supports `-alpha`, `-beta`, `-rc`)

---

## 📚 Code Pattern Reference

When implementing features, reference these patterns:

### **Proven Working (Use with Confidence)**
- Dual export pattern (21_CODE_PATTERN_MODULES.md)
- API base detection (20_CODE_PATTERN_API_BASE.md)
- Coordinate mapping (23_CODE_PATTERN_COORDINATE_MAPPING.md)

### **Legacy Reference (Test Before Using!)**
- Screenshot capture (22_CODE_PATTERN_SCREENSHOT.md)
- WebSocket streaming (25_CODE_PATTERN_WEBSOCKET.md)

### **Known Issues from Legacy**
- Navigation regression (lost working nav menu)
- Version accumulation (regex bug: `4.6.0-beta.6-beta.5...`)
- Module loading failures (missing `type="module"`)
- dev.html bugs (device selector, drawing offset, null errors)
- Live streaming never worked (needs complete implementation)

---

## 🧪 Testing Requirements

**Before EVERY commit:**
- ✅ Write test first (TDD)
- ✅ Test passes
- ✅ No console errors
- ✅ Tested on localhost:3000
- ✅ User validated in HA (for user-facing changes)

**Test Coverage Target:** >60%

**Test Frameworks:**
- Playwright (E2E browser tests)
- Jest (JavaScript unit tests)
- pytest (Python backend tests)

---

## 👥 Your Role vs. User Role

### **You (Claude)**
- ✅ Read documentation
- ✅ Write tests FIRST
- ✅ Implement features
- ✅ Run tests automatically
- ✅ Test on localhost:3000 automatically
- ✅ Fix bugs
- ✅ Update NEW_PROJECT_PLAN.md progress
- ❌ Cannot push to git (requires user approval)
- ❌ Cannot test in real HA (user does this)

### **User**
- ✅ Tests in real Home Assistant
- ✅ Provides console errors for debugging
- ✅ Approves git commits/pushes
- ✅ Makes final decisions
- ✅ Configures Claude permissions (01_CLAUDE_PERMISSIONS_SETUP.md)

---

## 🚀 Starting Phase 0: Foundation

**Your first tasks:**

1. **Read PROJECT_OVERVIEW.md** (understand complete context)
2. **Read NEW_PROJECT_PLAN.md Phase 0** (see task list)
3. **Setup project structure:**
   - Clean directory structure
   - Dockerfile with non-root user
   - nginx config (ports 3000, 8099, 8100)
   - Basic HTML with cache busting
   - Version sync git hook
4. **Write first test** (even if simple)
5. **Verify cache busting works**
6. **Mark Phase 0 tasks complete in NEW_PROJECT_PLAN.md**

---

## 📊 Success Metrics (Track These)

### **Technical**
- Page load <500ms
- Screenshot latency <200ms
- API response <100ms
- Memory <256MB
- Test coverage >60%

### **Quality**
- Zero console errors
- Zero broken links
- Cache busting works
- 100% tests passing

### **User Experience**
- 5-minute setup (install → first screenshot)
- 2-minute sensor creation
- 30-second live view startup

---

## 🗺️ Roadmap Overview

```
Phase 0: Foundation (v0.0.1)
  → Basic infrastructure, version sync, cache busting

Phase 1: Screenshot Capture (v0.0.2)
  → ADB connection, screenshot, UI elements

Phase 2: Device Control (v0.0.3)
  → Tap, swipe, type commands

Phase 3: Sensor Creation (v0.0.4)
  → HA sensor integration, MQTT discovery

Phase 4: Live Streaming (v0.0.5)
  → WebRTC + Canvas overlays, <100ms latency

Phase 5: Testing Infrastructure (v0.0.6)
  → Playwright + Jest + pytest, CI/CD

Phase 6: Polish (v0.0.7 → v0.1.0)
  → Complete all pages, optimize, document

Phase 7: Community Release (v1.0.0)
  → Plugin system, contribution guide, public release
```

---

## 💡 Quick Decision Guide

**"Should I use this legacy code?"**
→ Check if it has ⚠️ or 🔴 label. If yes, test it first!

**"Cache busting or not?"**
→ ALWAYS cache bust. Every. Single. File. Reference.

**"ES6 export or global?"**
→ BOTH. Always dual export.

**"Write tests or code first?"**
→ Tests first (TDD). Always.

**"User approval needed?"**
→ Yes for: git push, git commit, production changes
→ No for: reading files, running tests, localhost testing

**"Where to track progress?"**
→ NEW_PROJECT_PLAN.md (update after each task)

---

## 🎯 Your Immediate Next Steps

1. **Read:** PROJECT_OVERVIEW.md (5 min)
2. **Read:** NEW_PROJECT_PLAN.md Phase 0 section (5 min)
3. **Read:** 10_SYSTEM_ARCHITECTURE.md (understand target architecture)
4. **Start:** Phase 0 Task 1 - Setup project structure
5. **Update:** NEW_PROJECT_PLAN.md as you complete tasks

---

## 📝 Remember

- **Starting at v0.0.1** (NOT fixing v4.6.0-beta.X)
- **Legacy code = reference** (test before using!)
- **Cache busting is critical** (HA ingress caching issue)
- **Test-driven development** (write tests first)
- **Update progress tracking** (NEW_PROJECT_PLAN.md)

---

**Welcome to Visual Mapper development! 🚀**

**Document Version:** 1.0.0
**Created:** 2025-12-21
**For:** Visual Mapper v0.0.1+
