/**
 * Streaming Control Module for Flow Wizard Step 3
 *
 * Handles:
 * - Live stream start/stop/reconnect
 * - Device preparation for streaming
 * - Keep-awake functionality
 * - Stream status display
 * - Command routing method display
 * - Companion streaming restart
 *
 * Extracted from flow-wizard-step3.js for maintainability
 * @version 0.0.1
 */

import { showToast } from '../toast.js?v=0.4.0-beta.4';
import LiveStream from '../live-stream.js?v=0.4.0-beta.9';
import {
    ensureDeviceUnlocked as sharedEnsureUnlocked,
    startKeepAwake as sharedStartKeepAwake,
    stopKeepAwake as sharedStopKeepAwake
} from '../device-unlock.js?v=0.4.0-beta.4';
import { drawElementOverlays } from '../canvas-overlay-renderer.js?v=0.4.0-beta.10';
import { showPrerequisiteGuidance } from '../prerequisite-dialog.js?v=0.4.0-beta';

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Prepare device for streaming - check lock, wake screen, unlock if needed
 * Shows a status dialog keeping user informed
 * @param {Object} wizard - The wizard instance
 * @returns {Promise<boolean>} True if device is ready
 */
export async function prepareDeviceForStreaming(wizard) {
    return new Promise((resolve) => {
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

        (async () => {
            try {
                const apiBase = wizard.recorder?.apiBase || getApiBase();

                const unlockResult = await sharedEnsureUnlocked(wizard.selectedDevice, apiBase, {
                    onStatus: (msg) => {
                        messageEl.textContent = msg;
                    },
                    onStepUpdate: (stepId, status) => {
                        updateStep(stepId, status);
                    },
                    onNeedsManualUnlock: async () => {
                        cancelBtn.textContent = 'Continue Anyway';
                        cancelBtn.className = 'btn btn-primary';
                        await new Promise(resolveWait => {
                            cancelBtn.onclick = () => {
                                resolveWait();
                            };
                        });
                    },
                    isCancelled: () => cancelled
                });

                if (cancelled) return;

                updateStep('step-connect', 'working');
                messageEl.textContent = 'Loading first frame...';

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
                            wizard._preloadedImage = data.screenshot;
                            wizard._preloadedElements = data.elements || [];
                            console.log('[Streaming] Preloaded screenshot with', wizard._preloadedElements.length, 'elements');
                        }
                    }
                } catch (e) {
                    if (e.name === 'AbortError') {
                        console.log('[Streaming] Screenshot preload timed out');
                    } else {
                        console.log('[Streaming] Screenshot preload skipped:', e);
                    }
                }

                updateStep('step-connect', 'done');
                messageEl.textContent = 'Device ready! Starting stream...';
                await new Promise(r => setTimeout(r, 300));

                cleanup();
                resolve(true);

            } catch (error) {
                console.error('[Streaming] Device preparation error:', error);
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
 * @param {Object} wizard - The wizard instance
 * @param {Object} callbacks - Callback functions from main module
 */
export async function startStreaming(wizard, callbacks = {}) {
    const {
        setSetupStatus,
        setSetupStatusReady,
        checkCompanionAppStatus,
        checkCompanionStreamingStatus,
        refreshElements
    } = callbacks;

    if (!wizard.selectedDevice) {
        showToast('No device selected', 'error');
        return;
    }

    if (setSetupStatus) setSetupStatus(wizard, 'Connecting to live stream...');

    // Check for companion app (non-blocking)
    if (checkCompanionAppStatus) {
        checkCompanionAppStatus(wizard, wizard.selectedDevice);
    }

    // Start polling for command routing method
    startRoutingMethodPolling(wizard);

    // Reset stream session flags
    wizard._streamLoadingHidden = false;
    wizard._streamConnectedOnce = false;

    if (wizard._streamLoadingTimeout) {
        clearTimeout(wizard._streamLoadingTimeout);
        wizard._streamLoadingTimeout = null;
    }

    // Show loading indicator (or preloaded image if available)
    if (wizard._preloadedImage) {
        console.log('[Streaming] Using preloaded image');
        const img = new Image();
        img.onload = () => {
            wizard.canvas.width = img.width;
            wizard.canvas.height = img.height;
            console.log(`[Streaming] Preloaded image dimensions: ${img.width}x${img.height}`);
            const ctx = wizard.canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            wizard.hideLoadingOverlay();
            if (wizard.canvasRenderer) {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        wizard.canvasRenderer.applyZoom();
                    });
                });
            }
        };
        img.src = 'data:image/jpeg;base64,' + wizard._preloadedImage;

        if (wizard._preloadedElements && wizard._preloadedElements.length > 0) {
            if (wizard.liveStream) {
                wizard.liveStream.elements = wizard._preloadedElements;
                wizard.liveStream.markElementsFresh();
            }
            wizard.recorder.screenshotMetadata = { elements: wizard._preloadedElements };
            drawElementOverlays(wizard);
        }

        wizard._preloadedImage = null;
        wizard._preloadedElements = null;
    } else {
        wizard.showLoadingOverlay('Connecting to device...');
    }

    // Stop any existing stream
    await stopStreaming(wizard, callbacks);

    // Create fresh LiveStream
    if (wizard.liveStream) {
        wizard.liveStream = null;
    }
    wizard.liveStream = new LiveStream(wizard.canvas);
    console.log('[Streaming] Created new LiveStream for canvas:', wizard.canvas);

    // Apply fluency setting
    const fluency = wizard.streamFluency || localStorage.getItem('flowWizard.streamFluency') || 'balanced';
    wizard.liveStream.setFluency(fluency);
    console.log(`[Streaming] Applied fluency: ${fluency}`);

    // Handle each frame
    wizard.liveStream.onFrame = (data) => {
        if (!wizard._streamLoadingHidden) {
            wizard._streamLoadingHidden = true;
            wizard.hideLoadingOverlay();

            if (wizard._streamLoadingTimeout) {
                clearTimeout(wizard._streamLoadingTimeout);
                wizard._streamLoadingTimeout = null;
            }

            if (wizard.canvasRenderer) {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        wizard.canvasRenderer.applyZoom();
                    });
                });
            }

            if (setSetupStatusReady) setSetupStatusReady(wizard);
        }
    };

    // Wire up callbacks
    wizard.liveStream.onConnect = () => {
        updateStreamStatus(wizard, 'connected', 'Live');

        if (!wizard._streamConnectedOnce) {
            wizard._streamConnectedOnce = true;
            showToast('Streaming started', 'success', 2000);
        }

        if (wizard.recordMode === 'prerequisite' && wizard.prereqType) {
            showPrerequisiteGuidance(wizard, wizard.prereqType);
        }

        if (refreshElements) refreshElements(wizard);
        startElementAutoRefresh(wizard, callbacks);
        startKeepAwake(wizard);
    };

    // Setup ResizeObserver
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

    wizard.liveStream.onSourceChange = (source, message, reason) => {
        if (source === 'adb') {
            updateStreamStatus(wizard, 'connected', 'Live (ADB)');

            if (!wizard._streamLoadingHidden) {
                wizard.hideLoadingOverlay();
                wizard._streamLoadingHidden = true;
            }
            if (wizard._streamLoadingTimeout) {
                clearTimeout(wizard._streamLoadingTimeout);
                wizard._streamLoadingTimeout = null;
            }

            const toastMessage = reason === 'app_launch'
                ? 'Streaming via ADB (companion stopped for app launch)'
                : (message || 'Switched to ADB streaming');
            showToast(toastMessage, 'info', 5000);

            if (refreshElements) refreshElements(wizard);
        } else if (source === 'companion') {
            updateStreamStatus(wizard, 'connected', 'Live (Fast)');
            showToast(message || 'Fast streaming restored', 'success', 3000);
            if (refreshElements) refreshElements(wizard);
        }
    };

    wizard.liveStream.onConnectionStateChange = (state, attempts) => {
        switch (state) {
            case 'connecting':
                wizard.showLoadingOverlay('Connecting to device...');
                updateStreamStatus(wizard, 'connecting', 'Connecting...');
                break;
            case 'reconnecting':
                wizard.showLoadingOverlay(`Reconnecting (${attempts})...`);
                updateStreamStatus(wizard, 'reconnecting', `Retry ${attempts}...`);
                if (attempts === 1) {
                    showToast('Connection lost, reconnecting...', 'warning', 3000);
                }
                break;
            case 'connected':
                if (!wizard._streamLoadingHidden) {
                    wizard.showLoadingOverlay('Connected - loading stream...');
                }
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
        console.error('[Streaming] Stream error:', error);
        if (setSetupStatus) setSetupStatus(wizard, 'Stream error - check device connection', 'error');
        showToast(`Stream error: ${error.message || 'Connection failed'}`, 'error', 3000);
    };

    wizard.liveStream.onMetricsUpdate = (metrics) => {
        if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
            if (!wizard._streamLoadingHidden) {
                console.log('[Streaming] Hiding overlay via onMetricsUpdate backup');
                wizard.hideLoadingOverlay();
                wizard._streamLoadingHidden = true;
            }

            const captureTime = Math.round(metrics.captureTime || 0);
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

    wizard.liveStream.onDimensionsChange = (newWidth, newHeight, oldWidth, oldHeight) => {
        console.log(`[Streaming] Dimensions changed: ${oldWidth}x${oldHeight} -> ${newWidth}x${newHeight}`);
        wizard.liveStream.elements = [];
        wizard.liveStream.markElementsFresh();
        if (wizard.canvasRenderer) {
            requestAnimationFrame(() => {
                wizard.canvasRenderer.applyZoom();
            });
        }
        if (refreshElements) refreshElements(wizard);
    };

    // Apply overlay settings
    wizard.liveStream.setDisplayMode(wizard.overlayFilters.displayMode || 'all');
    wizard.liveStream.setOverlaysVisible(wizard.overlayFilters.showClickable || wizard.overlayFilters.showNonClickable);
    wizard.liveStream.setShowClickable(wizard.overlayFilters.showClickable);
    wizard.liveStream.setShowNonClickable(wizard.overlayFilters.showNonClickable);
    wizard.liveStream.setTextLabelsVisible(wizard.overlayFilters.showTextLabels);
    wizard.liveStream.setHideContainers(wizard.overlayFilters.hideContainers);
    wizard.liveStream.setHideEmptyElements(wizard.overlayFilters.hideEmptyElements);
    wizard.liveStream.setHideSmall(wizard.overlayFilters.hideSmall);
    wizard.liveStream.setHideDividers(wizard.overlayFilters.hideDividers);

    // Check companion streaming
    let streamMode = wizard.streamMode;
    let companionActive = false;
    try {
        if (checkCompanionStreamingStatus) {
            const companionStatus = await checkCompanionStreamingStatus(wizard, wizard.selectedDevice);
            if (companionStatus.active) {
                streamMode = companionStatus.mode;
                companionActive = true;
                console.log(`[Streaming] Using companion streaming (mjpeg-v2) for faster performance`);
                showToast('Companion streaming detected - using fast mode', 'success', 3000);
            }
        }
    } catch (e) {
        console.warn('[Streaming] Companion streaming check failed:', e);
    }

    wizard.showLoadingOverlay(companionActive ? 'Connected - loading stream...' : 'Connecting...');

    const frameTimeout = companionActive ? 5000 : 10000;
    wizard._streamLoadingTimeout = setTimeout(() => {
        if (!wizard._streamLoadingHidden) {
            wizard.hideLoadingOverlay();
            wizard._streamLoadingHidden = true;
            const message = companionActive
                ? 'Companion stream slow - restart streaming on tablet'
                : 'Stream loading slowly - check device connection';
            showToast(message, 'warning', 5000);
            console.warn(`[Streaming] Stream timeout after ${frameTimeout}ms (companion: ${companionActive})`);
        }
    }, frameTimeout);

    wizard.liveStream.start(wizard.selectedDevice, streamMode, wizard.streamQuality);
    updateStreamStatus(wizard, 'connecting', 'Connecting...');
}

/**
 * Stop live streaming
 * @param {Object} wizard - The wizard instance
 * @param {Object} callbacks - Callback functions
 */
export async function stopStreaming(wizard, callbacks = {}) {
    stopElementAutoRefresh(wizard);
    stopKeepAwake(wizard);
    stopRoutingMethodPolling(wizard);

    if (wizard._streamLoadingTimeout) {
        clearTimeout(wizard._streamLoadingTimeout);
        wizard._streamLoadingTimeout = null;
    }

    if (wizard.liveStream) {
        await wizard.liveStream.stop();
    }

    updateStreamStatus(wizard, '', '');
}

/**
 * Reconnect the stream (stop and restart)
 * @param {Object} wizard - The wizard instance
 * @param {Object} callbacks - Callback functions
 */
export async function reconnectStream(wizard, callbacks = {}) {
    if (wizard.captureMode !== 'streaming') {
        showToast('Not in streaming mode', 'info', 2000);
        return;
    }

    showToast('Reconnecting stream...', 'info', 2000);
    wizard._slowConnectionWarned = false;

    await stopStreaming(wizard, callbacks);
    await new Promise(resolve => setTimeout(resolve, 300));
    await startStreaming(wizard, callbacks);
}

/**
 * Refresh device ID by checking current ADB connections
 * @param {Object} wizard - The wizard instance
 * @returns {Promise<string|null>} Updated device ID
 */
export async function refreshDeviceId(wizard) {
    const currentId = wizard.selectedDevice;
    if (!currentId) return null;

    const ipMatch = currentId.match(/^(\d+\.\d+\.\d+\.\d+)/);
    if (!ipMatch) {
        console.log('[Streaming] Device ID is not IP-based, keeping as-is:', currentId);
        return currentId;
    }
    const deviceIp = ipMatch[1];

    try {
        const response = await fetch(`${getApiBase()}/adb/devices`);
        if (!response.ok) {
            console.warn('[Streaming] Failed to fetch devices, using current ID');
            return currentId;
        }

        const data = await response.json();
        const devices = data.devices || [];
        const matchingDevice = devices.find(d => d.device_id?.startsWith(deviceIp + ':'));

        if (matchingDevice && matchingDevice.device_id !== currentId) {
            console.log(`[Streaming] Device ID changed: ${currentId} -> ${matchingDevice.device_id}`);
            wizard.selectedDevice = matchingDevice.device_id;
            return matchingDevice.device_id;
        }

        return currentId;
    } catch (error) {
        console.warn('[Streaming] Error refreshing device ID:', error);
        return currentId;
    }
}

/**
 * Restart companion streaming via MQTT
 * @param {Object} wizard - The wizard instance
 * @param {Object} callbacks - Callback functions
 */
export async function restartCompanionStreaming(wizard, callbacks = {}) {
    const deviceId = await refreshDeviceId(wizard);
    if (!deviceId) {
        showToast('No device selected - please select a device first', 'error', 2000);
        return;
    }

    showToast('Restarting companion streaming...', 'info', 3000);
    console.log('[Streaming] Restarting companion streaming for', deviceId);

    try {
        const response = await fetch(`${getApiBase()}/stream/companion/${encodeURIComponent(deviceId)}/restart`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const result = await response.json();
        console.log('[Streaming] Restart companion streaming result:', result);

        if (result.success) {
            const accessibilityNotRunning =
                result.restart_result?.error?.includes('Accessibility') ||
                result.click_result?.error?.includes('Accessibility') ||
                result.message?.includes('manual approval');

            if (accessibilityNotRunning) {
                showAccessibilityServicePrompt();
            }

            showToast(result.message || 'Companion streaming restarted', 'success', 3000);

            await new Promise(resolve => setTimeout(resolve, 2000));
            await reconnectStream(wizard, callbacks);
        } else {
            if (result.error?.includes('Accessibility')) {
                showAccessibilityServicePrompt();
            }
            showToast(result.error || 'Failed to restart companion streaming', 'error', 3000);
        }
    } catch (error) {
        console.error('[Streaming] Failed to restart companion streaming:', error);
        showToast(`Error: ${error.message}`, 'error', 3000);
    }
}

/**
 * Show accessibility service prompt dialog
 */
export function showAccessibilityServicePrompt() {
    const existing = document.getElementById('accessibilityPromptDialog');
    if (existing) existing.remove();

    const dialog = document.createElement('div');
    dialog.id = 'accessibilityPromptDialog';
    dialog.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;

    dialog.innerHTML = `
        <div style="
            background: white;
            border-radius: 12px;
            padding: 24px;
            max-width: 420px;
            margin: 16px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        ">
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
                <span style="font-size: 32px;">⚙️</span>
                <h3 style="margin: 0; color: #1a1a2e;">Enable Accessibility Service</h3>
            </div>

            <p style="color: #666; line-height: 1.5; margin-bottom: 16px;">
                For <strong>automatic streaming restart</strong> without manual approval, enable the
                Accessibility Service in the companion app on your device.
            </p>

            <div style="background: #f0f9ff; border-left: 4px solid #0ea5e9; padding: 12px; border-radius: 4px; margin-bottom: 20px;">
                <p style="margin: 0; color: #0369a1; font-size: 14px;">
                    <strong>How to enable:</strong><br>
                    1. Open <strong>Visual Mapper Companion</strong> app<br>
                    2. Go to <strong>Settings</strong> tab<br>
                    3. Tap <strong>Enable Accessibility Service</strong><br>
                    4. Find "Visual Mapper Companion" and enable it
                </p>
            </div>

            <div style="display: flex; gap: 12px; justify-content: flex-end;">
                <button id="btnAccessibilityDismiss" style="
                    padding: 10px 20px;
                    border: 1px solid #ddd;
                    border-radius: 6px;
                    background: white;
                    cursor: pointer;
                    font-size: 14px;
                ">Dismiss</button>
                <button id="btnAccessibilityOpenApp" style="
                    padding: 10px 20px;
                    border: none;
                    border-radius: 6px;
                    background: #3b82f6;
                    color: white;
                    cursor: pointer;
                    font-size: 14px;
                ">Open Companion App</button>
            </div>
        </div>
    `;

    document.body.appendChild(dialog);

    document.getElementById('btnAccessibilityDismiss').onclick = () => dialog.remove();
    document.getElementById('btnAccessibilityOpenApp').onclick = async () => {
        dialog.remove();
        try {
            const deviceId = window.flowWizard?.selectedDevice;
            if (deviceId) {
                await fetch(`${getApiBase()}/adb/shell`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        device_id: deviceId,
                        command: 'am start -n com.visualmapper.companion/.ui.fragments.MainContainerActivity'
                    })
                });
                showToast('Opening companion app...', 'info', 2000);
            }
        } catch (e) {
            console.warn('[Streaming] Could not open companion app:', e);
        }
    };

    dialog.onclick = (e) => {
        if (e.target === dialog) dialog.remove();
    };
}

