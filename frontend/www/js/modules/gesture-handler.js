/**
 * Gesture Handler Module
 * Extracted from flow-wizard-step3.js for modularity
 *
 * Handles:
 * - Touch/mouse gesture detection (tap vs swipe)
 * - Swipe gesture execution via ADB API
 * - Visual feedback (tap ripples, swipe paths)
 * - Coordinate conversion (canvas to device)
 *
 * @module gesture-handler
 */

import { showToast } from './toast.js?v=0.4.0-beta.3.19';
import { refreshAfterAction } from './stream-manager.js?v=0.4.0-beta.3.19';

// ==========================================
// Utility Functions
// ==========================================

/**
 * Get API base URL with ingress support
 * @returns {string} The API base URL
 */
function getApiBase() {
    if (window.API_BASE) return window.API_BASE;
    if (window.opener?.API_BASE) return window.opener.API_BASE;
    const url = window.location.href;
    const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
    if (ingressMatch) return ingressMatch[0] + '/api';
    return '/api';
}

// ==========================================
// Gesture Detection Functions
// ==========================================

/**
 * Handle gesture start (mousedown/touchstart)
 * @param {Object} wizard - The wizard instance
 * @param {Event} e - The mouse or touch event
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
 * Determines if the gesture was a tap or swipe and handles accordingly
 * @param {Object} wizard - The wizard instance
 * @param {Event} e - The mouse or touch event
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
    if (!container) {
        console.warn('[GestureHandler] Screenshot container not found');
        return;
    }

    // Get canvas offset within container for accurate ripple/path position
    const canvasRect = wizard.canvas.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const canvasOffsetX = canvasRect.left - containerRect.left + container.scrollLeft;
    const canvasOffsetY = canvasRect.top - containerRect.top + container.scrollTop;

    // CSS scale factor: canvas bitmap coords to display coords (accounts for zoom)
    const cssScale = canvasRect.width / wizard.canvas.width;

    // Debug: Log distance and threshold
    const minDistance = wizard.MIN_SWIPE_DISTANCE || 30;
    console.log(`[GestureHandler] Gesture distance: ${distance.toFixed(1)}px (threshold: ${minDistance}px)`);

    if (distance < minDistance) {
        // It's a tap
        console.log(`[GestureHandler] Tap at canvas (${wizard.dragStart.canvasX}, ${wizard.dragStart.canvasY})`);

        // Show tap ripple effect (convert canvas coords to display coords, then add offset)
        const rippleX = wizard.dragStart.canvasX * cssScale + canvasOffsetX;
        const rippleY = wizard.dragStart.canvasY * cssScale + canvasOffsetY;
        showTapRipple(wizard, container, rippleX, rippleY);

        // Handle element click (existing logic)
        await wizard.handleElementClick(wizard.dragStart.canvasX, wizard.dragStart.canvasY);
    } else {
        // It's a swipe
        console.log(`[GestureHandler] Swipe from (${wizard.dragStart.canvasX},${wizard.dragStart.canvasY}) to (${endCanvasX},${endCanvasY})`);

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

// ==========================================
// Swipe Execution Functions
// ==========================================

/**
 * Execute swipe gesture on device
 * @param {Object} wizard - The wizard instance
 * @param {number} startCanvasX - Start X in canvas coordinates
 * @param {number} startCanvasY - Start Y in canvas coordinates
 * @param {number} endCanvasX - End X in canvas coordinates
 * @param {number} endCanvasY - End Y in canvas coordinates
 */
export async function executeSwipeGesture(wizard, startCanvasX, startCanvasY, endCanvasX, endCanvasY) {
    // Convert canvas coordinates to device coordinates (use appropriate converter)
    let startDevice, endDevice;
    if (wizard.captureMode === 'streaming' && wizard.liveStream) {
        startDevice = wizard.liveStream.canvasToDevice(startCanvasX, startCanvasY);
        endDevice = wizard.liveStream.canvasToDevice(endCanvasX, endCanvasY);
    } else if (wizard.canvasRenderer) {
        startDevice = wizard.canvasRenderer.canvasToDevice(startCanvasX, startCanvasY);
        endDevice = wizard.canvasRenderer.canvasToDevice(endCanvasX, endCanvasY);
    }

    // Handle null coordinates (no image loaded yet)
    if (!startDevice || !endDevice) {
        console.warn('[GestureHandler] Cannot convert coordinates - no image loaded');
        showToast('Swipe failed: wait for stream to load', 'warning');
        return;
    }

    console.log(`[GestureHandler] Executing swipe: (${startDevice.x},${startDevice.y}) -> (${endDevice.x},${endDevice.y})`);

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

        const result = await response.json();
        console.log('[GestureHandler] Swipe API response:', result);

        if (!response.ok) {
            throw new Error(result.detail || 'Failed to execute swipe');
        }

        // Build swipe step
        const swipeStep = {
            step_type: 'swipe',
            start_x: startDevice.x,
            start_y: startDevice.y,
            end_x: endDevice.x,
            end_y: endDevice.y,
            duration: 300,
            description: `Swipe from (${startDevice.x},${startDevice.y}) to (${endDevice.x},${endDevice.y})`
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
        console.error('[GestureHandler] Swipe failed:', error);
        showToast(`Swipe failed: ${error.message}`, 'error');
    }
}

// ==========================================
// Visual Feedback Functions
// ==========================================

/**
 * Show animated tap ripple at position
 * @param {Object} wizard - The wizard instance
 * @param {HTMLElement} container - The screenshot container
 * @param {number} x - X position in container coordinates
 * @param {number} y - Y position in container coordinates
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
 * @param {Object} wizard - The wizard instance
 * @param {HTMLElement} container - The screenshot container
 * @param {number} startX - Start X in container coordinates
 * @param {number} startY - Start Y in container coordinates
 * @param {number} endX - End X in container coordinates
 * @param {number} endY - End Y in container coordinates
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
// Default Export
// ==========================================

export default {
    // Gesture detection
    onGestureStart,
    onGestureEnd,

    // Swipe execution
    executeSwipeGesture,

    // Visual feedback
    showTapRipple,
    showSwipePath
};

// Global export for non-module usage
if (typeof window !== 'undefined') {
    window.GestureHandler = {
        onGestureStart,
        onGestureEnd,
        executeSwipeGesture,
        showTapRipple,
        showSwipePath
    };
}
