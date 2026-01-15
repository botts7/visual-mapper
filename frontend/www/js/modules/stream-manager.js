/**
 * Stream Manager Module
 * Visual Mapper v0.0.6
 *
 * Extracted from flow-wizard-step3.js (Phase 2.1)
 * Handles all live streaming, element refresh, and device connection logic.
 *
 * v0.0.6: Fix keep-awake - make async, await first signal, use 5s interval
 *
 * Responsibilities:
 * - Device preparation for streaming (unlock, wake)
 * - LiveStream lifecycle (start/stop/reconnect)
 * - Element auto-refresh with debouncing
 * - Keep-awake interval management
 * - Screenshot display and loading overlays
 * - Connection status updates
 */

import { showToast } from './toast.js?v=0.4.0-beta.2.20';
import LiveStream from './live-stream.js?v=0.4.0-beta.2.20';
import {
    ensureDeviceUnlocked as sharedEnsureUnlocked,
    startKeepAwake as sharedStartKeepAwake,
    stopKeepAwake as sharedStopKeepAwake
} from './device-unlock.js?v=0.4.0-beta.2.20';

// Helper to get API base (from global set by init.js)
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Prepare device for streaming - check lock, wake screen, unlock if needed
 * Shows a status dialog keeping user informed
 *
 * @param {Object} wizard - The wizard state object
 * @returns {Promise<boolean>} - True if device is ready
 */
export async function prepareDeviceForStreaming(wizard) {
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
                    const screenshotPromise = fetch(`${apiBase}/adb/screenshot`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ device_id: wizard.selectedDevice, quick: false })
                    });
                    const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject('timeout'), 3000));

                    const response = await Promise.race([screenshotPromise, timeoutPromise]);
                    if (response && response.ok) {
                        const data = await response.json();
                        if (data.screenshot) {
                            // Preload the image
                            wizard._preloadedImage = data.screenshot;
                            wizard._preloadedElements = data.elements || [];
                            console.log('[StreamManager] Preloaded screenshot with', wizard._preloadedElements.length, 'elements');
                        }
                    }
                } catch (e) {
                    console.log('[StreamManager] Screenshot preload skipped:', e);
                }

                updateStep('step-connect', 'done');
                messageEl.textContent = 'Device ready! Starting stream...';
                await new Promise(r => setTimeout(r, 300));

                cleanup();
                resolve(true);

            } catch (error) {
                console.error('[StreamManager] Device preparation error:', error);
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
 *
 * @param {Object} wizard - The wizard state object
 * @param {Function} drawElementOverlays - Callback to draw element overlays
 */
export async function startStreaming(wizard, drawElementOverlays) {
    if (!wizard.selectedDevice) {
        showToast('No device selected', 'error');
        return;
    }

    // Reset stream session flags
    wizard._streamLoadingHidden = false;
    wizard._streamConnectedOnce = false;

    // Clear any existing loading timeout
    if (wizard._streamLoadingTimeout) {
        clearTimeout(wizard._streamLoadingTimeout);
        wizard._streamLoadingTimeout = null;
    }

    // Show device preparation dialog
    const prepared = await prepareDeviceForStreaming(wizard);
    if (!prepared) {
        console.log('[StreamManager] Device preparation cancelled or failed');
        return;
    }

    // Show loading indicator (or preloaded image if available)
    if (wizard._preloadedImage) {
        // Display preloaded image immediately
        console.log('[StreamManager] Using preloaded image');
        const img = new Image();
        img.onload = () => {
            wizard.canvas.width = img.width;
            wizard.canvas.height = img.height;
            console.log(`[StreamManager] Preloaded image dimensions: ${img.width}x${img.height}`);
            const ctx = wizard.canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            wizard.hideLoadingOverlay();
            // Defer applyZoom until after browser layout settles
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
            if (drawElementOverlays) {
                drawElementOverlays(wizard);
            }
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
                console.warn('[StreamManager] Stream timeout - no frames received after 10s');
            }
        }, 10000);
    }

    // Stop any existing stream - MUST await to prevent WebSocket race condition
    await stopStreaming(wizard);

    // Always create a fresh LiveStream to ensure it's bound to current canvas
    if (wizard.liveStream) {
        wizard.liveStream = null;
    }
    wizard.liveStream = new LiveStream(wizard.canvas);
    console.log('[StreamManager] Created new LiveStream for canvas:', wizard.canvas);

    // Handle each frame - hide loading overlay and apply zoom (once per stream)
    wizard.liveStream.onFrame = (data) => {
        if (!wizard._streamLoadingHidden) {
            wizard.hideLoadingOverlay();
            wizard._streamLoadingHidden = true;

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
        }
    };

    // Wire up callbacks
    wizard.liveStream.onConnect = () => {
        updateStreamStatus(wizard, 'connected', 'Live');

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
        console.error('[StreamManager] Stream error:', error);
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
 *
 * @param {Object} wizard - The wizard state object
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
 * Resets slow connection warning flag and ensures device is unlocked
 *
 * @param {Object} wizard - The wizard state object
 * @param {Function} drawElementOverlays - Callback to draw element overlays
 */
export async function reconnectStream(wizard, drawElementOverlays) {
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

    // Ensure device is unlocked before reconnecting
    try {
        const unlockResult = await sharedEnsureUnlocked(wizard.selectedDevice, getApiBase(), {
            onStatus: (msg) => {
                if (msg.includes('Waking') || msg.includes('Unlocking')) {
                    showToast(msg, 'info', 2000);
                }
            }
        });
        if (unlockResult?.status === 'unlocked') {
            showToast('Device unlocked, connecting...', 'success', 2000);
        }
    } catch (e) {
        console.warn('[StreamManager] Unlock during reconnect failed:', e);
    }

    // Start the stream again
    startStreaming(wizard, drawElementOverlays);
}

/**
 * Start periodic element auto-refresh (for streaming mode)
 *
 * @param {Object} wizard - The wizard state object
 */
export function startElementAutoRefresh(wizard) {
    // Clear any existing interval
    stopElementAutoRefresh(wizard);

    // Get configurable interval from dropdown (default 3000ms)
    const intervalSelect = document.getElementById('elementRefreshInterval');
    const intervalMs = intervalSelect ? parseInt(intervalSelect.value) : 3000;

    // Track last frame time for debouncing
    wizard._lastFrameTime = performance.now();

    // Wrap original onFrame to track frame times
    const originalOnFrame = wizard.liveStream?.onFrame;
    if (wizard.liveStream) {
        wizard.liveStream.onFrame = (data) => {
            wizard._lastFrameTime = performance.now();
            if (originalOnFrame) originalOnFrame(data);
        };
    }

    // Start refresh with configured interval
    wizard.elementRefreshIntervalTimer = setInterval(() => {
        if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
            // Debounce: skip if a frame arrived recently (within 200ms)
            const timeSinceFrame = performance.now() - (wizard._lastFrameTime || 0);
            if (timeSinceFrame < 200) {
                return;
            }
            refreshElements(wizard);
        }
    }, intervalMs);

    console.log(`[StreamManager] Element auto-refresh started (${intervalMs / 1000}s interval, debounced)`);
}

