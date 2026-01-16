/**
 * Flow Wizard Step 3 Module - Recording Mode
 * Visual Mapper v0.0.63
 *
 * v0.0.63: Companion app integration for fast UI element fetching
 *          - checkCompanionAppStatus() checks if companion app is available for device
 *          - refreshElements() now uses companion API when available (100-300ms vs 1-3s)
 *          - Automatic fallback to ADB uiautomator when companion unavailable
 *          - flattenCompanionElements() converts nested companion elements to flat array
 * v0.0.62: Fix sensor creation from suggestions - create actual sensors via API instead of inline definitions
 *          - handleQuickAddSuggestion now creates sensor via API and uses sensor_ids
 *          - showSuggestionEditDialog save handler now creates sensor via API
 *          - addSelectedSuggestions batch operation now creates sensors via API
 *          - handleBulkSensorAddition now creates sensors via API
 * v0.0.61: Fix screen mismatch detection for app launch transitions
 * v0.0.60: Added screen_activity and bounds to sensor source data for better deduplication
 * v0.0.59: Reduce log spam - only call setDeviceDimensions when changed, throttle guard messages
 * v0.0.58: Simplified setup overlay - trust recorder.start() 3s wait, no complex validation
 * v0.0.57: (reverted) Complex app validation polling - overcomplicated
 * v0.0.56: Enhanced setup overlay - full-screen progress indicator during device prep
 *          - Shows step-by-step progress (register, wake, unlock, launch, wait, stream)
 *          - Covers black canvas during setup to prevent seeing random screens
 *          - Validates correct app is showing before revealing stream
 * v0.0.37: Fix screen mismatch detection - ignore mismatch if last step was navigation (tap/swipe)
 * v0.0.36: Fix tap/swipe recording - capture screen context BEFORE executing action to ensure correct step metadata
 * v0.0.35: Don't re-launch app in edit mode - use isEditMode() check
 * v0.0.34: Preserve steps when returning from step 4 - don't re-launch app or reset recorder
 * v0.0.33: Fix race condition - unlock device BEFORE app launch, remove redundant dialog
 * v0.0.32: Fix device locking - await keep-awake and setWizardActive, reorder startup
 * v0.0.31: Phase 2 Refactor - Extract modules for maintainability
 *          - stream-manager.js: Stream lifecycle, element refresh, keep-awake
 *          - canvas-overlay-renderer.js: Tooltips, highlights, element overlays
 *          - gesture-handler.js: Tap/swipe detection and execution
 *          - step3-controller.js: Orchestrator for all modules
 * v0.0.30: Fixed elementIndex passthrough for sensor creation, consolidate unlock logic
 * v0.0.29: Add screen mismatch detection - warn user when adding sensors to different screen, offer to add navigation step
 * v0.0.55: Add setup status banner so users can see preparation steps
 * v0.0.54: Treat matching activity names as same screen even when signatures differ
 * v0.0.28: Fix sensor/action creation - remove redundant dynamic import, add error handling, guard timeout
 * v0.0.27: Fix flicker - batch canvas ops, add refreshElements guard, remove duplicate calls
 * v0.0.26: Simplify loading overlay - show once at start, remove from onConnect entirely
 * v0.0.25: Fix loading overlay flicker - only show on initial connect, not reconnects
 * v0.0.24: Always create fresh LiveStream - fixes stale canvas reference bug
 * v0.0.23: Fix streaming issues - applyZoom on first frame (not onConnect), add 10s loading timeout
 * v0.0.22: FPS optimization - remove per-frame zoom, debounce element refresh, defer UI updates
 * v0.0.21: Remove scrcpy option entirely - MJPEG/WebSocket modes work with overlays
 * v0.0.20: Remove broken scrcpy integration, add ws-scrcpy launch button for view-only
 * v0.0.17: Fix empty element filter to keep all clickable elements (inherited from parent)
 * v0.0.16: Scale label text with canvas width for low resolution streams
 * v0.0.15: Fix hover highlight misalignment (use separate X/Y scaling) and clear highlight on actions
 * v0.0.14: Backend now returns device dimensions in elements API, frontend updates dimensions on refresh
 * v0.0.13: Auto-update app name header when refreshing elements (detects manual app switches)
 * v0.0.12: Force canvas redraw when refreshing elements to clear old overlays
 * Handles the complete Step 3 recording screen UI and interactions:
 * - App info header and screen awareness
 * - Recording UI setup (toolbar, panels, overlays)
 * - Capture mode (polling vs streaming)
 * - Live streaming controls
 * - Element refresh and auto-refresh
 * - Hover tooltips and highlights
 * - Gesture recording (tap/swipe)
 * - Visual feedback (ripples, swipe paths)
 */

import { showToast } from './toast.js?v=0.4.0-beta.3.2';
import FlowCanvasRenderer from './flow-canvas-renderer.js?v=0.4.0-beta.3.2';
import FlowInteractions from './flow-interactions.js?v=0.4.0-beta.3.2';
import FlowStepManager from './flow-step-manager.js?v=0.4.0-beta.3.2';
import FlowRecorder from './flow-recorder.js?v=0.4.0-beta.3.2';
import LiveStream from './live-stream.js?v=0.4.0-beta.3.2';
import * as Dialogs from './flow-wizard-dialogs.js?v=0.4.0-beta.3.2';
import {
    ensureDeviceUnlocked as sharedEnsureUnlocked,
    startKeepAwake as sharedStartKeepAwake,
    stopKeepAwake as sharedStopKeepAwake,
    sendWakeSignal
} from './device-unlock.js?v=0.4.0-beta.3.2';

// Phase 2 Refactor: Import modularized components
// These modules were extracted from this file for maintainability
import * as Step3Controller from './step3-controller.js?v=0.4.0-beta.3.2';

// Helper to get API base (from global set by init.js)
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Check if companion app is available for a device
 * Caches result on wizard to avoid repeated API calls
 * @param {Object} wizard - The wizard object
 * @param {string} deviceId - The device ID to check
 * @returns {Promise<boolean>} - True if companion app is connected
 */
async function checkCompanionAppStatus(wizard, deviceId) {
    try {
        const response = await fetch(`${getApiBase()}/companion/status/${encodeURIComponent(deviceId)}`);
        if (!response.ok) return false;

        const data = await response.json();
        const hasCompanion = data.connected === true;

        // Cache on wizard
        wizard._hasCompanionApp = hasCompanion;
        wizard._companionCapabilities = data.capabilities || [];

        if (hasCompanion) {
            console.log(`[FlowWizard] Companion app connected for ${deviceId} - using fast element refresh`);
        } else {
            console.log(`[FlowWizard] No companion app for ${deviceId} - using ADB for elements`);
        }

        return hasCompanion;
    } catch (error) {
        console.warn('[FlowWizard] Error checking companion app status:', error);
        wizard._hasCompanionApp = false;
        wizard._companionCapabilities = [];
        return false;
    }
}

/**
 * Flatten nested companion app elements into a flat array
 * Companion app returns hierarchical elements with children,
 * but the UI expects a flat array with bounds
 * @param {Array} elements - Nested elements from companion app
 * @returns {Array} - Flat array of elements
 */
function flattenCompanionElements(elements) {
    const flat = [];

    function processElement(el, index) {
        // Convert companion bounds format {left, top, right, bottom} to what UI expects
        const bounds = el.bounds || {};
        const flatEl = {
            index: flat.length,
            resource_id: el.resource_id || '',
            class_name: el.class_name || el.class || '',
            text: el.text || '',
            content_desc: el.content_desc || '',
            bounds: bounds,
            // Calculate width/height for convenience
            x: bounds.left || 0,
            y: bounds.top || 0,
            width: (bounds.right || 0) - (bounds.left || 0),
            height: (bounds.bottom || 0) - (bounds.top || 0),
            clickable: el.clickable || false,
            scrollable: el.scrollable || false,
            focusable: el.focusable || false,
            selected: el.selected || false
        };

        // Only add elements that have valid bounds
        if (flatEl.width > 0 && flatEl.height > 0) {
            flat.push(flatEl);
        }

        // Process children recursively
        if (el.children && el.children.length > 0) {
            for (const child of el.children) {
                processElement(child);
            }
        }
    }

    for (const el of elements) {
        processElement(el);
    }

    return flat;
}

function updateSetupMode(wizard) {
    const modeEl = document.getElementById('step3SetupMode');
    if (!modeEl) return;
    modeEl.textContent = wizard.startFromCurrentScreen
        ? 'Start mode: Current screen'
        : 'Start mode: Restart app';
}

function setSetupStatus(wizard, message, state = 'working') {
    const statusEl = document.getElementById('step3SetupStatus');
    const messageEl = document.getElementById('step3SetupMessage');
    if (!statusEl || !messageEl) return;

    updateSetupMode(wizard);
    statusEl.classList.remove('hidden', 'ready', 'error');
    if (state === 'ready') statusEl.classList.add('ready');
    if (state === 'error') statusEl.classList.add('error');
    messageEl.textContent = message;
}

function setSetupStatusReady(wizard, message = 'Ready to record') {
    setSetupStatus(wizard, message, 'ready');
    if (wizard._setupStatusTimeout) {
        clearTimeout(wizard._setupStatusTimeout);
    }
    wizard._setupStatusTimeout = setTimeout(() => {
        const statusEl = document.getElementById('step3SetupStatus');
        if (statusEl) statusEl.classList.add('hidden');
        // Recalculate canvas zoom after container height changes
        if (wizard.canvasRenderer) {
            requestAnimationFrame(() => wizard.canvasRenderer.applyZoom());
        }
    }, 1500);
}

// =============================================================================
// Setup Overlay Controls (Full-screen progress during device preparation)
// =============================================================================

/**
 * Show the setup overlay with app info
 * @param {Object} wizard - Flow wizard instance
 */
function showSetupOverlay(wizard) {
    const overlay = document.getElementById('step3SetupOverlay');
    if (!overlay) return;

    // Reset all step states
    document.querySelectorAll('.setup-step').forEach(step => {
        step.classList.remove('active', 'done', 'error');
        const statusEl = step.querySelector('.step-status');
        if (statusEl) statusEl.textContent = '';
    });

    // Set app icon and name
    const iconEl = document.getElementById('setupAppIcon');
    const nameEl = document.getElementById('setupAppName');

    if (iconEl) {
        const icon = wizard.selectedApp?.icon;
        if (icon) {
            iconEl.src = icon;
            iconEl.style.display = '';
        } else {
            iconEl.style.display = 'none';
        }
    }

    if (nameEl) {
        const appName = wizard.selectedApp?.name || wizard.selectedApp?.package || wizard.selectedApp || 'App';
        nameEl.textContent = `Preparing ${appName}`;
    }

    overlay.classList.remove('hidden');
    wizard._setupOverlayVisible = true;
}

/**
 * Update a setup step's status
 * @param {string} stepName - Step identifier (register, wake, unlock, launch, wait, stream)
 * @param {string} status - Status: 'active', 'done', 'error', or 'pending'
 */
function updateSetupStep(stepName, status) {
    const step = document.querySelector(`.setup-step[data-step="${stepName}"]`);
    if (!step) return;

    step.classList.remove('active', 'done', 'error');
    const statusEl = step.querySelector('.step-status');

    switch (status) {
        case 'active':
            step.classList.add('active');
            if (statusEl) statusEl.textContent = '...';
            break;
        case 'done':
            step.classList.add('done');
            if (statusEl) statusEl.textContent = '\u2713'; // checkmark
            break;
        case 'error':
            step.classList.add('error');
            if (statusEl) statusEl.textContent = '\u2717'; // X mark
            break;
        default:
            // pending - no class, empty status
            if (statusEl) statusEl.textContent = '';
    }
}

/**
 * Hide the setup overlay with fade animation
 * @param {Object} wizard - Flow wizard instance (optional, for state tracking)
 */
function hideSetupOverlay(wizard) {
    const overlay = document.getElementById('step3SetupOverlay');
    if (overlay) {
        overlay.classList.add('hidden');
    }
    if (wizard) {
        wizard._setupOverlayVisible = false;
    }
}

/**
 * Validate that the correct app is showing on screen
 * @param {Object} wizard - Flow wizard instance
 * @returns {Promise<boolean>} - True if correct app is showing
 */
async function validateCurrentApp(wizard) {
    if (!wizard.selectedDevice || !wizard.selectedApp) {
        return true; // Assume OK if no app selected
    }

    try {
        const apiBase = getApiBase();
        const response = await fetch(`${apiBase}/adb/screen/current/${encodeURIComponent(wizard.selectedDevice)}`);
        if (!response.ok) return true; // Assume OK if API fails

        const data = await response.json();
        const currentPackage = data.activity?.package;
        const expectedPackage = wizard.selectedApp?.package || wizard.selectedApp;

        console.log(`[SetupOverlay] App validation: current=${currentPackage}, expected=${expectedPackage}`);
        return currentPackage === expectedPackage;
    } catch (e) {
        console.warn('[SetupOverlay] App validation failed:', e);
        return true; // Assume OK if can't validate
    }
}

/**
 * Load Step 3: Recording Mode
 */
export async function loadStep3(wizard) {
    console.log('Loading Step 3: Recording Mode');

    // Show setup overlay immediately (covers black canvas)
    showSetupOverlay(wizard);

    showToast(`Starting recording session...`, 'info');
    setSetupStatus(wizard, 'Registering session...');
    updateSetupStep('register', 'active');

    // CRITICAL: Mark wizard as active FIRST before anything else
    // This tells server to not lock this device and cancels any queued flows
    if (wizard.selectedDevice) {
        console.log('[FlowWizard] Registering wizard active FIRST...');
        await wizard.setWizardActive(wizard.selectedDevice);
        console.log('[FlowWizard] Wizard active registered, server notified');
    }
    updateSetupStep('register', 'done');

    // Wake and unlock combined - skip separate keep-awake (streaming onConnect will handle it)
    updateSetupStep('wake', 'done');
    updateSetupStep('unlock', 'active');
    if (wizard.selectedDevice) {
        console.log('[FlowWizard] Unlocking device before setup...');
        setSetupStatus(wizard, 'Unlocking device...');
        const apiBase = getApiBase();
        const unlockResult = await sharedEnsureUnlocked(wizard.selectedDevice, apiBase, {
            onStatus: (msg) => {
                console.log(`[FlowWizard] ${msg}`);
            }
        });
        console.log('[FlowWizard] Device unlock complete, continuing setup');
    }
    updateSetupStep('unlock', 'done')

    // Populate app info header
    populateAppInfo(wizard);

    // Setup navigation context panel if navigation data is available
    setupNavigationContext(wizard);

    // Phase 1 Screen Awareness: Update screen info initially
    updateScreenInfo(wizard);

    // Get canvas and context for rendering
    wizard.canvas = document.getElementById('screenshotCanvas');
    wizard.ctx = wizard.canvas.getContext('2d');
    wizard.currentImage = null;

    // Initialize helper modules
    wizard.canvasRenderer = new FlowCanvasRenderer(wizard.canvas, wizard.ctx);
    wizard.canvasRenderer.setOverlayFilters(wizard.overlayFilters);

    // Note: Element panel replaced by ElementTree in right panel
    // ElementTree is initialized in setupElementTree()

    // Check if returning from a later step (preserve existing flow steps)
    const isReturning = wizard.flowSteps && wizard.flowSteps.length > 0;
    if (isReturning) {
        console.log(`[FlowWizard] Returning to Step 3 with ${wizard.flowSteps.length} existing steps`);
    }

    // Check if returning to insert a step at a specific index
    const isInsertMode = wizard.insertAtIndex !== undefined && wizard.insertAtIndex !== null;
    if (isInsertMode) {
        console.log(`[FlowWizard] Insert mode active - will insert before step ${wizard.insertAtIndex + 1}`);
        showInsertModeBanner(wizard, wizard.insertAtIndex);
    }

    wizard.interactions = new FlowInteractions(getApiBase());

    wizard.stepManager = new FlowStepManager(document.getElementById('flowStepsList'));

    // Only create new recorder if we don't have one with steps
    // This prevents losing steps when returning from step 4
    const packageName = wizard.selectedApp?.package || wizard.selectedApp;

    if (!wizard.recorder || !isReturning) {
        // Initialize FlowRecorder (pass package name, not full object)
        wizard.recorder = new FlowRecorder(wizard.selectedDevice, packageName, wizard.recordMode);
        // Use wizard's fresh start preference (default true = always restart app fresh)
        wizard.recorder.forceRestart = wizard.freshStart !== false;
    }

    // Restore existing steps to recorder and UI if returning from later step
    if (isReturning) {
        wizard.recorder.steps = [...wizard.flowSteps];
        // Use render() to display all steps at once (addStep doesn't exist on FlowStepManager)
        wizard.stepManager.render(wizard.flowSteps);
        console.log(`[FlowWizard] Restored ${wizard.flowSteps.length} steps to UI`);
    }

    // Load pending edit steps if in edit mode (only on first load, not when returning)
    if (wizard.isEditMode() && wizard._pendingEditSteps?.length > 0 && !isReturning) {
        wizard.recorder.loadSteps(wizard._pendingEditSteps, false);
        wizard.stepManager.render(wizard.recorder.getSteps());
        console.log(`[FlowWizard] Edit mode - loaded ${wizard._pendingEditSteps.length} existing steps`);

        // Show edit mode indicator in steps panel
        const stepsHeader = document.querySelector('#stepsPanel h3, .steps-header');
        if (stepsHeader) {
            stepsHeader.innerHTML = `📝 Steps <span style="font-size: 12px; color: #f59e0b;">(editing ${wizard.preExistingStepCount} existing)</span>`;
        }
    }

    // Set insert mode on recorder if we're inserting steps
    if (isInsertMode) {
        wizard.recorder.setInsertMode(wizard.insertAtIndex);
    }

    // Pass navigation context to recorder if available
    if (wizard.navigationGraph) {
        wizard.recorder.setNavigationContext(wizard.currentScreenId || null, wizard.navigationGraph);
    }

    // Setup UI event listeners
    setupRecordingUI(wizard);

    // Setup flow steps event listeners (for step added/removed events)
    setupFlowStepsListener(wizard);

    // Only start recording session on FIRST new flow (not when returning OR editing existing flow)
    // Starting re-launches app and adds duplicate launch_app step
    const shouldStartFresh = !isReturning && !wizard.isEditMode();

    if (shouldStartFresh) {
        console.log('[FlowWizard] Starting fresh recording session');

        // Launch app step
        updateSetupStep('launch', 'active');
        setSetupStatus(wizard, 'Launching app...');
        const started = await wizard.recorder.start();
        updateSetupStep('launch', 'done');

        if (started) {
            // App launched and recorder.start() already waited 3s
            // Mark wait as done
            updateSetupStep('wait', 'done');
            updateSetupStep('stream', 'done');

            // Hide overlay - app should be ready now
            hideSetupOverlay(wizard);
            setSetupStatusReady(wizard);

            // Load screenshot display (polling mode) or streaming will start via UI
            if (wizard.captureMode !== 'streaming') {
                await wizard.updateScreenshotDisplay();
                refreshElements(wizard).then(() => {
                    wizard.updateScreenshotDisplay();
                }).catch(e => console.warn('[FlowWizard] Auto-refresh failed:', e));
            }
        } else {
            updateSetupStep('launch', 'error');
            hideSetupOverlay(wizard);
        }
    } else {
        // When returning or editing, just refresh the screenshot without re-launching
        console.log('[FlowWizard] Edit/Return mode - refreshing screenshot without re-launching app');
        // Mark all previous steps done for returning users
        updateSetupStep('register', 'done');
        updateSetupStep('wake', 'done');
        updateSetupStep('unlock', 'done');
        updateSetupStep('launch', 'done');
        updateSetupStep('wait', 'active');
        setSetupStatus(wizard, 'Restoring session...');
        try {
            await wizard.recorder.captureScreenshot();
            await wizard.updateScreenshotDisplay();
            updateSetupStep('wait', 'done');
            updateSetupStep('stream', 'done');
            hideSetupOverlay(wizard);
            setSetupStatusReady(wizard, 'Session ready');
        } catch (e) {
            console.warn('[FlowWizard] Failed to refresh screenshot:', e);
            updateSetupStep('wait', 'error');
            hideSetupOverlay(wizard);
            setSetupStatus(wizard, 'Failed to refresh screen', 'error');
        }
    }
}

/**
 * Show insert mode banner when returning from step 4 to add missing steps
 * @param {Object} wizard - Flow wizard instance
 * @param {number} insertIndex - Index where new steps will be inserted
 */
