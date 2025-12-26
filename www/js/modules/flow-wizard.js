/**
 * Flow Wizard Module
 * Visual Mapper v0.0.6
 *
 * Interactive wizard for creating flows with recording mode
 * Refactored: Steps 1,2,4,5 use separate modules
 */

import { showToast } from './toast.js?v=0.0.5';
import FlowRecorder from './flow-recorder.js?v=0.0.6';
import FlowCanvasRenderer from './flow-canvas-renderer.js?v=0.0.5';
import FlowElementPanel from './flow-element-panel.js?v=0.0.5';
import FlowInteractions from './flow-interactions.js?v=0.0.9';
import FlowStepManager from './flow-step-manager.js?v=0.0.5';
import LiveStream from './live-stream.js?v=0.0.7';

// Step modules
import * as Step1 from './flow-wizard-step1.js?v=0.0.5';
import * as Step2 from './flow-wizard-step2.js?v=0.0.5';
import * as Step4 from './flow-wizard-step4.js?v=0.0.5';
import * as Step5 from './flow-wizard-step5.js?v=0.0.5';

// Helper to get API base (from global set by init.js)
function getApiBase() {
    return window.API_BASE || '/api';
}

class FlowWizard {
    constructor() {
        this.currentStep = 1;
        this.totalSteps = 5;
        this.selectedDevice = null;
        this.selectedApp = null;
        this.recordMode = 'execute';
        this.recorder = null;
        this.flowSteps = [];
        this.overlayFilters = {
            showClickable: true,
            showNonClickable: true,
            showTextLabels: true,
            hideSmall: false,
            textOnly: false
        };

        // Capture state tracking (prevent concurrent captures)
        this.captureInProgress = false;
        this.currentCaptureType = null; // 'normal' or 'stitch'

        // Canvas scaling
        this.scaleMode = 'fit'; // 'fit' or '1:1'
        this.currentScale = 1.0;

        // Dev toggle for icon source display
        this.showIconSources = false;
        this.queueStatsInterval = null;

        // System apps filter toggle
        this.hideSystemApps = true; // Default: hide system apps

        // Helper modules (initialized in loadStep3)
        this.canvasRenderer = null;
        this.elementPanel = null;
        this.interactions = null;
        this.stepManager = null;

        // Live streaming (Phase 1 enhancement)
        this.captureMode = 'polling'; // 'polling' or 'streaming'
        this.streamQuality = 'medium'; // 'high', 'medium', 'low', 'fast'
        this.liveStream = null;

        console.log('FlowWizard initialized');
        this.init();
    }

