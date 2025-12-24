/**
 * Flow Wizard Module
 * Visual Mapper v0.0.5
 *
 * Interactive wizard for creating flows with recording mode
 */

import { showToast } from './toast.js?v=0.0.14';
import FlowRecorder from './flow-recorder.js?v=0.0.14';

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
        this.loadStep1(); // Load first step immediately
        console.log('FlowWizard setup complete');
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
        switch(this.currentStep) {
            case 1:
                this.loadStep1();
                break;
            case 2:
                this.loadStep2();
                break;
            case 3:
                this.loadStep3();
                break;
            case 4:
                this.loadStep4();
                break;
            case 5:
                this.loadStep5();
                break;
        }
    }

    async loadStep1() {
        console.log('Loading Step 1: Device Selection');
        const deviceList = document.getElementById('deviceList');

        try {
            const response = await fetch('/api/adb/devices');
            if (!response.ok) throw new Error('Failed to fetch devices');

            const data = await response.json();
            const devices = data.devices || [];
            console.log('Devices loaded:', devices);

            if (devices.length === 0) {
                deviceList.innerHTML = `
                    <div class="empty-state">
                        <p>No devices connected</p>
                        <p><a href="devices.html" class="btn btn-primary">Connect a Device</a></p>
                    </div>
                `;
                return;
            }

            // Render device grid
            deviceList.className = 'device-grid';
            deviceList.innerHTML = devices.map(device => `
                <div class="device-card" data-device="${device.id}">
                    <div class="device-icon">📱</div>
                    <div class="device-name">${device.model || device.id}</div>
                    <div class="device-status">
                        <span class="status-dot" style="background: ${device.state === 'device' ? '#22c55e' : '#ef4444'}"></span>
                        ${device.state}
                    </div>
                </div>
            `).join('');

            // Add "Add New Device" card
            deviceList.insertAdjacentHTML('beforeend', `
                <div class="device-card" onclick="window.location.href='devices.html'">
                    <div class="device-icon">➕</div>
                    <div class="device-name">Add Device</div>
                    <div class="device-status">Connect new</div>
                </div>
            `);

            // Handle device selection
            deviceList.querySelectorAll('.device-card[data-device]').forEach(card => {
                card.addEventListener('click', () => {
                    deviceList.querySelectorAll('.device-card').forEach(c => c.classList.remove('selected'));
                    card.classList.add('selected');
                    this.selectedDevice = card.dataset.device;
                    console.log('Device selected:', this.selectedDevice);
                });
            });

        } catch (error) {
            console.error('Error loading devices:', error);
            deviceList.innerHTML = `
                <div class="error-state">
                    <p>Error loading devices: ${error.message}</p>
                    <button class="btn btn-secondary" onclick="location.reload()">Retry</button>
                </div>
            `;
        }
    }

    async loadStep2() {
        console.log('Loading Step 2: App Selection');
        const appList = document.getElementById('appList');

        if (!this.selectedDevice) {
            showToast('No device selected', 'error');
            this.currentStep = 1;
            this.updateUI();
            return;
        }

        try {
            const response = await fetch(`/api/adb/apps/${this.selectedDevice}`);
            if (!response.ok) throw new Error('Failed to fetch apps');

            const data = await response.json();
            const apps = data.apps || [];
            console.log('Apps loaded:', apps.length);

            if (apps.length === 0) {
                appList.innerHTML = `<div class="empty-state">No apps found on device</div>`;
                return;
            }

            // Sort apps alphabetically by label
            apps.sort((a, b) => {
                const labelA = (a.label || a.package).toLowerCase();
                const labelB = (b.label || b.package).toLowerCase();
                return labelA.localeCompare(labelB);
            });

            // Render app grid
            appList.className = 'app-grid';
            appList.innerHTML = apps.map(app => `
                <div class="app-item" data-package="${app.package}" data-label="${app.label || app.package}">
                    <div class="app-icon">📱</div>
                    <div class="app-label">${app.label || app.package}</div>
                    <div class="app-package">${app.package}</div>
                </div>
            `).join('');

            // Setup search (searches both label and package name)
            const searchInput = document.getElementById('appSearch');
            if (searchInput) {
                searchInput.addEventListener('input', (e) => {
                    const search = e.target.value.toLowerCase();
                    document.querySelectorAll('.app-item').forEach(item => {
                        const label = item.dataset.label.toLowerCase();
                        const pkg = item.dataset.package.toLowerCase();
                        const matches = label.includes(search) || pkg.includes(search);
                        item.style.display = matches ? '' : 'none';
                    });
                });
            }

            // Handle app selection
            document.querySelectorAll('.app-item').forEach(item => {
                item.addEventListener('click', () => {
                    document.querySelectorAll('.app-item').forEach(i => i.classList.remove('selected'));
                    item.classList.add('selected');
                    this.selectedApp = item.dataset.package;
                    console.log('App selected:', this.selectedApp);
                });
            });

        } catch (error) {
            console.error('Error loading apps:', error);
            appList.innerHTML = `
                <div class="error-state">
                    <p>Error loading apps: ${error.message}</p>
                </div>
            `;
        }
    }

    async loadStep3() {
        console.log('Loading Step 3: Recording Mode');
        showToast(`Starting recording session...`, 'info');

        // Get canvas and context for rendering
        this.canvas = document.getElementById('screenshotCanvas');
        this.ctx = this.canvas.getContext('2d');
        this.currentImage = null;

        // Initialize FlowRecorder
        this.recorder = new FlowRecorder(this.selectedDevice, this.selectedApp, this.recordMode);

        // Setup UI event listeners
        this.setupRecordingUI();

        // Start recording session
        const started = await this.recorder.start();

        if (started) {
            // Display initial screenshot
            this.updateScreenshotDisplay();

            // Setup flow steps listener
            this.setupFlowStepsListener();
        }
    }

    setupRecordingUI() {
        // Canvas click handler
        this.canvas.addEventListener('click', async (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const canvasX = e.clientX - rect.left;
            const canvasY = e.clientY - rect.top;

            // Show element selection dialog
            await this.handleElementClick(canvasX, canvasY);
        });

        // Toggle element panel button
        document.getElementById('btnToggleElementPanel')?.addEventListener('click', () => {
            this.toggleElementPanel();
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

        // Swipe controls
        document.querySelectorAll('[data-swipe]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const direction = btn.dataset.swipe;
                await this.recorder.swipe(direction);
                this.updateScreenshotDisplay();
            });
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
                console.log(`[FlowWizard] ${filterName} = ${checkbox.checked}`);
                this.updateScreenshotDisplay();
            });

            // Set initial state
            checkbox.checked = this.overlayFilters[filterName];
        });

        console.log('[FlowWizard] Overlay filters initialized');
    }

    async handleElementClick(canvasX, canvasY) {
        // Convert canvas coordinates to device coordinates
        const deviceCoords = this.canvasToDevice(canvasX, canvasY);

        // Find clicked element from metadata
        const clickedElement = this.findElementAtCoordinates(deviceCoords.x, deviceCoords.y);

        // Show selection dialog
        const choice = await this.showElementSelectionDialog(clickedElement, deviceCoords);

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
                const text = await this.promptForText();
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
        const size = 40;
        const radius = size / 2;

        // Draw pulsing circle
        this.ctx.save();
        this.ctx.strokeStyle = '#3b82f6';
        this.ctx.lineWidth = 3;
        this.ctx.globalAlpha = 0.8;
        this.ctx.beginPath();
        this.ctx.arc(x, y, radius, 0, Math.PI * 2);
        this.ctx.stroke();
        this.ctx.restore();

        // Redraw overlays after short delay
        setTimeout(() => {
            this.drawElementOverlays();
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
        const sensorName = await this.promptForSensorName('Text Sensor');
        if (!sensorName) return;

        try {
            // Build SensorDefinition object
            const sensorDefinition = {
                device_id: this.selectedDevice,
                friendly_name: sensorName,
                sensor_type: 'sensor',
                device_class: 'none',
                unit_of_measurement: null,
                state_class: 'measurement',
                icon: 'mdi:text',
                source: {
                    source_type: 'element',
                    element_index: element?.index || 0,
                    element_text: element?.text || '',
                    element_class: element?.class || '',
                    element_resource_id: element?.resource_id || '',
                    custom_bounds: coords ? { x: coords.x, y: coords.y } : null
                },
                extraction_rule: {
                    method: 'exact',
                    regex_pattern: null,
                    before_text: null,
                    after_text: null,
                    between_start: null,
                    between_end: null,
                    extract_numeric: false,
                    remove_unit: false,
                    fallback_value: null,
                    pipeline: null
                },
                update_interval_seconds: 60,
                enabled: true,
                target_app: this.selectedApp,
                prerequisite_actions: [],
                navigation_sequence: null,
                validation_element: null,
                return_home_after: true,
                max_navigation_attempts: 3,
                navigation_timeout: 10
            };

            // Create sensor via API
            const response = await fetch('/api/sensors', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(sensorDefinition)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to create sensor');
            }

            const result = await response.json();
            const createdSensor = result.sensor;

            console.log('[FlowWizard] Created sensor:', createdSensor);

            // Add capture_sensors step to flow with real sensor_id
            this.recorder.addStep({
                step_type: 'capture_sensors',
                sensor_ids: [createdSensor.sensor_id], // Array of sensor IDs
                element: element || {},
                x: coords.x,
                y: coords.y,
                description: `Capture ${sensorName} sensor`
            });

            showToast(`Sensor "${sensorName}" created successfully`, 'success');

        } catch (error) {
            console.error('[FlowWizard] Failed to create sensor:', error);
            showToast(`Failed to create sensor: ${error.message}`, 'error', 5000);
        }
    }

    async createImageSensor(element, coords) {
        const sensorName = await this.promptForSensorName('Image Sensor');
        if (!sensorName) return;

        try {
            // Build SensorDefinition object for image capture
            const sensorDefinition = {
                device_id: this.selectedDevice,
                friendly_name: sensorName,
                sensor_type: 'camera',
                device_class: 'none',
                unit_of_measurement: null,
                state_class: null,
                icon: 'mdi:camera',
                source: {
                    source_type: 'element',
                    element_index: element?.index || 0,
                    element_text: element?.text || '',
                    element_class: element?.class || '',
                    element_resource_id: element?.resource_id || '',
                    custom_bounds: element?.bounds || (coords ? { x: coords.x, y: coords.y } : null)
                },
                extraction_rule: {
                    method: 'image_capture',
                    regex_pattern: null,
                    before_text: null,
                    after_text: null,
                    between_start: null,
                    between_end: null,
                    extract_numeric: false,
                    remove_unit: false,
                    fallback_value: null,
                    pipeline: null
                },
                update_interval_seconds: 60,
                enabled: true,
                target_app: this.selectedApp,
                prerequisite_actions: [],
                navigation_sequence: null,
                validation_element: null,
                return_home_after: true,
                max_navigation_attempts: 3,
                navigation_timeout: 10
            };

            // Create sensor via API
            const response = await fetch('/api/sensors', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(sensorDefinition)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to create sensor');
            }

            const result = await response.json();
            const createdSensor = result.sensor;

            console.log('[FlowWizard] Created image sensor:', createdSensor);

            // Add capture_sensors step to flow with real sensor_id
            this.recorder.addStep({
                step_type: 'capture_sensors',
                sensor_ids: [createdSensor.sensor_id], // Array of sensor IDs
                element: element || {},
                x: coords.x,
                y: coords.y,
                crop_bounds: element?.bounds,
                description: `Capture ${sensorName} image`
            });

            showToast(`Image sensor "${sensorName}" created successfully`, 'success');

        } catch (error) {
            console.error('[FlowWizard] Failed to create image sensor:', error);
            showToast(`Failed to create image sensor: ${error.message}`, 'error', 5000);
        }
    }

    async promptForSensorName(defaultName) {
        const name = prompt(`Enter sensor name:`, defaultName);
        return name && name.trim() !== '' ? name.trim() : null;
    }

    async handleRefreshWithRetries() {
        // Prompt for refresh configuration
        const attemptsStr = prompt('Number of refresh attempts (1-5):', '2');
        if (!attemptsStr) return;

        const attempts = Math.min(Math.max(parseInt(attemptsStr) || 2, 1), 5);

        const delayStr = prompt('Delay between refreshes in milliseconds (500-5000):', '1000');
        if (!delayStr) return;

        const delay = Math.min(Math.max(parseInt(delayStr) || 1000, 500), 5000);

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

    updateScreenshotDisplay() {
        const dataUrl = this.recorder.getScreenshotDataUrl();
        const metadata = this.recorder.screenshotMetadata;
        const loading = document.getElementById('screenshotLoading');

        // Create image from base64 data
        const img = new Image();

        img.onload = () => {
            // Store current image
            this.currentImage = img;

            // Resize canvas to match image dimensions exactly (no letterboxing)
            this.canvas.width = img.width;
            this.canvas.height = img.height;

            // Draw screenshot image at full size
            this.ctx.drawImage(img, 0, 0);

            // Draw UI element overlays
            if (metadata && metadata.elements && metadata.elements.length > 0) {
                this.drawElementOverlays();
                this.updateElementPanel(metadata.elements);
            }

            // Show canvas, hide loading
            this.canvas.style.display = 'block';
            if (loading) loading.style.display = 'none';

            console.log(`[FlowWizard] Rendered screenshot at ${img.width}x${img.height} (1:1 scale)`);
        };

        img.onerror = () => {
            console.error('[FlowWizard] Failed to load screenshot');
            if (loading) {
                loading.textContent = 'Error loading screenshot';
                loading.style.display = 'block';
            }
        };

        img.src = dataUrl;
    }

    /**
     * Toggle element panel visibility
     */
    toggleElementPanel() {
        const panel = document.getElementById('elementPanel');
        if (!panel) {
            console.warn('[FlowWizard] Element panel not found');
            return;
        }

        const isVisible = panel.style.display !== 'none';
        panel.style.display = isVisible ? 'none' : 'block';

        const btn = document.getElementById('btnToggleElementPanel');
        if (btn) {
            btn.textContent = isVisible ? '📋 Show Elements' : '❌ Hide Elements';
        }

        console.log(`[FlowWizard] Element panel ${isVisible ? 'hidden' : 'shown'}`);
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

        if (!elements || elements.length === 0) {
            panel.innerHTML = '<div class="empty-state">No elements detected in screenshot</div>';
            return;
        }

        // Filter to clickable and text elements
        const interactiveElements = elements.filter(el =>
            el.clickable || (el.text && el.text.trim().length > 0)
        );

        console.log(`[FlowWizard] Rendering ${interactiveElements.length} interactive elements (${elements.length} total)`);

        panel.innerHTML = interactiveElements.map((el, index) => {
            const displayText = el.text || el.content_desc || el.resource_id?.split('/').pop() || `Element ${index}`;
            const isClickable = el.clickable === true || el.clickable === 'true';
            const icon = isClickable ? '🔘' : '📝';
            const typeLabel = isClickable ? 'Clickable' : 'Text';

            return `
                <div class="element-item" data-element-index="${index}">
                    <div class="element-item-header">
                        <span class="element-icon">${icon}</span>
                        <div class="element-info">
                            <div class="element-text">${displayText}</div>
                            <div class="element-meta">${typeLabel} • ${el.class?.split('.').pop() || 'Unknown'}</div>
                        </div>
                    </div>
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

    async loadStep4() {
        console.log('Loading Step 4: Review & Test');
        const reviewContainer = document.getElementById('flowStepsReview');

        if (this.flowSteps.length === 0) {
            reviewContainer.innerHTML = `
                <div class="empty-state">
                    <p>No steps recorded</p>
                </div>
            `;
            return;
        }

        // Render flow steps review
        reviewContainer.innerHTML = `
            <div class="flow-summary">
                <h3>Flow Summary</h3>
                <div class="summary-stats">
                    <div class="stat-item">
                        <span class="stat-label">Device:</span>
                        <span class="stat-value">${this.selectedDevice}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">App:</span>
                        <span class="stat-value">${this.selectedApp}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Total Steps:</span>
                        <span class="stat-value">${this.flowSteps.length}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Mode:</span>
                        <span class="stat-value">${this.recordMode === 'execute' ? 'Execute' : 'Record Only'}</span>
                    </div>
                </div>
            </div>

            <div class="steps-review-list">
                ${this.flowSteps.map((step, index) => `
                    <div class="step-review-item">
                        <div class="step-review-number">${index + 1}</div>
                        <div class="step-review-content">
                            <div class="step-review-type">${this.formatStepType(step.step_type)}</div>
                            <div class="step-review-description">${step.description || this.generateStepDescription(step)}</div>
                            ${this.renderStepDetails(step)}
                        </div>
                        <div class="step-review-actions">
                            <button class="btn btn-sm btn-danger" onclick="window.flowWizard.removeStepAt(${index})">
                                Delete
                            </button>
                        </div>
                    </div>
                `).join('')}
            </div>

            <div id="testResults" class="test-results" style="display: none;">
                <h3>Test Results</h3>
                <div id="testResultsContent"></div>
            </div>
        `;

        // Wire up test button
        const btnTestFlow = document.getElementById('btnTestFlow');
        if (btnTestFlow) {
            btnTestFlow.onclick = () => this.testFlow();
        }
    }

    formatStepType(stepType) {
        const types = {
            'launch_app': '🚀 Launch App',
            'tap': '👆 Tap',
            'swipe': '👉 Swipe',
            'text': '⌨️ Type Text',
            'keyevent': '🔘 Key Press',
            'wait': '⏱️ Wait',
            'go_back': '⬅️ Back',
            'go_home': '🏠 Home',
            'execute_action': '⚡ Action',
            'capture_sensors': '📊 Capture Sensor',
            'stitch_capture': '📸 Stitch Capture'
        };
        return types[stepType] || stepType;
    }

    generateStepDescription(step) {
        switch (step.step_type) {
            case 'launch_app':
                return `Launch ${step.package}`;
            case 'tap':
                return `Tap at (${step.x}, ${step.y})`;
            case 'swipe':
                return `Swipe from (${step.x1}, ${step.y1}) to (${step.x2}, ${step.y2})`;
            case 'text':
                return `Type: "${step.text}"`;
            case 'keyevent':
                return `Press ${step.keycode}`;
            case 'wait':
                if (step.refresh_attempts) {
                    return `Wait for UI update (${step.refresh_attempts} refreshes, ${step.refresh_delay}ms delay)`;
                }
                return `Wait ${step.duration}ms`;
            case 'capture_sensors':
                const sensorType = step.sensor_type || 'unknown';
                const sensorName = step.sensor_name || 'unnamed';
                return `Capture ${sensorType} sensor: "${sensorName}"`;
            default:
                return step.step_type;
        }
    }

    renderStepDetails(step) {
        let details = [];

        if (step.x !== undefined) details.push(`x: ${step.x}`);
        if (step.y !== undefined) details.push(`y: ${step.y}`);
        if (step.x1 !== undefined) details.push(`start: (${step.x1}, ${step.y1})`);
        if (step.x2 !== undefined) details.push(`end: (${step.x2}, ${step.y2})`);
        if (step.duration !== undefined) {
            if (step.refresh_attempts) {
                details.push(`${step.refresh_attempts} refreshes`);
                details.push(`${step.refresh_delay}ms delay`);
            } else {
                details.push(`duration: ${step.duration}ms`);
            }
        }
        if (step.text) details.push(`text: "${step.text}"`);
        if (step.package) details.push(`package: ${step.package}`);

        // Sensor-specific details
        if (step.step_type === 'capture_sensors') {
            if (step.sensor_id) details.push(`id: ${step.sensor_id}`);
            if (step.element?.text) details.push(`element text: "${step.element.text}"`);
            if (step.element?.class) details.push(`element class: ${step.element.class}`);
        }

        if (details.length === 0) return '';

        return `<div class="step-review-details">${details.join(' • ')}</div>`;
    }

    removeStepAt(index) {
        if (index >= 0 && index < this.flowSteps.length) {
            const removed = this.flowSteps.splice(index, 1)[0];
            console.log(`Removed step ${index}:`, removed);
            showToast(`Step ${index + 1} removed`, 'info');
            this.loadStep4(); // Refresh the review display
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

            const response = await fetch('/api/flows', {
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
            const executeResponse = await fetch(`/api/flows/${this.selectedDevice}/${createdFlow.flow_id}/execute`, {
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
            await fetch(`/api/flows/${this.selectedDevice}/${createdFlow.flow_id}`, {
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

    async loadStep5() {
        console.log('Loading Step 5: Settings');
        // Auto-generate flow name
        const appName = this.selectedApp ? this.selectedApp.split('.').pop() : 'flow';
        const flowNameInput = document.getElementById('flowName');
        if (flowNameInput && !flowNameInput.value) {
            flowNameInput.value = `${appName}_flow`;
        }

        // Setup quick interval buttons
        document.querySelectorAll('[data-interval]').forEach(btn => {
            btn.addEventListener('click', () => {
                const seconds = parseInt(btn.dataset.interval);
                const minutes = seconds / 60;
                document.getElementById('intervalValue').value = minutes;
                document.getElementById('intervalUnit').value = '60';
            });
        });
    }

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
            const response = await fetch('/api/flows', {
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
                this.currentStep = 1;
                this.selectedDevice = null;
                this.selectedApp = null;
                this.recordMode = 'execute';
                this.recorder = null;
                this.flowSteps = [];
                this.updateUI();
                this.loadStep1();
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