function showInsertModeBanner(wizard, insertIndex) {
    // Remove any existing banner
    const existingBanner = document.getElementById('insertModeBanner');
    if (existingBanner) existingBanner.remove();

    const screenshotPanel = document.querySelector('.screenshot-panel');
    if (!screenshotPanel) return;

    const banner = document.createElement('div');
    banner.id = 'insertModeBanner';
    banner.style.cssText = `
        background: linear-gradient(135deg, #fef3c7, #fde68a);
        border: 2px solid #f59e0b;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    `;
    banner.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px;">
            <span style="font-size: 1.5em;">➕</span>
            <div>
                <strong style="color: #92400e;">Insert Mode Active</strong>
                <p style="margin: 4px 0 0 0; color: #92400e; font-size: 0.9em;">
                    Recording navigation steps to insert before step ${insertIndex + 1}
                </p>
            </div>
        </div>
        <div style="display: flex; gap: 8px;">
            <button id="btnDoneInserting" class="btn btn-primary" style="background: #16a34a; border: none; padding: 8px 16px; border-radius: 6px; color: white; cursor: pointer;">
                Done Inserting
            </button>
            <button id="btnCancelInsert" class="btn btn-secondary" style="padding: 8px 16px; border-radius: 6px; cursor: pointer;">
                Cancel
            </button>
        </div>
    `;

    // Insert at top of screenshot panel
    screenshotPanel.prepend(banner);

    // Wire up buttons
    document.getElementById('btnDoneInserting').addEventListener('click', () => {
        console.log('[FlowWizard] Done inserting - returning to step 4');
        showToast('Steps inserted - returning to review', 'success');
        // Clear insert mode
        wizard.insertAtIndex = null;
        banner.remove();
        // Sync steps and go to step 4
        wizard.flowSteps = [...wizard.recorder.steps];
        if (typeof wizard.goToStep === 'function') {
            wizard.goToStep(4);
        } else if (window.flowWizard?.goToStep) {
            window.flowWizard.goToStep(4);
        }
    });

    document.getElementById('btnCancelInsert').addEventListener('click', () => {
        console.log('[FlowWizard] Cancel insert mode');
        wizard.insertAtIndex = null;
        banner.remove();
        showToast('Insert mode cancelled', 'info');
    });
}

/**
 * Populate app info header
 */
export function populateAppInfo(wizard) {
    console.log('[FlowWizard] populateAppInfo() called');

    const appIcon = document.getElementById('appIcon');
    const appName = document.getElementById('appName');

    if (!appIcon || !appName) {
        console.warn('[FlowWizard] App info elements not found in DOM');
        return;
    }

    // Get app data
    const packageName = wizard.selectedApp?.package || wizard.selectedApp;
    const label = wizard.selectedApp?.label || packageName;

    // Set app name (truncated for toolbar)
    const shortLabel = label.length > 20 ? label.substring(0, 18) + '...' : label;
    appName.textContent = shortLabel;
    appName.title = `${label} (${packageName})`;

    // Fetch and set app icon
    const iconUrl = `${getApiBase()}/adb/app-icon/${encodeURIComponent(wizard.selectedDevice)}/${encodeURIComponent(packageName)}`;
    appIcon.src = iconUrl;
    appIcon.onerror = () => {
        appIcon.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white"><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-size="16">📱</text></svg>';
    };

    console.log(`[FlowWizard] App info populated: ${label}`);
}

/**
 * Setup navigation context panel if navigation data is available
 * Shows current screen from navigation graph and known screens
 */
export function setupNavigationContext(wizard) {
    // Only show if we have navigation data from Step 2
    if (!wizard.navigationGraph || !wizard.navigationStats) {
        console.log('[FlowWizard] No navigation data available, skipping context panel');
        return;
    }

    const screenshotPanel = document.querySelector('.screenshot-panel');
    if (!screenshotPanel) {
        console.warn('[FlowWizard] Screenshot panel not found');
        return;
    }

    // Check if panel already exists (e.g., when returning from later step)
    const existingPanel = document.getElementById('navigationContextPanel');
    if (existingPanel) {
        console.log('[FlowWizard] Navigation context panel already exists, reusing');
        // Just update the screen count in case it changed
        const btnShowScreens = document.getElementById('btnShowScreens');
        if (btnShowScreens && wizard.navigationStats) {
            btnShowScreens.innerHTML = `📋 Screens (${wizard.navigationStats.screen_count})`;
        }
        return;
    }

    // Create navigation context panel
    const navPanel = document.createElement('div');
    navPanel.id = 'navigationContextPanel';
    navPanel.className = 'navigation-context-panel';
    navPanel.innerHTML = `
        <div class="nav-context-title">
            <span>🗺️</span>
            <span>Navigation</span>
        </div>
        <div class="nav-context-current">
            <span class="nav-screen-badge" id="navCurrentScreen">--</span>
            <span class="nav-screen-name" id="navScreenName">Loading...</span>
        </div>
        <div class="nav-context-actions">
            <div class="nav-screens-dropdown">
                <button class="nav-context-btn" id="btnShowScreens">
                    📋 Screens (${wizard.navigationStats.screen_count})
                </button>
                <div class="nav-screens-list" id="navScreensList"></div>
            </div>
        </div>
    `;

    // Insert before the quick-actions-bar
    const quickActionsBar = screenshotPanel.querySelector('.quick-actions-bar');
    if (quickActionsBar) {
        screenshotPanel.insertBefore(navPanel, quickActionsBar);
    } else {
        screenshotPanel.prepend(navPanel);
    }

    // Populate known screens
    populateKnownScreens(wizard);

    // Setup dropdown toggle
    const btnShowScreens = document.getElementById('btnShowScreens');
    const screensList = document.getElementById('navScreensList');

    if (btnShowScreens && screensList) {
        btnShowScreens.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = screensList.classList.toggle('open');
            btnShowScreens.classList.toggle('active');

            // Position dropdown using fixed positioning (escapes overflow:hidden)
            if (isOpen) {
                const btnRect = btnShowScreens.getBoundingClientRect();
                screensList.style.top = `${btnRect.bottom + 4}px`;
                screensList.style.left = `${btnRect.left}px`;

                // Ensure dropdown doesn't go off-screen to the right
                const listRect = screensList.getBoundingClientRect();
                if (listRect.right > window.innerWidth - 10) {
                    screensList.style.left = `${window.innerWidth - listRect.width - 10}px`;
                }
            }
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.nav-screens-dropdown')) {
                screensList.classList.remove('open');
                btnShowScreens.classList.remove('active');
            }
        });
    }

    console.log('[FlowWizard] Navigation context panel initialized');
}

/**
 * Populate the known screens dropdown from navigation graph
 */
function populateKnownScreens(wizard) {
    const screensList = document.getElementById('navScreensList');
    if (!screensList || !wizard.navigationGraph?.screens) return;

    const screens = Object.values(wizard.navigationGraph.screens);

    if (screens.length === 0) {
        screensList.innerHTML = '<div class="nav-screen-item">No screens recorded yet</div>';
        return;
    }

    screensList.innerHTML = screens.map(screen => {
        const activityShort = screen.activity?.split('.').pop() || 'Unknown';
        const displayName = screen.display_name || activityShort;
        const isHome = screen.is_home_screen ? '🏠' : '📱';

        return `
            <div class="nav-screen-item" data-screen-id="${screen.screen_id}" data-activity="${screen.activity || ''}">
                <span class="screen-icon">${isHome}</span>
                <span class="screen-name">${displayName}</span>
                <span class="screen-activity">${activityShort}</span>
            </div>
        `;
    }).join('');

    // Setup click handlers for screen items
    screensList.querySelectorAll('.nav-screen-item').forEach(item => {
        item.addEventListener('click', () => {
            const activity = item.dataset.activity;
            if (activity) {
                console.log('[FlowWizard] Screen selected from nav:', activity);
                // Could navigate to this screen in the future
            }
        });
    });
}

/**
 * Update navigation context with current screen
 * Called when screen info is updated
 */
function getCurrentScreenElements(wizard, elementsOverride = null) {
    if (Array.isArray(elementsOverride)) {
        return elementsOverride;
    }
    if (wizard.captureMode === 'streaming') {
        return wizard.liveStream?.elements || [];
    }
    return wizard.recorder?.screenshotMetadata?.elements || [];
}

function extractUiLandmarks(elements) {
    const landmarks = [];

    for (const el of elements || []) {
        const resourceId = el.resource_id || el['resource-id'] || '';
        const className = el.class || '';
        const text = el.text || '';
        const contentDesc = el.content_desc || el['content-desc'] || '';

        if (!text && !contentDesc) {
            continue;
        }

        const resourceLower = resourceId.toLowerCase();
        const classLower = className.toLowerCase();

        if (resourceLower.includes('toolbar') || resourceLower.includes('action_bar')) {
            landmarks.push({
                type: 'toolbar',
                text: text,
                resource_id: resourceId,
                content_desc: contentDesc
            });
            continue;
        }

        if (resourceLower.includes('tab') || classLower.includes('tablayout')) {
            landmarks.push({
                type: 'tab',
                text: text,
                resource_id: resourceId,
                content_desc: contentDesc
            });
            continue;
        }

        if (className.includes('TextView') && text) {
            if (text.length < 50 && !text.includes('\n')) {
                if (['title', 'header', 'name', 'label'].some((kw) => resourceLower.includes(kw))) {
                    landmarks.push({
                        type: 'title',
                        text: text,
                        resource_id: resourceId,
                        content_desc: contentDesc
                    });
                }
            }
        }
    }

    const seen = new Set();
    const unique = [];
    for (const lm of landmarks) {
        const key = `${lm.text || ''}|${lm.resource_id || ''}|${lm.content_desc || ''}`;
        if (!seen.has(key)) {
            seen.add(key);
            unique.push(lm);
        }
    }

    return unique;
}

async function computeScreenId(activity, elements) {
    if (!activity || !elements || elements.length === 0) {
        return null;
    }

    if (!window.crypto || !window.crypto.subtle || !window.TextEncoder) {
        return null;
    }

    const landmarkStrs = [];
    const landmarks = extractUiLandmarks(elements);

    for (const landmark of landmarks) {
        const text = landmark.text || '';
        const resourceId = landmark.resource_id || '';
        const contentDesc = landmark.content_desc || '';

        if (text) {
            landmarkStrs.push(`text:${text}`);
        } else if (resourceId) {
            landmarkStrs.push(`id:${resourceId}`);
        } else if (contentDesc) {
            landmarkStrs.push(`desc:${contentDesc}`);
        }
    }

    landmarkStrs.sort();
    const hashInput = `${activity}|${landmarkStrs.join(',')}`;

    try {
        const encoder = new TextEncoder();
        const hashBuffer = await window.crypto.subtle.digest('SHA-256', encoder.encode(hashInput));
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        const hex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
        return hex.slice(0, 16);
    } catch (e) {
        console.warn('[FlowWizard] Failed to compute screen id:', e);
        return null;
    }
}

function resolveScreenLabel(wizard, screenSignature, activityName) {
    if (screenSignature && wizard.navigationGraph?.screens?.[screenSignature]) {
        const screen = wizard.navigationGraph.screens[screenSignature];
        return screen.display_name || screen.activity?.split('.').pop() || screenSignature;
    }
    if (activityName) {
        const shortName = activityName.split('.').pop();
        return screenSignature ? `${shortName} (${screenSignature.slice(0, 6)})` : shortName;
    }
    return screenSignature ? screenSignature.slice(0, 6) : 'Unknown';
}

function normalizeScreenLabel(label) {
    if (!label) return null;
    return label.replace(/\s*\([0-9a-fA-F]{4,}\)\s*$/, '').trim();
}

function getActivityShortName(wizard, screenSignature, activityName) {
    if (activityName) {
        return activityName.split('.').pop();
    }
    if (screenSignature && wizard.navigationGraph?.screens?.[screenSignature]?.activity) {
        return wizard.navigationGraph.screens[screenSignature].activity.split('.').pop();
    }
    return null;
}

async function maybeLearnScreen(wizard, activityInfo, elements) {
    if (!wizard.autoLearnScreens) return;
    if (!activityInfo?.activity || !activityInfo?.package) return;
    if (!elements || elements.length === 0) return;

    const signature = await computeScreenId(activityInfo.activity, elements);
    if (!signature) return;

    const now = Date.now();
    const lastSignature = wizard._lastLearnedSignature;
    const lastTime = wizard._lastLearnedAt || 0;

    if (signature === lastSignature && (now - lastTime) < 5000) {
        return;
    }

    wizard._lastLearnedSignature = signature;
    wizard._lastLearnedAt = now;

    const packageName = activityInfo.package || wizard.selectedApp?.package || wizard.selectedApp;
    if (!packageName) return;

    try {
        const response = await fetch(
            `${getApiBase()}/navigation/${encodeURIComponent(packageName)}/screens`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    activity: activityInfo.activity,
                    ui_elements: elements,
                    display_name: activityInfo.activity.split('.').pop()
                })
            }
        );

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            console.warn('[FlowWizard] Screen learn failed:', error.detail || response.statusText);
            return;
        }

        const data = await response.json();
        if (data?.screen?.screen_id) {
            wizard.lastLearnedScreenId = data.screen.screen_id;
        }
        console.log('[FlowWizard] Learned screen:', activityInfo.activity);
    } catch (error) {
        console.warn('[FlowWizard] Screen learn error:', error);
    }
}

export async function updateNavigationContext(wizard, activityInfo, elementsOverride = null) {
    const navCurrentScreen = document.getElementById('navCurrentScreen');
    const navScreenName = document.getElementById('navScreenName');
    const screensList = document.getElementById('navScreensList');

    if (!navCurrentScreen || !navScreenName) return;

    if (!activityInfo?.activity) {
        navCurrentScreen.textContent = '--';
        navScreenName.textContent = 'Unknown screen';
        wizard.currentScreenId = null;
        wizard.currentScreenSignature = null;
        if (wizard.recorder) {
            wizard.recorder.setNavigationContext(null);
            if (wizard.recorder.setScreenSignature) {
                wizard.recorder.setScreenSignature(null);
            }
        }
        return;
    }

    const currentActivity = activityInfo.activity;
    const shortName = currentActivity.split('.').pop();

    // Check if this screen is in our navigation graph
    let screenInfo = null;
    let screenId = null;
    let ambiguousActivity = false;
    const elements = getCurrentScreenElements(wizard, elementsOverride);
    const screenSignature = await computeScreenId(currentActivity, elements);

    if (wizard.navigationGraph?.screens) {
        if (screenSignature && wizard.navigationGraph.screens[screenSignature]) {
            screenInfo = wizard.navigationGraph.screens[screenSignature];
            screenId = screenSignature;
        } else {
            const matches = Object.entries(wizard.navigationGraph.screens)
                .filter(([, screen]) => screen.activity === currentActivity);
            if (matches.length === 1) {
                [screenId, screenInfo] = matches[0];
            } else if (matches.length > 1) {
                ambiguousActivity = true;
            }
        }
    }

    if (screenInfo) {
        const displayName = screenInfo.display_name || shortName;
        const isHome = screenInfo.is_home_screen ? ' 🏠' : '';
        navCurrentScreen.textContent = shortName;
        navScreenName.textContent = `${displayName}${isHome} (known)`;
        navCurrentScreen.style.color = '#4ade80';
        navCurrentScreen.style.borderColor = 'rgba(74, 222, 128, 0.3)';

        // Store current screen ID for use in step recording
        wizard.currentScreenId = screenId;

        // Sync with recorder so new steps include this screen ID
        if (wizard.recorder) {
        wizard.recorder.setNavigationContext(screenId);
    }

        // Highlight current screen in dropdown
        if (screensList) {
            screensList.querySelectorAll('.nav-screen-item').forEach(item => {
                if (screenId) {
                    item.classList.toggle('current', item.dataset.screenId === screenId);
                } else {
                    item.classList.toggle('current', item.dataset.activity === currentActivity);
                }
            });
        }
    } else {
        navCurrentScreen.textContent = shortName;
        navScreenName.textContent = ambiguousActivity
            ? 'Multiple screens detected (need landmarks)'
            : 'New screen (will be learned)';
        navCurrentScreen.style.color = '#fbbf24';
        navCurrentScreen.style.borderColor = 'rgba(251, 191, 36, 0.3)';
        wizard.currentScreenId = null;

        // Clear screen ID on recorder
        if (wizard.recorder) {
            wizard.recorder.setNavigationContext(null);
        }
    }

    wizard.currentScreenSignature = screenSignature || null;
    if (wizard.recorder?.setScreenSignature) {
        wizard.recorder.setScreenSignature(screenSignature || null);
    }
}

/**
 * Phase 1 Screen Awareness: Update current screen info in toolbar
 * Shows the current Android activity name
 */
export async function updateScreenInfo(wizard) {
    const activityEl = document.getElementById('currentActivity');
    if (!activityEl) return;

    try {
        const response = await fetch(`${getApiBase()}/adb/screen/current/${encodeURIComponent(wizard.selectedDevice)}`);
        if (!response.ok) {
            console.warn('[FlowWizard] Failed to get screen info');
            activityEl.textContent = '--';
            return;
        }

        const data = await response.json();
        const activityInfo = data.activity;

        if (activityInfo?.activity) {
            // Show short activity name (e.g., "MainActivity" not full path)
            const shortName = activityInfo.activity.split('.').pop();
            activityEl.textContent = shortName;
            activityEl.title = activityInfo.full_name || activityInfo.activity;
            console.log(`[FlowWizard] Screen: ${shortName} (${activityInfo.package})`);

            // Update navigation context panel if available
            await updateNavigationContext(wizard, activityInfo);
        } else {
            activityEl.textContent = '--';
            await updateNavigationContext(wizard, null);
        }
    } catch (e) {
        console.warn('[FlowWizard] Error updating screen info:', e);
        activityEl.textContent = '--';
        await updateNavigationContext(wizard, null);
    }
}

/**
 * Setup recording UI event listeners
 */
export function setupRecordingUI(wizard) {
    // Setup capture mode toggle (Polling/Streaming)
    setupCaptureMode(wizard);

    // Canvas gesture handlers (mousedown/mouseup for drag detection)
    wizard.canvas.addEventListener('mousedown', (e) => onGestureStart(wizard, e));
    wizard.canvas.addEventListener('mouseup', (e) => onGestureEnd(wizard, e));
    wizard.canvas.addEventListener('mouseleave', () => {
        // Cancel drag if mouse leaves canvas
        if (wizard.isDragging) {
            wizard.isDragging = false;
            wizard.dragStart = null;
        }
    });

    // Touch support for mobile
    wizard.canvas.addEventListener('touchstart', (e) => onGestureStart(wizard, e), { passive: false });
    wizard.canvas.addEventListener('touchend', (e) => onGestureEnd(wizard, e));

    // Listen for zoom changes from gestures (pinch/wheel)
    wizard.canvas.addEventListener('zoomChanged', (e) => {
        wizard.updateZoomDisplay(e.detail.zoom);
    });

    // Setup hover tooltip for element preview
    setupHoverTooltip(wizard);

    // Setup toolbar handlers
    setupToolbarHandlers(wizard);

    // Setup panel toggle (mobile FAB + backdrop)
    setupPanelToggle(wizard);

    // Setup tab switching
    setupPanelTabs(wizard);

    // Setup element tree
    wizard.setupElementTree();

    // Setup overlay filter controls
    setupOverlayFilters(wizard);

    // Done recording button
    document.getElementById('btnDoneRecording')?.addEventListener('click', () => {
        wizard.flowSteps = wizard.recorder.getSteps();
        console.log('Recording complete:', wizard.flowSteps);
        wizard.nextStep();
    });

    // Clear flow button
    document.getElementById('btnClearFlow')?.addEventListener('click', () => {
        if (confirm('Clear all recorded steps?')) {
            wizard.recorder?.clearSteps();
            wizard.updateFlowStepsUI();
        }
    });
}

/**
 * Setup panel tab switching
 */
export function setupPanelTabs(wizard) {
    const tabs = document.querySelectorAll('.panel-tab');
    const tabContents = {
        'elements': document.getElementById('tabElements'),
        'flow': document.getElementById('tabFlow'),
        'suggestions': document.getElementById('tabSuggestions')
    };

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;

            // Update active tab
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Show corresponding content
            Object.entries(tabContents).forEach(([name, content]) => {
                if (content) {
                    content.classList.toggle('active', name === tabName);
                }
            });

            // If switching to suggestions tab, setup if not already done
            if (tabName === 'suggestions' && !wizard._suggestionsTabInitialized) {
                setupSuggestionsTab(wizard);
                wizard._suggestionsTabInitialized = true;
            }
        });
    });

    console.log('[FlowWizard] Panel tabs initialized');
}

/**
 * Switch to a specific tab (elements or flow)
 */
export function switchToTab(wizard, tabName) {
    const tabs = document.querySelectorAll('.panel-tab');
    const tabContents = {
        'elements': document.getElementById('tabElements'),
        'flow': document.getElementById('tabFlow'),
        'suggestions': document.getElementById('tabSuggestions')
    };

    tabs.forEach(tab => {
        const isTarget = tab.dataset.tab === tabName;
        tab.classList.toggle('active', isTarget);
    });

    Object.entries(tabContents).forEach(([name, content]) => {
        if (content) {
            content.classList.toggle('active', name === tabName);
        }
    });
}

/**
 * Setup Quick Actions Toolbar handlers
 */
export function setupToolbarHandlers(wizard) {
    // Refresh button
    document.getElementById('qabRefresh')?.addEventListener('click', async () => {
        const btn = document.getElementById('qabRefresh');
        btn.classList.add('active');
        await wizard.recorder.refresh();
        // Only update screenshot in polling mode - streaming updates automatically
        if (wizard.captureMode !== 'streaming') {
            await wizard.updateScreenshotDisplay();
        }
        btn.classList.remove('active');
    });

    // Back button
    document.getElementById('qabBack')?.addEventListener('click', async () => {
        await wizard.recorder.goBack();
        // Only update screenshot in polling mode - streaming updates automatically
        if (wizard.captureMode !== 'streaming') {
            wizard.updateScreenshotDisplay();
        }
        refreshAfterAction(wizard, 600);
    });

    // Home button
    document.getElementById('qabHome')?.addEventListener('click', async () => {
        await wizard.recorder.goHome();
        // Only update screenshot in polling mode - streaming updates automatically
        if (wizard.captureMode !== 'streaming') {
            wizard.updateScreenshotDisplay();
        }
        refreshAfterAction(wizard, 600);
    });

    // Zoom controls
    document.getElementById('qabZoomOut')?.addEventListener('click', () => wizard.zoomOut());
    document.getElementById('qabZoomIn')?.addEventListener('click', () => wizard.zoomIn());
    document.getElementById('qabFit')?.addEventListener('click', () => wizard.fitToScreen());
    document.getElementById('qabScale')?.addEventListener('click', () => wizard.toggleScale());

    // Recording toggle - pause/resume action recording
    document.getElementById('qabRecordToggle')?.addEventListener('click', () => wizard.toggleRecording());

    // Pull-to-refresh button - sends swipe down gesture to Android app (recordable)
    document.getElementById('qabPullRefresh')?.addEventListener('click', async () => {
        const btn = document.getElementById('qabPullRefresh');
        btn.classList.add('active');

        try {
            showToast('Sending pull-to-refresh...', 'info', 1500);

            // Use recorder's pullRefresh method which adds it as a flow step
            await wizard.recorder.pullRefresh();

            // Wait for app to refresh, then update screenshot
            refreshAfterAction(wizard, 800);

            showToast('App refreshed! (Added to flow)', 'success', 1500);
        } catch (error) {
            console.error('[FlowWizard] Pull-to-refresh failed:', error);
            showToast(`Refresh failed: ${error.message}`, 'error');
        } finally {
            btn.classList.remove('active');
        }
    });

    // Retry button - shown when screen_changed detected, allows manual retry
    document.getElementById('qabRetry')?.addEventListener('click', async () => {
        const btn = document.getElementById('qabRetry');
        btn.classList.add('active');

        try {
            showToast('Retrying capture...', 'info', 1500);
            // Reset retry counter
            wizard._screenChangedRetryCount = 0;
            // Hide the retry button
            btn.style.display = 'none';
            // Clear elements and refresh
            clearAllElementsAndHover(wizard);
            await wizard.recorder.refresh();
            if (wizard.captureMode !== 'streaming') {
                await wizard.updateScreenshotDisplay();
            }
            await refreshElements(wizard);
        } catch (error) {
            console.error('[FlowWizard] Retry failed:', error);
            showToast(`Retry failed: ${error.message}`, 'error');
        } finally {
            btn.classList.remove('active');
        }
    });

    // Restart app button - force stop and relaunch (for apps without pull-to-refresh)
    document.getElementById('qabRestartApp')?.addEventListener('click', async () => {
        const btn = document.getElementById('qabRestartApp');
        btn.classList.add('active');

        try {
            showToast('Restarting app...', 'info', 2000);

            // Use recorder's restartApp method which adds it as a flow step
            await wizard.recorder.restartApp();

            // Wait for app to fully restart, then update screenshot
            refreshAfterAction(wizard, 2000);

            showToast('App restarted! (Added to flow)', 'success', 1500);
        } catch (error) {
            console.error('[FlowWizard] Restart app failed:', error);
            showToast(`Restart failed: ${error.message}`, 'error');
        } finally {
            btn.classList.remove('active');
        }
    });

    // Stitch capture button
    document.getElementById('qabStitch')?.addEventListener('click', async () => {
        const btn = document.getElementById('qabStitch');
        btn.classList.add('active');
        showToast('Starting stitch capture... This may take 30-60 seconds', 'info', 3000);

        try {
            await wizard.recorder.stitchCapture();
            wizard.updateScreenshotDisplay();
            showToast('Stitch capture complete!', 'success', 2000);
        } catch (error) {
            showToast(`Stitch capture failed: ${error.message}`, 'error', 3000);
        } finally {
            btn.classList.remove('active');
        }
    });

    // Overlay settings toggle
    document.getElementById('qabOverlay')?.addEventListener('click', () => {
        const settings = document.getElementById('overlaySettings');
        const btn = document.getElementById('qabOverlay');
        if (settings) {
            const isVisible = settings.style.display !== 'none';
            settings.style.display = isVisible ? 'none' : 'flex';
            btn?.classList.toggle('active', !isVisible);
        }
    });

    // Insert Existing Sensor button
    document.getElementById('qabInsertSensor')?.addEventListener('click', async () => {
        if (!wizard.recorder) {
            showToast('Start recording first (Step 3)', 'warning', 2000);
            return;
        }
        await Dialogs.showInsertSensorDialog(wizard);
    });

    // Insert Existing Action button
    document.getElementById('qabInsertAction')?.addEventListener('click', async () => {
        if (!wizard.recorder) {
            showToast('Start recording first (Step 3)', 'warning', 2000);
            return;
        }
        await Dialogs.showInsertActionDialog(wizard);
    });

    // Wait/Delay button
    document.getElementById('qabWait')?.addEventListener('click', async () => {
        if (!wizard.recorder) {
            showToast('Start recording first (Step 3)', 'warning', 2000);
            return;
        }
        await Dialogs.addWaitStep(wizard);
    });

    // Reconnect stream button
    document.getElementById('qabReconnect')?.addEventListener('click', () => {
        reconnectStream(wizard);
    });

    // Panel toggle button (desktop)
    document.getElementById('qabPanel')?.addEventListener('click', () => {
        toggleRightPanel(wizard);
    });

    console.log('[FlowWizard] Toolbar handlers initialized');
}

/**
 * Setup panel toggle for mobile (FAB + backdrop)
 */
export function setupPanelToggle(wizard) {
    const fab = document.getElementById('panelToggleFab');
    const backdrop = document.getElementById('panelBackdrop');
    const rightPanel = document.getElementById('rightPanel');

    fab?.addEventListener('click', () => {
        rightPanel?.classList.toggle('open');
        backdrop?.classList.toggle('visible');
    });

    backdrop?.addEventListener('click', () => {
        rightPanel?.classList.remove('open');
        backdrop?.classList.remove('visible');
    });

    console.log('[FlowWizard] Panel toggle initialized');
}

/**
 * Toggle right panel visibility (for desktop)
 */
export function toggleRightPanel(wizard) {
    const rightPanel = document.getElementById('rightPanel');
    const btn = document.getElementById('qabPanel');

    if (rightPanel) {
        const isHidden = rightPanel.style.display === 'none';
        rightPanel.style.display = isHidden ? 'flex' : 'none';
        btn?.classList.toggle('active', isHidden);
    }
}

/**
 * Setup overlay filter controls
 */
export function setupOverlayFilters(wizard) {
    const filterIds = {
        showClickable: 'filterClickable',
        showNonClickable: 'filterNonClickable',
        showTextLabels: 'filterTextLabels',
        hideSmall: 'filterMinSize',
        hideDividers: 'filterDividers',
        hideContainers: 'filterContainers',
        hideEmptyElements: 'filterEmptyElements'
    };

    Object.entries(filterIds).forEach(([filterName, elementId]) => {
        const checkbox = document.getElementById(elementId);
        if (!checkbox) {
            console.warn(`[FlowWizard] Filter checkbox not found: ${elementId}`);
            return;
        }

        checkbox.addEventListener('change', () => {
            wizard.overlayFilters[filterName] = checkbox.checked;
            // Update canvas renderer filters
            if (wizard.canvasRenderer) {
                wizard.canvasRenderer.setOverlayFilters(wizard.overlayFilters);
            }
            console.log(`[FlowWizard] ${filterName} = ${checkbox.checked}`);

            // Only refresh display in polling mode WITH valid screenshot data
            if (wizard.captureMode === 'streaming') {
                // Streaming mode: update all LiveStream overlay settings
                if (wizard.liveStream) {
                    wizard.liveStream.setOverlaysVisible(
                        wizard.overlayFilters.showClickable || wizard.overlayFilters.showNonClickable
                    );
                    wizard.liveStream.setShowClickable(wizard.overlayFilters.showClickable);
                    wizard.liveStream.setShowNonClickable(wizard.overlayFilters.showNonClickable);
                    wizard.liveStream.setTextLabelsVisible(wizard.overlayFilters.showTextLabels);
                    wizard.liveStream.setHideContainers(wizard.overlayFilters.hideContainers);
                    wizard.liveStream.setHideEmptyElements(wizard.overlayFilters.hideEmptyElements);
                    wizard.liveStream.setHideSmall(wizard.overlayFilters.hideSmall);
                    wizard.liveStream.setHideDividers(wizard.overlayFilters.hideDividers);
                }
            } else if (wizard.recorder?.currentScreenshot) {
                // Polling mode: only redraw if we have valid screenshot data
                wizard.updateScreenshotDisplay();
            }
        });

        // Set initial state
        checkbox.checked = wizard.overlayFilters[filterName];
    });

    // Setup refresh interval dropdown
    const refreshSelect = document.getElementById('elementRefreshInterval');
    if (refreshSelect) {
        refreshSelect.addEventListener('change', () => {
            const newInterval = parseInt(refreshSelect.value);
            console.log(`[FlowWizard] Refresh interval changed to ${newInterval / 1000}s`);

            // Restart auto-refresh with new interval if streaming
            if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
                startElementAutoRefresh(wizard);
            }
        });
    }

    const learnCheckbox = document.getElementById('autoLearnScreens');
    if (learnCheckbox) {
        const savedLearn = localStorage.getItem('flowWizard.autoLearnScreens');
        wizard.autoLearnScreens = savedLearn === null ? true : savedLearn === 'true';
        learnCheckbox.checked = wizard.autoLearnScreens;
        learnCheckbox.addEventListener('change', () => {
            wizard.autoLearnScreens = learnCheckbox.checked;
            localStorage.setItem('flowWizard.autoLearnScreens', String(wizard.autoLearnScreens));
            console.log(`[FlowWizard] autoLearnScreens = ${wizard.autoLearnScreens}`);
        });
    } else {
        wizard.autoLearnScreens = true;
    }

    console.log('[FlowWizard] Overlay filters initialized');
}

/**
 * Setup capture mode toggle (Polling vs Streaming)
 */
export function setupCaptureMode(wizard) {
    const captureModeSelect = document.getElementById('captureMode');
    const streamModeSelect = document.getElementById('streamMode');
    const qualitySelect = document.getElementById('streamQuality');

    // Load saved preferences from localStorage
    const savedMode = localStorage.getItem('flowWizard.captureMode') || 'polling';
    const savedStreamMode = localStorage.getItem('flowWizard.streamMode') || 'mjpeg';
    const savedQuality = localStorage.getItem('flowWizard.streamQuality') || 'fast';

    // Handle capture mode change (select dropdown)
    if (captureModeSelect) {
        captureModeSelect.value = savedMode;
        // Don't await here - initialization continues, mode will be set
        setCaptureMode(wizard, savedMode);

        captureModeSelect.addEventListener('change', async (e) => {
            const mode = e.target.value;
            localStorage.setItem('flowWizard.captureMode', mode);
            await setCaptureMode(wizard, mode);
        });
    }

    // Handle stream mode change (mjpeg vs websocket)
    if (streamModeSelect) {
        streamModeSelect.value = savedStreamMode;
        wizard.streamMode = savedStreamMode;

        streamModeSelect.addEventListener('change', async (e) => {
            wizard.streamMode = e.target.value;
            localStorage.setItem('flowWizard.streamMode', e.target.value);
            // If streaming, restart with new mode (await to prevent overlapping stop/start)
            if (wizard.captureMode === 'streaming' && wizard.liveStream?.isStreaming) {
                await startStreaming(wizard);
            }
        });
    }

    // Handle quality change
    if (qualitySelect) {
        qualitySelect.value = savedQuality;
        wizard.streamQuality = savedQuality;

        qualitySelect.addEventListener('change', async (e) => {
            wizard.streamQuality = e.target.value;
            localStorage.setItem('flowWizard.streamQuality', e.target.value);
            // If streaming, restart with new quality (await to prevent overlapping stop/start)
            if (wizard.captureMode === 'streaming' && wizard.liveStream?.isStreaming) {
                await startStreaming(wizard);
            }
        });
    }

    console.log('[FlowWizard] Capture mode controls initialized');
}

/**
 * Set capture mode (polling or streaming)
 */
export async function setCaptureMode(wizard, mode) {
    const streamModeSelect = document.getElementById('streamMode');
    const qualitySelect = document.getElementById('streamQuality');

    // Get buttons that are mode-specific
    const refreshBtn = document.getElementById('qabRefresh');
    const stitchBtn = document.getElementById('qabStitch');
    const zoomOutBtn = document.getElementById('qabZoomOut');
    const zoomInBtn = document.getElementById('qabZoomIn');
    const scaleBtn = document.getElementById('qabScale');

    // Toggle visibility of mode-specific buttons using CSS classes
    const pollingButtons = document.querySelectorAll('.capture-mode-polling');
    const streamingButtons = document.querySelectorAll('.capture-mode-streaming');

    pollingButtons.forEach(btn => {
        btn.style.display = mode === 'polling' ? '' : 'none';
    });
    streamingButtons.forEach(btn => {
        btn.style.display = mode === 'streaming' ? '' : 'none';
    });

    if (mode === 'streaming') {
        wizard.captureMode = 'streaming';
        if (streamModeSelect) streamModeSelect.disabled = false;
        if (qualitySelect) qualitySelect.disabled = false;

        // Disable polling-only buttons in streaming mode
        if (refreshBtn) {
            refreshBtn.disabled = true;
            refreshBtn.title = 'Refresh not available in streaming mode';
        }
        if (stitchBtn) {
            stitchBtn.disabled = true;
            stitchBtn.title = 'Stitch not available in streaming mode';
        }
        // Zoom controls work in streaming mode

        await startStreaming(wizard);
    } else {
        wizard.captureMode = 'polling';
        if (streamModeSelect) streamModeSelect.disabled = true;
        if (qualitySelect) qualitySelect.disabled = true;

        // Enable polling buttons
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.title = 'Refresh Screen';
        }
        if (stitchBtn) {
            stitchBtn.disabled = false;
            stitchBtn.title = 'Full Page Capture';
        }

        await stopStreaming(wizard);
    }

    console.log(`[FlowWizard] Capture mode: ${mode}`);
}

/**
 * Prepare device for streaming - check lock, wake screen, unlock if needed
 * Shows a status dialog keeping user informed
 */
async function prepareDeviceForStreaming(wizard) {
    return new Promise((resolve) => {
        // Create preparation dialog
        const dialog = document.createElement('div');
        dialog.className = 'dialog-overlay device-prep-dialog-overlay';
        dialog.innerHTML = `
            <div class="dialog device-prep-dialog">
                <div class="dialog-header">
                    <h3>Preparing Device</h3>
                </div>
                <div class="dialog-body">
                    <div class="prep-status">
                        <div class="prep-spinner"></div>
                        <div class="prep-message" id="prepMessage">Checking device state...</div>
                    </div>
                    <div class="prep-steps">
                        <div class="prep-step" id="step-screen">
                            <span class="step-icon">⏳</span>
                            <span class="step-text">Check screen state</span>
                        </div>
                        <div class="prep-step" id="step-wake">
                            <span class="step-icon">⏳</span>
                            <span class="step-text">Wake screen if needed</span>
                        </div>
                        <div class="prep-step" id="step-unlock">
                            <span class="step-icon">⏳</span>
                            <span class="step-text">Unlock device</span>
                        </div>
                        <div class="prep-step" id="step-connect">
                            <span class="step-icon">⏳</span>
                            <span class="step-text">Connect to stream</span>
                        </div>
                    </div>
                </div>
                <div class="dialog-footer">
                    <button class="btn btn-secondary" id="prepCancel">Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(dialog);

        const messageEl = dialog.querySelector('#prepMessage');
        const cancelBtn = dialog.querySelector('#prepCancel');
        let cancelled = false;

        const updateStep = (stepId, status) => {
            const step = dialog.querySelector(`#${stepId}`);
            if (step) {
                const icon = step.querySelector('.step-icon');
                if (status === 'done') icon.textContent = '✅';
                else if (status === 'fail') icon.textContent = '❌';
                else if (status === 'skip') icon.textContent = '⏭️';
                else if (status === 'working') icon.textContent = '🔄';
            }
        };

        const cleanup = () => {
            dialog.remove();
        };

        cancelBtn.addEventListener('click', () => {
            cancelled = true;
            cleanup();
            resolve(false);
        });

        // Run preparation sequence using shared unlock module
        (async () => {
            try {
                const apiBase = wizard.recorder?.apiBase || getApiBase();

                // Use shared unlock module with wizard-style callbacks
                const unlockResult = await sharedEnsureUnlocked(wizard.selectedDevice, apiBase, {
                    onStatus: (msg) => {
                        messageEl.textContent = msg;
                    },
                    onStepUpdate: (stepId, status) => {
                        updateStep(stepId, status);
                    },
                    onNeedsManualUnlock: async () => {
                        // Change cancel button to continue
                        cancelBtn.textContent = 'Continue Anyway';
                        cancelBtn.className = 'btn btn-primary';

                        // Wait for user to click continue
                        await new Promise(resolveWait => {
                            cancelBtn.onclick = () => {
                                resolveWait();
                            };
                        });
                    },
                    isCancelled: () => cancelled
                });

                if (cancelled) return;

                // Step 4: Preload screenshot in background while finishing up
                updateStep('step-connect', 'working');
                messageEl.textContent = 'Loading first frame...';

                // Fetch screenshot to preload (don't wait too long)
                try {
                    const abortController = new AbortController();
                    const timeoutId = setTimeout(() => abortController.abort(), 3000);

                    const response = await fetch(`${apiBase}/adb/screenshot`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ device_id: wizard.selectedDevice, quick: false }),
                        signal: abortController.signal
                    });

                    clearTimeout(timeoutId);

                    if (response && response.ok) {
                        const data = await response.json();
                        if (data.screenshot) {
                            // Preload the image
                            wizard._preloadedImage = data.screenshot;
                            wizard._preloadedElements = data.elements || [];
                            console.log('[FlowWizard] Preloaded screenshot with', wizard._preloadedElements.length, 'elements');
                        }
                    }
                } catch (e) {
                    if (e.name === 'AbortError') {
                        console.log('[FlowWizard] Screenshot preload timed out');
                    } else {
                        console.log('[FlowWizard] Screenshot preload skipped:', e);
                    }
                }

                updateStep('step-connect', 'done');
                messageEl.textContent = 'Device ready! Starting stream...';
                await new Promise(r => setTimeout(r, 300));

                cleanup();
                resolve(true);

            } catch (error) {
                console.error('[FlowWizard] Device preparation error:', error);
                messageEl.textContent = 'Error preparing device, continuing anyway...';
                await new Promise(r => setTimeout(r, 1500));
                cleanup();
                resolve(true);
            }
        })();
    });
}

