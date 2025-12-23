# Visual Mapper - Documentation Navigation

**Welcome to Visual Mapper Development Documentation**

**Starting Version:** 0.0.1
**Target Version:** 1.0.0 (Community Release)
**Last Updated:** 2025-12-21

---

## ⚠️ START WITH THESE 3 FILES

1. **CLAUDE_START_PROMPT.md** ← Quick start (5 min)
2. **PROJECT_OVERVIEW.md** ← Complete context (15 min)
3. **NEW_PROJECT_PLAN.md** ← Task tracking

**Then read this file for documentation navigation**

---

## 🎯 What is Visual Mapper?

**Visual Mapper** is a Home Assistant addon for Android device monitoring, automation, and control.

**Core Features:**
- Screenshot Capture with UI element extraction
- Live Streaming with interactive overlays
- Device Control via ADB (tap, swipe, type)
- Sensor Creation for Home Assistant
- Action Automation
- Multi-Device Management

**Goal:** Open-source alternative to Vysor/AirDroid, self-hosted, privacy-focused.

---

## 📚 Documentation Structure (26 Files)

### **Quick Start (3 files)**
| File | Purpose | Read When |
|------|---------|-----------|
| CLAUDE_START_PROMPT.md | New session quick start | First thing |
| PROJECT_OVERVIEW.md | Complete context | After quick start |
| NEW_PROJECT_PLAN.md | Build plan & tasks | Before coding |

### **Navigation & Setup (3 files)**
| File | Purpose | Read When |
|------|---------|-----------|
| 00_START_HERE.md | This file - navigation | For file reference |
| 01_CLAUDE_PERMISSIONS_SETUP.md | USER permission config | Before autonomous testing |
| 02_QUICK_START_GUIDE.md | Development workflow | Learning workflow |

### **Architecture (3 files)**
| File | Purpose | Read When |
|------|---------|-----------|
| 10_SYSTEM_ARCHITECTURE.md | Complete system design | Understanding structure |
| 11_FRONTEND_MODULES.md | ES6 modules | Building frontend |
| 12_BACKEND_API.md | FastAPI + ADB | Building backend |

### **Code Patterns (6 files)**
| File | Purpose | Status |
|------|---------|--------|
| 20_CODE_PATTERN_API_BASE.md | HA ingress detection | ⚠️ Legacy - test! |
| 21_CODE_PATTERN_MODULES.md | Dual export | ⚠️ Legacy - test! |
| 22_CODE_PATTERN_SCREENSHOT.md | Screenshot capture | ⚠️ Legacy - test! |
| 23_CODE_PATTERN_COORDINATE_MAPPING.md | Coord conversion | ⚠️ Legacy - test! |
| 24_CODE_PATTERN_VERSION_SYNC.md | Git hook | ⚠️ Legacy - test! |
| 25_CODE_PATTERN_WEBSOCKET.md | WebSocket streaming | ⚠️ Legacy - test! |

### **Live Streaming (2 files)**
| File | Purpose | Status |
|------|---------|--------|
| 30_LIVE_STREAMING_RESEARCH.md | WebRTC vs WebSocket | Research complete |
| 31_LIVE_STREAMING_IMPLEMENTATION.md | Implementation plan | Ready to implement |

### **Testing (3 files)**
| File | Purpose | Read When |
|------|---------|-----------|
| 40_LOCAL_DEV_ENVIRONMENT.md | Docker setup | Setting up dev env |
| 41_TESTING_PLAYWRIGHT.md | E2E tests | Writing tests |
| 42_TESTING_JEST_PYTEST.md | Unit tests | Writing tests |

### **API Reference (2 files)**
| File | Purpose | Read When |
|------|---------|-----------|
| 50_API_ENDPOINTS.md | REST API docs | Building API calls |
| 51_ADB_BRIDGE_METHODS.md | ADB methods | Using ADB |