/**
 * Stop periodic element auto-refresh
 *
 * @param {Object} wizard - The wizard state object
 */
export function stopElementAutoRefresh(wizard) {
    if (wizard.elementRefreshIntervalTimer) {
        clearInterval(wizard.elementRefreshIntervalTimer);
        wizard.elementRefreshIntervalTimer = null;
        console.log('[StreamManager] Element auto-refresh stopped');
    }
}

/**
 * Start keep-awake interval to prevent device screen timeout
 * Uses shared device-unlock.js module with 5 second interval
 * MUST be awaited to ensure first wake signal is sent
 *
 * @param {Object} wizard - The wizard state object
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

    console.log('[StreamManager] Keep-awake started (5s interval via shared module)');
}

/**
 * Stop keep-awake interval
 *
 * @param {Object} wizard - The wizard state object
 */
export function stopKeepAwake(wizard) {
    if (wizard._keepAwakeInterval) {
        sharedStopKeepAwake(wizard._keepAwakeInterval);
        wizard._keepAwakeInterval = null;
        console.log('[StreamManager] Keep-awake stopped');
    }
}

/**
 * Update stream status display
 * Makes disconnected status clickable to trigger reconnect
 *
 * @param {Object} wizard - The wizard state object
 * @param {string} className - CSS class for status styling
 * @param {string} text - Status text to display
 */