/**
 * Start live streaming with device preparation
 */
export async function startStreaming(wizard) {
    if (!wizard.selectedDevice) {
        showToast('No device selected', 'error');
        return;
    }

    setSetupStatus(wizard, 'Connecting to live stream...');

    // Check for companion app (non-blocking - will be available by first refresh)
    // This enables fast element fetching when companion app is installed
    checkCompanionAppStatus(wizard, wizard.selectedDevice);

    // Reset stream session flags
    wizard._streamLoadingHidden = false;
    wizard._streamConnectedOnce = false;

    // Clear any existing loading timeout
    if (wizard._streamLoadingTimeout) {
        clearTimeout(wizard._streamLoadingTimeout);
        wizard._streamLoadingTimeout = null;
    }

    // NOTE: Device unlock now happens at start of loadStep3 (before UI setup)
    // Skip prepareDeviceForStreaming dialog since device is already unlocked
    // This eliminates the redundant "Preparing Device" dialog

    // Show loading indicator (or preloaded image if available)
    if (wizard._preloadedImage) {
        // Display preloaded image immediately
        console.log('[FlowWizard] Using preloaded image');
        const img = new Image();
        img.onload = () => {
            wizard.canvas.width = img.width;
            wizard.canvas.height = img.height;
            console.log(`[FlowWizard] Preloaded image dimensions: ${img.width}x${img.height}`);
            const ctx = wizard.canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            wizard.hideLoadingOverlay();
            // Defer applyZoom until after browser layout settles
            // Use double requestAnimationFrame for more reliable timing
            if (wizard.canvasRenderer) {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        wizard.canvasRenderer.applyZoom();
                    });
                });
            }
        };
        img.src = 'data:image/jpeg;base64,' + wizard._preloadedImage;

        // Use preloaded elements
        if (wizard._preloadedElements && wizard._preloadedElements.length > 0) {
            if (wizard.liveStream) {
                wizard.liveStream.elements = wizard._preloadedElements;
            }
            wizard.recorder.screenshotMetadata = { elements: wizard._preloadedElements };
            drawElementOverlays(wizard);
        }

        // Clear preloaded data
        wizard._preloadedImage = null;
        wizard._preloadedElements = null;
    } else {
        wizard.showLoadingOverlay('Connecting...');

        // Set timeout to hide loading overlay if no frames arrive within 10s
        wizard._streamLoadingTimeout = setTimeout(() => {
            if (!wizard._streamLoadingHidden) {
                wizard.hideLoadingOverlay();
                wizard._streamLoadingHidden = true;
                showToast('No frames received - check device connection', 'warning', 5000);
                console.warn('[FlowWizard] Stream timeout - no frames received after 10s');
            }
        }, 10000);
    }

    // NOTE: Removed duplicate refreshElements call here - onConnect already calls it
    // This prevents race conditions and duplicate API calls

    // Stop any existing stream - MUST await to prevent WebSocket race condition
    await stopStreaming(wizard);

    // Always create a fresh LiveStream to ensure it's bound to current canvas
    // Previous bug: reusing old LiveStream that was bound to stale canvas element
    if (wizard.liveStream) {
        wizard.liveStream = null;
    }
    wizard.liveStream = new LiveStream(wizard.canvas);
    console.log('[FlowWizard] Created new LiveStream for canvas:', wizard.canvas);

    // Handle each frame - hide loading overlay and apply zoom (once per stream)
    wizard.liveStream.onFrame = (data) => {
        // Only process once per stream session
        if (!wizard._streamLoadingHidden) {
            wizard._streamLoadingHidden = true;
            wizard.hideLoadingOverlay();

            // Clear any loading timeout since we got a frame
            if (wizard._streamLoadingTimeout) {
                clearTimeout(wizard._streamLoadingTimeout);
                wizard._streamLoadingTimeout = null;
            }

            // CRITICAL: Apply zoom after browser has finished layout
            if (wizard.canvasRenderer) {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        wizard.canvasRenderer.applyZoom();
                    });
                });
            }

            setSetupStatusReady(wizard);
        }
    };

    // Wire up callbacks
    wizard.liveStream.onConnect = () => {
        updateStreamStatus(wizard, 'connected', 'Live');

        // Don't show loading overlay here - it's already shown at startStreaming()
        // Only show toast on first connect
        if (!wizard._streamConnectedOnce) {
            wizard._streamConnectedOnce = true;
            showToast('Streaming started', 'success', 2000);
        }

        // Fetch elements and start auto-refresh
        refreshElements(wizard);
        startElementAutoRefresh(wizard);
        startKeepAwake(wizard);
    };

    // Setup ResizeObserver to apply zoom when canvas dimensions change (debounced)
    if (!wizard._canvasResizeObserver && wizard.canvas) {
        let resizeTimeout = null;
        wizard._canvasResizeObserver = new ResizeObserver(() => {
            if (wizard.canvasRenderer && wizard.captureMode === 'streaming') {
                // Debounce: only apply zoom after resize stops for 100ms
                if (resizeTimeout) clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(() => {
                    wizard.canvasRenderer.applyZoom();
                }, 100);
            }
        });
        wizard._canvasResizeObserver.observe(wizard.canvas);
    }

    wizard.liveStream.onDisconnect = () => {
        updateStreamStatus(wizard, 'disconnected', 'Offline');
        showToast('Device disconnected', 'warning', 3000);
    };

    wizard.liveStream.onConnectionStateChange = (state, attempts) => {
        switch (state) {
            case 'connecting':
                updateStreamStatus(wizard, 'connecting', 'Connecting...');
                break;
            case 'reconnecting':
                updateStreamStatus(wizard, 'reconnecting', `Retry ${attempts}...`);
                if (attempts === 1) {
                    showToast('Connection lost, reconnecting...', 'warning', 3000);
                }
                break;
            case 'connected':
                updateStreamStatus(wizard, 'connected', 'Live');
                break;
            case 'disconnected':
                updateStreamStatus(wizard, 'disconnected', 'Offline');
                if (attempts >= 10) {
                    showToast('Device connection failed after 10 attempts', 'error', 5000);
                }
                break;
        }
    };

    wizard.liveStream.onError = (error) => {
        console.error('[FlowWizard] Stream error:', error);
        setSetupStatus(wizard, 'Stream error - check device connection', 'error');
        showToast(`Stream error: ${error.message || 'Connection failed'}`, 'error', 3000);
    };

    // Show FPS and capture time in status
    wizard.liveStream.onMetricsUpdate = (metrics) => {
        if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
            const captureTime = metrics.captureTime || 0;
            let quality = 'connected';
            let statusText = `${metrics.fps} FPS`;

            if (captureTime > 0) {
                statusText = `${metrics.fps} FPS (${captureTime}ms)`;
                if (captureTime > 1000) {
                    quality = 'slow';
                } else if (captureTime > 500) {
                    quality = 'ok';
                } else {
                    quality = 'good';
                }
            }

            updateStreamStatus(wizard, quality, statusText);

            if (captureTime > 2000 && !wizard._slowConnectionWarned) {
                wizard._slowConnectionWarned = true;
                showToast('Slow connection - try USB for better performance', 'warning', 5000);
            }
        }
    };

    // Apply current overlay settings
    wizard.liveStream.setOverlaysVisible(wizard.overlayFilters.showClickable || wizard.overlayFilters.showNonClickable);
    wizard.liveStream.setShowClickable(wizard.overlayFilters.showClickable);
    wizard.liveStream.setShowNonClickable(wizard.overlayFilters.showNonClickable);
    wizard.liveStream.setTextLabelsVisible(wizard.overlayFilters.showTextLabels);
    wizard.liveStream.setHideContainers(wizard.overlayFilters.hideContainers);
    wizard.liveStream.setHideEmptyElements(wizard.overlayFilters.hideEmptyElements);
    wizard.liveStream.setHideSmall(wizard.overlayFilters.hideSmall);
    wizard.liveStream.setHideDividers(wizard.overlayFilters.hideDividers);

    // Start streaming with MJPEG or WebSocket mode
    wizard.liveStream.start(wizard.selectedDevice, wizard.streamMode, wizard.streamQuality);
    updateStreamStatus(wizard, 'connecting', 'Connecting...');
}

/**
 * Stop live streaming
 * IMPORTANT: This is async - must be awaited to prevent race conditions with start
 */
export async function stopStreaming(wizard) {
    // Stop element auto-refresh
    stopElementAutoRefresh(wizard);

    // Stop keep-awake
    stopKeepAwake(wizard);

    // Clear loading timeout
    if (wizard._streamLoadingTimeout) {
        clearTimeout(wizard._streamLoadingTimeout);
        wizard._streamLoadingTimeout = null;
    }

    // Stop LiveStream if active - MUST await to prevent race condition
    if (wizard.liveStream) {
        await wizard.liveStream.stop();
    }

    updateStreamStatus(wizard, '', '');
}

/**
 * Reconnect the stream (stop and restart)
 * Resets slow connection warning flag
 */
export async function reconnectStream(wizard) {
    if (wizard.captureMode !== 'streaming') {
        showToast('Not in streaming mode', 'info', 2000);
        return;
    }

    showToast('Reconnecting stream...', 'info', 2000);

    // Reset slow connection warning
    wizard._slowConnectionWarned = false;

    // Stop the stream and wait for it to fully stop
    await stopStreaming(wizard);

    // Small delay before reconnecting to ensure WebSocket is fully closed
    await new Promise(resolve => setTimeout(resolve, 300));

    // Start the new stream
    await startStreaming(wizard);
}

/**
 * Start element auto-refresh (for streaming mode)
 * Uses SMART refresh: detects screen changes and refreshes automatically
 * Falls back to interval-based refresh when screens are static
 */
export function startElementAutoRefresh(wizard) {
    // Clear any existing interval
    stopElementAutoRefresh(wizard);

    // Get configurable interval from dropdown (default 5000ms when smart refresh is enabled)
    const intervalSelect = document.getElementById('elementRefreshInterval');
    const intervalMs = intervalSelect ? parseInt(intervalSelect.value) : 5000;

    // Track last frame time for debouncing
    wizard._lastFrameTime = performance.now();

    // SMART REFRESH: Hook into LiveStream's screen change detection
    // This fires when the screen changes and then stabilizes (3 stable frames)
    if (wizard.liveStream) {
        console.log('[FlowWizard] Setting up smart refresh callback');
        wizard.liveStream.onScreenChange = () => {
            if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
                console.log('[FlowWizard] Smart refresh triggered');
                refreshElements(wizard);
            }
        };
        // Note: onElementsCleared callback removed - was causing element flicker
        // LiveStream's autoHideStaleElements now handles not drawing stale overlays
        // and new elements replace old ones atomically in refreshElements
    } else {
        console.warn('[FlowWizard] No liveStream - smart refresh not available');
    }

    // Wrap original onFrame to track frame times
    const originalOnFrame = wizard.liveStream?.onFrame;
    if (wizard.liveStream) {
        wizard.liveStream.onFrame = (data) => {
            wizard._lastFrameTime = performance.now();
            if (originalOnFrame) originalOnFrame(data);
        };
    }

    // FALLBACK: Interval-based refresh for static screens
    // Runs less frequently since smart refresh handles screen changes
    wizard.elementRefreshIntervalTimer = setInterval(() => {
        if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
            // Skip if a frame arrived recently (streaming active)
            const timeSinceFrame = performance.now() - (wizard._lastFrameTime || 0);
            if (timeSinceFrame < 200) {
                return; // Skip silently - frame just arrived, elements are fresh
            }
            // Fallback refresh for static screens (no smart refresh triggered recently)
            refreshElements(wizard);
        }
    }, intervalMs);

    console.log(`[FlowWizard] Smart element refresh enabled (fallback: ${intervalMs / 1000}s interval)`);
}

/**
 * Stop periodic element auto-refresh
 */
export function stopElementAutoRefresh(wizard) {
    if (wizard.elementRefreshIntervalTimer) {
        clearInterval(wizard.elementRefreshIntervalTimer);
        wizard.elementRefreshIntervalTimer = null;
    }
    // Clear smart refresh callbacks
    if (wizard.liveStream) {
        wizard.liveStream.onScreenChange = null;
        wizard.liveStream.onElementsCleared = null;
    }
    console.log('[FlowWizard] Element auto-refresh stopped');
}

/**
 * Start keep-awake interval to prevent device screen timeout
 * Uses shared device-unlock.js module with 5 second interval
 * MUST be awaited to ensure first wake signal is sent before continuing
 */
export async function startKeepAwake(wizard) {
    // Clear any existing interval
    stopKeepAwake(wizard);

    if (!wizard.selectedDevice) return;

    // Use shared module - await to ensure first wake signal is sent
    // Uses default 5 second interval from shared module
    wizard._keepAwakeInterval = await sharedStartKeepAwake(
        wizard.selectedDevice,
        getApiBase()
        // No interval arg - uses DEFAULT_KEEP_AWAKE_INTERVAL (5s)
    );

    console.log('[FlowWizard] Keep-awake started (5s interval via shared module)');
}

/**
 * Stop keep-awake interval
 */
export function stopKeepAwake(wizard) {
    if (wizard._keepAwakeInterval) {
        sharedStopKeepAwake(wizard._keepAwakeInterval);
        wizard._keepAwakeInterval = null;
        console.log('[FlowWizard] Keep-awake stopped');
    }
}

/**
 * Update stream status display
 */
export function updateStreamStatus(wizard, className, text) {
    const statusEl = document.getElementById('connectionStatus');
    if (statusEl) {
        statusEl.className = `connection-status ${className}`;
        statusEl.textContent = text;
    }
}

/**
 * Refresh elements in background
 * In streaming mode: uses fast elements-only endpoint
 * In polling mode: fetches full screenshot with elements
 */
