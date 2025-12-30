/**
 * Flow Wizard Step 3 Module - Recording Mode
 * Visual Mapper v0.0.14
 *
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

import { showToast } from './toast.js?v=0.0.5';
import FlowCanvasRenderer from './flow-canvas-renderer.js?v=0.0.9';
import FlowInteractions from './flow-interactions.js?v=0.0.15';
import FlowStepManager from './flow-step-manager.js?v=0.0.5';
import FlowRecorder from './flow-recorder.js?v=0.0.9';
import LiveStream from './live-stream.js?v=0.0.18';
import * as Dialogs from './flow-wizard-dialogs.js?v=0.0.6';

// Helper to get API base (from global set by init.js)
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Load Step 3: Recording Mode
 */
export async function loadStep3(wizard) {
    console.log('Loading Step 3: Recording Mode');
    showToast(`Starting recording session...`, 'info');

    // Populate app info header
    populateAppInfo(wizard);

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

    wizard.interactions = new FlowInteractions(getApiBase());

    wizard.stepManager = new FlowStepManager(document.getElementById('flowStepsList'));

    // Initialize FlowRecorder (pass package name, not full object)
    const packageName = wizard.selectedApp?.package || wizard.selectedApp;
    wizard.recorder = new FlowRecorder(wizard.selectedDevice, packageName, wizard.recordMode);

    // Setup UI event listeners
    setupRecordingUI(wizard);

    // Setup flow steps event listeners (for step added/removed events)
    setupFlowStepsListener(wizard);

    // Start recording session
    const started = await wizard.recorder.start();

    if (started) {
        // Only load initial screenshot in polling mode
        // Streaming mode will handle display via LiveStream callbacks
        if (wizard.captureMode !== 'streaming') {
            await wizard.updateScreenshotDisplay();
            // Auto-fetch full screenshot with elements after initial quick preview
            // This runs in background while user sees the quick preview
            refreshElements(wizard).then(() => {
                wizard.updateScreenshotDisplay();
            }).catch(e => console.warn('[FlowWizard] Auto-refresh failed:', e));
        }
    }
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
        } else {
            activityEl.textContent = '--';
        }
    } catch (e) {
        console.warn('[FlowWizard] Error updating screen info:', e);
        activityEl.textContent = '--';
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
                // Streaming mode: just update LiveStream overlay settings
                if (wizard.liveStream) {
                    wizard.liveStream.setOverlaysVisible(
                        wizard.overlayFilters.showClickable || wizard.overlayFilters.showNonClickable
                    );
                    wizard.liveStream.setTextLabelsVisible(wizard.overlayFilters.showTextLabels);
                    wizard.liveStream.setHideContainers(wizard.overlayFilters.hideContainers);
                    wizard.liveStream.setHideEmptyElements(wizard.overlayFilters.hideEmptyElements);
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
    const savedQuality = localStorage.getItem('flowWizard.streamQuality') || 'medium';

    // Handle capture mode change (select dropdown)
    if (captureModeSelect) {
        captureModeSelect.value = savedMode;
        setCaptureMode(wizard, savedMode);

        captureModeSelect.addEventListener('change', (e) => {
            const mode = e.target.value;
            localStorage.setItem('flowWizard.captureMode', mode);
            setCaptureMode(wizard, mode);
        });
    }

    // Handle stream mode change (mjpeg vs websocket)
    if (streamModeSelect) {
        streamModeSelect.value = savedStreamMode;
        wizard.streamMode = savedStreamMode;

        streamModeSelect.addEventListener('change', (e) => {
            wizard.streamMode = e.target.value;
            localStorage.setItem('flowWizard.streamMode', e.target.value);
            // If streaming, restart with new mode
            if (wizard.captureMode === 'streaming' && wizard.liveStream?.isActive()) {
                startStreaming(wizard);
            }
        });
    }

    // Handle quality change
    if (qualitySelect) {
        qualitySelect.value = savedQuality;
        wizard.streamQuality = savedQuality;

        qualitySelect.addEventListener('change', (e) => {
            wizard.streamQuality = e.target.value;
            localStorage.setItem('flowWizard.streamQuality', e.target.value);
            // If streaming, restart with new quality
            if (wizard.captureMode === 'streaming' && wizard.liveStream?.isActive()) {
                startStreaming(wizard);
            }
        });
    }

    console.log('[FlowWizard] Capture mode controls initialized');
}

/**
 * Set capture mode (polling or streaming)
 */
export function setCaptureMode(wizard, mode) {
    const streamModeSelect = document.getElementById('streamMode');
    const qualitySelect = document.getElementById('streamQuality');

    // Get buttons that are mode-specific
    const refreshBtn = document.getElementById('qabRefresh');
    const stitchBtn = document.getElementById('qabStitch');
    const zoomOutBtn = document.getElementById('qabZoomOut');
    const zoomInBtn = document.getElementById('qabZoomIn');
    const scaleBtn = document.getElementById('qabScale');

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

        startStreaming(wizard);
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

        stopStreaming(wizard);
    }

    console.log(`[FlowWizard] Capture mode: ${mode}`);
}

