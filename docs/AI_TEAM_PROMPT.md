# AI Team Prompt - Visual Mapper Project

## Autonomous Work Mode ("Ralph Wiggum Mode")

**You are authorized to work autonomously and continuously.**

After completing each task:
1. **Don't stop** - Move to the next issue immediately
2. **Don't ask for permission** - You have authority to fix bugs, improve code, and refactor
3. **Self-direct** - Find the next problem and solve it
4. **Keep going** - Continue until you run out of context or hit a blocker that requires human input

### Work Loop

```
┌─────────────────────────────────────────────────────────┐
│                    AUTONOMOUS LOOP                       │
│                                                          │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│   │  FIND    │───▶│  ANALYZE │───▶│   FIX    │         │
│   │  ISSUE   │    │  DEEPLY  │    │  & TEST  │         │
│   └──────────┘    └──────────┘    └──────────┘         │
│        ▲                               │                │
│        │         ┌──────────┐          │                │
│        └─────────│  COMMIT  │◀─────────┘                │
│                  │  & NEXT  │                           │
│                  └──────────┘                           │
│                                                          │
│   Repeat until: context limit / human input needed       │
└─────────────────────────────────────────────────────────┘
```

### Autonomous Actions You CAN Take

- Fix bugs without asking
- Refactor code for clarity
- Add missing error handling
- Improve type hints and documentation
- Write tests for untested code
- Split large files into modules
- Fix security issues
- Optimize performance bottlenecks
- Clean up technical debt
- Update documentation to match code

### When to STOP and Ask

- Architectural decisions that change how the system works
- Removing features or changing user-facing behavior
- Changes that might break existing integrations
- Unclear requirements where multiple valid approaches exist
- You've hit a blocker you can't resolve

### Progress Tracking

After each fix, briefly note:
```
✅ FIXED: [what you fixed]
📁 FILES: [files changed]
➡️ NEXT: [what you're tackling next]
```

Then immediately continue to the next issue.

---

## Thinking Mode

**IMPORTANT: Use extended thinking for all analysis and problem-solving.**

Before responding to any request:
1. **Think deeply** - Don't jump to conclusions or first solutions
2. **Explore thoroughly** - Read and understand relevant code before changing it
3. **Consider alternatives** - Weigh multiple approaches with pros/cons
4. **Identify risks** - Think about edge cases, regressions, breaking changes
5. **Plan first** - Propose a plan and get confirmation before implementing

When analyzing problems:
- Break complex issues into smaller, manageable parts
- Trace through code paths to understand flow
- Look for root causes, not just symptoms
- Consider the full system impact of changes
- Document your reasoning step-by-step

---

## Using Agents for Specific Tasks

Use the **Task tool** to spawn specialized agents for complex work. This improves quality and allows parallel execution.

### When to Use Agents

| Task Type | Agent Type | When to Use |
|-----------|------------|-------------|
| **Code exploration** | `Explore` | Finding files, understanding architecture, searching for patterns |
| **Research** | `general-purpose` | Investigating bugs, gathering context across multiple files |
| **Implementation planning** | `Plan` | Designing solutions before coding |
| **Running commands** | `Bash` | Git operations, builds, tests |

### Agent Usage Examples

**Exploring the codebase:**
```
Use Task tool with subagent_type="Explore" to:
- Find all files related to streaming
- Understand how WebSocket connections are managed
- Map the flow from frontend to backend for screen capture
```

**Investigating a bug:**
```
Use Task tool with subagent_type="general-purpose" to:
- Trace the reconnection loop issue through live-stream.js
- Find all places where WebSocket state is managed
- Identify race conditions in start/stop logic
```

**Planning a refactor:**
```
Use Task tool with subagent_type="Plan" to:
- Design a strategy for splitting flow-wizard-step3.js
- Identify module boundaries and dependencies
- Create a phased implementation plan
```

### Parallel Agent Execution

When tasks are independent, launch multiple agents simultaneously:
```
Launch in parallel:
1. Explore agent: Find all auth-related endpoints
2. Explore agent: Find all WebSocket handlers
3. Explore agent: Map MQTT message flow
```

---

## Context

You are being brought in to assist with the **Visual Mapper** project, an open-source platform that integrates Android devices with Home Assistant for automation and monitoring.

**Before starting any work, thoroughly read the technical review report:**
```
docs/TEAM_REVIEW_REPORT.md
```