export async function refreshElements(wizard) {
    if (!wizard.selectedDevice) return;

    // Guard against concurrent refreshElements calls (prevents race conditions)
    if (wizard._refreshingElements) {
        // Throttle log message to once every 10s to reduce noise
        const now = Date.now();
        if (!wizard._lastSkipLog || now - wizard._lastSkipLog > 10000) {
            console.log('[FlowWizard] refreshElements in progress, skipping (this message throttled)');
            wizard._lastSkipLog = now;
        }
        return;
    }
    wizard._refreshingElements = true;

    // Show refresh indicator to give user feedback
    const refreshIndicator = document.getElementById('elementsRefreshIndicator');
    if (refreshIndicator) {
        refreshIndicator.classList.remove('hidden');
    }

    // Safety net: auto-reset guard after 15 seconds in case of hung API call
    const guardTimeout = setTimeout(() => {
        if (wizard._refreshingElements) {
            console.warn('[FlowWizard] refreshElements guard timeout - resetting');
            wizard._refreshingElements = false;
            // Hide indicator on timeout
            if (refreshIndicator) refreshIndicator.classList.add('hidden');
        }
    }, 15000);

    try {
        let elements = [];
        let currentPackage = null;

        if (wizard.captureMode === 'streaming') {
            // Choose fast companion app path or ADB fallback
            let data = null;
            let currentActivity = null;

            if (wizard._hasCompanionApp) {
                // Fast path: Companion app via MQTT (100-300ms)
                try {
                    const startTime = performance.now();
                    const response = await fetch(`${getApiBase()}/companion/ui-tree`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            device_id: wizard.selectedDevice,
                            timeout: 5.0
                        })
                    });

                    if (response.ok) {
                        const companionData = await response.json();
                        if (companionData.success) {
                            const elapsed = Math.round(performance.now() - startTime);
                            // Only log timing occasionally to reduce noise
                            if (!wizard._lastCompanionLogTime || Date.now() - wizard._lastCompanionLogTime > 30000) {
                                console.log(`[FlowWizard] Companion app elements: ${companionData.element_count} in ${elapsed}ms`);
                                wizard._lastCompanionLogTime = Date.now();
                            }

                            // Flatten companion elements (they come nested with children)
                            elements = flattenCompanionElements(companionData.elements || []);
                            currentPackage = companionData.package;
                            currentActivity = companionData.activity;
                            data = {
                                elements,
                                current_package: currentPackage,
                                current_activity: currentActivity,
                                // Companion doesn't provide device dimensions, keep existing
                                device_width: wizard.liveStream?.deviceWidth,
                                device_height: wizard.liveStream?.deviceHeight
                            };
                        } else {
                            throw new Error(companionData.error || 'Companion returned unsuccessful');
                        }
                    } else if (response.status === 400) {
                        // Companion app not registered anymore - disable and fall back
                        console.log('[FlowWizard] Companion app disconnected, falling back to ADB');
                        wizard._hasCompanionApp = false;
                    }
                } catch (err) {
                    // Companion failed, will fall back to ADB below
                    if (!wizard._companionErrorLogged) {
                        console.warn('[FlowWizard] Companion app error, falling back to ADB:', err.message);
                        wizard._companionErrorLogged = true;
                    }
                }
            }

            // Fallback: ADB uiautomator (1-3 seconds)
            if (!data) {
                const response = await fetch(`${getApiBase()}/adb/elements/${encodeURIComponent(wizard.selectedDevice)}`);
                if (!response.ok) return;

                data = await response.json();
                elements = data.elements || [];
                currentPackage = data.current_package;
                currentActivity = data.current_activity;
            }

            // Detect app/screen change for logging (staleness handled by LiveStream)
            const packageChanged = currentPackage && wizard.currentElementsPackage &&
                currentPackage !== wizard.currentElementsPackage;
            const activityChanged = currentActivity && wizard.currentElementsActivity &&
                currentActivity !== wizard.currentElementsActivity;

            if (packageChanged || activityChanged) {
                const changeType = packageChanged ? 'App' : 'Screen';
                const from = packageChanged ? wizard.currentElementsPackage : wizard.currentElementsActivity;
                const to = packageChanged ? currentPackage : currentActivity;
                console.log(`[FlowWizard] ${changeType} changed: ${from} → ${to}`);
                // NOTE: Don't clear elements here - LiveStream's autoHideStaleElements handles
                // not drawing stale overlays. New elements will replace old ones atomically
                // below at _renderFrame call. This prevents show->hide->show flicker.
                // Just clear hover state since element coordinates won't match new screen
                clearHoverHighlight(wizard);
                wizard.hoveredElement = null;
            }
            // Track current package and activity for next comparison
            wizard.currentElementsPackage = currentPackage;
            wizard.currentElementsActivity = currentActivity;

            if (currentActivity) {
                await updateNavigationContext(
                    wizard,
                    { activity: currentActivity, package: currentPackage },
                    elements
                );
            }

            // Update device dimensions for proper overlay scaling (only if changed)
            if (data.device_width && data.device_height && wizard.liveStream) {
                const oldWidth = wizard.liveStream.deviceWidth;
                const oldHeight = wizard.liveStream.deviceHeight;
                // Only call setDeviceDimensions if dimensions actually changed
                // This prevents spam from resetScreenChangeTracking() every refresh
                if (oldWidth !== data.device_width || oldHeight !== data.device_height) {
                    wizard.liveStream.setDeviceDimensions(data.device_width, data.device_height);
                    console.log(`[FlowWizard] Device dimensions updated: ${oldWidth}x${oldHeight} → ${data.device_width}x${data.device_height}`);
                }
            }

            // Only log when element count changes significantly (reduces log noise)
            const lastCount = wizard._lastElementCount || 0;
            if (Math.abs(elements.length - lastCount) > 5) {
                console.log(`[FlowWizard] Elements updated: ${lastCount} → ${elements.length} (pkg: ${currentPackage || 'unknown'})`);
            }
            wizard._lastElementCount = elements.length;
        } else {
            // Polling mode: full screenshot with elements
            const response = await fetch(`${getApiBase()}/adb/screenshot`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: wizard.selectedDevice, quick: false })
            });

            if (!response.ok) return;

            const data = await response.json();
            elements = data.elements || [];

            // SCREEN CHANGE DETECTION: If screen changed during capture, elements were
            // cleared by backend to prevent overlay mismatch. Clear immediately and retry.
            if (data.screen_changed) {
                const MAX_RETRIES = 3;
                wizard._screenChangedRetryCount = (wizard._screenChangedRetryCount || 0) + 1;
                console.log(`[FlowWizard] Screen changed during capture - retry ${wizard._screenChangedRetryCount}/${MAX_RETRIES}`);
                clearAllElementsAndHover(wizard);

                if (wizard._screenChangedRetryCount < MAX_RETRIES) {
                    // Schedule a quick retry after a short delay
                    setTimeout(() => refreshElements(wizard), 300);
                    return;
                } else {
                    // Max retries reached - show retry button and notify user
                    console.warn('[FlowWizard] Screen still changing after max retries');
                    showToast('Screen unstable - click Retry when ready', 'warning', 5000);
                    const retryBtn = document.getElementById('qabRetry');
                    if (retryBtn) retryBtn.style.display = '';
                    wizard._screenChangedRetryCount = 0;
                    return;
                }
            }

            // Reset retry counter on successful capture
            wizard._screenChangedRetryCount = 0;
            // Hide retry button if visible
            const retryBtn = document.getElementById('qabRetry');
            if (retryBtn) retryBtn.style.display = 'none';

            // Extract device dimensions from screenshot (native resolution)
            if (data.screenshot && wizard.liveStream) {
                const img = new Image();
                img.onload = () => {
                    wizard.liveStream.deviceWidth = img.width;
                    wizard.liveStream.deviceHeight = img.height;
                    console.log(`[FlowWizard] Device dimensions: ${img.width}x${img.height}`);
                };
                img.src = 'data:image/png;base64,' + data.screenshot;
            }

            // Store metadata if recorder exists (for updateScreenshotDisplay)
            if (wizard.recorder) {
                wizard.recorder.currentScreenshot = data.screenshot;
                wizard.recorder.screenshotMetadata = {
                    elements: elements,
                    timestamp: data.timestamp,
                    width: wizard.recorder.screenshotMetadata?.width,
                    height: wizard.recorder.screenshotMetadata?.height,
                    quick: false
                };
                // Update the display with the fresh screenshot - MUST await to ensure
                // new screenshot is loaded before any element overlays are drawn
                // This fixes the bug where old screenshot would show with new elements
                await updateScreenshotDisplay(wizard);
            }
            // Polling mode uses canvasRenderer.render() which handles both screenshot
            // and element overlays, so no need to update liveStream separately
        }

        // Only in streaming mode: Update LiveStream elements for overlay (batched - single redraw)
        // In polling mode, canvasRenderer.render() already handles this
        if (wizard.captureMode === 'streaming' && wizard.liveStream) {
            // Set new elements and redraw in one operation (no intermediate states)
            wizard.liveStream.elements = elements;

            // Single atomic redraw with new elements
            if (wizard.liveStream.currentImage) {
                wizard.liveStream._renderFrame(wizard.liveStream.currentImage, elements);
            }
        }

        // Update element tree (deferred to avoid blocking frame rendering)
        // Use requestIdleCallback if available, otherwise requestAnimationFrame
        const updateUI = () => {
            wizard.updateElementTree(elements);
            wizard.updateElementCount(elements.length);
        };

        if (wizard.captureMode === 'streaming' && 'requestIdleCallback' in window) {
            // Defer DOM updates until browser is idle (won't block frame rendering)
            requestIdleCallback(updateUI, { timeout: 500 });
        } else {
            // Immediate update for polling mode
            updateUI();
        }

        // Update app info header (in case user manually switched apps)
        try {
            const screenResponse = await fetch(`${getApiBase()}/adb/screen/current/${encodeURIComponent(wizard.selectedDevice)}`);
            if (screenResponse.ok) {
                const screenData = await screenResponse.json();
                if (screenData.activity) {
                    const appNameEl = document.getElementById('appName');
                    if (appNameEl && screenData.activity.package) {
                        // Extract app name from package (e.g., "com.byd.autolink" → "BYD AUTO")
                        const appName = screenData.activity.package.split('.').pop() || screenData.activity.package;
                        appNameEl.textContent = appName.charAt(0).toUpperCase() + appName.slice(1);
                        console.log(`[FlowWizard] Updated app name: ${appName}`);
                    }
                    await updateNavigationContext(wizard, screenData.activity, elements);
                    await maybeLearnScreen(wizard, screenData.activity, elements);
                }
            }
        } catch (appInfoError) {
            console.warn('[FlowWizard] Failed to update app info:', appInfoError);
        }

        console.log(`[FlowWizard] Elements refreshed: ${elements.length} elements`);
    } catch (error) {
        console.warn('[FlowWizard] Failed to refresh elements:', error);
    } finally {
        // Clear the safety timeout and reset guard
        clearTimeout(guardTimeout);
        wizard._refreshingElements = false;

        // Hide refresh indicator
        const refreshIndicator = document.getElementById('elementsRefreshIndicator');
        if (refreshIndicator) {
            refreshIndicator.classList.add('hidden');
        }
    }
}

/**
 * Auto-refresh elements after an action (with delay)
 * Used in streaming mode to update element overlays after tap/swipe
 */
export async function refreshAfterAction(wizard, delayMs = 500) {
    // IMPORTANT: Clear all elements and hover immediately when action occurs
    // This prevents stale elements/highlight from previous screen showing on new screen
    clearAllElementsAndHover(wizard);

    setTimeout(async () => {
        try {
            if (wizard.captureMode === 'streaming') {
                // Streaming mode: fetch elements via fast API
                await refreshElements(wizard);
            } else {
                // Polling mode: capture screenshot which includes elements
                await wizard.recorder?.captureScreenshot();
                wizard.updateScreenshotDisplay?.();
            }
        } catch (e) {
            console.warn('[FlowWizard] Auto-refresh after action failed:', e);
        }
    }, delayMs);
}

/**
 * Setup hover tooltip for element preview
 */
export function setupHoverTooltip(wizard) {
    wizard.hoveredElement = null;
    const hoverTooltip = document.getElementById('hoverTooltip');
    const container = document.getElementById('screenshotContainer');

    if (!hoverTooltip || !container) return;

    // Handle mouse move on canvas
    wizard.canvas.addEventListener('mousemove', (e) => {
        handleCanvasHover(wizard, e, hoverTooltip, container);
    });

    // Hide tooltip when mouse leaves canvas
    wizard.canvas.addEventListener('mouseleave', () => {
        wizard.hoveredElement = null;
        hideHoverTooltip(wizard, hoverTooltip);
    });

    console.log('[FlowWizard] Hover tooltip initialized');
}

/**
 * Handle mouse movement over canvas for element hover
 */
export function handleCanvasHover(wizard, e, hoverTooltip, container) {
    // Use elements based on current capture mode to avoid stale data
    // In streaming mode: use liveStream.elements (updated from elements API)
    // In polling mode: use recorder.screenshotMetadata.elements (from screenshot response)
    const elements = wizard.captureMode === 'streaming'
        ? (wizard.liveStream?.elements || [])
        : (wizard.recorder?.screenshotMetadata?.elements || wizard.liveStream?.elements || []);

    if (elements.length === 0) {
        hideHoverTooltip(wizard, hoverTooltip);
        clearHoverHighlight(wizard);
        wizard.hoveredElement = null;
        return;
    }

    // Get canvas coordinates (CSS display coords → canvas bitmap coords)
    const rect = wizard.canvas.getBoundingClientRect();
    const cssToCanvas = wizard.canvas.width / rect.width;
    const canvasX = (e.clientX - rect.left) * cssToCanvas;
    const canvasY = (e.clientY - rect.top) * cssToCanvas;

    // Convert to device coordinates (use appropriate converter based on mode)
    let deviceCoords;
    if (wizard.captureMode === 'streaming' && wizard.liveStream) {
        deviceCoords = wizard.liveStream.canvasToDevice(canvasX, canvasY);
    } else {
        deviceCoords = wizard.canvasRenderer.canvasToDevice(canvasX, canvasY);
    }

    // Skip if no frame loaded yet (deviceCoords will be null)
    if (!deviceCoords) {
        hoverTooltip.style.display = 'none';
        return;
    }

    // Container classes to filter out (same as FlowInteractions)
    // Use Set for O(1) lookup instead of Array.includes() O(n)
    const containerClasses = new Set([
        'android.view.View', 'android.view.ViewGroup', 'android.widget.FrameLayout',
        'android.widget.LinearLayout', 'android.widget.RelativeLayout',
        'android.widget.ScrollView', 'android.widget.HorizontalScrollView',
        'androidx.constraintlayout.widget.ConstraintLayout',
        'androidx.recyclerview.widget.RecyclerView', 'androidx.cardview.widget.CardView'
    ]);

    // Find elements at hover position (filter containers)
    let elementsAtPoint = [];
    for (let i = elements.length - 1; i >= 0; i--) {
        const el = elements[i];
        if (!el.bounds) continue;

        // Skip containers if filter is enabled (BUT keep clickable containers - they're usually buttons)
        if (wizard.overlayFilters?.hideContainers && el.class && containerClasses.has(el.class)) {
            const isUsefulContainer = el.clickable || (el.resource_id && el.resource_id.trim());
            if (!isUsefulContainer) continue;
        }

        // Skip empty elements if filter is enabled
        // Keep clickable elements (includes inherited clickable from parent)
        if (wizard.overlayFilters?.hideEmptyElements) {
            const hasText = el.text && el.text.trim();
            const hasContentDesc = el.content_desc && el.content_desc.trim();
            if (!hasText && !hasContentDesc && !el.clickable) {
                continue;
            }
        }

        const b = el.bounds;
        if (deviceCoords.x >= b.x && deviceCoords.x <= b.x + b.width &&
            deviceCoords.y >= b.y && deviceCoords.y <= b.y + b.height) {
            elementsAtPoint.push(el);
        }
    }

    // Prioritize: elements with text first, then clickable, then smallest area
    let foundElement = null;
    if (elementsAtPoint.length > 0) {
        // Prefer elements with text
        const withText = elementsAtPoint.filter(el => el.text?.trim() || el.content_desc?.trim());
        const clickable = elementsAtPoint.filter(el => el.clickable);
        const candidates = withText.length > 0 ? withText : (clickable.length > 0 ? clickable : elementsAtPoint);

        foundElement = candidates.reduce((smallest, el) => {
            const area = el.bounds.width * el.bounds.height;
            const smallestArea = smallest.bounds.width * smallest.bounds.height;
            return area < smallestArea ? el : smallest;
        });
    }

    // Check if element changed (compare by bounds, not object reference)
    const isSameElement = foundElement && wizard.hoveredElement &&
        foundElement.bounds?.x === wizard.hoveredElement.bounds?.x &&
        foundElement.bounds?.y === wizard.hoveredElement.bounds?.y &&
        foundElement.bounds?.width === wizard.hoveredElement.bounds?.width;

    if (foundElement && !isSameElement) {
        // New element - rebuild tooltip content
        wizard.hoveredElement = foundElement;
        showHoverTooltip(wizard, e, foundElement, hoverTooltip, container);
        highlightHoveredElement(wizard, foundElement);
    } else if (!foundElement && wizard.hoveredElement) {
        // No longer hovering any element
        wizard.hoveredElement = null;
        hideHoverTooltip(wizard, hoverTooltip);
        clearHoverHighlight(wizard);
    }

    // ALWAYS update position when hovering an element (fixes cursor following)
    if (foundElement) {
        updateTooltipPosition(wizard, e, hoverTooltip, container);
    }
}

/**
 * Show hover tooltip with element info
 */
export function showHoverTooltip(wizard, e, element, hoverTooltip, container) {
    const header = hoverTooltip.querySelector('.tooltip-header');
    const body = hoverTooltip.querySelector('.tooltip-body');

    // Header: element text or class name
    const displayName = element.text?.trim() ||
                       element.content_desc?.trim() ||
                       element.class?.split('.').pop() ||
                       'Element';
    header.textContent = displayName;

    // Body: element details
    const clickableBadge = element.clickable
        ? '<span class="clickable-badge">Clickable</span>'
        : '<span class="not-clickable-badge">Not Clickable</span>';

    let bodyHtml = `<div class="tooltip-row"><span class="tooltip-label">Class:</span><span class="tooltip-value">${element.class?.split('.').pop() || '-'}</span></div>`;

    const resourceId = element.resource_id;
    if (resourceId) {
        const resId = resourceId.split('/').pop() || resourceId;
        bodyHtml += `<div class="tooltip-row"><span class="tooltip-label">ID:</span><span class="tooltip-value">${resId}</span></div>`;
    }

    if (element.bounds) {
        bodyHtml += `<div class="tooltip-row"><span class="tooltip-label">Size:</span><span class="tooltip-value">${element.bounds.width}x${element.bounds.height}</span></div>`;
    }

    bodyHtml += `<div class="tooltip-row"><span class="tooltip-label">Status:</span><span class="tooltip-value">${clickableBadge}</span></div>`;

    body.innerHTML = bodyHtml;

    updateTooltipPosition(wizard, e, hoverTooltip, container);
    hoverTooltip.style.display = 'block';
}

/**
 * Update tooltip position near cursor
 */
export function updateTooltipPosition(wizard, e, hoverTooltip, container) {
    const containerRect = container.getBoundingClientRect();

    // Account for container scroll offset
    const scrollLeft = container.scrollLeft || 0;
    const scrollTop = container.scrollTop || 0;

    // Position tooltip near cursor (add scroll offset for scrolled containers)
    let x = e.clientX - containerRect.left + scrollLeft + 15;
    let y = e.clientY - containerRect.top + scrollTop + 15;

    // Get tooltip dimensions (use cached if not visible yet)
    const tooltipWidth = hoverTooltip.offsetWidth || 280;
    const tooltipHeight = hoverTooltip.offsetHeight || 100;

    // Keep tooltip within visible viewport (not scrolled content)
    const visibleWidth = containerRect.width;
    const visibleHeight = containerRect.height;

    // Flip to left if would overflow right
    if (x - scrollLeft + tooltipWidth > visibleWidth - 10) {
        x = e.clientX - containerRect.left + scrollLeft - tooltipWidth - 15;
    }
    // Flip to top if would overflow bottom
    if (y - scrollTop + tooltipHeight > visibleHeight - 10) {
        y = e.clientY - containerRect.top + scrollTop - tooltipHeight - 15;
    }

    // Ensure minimum position
    x = Math.max(scrollLeft + 5, x);
    y = Math.max(scrollTop + 5, y);

    hoverTooltip.style.left = x + 'px';
    hoverTooltip.style.top = y + 'px';
}

/**
 * Hide hover tooltip
 */
export function hideHoverTooltip(wizard, hoverTooltip) {
    if (hoverTooltip) {
        hoverTooltip.style.display = 'none';
    }
}

/**
 * Highlight hovered element using CSS overlay (no canvas re-render)
 * Handles both polling mode (screenshot) and streaming mode (live stream)
 */
export function highlightHoveredElement(wizard, element) {
    const container = document.getElementById('screenshotContainer');
    if (!container || !element?.bounds) {
        clearHoverHighlight(wizard);
        return;
    }

    // Create or reuse highlight overlay
    let highlight = document.getElementById('hoverHighlight');
    if (!highlight) {
        highlight = document.createElement('div');
        highlight.id = 'hoverHighlight';
        highlight.className = 'hover-highlight';
        container.appendChild(highlight);
    }

    // Calculate position relative to canvas
    const canvasRect = wizard.canvas.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();

    // CRITICAL: For scroll containers, the highlight must be positioned relative to scroll position
    // canvasRect is viewport position (affected by scroll), but absolute positioning is relative to container
    // So we need the canvas offset WITHIN the scrollable content, not the viewport offset
    const offsetX = canvasRect.left - containerRect.left + container.scrollLeft;
    const offsetY = canvasRect.top - containerRect.top + container.scrollTop;

    // Get CSS scale (canvas bitmap size to display size)
    const cssScaleX = canvasRect.width / wizard.canvas.width;
    const cssScaleY = canvasRect.height / wizard.canvas.height;

    // DEBUG: Always log scaling info to diagnose misalignment
    console.log('[HoverHighlight] Scaling:', {
        mode: wizard.captureMode,
        canvasBitmap: `${wizard.canvas.width}x${wizard.canvas.height}`,
        canvasCSS: `${canvasRect.width.toFixed(0)}x${canvasRect.height.toFixed(0)}`,
        cssScale: `${cssScaleX.toFixed(3)}x${cssScaleY.toFixed(3)}`,
        offset: `${offsetX.toFixed(0)}x${offsetY.toFixed(0)}`,
        scroll: `${container.scrollLeft}x${container.scrollTop}`,
        canvasPos: `(${canvasRect.left.toFixed(0)},${canvasRect.top.toFixed(0)})`,
        containerPos: `(${containerRect.left.toFixed(0)},${containerRect.top.toFixed(0)})`
    });

    // In streaming mode, element bounds are in device coords, canvas may be at lower res
    // We need to scale: device coords → canvas coords → CSS display coords
    // IMPORTANT: Use separate X and Y scales to handle aspect ratio differences
    let deviceToCanvasScaleX = 1;
    let deviceToCanvasScaleY = 1;
    if (wizard.captureMode === 'streaming' && wizard.liveStream) {
        // Scale from device resolution to canvas resolution (separate X/Y for aspect ratio)
        deviceToCanvasScaleX = wizard.canvas.width / wizard.liveStream.deviceWidth;
        deviceToCanvasScaleY = wizard.canvas.height / wizard.liveStream.deviceHeight;
    }

    const b = element.bounds;
    // First scale from device to canvas, then from canvas to CSS display
    const totalScaleX = deviceToCanvasScaleX * cssScaleX;
    const totalScaleY = deviceToCanvasScaleY * cssScaleY;
    const x = b.x * totalScaleX + offsetX;
    const y = b.y * totalScaleY + offsetY;
    const w = b.width * totalScaleX;
    const h = b.height * totalScaleY;

    // DEBUG: Log element positioning
    console.log('[HoverHighlight] Element:', {
        bounds: `(${b.x},${b.y}) ${b.width}x${b.height}`,
        scaled: `(${x.toFixed(0)},${y.toFixed(0)}) ${w.toFixed(0)}x${h.toFixed(0)}`,
        text: element.text?.substring(0, 30) || element.class
    });

    highlight.style.cssText = `
        position: absolute;
        left: ${x}px;
        top: ${y}px;
        width: ${w}px;
        height: ${h}px;
        border: 2px solid #00ffff;
        border-radius: 4px;
        background: rgba(0, 255, 255, 0.1);
        pointer-events: none;
        z-index: 50;
        transition: all 0.1s ease-out;
    `;
}

/**
 * Clear hover highlight overlay
 */
export function clearHoverHighlight(wizard) {
    const highlight = document.getElementById('hoverHighlight');
    if (highlight) {
        highlight.remove();
    }
}

/**
 * Clear all elements and hover state across all modes
 * Call this when an action is performed that changes the screen
 */
export function clearAllElementsAndHover(wizard) {
    // Clear hover state
    clearHoverHighlight(wizard);
    wizard.hoveredElement = null;

    // Clear recorder metadata (used in polling mode)
    if (wizard.recorder?.screenshotMetadata) {
        wizard.recorder.screenshotMetadata.elements = [];
    }

    // Clear liveStream elements (used in streaming mode)
    if (wizard.liveStream) {
        wizard.liveStream.elements = [];
    }

    console.log('[FlowWizard] Cleared all elements and hover state');
}

// ==========================================
// Phase 4: Gesture Recording Methods
// ==========================================

/**
 * Handle gesture start (mousedown/touchstart)
 */
export function onGestureStart(wizard, e) {
    // Ignore during pinch gestures
    if (wizard.canvasRenderer?.isPinching) return;

    e.preventDefault();

    const rect = wizard.canvas.getBoundingClientRect();
    let clientX, clientY;

    if (e.touches) {
        clientX = e.touches[0].clientX;
        clientY = e.touches[0].clientY;
    } else {
        clientX = e.clientX;
        clientY = e.clientY;
    }

    // Convert CSS coordinates to canvas bitmap coordinates
    const cssToCanvas = wizard.canvas.width / rect.width;
    wizard.dragStart = {
        canvasX: (clientX - rect.left) * cssToCanvas,
        canvasY: (clientY - rect.top) * cssToCanvas,
        timestamp: Date.now()
    };
    wizard.isDragging = true;
}

/**
 * Handle gesture end (mouseup/touchend)
 */
export async function onGestureEnd(wizard, e) {
    if (!wizard.isDragging || !wizard.dragStart) return;

    const rect = wizard.canvas.getBoundingClientRect();
    let clientX, clientY;

    if (e.changedTouches) {
        clientX = e.changedTouches[0].clientX;
        clientY = e.changedTouches[0].clientY;
    } else {
        clientX = e.clientX;
        clientY = e.clientY;
    }

    // Convert CSS coordinates to canvas bitmap coordinates
    const cssToCanvas = wizard.canvas.width / rect.width;
    const endCanvasX = (clientX - rect.left) * cssToCanvas;
    const endCanvasY = (clientY - rect.top) * cssToCanvas;

    // Calculate distance
    const dx = endCanvasX - wizard.dragStart.canvasX;
    const dy = endCanvasY - wizard.dragStart.canvasY;
    const distance = Math.sqrt(dx * dx + dy * dy);

    wizard.isDragging = false;

    const container = document.getElementById('screenshotContainer');

    // Get canvas offset within container for accurate ripple/path position
    const canvasRect = wizard.canvas.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const canvasOffsetX = canvasRect.left - containerRect.left + container.scrollLeft;
    const canvasOffsetY = canvasRect.top - containerRect.top + container.scrollTop;

    // CSS scale factor: canvas bitmap coords to display coords (accounts for zoom)
    const cssScale = canvasRect.width / wizard.canvas.width;

    if (distance < wizard.MIN_SWIPE_DISTANCE) {
        // It's a tap
        console.log(`[FlowWizard] Tap at canvas (${wizard.dragStart.canvasX}, ${wizard.dragStart.canvasY})`);

        // Show tap ripple effect (convert canvas coords to display coords, then add offset)
        const rippleX = wizard.dragStart.canvasX * cssScale + canvasOffsetX;
        const rippleY = wizard.dragStart.canvasY * cssScale + canvasOffsetY;
        showTapRipple(wizard, container, rippleX, rippleY);

        // Handle element click (existing logic)
        await wizard.handleElementClick(wizard.dragStart.canvasX, wizard.dragStart.canvasY);
    } else {
        // It's a swipe
        console.log(`[FlowWizard] Swipe from (${wizard.dragStart.canvasX},${wizard.dragStart.canvasY}) to (${endCanvasX},${endCanvasY})`);

        // Show swipe path visualization (convert canvas coords to display coords, then add offset)
        showSwipePath(wizard, container,
            wizard.dragStart.canvasX * cssScale + canvasOffsetX,
            wizard.dragStart.canvasY * cssScale + canvasOffsetY,
            endCanvasX * cssScale + canvasOffsetX,
            endCanvasY * cssScale + canvasOffsetY);

        // Execute swipe on device
        await executeSwipeGesture(wizard,
            wizard.dragStart.canvasX, wizard.dragStart.canvasY,
            endCanvasX, endCanvasY
        );
    }

    wizard.dragStart = null;
}

/**
 * Execute swipe gesture on device
 */