/**
 * Start live streaming
 */
export function startStreaming(wizard) {
    if (!wizard.selectedDevice) {
        showToast('No device selected', 'error');
        return;
    }

    // Show loading indicator immediately
    wizard.showLoadingOverlay('Connecting to device...');

    // Pre-fetch elements while stream is connecting (faster startup)
    refreshElements(wizard).catch(e => console.warn('[FlowWizard] Pre-fetch elements failed:', e));

    // Stop any existing stream
    stopStreaming(wizard);

    // Initialize LiveStream if needed
    if (!wizard.liveStream) {
        wizard.liveStream = new LiveStream(wizard.canvas);

        // Handle each frame - hide loading and reapply zoom
        wizard.liveStream.onFrame = (data) => {
            wizard.hideLoadingOverlay();
            // Reapply zoom after each frame to ensure CSS sizing persists
            // This is needed because LiveStream updates canvas bitmap dimensions
            if (wizard.canvasRenderer) {
                wizard.canvasRenderer.applyZoom();
            }
        };

        // Wire up callbacks
        wizard.liveStream.onConnect = () => {
            updateStreamStatus(wizard, 'connected', 'Live');
            wizard.showLoadingOverlay('Loading stream...');
            showToast('Streaming started', 'success', 2000);
            // Fetch elements (may already be loaded from pre-fetch)
            refreshElements(wizard);
            // Start periodic element refresh (every 3 seconds)
            startElementAutoRefresh(wizard);
        };

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
            showToast(`Stream error: ${error.message || 'Connection failed'}`, 'error', 3000);
        };

        // Show FPS and capture time in status (updates every few frames)
        wizard.liveStream.onMetricsUpdate = (metrics) => {
            if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
                // Determine connection quality based on capture time
                const captureTime = metrics.captureTime || 0;
                let quality = 'connected'; // CSS class
                let statusText = `${metrics.fps} FPS`;

                if (captureTime > 0) {
                    statusText = `${metrics.fps} FPS (${captureTime}ms)`;

                    // Quality indicator based on capture time
                    if (captureTime > 1000) {
                        quality = 'slow'; // > 1 second = very slow
                    } else if (captureTime > 500) {
                        quality = 'ok'; // 500ms-1s = acceptable but slow
                    } else {
                        quality = 'good'; // < 500ms = good
                    }
                }

                updateStreamStatus(wizard, quality, statusText);

                // Warn user once if connection is very slow (only on first slow frame detection)
                if (captureTime > 2000 && !wizard._slowConnectionWarned) {
                    wizard._slowConnectionWarned = true;
                    showToast('Slow connection - try USB for better performance', 'warning', 5000);
                }
            }
        };

        // Apply current overlay settings
        wizard.liveStream.setOverlaysVisible(wizard.overlayFilters.showClickable || wizard.overlayFilters.showNonClickable);
        wizard.liveStream.setTextLabelsVisible(wizard.overlayFilters.showTextLabels);
        wizard.liveStream.setHideContainers(wizard.overlayFilters.hideContainers);
        wizard.liveStream.setHideEmptyElements(wizard.overlayFilters.hideEmptyElements);
    }

    // Start streaming with selected mode (mjpeg or websocket)
    wizard.liveStream.start(wizard.selectedDevice, wizard.streamMode, wizard.streamQuality);
    updateStreamStatus(wizard, 'connecting', 'Connecting...');
}