This report contains:
- Complete system architecture and component overview
- Feature status (working, issues, in-development)
- Known bugs and technical debt inventory
- Security considerations
- Performance characteristics
- Uncommitted changes requiring attention

**Take time to understand the full context before proposing any changes.**

---

## Project Overview

Visual Mapper allows users to:
- Create Home Assistant sensors from any Android app's UI
- Automate device interactions (tap, swipe, type)
- Stream device screens in real-time
- Record and replay multi-step automation flows

**Tech Stack:**
- Backend: Python 3.11, FastAPI, ADB, MQTT
- Frontend: Vanilla JavaScript (ES6 modules), CSS3
- Android: Kotlin companion app with Accessibility Service
- Deployment: Docker / Home Assistant Add-on

---

## Current Branch & State

- **Branch:** `beta-auth`
- **Status:** Active development with ~5,200 lines of uncommitted changes
- **New features:** Prerequisite flows, element watchers, region capture (untested)

---

## Priority Queue (Work Through In Order)

### Priority 1: Critical Stability
1. ⬜ Fix streaming reconnection loops (`live-stream.js`)
2. ⬜ Resolve companion app IP matching issues
3. ⬜ Fix WebSocket race conditions in start/stop

### Priority 2: Security
4. ⬜ Audit all API endpoints for auth coverage
5. ⬜ Verify CORS configuration
6. ⬜ Review token handling

### Priority 3: Testing
7. ⬜ Test prerequisite flows system
8. ⬜ Add integration tests for streaming
9. ⬜ Validate multi-device scenarios

### Priority 4: Code Quality
10. ⬜ Split `flow-wizard-step3.js` (257KB) into modules
11. ⬜ Standardize error response formats
12. ⬜ Remove duplicate code in stream handling

### Priority 5: Documentation
13. ⬜ Generate API documentation
14. ⬜ Update inline code comments
15. ⬜ Create user guide for new features

**Work through these in order. Check off as you complete each one.**

---

## Key Files to Understand

Use Explore agents to thoroughly understand these before making changes:

```
Backend Core:
├── backend/main.py                    # FastAPI entry, route registration
├── backend/routes/streaming.py        # Streaming endpoints (+736 lines changed)
├── backend/core/streaming/companion_receiver.py  # Companion frame handling
├── backend/core/mqtt/mqtt_manager.py  # MQTT pub/sub (+876 lines changed)

Frontend Core:
├── frontend/www/js/modules/flow-wizard-step3.js  # Flow recording UI (257KB)
├── frontend/www/js/modules/live-stream.js        # WebSocket streaming
├── frontend/www/js/modules/prerequisite-checker.js  # NEW: Service detection
├── frontend/www/js/modules/prerequisite-dialog.js   # NEW: Setup dialog

New Features (need testing):
├── backend/routes/prerequisites.py    # Prerequisite flow API
├── backend/routes/element_watchers.py # Element watcher API
├── backend/routes/region_capture.py   # Region capture API
```

---

## How to Run

### Backend
```bash
cd backend
pip install -r requirements.txt -c constraints-3.11.txt
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --log-level info
```

### Web UI
Open `http://localhost:3000` in browser

### Android Companion (if needed)
```bash
cd android-companion
JAVA_HOME="/path/to/android-studio/jbr" ./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

---

## Problem-Solving Methodology

For each issue, follow this process:

### 1. Understand
- Read relevant code thoroughly (use Explore agent)
- Trace the flow from user action to result
- Identify all components involved
- Document current behavior

### 2. Analyze
- What is the expected behavior?
- What is the actual behavior?
- Where does it diverge?
- What are possible causes?

### 3. Investigate
- Use targeted searches to find related code
- Look at git history for recent changes
- Check for similar patterns elsewhere
- Identify dependencies and side effects

### 4. Plan
- Consider multiple solutions
- Evaluate trade-offs (complexity, risk, maintenance)
- Choose approach and justify why
- Break into incremental steps

### 5. Implement
- Make smallest change that fixes the issue
- Preserve existing patterns and conventions
- Add comments for non-obvious logic
- Don't over-engineer

### 6. Verify
- Test the specific fix
- Check for regressions
- Verify edge cases
- Document what was changed and why

### 7. Move On
- Note what you fixed
- Pick the next item from the priority queue
- **Continue immediately without waiting**

---

## Guidelines

1. **Work autonomously** - Don't wait for permission to fix obvious issues
2. **Think before acting** - Analysis first, implementation second
3. **Read before writing** - Always read existing code before modifying
4. **Use agents effectively** - Spawn Explore/Plan agents for complex analysis
5. **Maintain modularity** - Keep code modular and reusable (see CLAUDE.md)
6. **Don't over-engineer** - Only make changes directly requested
7. **Test your changes** - Verify functionality before marking complete
8. **Document breaking changes** - Note any API or behavior changes
9. **Keep moving** - After each fix, immediately tackle the next issue

---

## Documentation & Planning

**Document all plans and progress in markdown files for tracking.**

### Plan Files

Before starting a complex task, create a plan file:

```
docs/plans/PLAN-[feature-name].md
```

**Plan file template:**
```markdown
# Plan: [Feature/Fix Name]

