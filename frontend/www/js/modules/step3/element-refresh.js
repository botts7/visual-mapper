/**
 * Element Refresh Module for Flow Wizard Step 3
 *
 * Handles:
 * - Element tree fetching (companion app or ADB fallback)
 * - Element refresh lifecycle (guards, indicators)
 * - Companion element flattening
 * - Hover and element state clearing
 *
 * Extracted from flow-wizard-step3.js for maintainability
 * @version 0.0.1
 */

import { showToast } from '../toast.js?v=0.4.0-beta.4';
import { maybeLearnScreen } from './screen-identification.js';

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Flatten nested companion app elements to a flat array
 * Companion app returns hierarchical elements with children property,
 * but the UI expects a flat array with bounds
 * @param {Array} elements - Nested elements from companion app
 * @returns {Array} - Flat array of elements
 */
export function flattenCompanionElements(elements) {
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

/**
 * Clear hover highlight overlay
 * @param {Object} wizard - The wizard instance
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
 * @param {Object} wizard - The wizard instance
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

/**
 * Refresh elements in background
 * In streaming mode: uses fast elements-only endpoint
 * In polling mode: fetches full screenshot with elements
 *
 * @param {Object} wizard - The wizard instance
 * @param {Object} callbacks - Optional callbacks
 * @param {Function} callbacks.updateNavigationContext - Navigation context updater
 * @param {Function} callbacks.updateScreenshotDisplay - Screenshot display updater
 */
export async function refreshElements(wizard, callbacks = {}) {
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
            // Use streaming_safe mode when stream is active to avoid blocking ADB capture
            if (!data) {
                const isStreaming = wizard.liveStream?.isStreaming;
                const streamingSafe = isStreaming ? 'true' : 'false';
                const url = `${getApiBase()}/adb/elements/${encodeURIComponent(wizard.selectedDevice)}?streaming_safe=${streamingSafe}`;
                const response = await fetch(url);
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
                console.log(`[FlowWizard] ${changeType} changed: ${from} -> ${to}`);
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

            if (currentActivity && callbacks.updateNavigationContext) {
                await callbacks.updateNavigationContext(
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
                    console.log(`[FlowWizard] Device dimensions updated: ${oldWidth}x${oldHeight} -> ${data.device_width}x${data.device_height}`);
                }
            }

            // Only log when element count changes significantly (reduces log noise)
            const lastCount = wizard._lastElementCount || 0;
            if (Math.abs(elements.length - lastCount) > 5) {
                console.log(`[FlowWizard] Elements updated: ${lastCount} -> ${elements.length} (pkg: ${currentPackage || 'unknown'})`);
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
                    setTimeout(() => refreshElements(wizard, callbacks), 300);
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
                if (callbacks.updateScreenshotDisplay) {
                    await callbacks.updateScreenshotDisplay(wizard);
                }
            }
            // Polling mode uses canvasRenderer.render() which handles both screenshot
            // and element overlays, so no need to update liveStream separately
        }

        // Only in streaming mode: Update LiveStream elements for overlay
        // In polling mode, canvasRenderer.render() already handles this
        if (wizard.captureMode === 'streaming' && wizard.liveStream) {
            // Update elements atomically - next WebSocket frame will redraw with new elements
            // CRITICAL: Do NOT call _renderFrame manually here!
            // Calling _renderFrame(currentImage) draws the LAST processed frame which may be stale
            // (showing old screen before the tap). The WebSocket handler will naturally redraw
            // the current live frame with the new elements on the next frame arrival.
            // This follows the principle: "video should just be video" - let the stream continue
            // uninterrupted instead of forcing a redraw with potentially stale cached images.
            wizard.liveStream.elements = elements;

            // Mark elements as fresh so they'll be drawn on the next frame
            // This clears the _elementsStale flag that was set on screen change detection
            wizard.liveStream.markElementsFresh();
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
                        // Extract app name from package (e.g., "com.byd.autolink" -> "BYD AUTO")
                        const appName = screenData.activity.package.split('.').pop() || screenData.activity.package;
                        appNameEl.textContent = appName.charAt(0).toUpperCase() + appName.slice(1);
                        // Throttle this log to reduce spam (only log when app name actually changes)
                        if (wizard._lastLoggedAppName !== appName) {
                            wizard._lastLoggedAppName = appName;
                            console.log(`[FlowWizard] Updated app name: ${appName}`);
                        }
                    }
                    if (callbacks.updateNavigationContext) {
                        await callbacks.updateNavigationContext(wizard, screenData.activity, elements);
                    }
                    await maybeLearnScreen(wizard, screenData.activity, elements);
                }
            }
        } catch (appInfoError) {
            console.warn('[FlowWizard] Failed to update app info:', appInfoError);
        }

        // Throttle this log - only show when element count changes
        if (wizard._lastLoggedElementCount !== elements.length) {
            wizard._lastLoggedElementCount = elements.length;
            console.log(`[FlowWizard] Elements refreshed: ${elements.length} elements`);
        }
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
 *
 * @param {Object} wizard - The wizard instance
 * @param {number} delayMs - Delay before refresh (default 500ms)
 * @param {Object} callbacks - Optional callbacks for refresh
 */
export async function refreshAfterAction(wizard, delayMs = 500, callbacks = {}) {
    // IMPORTANT: Clear all elements and hover immediately when action occurs
    // This prevents stale elements/highlight from previous screen showing on new screen
    clearAllElementsAndHover(wizard);

    setTimeout(async () => {
        try {
            if (wizard.captureMode === 'streaming') {
                // Streaming mode: fetch elements via fast API
                await refreshElements(wizard, callbacks);
            } else {
                // Polling mode: capture screenshot which includes elements
                await wizard.recorder?.captureScreenshot();

                // TIMING FIX: Wait for UI to settle before rendering overlays
                // Check if UI is still loading/refreshing - if so, wait and retry
                const MAX_SETTLE_ATTEMPTS = 3;
                let attempt = 0;
                while (attempt < MAX_SETTLE_ATTEMPTS && wizard.recorder?.detectLoadingIndicators?.()) {
                    console.log(`[FlowWizard] UI loading detected, waiting... (${attempt + 1}/${MAX_SETTLE_ATTEMPTS})`);
                    await new Promise(r => setTimeout(r, 800));
                    await wizard.recorder?.captureScreenshot();
                    attempt++;
                }

                if (callbacks.updateScreenshotDisplay) {
                    callbacks.updateScreenshotDisplay(wizard);
                } else {
                    wizard.updateScreenshotDisplay?.();
                }
            }
        } catch (e) {
            console.warn('[FlowWizard] Auto-refresh after action failed:', e);
        }
    }, delayMs);
}