    init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setup());
        } else {
            this.setup();
        }
    }

    setup() {
        this.setupNavigation();
        Step1.loadStep(this); // Load first step immediately
        console.log('FlowWizard setup complete');
    }

    /**
     * Reset wizard to initial state
     */
    reset() {
        // Stop streaming if active
        this.stopStreaming();
        this.captureMode = 'polling';

        this.currentStep = 1;
        this.selectedDevice = null;
        this.selectedApp = null;
        this.recordMode = 'execute';
        this.recorder = null;
        this.flowSteps = [];
        this.updateUI();
        Step1.loadStep(this);
    }

    setupNavigation() {
        const btnBack = document.getElementById('btnBack');
        const btnNext = document.getElementById('btnNext');

        if (btnBack) {
            btnBack.addEventListener('click', () => this.previousStep());
        }

        if (btnNext) {
            btnNext.addEventListener('click', () => this.nextStep());
        }
    }

    async nextStep() {
        // Validate current step before proceeding
        if (!await this.validateCurrentStep()) {
            return;
        }

        if (this.currentStep < this.totalSteps) {
            this.currentStep++;
            this.updateUI();
            this.loadStepContent();
        } else {
            // Last step - save flow
            this.saveFlow();
        }
    }

    previousStep() {
        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateUI();
            this.loadStepContent();
        }
    }

    updateUI() {
        // Update progress indicator
        document.querySelectorAll('.wizard-progress .step').forEach((step, index) => {
            step.classList.remove('active', 'completed');
            const stepNum = index + 1;

            if (stepNum === this.currentStep) {
                step.classList.add('active');
            } else if (stepNum < this.currentStep) {
                step.classList.add('completed');
            }
        });

        // Show/hide step content
        document.querySelectorAll('.wizard-step').forEach((step, index) => {
            step.classList.toggle('active', index + 1 === this.currentStep);
        });

        // Update navigation buttons
        const btnBack = document.getElementById('btnBack');
        const btnNext = document.getElementById('btnNext');

        if (btnBack) {
            btnBack.disabled = this.currentStep === 1;
        }

        if (btnNext) {
            btnNext.textContent = this.currentStep === this.totalSteps ? 'Save Flow' : 'Next →';
        }
    }

    async validateCurrentStep() {
        switch(this.currentStep) {
            case 1:
                if (!this.selectedDevice) {
                    showToast('Please select a device', 'error');
                    return false;
                }
                return true;

            case 2:
                if (!this.selectedApp) {
                    showToast('Please select an app', 'error');
                    return false;
                }
                // Get selected recording mode
                const modeInput = document.querySelector('input[name="recordMode"]:checked');
                if (modeInput) {
                    this.recordMode = modeInput.value;
                }
                console.log('[FlowWizard] Validated step 2:', {
                    app: this.selectedApp,
                    mode: this.recordMode
                });
                return true;

            case 3:
                if (this.flowSteps.length === 0) {
                    showToast('Please record at least one step', 'error');
                    return false;
                }
                return true;

            case 4:
                // Review step - always valid
                return true;

            case 5:
                // Settings validation
                const flowName = document.getElementById('flowName')?.value;
                if (!flowName || flowName.trim() === '') {
                    showToast('Please enter a flow name', 'error');
                    return false;
                }
                return true;

            default:
                return true;
        }
    }

    loadStepContent() {
        // Stop streaming when leaving Step 3
        if (this.currentStep !== 3 && this.captureMode === 'streaming') {
            this.stopStreaming();
            this.captureMode = 'polling';
        }

        switch(this.currentStep) {
            case 1:
                Step1.loadStep(this);
                break;
            case 2:
                Step2.loadStep(this);
                break;
            case 3:
                this.loadStep3(); // Step 3 remains inline (complex recording UI)
                break;
            case 4:
                Step4.loadStep(this);
                break;
            case 5:
                Step5.loadStep(this);
                break;
        }
    }

    // NOTE: Steps 1, 2, 4, 5 moved to separate modules:
    // - flow-wizard-step1.js (device selection)
    // - flow-wizard-step2.js (app selection, icon detection, filtering)
    // - flow-wizard-step4.js (review & test)
    // - flow-wizard-step5.js (settings & save)

    async loadStep3() {
        console.log('Loading Step 3: Recording Mode');
        showToast(`Starting recording session...`, 'info');

        // Populate app info header
        this.populateAppInfo();

        // Get canvas and context for rendering
        this.canvas = document.getElementById('screenshotCanvas');
        this.ctx = this.canvas.getContext('2d');
        this.currentImage = null;

        // Initialize helper modules
        this.canvasRenderer = new FlowCanvasRenderer(this.canvas, this.ctx);
        this.canvasRenderer.setOverlayFilters(this.overlayFilters);

        this.elementPanel = new FlowElementPanel(document.getElementById('elementList'));
        this.elementPanel.setCallbacks({
            onTap: (el) => this.addTapStepFromElement(el),
            onType: (el) => this.addTypeStepFromElement(el),
            onSensor: (el, idx) => this.addSensorCaptureFromElement(el, idx)
        });

        this.interactions = new FlowInteractions(getApiBase());

        this.stepManager = new FlowStepManager(document.getElementById('flowStepsList'));

        // Initialize FlowRecorder (pass package name, not full object)
        const packageName = this.selectedApp?.package || this.selectedApp;
        this.recorder = new FlowRecorder(this.selectedDevice, packageName, this.recordMode);

        // Setup UI event listeners
        this.setupRecordingUI();

        // Start recording session
        const started = await this.recorder.start();

        if (started) {
            // Display initial screenshot
            await this.updateScreenshotDisplay();

            // Show preview overlay if quick screenshot was loaded
            if (this.recorder.screenshotMetadata?.quick) {
                this.showPreviewOverlay();
            }
        }
    }

    populateAppInfo() {
        console.log('[FlowWizard] populateAppInfo() called');
        console.log('[FlowWizard] this.selectedApp:', this.selectedApp);
        console.log('[FlowWizard] this.selectedDevice:', this.selectedDevice);

        const appInfoHeader = document.getElementById('appInfoHeader');
        const appIcon = document.getElementById('appIcon');
        const appName = document.getElementById('appName');
        const appPackage = document.getElementById('appPackage');

        console.log('[FlowWizard] DOM elements:', { appInfoHeader, appIcon, appName, appPackage });

        if (!appInfoHeader || !appIcon || !appName || !appPackage) {
            console.warn('[FlowWizard] App info elements not found in DOM');
            return;
        }

        // Get app data
        const packageName = this.selectedApp?.package || this.selectedApp;
        const label = this.selectedApp?.label || packageName;

        console.log('[FlowWizard] Extracted data:', { packageName, label });

        // Set app name and package
        appName.textContent = label;
        appPackage.textContent = packageName;

        // Fetch and set app icon
        const iconUrl = `${getApiBase()}/adb/app-icon/${encodeURIComponent(this.selectedDevice)}/${encodeURIComponent(packageName)}`;
        console.log('[FlowWizard] App icon URL:', iconUrl);

        appIcon.src = iconUrl;
        appIcon.onerror = () => {
            console.warn('[FlowWizard] App icon failed to load, using fallback');
            // Fallback to emoji if icon fails to load
            appIcon.style.display = 'none';
            appIcon.insertAdjacentHTML('afterend', '<div style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; font-size: 32px; background: var(--surface); border-radius: 8px; border: 1px solid var(--border);">📱</div>');
        };

        // Show the header
        appInfoHeader.style.display = 'flex';
        console.log('[FlowWizard] App info header display set to flex');

        console.log(`[FlowWizard] App info populated: ${label} (${packageName})`);
    }

    setupRecordingUI() {
        // Setup capture mode toggle (Polling/Streaming)
        this.setupCaptureMode();

        // Canvas click handler
        this.canvas.addEventListener('click', async (e) => {
            // Ignore clicks during pinch gestures
            if (this.canvasRenderer.isPinching) return;

            const rect = this.canvas.getBoundingClientRect();
            const canvasX = e.clientX - rect.left;
            const canvasY = e.clientY - rect.top;

            // Show element selection dialog
            await this.handleElementClick(canvasX, canvasY);
        });

        // Listen for zoom changes from gestures (pinch/wheel)
        this.canvas.addEventListener('zoomChanged', (e) => {
            this.updateZoomDisplay(e.detail.zoom);
        });

        // Sidebar collapse/expand buttons
        document.getElementById('btnCollapseSidebar')?.addEventListener('click', () => {
            this.collapseSidebar();
        });

        document.getElementById('btnExpandSidebar')?.addEventListener('click', () => {
            this.expandSidebar();
        });

        // Navigation controls
        document.getElementById('btnRefreshScreen')?.addEventListener('click', async () => {
            await this.recorder.refresh();
            this.updateScreenshotDisplay();
        });

        document.getElementById('btnStitchCapture')?.addEventListener('click', async () => {
            const btn = document.getElementById('btnStitchCapture');
            const originalText = btn.textContent;

            try {
                // Disable button and show feedback
                btn.disabled = true;
                btn.textContent = '⏳ Stitching...';
                showToast('Starting stitch capture... This may take 30-60 seconds', 'info', 3000);

                await this.recorder.stitchCapture();
                this.updateScreenshotDisplay();

                showToast('Stitch capture complete!', 'success', 2000);
            } catch (error) {
                showToast(`Stitch capture failed: ${error.message}`, 'error', 3000);
            } finally {
                // Re-enable button
                btn.disabled = false;
                btn.textContent = originalText;
            }
        });

        document.getElementById('btnGoBack')?.addEventListener('click', async () => {
            await this.recorder.goBack();
            this.updateScreenshotDisplay();
        });

        document.getElementById('btnGoHome')?.addEventListener('click', async () => {
            await this.recorder.goHome();
            this.updateScreenshotDisplay();
        });

        // Zoom controls
        document.getElementById('btnZoomIn')?.addEventListener('click', () => {
            this.zoomIn();
        });

        document.getElementById('btnZoomOut')?.addEventListener('click', () => {
            this.zoomOut();
        });

        document.getElementById('btnZoomReset')?.addEventListener('click', () => {
            this.resetZoom();
        });

        // Swipe controls
        document.querySelectorAll('[data-swipe]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const direction = btn.dataset.swipe;
                await this.recorder.swipe(direction);
                this.updateScreenshotDisplay();
            });
        });

        // Scale toggle button
        document.getElementById('btnToggleScale')?.addEventListener('click', () => {
            this.toggleScale();
        });

        // Done recording button
        document.getElementById('btnDoneRecording')?.addEventListener('click', () => {
            this.flowSteps = this.recorder.getSteps();
            console.log('Recording complete:', this.flowSteps);
            this.nextStep();
        });

        // Setup overlay filter controls
        this.setupOverlayFilters();
    }

    setupOverlayFilters() {
        const filterIds = {
            showClickable: 'filterClickable',
            showNonClickable: 'filterNonClickable',
            showTextLabels: 'filterTextLabels',
            hideSmall: 'filterMinSize',
            textOnly: 'filterTextOnly'
        };

        Object.entries(filterIds).forEach(([filterName, elementId]) => {
            const checkbox = document.getElementById(elementId);
            if (!checkbox) {
                console.warn(`[FlowWizard] Filter checkbox not found: ${elementId}`);
                return;
            }

            checkbox.addEventListener('change', () => {
                this.overlayFilters[filterName] = checkbox.checked;
                // Update canvas renderer filters
                if (this.canvasRenderer) {
                    this.canvasRenderer.setOverlayFilters(this.overlayFilters);
                }
                console.log(`[FlowWizard] ${filterName} = ${checkbox.checked}`);
                this.updateScreenshotDisplay();
            });

            // Set initial state
            checkbox.checked = this.overlayFilters[filterName];
        });

        console.log('[FlowWizard] Overlay filters initialized');
    }

    /**
     * Setup capture mode toggle (Polling vs Streaming)
     */
    setupCaptureMode() {
        const captureModeInputs = document.querySelectorAll('input[name="captureMode"]');
        const qualitySelect = document.getElementById('streamQuality');
        const statusEl = document.getElementById('streamStatus');

        if (!captureModeInputs.length) return;

        // Handle capture mode change
        captureModeInputs.forEach(input => {
            input.addEventListener('change', (e) => {
                const mode = e.target.value;
                this.setCaptureMode(mode);
            });
        });

        // Handle quality change
        if (qualitySelect) {
            qualitySelect.addEventListener('change', (e) => {
                this.streamQuality = e.target.value;
                // If streaming, restart with new quality
                if (this.captureMode === 'streaming' && this.liveStream?.isActive()) {
                    this.startStreaming();
                }
            });
        }

        console.log('[FlowWizard] Capture mode controls initialized');
    }

    /**
     * Set capture mode (polling or streaming)
     */
    setCaptureMode(mode) {
        const qualitySelect = document.getElementById('streamQuality');

        if (mode === 'streaming') {
            this.captureMode = 'streaming';
            if (qualitySelect) qualitySelect.disabled = false;
            this.startStreaming();
        } else {
            this.captureMode = 'polling';
            if (qualitySelect) qualitySelect.disabled = true;
            this.stopStreaming();
        }

        console.log(`[FlowWizard] Capture mode: ${mode}`);
    }

    /**
     * Start live streaming
     */
    startStreaming() {
        if (!this.selectedDevice) {
            showToast('No device selected', 'error');
            return;
        }

        // Stop any existing stream
        this.stopStreaming();

        // Initialize LiveStream if needed
        if (!this.liveStream) {
            this.liveStream = new LiveStream(this.canvas);

            // Wire up callbacks
            this.liveStream.onConnect = () => {
                this.updateStreamStatus('connected', 'Live');
                showToast('Streaming started', 'success', 2000);
            };

            this.liveStream.onDisconnect = () => {
                this.updateStreamStatus('disconnected', 'Offline');
            };

            this.liveStream.onConnectionStateChange = (state, attempts) => {
                switch (state) {
                    case 'connecting':
                        this.updateStreamStatus('connecting', 'Connecting...');
                        break;
                    case 'reconnecting':
                        this.updateStreamStatus('reconnecting', `Retry ${attempts}...`);
                        break;
                    case 'connected':
                        this.updateStreamStatus('connected', 'Live');
                        break;
                    case 'disconnected':
                        this.updateStreamStatus('disconnected', 'Offline');
                        break;
                }
            };

            this.liveStream.onError = (error) => {
                console.error('[FlowWizard] Stream error:', error);
            };

            // Apply current overlay settings
            this.liveStream.setOverlaysVisible(this.overlayFilters.showClickable || this.overlayFilters.showNonClickable);
            this.liveStream.setTextLabelsVisible(this.overlayFilters.showTextLabels);
        }

        // Start streaming with MJPEG mode for lower bandwidth
        this.liveStream.start(this.selectedDevice, 'mjpeg', this.streamQuality);
        this.updateStreamStatus('connecting', 'Connecting...');
    }

    /**
     * Stop live streaming
     */
    stopStreaming() {
        if (this.liveStream) {
            this.liveStream.stop();
        }
        this.updateStreamStatus('', '');
    }

    /**
     * Update stream status display
     */
    updateStreamStatus(className, text) {
        const statusEl = document.getElementById('streamStatus');
        if (statusEl) {
            statusEl.className = `stream-status ${className}`;
            statusEl.textContent = text;
        }
    }

    toggleScale() {
        this.scaleMode = this.canvasRenderer.toggleScale();

        const btn = document.getElementById('btnToggleScale');
        if (btn) {
            btn.textContent = this.scaleMode === 'fit' ? '📏 1:1 Scale' : '📏 Fit to Screen';
        }

        console.log(`[FlowWizard] Scale mode: ${this.scaleMode}`);
        this.updateScreenshotDisplay();
    }

    zoomIn() {
        const zoomLevel = this.canvasRenderer.zoomIn();
        this.updateZoomDisplay(zoomLevel);
        this.updateScreenshotDisplay();
    }

    zoomOut() {
        const zoomLevel = this.canvasRenderer.zoomOut();
        this.updateZoomDisplay(zoomLevel);
        this.updateScreenshotDisplay();
    }

    resetZoom() {
        const zoomLevel = this.canvasRenderer.resetZoom();
        this.updateZoomDisplay(zoomLevel);
        this.updateScreenshotDisplay();
    }

    updateZoomDisplay(zoomLevel) {
        const display = document.getElementById('zoomLevel');
        if (display) {
            display.textContent = `${Math.round(zoomLevel * 100)}%`;
        }
    }

    // Removed applyCanvasScale() - now using direct canvas resizing instead of CSS transform

    async handleElementClick(canvasX, canvasY) {
        // Convert canvas coordinates to device coordinates
        const deviceCoords = this.canvasRenderer.canvasToDevice(canvasX, canvasY);

        // Find clicked element from metadata
        const clickedElement = this.interactions.findElementAtCoordinates(
            this.recorder.screenshotMetadata?.elements,
            deviceCoords.x,
            deviceCoords.y
        );

        // Show selection dialog
        const choice = await this.interactions.showElementSelectionDialog(clickedElement, deviceCoords);

        if (!choice) {
            return; // User cancelled
        }

        // Execute based on choice
        switch (choice.type) {
            case 'tap':
                await this.executeTap(deviceCoords.x, deviceCoords.y, clickedElement);
                this.updateScreenshotDisplay();
                break;

            case 'type':
                const text = await this.interactions.promptForText();
                if (text) {
                    await this.executeTap(deviceCoords.x, deviceCoords.y, clickedElement);
                    await this.recorder.typeText(text);
                    this.updateScreenshotDisplay();
                }
                break;

            case 'sensor_text':
                await this.createTextSensor(clickedElement, deviceCoords);
                break;

            case 'sensor_image':
                await this.createImageSensor(clickedElement, deviceCoords);
                break;

            case 'action':
                await this.createAction(clickedElement, deviceCoords);
                break;

            case 'refresh':
                await this.handleRefreshWithRetries();
                break;
        }
    }

    /**
     * Convert canvas coordinates to device coordinates (adapted from screenshot-capture.js)
     */
    canvasToDevice(canvasX, canvasY) {
        if (!this.currentImage || !this.canvas.width) {
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
    async executeTap(x, y, element = null) {
        // Show tap indicator on canvas
        this.showTapIndicator(x, y);

        // Execute tap if in execute mode
        if (this.recordMode === 'execute') {
            await this.recorder.executeTap(x, y);
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

        this.recorder.addStep(step);

        // Capture new screenshot after tap
        if (this.recordMode === 'execute') {
            await this.recorder.wait(500); // Wait for UI to update
            await this.recorder.captureScreenshot();
        }
    }

    /**
     * Show visual tap indicator on canvas
     */
    showTapIndicator(x, y) {
        this.canvasRenderer.showTapIndicator(x, y);

        // Redraw screenshot after short delay to clear tap indicator
        setTimeout(() => {
            this.updateScreenshotDisplay();
        }, 300);
    }

    findElementAtCoordinates(x, y) {
        if (!this.recorder.screenshotMetadata?.elements) {
            return null;
        }

        // Find element that contains the coordinates
        const elements = this.recorder.screenshotMetadata.elements;

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

    async showElementSelectionDialog(element, coords) {
        return new Promise((resolve) => {
            // Create dialog overlay
            const overlay = document.createElement('div');
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
                animation: fadeIn 0.2s ease;
            `;

            const elementInfo = element ? `
                <div style="background: linear-gradient(135deg, #dbeafe 0%, #e0e7ff 100%); padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 2px solid #3b82f6;">
                    <div style="font-size: 14px; color: #1e40af; font-weight: 600; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 20px;">🎯</span>
                        Element Selected
                    </div>
                    ${element.text ? `<div style="margin-bottom: 6px;"><strong>Text:</strong> ${element.text}</div>` : ''}
                    ${element.class ? `<div style="margin-bottom: 6px; font-size: 12px;"><strong>Class:</strong> <code style="background: rgba(255,255,255,0.6); padding: 2px 6px; border-radius: 3px;">${element.class}</code></div>` : ''}
                    ${element.resource_id ? `<div style="margin-bottom: 6px; font-size: 12px;"><strong>Resource ID:</strong> <code style="background: rgba(255,255,255,0.6); padding: 2px 6px; border-radius: 3px;">${element.resource_id.split('/').pop() || element.resource_id}</code></div>` : ''}
                    ${element.content_desc ? `<div style="margin-bottom: 6px;"><strong>Description:</strong> ${element.content_desc}</div>` : ''}
                    <div style="margin-bottom: 6px; font-size: 12px;"><strong>Position:</strong> (${coords.x}, ${coords.y})</div>
                    ${element.clickable ? `<div style="color: #22c55e; font-weight: 600; margin-top: 8px;">✓ Clickable Element</div>` : '<div style="color: #64748b; margin-top: 8px;">○ Non-Clickable Element</div>'}
                    <div style="margin-top: 10px; padding: 8px; background: rgba(59, 130, 246, 0.1); border-radius: 4px; font-size: 11px; color: #1e40af;">
                        <strong>Note:</strong> Steps will reference this element, not just coordinates
                    </div>
                </div>
            ` : `
                <div style="background: #fef3c7; padding: 12px; border-radius: 6px; margin-bottom: 20px; border: 2px solid #f59e0b;">
                    <div style="color: #92400e; font-size: 13px;">
                        <strong>⚠️ No element detected</strong><br>
                        <span style="font-size: 12px;">Using coordinates only: (${coords.x}, ${coords.y})</span>
                    </div>
                </div>
            `;

            overlay.innerHTML = `
                <div style="background: white; border-radius: 12px; padding: 30px; max-width: 500px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); animation: slideIn 0.3s ease;">
                    <h2 style="margin: 0 0 15px 0; color: #0f172a;">What do you want to do?</h2>

                    ${elementInfo}

                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px;">
                        <button class="choice-btn" data-choice="tap" style="
                            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
                            color: white;
                            border: none;
                            padding: 16px;
                            border-radius: 8px;
                            cursor: pointer;
                            font-size: 15px;
                            font-weight: 600;
                            transition: all 0.2s ease;
                            box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
                        ">
                            <div style="font-size: 24px; margin-bottom: 4px;">👆</div>
                            Tap Element
                        </button>

                        <button class="choice-btn" data-choice="type" style="
                            background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
                            color: white;
                            border: none;
                            padding: 16px;
                            border-radius: 8px;
                            cursor: pointer;
                            font-size: 15px;
                            font-weight: 600;
                            transition: all 0.2s ease;
                            box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
                        ">
                            <div style="font-size: 24px; margin-bottom: 4px;">⌨️</div>
                            Type Text
                        </button>

                        <button class="choice-btn" data-choice="sensor_text" style="
                            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                            color: white;
                            border: none;
                            padding: 16px;
                            border-radius: 8px;
                            cursor: pointer;
                            font-size: 15px;
                            font-weight: 600;
                            transition: all 0.2s ease;
                            box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
                        ">
                            <div style="font-size: 24px; margin-bottom: 4px;">📊</div>
                            Capture Text
                        </button>

                        <button class="choice-btn" data-choice="sensor_image" style="
                            background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
                            color: white;
                            border: none;
                            padding: 16px;
                            border-radius: 8px;
                            cursor: pointer;
                            font-size: 15px;
                            font-weight: 600;
                            transition: all 0.2s ease;
                            box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3);
                        ">
                            <div style="font-size: 24px; margin-bottom: 4px;">📸</div>
                            Capture Image
                        </button>

                        <button class="choice-btn" data-choice="refresh" style="
                            background: linear-gradient(135deg, #64748b 0%, #475569 100%);
                            color: white;
                            border: none;
                            padding: 16px;
                            border-radius: 8px;
                            cursor: pointer;
                            font-size: 15px;
                            font-weight: 600;
                            transition: all 0.2s ease;
                            box-shadow: 0 2px 8px rgba(100, 116, 139, 0.3);
                        ">
                            <div style="font-size: 24px; margin-bottom: 4px;">⏱️</div>
                            Wait for Update
                        </button>
                    </div>

                    <button id="btnCancelChoice" style="
                        width: 100%;
                        background: transparent;
                        color: #64748b;
                        border: 2px solid #e2e8f0;
                        padding: 12px;
                        border-radius: 8px;
                        cursor: pointer;
                        font-size: 14px;
                        font-weight: 600;
                        transition: all 0.2s ease;
                    ">
                        Cancel
                    </button>
                </div>
            `;

            document.body.appendChild(overlay);

            // Add hover effects
            const style = document.createElement('style');
            style.textContent = `
                .choice-btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2) !important;
                }
                @keyframes fadeIn {
                    from { opacity: 0; }
                    to { opacity: 1; }
                }
                @keyframes slideIn {
                    from { transform: scale(0.9); opacity: 0; }
                    to { transform: scale(1); opacity: 1; }
                }
            `;
            document.head.appendChild(style);

            // Handle button clicks
            overlay.querySelectorAll('.choice-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const choice = { type: btn.dataset.choice };
                    document.body.removeChild(overlay);
                    document.head.removeChild(style);
                    resolve(choice);
                });
            });

            document.getElementById('btnCancelChoice').addEventListener('click', () => {
                document.body.removeChild(overlay);
                document.head.removeChild(style);
                resolve(null);
            });

            // Close on overlay click
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    document.body.removeChild(overlay);
                    document.head.removeChild(style);
                    resolve(null);
                }
            });
        });
    }

    async promptForText() {
        const text = prompt('Enter text to type:');
        return text && text.trim() !== '' ? text.trim() : null;
    }

    async createTextSensor(element, coords) {
        const result = await this.interactions.createTextSensor(
            element,
            coords,
            this.selectedDevice,
            this.selectedApp
        );

        if (result && result.step) {
            this.recorder.addStep(result.step);
        }
    }

    async createImageSensor(element, coords) {
        const result = await this.interactions.createImageSensor(
            element,
            coords,
            this.selectedDevice,
            this.selectedApp
        );

        if (result && result.step) {
            this.recorder.addStep(result.step);
        }
    }

    /**
     * Show action configuration dialog
     * Returns config object or null if cancelled
     */
    async promptForActionConfig(defaultName, stepCount) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.id = 'action-config-overlay';
            overlay.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0, 0, 0, 0.7); z-index: 10000;
                display: flex; align-items: center; justify-content: center;
            `;

            const dialog = document.createElement('div');
            dialog.style.cssText = `
                background: white; border-radius: 12px; padding: 24px;
                max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            `;

            dialog.innerHTML = `
                <h3 style="margin-top: 0;">Configure Action</h3>
                <p style="color: #666; margin-bottom: 20px;">Creating action with ${stepCount} step${stepCount !== 1 ? 's' : ''}</p>

                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 4px; font-weight: 600;">Action Name:</label>
                    <input type="text" id="actionName" value="${defaultName}"
                           style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                </div>

                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 4px; font-weight: 600;">Description (optional):</label>
                    <textarea id="actionDescription" rows="2" placeholder="What does this action do?"
                              style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;"></textarea>
                </div>

                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 4px;">
                        <input type="checkbox" id="stopOnError">
                        Stop if any step fails
                    </label>
                    <p style="color: #666; font-size: 13px; margin: 4px 0 0 24px;">
                        If checked, the action will stop executing when a step encounters an error.
                    </p>
                </div>

                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 4px; font-weight: 600;">Tags (optional):</label>
                    <input type="text" id="actionTags" placeholder="e.g., automation, setup, navigation"
                           style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                    <p style="color: #666; font-size: 13px; margin: 4px 0 0 0;">
                        Comma-separated tags for organizing actions
                    </p>
                </div>

                <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 24px;">
                    <button id="cancelBtn" style="padding: 10px 20px; border: 1px solid #ccc; background: white; border-radius: 4px; cursor: pointer;">
                        Cancel
                    </button>
                    <button id="defaultsBtn" style="padding: 10px 20px; border: none; background: #6b7280; color: white; border-radius: 4px; cursor: pointer;">
                        Use Defaults
                    </button>
                    <button id="createBtn" style="padding: 10px 20px; border: none; background: #ec4899; color: white; border-radius: 4px; cursor: pointer;">
                        Create Action
                    </button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            // Handle button clicks
            dialog.querySelector('#cancelBtn').addEventListener('click', () => {
                document.body.removeChild(overlay);
                resolve(null);
            });

            dialog.querySelector('#defaultsBtn').addEventListener('click', () => {
                const name = dialog.querySelector('#actionName').value.trim();
                if (!name) {
                    alert('Please enter an action name');
                    return;
                }
                document.body.removeChild(overlay);
                resolve({
                    name,
                    description: null,
                    stopOnError: false,
                    tags: []
                });
            });

            dialog.querySelector('#createBtn').addEventListener('click', () => {
                const name = dialog.querySelector('#actionName').value.trim();
                if (!name) {
                    alert('Please enter an action name');
                    return;
                }

                const description = dialog.querySelector('#actionDescription').value.trim() || null;
                const stopOnError = dialog.querySelector('#stopOnError').checked;
                const tagsInput = dialog.querySelector('#actionTags').value.trim();
                const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];

                document.body.removeChild(overlay);
                resolve({
                    name,
                    description,
                    stopOnError,
                    tags
                });
            });
        });
    }

    async createAction(element, coords) {
        try {
            // Get all recorded steps up to this point
            const steps = this.recorder.getSteps();

            if (steps.length === 0) {
                showToast('No steps recorded yet. Record some steps first!', 'warning', 3000);
                return;
            }

            // Show configuration dialog
            const config = await this.promptForActionConfig(element?.text || 'Custom Action', steps.length);
            if (!config) return;

            // Create action via API (using correct ActionCreateRequest structure)
            const response = await fetch(`/api/actions?device_id=${encodeURIComponent(this.selectedDevice)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action: {
                        action_type: 'macro',
                        name: config.name,
                        description: config.description,
                        device_id: this.selectedDevice,
                        enabled: true,
                        actions: steps,
                        stop_on_error: config.stopOnError
                    },
                    tags: config.tags
                })
            });

            if (!response.ok) {
                const error = await response.json();

                // Handle 422 validation errors (array of error objects)
                if (response.status === 422 && Array.isArray(error.detail)) {
                    const errorMessages = error.detail.map(e =>
                        `${e.loc.join('.')}: ${e.msg}`
                    ).join('; ');
                    throw new Error(errorMessages || 'Validation failed');
                }

                throw new Error(error.detail || 'Failed to create action');
            }

            const result = await response.json();
            showToast(`Action "${config.name}" created successfully! (ID: ${result.action.id})`, 'success', 5000);

            console.log('[FlowWizard] Created action:', result.action);
        } catch (error) {
            console.error('[FlowWizard] Failed to create action:', error);
            showToast(`Failed to create action: ${error.message}`, 'error', 5000);
        }
    }

    async promptForSensorName(defaultName) {
        const name = prompt(`Enter sensor name:`, defaultName);
        return name && name.trim() !== '' ? name.trim() : null;
    }

    async handleRefreshWithRetries() {
        // Prompt for refresh configuration
        const config = await this.interactions.promptForRefreshConfig();
        if (!config) return;

        const { attempts, delay } = config;

        console.log(`[FlowWizard] Refreshing ${attempts} times with ${delay}ms delay`);

        // Perform multiple refreshes
        for (let i = 0; i < attempts; i++) {
            showToast(`Refresh ${i + 1}/${attempts}...`, 'info', 1000);
            await this.recorder.refresh(false); // Don't add step yet
            this.updateScreenshotDisplay();

            // Wait between attempts (except after the last one)
            if (i < attempts - 1) {
                await this.recorder.wait(delay);
            }
        }

        // Add a single wait step representing the total refresh operation
        const totalDuration = (attempts - 1) * delay + 500; // 500ms for screenshot capture
        this.recorder.addStep({
            step_type: 'wait',
            duration: totalDuration,
            refresh_attempts: attempts,
            refresh_delay: delay,
            description: `Wait for UI update (${attempts} refreshes, ${delay}ms delay)`
        });

        showToast(`Completed ${attempts} refresh attempts`, 'success', 2000);
    }

    async updateScreenshotDisplay() {
        const dataUrl = this.recorder.getScreenshotDataUrl();
        const metadata = this.recorder.screenshotMetadata;
        const loading = document.getElementById('screenshotLoading');

        try {
            // Render using canvas renderer module
            const { displayWidth, displayHeight, scale } = await this.canvasRenderer.render(dataUrl, metadata);

            // Store scale for coordinate mapping
            this.currentScale = scale;

            // Update element panel if metadata available
            if (metadata && metadata.elements && metadata.elements.length > 0) {
                this.elementPanel.updateElements(metadata.elements);
            }

            // Hide loading
            if (loading) loading.style.display = 'none';

        } catch (error) {
            console.error('[FlowWizard] Failed to render screenshot:', error);
            if (loading) {
                loading.textContent = 'Error loading screenshot';
                loading.style.display = 'block';
            }
        }
    }

    /**
     * Show preview overlay with screenshot method selection
     */
    showPreviewOverlay() {
        // Remove existing overlay if any
        this.hidePreviewOverlay();

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
        regularBtn.onclick = () => this.chooseRegularScreenshot();

        const stitchBtn = document.createElement('button');
        stitchBtn.textContent = '🧩 Stitch Capture';
        stitchBtn.className = 'btn btn-secondary';
        stitchBtn.style.cssText = 'padding: 12px 24px; font-size: 14px;';
        stitchBtn.onclick = () => this.chooseStitchCapture();

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
    hidePreviewOverlay() {
        const overlay = document.getElementById('previewOverlay');
        if (overlay) {
            overlay.remove();
            console.log('[FlowWizard] Preview overlay hidden');
        }
    }

    /**
     * User chose regular screenshot - capture with UI elements
     */
    async chooseRegularScreenshot() {
        this.hidePreviewOverlay();

        try {
            await this.recorder.captureScreenshot();
            await this.updateScreenshotDisplay();
            showToast(`Full screenshot captured! (${this.recorder.screenshotMetadata?.elements?.length || 0} UI elements)`, 'success', 3000);
        } catch (error) {
            console.error('[FlowWizard] Regular screenshot failed:', error);
            showToast(`Screenshot failed: ${error.message}`, 'error', 3000);
        }
    }

    /**
     * User chose stitch capture - capture stitched screenshot
     */
    async chooseStitchCapture() {
        this.hidePreviewOverlay();

        try {
            await this.recorder.stitchCapture();
            await this.updateScreenshotDisplay();
        } catch (error) {
            console.error('[FlowWizard] Stitch capture failed:', error);
            // Error already handled by stitchCapture()
        }
    }

    /**
     * Collapse the element sidebar
     */
    collapseSidebar() {
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
    expandSidebar() {
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

    /**
     * Update element panel with current elements
     */
    updateElementPanel(elements) {
        const panel = document.getElementById('elementList');
        if (!panel) {
            console.warn('[FlowWizard] Element list container not found');
            return;
        }

        // Store all elements for filtering
        this.allElements = elements || [];

        // Setup search and filter event listeners (once)
        if (!this.elementFiltersInitialized) {
            this.setupElementFilters();
            this.elementFiltersInitialized = true;
        }

        // Apply filters and render
        this.renderFilteredElements();
    }

    setupElementFilters() {
        const searchInput = document.getElementById('elementSearchInput');
        const clickableFilter = document.getElementById('filterSidebarClickable');
        const textFilter = document.getElementById('filterSidebarText');

        if (searchInput) {
            searchInput.addEventListener('input', () => this.renderFilteredElements());
        }
        if (clickableFilter) {
            clickableFilter.addEventListener('change', () => this.renderFilteredElements());
        }
        if (textFilter) {
            textFilter.addEventListener('change', () => this.renderFilteredElements());
        }
    }

    renderFilteredElements() {
        const panel = document.getElementById('elementList');
        if (!panel) return;

        const searchInput = document.getElementById('elementSearchInput');
        const clickableFilter = document.getElementById('filterSidebarClickable');
        const textFilter = document.getElementById('filterSidebarText');

        const searchTerm = searchInput?.value.toLowerCase() || '';
        const showClickable = clickableFilter?.checked !== false;
        const showWithText = textFilter?.checked !== false;

        if (!this.allElements || this.allElements.length === 0) {
            panel.innerHTML = '<div class="empty-state">No elements detected in screenshot</div>';
            return;
        }

        // Apply filters (OR logic: show if matches ANY checked filter)
        let filteredElements = this.allElements.filter(el => {
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

        console.log(`[FlowWizard] Rendering ${interactiveElements.length} interactive elements (${this.allElements.length} total)`);

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
                    </div>
                </div>
            `;
        }).join('');

        // Bind action buttons
        panel.querySelectorAll('.btn-tap').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                this.addTapStepFromElement(interactiveElements[index]);
            });
        });

        panel.querySelectorAll('.btn-type').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                this.addTypeStepFromElement(interactiveElements[index]);
            });
        });

        panel.querySelectorAll('.btn-sensor').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                this.addSensorCaptureFromElement(interactiveElements[index], index);
            });
        });
    }

    /**
     * Add tap step from element (via panel)
     */
    async addTapStepFromElement(element) {
        const bounds = element.bounds || {};
        const x = Math.round((bounds.x || 0) + (bounds.width || 0) / 2);
        const y = Math.round((bounds.y || 0) + (bounds.height || 0) / 2);

        await this.executeTap(x, y, element);
        showToast(`Added tap step for "${element.text || 'element'}"`, 'success');
    }

    /**
     * Add type step from element (via panel)
     */
    async addTypeStepFromElement(element) {
        const bounds = element.bounds || {};
        const x = Math.round((bounds.x || 0) + (bounds.width || 0) / 2);
        const y = Math.round((bounds.y || 0) + (bounds.height || 0) / 2);

        const text = await this.promptForText();
        if (text) {
            await this.executeTap(x, y, element);
            await this.recorder.typeText(text);
            showToast(`Added type step: "${text}"`, 'success');
        }
    }

    /**
     * Add sensor capture from element (via panel)
     */
    async addSensorCaptureFromElement(element, elementIndex) {
        const bounds = element.bounds || {};
        const coords = {
            x: Math.round((bounds.x || 0) + (bounds.width || 0) / 2),
            y: Math.round((bounds.y || 0) + (bounds.height || 0) / 2)
        };

        // Show sensor configuration dialog
        await this.createTextSensor(element, coords);
    }

    /**
     * Draw UI element overlays on canvas (adapted from screenshot-capture.js)
     */
    drawElementOverlays() {
        if (!this.currentImage || !this.recorder.screenshotMetadata) {
            console.warn('[FlowWizard] Cannot draw overlays: no screenshot loaded');
            return;
        }

        // Redraw the screenshot image first (to clear old overlays)
        this.ctx.drawImage(this.currentImage, 0, 0);

        const elements = this.recorder.screenshotMetadata.elements || [];

        // Count elements by type
        const clickableElements = elements.filter(e => e.clickable === true);
        const nonClickableElements = elements.filter(e => e.clickable === false || e.clickable === undefined);

        console.log(`[FlowWizard] Drawing ${elements.length} elements (${clickableElements.length} clickable, ${nonClickableElements.length} non-clickable)`);
        console.log('[FlowWizard] Overlay filters:', this.overlayFilters);

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
            if (el.clickable && !this.overlayFilters.showClickable) {
                filteredClickable++;
                return;
            }
            if (!el.clickable && !this.overlayFilters.showNonClickable) {
                filteredNonClickable++;
                return;
            }

            // Filter by size (hide small elements < 50px width or height)
            if (this.overlayFilters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) {
                if (el.clickable) filteredClickable++; else filteredNonClickable++;
                return;
            }

            // Filter: text elements only
            if (this.overlayFilters.textOnly && (!el.text || !el.text.trim())) {
                if (el.clickable) filteredClickable++; else filteredNonClickable++;
                return;
            }

            // Get coordinates (no scaling - 1:1)
            const x = el.bounds.x;
            const y = el.bounds.y;
            const w = el.bounds.width;
            const h = el.bounds.height;

            // Skip elements outside canvas
            if (x + w < 0 || x > this.canvas.width || y + h < 0 || y > this.canvas.height) {
                return;
            }

            // Draw bounding box
            // Green for clickable, blue for non-clickable (matching flow-wizard colors)
            this.ctx.strokeStyle = el.clickable ? '#22c55e' : '#3b82f6';
            this.ctx.fillStyle = el.clickable ? 'rgba(34, 197, 94, 0.1)' : 'rgba(59, 130, 246, 0.1)';
            this.ctx.lineWidth = 2;

            // Fill background
            this.ctx.fillRect(x, y, w, h);

            // Draw border
            this.ctx.strokeRect(x, y, w, h);
            drawnCount++;
            if (el.clickable) drawnClickable++; else drawnNonClickable++;

            // Draw text label if element has text (and labels are enabled)
            if (this.overlayFilters.showTextLabels && el.text && el.text.trim()) {
                this.drawTextLabel(el.text, x, y, w, el.clickable);
            }
        });

        console.log(`[FlowWizard] Total visible: ${visibleCount}`);
        console.log(`[FlowWizard] Filtered: ${filteredClickable + filteredNonClickable} (${filteredClickable} clickable, ${filteredNonClickable} non-clickable)`);
        console.log(`[FlowWizard] Drawn: ${drawnCount} (${drawnClickable} clickable, ${drawnNonClickable} non-clickable)`);
    }

    /**
     * Draw UI element overlays with scaling
     */
    drawElementOverlaysScaled(scale) {
        if (!this.currentImage || !this.recorder.screenshotMetadata) {
            console.warn('[FlowWizard] Cannot draw overlays: no screenshot loaded');
            return;
        }

        const elements = this.recorder.screenshotMetadata.elements || [];

        elements.forEach(el => {
            if (!el.bounds) return;

            // Apply overlay filters
            if (el.clickable && !this.overlayFilters.showClickable) return;
            if (!el.clickable && !this.overlayFilters.showNonClickable) return;
            if (this.overlayFilters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) return;
            if (this.overlayFilters.textOnly && (!el.text || !el.text.trim())) return;

            // Scale coordinates
            const x = Math.floor(el.bounds.x * scale);
            const y = Math.floor(el.bounds.y * scale);
            const w = Math.floor(el.bounds.width * scale);
            const h = Math.floor(el.bounds.height * scale);

            // Skip elements outside canvas
            if (x + w < 0 || x > this.canvas.width || y + h < 0 || y > this.canvas.height) return;

            // Draw bounding box
            this.ctx.strokeStyle = el.clickable ? '#22c55e' : '#3b82f6';
            this.ctx.lineWidth = 2;
            this.ctx.strokeRect(x, y, w, h);

            // Draw text label if element has text and showTextLabels is enabled
            if (el.text && el.text.trim() && this.overlayFilters.showTextLabels) {
                this.drawTextLabel(el.text.trim(), x, y, w, el.clickable);
            }
        });
    }

    /**
     * Draw text label for UI element on canvas (adapted from screenshot-capture.js)
     */
    drawTextLabel(text, x, y, w, isClickable) {
        const labelHeight = 20;
        const padding = 2;

        // Truncate long text
        const maxChars = Math.floor(w / 7); // Approximate chars that fit
        const displayText = text.length > maxChars
            ? text.substring(0, maxChars - 3) + '...'
            : text;

        // Draw background (matching element color)
        this.ctx.fillStyle = isClickable ? '#22c55e' : '#3b82f6';
        this.ctx.fillRect(x, y, w, labelHeight);

        // Draw text
        this.ctx.fillStyle = '#ffffff';
        this.ctx.font = '12px monospace';
        this.ctx.textBaseline = 'top';
        this.ctx.fillText(displayText, x + padding, y + padding);
    }

    setupFlowStepsListener() {
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
        });
    }

    // NOTE: loadStep4() moved to flow-wizard-step4.js
    // NOTE: formatStepType, generateStepDescription, renderStepDetails are in flow-step-manager.js

    removeStepAt(index) {
        if (index >= 0 && index < this.flowSteps.length) {
            const removed = this.flowSteps.splice(index, 1)[0];
            console.log(`Removed step ${index}:`, removed);
            showToast(`Step ${index + 1} removed`, 'info');
            Step4.loadStep(this); // Refresh the review display
        }
    }

    async testFlow() {
        console.log('Testing flow...');
        showToast('Running flow test...', 'info');

        const testResults = document.getElementById('testResults');
        const testResultsContent = document.getElementById('testResultsContent');

        testResults.style.display = 'block';
        testResultsContent.innerHTML = '<div class="loading">Executing flow...</div>';

        try {
            // Build flow payload
            const flowPayload = {
                flow_id: `test_${Date.now()}`,
                device_id: this.selectedDevice,
                name: 'Test Flow',
                description: 'Flow test execution',
                steps: this.flowSteps,
                update_interval_seconds: 60,
                enabled: false, // Don't enable test flows
                stop_on_error: true
            };

            console.log('Testing flow:', flowPayload);

            const response = await fetch(`${getApiBase()}/flows`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(flowPayload)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to create test flow');
            }

            const createdFlow = await response.json();
            console.log('Test flow created:', createdFlow);

            // Execute the flow
            const executeResponse = await fetch(`${getApiBase()}/flows/${this.selectedDevice}/${createdFlow.flow_id}/execute`, {
                method: 'POST'
            });

            if (!executeResponse.ok) {
                const error = await executeResponse.json();
                throw new Error(error.detail || 'Flow execution failed');
            }

            const result = await executeResponse.json();
            console.log('Flow execution result:', result);

            // Display results
            if (result.success) {
                testResultsContent.innerHTML = `
                    <div class="test-success">
                        <h4>✅ Flow Test Passed</h4>
                        <p><strong>Executed Steps:</strong> ${result.executed_steps} / ${this.flowSteps.length}</p>
                        <p><strong>Execution Time:</strong> ${result.execution_time_ms}ms</p>
                        ${Object.keys(result.captured_sensors || {}).length > 0 ? `
                            <div class="captured-sensors">
                                <strong>Captured Sensors:</strong>
                                <ul>
                                    ${Object.entries(result.captured_sensors).map(([id, value]) =>
                                        `<li>${id}: ${value}</li>`
                                    ).join('')}
                                </ul>
                            </div>
                        ` : ''}
                    </div>
                `;
                showToast('Flow test passed!', 'success');
            } else {
                testResultsContent.innerHTML = `
                    <div class="test-failure">
                        <h4>❌ Flow Test Failed</h4>
                        <p><strong>Failed at Step:</strong> ${result.failed_step !== null ? result.failed_step + 1 : 'Unknown'}</p>
                        <p><strong>Error:</strong> ${result.error_message || 'Unknown error'}</p>
                        <p><strong>Executed Steps:</strong> ${result.executed_steps} / ${this.flowSteps.length}</p>
                    </div>
                `;
                showToast('Flow test failed', 'error');
            }

            // Clean up test flow
            await fetch(`${getApiBase()}/flows/${this.selectedDevice}/${createdFlow.flow_id}`, {
                method: 'DELETE'
            });

        } catch (error) {
            console.error('Flow test error:', error);
            testResultsContent.innerHTML = `
                <div class="test-error">
                    <h4>⚠️ Test Error</h4>
                    <p>${error.message}</p>
                </div>
            `;
            showToast(`Test error: ${error.message}`, 'error');
        }
    }

    // NOTE: loadStep5() moved to flow-wizard-step5.js

    async saveFlow() {
        console.log('Saving flow...');
        showToast('Saving flow...', 'info');

        try {
            // Get form values
            const flowName = document.getElementById('flowName')?.value.trim();
            const flowDescription = document.getElementById('flowDescription')?.value.trim();
            const intervalValue = parseInt(document.getElementById('intervalValue')?.value || '60');
            const intervalUnit = parseInt(document.getElementById('intervalUnit')?.value || '60');

            // Calculate total interval in seconds
            const updateIntervalSeconds = intervalValue * intervalUnit;

            // Generate unique flow ID
            const flowId = `flow_${this.selectedDevice.replace(/[^a-zA-Z0-9]/g, '_')}_${Date.now()}`;

            // Build flow payload
            const flowPayload = {
                flow_id: flowId,
                device_id: this.selectedDevice,
                name: flowName,
                description: flowDescription || '',
                steps: this.flowSteps,
                update_interval_seconds: updateIntervalSeconds,
                enabled: true, // Enable by default
                stop_on_error: false,
                max_flow_retries: 3,
                flow_timeout: 60
            };

            console.log('Saving flow:', flowPayload);

            // Save flow via API
            const response = await fetch(`${getApiBase()}/flows`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(flowPayload)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to save flow');
            }

            const savedFlow = await response.json();
            console.log('Flow saved successfully:', savedFlow);

            showToast('Flow saved successfully!', 'success', 3000);

            // Show success message with option to view flows or create another
            const result = await this.showFlowSavedDialog(savedFlow);

            if (result === 'view') {
                window.location.href = 'flows.html';
            } else if (result === 'create') {
                // Reset wizard
                this.reset();
            }

        } catch (error) {
            console.error('Failed to save flow:', error);
            showToast(`Failed to save flow: ${error.message}`, 'error', 5000);
        }
    }

    async showFlowSavedDialog(flow) {
        return new Promise((resolve) => {
            // Create modal overlay
            const overlay = document.createElement('div');
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
            `;

            overlay.innerHTML = `
                <div style="background: white; border-radius: 8px; padding: 30px; max-width: 500px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                    <h2 style="margin: 0 0 15px 0; color: #22c55e;">✅ Flow Saved!</h2>
                    <p style="margin: 0 0 20px 0; color: #64748b;">
                        <strong>${flow.name}</strong> has been saved and enabled.
                    </p>
                    <div style="margin: 0 0 20px 0; padding: 15px; background: #f1f5f9; border-radius: 4px;">
                        <div style="margin-bottom: 8px;">
                            <strong>Device:</strong> ${flow.device_id}
                        </div>
                        <div style="margin-bottom: 8px;">
                            <strong>Steps:</strong> ${flow.steps.length}
                        </div>
                        <div>
                            <strong>Update Interval:</strong> ${this.formatInterval(flow.update_interval_seconds)}
                        </div>
                    </div>
                    <p style="margin: 0 0 20px 0; font-size: 14px; color: #64748b;">
                        The flow will run automatically every ${this.formatInterval(flow.update_interval_seconds)}.
                    </p>
                    <div style="display: flex; gap: 10px; justify-content: flex-end;">
                        <button id="btnCreateAnother" class="btn btn-secondary">
                            Create Another Flow
                        </button>
                        <button id="btnViewFlows" class="btn btn-primary">
                            View All Flows
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            // Handle button clicks
            document.getElementById('btnCreateAnother').onclick = () => {
                document.body.removeChild(overlay);
                resolve('create');
            };

            document.getElementById('btnViewFlows').onclick = () => {
                document.body.removeChild(overlay);
                resolve('view');
            };

            // Close on overlay click
            overlay.onclick = (e) => {
                if (e.target === overlay) {
                    document.body.removeChild(overlay);
                    resolve('view');
                }
            };
        });
    }

    formatInterval(seconds) {
        if (seconds < 60) {
            return `${seconds} seconds`;
        } else if (seconds < 3600) {
            const minutes = Math.floor(seconds / 60);
            return `${minutes} minute${minutes > 1 ? 's' : ''}`;
        } else {
            const hours = Math.floor(seconds / 3600);
            return `${hours} hour${hours > 1 ? 's' : ''}`;
        }
    }
}

// Initialize wizard when module loads
const wizard = new FlowWizard();

// Export for debugging
window.flowWizard = wizard;

export default FlowWizard;
