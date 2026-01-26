# Plan: Split flow-wizard-step3.js into Modules

## Status: In Progress

## Problem Statement
`frontend/www/js/modules/flow-wizard-step3.js` is 6,653 lines (264KB) - too large to maintain effectively. The file contains multiple distinct functional areas that should be separated into focused modules.

## Current File Analysis

### Size & Structure
- **Total Lines:** 6,653
- **File Size:** 264KB
- **Extractable:** ~5,600 lines (84%)
- **Core to Remain:** ~1,050 lines (initialization, exports)

### Major Functional Areas Identified

| Area | Lines | Priority | Description |
|------|-------|----------|-------------|
| Streaming Control | 460 | HIGH | startStreaming, stopStreaming, reconnectStream |
| Element Refresh | 307 | HIGH | refreshElements, auto-refresh logic |
| Suggestions Feature | 960 | HIGH | Entire suggestions tab UI and logic |
| Screen Identification | 183 | HIGH | computeScreenId, extractUiLandmarks |
| Navigation Context | 430 | MEDIUM | Navigation panel setup and updates |
| Hover/Tooltip | 350 | MEDIUM | Tooltip rendering and highlight |
| Element Interactions | 390 | MEDIUM | Click, tap, coordinate conversion |
| Panel/Tab UI | 480 | MEDIUM | Tab switching, toolbar handlers |
| Element Tree | 200 | MEDIUM | Element tree panel |
| Flow Steps | 560 | MEDIUM | Step rendering, mismatch detection |
| Companion App | 157 | MEDIUM | Companion status and elements |
| Zoom/Scale | 90 | LOW | Zoom controls |

## Solution: Modular Architecture

### Target Folder Structure
```
frontend/www/js/modules/
├── flow-wizard-step3.js          # Slimmed down (core + exports)
└── step3/
    ├── streaming-control.js      # HIGH: Start/stop/reconnect streaming
    ├── element-refresh.js        # HIGH: Element fetching and processing
    ├── suggestions.js            # HIGH: Suggestions tab feature
    ├── screen-identification.js  # HIGH: Screen hashing and learning
    ├── navigation-context.js     # MEDIUM: Navigation panel management
    ├── hover-tooltip.js          # MEDIUM: Hover and tooltip handling
    ├── element-interactions.js   # MEDIUM: Click and tap handlers
    ├── element-tree.js           # MEDIUM: Element tree panel
    ├── companion-integration.js  # MEDIUM: Companion app integration
    └── gesture-effects.js        # LOW: Tap ripple, swipe path visuals
```

### Backward Compatibility Strategy
1. Main file `flow-wizard-step3.js` re-exports everything from submodules
2. Existing imports continue to work unchanged
3. New code can import directly from submodules

### Import Pattern
```javascript
// In flow-wizard-step3.js (main file)
import * as StreamingControl from './step3/streaming-control.js';
import * as ElementRefresh from './step3/element-refresh.js';
// ... etc

// Re-export for backward compatibility
export const startStreaming = StreamingControl.startStreaming;
export const stopStreaming = StreamingControl.stopStreaming;
// ... etc

// Default export maintains Step3Module pattern
export default {
    startStreaming,
    stopStreaming,
    refreshElements,
    // ... all functions
};
```

## Implementation Phases

### Phase 1: High-Priority Extractions
**Goal:** Extract largest, most independent modules first

1. **streaming-control.js** (~460 lines)
   - `startStreaming()` (2067-2402)
   - `stopStreaming()` (2403-2430)
   - `reconnectStream()` (2431-2457)
   - `restartCompanionStreaming()` (2501-2553)
   - `prepareDeviceForStreaming()` (1914-2066)
   - `showAccessibilityServicePrompt()` (2554-2660)

2. **element-refresh.js** (~400 lines)
   - `refreshElements()` (2871-3178)
   - `startElementAutoRefresh()` (2661-2721)
   - `stopElementAutoRefresh()` (2722-2739)
   - `refreshAfterAction()` (3179-3214)

3. **screen-identification.js** (~200 lines)
   - `extractUiLandmarks()` (945-1007)
   - `computeScreenId()` (1008-1047)
   - `resolveScreenLabel()` (1049-1059)
   - `normalizeScreenLabel()` (1061-1064)
   - `getActivityShortName()` (1066-1074)
   - `maybeLearnScreen()` (1076-1126)

4. **suggestions.js** (~960 lines)
   - All functions from 4115-5072

### Phase 2: Medium-Priority Extractions

5. **navigation-context.js** (~430 lines)
   - Navigation panel setup and context updates

6. **hover-tooltip.js** (~350 lines)
   - Hover, tooltip, and highlight functions

7. **element-interactions.js** (~390 lines)
   - Click handlers, coordinate conversion

8. **element-tree.js** (~200 lines)
   - Element tree panel functions

### Phase 3: Remaining Extractions

9. **companion-integration.js** (~157 lines)
   - Companion app status and element functions

10. **gesture-effects.js** (~90 lines)
    - Tap ripple, swipe path visualizations

## Files Requiring Updates

1. `step3-controller.js` - Update imports (critical)
2. `flow-wizard.js` - May need import updates
3. Test files for step3 functionality

## Testing Strategy

1. Manual test: Flow wizard Step 3 loads correctly
2. Manual test: Streaming starts/stops properly
3. Manual test: Element refresh works
4. Manual test: Suggestions tab functions
5. Manual test: Screen identification works
6. Verify no console errors

## Success Criteria

- [x] Main file reduced to <2,000 lines
- [ ] Each submodule <500 lines
- [ ] All existing functionality preserved
- [ ] No circular dependencies
- [ ] All imports updated correctly
- [ ] Manual testing passes

## Progress Log

### 2026-01-27
- Created plan file
- Analyzed file structure (6,653 lines, 12 functional areas)
- Defined modular architecture
- Starting Phase 1 extractions
- Created `step3/streaming-control.js` (~700 lines)
  - Extracted all streaming-related functions
  - Uses callback pattern to maintain loose coupling
  - Functions: startStreaming, stopStreaming, reconnectStream, prepareDeviceForStreaming,
    restartCompanionStreaming, showAccessibilityServicePrompt, startElementAutoRefresh,
    stopElementAutoRefresh, startKeepAwake, stopKeepAwake, updateStreamStatus,
    updateCommandMethodBadge, fetchCommandRoutingMethod, startRoutingMethodPolling,
    stopRoutingMethodPolling

- Created `step3/screen-identification.js` (~230 lines)
  - extractUiLandmarks, computeScreenId, resolveScreenLabel
  - normalizeScreenLabel, getActivityShortName, maybeLearnScreen
  - getScreenContext (new helper combining context functions)

**Progress:** ~930 lines extracted (17% of extractable code)

- Created `step3/suggestions.js` (~780 lines)
  - setupSuggestionsTab, loadSuggestions, renderSuggestionsContent
  - handleQuickAddSuggestion, addSelectedSuggestions, handleBulkSensorAddition
  - getSuggestedSensors, updateAddSelectedBtnState, updateSensorCounts
  - All sensor suggestion UI and logic

- Created `step3/element-refresh.js` (~400 lines)
  - flattenCompanionElements, refreshElements, refreshAfterAction
  - clearHoverHighlight, clearAllElementsAndHover
  - Uses callback pattern for updateNavigationContext and updateScreenshotDisplay

**Progress:** ~2,310 lines extracted (41% of extractable code)

**Next Steps:**
1. Wire up modules in main file with wrapper functions
2. Extract navigation-context.js (~430 lines)
3. Extract hover-tooltip.js (~350 lines)
4. Integration testing
