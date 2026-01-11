/**
 * Step 3 Controller Module
 * Orchestrates all Step 3 (Recording Mode) modules
 *
 * This module coordinates:
 * - Stream management (LiveStream, element refresh, keep-awake)
 * - Canvas overlay rendering (tooltips, highlights, element overlays)
 * - Gesture handling (tap/swipe detection and execution)
 *
 * Provides a unified API for flow-wizard-step3.js to use
 *
 * @module step3-controller
 */

// Import extracted modules
import * as StreamManager from './stream-manager.js?v=0.2.41';
import * as CanvasOverlayRenderer from './canvas-overlay-renderer.js?v=0.2.41';
import * as GestureHandler from './gesture-handler.js?v=0.2.41';

// ==========================================
// Controller State
// ==========================================

/**
 * Controller state for tracking active instances
 */
const controllerState = {
    initialized: false,
    wizard: null,
    cleanupFunctions: []
};

// ==========================================
// Initialization
// ==========================================

/**
 * Initialize Step 3 controller with all modules
 * @param {Object} wizard - The wizard instance
 * @returns {Object} Controller API
 */
export function initializeController(wizard) {
    if (controllerState.initialized) {
        console.warn('[Step3Controller] Already initialized, cleaning up first');
        cleanup();
    }

    controllerState.wizard = wizard;
    controllerState.initialized = true;

    console.log('[Step3Controller] Initializing Step 3 modules');

    return {
        // Stream management
        stream: {
            prepareDevice: () => StreamManager.prepareDeviceForStreaming(wizard),
            start: (drawOverlays) => StreamManager.startStreaming(wizard, drawOverlays),
            stop: () => StreamManager.stopStreaming(wizard),
            reconnect: (drawOverlays) => StreamManager.reconnectStream(wizard, drawOverlays),
            updateStatus: (className, text) => StreamManager.updateStreamStatus(wizard, className, text),
            refresh: (clearFn) => StreamManager.refreshElements(wizard, clearFn),
            refreshAfterAction: (delayMs, clearFn) => StreamManager.refreshAfterAction(wizard, delayMs, clearFn),
            startAutoRefresh: () => StreamManager.startElementAutoRefresh(wizard),
            stopAutoRefresh: () => StreamManager.stopElementAutoRefresh(wizard),
            startKeepAwake: () => StreamManager.startKeepAwake(wizard),
            stopKeepAwake: () => StreamManager.stopKeepAwake(wizard)
        },

        // Canvas overlay rendering
        overlay: {
            setupTooltip: () => CanvasOverlayRenderer.setupHoverTooltip(wizard),
            drawElements: () => CanvasOverlayRenderer.drawElementOverlays(wizard),
            drawElementsScaled: (scale) => CanvasOverlayRenderer.drawElementOverlaysScaled(wizard, scale),
            clearAll: () => CanvasOverlayRenderer.clearAllElementsAndHover(wizard),
            highlightElement: (element) => CanvasOverlayRenderer.highlightHoveredElement(wizard, element),
            clearHighlight: () => CanvasOverlayRenderer.clearHoverHighlight(wizard)
        },

        // Gesture handling
        gesture: {
            onStart: (e) => GestureHandler.onGestureStart(wizard, e),
            onEnd: (e) => GestureHandler.onGestureEnd(wizard, e),
            executeSwipe: (x1, y1, x2, y2) => GestureHandler.executeSwipeGesture(wizard, x1, y1, x2, y2),
            showTapRipple: (container, x, y) => GestureHandler.showTapRipple(wizard, container, x, y),
            showSwipePath: (container, x1, y1, x2, y2) => GestureHandler.showSwipePath(wizard, container, x1, y1, x2, y2)
        },

        // Lifecycle
        cleanup: cleanup
    };
}

/**
 * Setup canvas event listeners for gestures
 * @param {Object} wizard - The wizard instance
 */
export function setupCanvasGestureListeners(wizard) {
    if (!wizard.canvas) {
        console.error('[Step3Controller] Canvas not initialized');
        return;
    }

    // Mouse events
    wizard.canvas.addEventListener('mousedown', (e) => GestureHandler.onGestureStart(wizard, e));
    wizard.canvas.addEventListener('mouseup', (e) => GestureHandler.onGestureEnd(wizard, e));

    // Touch events
    wizard.canvas.addEventListener('touchstart', (e) => GestureHandler.onGestureStart(wizard, e), { passive: false });
    wizard.canvas.addEventListener('touchend', (e) => GestureHandler.onGestureEnd(wizard, e), { passive: false });

    // Setup hover tooltip
    CanvasOverlayRenderer.setupHoverTooltip(wizard);

    console.log('[Step3Controller] Canvas gesture listeners setup complete');
}

/**
 * Setup streaming mode with all necessary handlers
 * @param {Object} wizard - The wizard instance
 * @param {Function} onFrame - Callback when frame received
 * @param {Function} onConnect - Callback when connected
 * @param {Function} onError - Callback on error
 */
