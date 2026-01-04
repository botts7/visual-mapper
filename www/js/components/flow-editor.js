/**
 * FlowEditor Component
 * Visual Mapper v0.0.5
 *
 * Reusable component for editing a complete flow (name, description, steps list).
 * Uses ActionConfigurator for individual step configuration.
 */

import { ActionConfigurator } from './action-configurator.js?v=0.0.5';

/**
 * FlowEditor class
 * Manages the entire flow editing form including metadata and steps
 */
export class FlowEditor {
    /**
     * @param {Object} options - Configuration options
     * @param {string} options.apiBase - API base URL (default: '/api')
     * @param {string} options.deviceId - Device ID for the flow
     * @param {Function} options.onCoordinatePick - Callback for coordinate picker
     * @param {Function} options.onChange - Callback when flow data changes
     */
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api';
        this.deviceId = options.deviceId || null;
        this.onCoordinatePick = options.onCoordinatePick || null;
        this.onChange = options.onChange || null;

        this.container = null;
        this.flowData = {};
        this.steps = [];
        this.stepConfigurators = [];

        this._draggedIndex = null;
    }

    /**
     * Render the complete flow editor
     * @param {HTMLElement} container - Container element
     * @param {Object} flowData - Existing flow data for editing
     */
    async render(container, flowData = {}) {
        this.container = container;
        this.flowData = { ...flowData };
        this.steps = [...(flowData.steps || [])];

        container.innerHTML = `
            <div class="flow-editor">
                <!-- Flow Metadata -->
                <div class="flow-metadata-section">
                    <h3>Flow Details</h3>

                    <div class="form-group">
                        <label for="flow-name">Flow Name *</label>
                        <input type="text" id="flow-name" name="name"
                               value="${flowData.name || ''}"
                               placeholder="My Collection Flow"
                               class="form-input" required>
                    </div>

                    <div class="form-group">
                        <label for="flow-description">Description</label>
                        <textarea id="flow-description" name="description"
                                  placeholder="What does this flow do?"
                                  class="form-input">${flowData.description || ''}</textarea>
                    </div>

                    <div class="form-row">
                        <div class="form-group">
                            <label for="flow-interval">Update Interval (seconds)</label>
                            <input type="number" id="flow-interval" name="update_interval_seconds"
                                   value="${flowData.update_interval_seconds || 60}"
                                   min="5" max="3600"
                                   class="form-input">
                        </div>

                        <div class="form-group">
                            <label for="flow-timeout">Flow Timeout (seconds)</label>
                            <input type="number" id="flow-timeout" name="flow_timeout"
                                   value="${flowData.flow_timeout || 60}"
                                   min="10" max="300"
                                   class="form-input">
                        </div>
                    </div>

                    <div class="form-group">
                        <label class="checkbox-label">
                            <input type="checkbox" id="flow-enabled" name="enabled"
                                   ${flowData.enabled !== false ? 'checked' : ''}>
                            <span>Flow Enabled</span>
                        </label>
                    </div>

                    <div class="form-group">
                        <label class="checkbox-label">
                            <input type="checkbox" id="flow-stop-on-error" name="stop_on_error"
                                   ${flowData.stop_on_error ? 'checked' : ''}>
                            <span>Stop on Error</span>
                        </label>
                    </div>
                </div>

                <!-- Steps Section -->
                <div class="flow-steps-section">
                    <div class="steps-header">
                        <h3>Flow Steps</h3>
                        <button type="button" class="btn btn-primary add-step-btn">
                            + Add Step
                        </button>
                    </div>

                    <div class="steps-list" id="flow-steps-list">
                        ${this.steps.length === 0 ? '<p class="no-steps">No steps yet. Click "Add Step" to begin.</p>' : ''}
                    </div>
                </div>

                <!-- Step Type Selector (hidden by default) -->
                <div class="step-type-selector hidden" id="step-type-selector">
                    <div class="selector-overlay"></div>
                    <div class="selector-content">
                        <h4>Select Step Type</h4>
                        <div class="step-types-grid">
                            ${ActionConfigurator.getStepTypes().map(st => `
                                <button type="button" class="step-type-btn" data-type="${st.type}">
                                    <span class="step-type-icon">${st.icon}</span>
                                    <span class="step-type-label">${st.label}</span>
                                </button>
                            `).join('')}
                        </div>
                        <button type="button" class="btn btn-secondary cancel-selector-btn">Cancel</button>
                    </div>
                </div>
            </div>
        `;

        // Render existing steps
        await this._renderSteps();

        // Bind events
        this._bindEvents();

        // Apply styles
        this._applyStyles();
    }

    /**
     * Render all steps
     * @private
     */
    async _renderSteps() {
        const listEl = this.container.querySelector('#flow-steps-list');
        if (!listEl) return;

        if (this.steps.length === 0) {
            listEl.innerHTML = '<p class="no-steps">No steps yet. Click "Add Step" to begin.</p>';
            return;
        }

        listEl.innerHTML = '';
        this.stepConfigurators = [];

        for (let i = 0; i < this.steps.length; i++) {
            const step = this.steps[i];
            const stepEl = await this._createStepElement(step, i);
            listEl.appendChild(stepEl);
        }
    }

    /**
     * Create a step element with configurator
     * @private
     */
    async _createStepElement(step, index) {
        const stepConfig = ActionConfigurator.getStepConfig(step.step_type);
        const icon = stepConfig?.icon || '❓';
        const label = stepConfig?.label || step.step_type;

        const stepEl = document.createElement('div');
        stepEl.className = 'step-item';
        stepEl.dataset.index = index;
        stepEl.draggable = true;

        stepEl.innerHTML = `
            <div class="step-header">
                <span class="step-drag-handle">≡</span>
                <span class="step-number">${index + 1}</span>
                <span class="step-icon">${icon}</span>
                <span class="step-label">${label}</span>
                <span class="step-desc">${step.description || ''}</span>
                <div class="step-actions">
                    <button type="button" class="btn-icon expand-step-btn" title="Expand/Collapse">
                        ▼
                    </button>
                    <button type="button" class="btn-icon delete-step-btn" title="Delete Step">
                        🗑️
                    </button>
                </div>
            </div>
            <div class="step-config-container collapsed">
                <div class="step-config-content"></div>
            </div>
        `;

        // Create configurator for this step
        const configurator = new ActionConfigurator({
            apiBase: this.apiBase,
            deviceId: this.deviceId,
            onCoordinatePick: this.onCoordinatePick
        });

        const contentEl = stepEl.querySelector('.step-config-content');
        await configurator.render(contentEl, step.step_type, step);

        this.stepConfigurators[index] = configurator;

        // Bind step events
        this._bindStepEvents(stepEl, index);

        return stepEl;
    }

    /**
     * Bind events for a step element
     * @private
     */
    _bindStepEvents(stepEl, index) {
        // Expand/collapse
        const expandBtn = stepEl.querySelector('.expand-step-btn');
        const configContainer = stepEl.querySelector('.step-config-container');

        expandBtn.addEventListener('click', () => {
            configContainer.classList.toggle('collapsed');
            expandBtn.textContent = configContainer.classList.contains('collapsed') ? '▼' : '▲';
        });

        // Delete
        stepEl.querySelector('.delete-step-btn').addEventListener('click', () => {
            this.removeStep(index);
        });

        // Drag events
        stepEl.addEventListener('dragstart', (e) => {
            this._draggedIndex = index;
            stepEl.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
        });

        stepEl.addEventListener('dragend', () => {
            stepEl.classList.remove('dragging');
            this._draggedIndex = null;
        });

        stepEl.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';

            const targetIndex = parseInt(stepEl.dataset.index);
            if (this._draggedIndex !== null && this._draggedIndex !== targetIndex) {
                stepEl.classList.add('drag-over');
            }
        });

        stepEl.addEventListener('dragleave', () => {
            stepEl.classList.remove('drag-over');
        });

        stepEl.addEventListener('drop', (e) => {
            e.preventDefault();
            stepEl.classList.remove('drag-over');

            const targetIndex = parseInt(stepEl.dataset.index);
            if (this._draggedIndex !== null && this._draggedIndex !== targetIndex) {
                this.reorderSteps(this._draggedIndex, targetIndex);
            }
        });
    }

    /**
     * Bind main editor events
     * @private
     */
    _bindEvents() {
        // Add step button
        this.container.querySelector('.add-step-btn').addEventListener('click', () => {
            this._showStepTypeSelector();
        });

        // Step type selector
        const selector = this.container.querySelector('#step-type-selector');

        selector.querySelector('.selector-overlay').addEventListener('click', () => {
            this._hideStepTypeSelector();
        });

        selector.querySelector('.cancel-selector-btn').addEventListener('click', () => {
            this._hideStepTypeSelector();
        });

        selector.querySelectorAll('.step-type-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const stepType = btn.dataset.type;
                this._hideStepTypeSelector();
                this.addStep(stepType);
            });
        });

        // Track changes on metadata inputs
        const inputs = this.container.querySelectorAll('.flow-metadata-section input, .flow-metadata-section textarea');
        inputs.forEach(input => {
            input.addEventListener('change', () => this._notifyChange());
        });
    }

    /**
     * Show step type selector
     * @private
     */
    _showStepTypeSelector() {
        this.container.querySelector('#step-type-selector').classList.remove('hidden');
    }

    /**
     * Hide step type selector
     * @private
     */
    _hideStepTypeSelector() {
        this.container.querySelector('#step-type-selector').classList.add('hidden');
    }

    /**
     * Add a new step
     * @param {string} stepType - Type of step to add
     */
    async addStep(stepType) {
        const newStep = { step_type: stepType };
        this.steps.push(newStep);

        await this._renderSteps();
        this._notifyChange();

        // Scroll to new step and expand it
        const listEl = this.container.querySelector('#flow-steps-list');
        const lastStep = listEl.lastElementChild;
        if (lastStep) {
            lastStep.scrollIntoView({ behavior: 'smooth', block: 'center' });

            // Auto-expand the new step
            const expandBtn = lastStep.querySelector('.expand-step-btn');
            const configContainer = lastStep.querySelector('.step-config-container');
            if (expandBtn && configContainer) {
                configContainer.classList.remove('collapsed');
                expandBtn.textContent = '▲';
            }
        }
    }

    /**
     * Remove a step
     * @param {number} index - Step index to remove
     */
    async removeStep(index) {
        if (index < 0 || index >= this.steps.length) return;

        this.steps.splice(index, 1);
        this.stepConfigurators.splice(index, 1);

        await this._renderSteps();
        this._notifyChange();
    }

    /**
     * Reorder steps
     * @param {number} fromIndex - Source index
     * @param {number} toIndex - Destination index
     */
    async reorderSteps(fromIndex, toIndex) {
        if (fromIndex < 0 || fromIndex >= this.steps.length) return;
        if (toIndex < 0 || toIndex >= this.steps.length) return;

        // Get current data from configurators before reordering
        this._syncStepsFromConfigurators();

        // Move the step
        const [movedStep] = this.steps.splice(fromIndex, 1);
        this.steps.splice(toIndex, 0, movedStep);

        await this._renderSteps();
        this._notifyChange();
    }

    /**
     * Sync steps array from configurators
     * @private
     */
    _syncStepsFromConfigurators() {
        for (let i = 0; i < this.stepConfigurators.length; i++) {
            if (this.stepConfigurators[i]) {
                try {
                    this.steps[i] = this.stepConfigurators[i].getData();
                } catch {
                    // Keep existing data if configurator fails
                }
            }
        }
    }

    /**
     * Get the complete flow data
     * @returns {Object} Complete flow object
     */
    getData() {
        // Sync steps from configurators
        this._syncStepsFromConfigurators();

        // Get metadata
        const name = this.container.querySelector('#flow-name')?.value.trim() || '';
        const description = this.container.querySelector('#flow-description')?.value.trim() || null;
        const updateInterval = parseInt(this.container.querySelector('#flow-interval')?.value) || 60;
        const flowTimeout = parseInt(this.container.querySelector('#flow-timeout')?.value) || 60;
        const enabled = this.container.querySelector('#flow-enabled')?.checked ?? true;
        const stopOnError = this.container.querySelector('#flow-stop-on-error')?.checked ?? false;

        return {
            ...this.flowData,
            name,
            description,
            update_interval_seconds: updateInterval,
            flow_timeout: flowTimeout,
            enabled,
            stop_on_error: stopOnError,
            steps: this.steps
        };
    }

    /**
     * Validate the entire flow
     * @returns {Object} Validated flow data
     * @throws {Error} If validation fails
     */
    validate() {
        const errors = [];

        // Validate metadata
        const name = this.container.querySelector('#flow-name')?.value.trim();
        if (!name) {
            errors.push('Flow name is required');
        }

        const updateInterval = parseInt(this.container.querySelector('#flow-interval')?.value);
        if (isNaN(updateInterval) || updateInterval < 5 || updateInterval > 3600) {
            errors.push('Update interval must be between 5 and 3600 seconds');
        }

        const flowTimeout = parseInt(this.container.querySelector('#flow-timeout')?.value);
        if (isNaN(flowTimeout) || flowTimeout < 10 || flowTimeout > 300) {
            errors.push('Flow timeout must be between 10 and 300 seconds');
        }

        // Validate steps
        if (this.steps.length === 0) {
            errors.push('Flow must have at least one step');
        }

        const validatedSteps = [];
        for (let i = 0; i < this.stepConfigurators.length; i++) {
            try {
                const stepData = this.stepConfigurators[i].validate();
                validatedSteps.push(stepData);
            } catch (error) {
                errors.push(`Step ${i + 1}: ${error.message}`);
            }
        }

        if (errors.length > 0) {
            throw new Error(errors.join('\n'));
        }

        // Return validated data
        return {
            ...this.flowData,
            name,
            description: this.container.querySelector('#flow-description')?.value.trim() || null,
            update_interval_seconds: updateInterval,
            flow_timeout: flowTimeout,
            enabled: this.container.querySelector('#flow-enabled')?.checked ?? true,
            stop_on_error: this.container.querySelector('#flow-stop-on-error')?.checked ?? false,
            steps: validatedSteps
        };
    }

    /**
     * Notify change callback
     * @private
     */
    _notifyChange() {
        if (this.onChange) {
            this.onChange(this.getData());
        }
    }

    /**
     * Apply component styles
     * @private
     */
    _applyStyles() {
        if (document.getElementById('flow-editor-styles')) return;

        const style = document.createElement('style');
        style.id = 'flow-editor-styles';
        style.textContent = `
            .flow-editor {
                font-family: inherit;
            }

            .flow-metadata-section,
            .flow-steps-section {
                background: var(--card-background, #1e1e1e);
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 20px;
            }

            .flow-metadata-section h3,
            .flow-steps-section h3 {
                margin: 0 0 16px 0;
                color: var(--text-color, #e0e0e0);
            }

            .form-row {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 16px;
            }

            .checkbox-label {
                display: flex;
                align-items: center;
                gap: 8px;
                cursor: pointer;
            }

            .checkbox-label input {
                accent-color: var(--primary-color, #2196F3);
            }

            .steps-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 16px;
            }

            .steps-header h3 {
                margin: 0;
            }

            .steps-list {
                min-height: 100px;
            }

            .no-steps {
                color: var(--text-secondary, #888);
                text-align: center;
                padding: 40px;
                font-style: italic;
            }

            /* Step Item */
            .step-item {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid var(--border-color, #333);
                border-radius: 8px;
                margin-bottom: 12px;
                overflow: hidden;
            }

            .step-item.dragging {
                opacity: 0.5;
            }

            .step-item.drag-over {
                border-color: var(--primary-color, #2196F3);
                border-style: dashed;
            }

            .step-header {
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 12px 16px;
                background: rgba(0, 0, 0, 0.2);
                cursor: grab;
            }

            .step-drag-handle {
                font-size: 18px;
                color: var(--text-secondary, #888);
                cursor: grab;
            }

            .step-number {
                background: var(--primary-color, #2196F3);
                color: white;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                font-weight: bold;
            }

            .step-icon {
                font-size: 20px;
            }

            .step-label {
                font-weight: 600;
            }

            .step-desc {
                flex: 1;
                color: var(--text-secondary, #888);
                font-size: 13px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .step-actions {
                display: flex;
                gap: 8px;
            }

            .btn-icon {
                background: none;
                border: none;
                cursor: pointer;
                font-size: 16px;
                padding: 4px 8px;
                border-radius: 4px;
            }

            .btn-icon:hover {
                background: rgba(255, 255, 255, 0.1);
            }

            .step-config-container {
                transition: max-height 0.3s ease;
                max-height: 500px;
                overflow: hidden;
            }

            .step-config-container.collapsed {
                max-height: 0;
            }

            .step-config-content {
                padding: 0 16px 16px;
            }

            /* Step Type Selector */
            .step-type-selector {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                z-index: 1000;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .step-type-selector.hidden {
                display: none;
            }

            .selector-overlay {
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
            }

            .selector-content {
                position: relative;
                background: var(--card-background, #1e1e1e);
                border-radius: 12px;
                padding: 24px;
                max-width: 600px;
                width: 90%;
                max-height: 80vh;
                overflow-y: auto;
            }

            .selector-content h4 {
                margin: 0 0 16px 0;
            }

            .step-types-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
                gap: 12px;
                margin-bottom: 20px;
            }

            .step-type-btn {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 8px;
                padding: 16px;
                border: 2px solid var(--border-color, #333);
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.05);
                cursor: pointer;
                transition: all 0.2s;
            }

            .step-type-btn:hover {
                border-color: var(--primary-color, #2196F3);
                background: rgba(33, 150, 243, 0.1);
            }

            .step-type-icon {
                font-size: 28px;
            }

            .step-type-label {
                font-size: 12px;
                font-weight: 500;
                text-align: center;
            }

            .cancel-selector-btn {
                width: 100%;
            }
        `;
        document.head.appendChild(style);
    }
}

// Dual export pattern: ES6 export + window global
window.FlowEditor = FlowEditor;

export default FlowEditor;