/**
 * Start element auto-refresh
 * @param {Object} wizard - The wizard instance
 * @param {Object} callbacks - Callback functions
 */
export function startElementAutoRefresh(wizard, callbacks = {}) {
    const { refreshElements } = callbacks;

    stopElementAutoRefresh(wizard);

    const intervalSelect = document.getElementById('elementRefreshInterval');
    const intervalMs = intervalSelect ? parseInt(intervalSelect.value) : 5000;

    wizard._lastFrameTime = performance.now();

    if (wizard.liveStream) {
        console.log('[Streaming] Setting up smart refresh callback');
        wizard.liveStream.onScreenChange = () => {
            if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
                console.log('[Streaming] Smart refresh triggered');
                if (refreshElements) refreshElements(wizard);
                wizard._lastElementRefreshTime = performance.now();
            }
        };
    } else {
        console.warn('[Streaming] No liveStream - smart refresh not available');
    }

    const originalOnFrame = wizard.liveStream?.onFrame;
    if (wizard.liveStream) {
        wizard.liveStream.onFrame = (data) => {
            wizard._lastFrameTime = performance.now();
            if (originalOnFrame) originalOnFrame(data);
        };
    }

    wizard.elementRefreshIntervalTimer = setInterval(() => {
        if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
            const timeSinceRefresh = performance.now() - (wizard._lastElementRefreshTime || 0);
            if (timeSinceRefresh < intervalMs * 0.9) {
                return;
            }
            console.log('[Streaming] Fallback interval refresh triggered');
            if (refreshElements) refreshElements(wizard);
            wizard._lastElementRefreshTime = performance.now();
        }
    }, intervalMs);

    console.log(`[Streaming] Smart element refresh enabled (fallback: ${intervalMs / 1000}s interval)`);
}