export async function setupStreamingMode(wizard, onFrame, onConnect, onError) {
    console.log('[Step3Controller] Setting up streaming mode');

    // Prepare device (unlock, wake)
    await StreamManager.prepareDeviceForStreaming(wizard);

    // Start streaming with element overlay callback
    const drawOverlays = () => CanvasOverlayRenderer.drawElementOverlays(wizard);
    await StreamManager.startStreaming(wizard, drawOverlays);

    // Start auto-refresh for elements
    StreamManager.startElementAutoRefresh(wizard);

    // Start keep-awake
    StreamManager.startKeepAwake(wizard);

    console.log('[Step3Controller] Streaming mode setup complete');
}

/**
 * Switch capture mode (polling vs streaming)
 * @param {Object} wizard - The wizard instance
 * @param {string} mode - 'polling' or 'streaming'
 */
export async function switchCaptureMode(wizard, mode) {
    console.log(`[Step3Controller] Switching to ${mode} mode`);

    // Stop current mode
    StreamManager.stopStreaming(wizard);
    StreamManager.stopElementAutoRefresh(wizard);

    wizard.captureMode = mode;

    if (mode === 'streaming') {
        await setupStreamingMode(wizard);
    } else {
        // Polling mode - just refresh elements
        await StreamManager.refreshElements(wizard, () => CanvasOverlayRenderer.clearAllElementsAndHover(wizard));
    }
}

// ==========================================
// Cleanup
// ==========================================

/**
 * Cleanup all Step 3 resources
 */
export function cleanup() {
    if (!controllerState.initialized) return;

    const wizard = controllerState.wizard;
    if (wizard) {
        console.log('[Step3Controller] Cleaning up Step 3 resources');

        // Stop streaming
        StreamManager.stopStreaming(wizard);
        StreamManager.stopElementAutoRefresh(wizard);
        StreamManager.stopKeepAwake(wizard);

        // Clear overlays
        CanvasOverlayRenderer.clearAllElementsAndHover(wizard);
    }

    // Run any registered cleanup functions
    controllerState.cleanupFunctions.forEach(fn => {
        try { fn(); } catch (e) { console.warn('[Step3Controller] Cleanup error:', e); }
    });

    controllerState.initialized = false;
    controllerState.wizard = null;
    controllerState.cleanupFunctions = [];

    console.log('[Step3Controller] Cleanup complete');
}

/**
 * Register a cleanup function to run on shutdown
 * @param {Function} fn - Cleanup function
 */
export function registerCleanup(fn) {
    if (typeof fn === 'function') {
        controllerState.cleanupFunctions.push(fn);
    }
}

// ==========================================
// Re-exports for Direct Access
// ==========================================

// Stream management
export const prepareDeviceForStreaming = StreamManager.prepareDeviceForStreaming;
export const startStreaming = StreamManager.startStreaming;
export const stopStreaming = StreamManager.stopStreaming;
export const reconnectStream = StreamManager.reconnectStream;
export const startElementAutoRefresh = StreamManager.startElementAutoRefresh;
export const stopElementAutoRefresh = StreamManager.stopElementAutoRefresh;
export const startKeepAwake = StreamManager.startKeepAwake;
export const stopKeepAwake = StreamManager.stopKeepAwake;
export const updateStreamStatus = StreamManager.updateStreamStatus;
export const refreshElements = StreamManager.refreshElements;
export const refreshAfterAction = StreamManager.refreshAfterAction;

// Canvas overlay rendering
export const setupHoverTooltip = CanvasOverlayRenderer.setupHoverTooltip;
export const handleCanvasHover = CanvasOverlayRenderer.handleCanvasHover;
export const showHoverTooltip = CanvasOverlayRenderer.showHoverTooltip;
export const updateTooltipPosition = CanvasOverlayRenderer.updateTooltipPosition;
export const hideHoverTooltip = CanvasOverlayRenderer.hideHoverTooltip;
export const highlightHoveredElement = CanvasOverlayRenderer.highlightHoveredElement;
export const clearHoverHighlight = CanvasOverlayRenderer.clearHoverHighlight;
export const clearAllElementsAndHover = CanvasOverlayRenderer.clearAllElementsAndHover;
export const drawElementOverlays = CanvasOverlayRenderer.drawElementOverlays;
export const drawElementOverlaysScaled = CanvasOverlayRenderer.drawElementOverlaysScaled;
export const drawTextLabel = CanvasOverlayRenderer.drawTextLabel;

// Gesture handling
export const onGestureStart = GestureHandler.onGestureStart;
export const onGestureEnd = GestureHandler.onGestureEnd;
export const executeSwipeGesture = GestureHandler.executeSwipeGesture;
export const showTapRipple = GestureHandler.showTapRipple;
export const showSwipePath = GestureHandler.showSwipePath;

// ==========================================
// Default Export
// ==========================================

export default {
    // Initialization
    initializeController,
    setupCanvasGestureListeners,
    setupStreamingMode,
    switchCaptureMode,

    // Cleanup
    cleanup,
    registerCleanup,

    // Modules (for direct access)
    StreamManager,
    CanvasOverlayRenderer,
    GestureHandler
};

// Global export for non-module usage
if (typeof window !== 'undefined') {
    window.Step3Controller = {
        initializeController,
        setupCanvasGestureListeners,
        setupStreamingMode,
        switchCaptureMode,
        cleanup,
        registerCleanup,
        StreamManager,
        CanvasOverlayRenderer,
        GestureHandler
    };
}
