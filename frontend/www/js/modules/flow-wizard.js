/**
 * Flow Wizard Module
 * Visual Mapper v0.0.28
 *
 * v0.0.28: Fix wizard cleanup - use sendBeacon for reliable release on page unload
 * v0.0.27: Preserve screen_activity/screen_package in step conversions, add wait refresh support
 * v0.0.26: Fix _convertWizardStepsToFlowFormat - use step.step_type || step.type, handle all step types
 * v0.0.25: Fix step format - include step_type in converted flow steps for executor compatibility
 * v0.0.24: Sync flowSteps when navigating between steps to preserve changes
 * v0.0.23: Fix edit mode not showing step 3 - add missing updateUI() call
 *
 * Interactive wizard for creating flows with recording mode
 * Refactored: Steps 1,2,4,5 use separate modules
 * v0.0.7: New toolbar UI, localStorage preferences, simplified layout
 * v0.0.8: Tabbed panel, loading overlay, fixed ripple offset
 * v0.0.9: Pass overlay filters to findElementAtCoordinates for container filtering
 * v0.0.10: Pause sensor updates during wizard to prevent ADB contention
 * v0.0.22: Updated Step4 import for navigation issue detection
 */

import { showToast } from './toast.js?v=0.4.0-beta.2.15';
import FlowRecorder from './flow-recorder.js?v=0.4.0-beta.2.15';
import FlowCanvasRenderer from './flow-canvas-renderer.js?v=0.4.0-beta.2.15';
import FlowInteractions from './flow-interactions.js?v=0.4.0-beta.2.15';
import FlowStepManager from './flow-step-manager.js?v=0.4.0-beta.2.15';
import LiveStream from './live-stream.js?v=0.4.0-beta.2.15';
import ElementTree from './element-tree.js?v=0.4.0-beta.2.15';
import APIClient from './api-client.js?v=0.4.0-beta.2.15';
import SensorCreator from './sensor-creator.js?v=0.4.0-beta.2.15';

// Step modules
import * as Step1 from './flow-wizard-step1.js?v=0.4.0-beta.2.15';
import * as Step2 from './flow-wizard-step2.js?v=0.4.0-beta.2.15';
import * as Step3 from './flow-wizard-step3.js?v=0.4.0-beta.2.15';
import * as Step4 from './flow-wizard-step4.js?v=0.4.0-beta.2.15';
import * as Step5 from './flow-wizard-step5.js?v=0.4.0-beta.2.15';

// Dialog module
import * as Dialogs from './flow-wizard-dialogs.js?v=0.4.0-beta.2.15';