### **Best Practices (2 files)**
| File | Purpose | Read When |
|------|---------|-----------|
| 60_SOLID_PRINCIPLES.md | Architecture principles | Designing features |
| 61_CONTRIBUTING.md | Community guidelines | Contributing |

### **Status Tracking (2 files)**
| File | Purpose | Read When |
|------|---------|-----------|
| DOCUMENTATION_STATUS.md | Doc completion status | Checking progress |
| NEW_PROJECT_PLAN.md | Build progress | Daily tracking |

---

## 🚀 Reading Paths

### **Path 1: New Claude Session**
```
1. CLAUDE_START_PROMPT.md (quick start)
2. PROJECT_OVERVIEW.md (context)
3. NEW_PROJECT_PLAN.md (current phase tasks)
4. Start building!
```

### **Path 2: Understanding Architecture**
```
1. 10_SYSTEM_ARCHITECTURE.md
2. 11_FRONTEND_MODULES.md
3. 12_BACKEND_API.md
4. Code pattern files (20-25) as needed
```

### **Path 3: Implementing Features**
```
1. NEW_PROJECT_PLAN.md (find current task)
2. Relevant code pattern file (20-25)
3. 60_SOLID_PRINCIPLES.md (design guidance)
4. Testing files (40-42)
```

### **Path 4: Setting Up Development**
```
1. 01_CLAUDE_PERMISSIONS_SETUP.md
2. 40_LOCAL_DEV_ENVIRONMENT.md
3. 41_TESTING_PLAYWRIGHT.md
4. 42_TESTING_JEST_PYTEST.md
```

---

## 🎯 Quick Reference

### **Critical Requirements**
- **Cache Busting:** `?v=0.0.1` on ALL file references
- **Dual Exports:** ES6 + global window
- **API Base Detection:** For HA ingress
- **DOM Ready Checks:** Avoid null errors
- **Version Sync:** Git hook auto-sync

See: PROJECT_OVERVIEW.md "Critical Requirements" section

### **Code Example Labels**
- ✅ **PROVEN WORKING** - Use with confidence
- ⚠️ **LEGACY REFERENCE** - Test before using!
- 🔴 **KNOWN BROKEN** - Example of what NOT to do
- 📖 **CONCEPTUAL** - Pseudocode only

### **Development Phases**
- Phase 0: Foundation (v0.0.1)
- Phase 1: Screenshot (v0.0.2)
- Phase 2: Device Control (v0.0.3)
- Phase 3: Sensors (v0.0.4)
- Phase 4: Live Streaming (v0.0.5)
- Phase 5: Testing (v0.0.6)
- Phase 6: Polish (v0.1.0)
- Phase 7: Community (v1.0.0)

See: NEW_PROJECT_PLAN.md for detailed task lists

---

## 📝 Legacy vs. New

**Legacy System:**
- v4.6.0-beta.1 through beta.10
- Had many issues (see PROJECT_OVERVIEW.md)
- Use as REFERENCE ONLY
- Test before using any code

**New System:**
- Starting at v0.0.1
- Building from scratch
- Following best practices
- Test-driven development

**Files:**
- PROGRESS_TRACKER.md = Legacy history (reference)
- NEW_PROJECT_PLAN.md = New build plan (active)

---

## 💡 Tips

**Before coding:**
- Read PROJECT_OVERVIEW.md (understand why decisions were made)
- Check NEW_PROJECT_PLAN.md (know current phase)
- Review relevant code patterns (20-25)

**While coding:**
- Write tests FIRST (TDD)
- Use proven patterns
- Update NEW_PROJECT_PLAN.md as you complete tasks
- Check DOCUMENTATION_STATUS.md if unsure what exists

**Before committing:**
- All tests pass
- No console errors
- Cache busting applied
- User validated (if user-facing)

---

**Document Version:** 2.0.0 (Updated for v0.0.1 rebuild)
**Created:** 2025-12-21
**For Project Version:** Visual Mapper 0.0.1+