export async function executeSwipeGesture(wizard, startCanvasX, startCanvasY, endCanvasX, endCanvasY) {
    // Convert canvas coordinates to device coordinates (use appropriate converter)
    let startDevice, endDevice;
    if (wizard.captureMode === 'streaming' && wizard.liveStream) {
        startDevice = wizard.liveStream.canvasToDevice(startCanvasX, startCanvasY);
        endDevice = wizard.liveStream.canvasToDevice(endCanvasX, endCanvasY);
    } else {
        startDevice = wizard.canvasRenderer.canvasToDevice(startCanvasX, startCanvasY);
        endDevice = wizard.canvasRenderer.canvasToDevice(endCanvasX, endCanvasY);
    }

    console.log(`[FlowWizard] Executing swipe: (${startDevice.x},${startDevice.y}) → (${endDevice.x},${endDevice.y})`);

    // Capture screen context BEFORE executing action (so step is linked to source screen)
    let screenContext = {};
    if (wizard.recorder) {
        try {
            const screenInfo = await wizard.recorder.getCurrentScreen();
            if (screenInfo?.activity) {
                screenContext = {
                    screen_activity: screenInfo.activity.activity || null,
                    screen_package: screenInfo.activity.package || null
                };
                console.log(`[FlowWizard] Captured pre-swipe context: ${screenContext.screen_activity}`);
            }
        } catch (e) {
            console.warn('[FlowWizard] Failed to capture pre-swipe screen context:', e);
        }
    }

    try {
        const response = await fetch(`${getApiBase()}/adb/swipe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: wizard.selectedDevice,
                x1: startDevice.x,
                y1: startDevice.y,
                x2: endDevice.x,
                y2: endDevice.y,
                duration: 300
            })
        });

        if (!response.ok) {
            throw new Error('Failed to execute swipe');
        }

        // Build swipe step
        const swipeStep = {
            step_type: 'swipe',
            start_x: startDevice.x,
            start_y: startDevice.y,
            end_x: endDevice.x,
            end_y: endDevice.y,
            duration: 300,
            description: `Swipe from (${startDevice.x},${startDevice.y}) to (${endDevice.x},${endDevice.y})`,
            // Include pre-captured screen context
            ...screenContext
        };

        // Track last executed action (even when paused) for navigation step insertion
        wizard._lastExecutedAction = { ...swipeStep, _timestamp: Date.now() };

        // Add swipe step to flow (unless recording is paused)
        if (!wizard.recordingPaused) {
            wizard.recorder.addStep(swipeStep);
            showToast('Swipe recorded', 'success', 1500);
        } else {
            showToast('Swipe executed (not recorded)', 'info', 1500);
        }

        // Refresh elements after swipe (give device time to settle)
        // This clears stale elements immediately, then refreshes after delay
        // Handles both streaming (refreshElements) and polling (captureScreenshot) modes
        refreshAfterAction(wizard, 800);

    } catch (error) {
        console.error('[FlowWizard] Swipe failed:', error);
        showToast(`Swipe failed: ${error.message}`, 'error');
    }
}

/**
 * Show animated tap ripple at position
 */
export function showTapRipple(wizard, container, x, y) {
    // Create ripple ring
    const ring = document.createElement('div');
    ring.className = 'tap-ripple-ring';
    ring.style.cssText = `
        position: absolute;
        left: ${x}px;
        top: ${y}px;
        width: 20px;
        height: 20px;
        margin-left: -10px;
        margin-top: -10px;
        border: 3px solid #3b82f6;
        border-radius: 50%;
        pointer-events: none;
        animation: tapRippleExpand 0.5s ease-out forwards;
        z-index: 100;
    `;
    container.appendChild(ring);

    // Create second delayed ring for effect
    setTimeout(() => {
        const ring2 = document.createElement('div');
        ring2.className = 'tap-ripple-ring';
        ring2.style.cssText = ring.style.cssText;
        ring2.style.animationDelay = '0.1s';
        container.appendChild(ring2);
        setTimeout(() => ring2.remove(), 600);
    }, 100);

    // Remove after animation
    setTimeout(() => ring.remove(), 600);
}

/**
 * Show animated swipe path from start to end
 */
export function showSwipePath(wizard, container, startX, startY, endX, endY) {
    // Create or reuse swipe path container
    let swipeContainer = document.getElementById('swipePathContainer');
    if (!swipeContainer) {
        swipeContainer = document.createElement('div');
        swipeContainer.id = 'swipePathContainer';
        swipeContainer.className = 'swipe-path';
        swipeContainer.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 100;
        `;
        container.appendChild(swipeContainer);
    }

    // Calculate SVG dimensions
    const width = container.offsetWidth;
    const height = container.offsetHeight;

    // Create SVG with animated line
    swipeContainer.innerHTML = `
        <svg width="${width}" height="${height}" style="position: absolute; top: 0; left: 0;">
            <defs>
                <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                    <polygon points="0 0, 10 3.5, 0 7" class="swipe-arrow" fill="#22c55e"/>
                </marker>
            </defs>
            <line x1="${startX}" y1="${startY}" x2="${endX}" y2="${endY}"
                  stroke="#22c55e" stroke-width="3" stroke-linecap="round"
                  class="swipe-line" marker-end="url(#arrowhead)"
                  stroke-dasharray="1000" stroke-dashoffset="1000"
                  style="animation: swipeLineDraw 0.3s ease-out forwards;"/>
        </svg>
    `;

    // Add start dot
    const startDot = document.createElement('div');
    startDot.className = 'swipe-dot swipe-dot-start';
    startDot.style.cssText = `
        position: absolute;
        left: ${startX}px;
        top: ${startY}px;
        width: 12px;
        height: 12px;
        margin-left: -6px;
        margin-top: -6px;
        background: #22c55e;
        border-radius: 50%;
        pointer-events: none;
    `;
    swipeContainer.appendChild(startDot);

    // Add end dot
    const endDot = document.createElement('div');
    endDot.className = 'swipe-dot swipe-dot-end';
    endDot.style.cssText = `
        position: absolute;
        left: ${endX}px;
        top: ${endY}px;
        width: 12px;
        height: 12px;
        margin-left: -6px;
        margin-top: -6px;
        background: #22c55e;
        border: 2px solid white;
        border-radius: 50%;
        pointer-events: none;
    `;
    swipeContainer.appendChild(endDot);

    swipeContainer.style.display = 'block';

    // Auto-hide after animation
    setTimeout(() => {
        swipeContainer.style.display = 'none';
        swipeContainer.innerHTML = '';
    }, 800);
}

// ==========================================
// Element Tree Methods
// ==========================================

/**
 * Setup element tree panel
 */
export function setupElementTree(wizard) {
    const container = document.getElementById('elementTreeContainer');
    if (!container) {
        console.warn('[FlowWizard] Element tree container not found');
        return;
    }

    const ElementTree = window.ElementTree;
    if (!ElementTree) {
        console.warn('[FlowWizard] ElementTree class not loaded');
        return;
    }

    wizard.elementTree = new ElementTree(container, {
        onTap: (element) => handleTreeTap(wizard, element),
        onSensor: (element) => handleTreeSensor(wizard, element),
        onTimestamp: (element) => handleTreeTimestamp(wizard, element),
        onHighlight: (element) => highlightHoveredElement(wizard, element)
    });

    // Wire up tree search
    const searchInput = document.getElementById('treeSearchInput');
    searchInput?.addEventListener('input', (e) => {
        wizard.elementTree?.setSearchFilter(e.target.value);
    });

    // Wire up tree filters
    document.getElementById('treeFilterClickable')?.addEventListener('change', (e) => {
        wizard.elementTree?.setFilterOptions({ clickableOnly: e.target.checked });
    });

    document.getElementById('treeFilterText')?.addEventListener('change', (e) => {
        wizard.elementTree?.setFilterOptions({ textOnly: e.target.checked });
    });

    // Wire up Smart Suggestions button
    document.getElementById('smartSuggestionsBtn')?.addEventListener('click', async () => {
        await handleSmartSuggestions(wizard);
    });

    console.log('[FlowWizard] Element tree initialized');
}

/**
 * Toggle element tree panel visibility
 */
export function toggleTreeView(wizard, show = null) {
    const treePanel = document.getElementById('elementTreePanel');
    const layout = document.querySelector('.recording-layout');
    const toggleBtn = document.getElementById('btnToggleTree');

    if (!treePanel || !layout) return;

    // Determine new state
    wizard.isTreeViewOpen = show !== null ? show : !wizard.isTreeViewOpen;

    if (wizard.isTreeViewOpen) {
        treePanel.style.display = 'flex';
        layout.classList.add('split-view');
        toggleBtn?.classList.add('active');

        // Update tree with current elements
        const elements = wizard.recorder?.screenshotMetadata?.elements || [];
        wizard.elementTree?.setElements(elements);
    } else {
        treePanel.style.display = 'none';
        layout.classList.remove('split-view');
        toggleBtn?.classList.remove('active');
    }

    console.log(`[FlowWizard] Tree view ${wizard.isTreeViewOpen ? 'opened' : 'closed'}`);
}

/**
 * Handle tap action from tree
 */
function buildElementMetadata(element) {
    if (!element) return null;

    return {
        text: element.text || null,
        resource_id: element.resource_id || null,
        class: element.class || null,
        content_desc: element.content_desc || null,
        clickable: element.clickable || false,
        bounds: element.bounds || null,
        path: element.path || null,
        parent_path: element.parent_path || null,
        depth: element.depth ?? null,
        sibling_index: element.sibling_index ?? null,
        element_index: element.element_index ?? null
    };
}

export function handleTreeTap(wizard, element) {
    if (!element?.bounds) return;

    const bounds = element.bounds;
    const x = bounds.x + bounds.width / 2;
    const y = bounds.y + bounds.height / 2;

    console.log(`[FlowWizard] Tree tap on element at (${x}, ${y})`);

    // Execute tap on device
    wizard.recorder?.executeTap(x, y);

    // Add step to flow
    wizard.recorder?.addStep({
        step_type: 'tap',
        x: Math.round(x),
        y: Math.round(y),
        description: `Tap "${element.text || element.class}"`,
        element: buildElementMetadata(element)
    });

    // Clear stale elements and hover highlight immediately (video updates faster than elements API)
    clearAllElementsAndHover(wizard);

    showToast('Tap recorded from tree', 'success', 1500);
    refreshAfterAction(wizard, 500);
}

/**
 * Handle sensor action from tree
 */
export async function handleTreeSensor(wizard, element) {
    if (!element) return;

    console.log('[FlowWizard] Tree sensor for element:', element);

    // Calculate coordinates from element bounds
    const bounds = element.bounds || {};
    const coords = {
        x: Math.round((bounds.x || 0) + (bounds.width || 0) / 2),
        y: Math.round((bounds.y || 0) + (bounds.height || 0) / 2)
    };

    // Import Dialogs module dynamically
    const Dialogs = await import('./flow-wizard-dialogs.js?v=0.4.0-beta.3.2');

    // Go directly to text sensor creation (most common case from element tree)
    // Use element.index if available (from tree), otherwise default to 0
    const elementIndex = element.index ?? 0;
    await Dialogs.createTextSensor(wizard, element, coords, elementIndex);
}

/**
 * Handle timestamp marking from tree
 * Marks this element as the timestamp validator for the most recent refresh step
 */
export async function handleTreeTimestamp(wizard, element) {
    if (!element) return;

    console.log('[FlowWizard] Tree timestamp for element:', element);

    // Find the most recent pull_refresh or restart_app step
    const steps = wizard.recorder.getSteps();
    let lastRefreshIndex = -1;

    for (let i = steps.length - 1; i >= 0; i--) {
        if (steps[i].step_type === 'pull_refresh' || steps[i].step_type === 'restart_app') {
            lastRefreshIndex = i;
            break;
        }
    }

    if (lastRefreshIndex === -1) {
        showToast('No refresh step found. Add a pull-refresh or restart-app step first!', 'warning', 3000);
        return;
    }

    // Import Dialogs module dynamically
    const Dialogs = await import('./flow-wizard-dialogs.js?v=0.4.0-beta.3.2');

    // Show configuration dialog
    const config = await Dialogs.promptForTimestampConfig(wizard, element, steps[lastRefreshIndex]);

    if (!config) return; // User cancelled

    // Update the refresh step with timestamp validation
    const refreshStep = steps[lastRefreshIndex];
    refreshStep.validate_timestamp = true;
    refreshStep.timestamp_element = {
        text: element.text,
        content_desc: element.content_desc,
        resource_id: element.resource_id,
        class: element.class,
        bounds: element.bounds
    };
    refreshStep.refresh_max_retries = config.maxRetries;
    refreshStep.refresh_retry_delay = config.retryDelay;

    showToast(`Timestamp validation added to refresh step #${lastRefreshIndex + 1}`, 'success', 2500);

    // Update UI to show the change
    wizard.updateFlowStepsUI();
}

/**
 * Setup the Suggestions tab in the right panel
 * This provides inline sensor/action suggestions without a modal
 */
export function setupSuggestionsTab(wizard) {
    console.log('[FlowWizard] Setting up Suggestions tab');

    const refreshBtn = document.getElementById('refreshSuggestionsBtn');
    const selectAllBtn = document.getElementById('selectAllSuggestionsTabBtn');
    const addSelectedBtn = document.getElementById('addSelectedSuggestionsTabBtn');
    const suggestionsContent = document.getElementById('suggestionsContent');
    const modeTabs = document.querySelectorAll('.suggestions-toolbar .mode-tab');

    // Track current mode and suggestions
    wizard._suggestionsMode = 'sensors';
    wizard._sensorSuggestions = [];
    wizard._actionSuggestions = [];
    wizard._selectedSuggestions = new Set();

    // Mode tab switching
    modeTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            modeTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            wizard._suggestionsMode = tab.dataset.mode;
            renderSuggestionsContent(wizard);
        });
    });

    // Refresh button
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            await loadSuggestions(wizard);
        });
    }

    // Select all button
    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => {
            const suggestions = wizard._suggestionsMode === 'sensors'
                ? wizard._sensorSuggestions
                : wizard._actionSuggestions;

            if (wizard._selectedSuggestions.size === suggestions.length) {
                // Deselect all
                wizard._selectedSuggestions.clear();
            } else {
                // Select all
                suggestions.forEach((_, i) => wizard._selectedSuggestions.add(i));
            }
            renderSuggestionsContent(wizard);
            updateSelectedCount(wizard);
        });
    }

    // Add selected button
    if (addSelectedBtn) {
        addSelectedBtn.addEventListener('click', async () => {
            await addSelectedSuggestions(wizard);
        });
    }

    console.log('[FlowWizard] Suggestions tab setup complete');
}

/**
 * Load suggestions from the API for current screen
 */