/**
 * Stop live streaming
 */
export function stopStreaming(wizard) {
    // Stop element auto-refresh
    stopElementAutoRefresh(wizard);

    if (wizard.liveStream) {
        wizard.liveStream.stop();
    }
    updateStreamStatus(wizard, '', '');
}

/**
 * Reconnect the stream (stop and restart)
 * Resets slow connection warning flag
 */
export function reconnectStream(wizard) {
    if (wizard.captureMode !== 'streaming') {
        showToast('Not in streaming mode', 'info', 2000);
        return;
    }

    showToast('Reconnecting stream...', 'info', 2000);

    // Reset slow connection warning
    wizard._slowConnectionWarned = false;

    // Stop and restart the stream
    stopStreaming(wizard);

    // Small delay before reconnecting
    setTimeout(() => {
        startStreaming(wizard);
    }, 500);
}

/**
 * Start periodic element auto-refresh (for streaming mode)
 */
export function startElementAutoRefresh(wizard) {
    // Clear any existing interval
    stopElementAutoRefresh(wizard);

    // Get configurable interval from dropdown (default 3000ms)
    const intervalSelect = document.getElementById('elementRefreshInterval');
    const intervalMs = intervalSelect ? parseInt(intervalSelect.value) : 3000;

    // Start refresh with configured interval
    wizard.elementRefreshIntervalTimer = setInterval(() => {
        if (wizard.captureMode === 'streaming' && wizard.liveStream?.connectionState === 'connected') {
            // Log with timestamp so user can verify actual interval
            const now = new Date().toLocaleTimeString();
            console.log(`[FlowWizard] Timer tick at ${now} - refreshing elements...`);
            refreshElements(wizard);
        }
    }, intervalMs);

    console.log(`[FlowWizard] Element auto-refresh started (${intervalMs / 1000}s interval)`);
}

/**
 * Stop periodic element auto-refresh
 */
export function stopElementAutoRefresh(wizard) {
    if (wizard.elementRefreshIntervalTimer) {
        clearInterval(wizard.elementRefreshIntervalTimer);
        wizard.elementRefreshIntervalTimer = null;
        console.log('[FlowWizard] Element auto-refresh stopped');
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

    try {
        let elements = [];

        if (wizard.captureMode === 'streaming') {
            // Fast path: elements-only endpoint (no screenshot capture)
            const response = await fetch(`${getApiBase()}/adb/elements/${encodeURIComponent(wizard.selectedDevice)}`);
            if (!response.ok) return;

            const data = await response.json();
            elements = data.elements || [];

            // Update device dimensions for proper overlay scaling
            if (data.device_width && data.device_height && wizard.liveStream) {
                const oldWidth = wizard.liveStream.deviceWidth;
                const oldHeight = wizard.liveStream.deviceHeight;
                wizard.liveStream.setDeviceDimensions(data.device_width, data.device_height);

                if (oldWidth !== data.device_width || oldHeight !== data.device_height) {
                    console.log(`[FlowWizard] Device dimensions updated: ${oldWidth}x${oldHeight} → ${data.device_width}x${data.device_height}`);
                }
            }

            console.log(`[FlowWizard] Fast elements refresh: ${elements.length} elements`);
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
            }
        }

        // Update LiveStream elements for overlay
        if (wizard.liveStream) {
            // Clear old elements and force canvas redraw
            wizard.liveStream.elements = [];  // Clear first to trigger re-render

            // Force canvas clear and redraw with new elements
            if (wizard.liveStream.currentImage) {
                wizard.liveStream.ctx.clearRect(0, 0, wizard.liveStream.canvas.width, wizard.liveStream.canvas.height);
                wizard.liveStream.ctx.drawImage(wizard.liveStream.currentImage, 0, 0);
            }

            // Now set new elements
            wizard.liveStream.elements = elements;

            // Redraw with new elements
            if (wizard.liveStream.currentImage) {
                wizard.liveStream._renderFrame(wizard.liveStream.currentImage, elements);
            }
        }

        // Update element tree
        wizard.updateElementTree(elements);
        wizard.updateElementCount(elements.length);

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
                }
            }
        } catch (appInfoError) {
            console.warn('[FlowWizard] Failed to update app info:', appInfoError);
        }

        console.log(`[FlowWizard] Elements refreshed: ${elements.length} elements`);
    } catch (error) {
        console.warn('[FlowWizard] Failed to refresh elements:', error);
    }
}

