/**
 * Visual Mapper - Sensor Creator Module
 * Version: 0.0.14 (Phase 4 - MQTT + Dynamic Hierarchical Dropdowns)
 * v0.0.14: Added debounce/guard to prevent double-submission
 * v0.0.13: Added targetApp to sensor data for app association
 * v0.0.12: Added pre-fill options support (name, device_class, unit, icon) for suggestions integration
 * v0.0.11: Added screenActivity to source data for better deduplication
 * v0.0.10: Fixed dialog initial display state
 *
 * Handles sensor creation dialog and configuration.
 * Creates Home Assistant sensors from selected UI elements.
 */

class SensorCreator {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.dialog = null;
        this.currentElement = null;
        this.currentElementIndex = null;
        this.currentDeviceId = null;
        this.currentDeviceStableId = null; // Stable device ID for data storage
        this.editMode = false;
        this.editingSensor = null;
        this.deviceClasses = null; // Will be loaded from API
        this.onSensorCreated = null; // Callback when sensor is created (response, sensorData)

        console.log('[SensorCreator] Initialized');

        // Load device classes from API
        this._loadDeviceClasses();
    }

    /**
     * Load device class reference from API
     * @private
     */
    async _loadDeviceClasses() {
        try {
            // Use apiClient for consistent API base detection
            const response = await this.apiClient.get('/device-classes');
            this.deviceClasses = response;
            console.log('[SensorCreator] Loaded device classes:', this.deviceClasses);
        } catch (error) {
            console.error('[SensorCreator] Error loading device classes:', error);
        }
    }

    /**
     * Populate sensor type dropdown from API data
     * @private
     */
    _populateSensorTypes() {
        const select = document.getElementById('sensorType');

        if (!select) {
            console.warn('[SensorCreator] Sensor type select not found');
            return;
        }

        if (!this.deviceClasses || !this.deviceClasses.sensor_types) {
            // Wait for device classes to load
            setTimeout(() => this._populateSensorTypes(), 100);
            return;
        }

        // Store current selection
        const currentValue = select.value;

        // Clear existing options
        select.innerHTML = '';

        // Add sensor types from API
        this.deviceClasses.sensor_types.forEach(type => {
            const option = document.createElement('option');
            option.value = type.value;
            option.textContent = `${type.name} - ${type.description}`;
            select.appendChild(option);
        });

        // Restore selection if possible, otherwise default to first option
        if (currentValue && Array.from(select.options).some(opt => opt.value === currentValue)) {
            select.value = currentValue;
        } else if (this.deviceClasses.sensor_types.length > 0) {
            select.value = this.deviceClasses.sensor_types[0].value;
        }

        console.log(`[SensorCreator] Populated ${this.deviceClasses.sensor_types.length} sensor types`);
    }

    /**
     * Show sensor creation dialog
     * @param {string} deviceId - Device ID (connection or stable)
     * @param {Object} element - Selected UI element
     * @param {number} elementIndex - Element index in hierarchy
     * @param {Object} options - Optional settings
     * @param {string} options.stableDeviceId - Stable device ID for data storage
     * @param {string} options.screenActivity - Current screen activity
     * @param {string} options.targetApp - Target app package name
     * @param {string} options.name - Pre-fill sensor name
     * @param {string} options.device_class - Pre-fill device class
     * @param {string} options.unit - Pre-fill unit of measurement
     * @param {string} options.icon - Pre-fill icon
     */
    show(deviceId, element, elementIndex, options = {}) {
        this.editMode = false;
        this.editingSensor = null;
        this.currentDeviceId = deviceId;
        this.currentDeviceStableId = options.stableDeviceId || deviceId;
        this.currentElement = element;
        this.currentElementIndex = elementIndex;
        this.screenActivity = options.screenActivity || null;
        this.targetApp = options.targetApp || null;

        // Create dialog if it doesn't exist
        if (!this.dialog) {
            this._createDialog();
        }

        // Populate form with element data
        this._populateForm(element, elementIndex);

        // Apply pre-fill options from suggestions (override defaults)
        if (options.name) {
            const nameInput = document.getElementById('sensorName');
            if (nameInput) nameInput.value = options.name;
        }
        if (options.device_class && options.device_class !== 'none') {
            const deviceClassSelect = document.getElementById('deviceClass');
            if (deviceClassSelect) {
                deviceClassSelect.value = options.device_class;
                // Trigger change to update units and state class
                this._onDeviceClassChange();
            }
        }
        if (options.unit) {
            const unitInput = document.getElementById('unitOfMeasurement');
            if (unitInput) unitInput.value = options.unit;
        }
        if (options.icon) {
            const iconInput = document.getElementById('sensorIcon');
            if (iconInput) iconInput.value = options.icon;
        }

        // Populate datalists based on device class selection
        this._onDeviceClassChange();

        // Update dialog title
        this.dialog.querySelector('h2').textContent = 'Create Sensor';
        this.dialog.querySelector('.btn-submit').textContent = 'Create Sensor';

        // Show dialog
        this.dialog.style.display = 'block';

        console.log('[SensorCreator] Dialog shown for element:', element, 'options:', options);
    }

    /**
     * Show sensor edit dialog
     * @param {Object} sensor - Sensor to edit
     */
    async showEdit(sensor) {
        this.editMode = true;
        this.editingSensor = sensor;
        this.currentDeviceId = sensor.device_id;
        this.currentElement = {
            text: sensor.source.element_text,
            class: sensor.source.element_class,
            resource_id: sensor.source.element_resource_id
        };
        this.currentElementIndex = sensor.source.element_index;

        // Create dialog if it doesn't exist
        if (!this.dialog) {
            this._createDialog();
        }

        // Populate form with sensor data
        this._populateFormWithSensor(sensor);

        // Ensure device classes are loaded before populating datalists
        if (!this.deviceClasses) {
            console.log('[SensorCreator] Waiting for device classes to load before populating datalists...');
            // Wait for device classes, then populate
            const waitForClasses = setInterval(() => {
                if (this.deviceClasses) {
                    clearInterval(waitForClasses);
                    console.log('[SensorCreator] Device classes loaded, populating datalists');
                    this._onDeviceClassChange();
                }
            }, 100);
        } else {
            // Populate datalists based on current device class selection
            this._onDeviceClassChange();
        }

        // Update dialog title
        this.dialog.querySelector('h2').textContent = 'Edit Sensor';
        this.dialog.querySelector('.btn-submit').textContent = 'Update Sensor';

        // Show dialog
        this.dialog.style.display = 'block';

        console.log('[SensorCreator] Edit dialog shown for sensor:', sensor);
    }

    /**
     * Hide sensor creation dialog
     */
    hide() {
        if (this.dialog) {
            this.dialog.style.display = 'none';
        }
    }

    /**
     * Create sensor creation dialog
     * @private
     */
    _createDialog() {
        // Create modal overlay
        const overlay = document.createElement('div');
        overlay.id = 'sensorCreatorDialog';
        overlay.className = 'modal-overlay';

        // Create dialog content
        overlay.innerHTML = `
            <div class="modal-content">
                <h2>Create Sensor</h2>

                <form id="sensorCreatorForm">
                    <!-- Element Info -->
                    <div class="info-box">
                        <strong>Selected Element:</strong><br>
                        <span id="selectedElementInfo"></span>
                    </div>

                    <!-- Sensor Name -->
                    <div class="form-group">
                        <label class="form-label">Sensor Name *</label>
                        <input type="text" id="sensorName" required class="form-input">
                    </div>

                    <!-- Sensor Type -->
                    <div class="form-group">
                        <label class="form-label">Sensor Type *</label>
                        <select id="sensorType" class="form-select">
                            <!-- Options populated dynamically from API -->
                        </select>
                    </div>

                    <!-- Device Class -->
                    <div class="form-group">
                        <label class="form-label">Device Class</label>
                        <select id="deviceClass" class="form-select">
                            <option value="none">Loading...</option>
                        </select>
                        <small id="deviceClassHelp" style="color: var(--text-secondary); font-size: 12px;"></small>
                    </div>

                    <!-- Unit of Measurement -->
                    <div class="form-group">
                        <label class="form-label">Unit of Measurement</label>
                        <select id="unitOfMeasurement" class="form-select">
                            <option value="">No unit</option>
                        </select>
                        <small id="unitHelp" style="color: var(--text-secondary); font-size: 12px;"></small>
                    </div>

                    <!-- State Class -->
                    <div class="form-group" id="stateClassGroup">
                        <label class="form-label">State Class</label>
                        <select id="stateClass" class="form-select">
                            <option value="none">None (Text sensor)</option>
                            <option value="measurement">Measurement (fluctuating values)</option>
                            <option value="total">Total (monotonically increasing)</option>
                            <option value="total_increasing">Total Increasing (can reset)</option>
                        </select>
                        <small id="stateClassHelp" style="color: var(--text-secondary); font-size: 12px;">For numeric sensors that track statistics</small>
                    </div>

                    <!-- Icon -->
                    <div class="form-group">
                        <label class="form-label">Icon (MDI)</label>
                        <select id="sensorIcon" class="form-select">
                            <option value="mdi:cellphone">mdi:cellphone (default)</option>
                        </select>
                        <small id="iconHelp" style="color: var(--text-secondary); font-size: 12px;">Suggested icon based on device class</small>
                    </div>

                    <!-- Extraction Pipeline -->
                    <div class="form-group">
                        <label class="form-label">
                            Text Extraction Pipeline
                            <span style="font-size: 12px; color: var(--text-secondary); font-weight: normal;">
                                (Chain multiple steps to extract complex values)
                            </span>
                        </label>
                        <div id="pipelineSteps"></div>
                        <button type="button" id="addPipelineStep" class="btn-add-step" style="margin-top: 10px;">
                            + Add Extraction Step
                        </button>
                    </div>

                    <!-- Extract Numeric Checkbox -->
                    <div class="form-group">
                        <label class="form-checkbox-label">
                            <input type="checkbox" id="extractNumeric">
                            Extract numeric value only (post-process all steps)
                        </label>
                    </div>

                    <!-- Remove Unit Checkbox -->
                    <div class="form-group">
                        <label class="form-checkbox-label">
                            <input type="checkbox" id="removeUnit">
                            Remove unit suffix (e.g., "94%" → "94")
                        </label>
                    </div>

                    <!-- Fallback Value -->
                    <div class="form-group">
                        <label class="form-label">Fallback Value (if extraction fails)</label>
                        <input type="text" id="fallbackValue" placeholder="e.g., unknown, 0" class="form-input">
                    </div>

                    <!-- Update Interval -->
                    <div class="form-group">
                        <label class="form-label">Update Interval (seconds)</label>
                        <input type="number" id="updateInterval" value="60" min="5" max="3600" class="form-input">
                    </div>

                    <!-- Preview -->
                    <div class="preview-box-large">
                        <h3 style="margin: 0 0 10px 0; color: var(--primary-color);">📋 Extraction Preview</h3>
                        <div id="previewSteps" style="margin-bottom: 10px; font-size: 13px; color: var(--text-secondary);"></div>
                        <div id="previewValue" class="preview-value-large"></div>
                    </div>

                    <!-- Buttons -->
                    <div class="button-group">
                        <button type="button" id="cancelSensorBtn" class="btn-cancel">Cancel</button>
                        <button type="submit" class="btn-submit">Create Sensor</button>
                    </div>
                </form>
            </div>
        `;

        document.body.appendChild(overlay);
        this.dialog = overlay;

        // Ensure dialog is hidden initially (CSS may conflict)
        this.dialog.style.display = 'none';

        // Initialize pipeline
        this.pipelineSteps = [];
        this._addPipelineStep(); // Add first step by default

        // Bind event handlers
        document.getElementById('cancelSensorBtn').addEventListener('click', () => this.hide());
        document.getElementById('sensorCreatorForm').addEventListener('submit', (e) => this._handleSubmit(e));
        document.getElementById('addPipelineStep').addEventListener('click', () => this._addPipelineStep());
        document.getElementById('sensorName').addEventListener('input', () => this._updatePreview());
        document.getElementById('extractNumeric').addEventListener('change', () => this._updatePreview());
        document.getElementById('removeUnit').addEventListener('change', () => this._updatePreview());
        document.getElementById('fallbackValue').addEventListener('input', () => this._updatePreview());
        document.getElementById('sensorType').addEventListener('change', () => this._onSensorTypeChange());
        document.getElementById('deviceClass').addEventListener('change', () => this._onDeviceClassChange());

        // Populate sensor types from API
        this._populateSensorTypes();

        // Populate device classes (will also populate datalists)
        this._populateDeviceClasses();
    }

    /**
     * Populate device class dropdown from API data
     * @private
     */
    _populateDeviceClasses() {
        const select = document.getElementById('deviceClass');
        const sensorType = document.getElementById('sensorType').value;

        if (!this.deviceClasses) {
            // Wait for device classes to load
            setTimeout(() => this._populateDeviceClasses(), 100);
            return;
        }

        // Clear existing options
        select.innerHTML = '<option value="none">None (Generic Sensor)</option>';

        // Get device classes for current sensor type
        const classes = sensorType === 'binary_sensor'
            ? this.deviceClasses.binary_sensor_device_classes
            : this.deviceClasses.sensor_device_classes;

        // Add options
        for (const [key, info] of Object.entries(classes)) {
            if (key === 'none') continue; // Already added
            const option = document.createElement('option');
            option.value = key;
            option.textContent = `${info.name} - ${info.description}`;
            select.appendChild(option);
        }

        console.log(`[SensorCreator] Populated ${Object.keys(classes).length} device classes for ${sensorType}`);

        // Trigger initial population of unit/icon datalists
        this._onDeviceClassChange();
    }

    /**
     * Handle sensor type change (sensor vs binary_sensor)
     * @private
     */
    _onSensorTypeChange() {
        this._populateDeviceClasses();
        this._onDeviceClassChange(); // Update help text
    }

    /**
     * Handle device class change - update help text and populate unit/icon dropdowns
     * @private
     */
    _onDeviceClassChange() {
        const deviceClass = document.getElementById('deviceClass').value;
        const sensorType = document.getElementById('sensorType').value;
        const helpText = document.getElementById('deviceClassHelp');
        const unitSelect = document.getElementById('unitOfMeasurement');
        const unitHelp = document.getElementById('unitHelp');
        const iconSelect = document.getElementById('sensorIcon');

        console.log(`[SensorCreator] _onDeviceClassChange - deviceClass: ${deviceClass}, sensorType: ${sensorType}, hasDeviceClasses: ${!!this.deviceClasses}`);

        // Store current values before clearing
        const currentUnit = unitSelect.value;
        const currentIcon = iconSelect.value;

        // Clear existing options
        unitSelect.innerHTML = '<option value="">No unit</option>';
        iconSelect.innerHTML = '<option value="mdi:cellphone">mdi:cellphone (default)</option>';

        if (!this.deviceClasses || deviceClass === 'none') {
            helpText.textContent = '';
            unitHelp.textContent = '';
            return;
        }

        // Get device class info
        const classes = sensorType === 'binary_sensor'
            ? this.deviceClasses.binary_sensor_device_classes
            : this.deviceClasses.sensor_device_classes;

        const info = classes[deviceClass];
        if (!info) return;

        // Update help text
        helpText.textContent = info.description;

        // Populate unit dropdown for sensors (not binary sensors)
        if (sensorType === 'sensor' && info.valid_units && info.valid_units.length > 0) {
            console.log(`[SensorCreator] Populating ${info.valid_units.length} units for device class ${deviceClass}:`, info.valid_units);
            info.valid_units.forEach(unit => {
                const option = document.createElement('option');
                option.value = unit;
                option.textContent = unit || '(no unit)';
                unitSelect.appendChild(option);
            });

            unitHelp.textContent = `Valid units: ${info.valid_units.join(', ')}`;

            // Select first valid unit or restore previous value
            if (currentUnit && info.valid_units.includes(currentUnit)) {
                unitSelect.value = currentUnit;
            } else {
                const firstUnit = info.valid_units[0];
                unitSelect.value = firstUnit || '';
            }
            console.log(`[SensorCreator] Unit dropdown now has ${unitSelect.options.length} options`);
        } else {
            unitHelp.textContent = sensorType === 'binary_sensor' ? 'Binary sensors do not have units' : 'No specific unit required';
            console.log(`[SensorCreator] Skipping unit population - sensor type: ${sensorType}, has valid_units: ${!!(info.valid_units && info.valid_units.length > 0)}`);
        }

        // Populate icon dropdown with suggested icon + common icons
        if (info.default_icon) {
            const option = document.createElement('option');
            option.value = info.default_icon;
            option.textContent = `${info.default_icon} (suggested)`;
            iconSelect.appendChild(option);
        }

        // Add common icons to dropdown
        const commonIcons = [
            'mdi:cellphone', 'mdi:battery', 'mdi:thermometer', 'mdi:water-percent',
            'mdi:speedometer', 'mdi:gauge', 'mdi:flash', 'mdi:weather-sunny',
            'mdi:home', 'mdi:lightbulb', 'mdi:power-plug', 'mdi:clock'
        ];
        commonIcons.forEach(icon => {
            if (icon !== info.default_icon) {
                const option = document.createElement('option');
                option.value = icon;
                option.textContent = icon;
                iconSelect.appendChild(option);
            }
        });

        // Select suggested icon or restore previous value
        if (currentIcon && Array.from(iconSelect.options).some(opt => opt.value === currentIcon)) {
            iconSelect.value = currentIcon;
        } else if (info.default_icon) {
            iconSelect.value = info.default_icon;
        }

        console.log(`[SensorCreator] Icon dropdown now has ${iconSelect.options.length} options`);
    }

    /**
     * Populate form with element data (create mode)
     * @private
     */
    _populateForm(element, elementIndex) {
        // Handle null/undefined element
        if (!element) {
            console.warn('[SensorCreator] No element provided to _populateForm');
            element = { class: 'Unknown', text: '' };
        }

        // Element info
        const elementInfo = document.getElementById('selectedElementInfo');
        const elementClass = element.class || element['class'] || 'Unknown';
        const elementText = element.text || '';
        elementInfo.textContent = `Index: ${elementIndex} | Class: ${elementClass} | Text: "${elementText || '(empty)'}"`;

        // Auto-populate sensor name from element text
        const sensorName = document.getElementById('sensorName');
        if (elementText && elementText.trim()) {
            // Clean text for sensor name
            const cleanName = elementText.trim().substring(0, 50).replace(/[^a-zA-Z0-9\s]/g, '');
            sensorName.value = cleanName || 'Sensor';
        } else {
            const classShortName = elementClass.split('.').pop() || 'Element';
            sensorName.value = classShortName + ' Sensor';
        }

        // Update preview
        this._updatePreview();
    }

    /**
     * Populate form with sensor data (edit mode)
     * @private
     */
    _populateFormWithSensor(sensor) {
        // Element info
        const elementInfo = document.getElementById('selectedElementInfo');
        elementInfo.textContent = `Index: ${sensor.source.element_index} | Class: ${sensor.source.element_class || 'N/A'} | Text: "${sensor.source.element_text || '(empty)'}"`;

        // Fill in all form fields
        document.getElementById('sensorName').value = sensor.friendly_name;
        document.getElementById('sensorType').value = sensor.sensor_type;
        document.getElementById('deviceClass').value = sensor.device_class || 'none';
        document.getElementById('unitOfMeasurement').value = sensor.unit_of_measurement || '';
        document.getElementById('stateClass').value = sensor.state_class || 'none';
        document.getElementById('sensorIcon').value = sensor.icon || 'mdi:cellphone';
        document.getElementById('updateInterval').value = sensor.update_interval_seconds;
        document.getElementById('extractNumeric').checked = sensor.extraction_rule.extract_numeric || false;
        document.getElementById('removeUnit').checked = sensor.extraction_rule.remove_unit || false;
        document.getElementById('fallbackValue').value = sensor.extraction_rule.fallback_value || '';

        // Rebuild pipeline from extraction rule
        this.pipelineSteps = [];
        const container = document.getElementById('pipelineSteps');
        container.innerHTML = '';

        // First step is the main method
        this.pipelineSteps.push({
            method: sensor.extraction_rule.method,
            params: this._extractMethodParams(sensor.extraction_rule)
        });

        // Add pipeline steps if they exist
        if (sensor.extraction_rule.pipeline && sensor.extraction_rule.pipeline.length > 0) {
            for (const pipeStep of sensor.extraction_rule.pipeline) {
                this.pipelineSteps.push({
                    method: pipeStep.method,
                    params: this._extractMethodParams(pipeStep)
                });
            }
        }

        // Re-render pipeline UI
        this._renderPipeline();

        // Update preview
        this._updatePreview();
    }

    /**
     * Extract method-specific parameters from extraction rule
     * @private
     */
    _extractMethodParams(rule) {
        const params = {};
        if (rule.regex_pattern) params.regex_pattern = rule.regex_pattern;
        if (rule.after_text) params.after_text = rule.after_text;
        if (rule.before_text) params.before_text = rule.before_text;
        if (rule.between_start) {
            params.between_start = rule.between_start;
            params.between_end = rule.between_end;
        }
        return params;
    }

    /**
     * Add a new pipeline step
     * @private
     */
    _addPipelineStep() {
        const stepIndex = this.pipelineSteps.length;
        const step = {
            method: 'exact',
            params: {}
        };
        this.pipelineSteps.push(step);

        const container = document.getElementById('pipelineSteps');
        const stepDiv = document.createElement('div');
        stepDiv.className = 'pipeline-step';
        stepDiv.dataset.stepIndex = stepIndex;
        stepDiv.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                <strong>Step ${stepIndex + 1}</strong>
                <button type="button" class="btn-remove-step" data-step="${stepIndex}" style="background: #f44336; color: white; border: none; padding: 4px 8px; border-radius: 3px; cursor: pointer; font-size: 12px;">Remove</button>
            </div>
            <select class="pipeline-method form-select" data-step="${stepIndex}" style="margin-bottom: 5px;">
                <option value="exact">Exact (use text as-is)</option>
                <option value="numeric">Numeric (extract number)</option>
                <option value="regex">Regex (pattern)</option>
                <option value="after">After (text after)</option>
                <option value="before">Before (text before)</option>
                <option value="between">Between (text between)</option>
            </select>
            <div class="pipeline-params" data-step="${stepIndex}"></div>
        `;

        container.appendChild(stepDiv);

        // Bind events
        stepDiv.querySelector('.pipeline-method').addEventListener('change', (e) => {
            this._updateStepParams(stepIndex, e.target.value);
            this._updatePreview();
        });

        stepDiv.querySelector('.btn-remove-step').addEventListener('click', () => {
            this._removePipelineStep(stepIndex);
        });

        // Initialize params
        this._updateStepParams(stepIndex, 'exact');
    }

    /**
     * Remove a pipeline step
     * @private
     */
    _removePipelineStep(stepIndex) {
        // Don't allow removing the last step
        if (this.pipelineSteps.length <= 1) {
            alert('You must have at least one extraction step');
            return;
        }

        // Remove from DOM
        const stepDiv = document.querySelector(`[data-step-index="${stepIndex}"]`);
        if (stepDiv) {
            stepDiv.remove();
        }

        // Remove from array
        this.pipelineSteps.splice(stepIndex, 1);

        // Re-render all steps to update indices
        this._renderPipeline();
        this._updatePreview();
    }

    /**
     * Re-render entire pipeline
     * @private
     */
    _renderPipeline() {
        const container = document.getElementById('pipelineSteps');
        container.innerHTML = '';
        const savedSteps = [...this.pipelineSteps];
        this.pipelineSteps = [];

        savedSteps.forEach((step) => {
            this._addPipelineStep();
            const stepIndex = this.pipelineSteps.length - 1;
            this.pipelineSteps[stepIndex] = step;

            // Set method
            const methodSelect = container.querySelector(`.pipeline-method[data-step="${stepIndex}"]`);
            methodSelect.value = step.method;
            this._updateStepParams(stepIndex, step.method);

            // Set params
            const paramsDiv = container.querySelector(`.pipeline-params[data-step="${stepIndex}"]`);
            if (step.method === 'regex' && step.params.regex_pattern) {
                paramsDiv.querySelector('input').value = step.params.regex_pattern;
            } else if (step.method === 'after' && step.params.after_text) {
                paramsDiv.querySelector('input').value = step.params.after_text;
            } else if (step.method === 'before' && step.params.before_text) {
                paramsDiv.querySelector('input').value = step.params.before_text;
            } else if (step.method === 'between') {
                const inputs = paramsDiv.querySelectorAll('input');
                if (step.params.between_start) inputs[0].value = step.params.between_start;
                if (step.params.between_end) inputs[1].value = step.params.between_end;
            }
        });
    }

    /**
     * Update parameter fields for a pipeline step
     * @private
     */
    _updateStepParams(stepIndex, method) {
        const paramsDiv = document.querySelector(`.pipeline-params[data-step="${stepIndex}"]`);
        this.pipelineSteps[stepIndex].method = method;
        this.pipelineSteps[stepIndex].params = {};

        paramsDiv.innerHTML = '';

        if (method === 'regex') {
            paramsDiv.innerHTML = '<input type="text" class="form-input" placeholder="e.g., (\\d+)% for percentage" style="margin-top: 5px;">';
            paramsDiv.querySelector('input').addEventListener('input', (e) => {
                this.pipelineSteps[stepIndex].params.regex_pattern = e.target.value;
                this._updatePreview();
            });
        } else if (method === 'after') {
            paramsDiv.innerHTML = '<input type="text" class="form-input" placeholder="Text to search after" style="margin-top: 5px;">';
            paramsDiv.querySelector('input').addEventListener('input', (e) => {
                this.pipelineSteps[stepIndex].params.after_text = e.target.value;
                this._updatePreview();
            });
        } else if (method === 'before') {
            paramsDiv.innerHTML = '<input type="text" class="form-input" placeholder="Text to search before" style="margin-top: 5px;">';
            paramsDiv.querySelector('input').addEventListener('input', (e) => {
                this.pipelineSteps[stepIndex].params.before_text = e.target.value;
                this._updatePreview();
            });
        } else if (method === 'between') {
            paramsDiv.innerHTML = `
                <input type="text" class="form-input" placeholder="Start text" style="margin-top: 5px; margin-bottom: 5px;">
                <input type="text" class="form-input" placeholder="End text">
            `;
            const inputs = paramsDiv.querySelectorAll('input');
            inputs[0].addEventListener('input', (e) => {
                this.pipelineSteps[stepIndex].params.between_start = e.target.value;
                this._updatePreview();
            });
            inputs[1].addEventListener('input', (e) => {
                this.pipelineSteps[stepIndex].params.between_end = e.target.value;
                this._updatePreview();
            });
        }
    }

    /**
     * Update extraction preview (calls backend API for progressive step-by-step results)
     * Shows what text remains after EACH pipeline step
     * @private
     */
    async _updatePreview() {
        const previewValue = document.getElementById('previewValue');
        const previewSteps = document.getElementById('previewSteps');

        if (!this.currentElement || !this.currentElement.text) {
            previewValue.innerHTML = '<span style="color: var(--text-secondary); font-style: italic;">(No text in element)</span>';
            previewSteps.textContent = '';
            return;
        }

        // Check if any step needs parameters filled
        const incompleteSteps = this.pipelineSteps.filter((step, idx) => {
            if (step.method === 'regex' && !step.params.regex_pattern) return true;
            if (step.method === 'after' && !step.params.after_text) return true;
            if (step.method === 'before' && !step.params.before_text) return true;
            if (step.method === 'between' && (!step.params.between_start || !step.params.between_end)) return true;
            return false;
        });

        if (incompleteSteps.length > 0) {
            previewValue.innerHTML = '<span style="color: var(--warning-color); font-style: italic;">⚠️ Fill in all extraction parameters to see preview</span>';
            previewSteps.textContent = '';
            return;
        }

        // Show loading state
        previewValue.innerHTML = '<span style="color: var(--primary-color);">⏳ Testing extraction...</span>';
        previewValue.style.opacity = '0.6';
        previewSteps.textContent = '';

        try {
            // Test each step progressively to show intermediate results
            let currentText = this.currentElement.text;
            let stepsHTML = `<strong>Original:</strong> "<span style="color: var(--text-color); font-weight: 600;">${currentText}</span>"<br>`;

            // Test step by step
            for (let i = 0; i < this.pipelineSteps.length; i++) {
                const step = this.pipelineSteps[i];

                // Build extraction rule for this step only
                const testRule = {
                    method: step.method,
                    ...step.params
                };

                const response = await this.apiClient.post('/test/extract', {
                    text: currentText,
                    extraction_rule: testRule
                });

                if (response.success) {
                    currentText = response.extracted_value;
                    stepsHTML += `<strong>Step ${i + 1} (${step.method}):</strong> "<span style="color: var(--primary-color); font-weight: 600;">${currentText}</span>"<br>`;
                } else {
                    stepsHTML += `<strong>Step ${i + 1} (${step.method}):</strong> <span style="color: var(--error-color);">Error: ${response.error}</span><br>`;
                    break;
                }
            }

            // Apply post-processing (extract_numeric, remove_unit)
            const extractNumeric = document.getElementById('extractNumeric').checked;
            const removeUnit = document.getElementById('removeUnit').checked;
            const fallbackValue = document.getElementById('fallbackValue').value;

            if (extractNumeric || removeUnit) {
                const postProcessRule = {
                    method: 'exact',
                    extract_numeric: extractNumeric,
                    remove_unit: removeUnit
                };

                const response = await this.apiClient.post('/test/extract', {
                    text: currentText,
                    extraction_rule: postProcessRule
                });

                if (response.success && response.extracted_value !== currentText) {
                    currentText = response.extracted_value;
                    stepsHTML += `<strong>Post-processing:</strong> "<span style="color: var(--secondary-color); font-weight: 600;">${currentText}</span>"<br>`;
                }
            }

            previewSteps.innerHTML = stepsHTML;
            previewValue.innerHTML = `
                <div style="padding: 15px; background: var(--preview-background); border: 2px solid var(--preview-border); border-radius: 6px;">
                    <strong style="color: var(--preview-text); font-size: 16px;">✅ Final Result:</strong><br>
                    <span style="color: var(--text-color); font-size: 18px; font-weight: bold;">"${currentText}"</span>
                </div>
            `;
            previewValue.style.color = 'var(--text-color)';

        } catch (error) {
            console.error('[SensorCreator] Preview failed:', error);
            previewValue.innerHTML = `<span style="color: var(--error-color);">❌ Preview failed: ${error.message}</span>`;
            previewSteps.textContent = '';
        } finally {
            previewValue.style.opacity = '1';
        }
    }

    /**
     * Handle form submission (create or update)
     * @private
     */
    async _handleSubmit(event) {
        event.preventDefault();

        // Prevent double-submission
        if (this._submitting) {
            console.log('[SensorCreator] Submission already in progress, ignoring duplicate');
            return;
        }
        this._submitting = true;

        // Safety net: auto-reset flag after 30 seconds
        const submitTimeout = setTimeout(() => {
            if (this._submitting) {
                console.warn('[SensorCreator] Submit timeout after 30s - resetting flag');
                this._submitting = false;
                this._enableSubmitButton();
            }
        }, 30000);

        // Disable submit button
        this._disableSubmitButton();

        try {
            await this._doSubmit();
        } finally {
            clearTimeout(submitTimeout);
            this._submitting = false;
            this._enableSubmitButton();
        }
    }

    /**
     * Disable submit button during submission
     * @private
     */
    _disableSubmitButton() {
        const btn = document.querySelector('#sensorCreatorForm button[type="submit"]');
        if (btn) {
            btn.disabled = true;
            btn._originalText = btn.textContent;
            btn.textContent = 'Saving...';
        }
    }

    /**
     * Re-enable submit button after submission
     * @private
     */
    _enableSubmitButton() {
        const btn = document.querySelector('#sensorCreatorForm button[type="submit"]');
        if (btn) {
            btn.disabled = false;
            btn.textContent = btn._originalText || 'Create Sensor';
        }
    }

    /**
     * Actual submission logic (extracted from _handleSubmit)
     * @private
     */
    async _doSubmit() {
        // Validate required data is present
        if (!this.currentDeviceId) {
            alert('Error: No device selected');
            return;
        }
        if (this.currentElementIndex === undefined || this.currentElementIndex === null) {
            alert('Error: No element selected. Please select an element from the screen first.');
            return;
        }
        if (!this.currentElement) {
            alert('Error: Element data missing. Please re-select an element.');
            return;
        }
        if (!this.pipelineSteps || this.pipelineSteps.length === 0) {
            alert('Error: No extraction rule configured');
            return;
        }

        const sensorData = {
            sensor_id: this.editMode ? this.editingSensor.sensor_id : "", // Use existing ID in edit mode
            device_id: this.currentDeviceStableId || this.currentDeviceId, // Use stable ID for storage
            stable_device_id: this.currentDeviceStableId || this.currentDeviceId,
            friendly_name: document.getElementById('sensorName').value,
            sensor_type: document.getElementById('sensorType').value,
            device_class: document.getElementById('deviceClass').value,
            unit_of_measurement: document.getElementById('unitOfMeasurement').value || null,
            state_class: (() => {
                const val = document.getElementById('stateClass').value;
                return val === 'none' || val === '' ? null : val;
            })(),
            icon: document.getElementById('sensorIcon').value,
            target_app: this.targetApp || null,
            source: {
                source_type: "element",
                element_index: this.currentElementIndex,
                element_text: this.currentElement.text || null,
                element_class: this.currentElement.class || null,
                element_resource_id: this.currentElement.resource_id || null,
                screen_activity: this.screenActivity || null,
                custom_bounds: this.currentElement.bounds || null
            },
            extraction_rule: this._buildExtractionRule(),
            update_interval_seconds: parseInt(document.getElementById('updateInterval').value),
            enabled: this.editMode ? this.editingSensor.enabled : true
        };

        // Log sensor data for debugging
        console.log('[SensorCreator] Submitting sensor data:', JSON.stringify(sensorData, null, 2));

        try {
            let response;
            if (this.editMode) {
                // Update existing sensor
                response = await this.apiClient.put('/sensors', sensorData);
                console.log('[SensorCreator] Sensor updated:', response);
                alert(`Sensor "${sensorData.friendly_name}" updated successfully!`);
            } else {
                // Check for similar sensors before creating (deduplication)
                const dupCheck = await this._checkForDuplicates(sensorData);
                if (dupCheck.hasSimilar) {
                    const useExisting = await this._showDuplicateWarning(dupCheck);
                    if (useExisting) {
                        // User chose to use existing sensor
                        console.log('[SensorCreator] Using existing sensor:', dupCheck.bestMatch.entity_id);
                        response = { sensor_id: dupCheck.bestMatch.entity_id, ...dupCheck.bestMatch.details };
                        alert(`Using existing sensor "${dupCheck.bestMatch.entity_name}" instead of creating duplicate.`);

                        // Fire callback with existing sensor
                        if (this.onSensorCreated) {
                            this.onSensorCreated(response, sensorData);
                        }
                        this.hide();
                        return;
                    }
                    // else: User chose to create anyway, continue below
                }

                // Create new sensor (backend may auto-reuse if ≥90% match found)
                response = await this.apiClient.post('/sensors', sensorData);
                console.log('[SensorCreator] Sensor response:', response);

                // Handle auto-reuse response from backend
                if (response.reused) {
                    // Backend auto-reused an existing sensor
                    const reusedName = response.sensor?.friendly_name || 'existing sensor';
                    console.log(`[SensorCreator] Auto-reused existing sensor: ${reusedName}`);
                    alert(`Using existing sensor: ${reusedName}\n\n(A matching sensor already exists)`);
                } else {
                    // New sensor was created
                    alert(`Sensor "${sensorData.friendly_name}" created successfully!`);
                }
            }

            // Hide dialog
            this.hide();

            // Fire callback if set (for flow wizard integration)
            if (!this.editMode && this.onSensorCreated) {
                try {
                    this.onSensorCreated(response, sensorData);
                } catch (e) {
                    console.warn('[SensorCreator] onSensorCreated callback error:', e);
                }
            }

            // Trigger page reload if this was called from sensors.html
            if (window.location.pathname.includes('sensors.html') && window.loadSensors) {
                await window.loadSensors();
            }

        } catch (error) {
            console.error(`[SensorCreator] Failed to ${this.editMode ? 'update' : 'create'} sensor:`, error);
            alert(`Failed to ${this.editMode ? 'update' : 'create'} sensor: ${error.message}`);
        }
    }

    /**
     * Build extraction rule from pipeline
     * @private
     */
    _buildExtractionRule() {
        const extractNumeric = document.getElementById('extractNumeric').checked;
        const removeUnit = document.getElementById('removeUnit').checked;
        const fallbackValue = document.getElementById('fallbackValue').value;

        // Use first step method as primary, rest as pipeline
        const firstStep = this.pipelineSteps[0];
        const rule = {
            method: firstStep.method,
            ...firstStep.params,
            extract_numeric: extractNumeric,
            remove_unit: removeUnit,
            fallback_value: fallbackValue || null
        };

        // Add pipeline if multiple steps
        if (this.pipelineSteps.length > 1) {
            rule.pipeline = this.pipelineSteps.slice(1).map(step => ({
                method: step.method,
                ...step.params
            }));
        }

        return rule;
    }

    /**
     * Check for duplicate sensors before creating
     * @private
     */
    async _checkForDuplicates(sensorData) {
        try {
            const response = await this.apiClient.post('/dedup/sensors/check', {
                device_id: sensorData.device_id,
                sensor: {
                    resource_id: sensorData.resource_id,
                    bounds: sensorData.bounds,
                    screen_activity: sensorData.screen_activity,
                    name: sensorData.friendly_name,
                    extraction_method: sensorData.extraction_rule?.method
                }
            });

            return {
                hasSimilar: response.has_similar,
                matches: response.matches || [],
                bestMatch: response.best_match,
                recommendation: response.recommendation
            };
        } catch (error) {
            console.warn('[SensorCreator] Duplicate check failed, proceeding with creation:', error);
            return { hasSimilar: false, matches: [] };
        }
    }

    /**
     * Show duplicate warning dialog and return user choice
     * @private
     * @returns {Promise<boolean>} true = use existing, false = create anyway
     */
    async _showDuplicateWarning(dupCheck) {
        return new Promise((resolve) => {
            const match = dupCheck.bestMatch;
            const score = Math.round((match.similarity_score || 0) * 100);
            const reasons = (match.match_reasons || []).join(', ').replace(/_/g, ' ');

            const modal = document.createElement('div');
            modal.className = 'modal-overlay';
            modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10001;display:flex;align-items:center;justify-content:center;';

            modal.innerHTML = `
                <div style="background:white;border-radius:12px;padding:24px;max-width:450px;margin:20px;box-shadow:0 4px 20px rgba(0,0,0,0.3);">
                    <h3 style="margin:0 0 16px 0;color:#ff9800;">
                        ⚠️ Similar Sensor Found
                    </h3>
                    <div style="background:#fff3e0;padding:12px;border-radius:8px;margin-bottom:16px;">
                        <strong style="color:#e65100;">${match.entity_name}</strong>
                        <div style="font-size:0.9em;color:#666;margin-top:4px;">
                            ${score}% match • ${reasons}
                        </div>
                        ${match.details?.existing_value ? `
                            <div style="font-size:0.85em;color:#888;margin-top:4px;">
                                Current value: <strong>${match.details.existing_value}</strong>
                            </div>
                        ` : ''}
                    </div>
                    <p style="margin:0 0 20px 0;color:#555;">
                        ${dupCheck.recommendation === 'use_existing'
                            ? 'This appears to be the same sensor. Using the existing one is recommended.'
                            : 'A similar sensor exists. You may want to use it instead of creating a duplicate.'}
                    </p>
                    <div style="display:flex;gap:12px;justify-content:flex-end;">
                        <button id="dupCreateAnyway" style="padding:10px 20px;border:1px solid #ddd;background:#fff;border-radius:6px;cursor:pointer;">
                            Create Anyway
                        </button>
                        <button id="dupUseExisting" style="padding:10px 20px;border:none;background:#4CAF50;color:white;border-radius:6px;cursor:pointer;font-weight:500;">
                            Use Existing
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            modal.querySelector('#dupUseExisting').onclick = () => {
                document.body.removeChild(modal);
                resolve(true);
            };

            modal.querySelector('#dupCreateAnyway').onclick = () => {
                document.body.removeChild(modal);
                resolve(false);
            };

            // Close on backdrop click
            modal.onclick = (e) => {
                if (e.target === modal) {
                    document.body.removeChild(modal);
                    resolve(false);
                }
            };
        });
    }
}

// ES6 export
export default SensorCreator;

// Global export for non-module usage
window.SensorCreator = SensorCreator;