/**
 * Stop element auto-refresh
 * @param {Object} wizard - The wizard instance
 */
export function stopElementAutoRefresh(wizard) {
    if (wizard.elementRefreshIntervalTimer) {
        clearInterval(wizard.elementRefreshIntervalTimer);
        wizard.elementRefreshIntervalTimer = null;
    }
    if (wizard.liveStream) {
        wizard.liveStream.onScreenChange = null;
        wizard.liveStream.onElementsCleared = null;
    }
    console.log('[Streaming] Element auto-refresh stopped');
}

/**
 * Start keep-awake interval
 * @param {Object} wizard - The wizard instance
 */
export async function startKeepAwake(wizard) {
    stopKeepAwake(wizard);

    if (!wizard.selectedDevice) return;

    wizard._keepAwakeInterval = await sharedStartKeepAwake(
        wizard.selectedDevice,
        getApiBase()
    );

    console.log('[Streaming] Keep-awake started (5s interval via shared module)');
}

/**
 * Stop keep-awake interval
 * @param {Object} wizard - The wizard instance
 */
export function stopKeepAwake(wizard) {
    if (wizard._keepAwakeInterval) {
        sharedStopKeepAwake(wizard._keepAwakeInterval);
        wizard._keepAwakeInterval = null;
        console.log('[Streaming] Keep-awake stopped');
    }
}