/**
 * Auto-refresh elements after an action (with delay)
 * Used in streaming mode to update element overlays after tap/swipe
 */
export async function refreshAfterAction(wizard, delayMs = 500) {
    if (wizard.captureMode !== 'streaming') return;

    setTimeout(async () => {
        try {
            await refreshElements(wizard);
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
    const elements = wizard.recorder?.screenshotMetadata?.elements || wizard.liveStream?.elements || [];
    if (elements.length === 0) {
        hideHoverTooltip(wizard, hoverTooltip);
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

    // Container classes to filter out (same as FlowInteractions)
    const containerClasses = [
        'android.view.View', 'android.view.ViewGroup', 'android.widget.FrameLayout',
        'android.widget.LinearLayout', 'android.widget.RelativeLayout',
        'android.widget.ScrollView', 'android.widget.HorizontalScrollView',
        'androidx.constraintlayout.widget.ConstraintLayout',
        'androidx.recyclerview.widget.RecyclerView', 'androidx.cardview.widget.CardView'
    ];

    // Find elements at hover position (filter containers)
    let elementsAtPoint = [];
    for (let i = elements.length - 1; i >= 0; i--) {
        const el = elements[i];
        if (!el.bounds) continue;

        // Skip containers if filter is enabled (BUT keep clickable containers - they're usually buttons)
        if (wizard.overlayFilters?.hideContainers && el.class && containerClasses.includes(el.class)) {
            const isUsefulContainer = el.clickable || (el.resource_id && el.resource_id.trim());
            if (!isUsefulContainer) continue;
        }

        // Skip empty elements if filter is enabled
        if (wizard.overlayFilters?.hideEmptyElements) {
            const hasText = el.text && el.text.trim();
            const hasContentDesc = el.content_desc && el.content_desc.trim();
            const hasResourceId = el.resource_id && el.resource_id.trim();
            if (!hasText && !hasContentDesc && !(el.clickable && hasResourceId)) {
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
    const offsetX = canvasRect.left - containerRect.left + container.scrollLeft;
    const offsetY = canvasRect.top - containerRect.top + container.scrollTop;

    // Get CSS scale (canvas bitmap size to display size)
    const cssScale = canvasRect.width / wizard.canvas.width;

    // In streaming mode, element bounds are in device coords, canvas may be at lower res
    // We need to scale: device coords → canvas coords → CSS display coords
    let deviceToCanvasScale = 1;
    if (wizard.captureMode === 'streaming' && wizard.liveStream) {
        // Scale from device resolution to canvas resolution
        deviceToCanvasScale = wizard.canvas.width / wizard.liveStream.deviceWidth;
    }

    const b = element.bounds;
    // First scale from device to canvas, then from canvas to CSS display
    const totalScale = deviceToCanvasScale * cssScale;
    const x = b.x * totalScale + offsetX;
    const y = b.y * totalScale + offsetY;
    const w = b.width * totalScale;
    const h = b.height * totalScale;

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

        // Add swipe step to flow (unless recording is paused)
        if (!wizard.recordingPaused) {
            wizard.recorder.addStep({
                step_type: 'swipe',
                start_x: startDevice.x,
                start_y: startDevice.y,
                end_x: endDevice.x,
                end_y: endDevice.y,
                duration: 300,
                description: `Swipe from (${startDevice.x},${startDevice.y}) to (${endDevice.x},${endDevice.y})`
            });
            showToast('Swipe recorded', 'success', 1500);
        } else {
            showToast('Swipe executed (not recorded)', 'info', 1500);
        }

        // Clear stale elements immediately (video updates faster than elements API)
        if (wizard.captureMode === 'streaming' && wizard.liveStream) {
            wizard.liveStream.elements = [];
        }

        // Refresh elements after swipe (give device time to settle)
        refreshAfterAction(wizard, 800);

        // Update screenshot in polling mode
        if (wizard.captureMode === 'polling') {
            await wizard.recorder.wait(400);
            await wizard.recorder.captureScreenshot();
            wizard.updateScreenshotDisplay();
        }

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
        description: `Tap "${element.text || element.class}"`
    });

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
    const Dialogs = await import('./flow-wizard-dialogs.js?v=0.0.6');

    // Go directly to text sensor creation (most common case from element tree)
    await Dialogs.createTextSensor(wizard, element, coords);
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
    const Dialogs = await import('./flow-wizard-dialogs.js?v=0.0.6');

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
 * Handle Smart Suggestions button click
 * Shows AI-powered sensor suggestions
 */
export async function handleSmartSuggestions(wizard) {
    if (!wizard.selectedDevice) {
        showToast('Please select a device first', 'warning');
        return;
    }

    try {
        // Dynamically import SmartSuggestions module
        // Use timestamp to force cache refresh (browser was aggressively caching)
        const cacheBust = Date.now();
        const SmartSuggestionsModule = await import(`./smart-suggestions.js?v=0.0.10&t=${cacheBust}`);
        const SmartSuggestions = SmartSuggestionsModule.default || window.SmartSuggestions;

        // Create instance and show (pass wizard for full creator dialog access)
        const smartSuggestions = new SmartSuggestions();
        await smartSuggestions.show(wizard, wizard.selectedDevice, (sensors) => {
            // Callback when sensors are added
            handleBulkSensorAddition(wizard, sensors);
        });

    } catch (error) {
        console.error('[FlowWizard] Failed to load Smart Suggestions:', error);
        showToast('Failed to load Smart Suggestions', 'error');
    }
}

/**
 * Handle bulk sensor addition from Smart Suggestions
 */
async function handleBulkSensorAddition(wizard, sensors) {
    console.log('[FlowWizard] Adding bulk sensors:', sensors);

    // Import Dialogs module
    const Dialogs = await import('./flow-wizard-dialogs.js?v=0.0.6');

    // Add each sensor to the flow
    for (const sensor of sensors) {
        // Create sensor step
        const sensorStep = {
            step_type: 'capture_sensors',
            sensors: [{
                name: sensor.name,
                entity_id: sensor.entity_id,
                element: sensor.element,
                device_class: sensor.device_class || 'none',
                unit_of_measurement: sensor.unit_of_measurement || null,
                icon: sensor.icon || 'mdi:eye'
            }],
            wait_before: 0,
            wait_after: 0
        };

        // Add to flow
        wizard.recorder.addStep(sensorStep);
    }

    // Update UI
    wizard.updateFlowStepsUI();

    showToast(`Added ${sensors.length} sensor(s) to flow!`, 'success');
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

    // Show selection dialog
    const choice = await wizard.interactions.showElementSelectionDialog(clickedElement, deviceCoords);

    if (!choice) {
        return; // User cancelled
    }

    // Import Dialogs module dynamically
    const Dialogs = await import('./flow-wizard-dialogs.js?v=0.0.6');

    // Execute based on choice
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
            await Dialogs.createTextSensor(wizard, clickedElement, deviceCoords);
            break;

        case 'sensor_image':
            await Dialogs.createImageSensor(wizard, clickedElement, deviceCoords);
            break;

        case 'action':
            await Dialogs.createAction(wizard, clickedElement, deviceCoords);
            break;

        case 'refresh':
            await handleRefreshWithRetries(wizard);
            break;
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

    // Execute tap if in execute mode
    if (wizard.recordMode === 'execute') {
        await wizard.recorder.executeTap(x, y);
    }

    // Build step description
    let description = `Tap at (${x}, ${y})`;
    if (element) {
        if (element.text) {
            description = `Tap "${element.text}" at (${x}, ${y})`;
        } else if (element.content_desc) {
            description = `Tap "${element.content_desc}" at (${x}, ${y})`;
        } else if (element.resource_id) {
            const shortId = element.resource_id.split('/').pop() || element.resource_id;
            description = `Tap ${shortId} at (${x}, ${y})`;
        }
    }

    // Add tap step to flow with optional element metadata
    const step = {
        step_type: 'tap',
        x: x,
        y: y,
        description: description
    };

    // Include element metadata if available
    if (element) {
        step.element = {
            text: element.text || null,
            resource_id: element.resource_id || null,
            class: element.class || null,
            content_desc: element.content_desc || null,
            clickable: element.clickable || false,
            bounds: element.bounds || null
        };
    }

    // Add step to flow (unless recording is paused)
    if (!wizard.recordingPaused) {
        wizard.recorder.addStep(step);
    }

    // Capture new screenshot after tap
    if (wizard.recordMode === 'execute') {
        await wizard.recorder.wait(500); // Wait for UI to update
        await wizard.recorder.captureScreenshot();
    }

    // Refresh elements in streaming mode
    refreshAfterAction(wizard, 500);
}

/**
 * Show visual tap indicator on canvas
 */
export function showTapIndicator(wizard, x, y) {
    wizard.canvasRenderer.showTapIndicator(x, y);

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
            const ElementActions = await import('./flow-wizard-element-actions.js?v=0.0.5');
            await ElementActions.addTapStepFromElement(wizard, interactiveElements[index]);
        });
    });

    panel.querySelectorAll('.btn-type').forEach(btn => {
        btn.addEventListener('click', async () => {
            const index = parseInt(btn.dataset.index);
            const ElementActions = await import('./flow-wizard-element-actions.js?v=0.0.5');
            await ElementActions.addTypeStepFromElement(wizard, interactiveElements[index]);
        });
    });

    panel.querySelectorAll('.btn-sensor').forEach(btn => {
        btn.addEventListener('click', async () => {
            const index = parseInt(btn.dataset.index);
            const ElementActions = await import('./flow-wizard-element-actions.js?v=0.0.5');
            await ElementActions.addSensorCaptureFromElement(wizard, interactiveElements[index], index);
        });
    });

    panel.querySelectorAll('.btn-action').forEach(btn => {
        btn.addEventListener('click', async () => {
            const index = parseInt(btn.dataset.index);
            const Dialogs = await import('./flow-wizard-dialogs.js?v=0.0.6');
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
 */
export function drawTextLabel(wizard, text, x, y, w, isClickable) {
    const labelHeight = 20;
    const padding = 2;

    // Truncate long text
    const maxChars = Math.floor(w / 7); // Approximate chars that fit
    const displayText = text.length > maxChars
        ? text.substring(0, maxChars - 3) + '...'
        : text;

    // Draw background (matching element color)
    wizard.ctx.fillStyle = isClickable ? '#22c55e' : '#3b82f6';
    wizard.ctx.fillRect(x, y, w, labelHeight);

    // Draw text
    wizard.ctx.fillStyle = '#ffffff';
    wizard.ctx.font = '12px monospace';
    wizard.ctx.textBaseline = 'top';
    wizard.ctx.fillText(displayText, x + padding, y + padding);
}

/**
 * Setup flow steps event listeners
 * Listens for flowStepAdded and flowStepRemoved events during recording
 */
export function setupFlowStepsListener(wizard) {
    const stepsList = document.getElementById('flowStepsList');

    window.addEventListener('flowStepAdded', (e) => {
        const { step, index } = e.detail;

        const stepHtml = `
            <div class="flow-step-item" data-step-index="${index}">
                <div class="step-number-badge">${index + 1}</div>
                <div class="step-content">
                    <div class="step-description">${step.description}</div>
                </div>
                <div class="step-actions">
                    <button class="btn btn-sm" onclick="window.flowWizard.recorder.removeStep(${index})">✕</button>
                </div>
            </div>
        `;

        stepsList.insertAdjacentHTML('beforeend', stepHtml);

        // Auto-switch to Flow tab when step is added
        wizard.switchToTab('flow');

        // Update step count badge
        wizard.updateFlowStepsUI();
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
    startStreaming,
    stopStreaming,
    reconnectStream,
    startElementAutoRefresh,
    stopElementAutoRefresh,
    updateStreamStatus,
    refreshElements,
    refreshAfterAction,
    setupHoverTooltip,
    handleCanvasHover,
    showHoverTooltip,
    updateTooltipPosition,
    hideHoverTooltip,
    highlightHoveredElement,
    clearHoverHighlight,
    onGestureStart,
    onGestureEnd,
    executeSwipeGesture,
    showTapRipple,
    showSwipePath,
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
    setupFlowStepsListener
};

// Global export for backward compatibility
window.FlowWizardStep3 = Step3Module;

export default Step3Module;
