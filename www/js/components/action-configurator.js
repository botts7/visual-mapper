/**
 * ActionConfigurator Component
 * Visual Mapper v0.0.5
 *
 * Reusable component for configuring a SINGLE flow action/step.
 * Supports all step types from flow_models.py:
 *   tap, swipe, text, wait, launch_app, keyevent, go_home, go_back,
 *   capture_sensors, screenshot, execute_action, loop, etc.
 */

/**
 * Step type configurations with form field definitions
 */
const STEP_CONFIGS = {
    tap: {
        label: 'Tap',
        icon: '👆',
        fields: [
            { name: 'x', label: 'X Coordinate', type: 'number', required: true, min: 0 },
            { name: 'y', label: 'Y Coordinate', type: 'number', required: true, min: 0 }
        ]
    },
    swipe: {
        label: 'Swipe',
        icon: '👉',
        fields: [
            { name: 'start_x', label: 'Start X', type: 'number', required: true, min: 0 },
            { name: 'start_y', label: 'Start Y', type: 'number', required: true, min: 0 },
            { name: 'end_x', label: 'End X', type: 'number', required: true, min: 0 },
            { name: 'end_y', label: 'End Y', type: 'number', required: true, min: 0 }
        ]
    },
    text: {
        label: 'Type Text',
        icon: '⌨️',
        fields: [
            { name: 'text', label: 'Text to Type', type: 'text', required: true, placeholder: 'Enter text...' }
        ]
    },
    wait: {
        label: 'Wait/Delay',
        icon: '⏱️',
        fields: [
            { name: 'duration', label: 'Duration (ms)', type: 'number', required: true, min: 100, max: 60000, default: 1000 }
        ]
    },
    launch_app: {
        label: 'Launch App',
        icon: '🚀',
        fields: [
            { name: 'package', label: 'Package Name', type: 'text', required: true, placeholder: 'com.example.app' }
        ]
    },
    keyevent: {
        label: 'Key Event',
        icon: '🔘',
        fields: [
            { name: 'keycode', label: 'Keycode', type: 'select', required: true, options: [
                { value: '3', label: 'Home (3)' },
                { value: '4', label: 'Back (4)' },
                { value: '24', label: 'Volume Up (24)' },
                { value: '25', label: 'Volume Down (25)' },
                { value: '26', label: 'Power (26)' },
                { value: '66', label: 'Enter (66)' },
                { value: '82', label: 'Menu (82)' },
                { value: '187', label: 'App Switch (187)' }
            ]}
        ]
    },
    go_home: {
        label: 'Go Home',
        icon: '🏠',
        fields: []  // No configuration needed
    },
    go_back: {
        label: 'Go Back',
        icon: '⬅️',
        fields: []  // No configuration needed
    },
    capture_sensors: {
        label: 'Capture Sensors',
        icon: '📊',
        fields: [
            { name: 'sensor_ids', label: 'Sensor IDs', type: 'multiselect', required: true, placeholder: 'Select sensors...' }
        ]
    },
    screenshot: {
        label: 'Take Screenshot',
        icon: '📸',
        fields: []  // No configuration needed
    },
    execute_action: {
        label: 'Execute Action',
        icon: '⚡',
        fields: [
            { name: 'action_id', label: 'Action', type: 'select', required: true, placeholder: 'Select action...' }
        ]
    },
    loop: {
        label: 'Loop',
        icon: '🔁',
        fields: [
            { name: 'iterations', label: 'Iterations', type: 'number', required: true, min: 1, max: 100, default: 3 },
            { name: 'loop_variable', label: 'Loop Variable (optional)', type: 'text', required: false, placeholder: 'i' }
        ]
    },
    pull_refresh: {
        label: 'Pull to Refresh',
        icon: '🔄',
        fields: []  // No configuration needed
    },
    restart_app: {
        label: 'Restart App',
        icon: '♻️',
        fields: [
            { name: 'package', label: 'Package Name', type: 'text', required: true, placeholder: 'com.example.app' }
        ]
    },
    validate_screen: {
        label: 'Validate Screen',
        icon: '✅',
        fields: [
            { name: 'validation_element', label: 'Validation Element', type: 'json', required: true, placeholder: '{"text": "Expected Text"}' }
        ]
    },
    set_variable: {
        label: 'Set Variable',
        icon: '📝',
        fields: [
            { name: 'variable_name', label: 'Variable Name', type: 'text', required: true, placeholder: 'myVar' },
            { name: 'variable_value', label: 'Value', type: 'text', required: true, placeholder: 'value or ${ref}' }
        ]
    }
};

