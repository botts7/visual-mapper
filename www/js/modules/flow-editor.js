/**
 * Flow Editor Module
 * Visual Mapper v0.0.6
 *
 * Handles flow editing, step management, and modal interactions.
 */

class FlowEditor {
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api';
        this.flowManager = options.flowManager || window.flowManager;
        this.showToast = options.showToast || console.log;
        this.escapeHtml = options.escapeHtml || this._defaultEscapeHtml;
        this.loadFlows = options.loadFlows || (() => {});
        this.flows = options.flows || [];

        // Editor state
        this.editingFlow = null;
        this.currentEditTab = 'basic';
    }

    /**
     * Open flow for editing
     */
    edit(deviceId, flowId) {
        const flow = this.flows.find(f => f.device_id === deviceId && f.flow_id === flowId);
        if (!flow) {
            this.showToast('Flow not found', 'error');
            return;
        }

        // Store reference for saving
        this.editingFlow = { deviceId, flowId, flow: JSON.parse(JSON.stringify(flow)) };

        // Populate basic form
        const nameInput = document.getElementById('editFlowName') || document.getElementById('editFlowNameInput');
        if (nameInput) nameInput.value = flow.name || '';

        const descInput = document.getElementById('editFlowDescription');
        if (descInput) descInput.value = flow.description || '';

        const intervalInput = document.getElementById('editFlowInterval') || document.getElementById('editUpdateInterval');
        if (intervalInput) intervalInput.value = flow.update_interval_seconds || 60;

        const enabledInput = document.getElementById('editFlowEnabled');
        if (enabledInput) enabledInput.checked = flow.enabled !== false;

        // Populate headless mode options
        const autoWakeInput = document.getElementById('editAutoWakeBefore');
        if (autoWakeInput) autoWakeInput.checked = flow.auto_wake_before !== false;

        const autoSleepInput = document.getElementById('editAutoSleepAfter');
        if (autoSleepInput) autoSleepInput.checked = flow.auto_sleep_after !== false;

        const verifyScreenInput = document.getElementById('editVerifyScreenOn');
        if (verifyScreenInput) verifyScreenInput.checked = flow.verify_screen_on !== false;

        // Populate JSON editor
        const jsonEditor = document.getElementById('editFlowJSON');
        if (jsonEditor) jsonEditor.value = JSON.stringify(flow, null, 2);

        // Update modal title
        const modalTitle = document.getElementById('editFlowName');
        if (modalTitle && modalTitle.tagName === 'SPAN') {
            modalTitle.textContent = flow.name || flowId;
        }

        // Reset to basic tab
        this.currentEditTab = 'basic';
        this._updateTabs('basic');

        // Show modal
        const modal = document.getElementById('editModal');
        if (modal) modal.classList.add('active');
    }

    /**
     * Close editor modal
     */
    close() {
        const modal = document.getElementById('editModal');
        if (modal) modal.classList.remove('active');
        this.editingFlow = null;
        this.currentEditTab = 'basic';
    }

    /**
     * Switch editor tab
     */
    switchTab(tabName) {
        this.currentEditTab = tabName;
        this._updateTabs(tabName);

        if (tabName === 'basic' || tabName === 'steps') {
            this.syncBasicFormFromJSON();
        } else if (tabName === 'advanced' || tabName === 'json') {
            this.syncJSONFromBasicForm();
        }

        if (tabName === 'steps') {
            this.renderSteps();
        }
    }

    _updateTabs(activeTab) {
        // Update tab buttons
        document.querySelectorAll('.modal-tab, .tab, .edit-tabs button').forEach(tab => {
            tab.classList.remove('active');
            if (tab.textContent.toLowerCase().includes(activeTab.toLowerCase())) {
                tab.classList.add('active');
            }
        });

        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });

        const tabId = activeTab === 'basic' ? 'tabBasic' :
                      activeTab === 'steps' ? 'tabSteps' :
                      activeTab === 'advanced' ? 'tabAdvanced' :
                      activeTab === 'json' ? 'jsonEditor' : `tab${activeTab}`;

        const activeContent = document.getElementById(tabId);
        if (activeContent) activeContent.classList.add('active');
    }

    /**
     * Save flow changes
     */
    async save() {
        if (!this.editingFlow) return;

        let updatedFlow;

        try {
            if (this.currentEditTab === 'advanced' || this.currentEditTab === 'json') {
                const jsonText = document.getElementById('editFlowJSON').value;
                updatedFlow = JSON.parse(jsonText);

                if (!updatedFlow.flow_id || !updatedFlow.device_id) {
                    throw new Error('Invalid flow JSON: missing flow_id or device_id');
                }
            } else {
                const nameInput = document.getElementById('editFlowName') || document.getElementById('editFlowNameInput');
                const descInput = document.getElementById('editFlowDescription');
                const intervalInput = document.getElementById('editFlowInterval') || document.getElementById('editUpdateInterval');
                const enabledInput = document.getElementById('editFlowEnabled');

                updatedFlow = {
                    ...this.editingFlow.flow,
                    name: nameInput?.value || this.editingFlow.flow.name,
                    description: descInput?.value || '',
                    update_interval_seconds: parseInt(intervalInput?.value || 60),
                    enabled: enabledInput?.checked !== false
                };

                // Headless mode settings
                const autoWakeInput = document.getElementById('editAutoWakeBefore');
                const autoSleepInput = document.getElementById('editAutoSleepAfter');
                const verifyScreenInput = document.getElementById('editVerifyScreenOn');

                if (autoWakeInput) updatedFlow.auto_wake_before = autoWakeInput.checked;
                if (autoSleepInput) updatedFlow.auto_sleep_after = autoSleepInput.checked;
                if (verifyScreenInput) updatedFlow.verify_screen_on = verifyScreenInput.checked;
            }

            await this.flowManager.updateFlow(this.editingFlow.deviceId, this.editingFlow.flowId, updatedFlow);
            this.showToast('Flow updated successfully', 'success');
            this.close();
            await this.loadFlows();
        } catch (error) {
            if (error instanceof SyntaxError) {
                this.showToast('Invalid JSON: ' + error.message, 'error');
            } else {
                this.showToast('Failed to update flow: ' + error.message, 'error');
            }
        }
    }

    /**
     * Toggle flow enabled status
     */
    async toggleEnabled(deviceId, flowId, enabled) {
        try {
            const flow = this.flows.find(f => f.device_id === deviceId && f.flow_id === flowId);
            if (!flow) return;

            const updatedFlow = { ...flow, enabled };
            await this.flowManager.updateFlow(deviceId, flowId, updatedFlow);

            this.showToast(`Flow ${enabled ? 'enabled' : 'disabled'}`, 'success');
            await this.loadFlows();
        } catch (error) {
            this.showToast(`Failed to toggle flow: ${error.message}`, 'error');
            await this.loadFlows();
        }
    }

    /**
     * Render flow steps in editor
     */
    renderSteps() {
        if (!this.editingFlow) return;

        const stepsContainer = document.getElementById('stepsEditor');
        if (!stepsContainer) return;

        const steps = this.editingFlow.flow.steps || [];

        // Add "Edit in Wizard" button at the top
        let wizardButtonHtml = `
            <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary, #1e293b); border-radius: 8px; border: 1px dashed var(--border-color, #334155);">
                <button type="button" class="btn btn-primary" onclick="window.flowEditor.openInWizard()" style="width: 100%;">
                    🪄 Edit Steps in Visual Wizard
                </button>
                <p style="color: var(--text-secondary, #94a3b8); font-size: 0.8em; margin-top: 8px; text-align: center;">
                    Opens the wizard to add taps, swipes, and sensors by clicking on the screen
                </p>
            </div>
        `;

        if (steps.length === 0) {
            stepsContainer.innerHTML = wizardButtonHtml + '<p style="text-align:center;color:#64748b;">No steps defined yet. Use the Visual Wizard or click "+ Add Step" below.</p>';
            return;
        }

        stepsContainer.innerHTML = wizardButtonHtml + steps.map((step, index) => `
            <div class="step-card" data-step-index="${index}">
                <div class="step-card-header">
                    <span class="step-type-badge">${step.step_type || 'unknown'}</span>
                    <div class="step-actions">
                        <button type="button" class="step-action-btn" onclick="window.flowEditor.moveStepUp(${index})" ${index === 0 ? 'disabled' : ''}>Up</button>
                        <button type="button" class="step-action-btn" onclick="window.flowEditor.moveStepDown(${index})" ${index === steps.length - 1 ? 'disabled' : ''}>Down</button>
                        <button type="button" class="step-action-btn" onclick="window.flowEditor.deleteStep(${index})">X</button>
                    </div>
                </div>
                <div class="step-fields">
                    ${this._renderStepFields(step, index)}
                </div>
            </div>
        `).join('');
    }

    _renderStepFields(step, index) {
        const stepType = step.step_type;
        let fields = `
            <div class="step-field" style="grid-column: 1 / -1">
                <label>Description</label>
                <input type="text" value="${this.escapeHtml(step.description || '')}"
                       onchange="window.flowEditor.updateStepField(${index}, 'description', this.value)">
            </div>
        `;

        if (stepType === 'tap') {
            fields += `
                <div class="step-field">
                    <label>X Coordinate</label>
                    <input type="number" value="${step.x || ''}"
                           onchange="window.flowEditor.updateStepField(${index}, 'x', parseInt(this.value))">
                </div>
                <div class="step-field">
                    <label>Y Coordinate</label>
                    <input type="number" value="${step.y || ''}"
                           onchange="window.flowEditor.updateStepField(${index}, 'y', parseInt(this.value))">
                </div>
            `;
        } else if (stepType === 'swipe') {
            fields += `
                <div class="step-field"><label>Start X</label>
                    <input type="number" value="${step.start_x || ''}"
                           onchange="window.flowEditor.updateStepField(${index}, 'start_x', parseInt(this.value))"></div>
                <div class="step-field"><label>Start Y</label>
                    <input type="number" value="${step.start_y || ''}"
                           onchange="window.flowEditor.updateStepField(${index}, 'start_y', parseInt(this.value))"></div>
                <div class="step-field"><label>End X</label>
                    <input type="number" value="${step.end_x || ''}"
                           onchange="window.flowEditor.updateStepField(${index}, 'end_x', parseInt(this.value))"></div>
                <div class="step-field"><label>End Y</label>
                    <input type="number" value="${step.end_y || ''}"
                           onchange="window.flowEditor.updateStepField(${index}, 'end_y', parseInt(this.value))"></div>
                <div class="step-field"><label>Duration (ms)</label>
                    <input type="number" value="${step.duration || 500}"
                           onchange="window.flowEditor.updateStepField(${index}, 'duration', parseInt(this.value))"></div>
            `;
        } else if (stepType === 'type_text') {
            fields += `
                <div class="step-field" style="grid-column: 1 / -1">
                    <label>Text to Type</label>
                    <input type="text" value="${this.escapeHtml(step.text || '')}"
                           onchange="window.flowEditor.updateStepField(${index}, 'text', this.value)">
                </div>
            `;
        } else if (stepType === 'wait') {
            fields += `
                <div class="step-field">
                    <label>Duration (seconds)</label>
                    <input type="number" step="0.1" value="${step.duration || 1}"
                           onchange="window.flowEditor.updateStepField(${index}, 'duration', parseFloat(this.value))">
                </div>
            `;
        } else if (stepType === 'launch_app') {
            fields += `
                <div class="step-field" style="grid-column: 1 / -1">
                    <label>Package Name</label>
                    <input type="text" value="${this.escapeHtml(step.package || '')}"
                           onchange="window.flowEditor.updateStepField(${index}, 'package', this.value)">
                </div>
            `;
        } else if (stepType === 'capture_sensors') {
            fields += `
                <div class="step-field" style="grid-column: 1 / -1">
                    <label>Sensor IDs (comma-separated)</label>
                    <input type="text" value="${(step.sensor_ids || []).join(', ')}"
                           onchange="window.flowEditor.updateStepField(${index}, 'sensor_ids', this.value.split(',').map(s => s.trim()).filter(s => s))">
                </div>
            `;
        }

        return fields;
    }

    updateStepField(stepIndex, field, value) {
        if (!this.editingFlow) return;
        this.editingFlow.flow.steps[stepIndex][field] = value;
    }

    deleteStep(stepIndex) {
        if (!this.editingFlow) return;
        if (!confirm('Delete this step?')) return;
        this.editingFlow.flow.steps.splice(stepIndex, 1);
        this.renderSteps();
    }

    moveStepUp(stepIndex) {
        if (!this.editingFlow || stepIndex === 0) return;
        const steps = this.editingFlow.flow.steps;
        [steps[stepIndex - 1], steps[stepIndex]] = [steps[stepIndex], steps[stepIndex - 1]];
        this.renderSteps();
    }

    moveStepDown(stepIndex) {
        if (!this.editingFlow) return;
        const steps = this.editingFlow.flow.steps;
        if (stepIndex === steps.length - 1) return;
        [steps[stepIndex], steps[stepIndex + 1]] = [steps[stepIndex + 1], steps[stepIndex]];
        this.renderSteps();
    }

    /**
     * Open flow in Visual Wizard for visual step editing
     * Allows adding taps, swipes, etc. by clicking on the screen
     */
    openInWizard() {
        if (!this.editingFlow) {
            this.showToast('No flow selected for editing', 'error');
            return;
        }

        const { deviceId, flowId } = this.editingFlow;

        // Close the modal
        this.close();

        // Navigate to wizard with flow edit params
        const wizardUrl = `flow-wizard.html?editFlow=true&device=${encodeURIComponent(deviceId)}&flow=${encodeURIComponent(flowId)}`;
        window.location.href = wizardUrl;
    }

    addNewStep() {
        if (!this.editingFlow) return;

        const stepType = prompt('Enter step type (tap, swipe, type_text, wait, launch_app, capture_sensors, keypress):');
        if (!stepType) return;

        const newStep = {
            step_type: stepType,
            description: `New ${stepType} step`,
            retry_on_failure: false,
            max_retries: 3
        };

        // Initialize type-specific fields
        if (stepType === 'tap') { newStep.x = 0; newStep.y = 0; }
        else if (stepType === 'swipe') { newStep.start_x = 0; newStep.start_y = 0; newStep.end_x = 0; newStep.end_y = 0; newStep.duration = 500; }
        else if (stepType === 'type_text') { newStep.text = ''; }
        else if (stepType === 'wait') { newStep.duration = 1; }
        else if (stepType === 'launch_app') { newStep.package = ''; }
        else if (stepType === 'capture_sensors') { newStep.sensor_ids = []; }

        this.editingFlow.flow.steps.push(newStep);
        this.renderSteps();
    }

    syncJSONFromBasicForm() {
        if (!this.editingFlow) return;

        const nameInput = document.getElementById('editFlowName') || document.getElementById('editFlowNameInput');
        const descInput = document.getElementById('editFlowDescription');
        const intervalInput = document.getElementById('editFlowInterval') || document.getElementById('editUpdateInterval');
        const enabledInput = document.getElementById('editFlowEnabled');

        const updatedFlow = {
            ...this.editingFlow.flow,
            name: nameInput?.value || this.editingFlow.flow.name,
            description: descInput?.value || '',
            update_interval_seconds: parseInt(intervalInput?.value || 60),
            enabled: enabledInput?.checked !== false
        };

        const jsonEditor = document.getElementById('editFlowJSON');
        if (jsonEditor) jsonEditor.value = JSON.stringify(updatedFlow, null, 2);
    }

    syncBasicFormFromJSON() {
        if (!this.editingFlow) return;

        try {
            const jsonEditor = document.getElementById('editFlowJSON');
            if (!jsonEditor) return;

            const flowData = JSON.parse(jsonEditor.value);
            this.editingFlow.flow = flowData;

            const nameInput = document.getElementById('editFlowName') || document.getElementById('editFlowNameInput');
            const descInput = document.getElementById('editFlowDescription');
            const intervalInput = document.getElementById('editFlowInterval') || document.getElementById('editUpdateInterval');
            const enabledInput = document.getElementById('editFlowEnabled');

            if (nameInput) nameInput.value = flowData.name || '';
            if (descInput) descInput.value = flowData.description || '';
            if (intervalInput) intervalInput.value = flowData.update_interval_seconds || 60;
            if (enabledInput) enabledInput.checked = flowData.enabled !== false;
        } catch (error) {
            console.warn('Failed to sync basic form from JSON:', error);
        }
    }

    // Default utility method
    _defaultEscapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// ES6 export
export default FlowEditor;

// Global export for backward compatibility
window.FlowEditor = FlowEditor;