async function loadSuggestions(wizard) {
    const suggestionsContent = document.getElementById('suggestionsContent');
    if (!suggestionsContent) return;

    if (!wizard.selectedDevice) {
        suggestionsContent.innerHTML = '<div class="suggestions-empty"><p>No device selected</p></div>';
        return;
    }

    suggestionsContent.innerHTML = '<div class="suggestions-loading"><div class="spinner"></div><p>Analyzing screen...</p></div>';

    try {
        // Load sensor suggestions
        const sensorResponse = await fetch(`${getApiBase()}/devices/suggest-sensors`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: wizard.selectedDevice,
                package_name: wizard.selectedApp?.package || null
            })
        });

        if (sensorResponse.ok) {
            const sensorData = await sensorResponse.json();
            wizard._sensorSuggestions = sensorData.suggestions || [];
            document.getElementById('sensorSuggestionsCount').textContent = wizard._sensorSuggestions.length;
        }

        // Load action suggestions
        const actionResponse = await fetch(`${getApiBase()}/devices/suggest-actions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: wizard.selectedDevice,
                package_name: wizard.selectedApp?.package || null
            })
        });

        if (actionResponse.ok) {
            const actionData = await actionResponse.json();
            wizard._actionSuggestions = actionData.suggestions || [];
            document.getElementById('actionSuggestionsCount').textContent = wizard._actionSuggestions.length;
        }

        // Update total count in tab badge
        const totalCount = wizard._sensorSuggestions.length + wizard._actionSuggestions.length;
        document.getElementById('suggestionsCount').textContent = totalCount;

        // Clear selections and render
        wizard._selectedSuggestions.clear();
        renderSuggestionsContent(wizard);
        updateSelectedCount(wizard);

    } catch (error) {
        console.error('[FlowWizard] Failed to load suggestions:', error);
        suggestionsContent.innerHTML = `<div class="suggestions-empty"><p>Failed to load suggestions: ${error.message}</p></div>`;
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Handle alternative name click - swap names
 */
function handleAlternativeNameClick(wizard, index, altName) {
    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    const suggestion = suggestions[index];
    if (!suggestion) return;

    // Swap names: current name becomes an alternative, alt becomes primary
    const oldName = suggestion.name || suggestion.suggested_name;
    suggestion.name = altName;
    suggestion.suggested_name = altName;

    // Update alternatives list
    if (suggestion.alternative_names) {
        // Remove the selected alternative
        suggestion.alternative_names = suggestion.alternative_names.filter(
            alt => alt.name.toLowerCase() !== altName.toLowerCase()
        );
        // Add old name as alternative (if not already there)
        if (!suggestion.alternative_names.some(alt => alt.name.toLowerCase() === oldName.toLowerCase())) {
            suggestion.alternative_names.unshift({
                name: oldName,
                location: 'previous',
                score: 100
            });
        }
    }

    // Re-render to update display
    renderSuggestionsContent(wizard);
    showToast(`Name changed to "${altName}"`, 'success', 2000);
}

/**
 * Highlight suggestion element on screenshot
 */
function highlightSuggestionElement(wizard, suggestion) {
    if (!wizard || !suggestion?.element?.bounds) return;

    import('./canvas-overlay-renderer.js').then(module => {
        const element = {
            bounds: suggestion.element.bounds,
            text: suggestion.element.text,
            class: suggestion.element.class
        };
        module.highlightHoveredElement(wizard, element);
    }).catch(err => {
        console.warn('[Suggestions] Could not highlight element:', err);
    });
}

/**
 * Clear suggestion highlight
 */
function clearSuggestionHighlight(wizard) {
    if (!wizard) return;

    import('./canvas-overlay-renderer.js').then(module => {
        module.clearHoverHighlight(wizard);
    }).catch(err => console.warn('[FlowWizard] Failed to clear hover highlight:', err));
}

/**
 * Render the suggestions content based on current mode
 */
function renderSuggestionsContent(wizard) {
    const suggestionsContent = document.getElementById('suggestionsContent');
    if (!suggestionsContent) return;

    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    if (suggestions.length === 0) {
        suggestionsContent.innerHTML = `
            <div class="suggestions-empty">
                <p>No ${wizard._suggestionsMode} found on current screen</p>
                <p class="hint">Try scrolling or navigating to a different screen</p>
            </div>
        `;
        return;
    }

    const itemsHtml = suggestions.map((suggestion, index) => {
        const isSelected = wizard._selectedSuggestions.has(index);
        const icon = wizard._suggestionsMode === 'sensors'
            ? (suggestion.icon || 'mdi:eye')
            : (suggestion.icon || 'mdi:gesture-tap');

        // Get the current value and element text for prominent display
        const currentValue = suggestion.current_value || '';
        const elementText = suggestion.element?.text || suggestion.text || '';
        const displayValue = currentValue || elementText || '--';
        const unit = suggestion.unit_of_measurement || '';
        const deviceClass = suggestion.device_class || suggestion.pattern_type || '';
        const confidence = suggestion.confidence ? Math.round(suggestion.confidence * 100) : 0;

        // Icon emoji mapping for common types
        const iconEmoji = {
            'mdi:thermometer': '🌡️',
            'mdi:water-percent': '💧',
            'mdi:battery': '🔋',
            'mdi:lightning-bolt': '⚡',
            'mdi:current-ac': '🔌',
            'mdi:flash': '💡',
            'mdi:speedometer': '🚗',
            'mdi:map-marker-distance': '📍',
            'mdi:signal': '📶',
            'mdi:toggle-switch': '🔘',
            'mdi:gesture-tap': '👆',
            'mdi:gesture-tap-button': '🔘',
            'mdi:form-textbox': '📝',
            'mdi:checkbox-marked': '☑️',
            'mdi:timer': '⏱️',
            'mdi:percent': '📊',
            'mdi:clock': '🕐'
        };
        const displayIcon = iconEmoji[icon] || '📊';

        // Build alternative names HTML if available
        let alternativeNamesHtml = '';
        if (suggestion.alternative_names && suggestion.alternative_names.length > 0) {
            const locationIcons = {
                'above': '⬆️',
                'below': '⬇️',
                'left': '⬅️',
                'right': '➡️',
                'resource_id': '🏷️',
                'pattern': '🔍',
                'content_desc': '📝',
                'previous': '↩️'
            };
            const altOptions = suggestion.alternative_names.map(alt => {
                const locIcon = locationIcons[alt.location] || '📍';
                return `<option value="${escapeHtml(alt.name)}" title="${alt.location}: score ${alt.score}">${locIcon} ${escapeHtml(alt.name)}</option>`;
            }).join('');

            alternativeNamesHtml = `
                <div class="suggestion-alt-names">
                    <select class="alt-name-select" data-index="${index}">
                        <option value="" disabled selected>Select name...</option>
                        ${altOptions}
                    </select>
                </div>
            `;
        }

        return `
            <div class="suggestion-item ${isSelected ? 'selected' : ''}" data-index="${index}">
                <label class="suggestion-checkbox">
                    <input type="checkbox" ${isSelected ? 'checked' : ''}>
                </label>
                <div class="suggestion-icon">${displayIcon}</div>
                <div class="suggestion-details">
                    <div class="suggestion-name">${escapeHtml(suggestion.name || suggestion.suggested_name || 'Unnamed')}</div>
                    <div class="suggestion-value-big">${escapeHtml(displayValue)}${unit ? ' ' + escapeHtml(unit) : ''}</div>
                    ${alternativeNamesHtml}
                    <div class="suggestion-meta">
                        <span class="suggestion-device-class">${escapeHtml(deviceClass)}</span>
                        <span class="suggestion-confidence">${confidence}%</span>
                    </div>
                </div>
                <div class="suggestion-buttons">
                    <button class="btn-edit" data-index="${index}" title="Edit before adding">Edit</button>
                    <button class="btn-quick-add" data-index="${index}" title="Add with defaults">+ Add</button>
                </div>
            </div>
        `;
    }).join('');

    suggestionsContent.innerHTML = `<div class="suggestions-list">${itemsHtml}</div>`;

    // Add click handlers for checkboxes (toggle selection)
    suggestionsContent.querySelectorAll('.suggestion-item').forEach(item => {
        item.addEventListener('click', (e) => {
            // Don't toggle if clicking on buttons or alt-name dropdown
            if (e.target.closest('.suggestion-buttons') || e.target.closest('.alt-name-select')) return;

            const index = parseInt(item.dataset.index);
            if (wizard._selectedSuggestions.has(index)) {
                wizard._selectedSuggestions.delete(index);
                item.classList.remove('selected');
                item.querySelector('input[type="checkbox"]').checked = false;
            } else {
                wizard._selectedSuggestions.add(index);
                item.classList.add('selected');
                item.querySelector('input[type="checkbox"]').checked = true;
            }
            updateSelectedCount(wizard);
        });

        // Add hover handlers for element highlighting
        item.addEventListener('mouseenter', () => {
            const index = parseInt(item.dataset.index);
            const suggestions = wizard._suggestionsMode === 'sensors'
                ? wizard._sensorSuggestions
                : wizard._actionSuggestions;
            const suggestion = suggestions[index];
            if (suggestion) {
                highlightSuggestionElement(wizard, suggestion);
            }
        });

        item.addEventListener('mouseleave', () => {
            clearSuggestionHighlight(wizard);
        });
    });

    // Add click handlers for Edit buttons
    suggestionsContent.querySelectorAll('.btn-edit').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            handleEditSuggestion(wizard, index);
        });
    });

    // Add click handlers for Quick Add buttons
    suggestionsContent.querySelectorAll('.btn-quick-add').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            handleQuickAddSuggestion(wizard, index);
        });
    });

    // Add change handlers for Alternative Name dropdown
    suggestionsContent.querySelectorAll('.alt-name-select').forEach(select => {
        select.addEventListener('change', (e) => {
            e.stopPropagation();
            const index = parseInt(select.dataset.index);
            const altName = e.target.value;
            if (altName) {
                handleAlternativeNameClick(wizard, index, altName);
                // Reset dropdown to placeholder
                select.selectedIndex = 0;
            }
        });
    });
}

/**
 * Handle Edit button click - opens full SensorCreator for sensors, simple dialog for actions
 */
function handleEditSuggestion(wizard, index) {
    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    const suggestion = suggestions[index];
    if (!suggestion) return;

    if (wizard._suggestionsMode === 'sensors') {
        // Open full SensorCreator with pre-filled data from suggestion
        const element = suggestion.element || {
            text: suggestion.current_value || suggestion.name,
            bounds: suggestion.bounds,
            resource_id: suggestion.resource_id,
            class: suggestion.element_class,
            index: suggestion.element_index || 0
        };

        const screenActivity = wizard.recorder?.currentScreenActivity || wizard.currentActivity || null;

        // Show full sensor creator with suggestion data pre-filled
        wizard.sensorCreator.show(wizard.selectedDevice, element, element.index || 0, {
            stableDeviceId: wizard.selectedDeviceStableId || wizard.selectedDevice,
            screenActivity: screenActivity,
            targetApp: wizard.selectedApp?.package || null,
            // Pre-fill with suggestion data
            name: suggestion.name || suggestion.suggested_name,
            device_class: suggestion.device_class || 'none',
            unit: suggestion.unit_of_measurement || '',
            icon: suggestion.icon || 'mdi:eye'
        });

        console.log('[Suggestions] Opened full SensorCreator for:', suggestion.name);
    } else {
        // For actions, use the simple edit dialog
        showSuggestionEditDialog(wizard, suggestion, index);
    }
}

/**
 * Handle Quick Add button click - adds suggestion with defaults immediately
 */
async function handleQuickAddSuggestion(wizard, index) {
    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    const suggestion = suggestions[index];
    if (!suggestion) return;

    if (wizard._suggestionsMode === 'sensors') {
        // Create actual sensor via API first, then add capture step
        const sensorName = suggestion.name || suggestion.suggested_name || 'Sensor';

        try {
            // Build sensor definition for API
            // Note: state_class='measurement' requires unit_of_measurement
            const hasUnit = suggestion.unit_of_measurement && suggestion.unit_of_measurement.trim() !== '';
            const hasDeviceClass = suggestion.device_class && suggestion.device_class !== 'none';
            const sensorData = {
                device_id: wizard.selectedDevice,
                stable_device_id: wizard.selectedDeviceStableId || null,
                friendly_name: sensorName,
                sensor_type: 'sensor',
                device_class: suggestion.device_class || 'none',
                state_class: (hasDeviceClass && hasUnit) ? 'measurement' : 'none',
                unit_of_measurement: hasUnit ? suggestion.unit_of_measurement : null,
                icon: suggestion.icon || 'mdi:eye',
                target_app: wizard.selectedApp?.package || null,
                source: {
                    source_type: 'element',
                    element_index: suggestion.element?.index || 0,
                    element_text: suggestion.element?.text || null,
                    element_class: suggestion.element?.class || null,
                    element_resource_id: suggestion.element?.resource_id || null,
                    screen_activity: wizard.recorder?.currentScreenActivity || wizard.currentActivity || null,
                    custom_bounds: suggestion.element?.bounds || null
                },
                extraction_rule: {
                    method: 'exact',
                    extract_numeric: suggestion.device_class && ['battery', 'temperature', 'humidity', 'voltage', 'current', 'power', 'energy'].includes(suggestion.device_class)
                }
            };

            // Create sensor via API (will auto-reuse if matching sensor exists)
            const response = await wizard.apiClient.post('/sensors', sensorData);
            console.log('[Suggestions] Sensor created/reused:', response);

            // Get sensor_id from response
            const sensorId = response?.sensor?.sensor_id || response?.sensor_id;
            if (!sensorId) {
                throw new Error('No sensor_id in response');
            }

            // Create capture_sensors step with sensor_ids (not inline sensors)
            const sensorStep = {
                step_type: 'capture_sensors',
                description: `Capture: ${sensorName}`,
                sensor_ids: [sensorId]
            };

            // Check for screen mismatch and offer navigation step
            const added = await addSensorWithNavigationCheck(wizard, sensorStep);
            if (added) {
                const wasReused = response?.reused;
                showToast(`${wasReused ? 'Reused' : 'Created'} sensor: ${sensorName}`, 'success');
            }
        } catch (error) {
            console.error('[Suggestions] Failed to create sensor:', error);
            showToast(`Failed to create sensor: ${error.message}`, 'error');
        }
    } else {
        // Add action to flow
        if (suggestion.element?.bounds) {
            const tapStep = {
                step_type: 'tap',
                x: Math.round(suggestion.element.bounds.x + suggestion.element.bounds.width / 2),
                y: Math.round(suggestion.element.bounds.y + suggestion.element.bounds.height / 2),
                description: suggestion.name || suggestion.suggested_name || 'Tap action',
                element: buildElementMetadata(suggestion.element)
            };
            wizard.recorder.addStep(tapStep);
            showToast(`Added action: ${suggestion.name || 'Tap'}`, 'success');
        }
    }

    // Update UI
    wizard.updateFlowStepsUI();
}

/**
 * Show edit dialog for a suggestion
 */
function showSuggestionEditDialog(wizard, suggestion, index) {
    // Create dialog overlay
    const dialogOverlay = document.createElement('div');
    dialogOverlay.className = 'dialog-overlay suggestion-edit-dialog-overlay';
    dialogOverlay.innerHTML = `
        <div class="dialog suggestion-edit-dialog">
            <div class="dialog-header">
                <h3>Edit ${wizard._suggestionsMode === 'sensors' ? 'Sensor' : 'Action'}</h3>
                <button class="dialog-close">&times;</button>
            </div>
            <div class="dialog-body">
                <div class="form-group">
                    <label>Name</label>
                    <input type="text" id="editSuggestionName" value="${suggestion.name || suggestion.suggested_name || ''}" placeholder="Enter name">
                </div>
                ${wizard._suggestionsMode === 'sensors' ? `
                    <div class="form-group">
                        <label>Device Class</label>
                        <select id="editSuggestionDeviceClass">
                            <option value="none" ${suggestion.device_class === 'none' ? 'selected' : ''}>None</option>
                            <option value="battery" ${suggestion.device_class === 'battery' ? 'selected' : ''}>Battery</option>
                            <option value="temperature" ${suggestion.device_class === 'temperature' ? 'selected' : ''}>Temperature</option>
                            <option value="humidity" ${suggestion.device_class === 'humidity' ? 'selected' : ''}>Humidity</option>
                            <option value="voltage" ${suggestion.device_class === 'voltage' ? 'selected' : ''}>Voltage</option>
                            <option value="current" ${suggestion.device_class === 'current' ? 'selected' : ''}>Current</option>
                            <option value="power" ${suggestion.device_class === 'power' ? 'selected' : ''}>Power</option>
                            <option value="energy" ${suggestion.device_class === 'energy' ? 'selected' : ''}>Energy</option>
                            <option value="speed" ${suggestion.device_class === 'speed' ? 'selected' : ''}>Speed</option>
                            <option value="distance" ${suggestion.device_class === 'distance' ? 'selected' : ''}>Distance</option>
                            <option value="signal_strength" ${suggestion.device_class === 'signal_strength' ? 'selected' : ''}>Signal Strength</option>
                            <option value="pressure" ${suggestion.device_class === 'pressure' ? 'selected' : ''}>Pressure</option>
                            <option value="illuminance" ${suggestion.device_class === 'illuminance' ? 'selected' : ''}>Illuminance</option>
                            <option value="carbon_dioxide" ${suggestion.device_class === 'carbon_dioxide' ? 'selected' : ''}>CO2</option>
                            <option value="aqi" ${suggestion.device_class === 'aqi' ? 'selected' : ''}>Air Quality</option>
                            <option value="weight" ${suggestion.device_class === 'weight' ? 'selected' : ''}>Weight</option>
                            <option value="volume" ${suggestion.device_class === 'volume' ? 'selected' : ''}>Volume</option>
                            <option value="frequency" ${suggestion.device_class === 'frequency' ? 'selected' : ''}>Frequency</option>
                            <option value="monetary" ${suggestion.device_class === 'monetary' ? 'selected' : ''}>Monetary</option>
                            <option value="duration" ${suggestion.device_class === 'duration' ? 'selected' : ''}>Duration</option>
                            <option value="timestamp" ${suggestion.device_class === 'timestamp' ? 'selected' : ''}>Timestamp</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Unit of Measurement</label>
                        <input type="text" id="editSuggestionUnit" value="${suggestion.unit_of_measurement || ''}" placeholder="e.g., %, °C, km">
                    </div>
                ` : `
                    <div class="form-group">
                        <label>Action Type</label>
                        <select id="editSuggestionActionType">
                            <option value="tap" ${suggestion.action_type === 'tap' ? 'selected' : ''}>Tap</option>
                            <option value="toggle" ${suggestion.action_type === 'toggle' ? 'selected' : ''}>Toggle</option>
                            <option value="input_text" ${suggestion.action_type === 'input_text' ? 'selected' : ''}>Input Text</option>
                            <option value="swipe" ${suggestion.action_type === 'swipe' ? 'selected' : ''}>Swipe</option>
                        </select>
                    </div>
                `}
                <div class="form-group">
                    <label>Entity ID</label>
                    <input type="text" id="editSuggestionEntityId" value="${suggestion.entity_id || ''}" placeholder="sensor.my_sensor">
                </div>
                <div class="suggestion-preview">
                    <strong>Current Value:</strong> ${suggestion.current_value || suggestion.element?.text || 'N/A'}
                </div>
            </div>
            <div class="dialog-footer">
                <button class="btn btn-secondary dialog-cancel">Cancel</button>
                <button class="btn btn-primary dialog-save">Add to Flow</button>
            </div>
        </div>
    `;

    document.body.appendChild(dialogOverlay);

    // Close button handler
    dialogOverlay.querySelector('.dialog-close').addEventListener('click', () => {
        dialogOverlay.remove();
    });

    // Cancel button handler
    dialogOverlay.querySelector('.dialog-cancel').addEventListener('click', () => {
        dialogOverlay.remove();
    });

    // Save button handler
    dialogOverlay.querySelector('.dialog-save').addEventListener('click', async () => {
        const name = document.getElementById('editSuggestionName').value.trim();
        const entityId = document.getElementById('editSuggestionEntityId').value.trim();

        if (wizard._suggestionsMode === 'sensors') {
            const deviceClass = document.getElementById('editSuggestionDeviceClass').value;
            const unit = document.getElementById('editSuggestionUnit').value.trim();
            const sensorName = name || 'Sensor';

            try {
                // Build sensor definition for API
                // Note: state_class='measurement' requires unit_of_measurement
                const hasUnit = unit && unit.trim() !== '';
                const hasDeviceClass = deviceClass && deviceClass !== 'none';
                const sensorData = {
                    device_id: wizard.selectedDevice,
                    stable_device_id: wizard.selectedDeviceStableId || null,
                    friendly_name: sensorName,
                    sensor_type: 'sensor',
                    device_class: deviceClass || 'none',
                    state_class: (hasDeviceClass && hasUnit) ? 'measurement' : 'none',
                    unit_of_measurement: hasUnit ? unit : null,
                    icon: suggestion.icon || 'mdi:eye',
                    target_app: wizard.selectedApp?.package || null,
                    source: {
                        source_type: 'element',
                        element_index: suggestion.element?.index || 0,
                        element_text: suggestion.element?.text || null,
                        element_class: suggestion.element?.class || null,
                        element_resource_id: suggestion.element?.resource_id || null,
                        screen_activity: wizard.recorder?.currentScreenActivity || wizard.currentActivity || null,
                        custom_bounds: suggestion.element?.bounds || null
                    },
                    extraction_rule: {
                        method: 'exact',
                        extract_numeric: hasDeviceClass && ['battery', 'temperature', 'humidity', 'voltage', 'current', 'power', 'energy'].includes(deviceClass)
                    }
                };

                // Create sensor via API (will auto-reuse if matching sensor exists)
                const response = await wizard.apiClient.post('/sensors', sensorData);
                console.log('[Suggestions Edit] Sensor created/reused:', response);

                // Get sensor_id from response
                const sensorId = response?.sensor?.sensor_id || response?.sensor_id;
                if (!sensorId) {
                    throw new Error('No sensor_id in response');
                }

                // Create capture_sensors step with sensor_ids (not inline sensors)
                const sensorStep = {
                    step_type: 'capture_sensors',
                    description: `Capture: ${sensorName}`,
                    sensor_ids: [sensorId]
                };

                // Check for screen mismatch and offer navigation step
                const added = await addSensorWithNavigationCheck(wizard, sensorStep);
                if (added) {
                    const wasReused = response?.reused;
                    showToast(`${wasReused ? 'Reused' : 'Created'} sensor: ${sensorName}`, 'success');
                }
            } catch (error) {
                console.error('[Suggestions Edit] Failed to create sensor:', error);
                showToast(`Failed to create sensor: ${error.message}`, 'error');
            }
        } else {
            const actionType = document.getElementById('editSuggestionActionType').value;

            if (suggestion.element?.bounds) {
                const tapStep = {
                    step_type: actionType,
                    x: Math.round(suggestion.element.bounds.x + suggestion.element.bounds.width / 2),
                    y: Math.round(suggestion.element.bounds.y + suggestion.element.bounds.height / 2),
                    description: name || 'Action'
                };
                wizard.recorder.addStep(tapStep);
                showToast(`Added action: ${name}`, 'success');
            }
        }

        wizard.updateFlowStepsUI();
        dialogOverlay.remove();
    });

    // Click outside to close
    dialogOverlay.addEventListener('click', (e) => {
        if (e.target === dialogOverlay) {
            dialogOverlay.remove();
        }
    });
}

/**
 * Update the selected suggestions count
 */
function updateSelectedCount(wizard) {
    const countEl = document.getElementById('selectedSuggestionsCount');
    if (countEl) {
        countEl.textContent = wizard._selectedSuggestions.size;
    }
}

/**
 * Add selected suggestions to the flow
 */
async function addSelectedSuggestions(wizard) {
    if (wizard._selectedSuggestions.size === 0) {
        showToast('No suggestions selected', 'warning');
        return;
    }

    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    const selectedItems = Array.from(wizard._selectedSuggestions).map(i => suggestions[i]);

    if (wizard._suggestionsMode === 'sensors') {
        // Add sensors to flow - create actual sensors via API first
        let createdCount = 0;
        let reusedCount = 0;
        let failedCount = 0;

        for (const sensor of selectedItems) {
            const sensorName = sensor.name || sensor.suggested_name || 'Sensor';

            try {
                // Build sensor definition for API
                // Note: state_class='measurement' requires unit_of_measurement
                const hasUnit = sensor.unit_of_measurement && sensor.unit_of_measurement.trim() !== '';
                const hasDeviceClass = sensor.device_class && sensor.device_class !== 'none';
                const sensorData = {
                    device_id: wizard.selectedDevice,
                    stable_device_id: wizard.selectedDeviceStableId || null,
                    friendly_name: sensorName,
                    sensor_type: 'sensor',
                    device_class: sensor.device_class || 'none',
                    state_class: (hasDeviceClass && hasUnit) ? 'measurement' : 'none',
                    unit_of_measurement: hasUnit ? sensor.unit_of_measurement : null,
                    icon: sensor.icon || 'mdi:eye',
                    target_app: wizard.selectedApp?.package || null,
                    source: {
                        source_type: 'element',
                        element_index: sensor.element?.index || 0,
                        element_text: sensor.element?.text || null,
                        element_class: sensor.element?.class || null,
                        element_resource_id: sensor.element?.resource_id || null,
                        screen_activity: wizard.recorder?.currentScreenActivity || wizard.currentActivity || null,
                        custom_bounds: sensor.element?.bounds || null
                    },
                    extraction_rule: {
                        method: 'exact',
                        extract_numeric: hasDeviceClass && ['battery', 'temperature', 'humidity', 'voltage', 'current', 'power', 'energy'].includes(sensor.device_class)
                    }
                };

                // Create sensor via API (will auto-reuse if matching sensor exists)
                const response = await wizard.apiClient.post('/sensors', sensorData);

                // Get sensor_id from response
                const sensorId = response?.sensor?.sensor_id || response?.sensor_id;
                if (!sensorId) {
                    throw new Error('No sensor_id in response');
                }

                // Create capture_sensors step with sensor_ids (not inline sensors)
                const sensorStep = {
                    step_type: 'capture_sensors',
                    description: `Capture: ${sensorName}`,
                    sensor_ids: [sensorId]
                };
                wizard.recorder.addStep(sensorStep);

                if (response?.reused) {
                    reusedCount++;
                } else {
                    createdCount++;
                }
            } catch (error) {
                console.error(`[Suggestions Batch] Failed to create sensor ${sensorName}:`, error);
                failedCount++;
            }
        }

        // Show summary toast
        const parts = [];
        if (createdCount > 0) parts.push(`${createdCount} created`);
        if (reusedCount > 0) parts.push(`${reusedCount} reused`);
        if (failedCount > 0) parts.push(`${failedCount} failed`);
        showToast(`Sensors: ${parts.join(', ')}`, failedCount > 0 ? 'warning' : 'success');
    } else {
        // Add actions to flow
        for (const action of selectedItems) {
            if (action.element?.bounds) {
                const tapStep = {
                    step_type: 'tap',
                    x: Math.round(action.element.bounds.x + action.element.bounds.width / 2),
                    y: Math.round(action.element.bounds.y + action.element.bounds.height / 2),
                    description: action.name || action.suggested_name || 'Tap action',
                    element: buildElementMetadata(action.element)
                };
                wizard.recorder.addStep(tapStep);
            }
        }
        showToast(`Added ${selectedItems.length} action(s) to flow`, 'success');
    }

    // Update UI and clear selection
    wizard.updateFlowStepsUI();
    wizard._selectedSuggestions.clear();
    renderSuggestionsContent(wizard);
    updateSelectedCount(wizard);

    // Switch to flow tab to show added items
    switchToTab(wizard, 'flow');
}

/**
 * Handle Smart Suggestions button click
 * Shows AI-powered sensor suggestions in the inline Suggestions tab
 */
export async function handleSmartSuggestions(wizard) {
    if (!wizard.selectedDevice) {
        showToast('Please select a device first', 'warning');
        return;
    }

    // Switch to the Suggestions tab
    switchToTab(wizard, 'suggestions');

    // Initialize suggestions tab if not already done
    if (!wizard._suggestionsTabInitialized) {
        setupSuggestionsTab(wizard);
        wizard._suggestionsTabInitialized = true;
    }

    // Trigger a refresh to load suggestions
    await loadSuggestions(wizard);
}

/**
 * Handle bulk sensor addition from Smart Suggestions
 * Creates actual sensors via API and adds capture_sensors steps with sensor_ids
 */
async function handleBulkSensorAddition(wizard, sensors) {
    console.log('[FlowWizard] Adding bulk sensors:', sensors);

    if (sensors.length === 0) return;

    // Build a dummy step to check for screen mismatch (using first sensor's element)
    const firstSensor = sensors[0];
    const dummyStep = {
        step_type: 'capture_sensors',
        description: `Capture: ${firstSensor.name}`,
        element: firstSensor.element
    };

    // Check for screen mismatch on first sensor (all sensors are from same screen)
    const mismatchInfo = await checkScreenMismatch(wizard, dummyStep);

    if (mismatchInfo) {
        // Show dialog asking about navigation step
        const choice = await showNavigationMismatchDialog(wizard, mismatchInfo);

        if (choice === 'cancel') {
            showToast('Bulk sensor addition cancelled', 'info');
            return;
        }

        // If user chose to add navigation step, add it first
        if (choice === 'add_nav' && wizard._lastExecutedAction) {
            const navStep = { ...wizard._lastExecutedAction };
            delete navStep._timestamp;
            wizard.recorder.addStep(navStep);
            console.log('[FlowWizard] Added navigation step before bulk sensors:', navStep);
        }
    }

    // Create actual sensors via API and add capture steps
    let createdCount = 0;
    let reusedCount = 0;
    let failedCount = 0;

    for (const sensor of sensors) {
        const sensorName = sensor.name || 'Sensor';

        try {
            // Build sensor definition for API
            // Note: state_class='measurement' requires unit_of_measurement
            const hasUnit = sensor.unit_of_measurement && sensor.unit_of_measurement.trim() !== '';
            const hasDeviceClass = sensor.device_class && sensor.device_class !== 'none';
            const sensorData = {
                device_id: wizard.selectedDevice,
                stable_device_id: wizard.selectedDeviceStableId || null,
                friendly_name: sensorName,
                sensor_type: 'sensor',
                device_class: sensor.device_class || 'none',
                state_class: (hasDeviceClass && hasUnit) ? 'measurement' : 'none',
                unit_of_measurement: hasUnit ? sensor.unit_of_measurement : null,
                icon: sensor.icon || 'mdi:eye',
                target_app: wizard.selectedApp?.package || null,
                source: {
                    source_type: 'element',
                    element_index: sensor.element?.index || 0,
                    element_text: sensor.element?.text || null,
                    element_class: sensor.element?.class || null,
                    element_resource_id: sensor.element?.resource_id || null,
                    screen_activity: wizard.recorder?.currentScreenActivity || wizard.currentActivity || null,
                    custom_bounds: sensor.element?.bounds || null
                },
                extraction_rule: {
                    method: 'exact',
                    extract_numeric: hasDeviceClass && ['battery', 'temperature', 'humidity', 'voltage', 'current', 'power', 'energy'].includes(sensor.device_class)
                }
            };

            // Create sensor via API (will auto-reuse if matching sensor exists)
            const response = await wizard.apiClient.post('/sensors', sensorData);

            // Get sensor_id from response
            const sensorId = response?.sensor?.sensor_id || response?.sensor_id;
            if (!sensorId) {
                throw new Error('No sensor_id in response');
            }

            // Create capture_sensors step with sensor_ids (not inline sensors)
            const sensorStep = {
                step_type: 'capture_sensors',
                description: `Capture: ${sensorName}`,
                sensor_ids: [sensorId]
            };
            wizard.recorder.addStep(sensorStep);

            if (response?.reused) {
                reusedCount++;
            } else {
                createdCount++;
            }
        } catch (error) {
            console.error(`[Bulk Sensors] Failed to create sensor ${sensorName}:`, error);
            failedCount++;
        }
    }

    // Update UI
    wizard.updateFlowStepsUI();

    // Show summary toast
    const parts = [];
    if (createdCount > 0) parts.push(`${createdCount} created`);
    if (reusedCount > 0) parts.push(`${reusedCount} reused`);
    if (failedCount > 0) parts.push(`${failedCount} failed`);
    showToast(`Sensors: ${parts.join(', ')}`, failedCount > 0 ? 'warning' : 'success');
}

/**
 * Update tree with new elements
 */
export function updateElementTree(wizard, elements) {
    // Element tree is always visible in right panel
    if (wizard.elementTree) {
        wizard.elementTree.setElements(elements);
    }
}

// ==========================================
// Zoom/Scale Methods
// ==========================================

/**
 * Toggle scale mode (fit vs 1:1)
 */
export function toggleScale(wizard) {
    wizard.scaleMode = wizard.canvasRenderer.toggleScale();

    const btn = document.getElementById('qabScale');
    if (btn) {
        btn.classList.toggle('active', wizard.scaleMode === '1:1');
        btn.title = wizard.scaleMode === 'fit' ? 'Toggle 1:1 Scale' : 'Toggle Fit to Screen';
    }

    console.log(`[FlowWizard] Scale mode: ${wizard.scaleMode}`);
    // In streaming mode, just apply CSS zoom - don't re-render screenshot
    if (wizard.captureMode === 'streaming') {
        wizard.canvasRenderer.applyZoom();
    } else {
        updateScreenshotDisplay(wizard);
    }
}

/**
 * Zoom in
 */
export function zoomIn(wizard) {
    const zoomLevel = wizard.canvasRenderer.zoomIn();
    updateZoomDisplay(wizard, zoomLevel);
    // In streaming mode, just apply CSS zoom - don't re-render screenshot
    if (wizard.captureMode === 'streaming') {
        wizard.canvasRenderer.applyZoom();
    } else {
        updateScreenshotDisplay(wizard);
    }
}

/**
 * Zoom out
 */
export function zoomOut(wizard) {
    const zoomLevel = wizard.canvasRenderer.zoomOut();
    updateZoomDisplay(wizard, zoomLevel);
    // In streaming mode, just apply CSS zoom - don't re-render screenshot
    if (wizard.captureMode === 'streaming') {
        wizard.canvasRenderer.applyZoom();
    } else {
        updateScreenshotDisplay(wizard);
    }
}

/**
 * Reset zoom to 100%
 */
export function resetZoom(wizard) {
    const zoomLevel = wizard.canvasRenderer.resetZoom();
    updateZoomDisplay(wizard, zoomLevel);
    // In streaming mode, just apply CSS zoom - don't re-render screenshot
    if (wizard.captureMode === 'streaming') {
        wizard.canvasRenderer.applyZoom();
    } else {
        updateScreenshotDisplay(wizard);
    }
}

/**
 * Update zoom level display
 */
export function updateZoomDisplay(wizard, zoomLevel) {
    const display = document.getElementById('zoomLevel');
    if (display) {
        display.textContent = `${Math.round(zoomLevel * 100)}%`;
    }
}

/**
 * Fit to screen - reset zoom and set fit mode
 */
export function fitToScreen(wizard) {
    const zoomLevel = wizard.canvasRenderer.fitToScreen();
    updateZoomDisplay(wizard, zoomLevel);
    wizard.scaleMode = 'fit';
    console.log('[FlowWizard] Fit to screen');
}

// ==========================================
// Recording Toggle
// ==========================================

/**
 * Toggle recording pause/resume
 * When paused, gestures are executed but not recorded to the flow
 */
export function toggleRecording(wizard) {
    wizard.recordingPaused = !wizard.recordingPaused;

    const btn = document.getElementById('qabRecordToggle');
    const label = btn?.querySelector('.btn-label');
    const icon = btn?.querySelector('.btn-icon');

    if (wizard.recordingPaused) {
        btn?.classList.remove('recording-active');
        btn?.classList.add('recording-paused');
        if (label) label.textContent = 'Paused';
        if (icon) icon.textContent = '⏸';
        showToast('Recording paused - actions will not be saved', 'info', 2000);
    } else {
        btn?.classList.remove('recording-paused');
        btn?.classList.add('recording-active');
        if (label) label.textContent = 'Recording';
        if (icon) icon.textContent = '⏺';
        showToast('Recording resumed', 'success', 2000);
    }

    console.log(`[FlowWizard] Recording ${wizard.recordingPaused ? 'paused' : 'resumed'}`);
}

// ==========================================
// Element Interaction Methods (Continued)
// ==========================================

/**
 * Handle element click on canvas
 */
export async function handleElementClick(wizard, canvasX, canvasY) {
    // Convert canvas coordinates to device coordinates (use appropriate converter)
    let deviceCoords;
    if (wizard.captureMode === 'streaming' && wizard.liveStream) {
        deviceCoords = wizard.liveStream.canvasToDevice(canvasX, canvasY);
    } else {
        deviceCoords = wizard.canvasRenderer.canvasToDevice(canvasX, canvasY);
    }

    // Find clicked element from metadata (use appropriate element source)
    const elements = wizard.captureMode === 'streaming'
        ? wizard.liveStream?.elements
        : wizard.recorder.screenshotMetadata?.elements;
    const clickedElement = wizard.interactions.findElementAtCoordinates(
        elements,
        deviceCoords.x,
        deviceCoords.y,
        {
            hideContainers: wizard.overlayFilters.hideContainers,
            hideEmptyElements: wizard.overlayFilters.hideEmptyElements
        }
    );

    // Handle timestamp element selection for wait step
    if (wizard._waitingForTimestampElement && wizard._pendingWaitStep) {
        if (!clickedElement) {
            showToast('Please tap on an element with text (e.g., a timestamp)', 'warning', 3000);
            return;
        }

        // Build timestamp element config
        const timestampElement = {
            text: clickedElement.text || null,
            'resource-id': clickedElement.resource_id || null,
            class: clickedElement.class || null,
            bounds: clickedElement.bounds || null
        };

        // Add timestamp element to the pending wait step
        wizard._pendingWaitStep.timestamp_element = timestampElement;

        // Add the complete wait step to the recorder
        wizard.recorder.addStep(wizard._pendingWaitStep);

        const elementName = clickedElement.text?.substring(0, 30) || clickedElement.resource_id?.split('/').pop() || 'element';
        showToast(`Wait step added - will monitor "${elementName}" for changes`, 'success', 3000);

        // Clear the pending state
        wizard._waitingForTimestampElement = false;
        wizard._pendingWaitStep = null;
        return;
    }

    // Show selection dialog
    const choice = await wizard.interactions.showElementSelectionDialog(clickedElement, deviceCoords);

    if (!choice) {
        return; // User cancelled
    }

    // NOTE: Dialogs module is already imported at module level (line 36)
    // Removed redundant dynamic import that was shadowing the static import

    // Execute based on choice - wrapped in try-catch to catch silent errors
    try {
        switch (choice.type) {
        case 'tap':
            await executeTap(wizard, deviceCoords.x, deviceCoords.y, clickedElement);
            // Only update screenshot in polling mode - streaming updates automatically
            if (wizard.captureMode !== 'streaming') {
                updateScreenshotDisplay(wizard);
            }
            break;

        case 'type':
            const text = await wizard.interactions.promptForText();
            if (text) {
                await executeTap(wizard, deviceCoords.x, deviceCoords.y, clickedElement);
                await wizard.recorder.typeText(text);
                // Only update screenshot in polling mode - streaming updates automatically
                if (wizard.captureMode !== 'streaming') {
                    updateScreenshotDisplay(wizard);
                }
            }
            break;

        case 'sensor_text':
            // Use element.index if available, otherwise default to 0
            await Dialogs.createTextSensor(wizard, clickedElement, deviceCoords, clickedElement?.index ?? 0);
            break;

        case 'sensor_image':
            // Create fallback element if none was detected at coordinates
            const sensorElement = clickedElement || {
                class: 'Unknown',
                text: '',
                bounds: { x: deviceCoords.x - 50, y: deviceCoords.y - 25, width: 100, height: 50 },
                index: 0
            };
            await Dialogs.createImageSensor(wizard, sensorElement, deviceCoords, sensorElement.index ?? 0);
            break;

        case 'action':
            await Dialogs.createAction(wizard, clickedElement, deviceCoords);
            break;

        case 'refresh':
            await handleRefreshWithRetries(wizard);
            break;
        }
    } catch (error) {
        console.error('[FlowWizard] handleElementClick error:', error);
        showToast('Operation failed - see console for details', 'error');
    }
}

/**
 * Convert canvas coordinates to device coordinates
 */
export function canvasToDevice(wizard, canvasX, canvasY) {
    if (!wizard.currentImage || !wizard.canvas.width) {
        console.warn('[FlowWizard] No screenshot loaded');
        return { x: Math.round(canvasX), y: Math.round(canvasY) };
    }

    // Canvas is 1:1 with device (no scaling), so coordinates are direct
    return {
        x: Math.round(canvasX),
        y: Math.round(canvasY)
    };
}

/**
 * Execute tap on device and add to flow
 */
export async function executeTap(wizard, x, y, element = null) {
    // Show tap indicator on canvas
    showTapIndicator(wizard, x, y);

    // Capture screen context BEFORE executing action (so step is linked to source screen)
    let screenContext = {};
    if (wizard.recorder) {
        try {
            const screenInfo = await wizard.recorder.getCurrentScreen();
            if (screenInfo?.activity) {
                screenContext = {
                    screen_activity: screenInfo.activity.activity || null,
                    screen_package: screenInfo.activity.package || null
                };
                console.log(`[FlowWizard] Captured pre-tap context: ${screenContext.screen_activity}`);
            }
        } catch (e) {
            console.warn('[FlowWizard] Failed to capture pre-tap screen context:', e);
        }
    }

    // Execute tap if in execute mode
    if (wizard.recordMode === 'execute') {
        await wizard.recorder.executeTap(x, y);
    }

    // Build step description
    let description = `Tap at (${x}, ${y})`;
    if (element) {
        if (element.text) {
            description = `Tap "${element.text}"`;
        } else if (element.content_desc) {
            description = `Tap "${element.content_desc}"`;
        } else if (element.resource_id) {
            const shortId = element.resource_id.split('/').pop() || element.resource_id;
            description = `Tap ${shortId}`;
        }
    }

    // Add tap step to flow with optional element metadata
    const step = {
        step_type: 'tap',
        x: x,
        y: y,
        description: description,
        // Include pre-captured screen context
        ...screenContext
    };

    // Include element metadata if available
    if (element) {
        step.element = buildElementMetadata(element);
    }

    // Track last executed action (even when paused) for navigation step insertion
    wizard._lastExecutedAction = { ...step, _timestamp: Date.now() };

    // Add step to flow (unless recording is paused)
    if (!wizard.recordingPaused) {
        wizard.recorder.addStep(step);
    }

    // Clear stale elements and hover highlight immediately
    // This prevents old screen's elements/highlight from being shown on new screen
    clearAllElementsAndHover(wizard);

    // Handle post-tap refresh based on mode
    if (wizard.recordMode === 'execute' && wizard.captureMode !== 'streaming') {
        // Polling mode + execute: Single screenshot capture (wait for UI to settle)
        await wizard.recorder.wait(500);
        await wizard.recorder.captureScreenshot();
        // Don't call refreshAfterAction - we just captured, avoid double fetch
    } else {
        // Streaming mode or non-execute: Use refreshAfterAction
        // Streaming: refreshes elements only (fast endpoint)
        // Non-execute: lets refreshAfterAction handle the screenshot
        refreshAfterAction(wizard, 500);
    }
}

/**
 * Show visual tap indicator on canvas
 * @param {FlowWizard} wizard - Wizard instance
 * @param {number} x - Device X coordinate
 * @param {number} y - Device Y coordinate
 */
export function showTapIndicator(wizard, x, y) {
    // Convert device coords to canvas coords for drawing
    // In streaming mode, canvas may be at different resolution than device
    let canvasX = x, canvasY = y;
    if (wizard.captureMode === 'streaming' && wizard.liveStream?.deviceToCanvas) {
        const canvasCoords = wizard.liveStream.deviceToCanvas(x, y);
        canvasX = canvasCoords.x;
        canvasY = canvasCoords.y;
    }

    wizard.canvasRenderer.showTapIndicator(canvasX, canvasY);

    // Redraw screenshot after short delay to clear tap indicator
    // In streaming mode, the next frame will naturally clear it
    if (wizard.captureMode !== 'streaming') {
        setTimeout(() => {
            updateScreenshotDisplay(wizard);
        }, 300);
    }
}

/**
 * Find element at coordinates
 */
export function findElementAtCoordinates(wizard, x, y) {
    if (!wizard.recorder.screenshotMetadata?.elements) {
        return null;
    }

    // Find element that contains the coordinates
    const elements = wizard.recorder.screenshotMetadata.elements;

    for (const el of elements) {
        const bounds = el.bounds || {};
        const elX = bounds.x || 0;
        const elY = bounds.y || 0;
        const elWidth = bounds.width || 0;
        const elHeight = bounds.height || 0;

        if (x >= elX && x <= elX + elWidth &&
            y >= elY && y <= elY + elHeight) {
            return el;
        }
    }

    return null;
}

/**
 * Show element selection dialog
 */
export async function showElementSelectionDialog(wizard, element, coords) {
    // Delegate to FlowInteractions module
    return await wizard.interactions.showElementSelectionDialog(element, coords);
}

// ==========================================
// Screenshot Display Methods (Continued)
// ==========================================

/**
 * Handle refresh with retries
 */
export async function handleRefreshWithRetries(wizard) {
    // Prompt for refresh configuration
    const config = await wizard.interactions.promptForRefreshConfig();
    if (!config) return;

    const { attempts, delay } = config;

    console.log(`[FlowWizard] Refreshing ${attempts} times with ${delay}ms delay`);

    // Perform multiple refreshes
    for (let i = 0; i < attempts; i++) {
        showToast(`Refresh ${i + 1}/${attempts}...`, 'info', 1000);
        await wizard.recorder.refresh(false); // Don't add step yet
        updateScreenshotDisplay(wizard);

        // Wait between attempts (except after the last one)
        if (i < attempts - 1) {
            await wizard.recorder.wait(delay);
        }
    }

    // Add a single wait step representing the total refresh operation (unless recording is paused)
    if (!wizard.recordingPaused) {
        const totalDuration = (attempts - 1) * delay + 500; // 500ms for screenshot capture
        wizard.recorder.addStep({
            step_type: 'wait',
            duration: totalDuration,
            refresh_attempts: attempts,
            refresh_delay: delay,
            description: `Wait for UI update (${attempts} refreshes, ${delay}ms delay)`
        });
    }

    showToast(`Completed ${attempts} refresh attempts`, 'success', 2000);
}

/**
 * Update screenshot display
 */
export async function updateScreenshotDisplay(wizard) {
    const dataUrl = wizard.recorder.getScreenshotDataUrl();
    const metadata = wizard.recorder.screenshotMetadata;

    try {
        // Render using canvas renderer module
        const { displayWidth, displayHeight, scale } = await wizard.canvasRenderer.render(dataUrl, metadata);

        // Store scale for coordinate mapping
        wizard.currentScale = scale;

        // Update element tree and count if metadata available
        if (metadata && metadata.elements && metadata.elements.length > 0) {
            updateElementTree(wizard, metadata.elements);
            updateElementCount(wizard, metadata.elements.length);
        }

        // Phase 1 Screen Awareness: Update screen info after each screenshot
        updateScreenInfo(wizard);

        // Hide loading overlay
        hideLoadingOverlay(wizard);

    } catch (error) {
        console.error('[FlowWizard] Failed to render screenshot:', error);
        showLoadingOverlay(wizard, 'Error loading screenshot');
    }
}

/**
 * Show loading overlay on screenshot
 */
export function showLoadingOverlay(wizard, text = 'Loading...') {
    const overlay = document.getElementById('screenshotLoading');
    if (overlay) {
        const textEl = overlay.querySelector('.loading-text');
        if (textEl) textEl.textContent = text;
        overlay.classList.add('visible');
    }
}

/**
 * Hide loading overlay
 */
export function hideLoadingOverlay(wizard) {
    const overlay = document.getElementById('screenshotLoading');
    if (overlay) {
        overlay.classList.remove('visible');
    }
}

// ==========================================
// Flow UI Update Methods
// ==========================================

/**
 * Update element count badge
 */
export function updateElementCount(wizard, count) {
    const badge = document.getElementById('elementCount');
    if (badge) badge.textContent = count;
}

/**
 * Update flow steps UI
 */
export function updateFlowStepsUI(wizard) {
    const badge = document.getElementById('stepCount');
    const steps = wizard.recorder?.getSteps() || [];
    if (badge) badge.textContent = steps.length;

    // Update step manager display
    if (wizard.stepManager) {
        wizard.stepManager.render(steps);
    }
}

// ==========================================
// Preview Overlay Methods
// ==========================================

/**
 * Show preview overlay with screenshot method selection
 */
export function showPreviewOverlay(wizard) {
    // Remove existing overlay if any
    hidePreviewOverlay(wizard);

    const overlay = document.createElement('div');
    overlay.id = 'previewOverlay';
    overlay.style.cssText = `
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.6);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        z-index: 1000;
        backdrop-filter: blur(2px);
    `;

    const messageBox = document.createElement('div');
    messageBox.style.cssText = `
        background: white;
        padding: 30px 40px;
        border-radius: 12px;
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
        max-width: 500px;
        text-align: center;
    `;

    const title = document.createElement('h3');
    title.textContent = '📸 Preview of Current Screen';
    title.style.cssText = 'margin: 0 0 15px; color: #1f2937; font-size: 20px;';

    const description = document.createElement('p');
    description.textContent = 'This is a quick preview. Choose your capture method to begin recording:';
    description.style.cssText = 'margin: 0 0 25px; color: #6b7280; font-size: 14px; line-height: 1.5;';

    const buttonContainer = document.createElement('div');
    buttonContainer.style.cssText = 'display: flex; gap: 12px; justify-content: center;';

    const regularBtn = document.createElement('button');
    regularBtn.textContent = '📋 Regular Screenshot';
    regularBtn.className = 'btn btn-primary';
    regularBtn.style.cssText = 'padding: 12px 24px; font-size: 14px;';
    regularBtn.onclick = () => chooseRegularScreenshot(wizard);

    const stitchBtn = document.createElement('button');
    stitchBtn.textContent = '🧩 Stitch Capture';
    stitchBtn.className = 'btn btn-secondary';
    stitchBtn.style.cssText = 'padding: 12px 24px; font-size: 14px;';
    stitchBtn.onclick = () => chooseStitchCapture(wizard);

    buttonContainer.appendChild(regularBtn);
    buttonContainer.appendChild(stitchBtn);

    messageBox.appendChild(title);
    messageBox.appendChild(description);
    messageBox.appendChild(buttonContainer);
    overlay.appendChild(messageBox);

    // Add to screenshot container
    const screenshotContainer = document.getElementById('screenshotContainer');
    if (screenshotContainer) {
        screenshotContainer.appendChild(overlay);
        console.log('[FlowWizard] Preview overlay shown');
    }
}

/**
 * Hide preview overlay
 */
export function hidePreviewOverlay(wizard) {
    const overlay = document.getElementById('previewOverlay');
    if (overlay) {
        overlay.remove();
        console.log('[FlowWizard] Preview overlay hidden');
    }
}

/**
 * User chose regular screenshot - capture with UI elements
 */
export async function chooseRegularScreenshot(wizard) {
    hidePreviewOverlay(wizard);

    try {
        await wizard.recorder.captureScreenshot();
        await updateScreenshotDisplay(wizard);
        showToast(`Full screenshot captured! (${wizard.recorder.screenshotMetadata?.elements?.length || 0} UI elements)`, 'success', 3000);
    } catch (error) {
        console.error('[FlowWizard] Regular screenshot failed:', error);
        showToast(`Screenshot failed: ${error.message}`, 'error', 3000);
    }
}

/**
 * User chose stitch capture - capture stitched screenshot
 */
export async function chooseStitchCapture(wizard) {
    hidePreviewOverlay(wizard);

    try {
        await wizard.recorder.stitchCapture();
        await updateScreenshotDisplay(wizard);
    } catch (error) {
        console.error('[FlowWizard] Stitch capture failed:', error);
        // Error already handled by stitchCapture()
    }
}

// ==========================================
// Sidebar Methods
// ==========================================

/**
 * Collapse the element sidebar
 */
export function collapseSidebar(wizard) {
    const sidebar = document.getElementById('elementSidebar');
    const expandBtn = document.getElementById('btnExpandSidebar');
    const layout = document.querySelector('.recording-layout');

    if (sidebar) {
        sidebar.classList.add('collapsed');
    }
    if (expandBtn) {
        expandBtn.style.display = 'block';
    }
    if (layout) {
        layout.classList.add('sidebar-collapsed');
    }

    console.log('[FlowWizard] Sidebar collapsed');
}

/**
 * Expand the element sidebar
 */
export function expandSidebar(wizard) {
    const sidebar = document.getElementById('elementSidebar');
    const expandBtn = document.getElementById('btnExpandSidebar');
    const layout = document.querySelector('.recording-layout');

    if (sidebar) {
        sidebar.classList.remove('collapsed');
    }
    if (expandBtn) {
        expandBtn.style.display = 'none';
    }
    if (layout) {
        layout.classList.remove('sidebar-collapsed');
    }

    console.log('[FlowWizard] Sidebar expanded');
}

// ==========================================
// Element Panel Methods
// ==========================================

/**
 * Update element panel with current elements
 */
export function updateElementPanel(wizard, elements) {
    const panel = document.getElementById('elementList');
    if (!panel) {
        console.warn('[FlowWizard] Element list container not found');
        return;
    }

    // Store all elements for filtering
    wizard.allElements = elements || [];

    // Setup search and filter event listeners (once)
    if (!wizard.elementFiltersInitialized) {
        setupElementFilters(wizard);
        wizard.elementFiltersInitialized = true;
    }

    // Apply filters and render
    renderFilteredElements(wizard);
}

/**
 * Setup element filters
 */
export function setupElementFilters(wizard) {
    const searchInput = document.getElementById('elementSearchInput');
    const clickableFilter = document.getElementById('filterSidebarClickable');
    const textFilter = document.getElementById('filterSidebarText');

    if (searchInput) {
        searchInput.addEventListener('input', () => renderFilteredElements(wizard));
    }
    if (clickableFilter) {
        clickableFilter.addEventListener('change', () => renderFilteredElements(wizard));
    }
    if (textFilter) {
        textFilter.addEventListener('change', () => renderFilteredElements(wizard));
    }
}

/**
 * Render filtered elements
 */
export function renderFilteredElements(wizard) {
    const panel = document.getElementById('elementList');
    if (!panel) return;

    const searchInput = document.getElementById('elementSearchInput');
    const clickableFilter = document.getElementById('filterSidebarClickable');
    const textFilter = document.getElementById('filterSidebarText');

    const searchTerm = searchInput?.value.toLowerCase() || '';
    const showClickable = clickableFilter?.checked !== false;
    const showWithText = textFilter?.checked !== false;

    if (!wizard.allElements || wizard.allElements.length === 0) {
        panel.innerHTML = '<div class="empty-state">No elements detected in screenshot</div>';
        return;
    }

    // Apply filters (OR logic: show if matches ANY checked filter)
    let filteredElements = wizard.allElements.filter(el => {
        // If both filters are off, show all
        if (!showClickable && !showWithText) return true;

        // Show if matches any checked filter
        const isClickable = el.clickable;
        const hasText = el.text && el.text.trim().length > 0;

        if (showClickable && isClickable) return true;
        if (showWithText && hasText) return true;

        return false;
    });

    // Apply search
    if (searchTerm) {
        filteredElements = filteredElements.filter(el => {
            const displayText = (el.text || el.content_desc || el.resource_id || '').toLowerCase();
            return displayText.includes(searchTerm);
        });
    }

    const interactiveElements = filteredElements;

    console.log(`[FlowWizard] Rendering ${interactiveElements.length} interactive elements (${wizard.allElements.length} total)`);

    panel.innerHTML = interactiveElements.map((el, index) => {
        const displayText = el.text || el.content_desc || el.resource_id?.split('/').pop() || `Element ${index}`;
        const isClickable = el.clickable === true || el.clickable === 'true';
        const icon = isClickable ? '🔘' : '📝';
        const typeLabel = isClickable ? 'Clickable' : 'Text';

        // Determine preview value (what would be captured as sensor)
        const previewValue = el.text || el.content_desc || el.resource_id || '';
        const hasPreview = previewValue.trim().length > 0;
        const truncatedPreview = previewValue.length > 50
            ? previewValue.substring(0, 50) + '...'
            : previewValue;

        return `
            <div class="element-item" data-element-index="${index}">
                <div class="element-item-header">
                    <span class="element-icon">${icon}</span>
                    <div class="element-info">
                        <div class="element-text">${displayText}</div>
                        <div class="element-meta">${typeLabel} • ${el.class?.split('.').pop() || 'Unknown'}</div>
                    </div>
                </div>
                ${hasPreview ? `
                <div class="element-preview" title="${previewValue}">
                    <span class="preview-label">Preview:</span>
                    <span class="preview-value">${truncatedPreview}</span>
                </div>
                ` : ''}
                <div class="element-actions">
                    <button class="btn-element-action btn-tap" data-index="${index}" title="Add tap step">
                        👆 Tap
                    </button>
                    <button class="btn-element-action btn-type" data-index="${index}" title="Add type step">
                        ⌨️ Type
                    </button>
                    <button class="btn-element-action btn-sensor" data-index="${index}" title="Add sensor capture">
                        📊 Sensor
                    </button>
                    <button class="btn-element-action btn-action" data-index="${index}" title="Execute saved action">
                        ⚡ Action
                    </button>
                </div>
            </div>
        `;
    }).join('');

    // Bind action buttons - delegate to element actions module
    // These will be imported dynamically when needed
    panel.querySelectorAll('.btn-tap').forEach(btn => {
        btn.addEventListener('click', async () => {
            const index = parseInt(btn.dataset.index);
            const ElementActions = await import('./flow-wizard-element-actions.js?v=0.4.0-beta.3.2');
            await ElementActions.addTapStepFromElement(wizard, interactiveElements[index]);
        });
    });

    panel.querySelectorAll('.btn-type').forEach(btn => {
        btn.addEventListener('click', async () => {
            const index = parseInt(btn.dataset.index);
            const ElementActions = await import('./flow-wizard-element-actions.js?v=0.4.0-beta.3.2');
            await ElementActions.addTypeStepFromElement(wizard, interactiveElements[index]);
        });
    });

    panel.querySelectorAll('.btn-sensor').forEach(btn => {
        btn.addEventListener('click', async () => {
            const index = parseInt(btn.dataset.index);
            const ElementActions = await import('./flow-wizard-element-actions.js?v=0.4.0-beta.3.2');
            await ElementActions.addSensorCaptureFromElement(wizard, interactiveElements[index], index);
        });
    });

    panel.querySelectorAll('.btn-action').forEach(btn => {
        btn.addEventListener('click', async () => {
            const index = parseInt(btn.dataset.index);
            const Dialogs = await import('./flow-wizard-dialogs.js?v=0.4.0-beta.3.2');
            await Dialogs.addActionStepFromElement(wizard, interactiveElements[index]);
        });
    });
}

// ==========================================
// Drawing Methods
// ==========================================

/**
 * Draw UI element overlays on canvas
 */
export function drawElementOverlays(wizard) {
    if (!wizard.currentImage || !wizard.recorder.screenshotMetadata) {
        console.warn('[FlowWizard] Cannot draw overlays: no screenshot loaded');
        return;
    }

    // Redraw the screenshot image first (to clear old overlays)
    wizard.ctx.drawImage(wizard.currentImage, 0, 0);

    const elements = wizard.recorder.screenshotMetadata.elements || [];

    // Count elements by type
    const clickableElements = elements.filter(e => e.clickable === true);
    const nonClickableElements = elements.filter(e => e.clickable === false || e.clickable === undefined);

    console.log(`[FlowWizard] Drawing ${elements.length} elements (${clickableElements.length} clickable, ${nonClickableElements.length} non-clickable)`);
    console.log('[FlowWizard] Overlay filters:', wizard.overlayFilters);

    let visibleCount = 0;
    let drawnCount = 0;
    let filteredClickable = 0;
    let filteredNonClickable = 0;
    let drawnClickable = 0;
    let drawnNonClickable = 0;

    elements.forEach(el => {
        // Only draw elements with bounds
        if (!el.bounds) {
            return;
        }

        visibleCount++;

        // Apply filters (same as screenshot-capture.js)
        if (el.clickable && !wizard.overlayFilters.showClickable) {
            filteredClickable++;
            return;
        }
        if (!el.clickable && !wizard.overlayFilters.showNonClickable) {
            filteredNonClickable++;
            return;
        }

        // Filter by size (hide small elements < 50px width or height)
        if (wizard.overlayFilters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) {
            if (el.clickable) filteredClickable++; else filteredNonClickable++;
            return;
        }

        // Filter: text elements only
        if (wizard.overlayFilters.textOnly && (!el.text || !el.text.trim())) {
            if (el.clickable) filteredClickable++; else filteredNonClickable++;
            return;
        }

        // Get coordinates (no scaling - 1:1)
        const x = el.bounds.x;
        const y = el.bounds.y;
        const w = el.bounds.width;
        const h = el.bounds.height;

        // Skip elements outside canvas
        if (x + w < 0 || x > wizard.canvas.width || y + h < 0 || y > wizard.canvas.height) {
            return;
        }

        // Draw bounding box
        // Green for clickable, blue for non-clickable (matching flow-wizard colors)
        wizard.ctx.strokeStyle = el.clickable ? '#22c55e' : '#3b82f6';
        wizard.ctx.fillStyle = el.clickable ? 'rgba(34, 197, 94, 0.1)' : 'rgba(59, 130, 246, 0.1)';
        wizard.ctx.lineWidth = 2;

        // Fill background
        wizard.ctx.fillRect(x, y, w, h);

        // Draw border
        wizard.ctx.strokeRect(x, y, w, h);
        drawnCount++;
        if (el.clickable) drawnClickable++; else drawnNonClickable++;

        // Draw text label if element has text (and labels are enabled)
        if (wizard.overlayFilters.showTextLabels && el.text && el.text.trim()) {
            drawTextLabel(wizard, el.text, x, y, w, el.clickable);
        }
    });

    console.log(`[FlowWizard] Total visible: ${visibleCount}`);
    console.log(`[FlowWizard] Filtered: ${filteredClickable + filteredNonClickable} (${filteredClickable} clickable, ${filteredNonClickable} non-clickable)`);
    console.log(`[FlowWizard] Drawn: ${drawnCount} (${drawnClickable} clickable, ${drawnNonClickable} non-clickable)`);
}

/**
 * Draw UI element overlays with scaling
 */
export function drawElementOverlaysScaled(wizard, scale) {
    if (!wizard.currentImage || !wizard.recorder.screenshotMetadata) {
        console.warn('[FlowWizard] Cannot draw overlays: no screenshot loaded');
        return;
    }

    const elements = wizard.recorder.screenshotMetadata.elements || [];

    elements.forEach(el => {
        if (!el.bounds) return;

        // Apply overlay filters
        if (el.clickable && !wizard.overlayFilters.showClickable) return;
        if (!el.clickable && !wizard.overlayFilters.showNonClickable) return;
        if (wizard.overlayFilters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) return;
        if (wizard.overlayFilters.textOnly && (!el.text || !el.text.trim())) return;

        // Scale coordinates
        const x = Math.floor(el.bounds.x * scale);
        const y = Math.floor(el.bounds.y * scale);
        const w = Math.floor(el.bounds.width * scale);
        const h = Math.floor(el.bounds.height * scale);

        // Skip elements outside canvas
        if (x + w < 0 || x > wizard.canvas.width || y + h < 0 || y > wizard.canvas.height) return;

        // Draw bounding box
        wizard.ctx.strokeStyle = el.clickable ? '#22c55e' : '#3b82f6';
        wizard.ctx.lineWidth = 2;
        wizard.ctx.strokeRect(x, y, w, h);

        // Draw text label if element has text and showTextLabels is enabled
        if (el.text && el.text.trim() && wizard.overlayFilters.showTextLabels) {
            drawTextLabel(wizard, el.text.trim(), x, y, w, el.clickable);
        }
    });
}

/**
 * Draw text label for UI element on canvas
 * Scales font size based on canvas width to look appropriate at all resolutions
 */
export function drawTextLabel(wizard, text, x, y, w, isClickable) {
    // Scale font based on canvas width (reference: 720px = 12px font)
    const scaleFactor = Math.max(0.6, Math.min(1.5, wizard.canvas.width / 720));
    const fontSize = Math.round(12 * scaleFactor);
    const labelHeight = Math.round(20 * scaleFactor);
    const charWidth = Math.round(7 * scaleFactor);
    const padding = Math.round(2 * scaleFactor);

    // Truncate long text
    const maxChars = Math.floor(w / charWidth); // Approximate chars that fit
    const displayText = text.length > maxChars
        ? text.substring(0, maxChars - 3) + '...'
        : text;

    // Draw background (matching element color)
    wizard.ctx.fillStyle = isClickable ? '#22c55e' : '#3b82f6';
    wizard.ctx.fillRect(x, y, w, labelHeight);

    // Draw text
    wizard.ctx.fillStyle = '#ffffff';
    wizard.ctx.font = `${fontSize}px monospace`;
    wizard.ctx.textBaseline = 'top';
    wizard.ctx.fillText(displayText, x + padding, y + padding);
}

/**
 * Wire up edit button click handler for a step element
 * Handles both sensor and action edit buttons
 */
function wireUpEditButton(stepEl, wizard) {
    // Handle sensor edit button
    const sensorBtn = stepEl.querySelector('.btn-edit-sensor');
    if (sensorBtn && !sensorBtn.dataset.wired) {
        sensorBtn.dataset.wired = 'true';
        sensorBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const sensorIds = e.target.dataset.sensorIds?.split(',') || [];
            if (sensorIds.length === 0) {
                showToast('No sensors linked to this step', 'warning');
                return;
            }

            const sensorId = sensorIds[0];
            try {
                const response = await fetch(`${window.API_BASE || '/api'}/sensors/${wizard.selectedDevice}/${sensorId}`);
                if (!response.ok) throw new Error('Sensor not found');
                const sensor = await response.json();

                if (wizard.sensorCreator) {
                    wizard.sensorCreator.show(wizard.selectedDevice, sensor.element || {}, 0, {
                        name: sensor.name,
                        entity_id: sensor.entity_id,
                        device_class: sensor.device_class || 'none',
                        unit: sensor.unit_of_measurement || '',
                        icon: sensor.icon || 'mdi:eye',
                        existingSensorId: sensorId,
                        stableDeviceId: wizard.selectedDeviceStableId || wizard.selectedDevice,
                        screenActivity: sensor.screen_activity,
                        targetApp: wizard.selectedApp?.package
                    });
                } else {
                    showToast('Opening sensor in new tab...', 'info');
                    window.open(`/sensors.html?edit=${sensorId}`, '_blank');
                }
            } catch (error) {
                console.error('[Step3] Error editing sensor:', error);
                showToast(`Could not load sensor: ${error.message}`, 'error');
            }
        });
    }

    // Handle action edit button
    const actionBtn = stepEl.querySelector('.btn-edit-action');
    if (actionBtn && !actionBtn.dataset.wired) {
        actionBtn.dataset.wired = 'true';
        actionBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const actionId = e.target.dataset.actionId;
            if (!actionId) {
                showToast('No action linked to this step', 'warning');
                return;
            }

            try {
                const response = await fetch(`${window.API_BASE || '/api'}/actions/${wizard.selectedDevice}/${actionId}`);
                if (!response.ok) throw new Error('Action not found');
                const action = await response.json();

                // Open action editor or navigate to actions page
                showToast('Opening action in new tab...', 'info');
                window.open(`/actions.html?edit=${actionId}`, '_blank');
            } catch (error) {
                console.error('[Step3] Error editing action:', error);
                showToast(`Could not load action: ${error.message}`, 'error');
            }
        });
    }
}

/**
 * Setup flow steps event listeners
 * Listens for flowStepAdded and flowStepRemoved events during recording
 */
export function setupFlowStepsListener(wizard) {
    const stepsList = document.getElementById('flowStepsList');

    window.addEventListener('flowStepAdded', (e) => {
        const { step, index } = e.detail;

        // Add edit button for capture_sensors or execute_action steps
        let editBtn = '';
        if (step.step_type === 'capture_sensors' && step.sensor_ids?.length) {
            editBtn = `<button class="btn btn-sm btn-edit-sensor" data-step-index="${index}" data-sensor-ids="${step.sensor_ids.join(',')}" title="Edit sensor">✏️</button>`;
        } else if (step.step_type === 'execute_action' && step.action_id) {
            editBtn = `<button class="btn btn-sm btn-edit-action" data-step-index="${index}" data-action-id="${step.action_id}" title="Edit action">✏️</button>`;
        }

        const stepHtml = `
            <div class="flow-step-item" data-step-index="${index}">
                <div class="step-number-badge">${index + 1}</div>
                <div class="step-content">
                    <div class="step-description">${step.description}</div>
                </div>
                <div class="step-actions">
                    ${editBtn}
                    <button class="btn btn-sm" onclick="window.flowWizard.recorder.removeStep(${index})">✕</button>
                </div>
            </div>
        `;

        stepsList.insertAdjacentHTML('beforeend', stepHtml);

        // Wire up edit button click handler
        const addedStep = stepsList.querySelector(`[data-step-index="${index}"]`);
        wireUpEditButton(addedStep, wizard);

        // Auto-switch to Flow tab when step is added
        wizard.switchToTab('flow');

        // Update step count badge
        wizard.updateFlowStepsUI();
    });

    // Handle step insertion (from insert mode when returning from step 4)
    window.addEventListener('flowStepInserted', (e) => {
        const { step, index } = e.detail;

        // Add edit button for capture_sensors or execute_action steps
        let editBtn = '';
        if (step.step_type === 'capture_sensors' && step.sensor_ids?.length) {
            editBtn = `<button class="btn btn-sm btn-edit-sensor" data-step-index="${index}" data-sensor-ids="${step.sensor_ids.join(',')}" title="Edit sensor">✏️</button>`;
        } else if (step.step_type === 'execute_action' && step.action_id) {
            editBtn = `<button class="btn btn-sm btn-edit-action" data-step-index="${index}" data-action-id="${step.action_id}" title="Edit action">✏️</button>`;
        }

        const stepHtml = `
            <div class="flow-step-item" data-step-index="${index}" style="border: 2px solid #16a34a; background: #f0fdf4;">
                <div class="step-number-badge" style="background: #16a34a;">${index + 1}</div>
                <div class="step-content">
                    <div class="step-description">${step.description}</div>
                    <span style="color: #16a34a; font-size: 0.8em;">✓ Inserted</span>
                </div>
                <div class="step-actions">
                    ${editBtn}
                    <button class="btn btn-sm" onclick="window.flowWizard.recorder.removeStep(${index})">✕</button>
                </div>
            </div>
        `;

        // Find the element at the insert position
        const existingSteps = stepsList.querySelectorAll('.flow-step-item');
        if (index < existingSteps.length) {
            existingSteps[index].insertAdjacentHTML('beforebegin', stepHtml);
        } else {
            stepsList.insertAdjacentHTML('beforeend', stepHtml);
        }

        // Renumber all steps and wire up edit buttons
        stepsList.querySelectorAll('.flow-step-item').forEach((el, i) => {
            el.dataset.stepIndex = i;
            el.querySelector('.step-number-badge').textContent = i + 1;
            wireUpEditButton(el, wizard);
        });

        // Auto-switch to Flow tab when step is inserted
        wizard.switchToTab('flow');

        // Update step count badge
        wizard.updateFlowStepsUI();

        showToast(`Inserted step at position ${index + 1}`, 'success', 2000);
    });

    window.addEventListener('flowStepRemoved', (e) => {
        const { index } = e.detail;
        const stepEl = stepsList.querySelector(`[data-step-index="${index}"]`);
        if (stepEl) stepEl.remove();

        // Renumber remaining steps
        stepsList.querySelectorAll('.flow-step-item').forEach((el, i) => {
            el.dataset.stepIndex = i;
            el.querySelector('.step-number-badge').textContent = i + 1;
        });

        // Update step count badge
        wizard.updateFlowStepsUI();
    });
}

// ==========================================
// Screen Mismatch Detection (v0.0.29)
// ==========================================

/**
 * Get the current flow's expected screen context
 * Returns the screen_id/activity from the last step that set it
 */
function getFlowCurrentScreenContext(wizard) {
    const steps = wizard.recorder?.getSteps?.() || wizard.flowSteps || [];

    // Walk backwards through steps to find the last known context
    for (let i = steps.length - 1; i >= 0; i--) {
        const step = steps[i];
        const screenId = step.expected_screen_id || null;
        const signature = step.screen_signature || null;
        const activity = step.screen_activity || step.expected_activity || null;

        // launch_app sets the initial screen
        if (step.step_type === 'launch_app') {
            return { screenId, signature, activity };
        }

        if (screenId || signature || activity) {
            return { screenId, signature, activity };
        }
    }

    return { screenId: null, signature: null, activity: null };
}

function annotateNavigationTarget(wizard, deviceActivity, deviceScreenId) {
    const steps = wizard.recorder?.getSteps?.() || wizard.flowSteps || [];
    if (!steps.length) return false;

    const lastStep = steps[steps.length - 1];
    if (!lastStep || !['tap', 'swipe', 'go_back', 'go_home'].includes(lastStep.step_type)) {
        return false;
    }

    let updated = false;
    if (deviceActivity && lastStep.expected_activity !== deviceActivity) {
        lastStep.expected_activity = deviceActivity;
        updated = true;
    }
    if (deviceScreenId && lastStep.expected_screen_id !== deviceScreenId) {
        lastStep.expected_screen_id = deviceScreenId;
        updated = true;
    }
    if (deviceScreenId && !lastStep.screen_signature) {
        lastStep.screen_signature = deviceScreenId;
        updated = true;
    }

    if (updated) {
        console.log('[FlowWizard] Annotated navigation target on last step', {
            step_type: lastStep.step_type,
            expected_activity: lastStep.expected_activity,
            expected_screen_id: lastStep.expected_screen_id
        });
        if (typeof wizard.updateFlowStepsUI === 'function') {
            wizard.updateFlowStepsUI();
        }
    }

    return updated;
}

/**
 * Check if adding a sensor would create a screen mismatch
 * Returns: { mismatch: boolean, currentActivity: string, sensorActivity: string }
 */
export async function checkScreenMismatch(wizard, sensorElement) {
    const flowContext = getFlowCurrentScreenContext(wizard);

    // Get current device screen
    let currentScreen = null;
    try {
        const response = await fetch(`${getApiBase()}/adb/screen/current/${encodeURIComponent(wizard.selectedDevice)}`);
        if (response.ok) {
            currentScreen = await response.json();
        }
    } catch (e) {
        console.warn('[FlowWizard] Could not get current screen:', e);
    }

    const deviceActivity = currentScreen?.activity?.activity || null;
    const deviceElements = getCurrentScreenElements(wizard);
    const deviceScreenId = await computeScreenId(deviceActivity, deviceElements);
    const flowScreenId = flowContext.screenId || null;
    const flowSignature = flowContext.signature || null;
    const lastStep = wizard.recorder?.getSteps?.().slice(-1)[0] || null;
    const lastStepIsNavigation = lastStep && ['tap', 'swipe', 'go_back', 'go_home'].includes(lastStep.step_type);
    const lastStepIsAppLaunch = lastStep && lastStep.step_type === 'launch_app';

    console.log('[FlowWizard] checkScreenMismatch', {
        flowContext,
        deviceActivity,
        deviceScreenId,
        lastStepType: lastStep?.step_type || null
    });

    // If flow has no activity yet (first sensor), no mismatch
    if (!flowContext.activity && !flowScreenId && !flowSignature) {
        return {
            mismatch: false,
            currentActivity: resolveScreenLabel(wizard, deviceScreenId, deviceActivity),
            sensorActivity: resolveScreenLabel(wizard, deviceScreenId, deviceActivity)
        };
    }

    const flowSignatureId = flowScreenId || flowSignature;
    const flowLabel = resolveScreenLabel(wizard, flowSignatureId, flowContext.activity);
    const deviceLabel = resolveScreenLabel(wizard, deviceScreenId, deviceActivity);
    const flowActName = getActivityShortName(wizard, flowSignatureId, flowContext.activity);
    const deviceActName = getActivityShortName(wizard, deviceScreenId, deviceActivity);

    if (flowActName && deviceActName && flowActName === deviceActName) {
        return { mismatch: false, currentActivity: flowLabel, sensorActivity: deviceLabel };
    }

    const normalizedFlowLabel = normalizeScreenLabel(flowLabel);
    const normalizedDeviceLabel = normalizeScreenLabel(deviceLabel);
    if (normalizedFlowLabel && normalizedDeviceLabel && normalizedFlowLabel === normalizedDeviceLabel) {
        return { mismatch: false, currentActivity: flowLabel, sensorActivity: deviceLabel };
    }

    if (flowScreenId && deviceScreenId && flowScreenId !== deviceScreenId) {
        // Check if the screen change was caused by navigation or app launch (splash → main screen)
        if (lastStepIsNavigation || lastStepIsAppLaunch) {
            annotateNavigationTarget(wizard, deviceActivity, deviceScreenId);
            console.log(`[FlowWizard] Screen changed after ${lastStep.step_type} (${flowLabel} -> ${deviceLabel}) - valid transition`);
            // Update the launch_app step with the final screen (not splash)
            if (lastStepIsAppLaunch) {
                lastStep.expected_activity = deviceActivity;
                lastStep.screen_activity = deviceActivity;  // Also update screen_activity for nav issue detection
                lastStep.expected_screen_id = deviceScreenId;
                lastStep.screen_signature = deviceScreenId;
                console.log(`[FlowWizard] Updated launch_app step with final screen: ${deviceLabel}`);
                // Refresh the step list UI to show updated screen info
                if (typeof wizard.updateFlowStepsUI === 'function') {
                    wizard.updateFlowStepsUI();
                }
            }
            return { mismatch: false, currentActivity: deviceLabel, sensorActivity: deviceLabel };
        }

        return {
            mismatch: true,
            currentActivity: flowLabel,
            sensorActivity: deviceLabel,
            fullCurrentActivity: flowContext.activity,
            fullSensorActivity: deviceActivity
        };
    }

    if (flowSignature && deviceScreenId && flowSignature !== deviceScreenId) {
        if (lastStepIsNavigation || lastStepIsAppLaunch) {
            annotateNavigationTarget(wizard, deviceActivity, deviceScreenId);
            console.log(`[FlowWizard] Screen changed after ${lastStep.step_type} (${flowLabel} -> ${deviceLabel}) - valid transition`);
            if (lastStepIsAppLaunch) {
                lastStep.expected_activity = deviceActivity;
                lastStep.screen_activity = deviceActivity;  // Also update screen_activity for nav issue detection
                lastStep.expected_screen_id = deviceScreenId;
                lastStep.screen_signature = deviceScreenId;
                console.log(`[FlowWizard] Updated launch_app step with final screen: ${deviceLabel}`);
                // Refresh the step list UI to show updated screen info
                if (typeof wizard.updateFlowStepsUI === 'function') {
                    wizard.updateFlowStepsUI();
                }
            }
            return { mismatch: false, currentActivity: deviceLabel, sensorActivity: deviceLabel };
        }
        return {
            mismatch: true,
            currentActivity: flowLabel,
            sensorActivity: deviceLabel,
            fullCurrentActivity: flowContext.activity,
            fullSensorActivity: deviceActivity
        };
    }

    // Fallback to activity name comparison when screen ids are unavailable
    if (flowContext.activity && deviceActivity) {
        if (flowActName !== deviceActName) {
            if (lastStepIsNavigation || lastStepIsAppLaunch) {
                console.log(`[FlowWizard] Screen changed after ${lastStep.step_type} (${flowLabel} -> ${deviceLabel}) - valid transition`);
                if (lastStepIsAppLaunch) {
                    lastStep.expected_activity = deviceActivity;
                    lastStep.screen_activity = deviceActivity;  // Also update screen_activity for nav issue detection
                    lastStep.expected_screen_id = deviceScreenId;
                    lastStep.screen_signature = deviceScreenId;
                    // Refresh the step list UI to show updated screen info
                    if (typeof wizard.updateFlowStepsUI === 'function') {
                        wizard.updateFlowStepsUI();
                    }
                }
                return { mismatch: false, currentActivity: deviceLabel, sensorActivity: deviceLabel };
            }
            return {
                mismatch: true,
                currentActivity: flowLabel,
                sensorActivity: deviceLabel,
                fullCurrentActivity: flowContext.activity,
                fullSensorActivity: deviceActivity
            };
        }
    }

    return { mismatch: false, currentActivity: flowLabel, sensorActivity: deviceLabel };
}

/**
 * Show dialog when adding sensor on different screen
 * Returns: 'add_nav' | 'add_anyway' | 'cancel'
 */
export function showNavigationMismatchDialog(wizard, mismatchInfo) {
    return new Promise((resolve) => {
        const hasLastAction = wizard._lastExecutedAction &&
            (Date.now() - wizard._lastExecutedAction._timestamp) < 60000; // Within last 60 seconds

        const lastActionDesc = hasLastAction
            ? `"${wizard._lastExecutedAction.description || wizard._lastExecutedAction.step_type}"`
            : 'the previous tap/swipe';

        // Create modal overlay
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); z-index: 10000; display: flex; align-items: center; justify-content: center;';

        overlay.innerHTML = `
            <div class="modal-content" style="background: var(--card-bg, #fff); border-radius: 12px; padding: 24px; max-width: 500px; margin: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                <h3 style="margin: 0 0 16px 0; color: #f59e0b;">⚠️ Different Screen Detected</h3>
                <p style="margin: 0 0 12px 0;">
                    This sensor is on <strong>"${mismatchInfo.sensorActivity}"</strong> but your flow is currently on <strong>"${mismatchInfo.currentActivity}"</strong>.
                </p>
                <p style="margin: 0 0 16px 0; color: #64748b; font-size: 0.9em;">
                    Without navigation steps, the sensor won't be found during flow execution.
                </p>

                <div style="display: flex; flex-direction: column; gap: 10px;">
                    ${hasLastAction ? `
                    <button id="btnAddNav" class="btn btn-primary" style="padding: 12px; font-size: 1em; background: #2196F3;">
                        📍 Add Navigation Step First
                        <span style="display: block; font-size: 0.8em; opacity: 0.8;">Adds ${lastActionDesc} before the sensor</span>
                    </button>
                    ` : ''}

                    <button id="btnSetCurrent" class="btn btn-secondary" style="padding: 12px; font-size: 1em; background: #22c55e; color: white; border: none;">
                        ✅ Use Current Screen
                        <span style="display: block; font-size: 0.8em; opacity: 0.8;">Insert a screen check before the sensor</span>
                    </button>

                    <button id="btnAddAnyway" class="btn btn-secondary" style="padding: 12px; font-size: 1em; background: #f59e0b; color: white; border: none;">
                        ⚠️ Add Sensor Anyway
                        <span style="display: block; font-size: 0.8em; opacity: 0.8;">I'll add navigation steps manually</span>
                    </button>

                    <button id="btnCancel" class="btn" style="padding: 12px; font-size: 1em; background: #e5e7eb; color: #374151;">
                        Cancel
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        // Event handlers
        const btnAddNav = overlay.querySelector('#btnAddNav');
        const btnSetCurrent = overlay.querySelector('#btnSetCurrent');
        const btnAddAnyway = overlay.querySelector('#btnAddAnyway');
        const btnCancel = overlay.querySelector('#btnCancel');

        if (btnAddNav) {
            btnAddNav.onclick = () => {
                overlay.remove();
                resolve('add_nav');
            };
        }

        btnSetCurrent.onclick = () => {
            overlay.remove();
            resolve('set_current');
        };

        btnAddAnyway.onclick = () => {
            overlay.remove();
            resolve('add_anyway');
        };

        btnCancel.onclick = () => {
            overlay.remove();
            resolve('cancel');
        };

        // Close on overlay click
        overlay.onclick = (e) => {
            if (e.target === overlay) {
                overlay.remove();
                resolve('cancel');
            }
        };
    });
}