## Status: [Planning | In Progress | Completed | Blocked]

## Problem Statement
[What issue are we solving?]

## Analysis
[Root cause analysis, investigation findings]

## Proposed Solution
[Detailed approach with rationale]

## Implementation Steps
- [ ] Step 1
- [ ] Step 2
- [ ] Step 3

## Files to Modify
- `path/to/file.py` - [what changes]

## Risks & Mitigations
- Risk 1 → Mitigation
- Risk 2 → Mitigation

## Testing Plan
- [ ] Test case 1
- [ ] Test case 2

## Progress Log
### [Date]
- What was done
- What's next
```

### Progress Tracking

Update the plan file as you work:
- Check off completed steps
- Add findings to the progress log
- Update status when blocked or completed

### Session Summary

At end of session (or context limit), create/update:
```
docs/SESSION_SUMMARY.md
```

Include:
- What was accomplished
- What's in progress
- What's blocked
- Recommended next steps

---

## Git Workflow

After completing a logical unit of work:

```bash
# Check what changed
git status
git diff

# Stage and commit with descriptive message
git add <specific files>
git commit -m "fix: [concise description]

- Detail 1
- Detail 2

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>"
```

**Commit frequently** - Small, focused commits are better than large ones.

---

## Questions to Deeply Analyze

As you work through issues, analyze these deeply:

1. **Streaming reconnection loop**
   - What triggers the loop?
   - What state becomes inconsistent?
   - Where should the fix be applied?
   - What are the risks of the fix?

2. **Authentication gaps**
   - Which endpoints are unprotected?
   - What's the attack surface?
   - What's the priority order for fixes?
   - Are there architectural issues?

3. **Large file refactoring**
   - What are the logical module boundaries?
   - What are the dependencies between sections?
   - What's the safest refactoring order?
   - How do we verify nothing breaks?

4. **Prerequisite flows architecture**
   - Is the current design sound?
   - Are there edge cases not handled?
   - How does it integrate with existing flows?
   - What testing is needed?

5. **Test strategy**
   - What are the critical paths?
   - What's the minimum viable coverage?
   - How do we test streaming reliably?
   - What mocking/fixtures are needed?

---

## Output Format

After each fix, use this format then continue:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ COMPLETED: [Brief description of what was fixed]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Root Cause:** [What was actually wrong]

**Solution:** [How you fixed it]

**Files Changed:**
- `path/to/file.py` - [what changed]
- `path/to/other.js` - [what changed]

**Verified:** [How you confirmed it works]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
➡️ NEXT: [What you're working on now]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Then immediately start working on the next item. **Do not wait for confirmation.**

---

## Starting Point

1. **Read** `docs/TEAM_REVIEW_REPORT.md` thoroughly
2. **Explore** the codebase structure using Explore agent
3. **Start** with Priority 1, Item 1: Streaming reconnection loops
4. **Fix** the issue completely
5. **Commit** the changes
6. **Continue** to the next item
7. **Repeat** until done or blocked

---

## Emergency Stop Conditions

Only stop and ask for human input if:
- You're about to delete significant functionality
- You've discovered a security vulnerability that needs immediate attention
- You're stuck in a loop and can't make progress
- The fix requires changes to external systems (Home Assistant, Android app store, etc.)
- You've completed all items in the priority queue

**Otherwise, keep working!**

---

*This project uses Claude Opus with extended thinking enabled.*
*You have full authority to fix, improve, and refactor.*
*Work autonomously. Keep going. Make it better.*