// Element actions module
import * as ElementActions from './flow-wizard-element-actions.js?v=0.4.0-beta.2.15';

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
        this.freshStart = true; // Force-stop app before launch by default
        const savedStartMode = localStorage.getItem('flowWizard.startFromCurrentScreen');
        this.startFromCurrentScreen = savedStartMode === 'true';
        this.recorder = null;
        this.flowSteps = [];
        this.schedulerWasPaused = false;  // Track if we paused the scheduler
        this.overlayFilters = {
            showClickable: true,
            showNonClickable: false,  // Off by default - clickable elements are most useful
            showTextLabels: true,
            hideSmall: true,          // On by default - hide tiny elements
            textOnly: false,
            hideDividers: true,       // Hide full-width horizontal line elements
            hideContainers: true,     // Hide layout/container elements (View, FrameLayout, etc.)
            hideEmptyElements: true   // Hide elements without text or content-desc
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
        this.interactions = null;
        this.stepManager = null;

        // Live streaming (Phase 1 enhancement)
        this.captureMode = 'polling'; // 'polling' or 'streaming'
        this.streamMode = 'mjpeg'; // 'mjpeg' or 'websocket'
        this.streamQuality = 'fast'; // 'high', 'medium', 'low', 'fast' - default 'fast' for WiFi compatibility
        this.liveStream = null;

        // Gesture recording (Phase 4 enhancement)
        this.dragStart = null;
        this.isDragging = false;

        // Recording pause toggle - when paused, gestures are executed but not recorded
        this.recordingPaused = false;
        this.MIN_SWIPE_DISTANCE = 30; // Minimum pixels to count as swipe

        // Element tree (Phase 5 enhancement)
        this.elementTree = null;
        this.isTreeViewOpen = false;

        // API client and sensor creator (for advanced sensor dialog)
        this.apiClient = new APIClient();
        this.sensorCreator = new SensorCreator(this.apiClient);

        // Set callback for when sensor is created - add capture step to flow
        this.sensorCreator.onSensorCreated = (response, sensorData) => {
            Dialogs.handleSensorCreated(this, response, sensorData);
        };

        // Edit mode properties
        this.editMode = false;
        this.editingActionId = null;
        this.editingActionDef = null;
        this.preExistingStepCount = 0;

        console.log('FlowWizard initialized');
        this.init();
    }

    /**
     * Open wizard in edit mode with pre-loaded action steps
     * @param {Object} actionDef - Full action definition object
     * @param {string} deviceId - Device ID the action belongs to
     */
    async openInEditMode(actionDef, deviceId) {
        console.log('[FlowWizard] Opening in edit mode for action:', actionDef.id);

        this.editMode = true;
        this.editingActionId = actionDef.id;
        this.editingActionDef = actionDef;

        const action = actionDef.action;

        // Set device and app context
        this.selectedDevice = deviceId;
        this.selectedApp = actionDef.source_app || action.package_name || null;

        // Skip to step 3 (recording step) directly
        this.currentStep = 3;

        // Create recorder with existing steps
        if (this.recorder) {
            this.recorder.stop?.();
        }

        const FlowRecorder = (await import('./flow-recorder.js?v=0.4.0-beta.2.15')).default;
        this.recorder = new FlowRecorder(deviceId, this.selectedApp, this.recordMode);

        // Load existing steps (convert from action format to flow format)
        if (action.action_type === 'macro' && Array.isArray(action.actions)) {
            // Don't skip launch step - user might want to see full sequence
            this.recorder.loadSteps(action.actions, false);
            this.preExistingStepCount = action.actions.length;
        }

        // Update UI to show we're in edit mode
        this._showEditModeUI();

        // Navigate to wizard page with edit params
        const wizardUrl = `flow-wizard.html?edit=true&device=${encodeURIComponent(deviceId)}&action=${encodeURIComponent(actionDef.id)}`;
        window.location.href = wizardUrl;
    }

    /**
     * Resume edit mode from URL params (called on page load)
     * Handles both action editing (edit=true&action=X) and flow editing (editFlow=true&flow=X)
     */
    async resumeEditMode() {
        const params = new URLSearchParams(window.location.search);

        // Check for flow editing first
        if (params.get('editFlow') === 'true') {
            return await this._resumeFlowEditMode(params);
        }

        // Then check for action editing
        if (params.get('edit') !== 'true') return false;

        const deviceId = params.get('device');
        const actionId = params.get('action');

        if (!deviceId || !actionId) {
            console.warn('[FlowWizard] Edit mode missing device or action ID');
            return false;
        }

        try {
            // Fetch action data
            const response = await fetch(`${getApiBase()}/actions/${deviceId}/${actionId}`);
            if (!response.ok) throw new Error('Failed to fetch action');

            const data = await response.json();
            if (!data.success || !data.action) throw new Error('Invalid action data');

            const actionDef = data.action;
            const action = actionDef.action;

            this.editMode = true;
            this.editingActionId = actionId;
            this.editingActionDef = actionDef;
            this.selectedDevice = deviceId;
            this.selectedApp = actionDef.source_app || action.package_name || null;

            // Load steps into recorder when it's ready
            this._pendingEditSteps = action.action_type === 'macro' ? action.actions : [];
            this.preExistingStepCount = this._pendingEditSteps.length;

            console.log(`[FlowWizard] Resumed edit mode: ${actionId} with ${this.preExistingStepCount} steps`);
            return true;
        } catch (error) {
            console.error('[FlowWizard] Failed to resume edit mode:', error);
            return false;
        }
    }

    /**
     * Resume flow edit mode from URL params
     * @private
     */
    async _resumeFlowEditMode(params) {
        const deviceId = params.get('device');
        const flowId = params.get('flow');

        if (!deviceId || !flowId) {
            console.warn('[FlowWizard] Flow edit mode missing device or flow ID');
            return false;
        }

        try {
            // Fetch flow data
            const response = await fetch(`${getApiBase()}/flows/${deviceId}/${flowId}`);
            if (!response.ok) throw new Error('Failed to fetch flow');

            const flow = await response.json();

            this.editMode = true;
            this.editingFlowMode = true;  // Flag to distinguish from action editing
            this.editingFlowId = flowId;
            this.editingFlowData = flow;
            this.stableDeviceId = deviceId;  // Store stable ID separately

            // Resolve connection ID from stable ID by fetching ADB devices
            let connectionId = deviceId;  // Fallback to stable ID
            try {
                const devicesResponse = await fetch(`${getApiBase()}/adb/devices`);
                if (devicesResponse.ok) {
                    const devicesData = await devicesResponse.json();
                    const devices = devicesData.devices || [];
                    // Find device by matching stable ID in the id or by model
                    const matchingDevice = devices.find(d =>
                        d.id === deviceId ||
                        d.serial === deviceId ||
                        d.id.includes(deviceId)
                    );
                    if (matchingDevice) {
                        connectionId = matchingDevice.id;
                        console.log(`[FlowWizard] Resolved stable ID ${deviceId} to connection ID ${connectionId}`);
                    }
                }
            } catch (e) {
                console.warn('[FlowWizard] Could not resolve connection ID:', e);
            }

            this.selectedDevice = connectionId;

            // Extract app from first launch_app step or from step screen_package
            const launchStep = (flow.steps || []).find(s => s.step_type === 'launch_app');
            const anyStep = (flow.steps || []).find(s => s.screen_package);
            this.selectedApp = launchStep?.package || anyStep?.screen_package || null;

            // Convert flow steps to wizard step format
            this._pendingEditSteps = this._convertFlowStepsToWizardFormat(flow.steps || []);
            this.preExistingStepCount = this._pendingEditSteps.length;

            console.log(`[FlowWizard] Resumed FLOW edit mode: ${flowId} with ${this.preExistingStepCount} steps`);
            return true;
        } catch (error) {
            console.error('[FlowWizard] Failed to resume flow edit mode:', error);
            return false;
        }
    }

    /**
     * Convert flow steps to wizard step format
     * Flow steps have different property names than wizard steps
     * IMPORTANT: Keep step_type for compatibility with flow executor
     * @private
     */
    _convertFlowStepsToWizardFormat(flowSteps) {
        return flowSteps.map(step => {
            const wizardStep = {
                step_type: step.step_type,  // Keep step_type for flow executor compatibility
                type: step.step_type,       // Also set type for wizard UI
                description: step.description || '',
                // Preserve screen context
                screen_activity: step.screen_activity || null,
                screen_package: step.screen_package || null,
                _preExisting: true,  // Mark as existing step
                _flowStep: step      // Keep original for reference
            };

            switch (step.step_type) {
                case 'tap':
                    wizardStep.x = step.x;
                    wizardStep.y = step.y;
                    wizardStep.element_id = step.element_resource_id;
                    wizardStep.element = step.element;
                    break;
                case 'swipe':
                    wizardStep.x1 = step.start_x;
                    wizardStep.y1 = step.start_y;
                    wizardStep.x2 = step.end_x;
                    wizardStep.y2 = step.end_y;
                    wizardStep.start_x = step.start_x;
                    wizardStep.start_y = step.start_y;
                    wizardStep.end_x = step.end_x;
                    wizardStep.end_y = step.end_y;
                    wizardStep.duration = step.duration || 500;
                    break;
                case 'launch_app':
                    wizardStep.package = step.package;
                    wizardStep.expected_activity = step.expected_activity;
                    break;
                case 'wait':
                    wizardStep.duration = step.duration;
                    wizardStep.validate_timestamp = step.validate_timestamp;
                    wizardStep.timestamp_element = step.timestamp_element;
                    wizardStep.refresh_max_retries = step.refresh_max_retries;
                    wizardStep.refresh_retry_delay = step.refresh_retry_delay;
                    break;
                case 'type_text':
                case 'text':
                    wizardStep.text = step.text;
                    break;
                case 'capture_sensors':
                    wizardStep.sensor_ids = step.sensor_ids || [];
                    wizardStep.sensor_name = step.sensor_name;
                    wizardStep.sensor_type = step.sensor_type;
                    wizardStep.element = step.element;
                    break;
                case 'keypress':
                case 'keyevent':
                    wizardStep.keycode = step.keycode;
                    break;
            }

            return wizardStep;
        });
    }

    /**
     * Convert wizard steps back to flow step format for saving
     * @private
     */
    _convertWizardStepsToFlowFormat(wizardSteps) {
        return wizardSteps.map(step => {
            // If this was a pre-existing step with original data, use it as base
            const baseStep = step._flowStep || {};

            // Get step type - new recorder steps use step_type, converted ones have type
            const stepType = step.step_type || step.type;

            const flowStep = {
                ...baseStep,
                step_type: stepType,
                description: step.description || `${stepType} step`,
                // Preserve screen context (from wizard step or base)
                screen_activity: step.screen_activity || baseStep.screen_activity || null,
                screen_package: step.screen_package || baseStep.screen_package || null
            };

            switch (stepType) {
                case 'tap':
                    flowStep.x = step.x;
                    flowStep.y = step.y;
                    if (step.element_id) flowStep.element_resource_id = step.element_id;
                    if (step.element) flowStep.element = step.element;
                    break;
                case 'swipe':
                    flowStep.start_x = step.x1 || step.start_x;
                    flowStep.start_y = step.y1 || step.start_y;
                    flowStep.end_x = step.x2 || step.end_x;
                    flowStep.end_y = step.y2 || step.end_y;
                    flowStep.duration = step.duration || 500;
                    break;
                case 'launch_app':
                    flowStep.package = step.package;
                    if (step.expected_activity) flowStep.expected_activity = step.expected_activity;
                    break;
                case 'wait':
                    flowStep.duration = step.duration;
                    // Legacy refresh_attempts support
                    if (step.refresh_attempts) {
                        flowStep.refresh_attempts = step.refresh_attempts;
                        flowStep.refresh_delay = step.refresh_delay;
                    }
                    // New validate_timestamp support
                    if (step.validate_timestamp) {
                        flowStep.validate_timestamp = step.validate_timestamp;
                        flowStep.timestamp_element = step.timestamp_element;
                        flowStep.refresh_max_retries = step.refresh_max_retries || 3;
                        flowStep.refresh_retry_delay = step.refresh_retry_delay || 2000;
                    }
                    break;
                case 'pull_refresh':
                    // Pull refresh is its own step type - preserve it
                    if (step.validate_timestamp) {
                        flowStep.validate_timestamp = step.validate_timestamp;
                        flowStep.timestamp_element = step.timestamp_element;
                        flowStep.refresh_max_retries = step.refresh_max_retries;
                        flowStep.refresh_retry_delay = step.refresh_retry_delay;
                    }
                    break;
                case 'type_text':
                case 'text':
                    flowStep.step_type = 'text';
                    flowStep.text = step.text;
                    break;
                case 'capture_sensors':
                    flowStep.sensor_ids = step.sensor_ids || [];
                    // Preserve sensor details for execution
                    if (step.sensor_name) flowStep.sensor_name = step.sensor_name;
                    if (step.sensor_type) flowStep.sensor_type = step.sensor_type;
                    if (step.element) flowStep.element = step.element;
                    if (step.extraction) flowStep.extraction = step.extraction;
                    break;
                case 'keypress':
                case 'keyevent':
                    flowStep.step_type = 'keyevent';
                    flowStep.keycode = step.keycode;
                    break;
                case 'go_back':
                case 'go_home':
                    // Navigation steps - keep as is
                    break;
            }

            // Remove internal wizard properties
            delete flowStep._preExisting;
            delete flowStep._flowStep;
            delete flowStep.type;  // Remove wizard-only property

            return flowStep;
        });
    }

    /**
     * Check if editing a flow (vs an action)
     */
    isFlowEditMode() {
        return this.editMode && this.editingFlowMode === true;
    }

    /**
     * Show edit mode UI indicators
     * @private
     */
    _showEditModeUI() {
        // Add edit mode banner when DOM is ready
        setTimeout(() => {
            const header = document.querySelector('.wizard-header h1, .page-title');
            if (header && this.editMode) {
                if (this.isFlowEditMode()) {
                    header.innerHTML = `✏️ Editing Flow: ${this.editingFlowData?.name || 'Unknown'}`;
                } else {
                    header.innerHTML = `✏️ Editing Action: ${this.editingActionDef?.action?.name || 'Unknown'}`;
                }
            }

            // Show pre-existing step count
            const stepsPanel = document.getElementById('stepsPanel');
            if (stepsPanel && this.preExistingStepCount > 0) {
                const badge = document.createElement('div');
                badge.className = 'edit-mode-badge';
                const editType = this.isFlowEditMode() ? 'flow' : 'action';
                badge.innerHTML = `<span style="background: #f59e0b; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px;">📝 ${this.preExistingStepCount} existing ${editType} steps loaded</span>`;
                stepsPanel.insertBefore(badge, stepsPanel.firstChild);
            }
        }, 500);
    }

    /**
     * Check if in edit mode
     */
    isEditMode() {
        return this.editMode === true;
    }

    /**
     * Exit edit mode and reset state
     */
    exitEditMode() {
        this.editMode = false;
        this.editingActionId = null;
        this.editingActionDef = null;
        this.preExistingStepCount = 0;
        this._pendingEditSteps = null;
    }

    init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setup());
        } else {
            this.setup();
        }
    }

    async setup() {
        this.setupNavigation();
        this.setupCleanup();
        this.setupEditListeners();
        this.pauseSchedulerForEditing();

        // Check if resuming edit mode from URL
        const isEditMode = await this.resumeEditMode();

        if (isEditMode) {
            // Skip device/app selection, go directly to step 3
            console.log('[FlowWizard] Edit mode - skipping to step 3');
            this.currentStep = 3;
            this.updateUI();  // CRITICAL: Update DOM to show step 3 content, hide step 1
            Step3.loadStep3(this);
            this._showEditModeUI();
        } else {
            Step1.loadStep(this); // Load first step for new flow
        }

        console.log('FlowWizard setup complete');
    }

    /**
     * Setup cleanup handlers for page unload
     */
    setupCleanup() {
        // Resume scheduler and mark wizard inactive when leaving the page
        // Use 'pagehide' instead of 'beforeunload' for better mobile support
        window.addEventListener('pagehide', (event) => {
            this._cleanupOnUnload();
        });

        // Also use beforeunload as backup
        window.addEventListener('beforeunload', () => {
            this._cleanupOnUnload();
        });

        // Also handle visibility change (tab switch)
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'hidden') {
                // Don't resume on tab switch - only on page close
            }
        });
    }

    /**
     * Setup event listeners for edit requests from FlowStepManager
     */
    setupEditListeners() {
        const wizard = this;

        // Handle sensor edit request from Flow panel
        window.addEventListener('editSensorRequest', async (event) => {
            const { sensorId, stepIndex } = event.detail;
            console.log(`[FlowWizard] Edit sensor request: ${sensorId} (step ${stepIndex})`);

            // Need device ID to fetch sensor - use selected device
            const deviceId = wizard.selectedDevice;
            if (!deviceId) {
                console.warn('[FlowWizard] No device selected for sensor edit');
                window.showToast?.('No device selected', 'error', 3000);
                return;
            }

            try {
                // Fetch sensor data from API - endpoint is /sensors/{device_id}/{sensor_id}
                const response = await wizard.apiClient.get(`/sensors/${encodeURIComponent(deviceId)}/${encodeURIComponent(sensorId)}`);
                if (response && response.sensor) {
                    // Open sensor editor dialog
                    if (wizard.sensorCreator) {
                        wizard.sensorCreator.showEdit(response.sensor);
                    } else {
                        console.warn('[FlowWizard] SensorCreator not available');
                        window.showToast?.('Sensor editor not available', 'error', 3000);
                    }
                } else {
                    window.showToast?.('Sensor not found', 'error', 3000);
                }
            } catch (error) {
                console.error('[FlowWizard] Failed to load sensor for editing:', error);
                window.showToast?.('Failed to load sensor', 'error', 3000);
            }
        });

        // Handle action edit request from Flow panel
        window.addEventListener('editActionRequest', async (event) => {
            const { actionId, stepIndex } = event.detail;
            console.log(`[FlowWizard] Edit action request: ${actionId} (step ${stepIndex})`);

            try {
                // Fetch action data from API
                const response = await wizard.apiClient.get(`/actions/${actionId}`);
                if (response && response.action) {
                    // Open action editor dialog (use simple dialog for now)
                    window.showToast?.('Action editing coming soon', 'info', 3000);
                    // TODO: Implement action edit dialog
                } else {
                    window.showToast?.('Action not found', 'error', 3000);
                }
            } catch (error) {
                console.error('[FlowWizard] Failed to load action for editing:', error);
                window.showToast?.('Failed to load action', 'error', 3000);
            }
        });
    }

    /**
     * Cleanup wizard state on page unload
     * Uses sendBeacon for reliable delivery during page close
     */
    _cleanupOnUnload() {
        // Resume scheduler (fire and forget with sendBeacon)
        try {
            const apiBase = window.API_BASE || '/api';
            navigator.sendBeacon(`${apiBase}/scheduler/resume`);
        } catch (e) {
            console.warn('[FlowWizard] Could not resume scheduler on unload');
        }

        // Mark wizard inactive using sendBeacon (more reliable during unload)
        if (this._wizardActiveDevice) {
            try {
                const apiBase = window.API_BASE || '/api';
                // sendBeacon only supports POST, so we need a POST endpoint
                // Use a blob to send the DELETE-like request
                const url = `${apiBase}/wizard/release/${encodeURIComponent(this._wizardActiveDevice)}`;
                navigator.sendBeacon(url);
                console.log(`[FlowWizard] Sent beacon to release wizard for ${this._wizardActiveDevice}`);
            } catch (e) {
                console.warn('[FlowWizard] Could not release wizard on unload:', e);
            }
        }
    }

    /**
     * Pause the flow scheduler and sensor updates while editing flows
     * This prevents ADB contention and improves streaming performance
     */
    async pauseSchedulerForEditing() {
        // Pause flow scheduler
        try {
            const response = await this.apiClient.post('/scheduler/pause');
            if (response.success) {
                console.log('[FlowWizard] Paused flow scheduler for editing');
                this.schedulerWasPaused = true;
                this.showSchedulerStatus('paused');
            }
        } catch (e) {
            console.warn('[FlowWizard] Could not pause scheduler:', e);
        }
    }

    /**
     * Pause sensor updates for the selected device
     * Call this when device is selected to reduce ADB contention
     */
    async pauseSensorUpdates(deviceId) {
        if (!deviceId) return;
        try {
            const response = await this.apiClient.post(`/sensors/pause/${encodeURIComponent(deviceId)}`);
            if (response.success && response.paused) {
                console.log(`[FlowWizard] Paused sensor updates for ${deviceId}`);
                this._sensorsPaused = true;
                this._pausedDeviceId = deviceId;
            }
        } catch (e) {
            console.warn('[FlowWizard] Could not pause sensor updates:', e);
        }
    }

    /**
     * Resume sensor updates for the paused device
     */
    async resumeSensorUpdates() {
        if (!this._sensorsPaused || !this._pausedDeviceId) return;
        try {
            await this.apiClient.post(`/sensors/resume/${encodeURIComponent(this._pausedDeviceId)}`);
            console.log(`[FlowWizard] Resumed sensor updates for ${this._pausedDeviceId}`);
            this._sensorsPaused = false;
            this._pausedDeviceId = null;
        } catch (e) {
            console.warn('[FlowWizard] Could not resume sensor updates:', e);
        }
    }

    /**
     * Resume the flow scheduler and sensor updates after editing
     */
    async resumeSchedulerAfterEditing() {
        // Resume sensor updates first
        await this.resumeSensorUpdates();

        // Resume flow scheduler
        if (!this.schedulerWasPaused) return;

        try {
            await this.apiClient.post('/scheduler/resume');
            console.log('[FlowWizard] Resumed flow scheduler after editing');
            this.schedulerWasPaused = false;
        } catch (e) {
            console.warn('[FlowWizard] Could not resume scheduler:', e);
        }
    }

    /**
     * Show scheduler status indicator
     */
    showSchedulerStatus(status) {
        // Add a subtle indicator that scheduler is paused
        const nav = document.querySelector('nav');
        if (nav && status === 'paused') {
            // Check if indicator already exists
            if (!document.getElementById('scheduler-pause-indicator')) {
                const indicator = document.createElement('li');
                indicator.id = 'scheduler-pause-indicator';
                indicator.innerHTML = '<span style="color: #ff9800; font-size: 12px;" title="Flow scheduler is paused during editing">⏸ Flows Paused</span>';
                nav.querySelector('ul').appendChild(indicator);
            }
        } else {
            const indicator = document.getElementById('scheduler-pause-indicator');
            if (indicator) indicator.remove();
        }
    }

    /**
     * Mark device as having active wizard session
     * Prevents auto-sleep after flow execution while wizard is open
     */
    async setWizardActive(deviceId) {
        if (!deviceId) return;
        try {
            await this.apiClient.post(`/wizard/active/${encodeURIComponent(deviceId)}`);
            console.log(`[FlowWizard] Marked wizard active for device ${deviceId}`);
            this._wizardActiveDevice = deviceId;
        } catch (e) {
            console.warn('[FlowWizard] Could not mark wizard active:', e);
        }
    }

    /**
     * Mark device as no longer having active wizard session
     * Re-enables auto-sleep after flow execution
     */
    async setWizardInactive(deviceId) {
        if (!deviceId) return;
        try {
            await this.apiClient.delete(`/wizard/active/${encodeURIComponent(deviceId)}`);
            console.log(`[FlowWizard] Marked wizard inactive for device ${deviceId}`);
            this._wizardActiveDevice = null;
        } catch (e) {
            console.warn('[FlowWizard] Could not mark wizard inactive:', e);
        }
    }

    /**
     * Reset wizard to initial state
     */
    async reset() {
        // Stop streaming if active (await to ensure clean teardown)
        await this.stopStreaming();
        this.captureMode = 'polling';

        this.currentStep = 1;
        this.selectedDevice = null;
        this.selectedApp = null;
        this.recordMode = 'execute';
        this.freshStart = true;
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

        // Sync flowSteps when leaving step 3
        if (this.currentStep === 3 && this.recorder) {
            this.flowSteps = [...this.recorder.getSteps()];
            console.log(`[FlowWizard] Synced ${this.flowSteps.length} steps before leaving step 3`);
        }

        if (this.currentStep < this.totalSteps) {
            this.currentStep++;
            this.updateUI();
            this.loadStepContent();
        } else {
            // Last step - save flow (delegate to Step5)
            Step5.saveFlow(this);
        }
    }

    previousStep() {
        // Sync flowSteps when leaving step 4 (going back to 3)
        if (this.currentStep === 4 && this.recorder) {
            this.flowSteps = [...this.recorder.getSteps()];
            console.log(`[FlowWizard] Synced ${this.flowSteps.length} steps before going back to step 3`);
        }

        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateUI();
            this.loadStepContent();
        }
    }

    /**
     * Navigate directly to a specific step
     * Used by Step 4 to return to Step 3 for inserting missing navigation steps
     * @param {number} stepNumber - Step number (1-5)
     */
    async goToStep(stepNumber) {
        if (stepNumber < 1 || stepNumber > this.totalSteps) {
            console.warn(`[FlowWizard] Invalid step number: ${stepNumber}`);
            return;
        }

        // Stop streaming when leaving Step 3 (await to ensure clean teardown)
        if (this.currentStep === 3 && stepNumber !== 3 && this.captureMode === 'streaming') {
            await this.stopStreaming();
            this.captureMode = 'polling';
        }

        console.log(`[FlowWizard] Navigating from step ${this.currentStep} to step ${stepNumber}`);
        this.currentStep = stepNumber;
        this.updateUI();
        this.loadStepContent();
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
                // Get fresh start preference
                const freshStartToggle = document.getElementById('freshStartToggle');
                this.freshStart = freshStartToggle ? freshStartToggle.checked : true;
                console.log('[FlowWizard] Validated step 2:', {
                    app: this.selectedApp,
                    mode: this.recordMode,
                    freshStart: this.freshStart
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

    async loadStepContent() {
        // Stop streaming when leaving Step 3 (await to ensure clean teardown)
        if (this.currentStep !== 3 && this.captureMode === 'streaming') {
            await this.stopStreaming();
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
                Step3.loadStep3(this);
                break;
            case 4:
                Step4.loadStep(this);
                break;
            case 5:
                Step5.loadStep(this);
                break;
        }
    }

    // NOTE: All steps moved to separate modules:
    // - flow-wizard-step1.js (device selection)
    // - flow-wizard-step2.js (app selection, icon detection, filtering)
    // - flow-wizard-step3.js (recording mode - UI, streaming, gestures)
    // - flow-wizard-step4.js (review & test)
    // - flow-wizard-step5.js (settings & save)


    // ==========================================
    // Step 3 Delegation Wrappers (for backward compatibility)
    // All Step 3 logic moved to flow-wizard-step3.js
    // ==========================================

    async loadStep3() { return await Step3.loadStep3(this); }
    populateAppInfo() { return Step3.populateAppInfo(this); }
    async updateScreenInfo() { return await Step3.updateScreenInfo(this); }
    setupRecordingUI() { return Step3.setupRecordingUI(this); }
    setupPanelTabs() { return Step3.setupPanelTabs(this); }
    switchToTab(tabName) { return Step3.switchToTab(this, tabName); }
    setupToolbarHandlers() { return Step3.setupToolbarHandlers(this); }
    setupPanelToggle() { return Step3.setupPanelToggle(this); }
    toggleRightPanel() { return Step3.toggleRightPanel(this); }
    setupOverlayFilters() { return Step3.setupOverlayFilters(this); }
    setupCaptureMode() { return Step3.setupCaptureMode(this); }
    setCaptureMode(mode) { return Step3.setCaptureMode(this, mode); }
    startStreaming() { return Step3.startStreaming(this); }
    stopStreaming() { return Step3.stopStreaming(this); }
    reconnectStream() { return Step3.reconnectStream(this); }
    startElementAutoRefresh() { return Step3.startElementAutoRefresh(this); }
    stopElementAutoRefresh() { return Step3.stopElementAutoRefresh(this); }
    updateStreamStatus(className, text) { return Step3.updateStreamStatus(this, className, text); }
    async refreshElements() { return await Step3.refreshElements(this); }
    async refreshAfterAction(delayMs) { return await Step3.refreshAfterAction(this, delayMs); }
    setupHoverTooltip() { return Step3.setupHoverTooltip(this); }
    handleCanvasHover(e, hoverTooltip, container) { return Step3.handleCanvasHover(this, e, hoverTooltip, container); }
    showHoverTooltip(e, element, hoverTooltip, container) { return Step3.showHoverTooltip(this, e, element, hoverTooltip, container); }
    updateTooltipPosition(e, hoverTooltip, container) { return Step3.updateTooltipPosition(this, e, hoverTooltip, container); }
    hideHoverTooltip(hoverTooltip) { return Step3.hideHoverTooltip(this, hoverTooltip); }
    highlightHoveredElement(element) { return Step3.highlightHoveredElement(this, element); }
    clearHoverHighlight() { return Step3.clearHoverHighlight(this); }
    onGestureStart(e) { return Step3.onGestureStart(this, e); }
    async onGestureEnd(e) { return await Step3.onGestureEnd(this, e); }
    async executeSwipeGesture(startCanvasX, startCanvasY, endCanvasX, endCanvasY) {
        return await Step3.executeSwipeGesture(this, startCanvasX, startCanvasY, endCanvasX, endCanvasY);
    }
    showTapRipple(container, x, y) { return Step3.showTapRipple(this, container, x, y); }
    showSwipePath(container, startX, startY, endX, endY) {
        return Step3.showSwipePath(this, container, startX, startY, endX, endY);
    }

    // ==========================================
    // Additional Step 3 delegation wrappers
    // ==========================================
    setupElementTree() { return Step3.setupElementTree(this); }
    toggleTreeView(show) { return Step3.toggleTreeView(this, show); }
    handleTreeTap(element) { return Step3.handleTreeTap(this, element); }
    async handleTreeSensor(element) { return await Step3.handleTreeSensor(this, element); }
    updateElementTree(elements) { return Step3.updateElementTree(this, elements); }
    toggleScale() { return Step3.toggleScale(this); }
    zoomIn() { return Step3.zoomIn(this); }
    zoomOut() { return Step3.zoomOut(this); }
    resetZoom() { return Step3.resetZoom(this); }
    updateZoomDisplay(zoomLevel) { return Step3.updateZoomDisplay(this, zoomLevel); }
    fitToScreen() { return Step3.fitToScreen(this); }
    toggleRecording() { return Step3.toggleRecording(this); }
    async handleElementClick(canvasX, canvasY) { return await Step3.handleElementClick(this, canvasX, canvasY); }
    canvasToDevice(canvasX, canvasY) { return Step3.canvasToDevice(this, canvasX, canvasY); }
    async executeTap(x, y, element) { return await Step3.executeTap(this, x, y, element); }
    showTapIndicator(x, y) { return Step3.showTapIndicator(this, x, y); }
    findElementAtCoordinates(x, y) { return Step3.findElementAtCoordinates(this, x, y); }
    async showElementSelectionDialog(element, coords) { return await Step3.showElementSelectionDialog(this, element, coords); }
    async handleRefreshWithRetries() { return await Step3.handleRefreshWithRetries(this); }
    async updateScreenshotDisplay() { return await Step3.updateScreenshotDisplay(this); }
    showLoadingOverlay(text) { return Step3.showLoadingOverlay(this, text); }
    hideLoadingOverlay() { return Step3.hideLoadingOverlay(this); }
    updateElementCount(count) { return Step3.updateElementCount(this, count); }
    updateFlowStepsUI() { return Step3.updateFlowStepsUI(this); }
    async addSensorWithNavigationCheck(sensorStep, skipCheck = false) {
        return await Step3.addSensorWithNavigationCheck(this, sensorStep, skipCheck);
    }
    showPreviewOverlay() { return Step3.showPreviewOverlay(this); }
    hidePreviewOverlay() { return Step3.hidePreviewOverlay(this); }
    async chooseRegularScreenshot() { return await Step3.chooseRegularScreenshot(this); }
    async chooseStitchCapture() { return await Step3.chooseStitchCapture(this); }
    collapseSidebar() { return Step3.collapseSidebar(this); }
    expandSidebar() { return Step3.expandSidebar(this); }
    updateElementPanel(elements) { return Step3.updateElementPanel(this, elements); }
    setupElementFilters() { return Step3.setupElementFilters(this); }
    renderFilteredElements() { return Step3.renderFilteredElements(this); }
    drawElementOverlays() { return Step3.drawElementOverlays(this); }
    drawElementOverlaysScaled(scale) { return Step3.drawElementOverlaysScaled(this, scale); }
    drawTextLabel(text, x, y, w, isClickable) { return Step3.drawTextLabel(this, text, x, y, w, isClickable); }
    setupFlowStepsListener() { return Step3.setupFlowStepsListener(this); }

    // ==========================================
    // Dialog delegation wrappers (for Dialogs module)
    // ==========================================

    async promptForText() {
        return Dialogs.promptForText(this);
    }

    async createTextSensor(element, coords, elementIndex = 0) {
        return Dialogs.createTextSensor(this, element, coords, elementIndex);
    }

    async createImageSensor(element, coords, elementIndex = 0) {
        return Dialogs.createImageSensor(this, element, coords, elementIndex);
    }

    /**
     * Handle sensor created callback - adds capture_sensors step to flow
     * Called by SensorCreator.onSensorCreated callback
     */
    _handleSensorCreated(response, sensorData) {
        return Dialogs.handleSensorCreated(this, response, sensorData);
    }

    /**
     * Show action configuration dialog
     * Returns config object or null if cancelled
     */
    async promptForActionConfig(defaultName, stepCount) {
        return Dialogs.promptForActionConfig(this, defaultName, stepCount);
    }

    async createAction(element, coords) {
        return Dialogs.createAction(this, element, coords);
    }

    async promptForSensorName(defaultName) {
        return Dialogs.promptForSensorName(this, defaultName);
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

        // Add a single wait step representing the total refresh operation (unless recording is paused)
        if (!this.recordingPaused) {
            const totalDuration = (attempts - 1) * delay + 500; // 500ms for screenshot capture
            this.recorder.addStep({
                step_type: 'wait',
                duration: totalDuration,
                refresh_attempts: attempts,
                refresh_delay: delay,
                description: `Wait for UI update (${attempts} refreshes, ${delay}ms delay)`
            });
        }

        showToast(`Completed ${attempts} refresh attempts`, 'success', 2000);
    }

    async updateScreenshotDisplay() {
        const dataUrl = this.recorder.getScreenshotDataUrl();
        const metadata = this.recorder.screenshotMetadata;

        try {
            // Render using canvas renderer module
            const { displayWidth, displayHeight, scale } = await this.canvasRenderer.render(dataUrl, metadata);

            // Store scale for coordinate mapping
            this.currentScale = scale;

            // Update element tree and count if metadata available
            if (metadata && metadata.elements && metadata.elements.length > 0) {
                this.updateElementTree(metadata.elements);
                this.updateElementCount(metadata.elements.length);
            }

            // Phase 1 Screen Awareness: Update screen info after each screenshot
            this.updateScreenInfo();

            // Hide loading overlay
            this.hideLoadingOverlay();

        } catch (error) {
            console.error('[FlowWizard] Failed to render screenshot:', error);
            this.showLoadingOverlay('Error loading screenshot');
        }
    }

    /**
     * Show loading overlay on screenshot
     */
    showLoadingOverlay(text = 'Loading...') {
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
    hideLoadingOverlay() {
        const overlay = document.getElementById('screenshotLoading');
        if (overlay) {
            overlay.classList.remove('visible');
        }
    }

    /**
     * Update element count badge
     */
    updateElementCount(count) {
        const badge = document.getElementById('elementCount');
        if (badge) badge.textContent = count;
    }

    /**
     * Update flow steps count badge
     */
    updateFlowStepsUI() {
        const badge = document.getElementById('stepCount');
        const steps = this.recorder?.getSteps() || [];
        if (badge) badge.textContent = steps.length;

        // Update step manager display
        if (this.stepManager) {
            this.stepManager.render(steps);
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
                        <button class="btn-element-action btn-action" data-index="${index}" title="Execute saved action">
                            ⚡ Action
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

        panel.querySelectorAll('.btn-action').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                this.addActionStepFromElement(interactiveElements[index]);
            });
        });
    }

    /**
     * Add tap step from element (via panel)
     */
    async addTapStepFromElement(element) {
        return ElementActions.addTapStepFromElement(this, element);
    }

    /**
     * Add type step from element (via panel)
     */
    async addTypeStepFromElement(element) {
        return ElementActions.addTypeStepFromElement(this, element);
    }

    /**
     * Add sensor capture from element (via panel)
     */
    async addSensorCaptureFromElement(element, elementIndex) {
        return ElementActions.addSensorCaptureFromElement(this, element, elementIndex);
    }

    /**
     * Add action from recorded steps (via panel)
     */
    async addActionStepFromElement(element) {
        return Dialogs.addActionStepFromElement(this, element);
    }

    /**
     * Show action creation dialog with choice
     */
    async promptForActionCreation(defaultName, stepCount) {
        return Dialogs.promptForActionCreation(this, defaultName, stepCount);
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

    // ==========================================
    // Step 4 Delegation Wrappers (Review & Test)
    // All Step 4 logic moved to flow-wizard-step4.js
    // ==========================================

    removeStepAt(index) { return Step4.removeStepAt(this, index); }
    async testFlow() { return await Step4.testFlow(this); }

    // NOTE: loadStep5() moved to flow-wizard-step5.js
    // NOTE: saveFlow(), showFlowSavedDialog(), formatInterval() moved to flow-wizard-step5.js
}

// Initialize wizard when module loads
const wizard = new FlowWizard();

// Export for debugging
window.flowWizard = wizard;

export default FlowWizard;