export function updateStreamStatus(wizard, className, text) {
    const statusEl = document.getElementById('connectionStatus');
    if (statusEl) {
        statusEl.className = `connection-status ${className}`;

        // Make disconnected status clickable for reconnect
        if (className === 'disconnected') {
            statusEl.textContent = text + ' (click to reconnect)';
            statusEl.style.cursor = 'pointer';
            statusEl.title = 'Click to reconnect';

            // Remove old listener if any
            if (statusEl._reconnectHandler) {
                statusEl.removeEventListener('click', statusEl._reconnectHandler);
            }

            // Add click handler for reconnect
            statusEl._reconnectHandler = () => {
                if (wizard.liveStream) {
                    // Reset reconnect attempts and delay
                    wizard.liveStream.reconnectAttempts = 0;
                    wizard.liveStream.reconnectDelay = 1000;
                    wizard.liveStream._manualStop = false;
                }
                showToast('Reconnecting...', 'info', 2000);
                reconnectStream(wizard, () => {
                    // Draw overlays callback (optional)
                    if (wizard.drawElementOverlays) {
                        wizard.drawElementOverlays();
                    }
                });
            };
            statusEl.addEventListener('click', statusEl._reconnectHandler);
        } else {
            statusEl.textContent = text;
            statusEl.style.cursor = 'default';
            statusEl.title = '';

            // Remove reconnect handler when not disconnected
            if (statusEl._reconnectHandler) {
                statusEl.removeEventListener('click', statusEl._reconnectHandler);
                statusEl._reconnectHandler = null;
            }
        }
    }
}

/**
 * Refresh elements in background
 * In streaming mode: uses fast elements-only endpoint
 * In polling mode: fetches full screenshot with elements
 *
 * @param {Object} wizard - The wizard state object
 * @param {Function} clearAllElementsAndHover - Callback to clear elements (optional)
 */
export async function refreshElements(wizard, clearAllElementsAndHover) {
    if (!wizard.selectedDevice) return;

    // Guard against concurrent refreshElements calls
    if (wizard._refreshingElements) {
        console.log('[StreamManager] refreshElements already in progress, skipping');
        return;
    }
    wizard._refreshingElements = true;

    // Safety net: auto-reset guard after 10 seconds
    const guardTimeout = setTimeout(() => {
        if (wizard._refreshingElements) {
            console.warn('[StreamManager] refreshElements guard timeout after 10s - resetting');
            wizard._refreshingElements = false;
        }
    }, 10000);

    try {
        let elements = [];
        let currentPackage = null;

        if (wizard.captureMode === 'streaming') {
            // Fast path: elements-only endpoint
            const response = await fetch(`${getApiBase()}/adb/elements/${encodeURIComponent(wizard.selectedDevice)}`);
            if (!response.ok) return;

            const data = await response.json();
            elements = data.elements || [];
            currentPackage = data.current_package;
            const currentActivity = data.current_activity;

            // Detect app/screen change and clear stale elements
            const packageChanged = currentPackage && wizard.currentElementsPackage &&
                currentPackage !== wizard.currentElementsPackage;
            const activityChanged = currentActivity && wizard.currentElementsActivity &&
                currentActivity !== wizard.currentElementsActivity;

            if (packageChanged || activityChanged) {
                const changeType = packageChanged ? 'App' : 'Screen';
                const from = packageChanged ? wizard.currentElementsPackage : wizard.currentElementsActivity;
                const to = packageChanged ? currentPackage : currentActivity;
                console.log(`[StreamManager] ${changeType} changed: ${from} → ${to}, clearing stale elements`);

                // Clear ALL element sources and hover state
                if (clearAllElementsAndHover) {
                    clearAllElementsAndHover(wizard);
                } else if (wizard.clearAllElementsAndHover) {
                    wizard.clearAllElementsAndHover();
                }

                // Force immediate redraw without old overlays
                if (wizard.liveStream?.currentImage) {
                    wizard.liveStream.ctx.clearRect(0, 0, wizard.liveStream.canvas.width, wizard.liveStream.canvas.height);
                    wizard.liveStream.ctx.drawImage(wizard.liveStream.currentImage, 0, 0);
                }
            }

            wizard.currentElementsPackage = currentPackage;
            wizard.currentElementsActivity = currentActivity;

            // Update device dimensions for proper overlay scaling
            if (data.device_width && data.device_height && wizard.liveStream) {
                const oldWidth = wizard.liveStream.deviceWidth;
                const oldHeight = wizard.liveStream.deviceHeight;
                wizard.liveStream.setDeviceDimensions(data.device_width, data.device_height);

                if (oldWidth !== data.device_width || oldHeight !== data.device_height) {
                    console.log(`[StreamManager] Device dimensions updated: ${oldWidth}x${oldHeight} → ${data.device_width}x${data.device_height}`);
                }
            }

            console.log(`[StreamManager] Fast elements refresh: ${elements.length} elements (pkg: ${currentPackage || 'unknown'})`);
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

            // Extract device dimensions from screenshot
            if (data.screenshot && wizard.liveStream) {
                const img = new Image();
                img.onload = () => {
                    wizard.liveStream.deviceWidth = img.width;
                    wizard.liveStream.deviceHeight = img.height;
                    console.log(`[StreamManager] Device dimensions: ${img.width}x${img.height}`);
                };
                img.src = 'data:image/png;base64,' + data.screenshot;
            }

            // Store metadata if recorder exists
            if (wizard.recorder) {
                wizard.recorder.currentScreenshot = data.screenshot;
                wizard.recorder.screenshotMetadata = {
                    elements: elements,
                    timestamp: data.timestamp,
                    width: wizard.recorder.screenshotMetadata?.width,
                    height: wizard.recorder.screenshotMetadata?.height,
                    quick: false
                };
            }
        }

        // Update LiveStream elements for overlay
        if (wizard.liveStream) {
            wizard.liveStream.elements = elements;

            if (wizard.liveStream.currentImage) {
                wizard.liveStream._renderFrame(wizard.liveStream.currentImage, elements);
            }
        }

        // Update element tree (deferred to avoid blocking)
        const updateUI = () => {
            if (wizard.updateElementTree) {
                wizard.updateElementTree(elements);
            }
            if (wizard.updateElementCount) {
                wizard.updateElementCount(elements.length);
            }
        };

        if (wizard.captureMode === 'streaming' && 'requestIdleCallback' in window) {
            requestIdleCallback(updateUI, { timeout: 500 });
        } else {
            updateUI();
        }

        // Update app info header
        try {
            const screenResponse = await fetch(`${getApiBase()}/adb/screen/current/${encodeURIComponent(wizard.selectedDevice)}`);
            if (screenResponse.ok) {
                const screenData = await screenResponse.json();
                if (screenData.activity) {
                    const appNameEl = document.getElementById('appName');
                    if (appNameEl && screenData.activity.package) {
                        const appName = screenData.activity.package.split('.').pop() || screenData.activity.package;
                        appNameEl.textContent = appName.charAt(0).toUpperCase() + appName.slice(1);
                    }
                }
            }
        } catch (appInfoError) {
            console.warn('[StreamManager] Failed to update app info:', appInfoError);
        }

        console.log(`[StreamManager] Elements refreshed: ${elements.length} elements`);
    } catch (error) {
        console.warn('[StreamManager] Failed to refresh elements:', error);
    } finally {
        clearTimeout(guardTimeout);
        wizard._refreshingElements = false;
    }
}