/**
 * Update stream status display
 * @param {Object} wizard - The wizard instance
 * @param {string} className - CSS class name
 * @param {string} text - Status text
 */
export function updateStreamStatus(wizard, className, text) {
    const statusEl = document.getElementById('connectionStatus');
    if (statusEl) {
        statusEl.className = `connection-status ${className}`;
        statusEl.textContent = text;
    }
}

/**
 * Update command method badge
 * @param {string} method - 'websocket', 'mqtt', or 'adb'
 */
export function updateCommandMethodBadge(method) {
    const badge = document.getElementById('commandMethodBadge');
    const label = document.getElementById('commandMethodLabel');

    if (!badge || !label) return;

    badge.classList.remove('method-websocket', 'method-mqtt', 'method-adb', 'method-unknown');

    const methodLower = (method || '').toLowerCase();
    switch (methodLower) {
        case 'websocket':
            badge.classList.add('method-websocket');
            label.textContent = 'WS';
            badge.title = 'Commands via WebSocket (fastest - companion streaming)';
            break;
        case 'mqtt':
            badge.classList.add('method-mqtt');
            label.textContent = 'MQTT';
            badge.title = 'Commands via MQTT (companion connected)';
            break;
        case 'adb':
            badge.classList.add('method-adb');
            label.textContent = 'ADB';
            badge.title = 'Commands via ADB (fallback - may interrupt stream)';
            break;
        default:
            badge.classList.add('method-unknown');
            label.textContent = '--';
            badge.title = 'Command routing method unknown';
    }
}

/**
 * Fetch current command routing method from backend
 * @param {Object} wizard - The wizard instance
 */
export async function fetchCommandRoutingMethod(wizard) {
    if (!wizard.selectedDevice) return;

    try {
        const response = await fetch(
            `${getApiBase()}/adb/routing/${encodeURIComponent(wizard.selectedDevice)}`
        );
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.preferred_method) {
                updateCommandMethodBadge(data.preferred_method);
            }
        }
    } catch (error) {
        console.warn('[Streaming] Failed to fetch routing method:', error);
    }
}

/**
 * Start periodic polling for command routing method
 * @param {Object} wizard - The wizard instance
 */
export function startRoutingMethodPolling(wizard) {
    if (wizard._routingMethodInterval) {
        clearInterval(wizard._routingMethodInterval);
    }

    fetchCommandRoutingMethod(wizard);

    wizard._routingMethodInterval = setInterval(() => {
        fetchCommandRoutingMethod(wizard);
    }, 5000);
}

/**
 * Stop routing method polling
 * @param {Object} wizard - The wizard instance
 */
export function stopRoutingMethodPolling(wizard) {
    if (wizard._routingMethodInterval) {
        clearInterval(wizard._routingMethodInterval);
        wizard._routingMethodInterval = null;
    }
}