/**
 * Add sensor with screen mismatch checking
 * This wraps the sensor addition with navigation step option
 */
export async function addSensorWithNavigationCheck(wizard, sensorStep, skipCheck = false) {
    if (!skipCheck) {
        const mismatchInfo = await checkScreenMismatch(wizard, sensorStep);

        if (mismatchInfo.mismatch) {
            console.log('[FlowWizard] Screen mismatch detected:', mismatchInfo);
            const choice = await showNavigationMismatchDialog(wizard, mismatchInfo);
            console.log('[FlowWizard] Screen mismatch choice:', choice);

            if (choice === 'cancel') {
                showToast('Sensor not added', 'info');
                return false;
            }

            if (choice === 'add_nav' && wizard._lastExecutedAction) {
                // Add the navigation step first (without _timestamp)
                const navStep = { ...wizard._lastExecutedAction };
                delete navStep._timestamp;

                // Get screen info for the nav step
                try {
                    const screenInfo = await wizard.recorder.getCurrentScreen();
                    if (screenInfo?.activity) {
                        navStep.screen_activity = mismatchInfo.fullCurrentActivity;
                        navStep.screen_package = screenInfo.activity.package;
                    }
                } catch (e) {
                    console.warn('[FlowWizard] Could not get screen info for nav step:', e);
                }

                const existingStep = wizard.recorder?.getSteps?.().slice(-1)[0];
                const isDuplicateTap = existingStep?.step_type === 'tap' &&
                    navStep.step_type === 'tap' &&
                    existingStep.x === navStep.x && existingStep.y === navStep.y;
                const isDuplicateSwipe = existingStep?.step_type === 'swipe' &&
                    navStep.step_type === 'swipe' &&
                    existingStep.start_x === navStep.start_x &&
                    existingStep.start_y === navStep.start_y &&
                    existingStep.end_x === navStep.end_x &&
                    existingStep.end_y === navStep.end_y;

                if (isDuplicateTap || isDuplicateSwipe) {
                    showToast('Navigation already recorded', 'info');
                } else {
                    wizard.recorder.addStep(navStep);
                    showToast(`Added navigation: ${navStep.description}`, 'info');
                }
            } else if (choice === 'set_current') {
                const expectedActivity = mismatchInfo.fullSensorActivity || null;
                if (expectedActivity) {
                    const existingStep = wizard.recorder?.getSteps?.().slice(-1)[0];
                    const alreadySet = existingStep?.step_type === 'validate_screen' &&
                        existingStep.expected_activity === expectedActivity;
                    if (!alreadySet) {
                        wizard.recorder.addStep({
                            step_type: 'validate_screen',
                            expected_activity: expectedActivity,
                            description: `Validate screen: ${mismatchInfo.sensorActivity}`
                        });
                        showToast(`Set current screen: ${mismatchInfo.sensorActivity}`, 'info');
                    } else {
                        showToast('Current screen already set', 'info');
                    }
                } else {
                    showToast('Could not detect current screen', 'warning');
                }
            }
        }
    }

    // Add the sensor step
    await wizard.recorder.addStep(sensorStep);
    return true;
}