/**
 * Auto-refresh elements after an action (with delay)
 * Used in streaming mode to update element overlays after tap/swipe
 *
 * @param {Object} wizard - The wizard state object
 * @param {number} delayMs - Delay before refresh (default 500ms)
 * @param {Function} clearAllElementsAndHover - Callback to clear elements
 */
export async function refreshAfterAction(wizard, delayMs = 500, clearAllElementsAndHover) {
    // Clear all elements and hover immediately when action occurs
    if (clearAllElementsAndHover) {
        clearAllElementsAndHover(wizard);
    } else if (wizard.clearAllElementsAndHover) {
        wizard.clearAllElementsAndHover();
    }

    setTimeout(async () => {
        try {
            if (wizard.captureMode === 'streaming') {
                await refreshElements(wizard, clearAllElementsAndHover);
            } else {
                await wizard.recorder?.captureScreenshot();
                if (wizard.updateScreenshotDisplay) {
                    wizard.updateScreenshotDisplay();
                }
            }
        } catch (e) {
            console.warn('[StreamManager] Auto-refresh after action failed:', e);
        }
    }, delayMs);
}

// Export default for ES6 module pattern
export default {
    prepareDeviceForStreaming,
    startStreaming,
    stopStreaming,
    reconnectStream,
    startElementAutoRefresh,
    stopElementAutoRefresh,
    startKeepAwake,
    stopKeepAwake,
    updateStreamStatus,
    refreshElements,
    refreshAfterAction
};

// Also expose on window for global access
if (typeof window !== 'undefined') {
    window.StreamManager = {
        prepareDeviceForStreaming,
        startStreaming,
        stopStreaming,
        reconnectStream,
        startElementAutoRefresh,
        stopElementAutoRefresh,
        startKeepAwake,
        stopKeepAwake,
        updateStreamStatus,
        refreshElements,
        refreshAfterAction
    };
}