/**
 * ActionConfigurator class
 * Renders and manages form for a single action/step configuration
 */
export class ActionConfigurator {
    /**
     * @param {Object} options - Configuration options
     * @param {string} options.apiBase - API base URL (default: '/api')
     * @param {string} options.deviceId - Device ID for loading sensors/actions
     * @param {Function} options.onCoordinatePick - Callback for coordinate picker (x, y) => void
     */
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api';
        this.deviceId = options.deviceId || null;
        this.onCoordinatePick = options.onCoordinatePick || null;

        this.container = null;
        this.currentType = null;
        this.currentData = {};
        this.sensors = [];
        this.actions = [];
    }

    /**
     * Render the configuration form for a step type
     * @param {HTMLElement} container - Container element
     * @param {string} stepType - Step type (tap, swipe, wait, etc.)
     * @param {Object} existingData - Existing data for editing
     */
    async render(container, stepType, existingData = {}) {
        this.container = container;
        this.currentType = stepType;
        this.currentData = { ...existingData };

        const config = STEP_CONFIGS[stepType];
        if (!config) {
            container.innerHTML = `<p class="error">Unknown step type: ${stepType}</p>`;
            return;
        }

        // Load sensors/actions if needed
        if (stepType === 'capture_sensors' && this.deviceId) {
            await this._loadSensors();
        }
        if (stepType === 'execute_action' && this.deviceId) {
            await this._loadActions();
        }

        // Build form HTML
        let formHtml = `
            <div class="action-config-form" data-step-type="${stepType}">
                <div class="action-config-header">
                    <span class="action-icon">${config.icon}</span>
                    <span class="action-label">${config.label}</span>
                </div>
        `;

        if (config.fields.length === 0) {
            formHtml += `
                <p class="no-config-needed">No configuration needed for this step.</p>
            `;
        } else {
            for (const field of config.fields) {
                formHtml += this._renderField(field, existingData[field.name]);
            }
        }

        // Description field (always available)
        formHtml += `
            <div class="form-group">
                <label for="action-description">Description (optional)</label>
                <input type="text" id="action-description" name="description"
                       value="${existingData.description || ''}"
                       placeholder="Describe this step..."
                       class="form-input">
            </div>
        `;

        formHtml += '</div>';

        container.innerHTML = formHtml;

        // Add coordinate picker buttons for tap/swipe
        if ((stepType === 'tap' || stepType === 'swipe') && this.onCoordinatePick) {
            this._addCoordinatePickers();
        }

        // Apply styles
        this._applyStyles();
    }

    /**
     * Render a single form field
     * @private
     */
    _renderField(field, value) {
        const id = `action-field-${field.name}`;
        const displayValue = value !== undefined ? value : (field.default || '');
        const required = field.required ? 'required' : '';

        let inputHtml = '';

        switch (field.type) {
            case 'number':
                inputHtml = `
                    <input type="number" id="${id}" name="${field.name}"
                           value="${displayValue}"
                           ${field.min !== undefined ? `min="${field.min}"` : ''}
                           ${field.max !== undefined ? `max="${field.max}"` : ''}
                           class="form-input" ${required}>
                `;
                break;

            case 'text':
                inputHtml = `
                    <input type="text" id="${id}" name="${field.name}"
                           value="${displayValue}"
                           placeholder="${field.placeholder || ''}"
                           class="form-input" ${required}>
                `;
                break;

            case 'select':
                let options = field.options || [];

                // For action_id, use loaded actions
                if (field.name === 'action_id') {
                    options = this.actions.map(a => ({
                        value: a.id,
                        label: a.action?.name || a.id
                    }));
                }

                inputHtml = `
                    <select id="${id}" name="${field.name}" class="form-input" ${required}>
                        <option value="">${field.placeholder || 'Select...'}</option>
                        ${options.map(opt => `
                            <option value="${opt.value}" ${displayValue == opt.value ? 'selected' : ''}>
                                ${opt.label}
                            </option>
                        `).join('')}
                    </select>
                `;
                break;

            case 'multiselect':
                // For sensor_ids, render checkboxes
                if (field.name === 'sensor_ids') {
                    const selectedIds = Array.isArray(displayValue) ? displayValue : [];
                    inputHtml = `
                        <div id="${id}" class="multiselect-container">
                            ${this.sensors.length === 0 ? '<p class="no-items">No sensors available</p>' :
                              this.sensors.map(s => `
                                <label class="multiselect-item">
                                    <input type="checkbox" name="${field.name}"
                                           value="${s.sensor_id}"
                                           ${selectedIds.includes(s.sensor_id) ? 'checked' : ''}>
                                    <span>${s.friendly_name}</span>
                                </label>
                              `).join('')}
                        </div>
                    `;
                }
                break;

            case 'json':
                const jsonValue = typeof displayValue === 'object' ?
                    JSON.stringify(displayValue, null, 2) : (displayValue || '');
                inputHtml = `
                    <textarea id="${id}" name="${field.name}"
                              placeholder="${field.placeholder || '{}'}"
                              class="form-input form-textarea" ${required}>${jsonValue}</textarea>
                `;
                break;

            default:
                inputHtml = `
                    <input type="text" id="${id}" name="${field.name}"
                           value="${displayValue}"
                           class="form-input" ${required}>
                `;
        }

        return `
            <div class="form-group" data-field="${field.name}">
                <label for="${id}">${field.label}${field.required ? ' *' : ''}</label>
                ${inputHtml}
            </div>
        `;
    }

    /**
     * Add coordinate picker buttons for tap/swipe fields
     * @private
     */
    _addCoordinatePickers() {
        const fields = this.currentType === 'tap' ?
            [['x', 'y']] :
            [['start_x', 'start_y'], ['end_x', 'end_y']];

        fields.forEach((pair, index) => {
            const xField = this.container.querySelector(`[name="${pair[0]}"]`);
            const yField = this.container.querySelector(`[name="${pair[1]}"]`);

            if (xField && yField) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-secondary coord-picker-btn';
                btn.innerHTML = '📍 Pick from Screen';
                btn.onclick = () => {
                    this.onCoordinatePick((x, y) => {
                        xField.value = Math.round(x);
                        yField.value = Math.round(y);
                    });
                };

                yField.parentElement.appendChild(btn);
            }
        });
    }

    /**
     * Load sensors for the current device
     * @private
     */
    async _loadSensors() {
        if (!this.deviceId) return;

        try {
            const response = await fetch(`${this.apiBase}/sensors/${encodeURIComponent(this.deviceId)}`);
            if (response.ok) {
                const data = await response.json();
                this.sensors = data.sensors || [];
            }
        } catch (error) {
            console.error('[ActionConfigurator] Failed to load sensors:', error);
            this.sensors = [];
        }
    }

    /**
     * Load actions for the current device
     * @private
     */
    async _loadActions() {
        if (!this.deviceId) return;

        try {
            const response = await fetch(`${this.apiBase}/actions/${encodeURIComponent(this.deviceId)}`);
            if (response.ok) {
                const data = await response.json();
                this.actions = data.actions || [];
            }
        } catch (error) {
            console.error('[ActionConfigurator] Failed to load actions:', error);
            this.actions = [];
        }
    }

    /**
     * Validate the current form
     * @returns {Object} Validated data
     * @throws {Error} If validation fails
     */
    validate() {
        const config = STEP_CONFIGS[this.currentType];
        if (!config) {
            throw new Error(`Unknown step type: ${this.currentType}`);
        }

        const data = { step_type: this.currentType };
        const errors = [];

        for (const field of config.fields) {
            const value = this._getFieldValue(field.name, field.type);

            if (field.required && (value === null || value === undefined || value === '')) {
                errors.push(`${field.label} is required`);
                continue;
            }

            if (value !== null && value !== undefined && value !== '') {
                // Type-specific validation
                if (field.type === 'number') {
                    const num = parseFloat(value);
                    if (isNaN(num)) {
                        errors.push(`${field.label} must be a number`);
                        continue;
                    }
                    if (field.min !== undefined && num < field.min) {
                        errors.push(`${field.label} must be at least ${field.min}`);
                        continue;
                    }
                    if (field.max !== undefined && num > field.max) {
                        errors.push(`${field.label} must be at most ${field.max}`);
                        continue;
                    }
                    data[field.name] = num;
                } else if (field.type === 'json') {
                    try {
                        data[field.name] = typeof value === 'string' ? JSON.parse(value) : value;
                    } catch {
                        errors.push(`${field.label} must be valid JSON`);
                        continue;
                    }
                } else if (field.type === 'multiselect') {
                    if (field.required && (!Array.isArray(value) || value.length === 0)) {
                        errors.push(`${field.label} requires at least one selection`);
                        continue;
                    }
                    data[field.name] = value;
                } else {
                    data[field.name] = value;
                }
            }
        }

        // Add description if provided
        const descInput = this.container.querySelector('[name="description"]');
        if (descInput && descInput.value.trim()) {
            data.description = descInput.value.trim();
        }

        if (errors.length > 0) {
            throw new Error(errors.join(', '));
        }

        return data;
    }

    /**
     * Get the current form data (without validation)
     * @returns {Object} Current form data
     */
    getData() {
        try {
            return this.validate();
        } catch {
            // Return partial data even if validation fails
            const config = STEP_CONFIGS[this.currentType];
            const data = { step_type: this.currentType };

            if (config) {
                for (const field of config.fields) {
                    const value = this._getFieldValue(field.name, field.type);
                    if (value !== null && value !== undefined && value !== '') {
                        data[field.name] = value;
                    }
                }
            }

            const descInput = this.container.querySelector('[name="description"]');
            if (descInput && descInput.value.trim()) {
                data.description = descInput.value.trim();
            }

            return data;
        }
    }

    /**
     * Get a field value from the form
     * @private
     */
    _getFieldValue(name, type) {
        if (type === 'multiselect') {
            const checkboxes = this.container.querySelectorAll(`[name="${name}"]:checked`);
            return Array.from(checkboxes).map(cb => cb.value);
        }

        const input = this.container.querySelector(`[name="${name}"]`);
        if (!input) return null;

        return input.value;
    }

    /**
     * Apply component styles
     * @private
     */
    _applyStyles() {
        if (document.getElementById('action-configurator-styles')) return;

        const style = document.createElement('style');
        style.id = 'action-configurator-styles';
        style.textContent = `
            .action-config-form {
                padding: 16px;
            }

            .action-config-header {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 20px;
                padding-bottom: 12px;
                border-bottom: 1px solid var(--border-color, #333);
            }

            .action-icon {
                font-size: 24px;
            }

            .action-label {
                font-size: 18px;
                font-weight: 600;
            }

            .form-group {
                margin-bottom: 16px;
            }

            .form-group label {
                display: block;
                margin-bottom: 6px;
                font-weight: 500;
                color: var(--text-color, #e0e0e0);
            }

            .form-input {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid var(--border-color, #444);
                border-radius: 6px;
                background: var(--card-background, #2a2a2a);
                color: var(--text-color, #e0e0e0);
                font-size: 14px;
            }

            .form-input:focus {
                outline: none;
                border-color: var(--primary-color, #2196F3);
            }

            .form-textarea {
                min-height: 80px;
                resize: vertical;
                font-family: monospace;
            }

            .no-config-needed {
                color: var(--text-secondary, #888);
                font-style: italic;
                text-align: center;
                padding: 20px;
            }

            .multiselect-container {
                max-height: 200px;
                overflow-y: auto;
                border: 1px solid var(--border-color, #444);
                border-radius: 6px;
                padding: 8px;
                background: var(--card-background, #2a2a2a);
            }

            .multiselect-item {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 8px;
                border-radius: 4px;
                cursor: pointer;
            }

            .multiselect-item:hover {
                background: rgba(255, 255, 255, 0.05);
            }

            .multiselect-item input {
                accent-color: var(--primary-color, #2196F3);
            }

            .no-items {
                color: var(--text-secondary, #888);
                font-style: italic;
                text-align: center;
                padding: 10px;
                margin: 0;
            }

            .coord-picker-btn {
                margin-top: 8px;
                font-size: 12px;
                padding: 6px 12px;
            }

            .error {
                color: #f44336;
                text-align: center;
                padding: 20px;
            }
        `;
        document.head.appendChild(style);
    }

    /**
     * Get available step types
     * @returns {Array} Array of {type, label, icon} objects
     */
    static getStepTypes() {
        return Object.entries(STEP_CONFIGS).map(([type, config]) => ({
            type,
            label: config.label,
            icon: config.icon
        }));
    }

    /**
     * Get configuration for a step type
     * @param {string} stepType - Step type
     * @returns {Object|null} Step configuration or null
     */
    static getStepConfig(stepType) {
        return STEP_CONFIGS[stepType] || null;
    }
}

// Dual export pattern: ES6 export + window global
window.ActionConfigurator = ActionConfigurator;

export default ActionConfigurator;