// ==========================================
// Dual Export Pattern
// ==========================================

const Step3Module = {
    loadStep3,
    populateAppInfo,
    updateScreenInfo,
    setupRecordingUI,
    setupPanelTabs,
    switchToTab,
    setupToolbarHandlers,
    setupPanelToggle,
    toggleRightPanel,
    setupOverlayFilters,
    setupCaptureMode,
    setCaptureMode,

    // ========================================
    // Phase 2 Modularized Functions
    // These are also available from Step3Controller
    // ========================================

    // Stream management (from stream-manager.js)
    startStreaming,
    stopStreaming,
    reconnectStream,
    startElementAutoRefresh,
    stopElementAutoRefresh,
    startKeepAwake,
    stopKeepAwake,
    updateStreamStatus,
    refreshElements,
    refreshAfterAction,

    // Canvas overlay rendering (from canvas-overlay-renderer.js)
    setupHoverTooltip,
    handleCanvasHover,
    showHoverTooltip,
    updateTooltipPosition,
    hideHoverTooltip,
    highlightHoveredElement,
    clearHoverHighlight,
    clearAllElementsAndHover,

    // Gesture handling (from gesture-handler.js)
    onGestureStart,
    onGestureEnd,
    executeSwipeGesture,
    showTapRipple,
    showSwipePath,

    // Controller reference for direct module access
    Controller: Step3Controller,

    // ========================================
    // Element tree methods
    setupElementTree,
    toggleTreeView,
    handleTreeTap,
    handleTreeSensor,
    handleTreeTimestamp,
    updateElementTree,
    // Zoom/scale methods
    toggleScale,
    zoomIn,
    zoomOut,
    resetZoom,
    updateZoomDisplay,
    fitToScreen,
    // Recording toggle
    toggleRecording,
    // Element interaction methods
    handleElementClick,
    canvasToDevice,
    executeTap,
    showTapIndicator,
    findElementAtCoordinates,
    showElementSelectionDialog,
    // Screen mismatch detection
    checkScreenMismatch,
    showNavigationMismatchDialog,
    addSensorWithNavigationCheck,
    // Screenshot display methods
    handleRefreshWithRetries,
    updateScreenshotDisplay,
    showLoadingOverlay,
    hideLoadingOverlay,
    // Flow UI update methods
    updateElementCount,
    updateFlowStepsUI,
    // Preview overlay methods
    showPreviewOverlay,
    hidePreviewOverlay,
    chooseRegularScreenshot,
    chooseStitchCapture,
    // Sidebar methods
    collapseSidebar,
    expandSidebar,
    // Element panel methods
    updateElementPanel,
    setupElementFilters,
    renderFilteredElements,
    // Drawing methods
    drawElementOverlays,
    drawElementOverlaysScaled,
    drawTextLabel,
    // Flow steps listener
    setupFlowStepsListener,
    // Suggestions tab
    setupSuggestionsTab
};

// Global export for backward compatibility
window.FlowWizardStep3 = Step3Module;

export default Step3Module;
