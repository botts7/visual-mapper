/**
 * Flow Interactions Module
 * Visual Mapper v0.0.13
 *
 * Handles user interactions, dialogs, and sensor creation
 * v0.0.10: Added element info preview and warnings in sensor dialog
 * v0.0.11: Added container filtering to findElementAtCoordinates
 * v0.0.12: Fixed hyphenated property names (resource-id, content-desc)
 * v0.0.13: containerClasses Set for O(1) lookup
 */

import { showToast } from './toast.js?v=0.4.0-beta.2.5';

export class FlowInteractions {
    constructor(apiBase) {
        this.apiBase = apiBase;
    }

    /**
     * Show element selection dialog
     */
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
                <div style="background: linear-gradient(135deg, #dbeafe 0%, #e0e7ff 100%); padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 2px solid #3b82f6; color: #1e3a8a;">
                    <div style="font-size: 14px; color: #1e40af; font-weight: 600; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 20px;">🎯</span>
                        Element Selected
                    </div>
                    ${element.text ? `<div style="margin-bottom: 6px; color: #1e3a8a;"><strong>Text:</strong> ${element.text}</div>` : ''}
                    ${element.class ? `<div style="margin-bottom: 6px; font-size: 12px; color: #1e3a8a;"><strong>Class:</strong> <code style="background: rgba(255,255,255,0.7); padding: 2px 6px; border-radius: 3px; color: #1e3a8a;">${element.class}</code></div>` : ''}
                    ${element.resource_id ? `<div style="margin-bottom: 6px; font-size: 12px; color: #1e3a8a;"><strong>Resource ID:</strong> <code style="background: rgba(255,255,255,0.7); padding: 2px 6px; border-radius: 3px; color: #1e3a8a;">${element.resource_id.split('/').pop() || element.resource_id}</code></div>` : ''}
                    ${element.content_desc ? `<div style="margin-bottom: 6px; color: #1e3a8a;"><strong>Description:</strong> ${element.content_desc}</div>` : ''}
                    <div style="margin-bottom: 6px; font-size: 12px; color: #1e3a8a;"><strong>Position:</strong> (${coords.x}, ${coords.y})</div>
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

                        <button class="choice-btn" data-choice="action" style="
                            background: linear-gradient(135deg, #ec4899 0%, #db2777 100%);
                            color: white;
                            border: none;
                            padding: 16px;
                            border-radius: 8px;
                            cursor: pointer;
                            font-size: 15px;
                            font-weight: 600;
                            transition: all 0.2s ease;
                            box-shadow: 0 2px 8px rgba(236, 72, 153, 0.3);
                        ">
                            <div style="font-size: 24px; margin-bottom: 4px;">⚡</div>
                            Create Action
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

    /**
     * Prompt user for text input
     */
    async promptForText() {
        const text = prompt('Enter text to type:');
        return text && text.trim() !== '' ? text.trim() : null;
    }

    /**
     * Prompt user for sensor name
     */
    async promptForSensorName(defaultName) {
        const name = prompt(`Enter sensor name:`, defaultName);
        return name && name.trim() !== '' ? name.trim() : null;
    }

    /**
     * Validate that bounds have all required fields (x, y, width, height)
     * Returns the bounds if valid, null otherwise
     */
    validateBounds(bounds) {
        if (!bounds) return null;

        // Check that all required fields are present and valid
        const hasX = typeof bounds.x === 'number' && bounds.x >= 0;
        const hasY = typeof bounds.y === 'number' && bounds.y >= 0;
        const hasWidth = typeof bounds.width === 'number' && bounds.width > 0;
        const hasHeight = typeof bounds.height === 'number' && bounds.height > 0;

        return (hasX && hasY && hasWidth && hasHeight) ? bounds : null;
    }

    /**
     * Prompt for refresh configuration
     */
    async promptForRefreshConfig() {
        const attemptsStr = prompt('Number of refresh attempts (1-5):', '2');
        if (!attemptsStr) return null;

        const attempts = Math.min(Math.max(parseInt(attemptsStr) || 2, 1), 5);

        const delayStr = prompt('Delay between refreshes in milliseconds (500-5000):', '1000');
        if (!delayStr) return null;

        const delay = Math.min(Math.max(parseInt(delayStr) || 1000, 500), 5000);

        return { attempts, delay };
    }

    /**
     * Show sensor configuration dialog
     * Returns config object or null if cancelled
     * @param {string} defaultName - Default sensor name
     * @param {string} sensorType - 'text' or 'image'
     * @param {Object} element - The selected element (optional, for preview/warnings)
     */
    async promptForSensorConfig(defaultName, sensorType = 'text', element = null) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.id = 'sensor-config-overlay';
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

            // Check for problematic elements
            const elementClass = element?.class || '';
            const elementText = element?.text?.trim() || '';
            const elementContentDesc = element?.content_desc?.trim() || '';
            const shortClass = elementClass.split('.').pop();

            // Determine warnings
            const isContainer = ['View', 'ViewGroup', 'FrameLayout', 'LinearLayout', 'RelativeLayout',
                'ConstraintLayout', 'RecyclerView', 'ScrollView', 'CardView'].some(c => shortClass.includes(c));
            const hasNoValue = !elementText && !elementContentDesc;

            let warningHtml = '';
            if (isContainer && hasNoValue) {
                warningHtml = `
                    <div style="background: #fef2f2; border: 1px solid #f87171; border-radius: 8px; padding: 12px; margin-bottom: 16px;">
                        <strong style="color: #dc2626;">⚠️ Warning: This element may not work as a sensor</strong>
                        <p style="margin: 8px 0 0 0; color: #991b1b; font-size: 13px;">
                            <strong>${shortClass}</strong> is a container element with no text value.
                            Sensors need text elements (like TextView) to extract values from.
                        </p>
                    </div>
                `;
            } else if (hasNoValue) {
                warningHtml = `
                    <div style="background: #fffbeb; border: 1px solid #fbbf24; border-radius: 8px; padding: 12px; margin-bottom: 16px;">
                        <strong style="color: #b45309;">⚠️ Warning: Element has no text value</strong>
                        <p style="margin: 8px 0 0 0; color: #92400e; font-size: 13px;">
                            This element has no visible text. The sensor may not capture useful data.
                        </p>
                    </div>
                `;
            }

            // Element info box
            const elementInfoHtml = element ? `
                <div style="background: #f0f9ff; border: 1px solid #0ea5e9; border-radius: 8px; padding: 12px; margin-bottom: 16px;">
                    <strong style="color: #0369a1;">Selected Element:</strong>
                    <div style="margin-top: 8px; font-size: 13px; color: #0c4a6e;">
                        <div><strong>Type:</strong> ${shortClass}</div>
                        <div><strong>Value:</strong> "${elementText || elementContentDesc || '(empty)'}"</div>
                        ${element.resource_id ? `<div><strong>ID:</strong> ${element.resource_id.split('/').pop()}</div>` : ''}
                    </div>
                </div>
            ` : '';

            dialog.innerHTML = `
                <h3 style="margin-top: 0;">Configure ${sensorType === 'text' ? 'Text' : 'Image'} Sensor</h3>

                ${warningHtml}
                ${elementInfoHtml}

                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 4px; font-weight: 600;">Sensor Name:</label>
                    <input type="text" id="sensorName" value="${defaultName}"
                           style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                </div>

                ${sensorType === 'text' ? `
                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 4px; font-weight: 600;">Extraction Method:</label>
                    <select id="extractionMethod" style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                        <option value="exact">Exact Text (Default)</option>
                        <option value="regex">Regex Pattern</option>
                        <option value="before_after">Extract Between Text</option>
                        <option value="between">Extract Between Start/End</option>
                        <option value="numeric">Extract Number</option>
                    </select>
                </div>

                <div id="regexOptions" style="margin-bottom: 16px; display: none;">
                    <label style="display: block; margin-bottom: 4px; font-weight: 600;">Regex Pattern:</label>
                    <input type="text" id="regexPattern" placeholder="e.g., \\d+"
                           style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                </div>

                <div id="beforeAfterOptions" style="display: none;">
                    <div style="margin-bottom: 16px;">
                        <label style="display: block; margin-bottom: 4px; font-weight: 600;">Text Before:</label>
                        <input type="text" id="beforeText" placeholder="Optional"
                               style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>
                    <div style="margin-bottom: 16px;">
                        <label style="display: block; margin-bottom: 4px; font-weight: 600;">Text After:</label>
                        <input type="text" id="afterText" placeholder="Optional"
                               style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>
                </div>

                <div id="betweenOptions" style="display: none;">
                    <div style="margin-bottom: 16px;">
                        <label style="display: block; margin-bottom: 4px; font-weight: 600;">Start Marker:</label>
                        <input type="text" id="betweenStart" placeholder="e.g., <value>"
                               style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>
                    <div style="margin-bottom: 16px;">
                        <label style="display: block; margin-bottom: 4px; font-weight: 600;">End Marker:</label>
                        <input type="text" id="betweenEnd" placeholder="e.g., </value>"
                               style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>
                </div>

                <div id="numericOptions" style="margin-bottom: 16px; display: none;">
                    <label style="display: block; margin-bottom: 4px;">
                        <input type="checkbox" id="removeUnit">
                        Remove unit symbols (%, $, etc.)
                    </label>
                </div>
                ` : ''}

                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 4px; font-weight: 600;">Update Interval (seconds):</label>
                    <input type="number" id="updateInterval" value="60" min="10" max="3600"
                           style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                </div>

                <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 24px;">
                    <button id="cancelBtn" style="padding: 10px 20px; border: 1px solid #ccc; background: white; border-radius: 4px; cursor: pointer;">
                        Cancel
                    </button>
                    <button id="defaultsBtn" style="padding: 10px 20px; border: none; background: #6b7280; color: white; border-radius: 4px; cursor: pointer;">
                        Use Defaults
                    </button>
                    <button id="createBtn" style="padding: 10px 20px; border: none; background: #3b82f6; color: white; border-radius: 4px; cursor: pointer;">
                        Create Sensor
                    </button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            // Handle extraction method change
            const methodSelect = dialog.querySelector('#extractionMethod');
            if (methodSelect) {
                methodSelect.addEventListener('change', () => {
                    const method = methodSelect.value;
                    dialog.querySelector('#regexOptions').style.display = method === 'regex' ? 'block' : 'none';
                    dialog.querySelector('#beforeAfterOptions').style.display = method === 'before_after' ? 'block' : 'none';
                    dialog.querySelector('#betweenOptions').style.display = method === 'between' ? 'block' : 'none';
                    dialog.querySelector('#numericOptions').style.display = method === 'numeric' ? 'block' : 'none';
                });
            }

            // Handle button clicks
            dialog.querySelector('#cancelBtn').addEventListener('click', () => {
                document.body.removeChild(overlay);
                resolve(null);
            });

            dialog.querySelector('#defaultsBtn').addEventListener('click', () => {
                const name = dialog.querySelector('#sensorName').value.trim();
                if (!name) {
                    alert('Please enter a sensor name');
                    return;
                }
                document.body.removeChild(overlay);
                resolve({
                    name,
                    useDefaults: true,
                    updateInterval: 60
                });
            });

            dialog.querySelector('#createBtn').addEventListener('click', () => {
                const name = dialog.querySelector('#sensorName').value.trim();
                if (!name) {
                    alert('Please enter a sensor name');
                    return;
                }

                const config = {
                    name,
                    useDefaults: false,
                    updateInterval: parseInt(dialog.querySelector('#updateInterval').value) || 60
                };

                if (sensorType === 'text') {
                    const method = dialog.querySelector('#extractionMethod').value;
                    config.extractionMethod = method;

                    switch (method) {
                        case 'regex':
                            config.regexPattern = dialog.querySelector('#regexPattern').value.trim();
                            break;
                        case 'before_after':
                            config.beforeText = dialog.querySelector('#beforeText').value.trim() || null;
                            config.afterText = dialog.querySelector('#afterText').value.trim() || null;
                            break;
                        case 'between':
                            config.betweenStart = dialog.querySelector('#betweenStart').value.trim() || null;
                            config.betweenEnd = dialog.querySelector('#betweenEnd').value.trim() || null;
                            break;
                        case 'numeric':
                            config.removeUnit = dialog.querySelector('#removeUnit').checked;
                            config.extractNumeric = true;
                            break;
                    }
                }

                document.body.removeChild(overlay);
                resolve(config);
            });
        });
    }

    /**
     * Create text sensor via API
     */
    async createTextSensor(element, coords, deviceId, selectedApp) {
        // Show configuration dialog with element info
        const config = await this.promptForSensorConfig(element?.text || 'Text Sensor', 'text', element);
        if (!config) return null;

        try {
            const packageName = selectedApp?.package || selectedApp;

            // Build extraction rule based on config
            const extractionRule = {
                method: config.useDefaults ? 'exact' : (config.extractionMethod || 'exact'),
                regex_pattern: null,
                before_text: null,
                after_text: null,
                between_start: null,
                between_end: null,
                extract_numeric: false,
                remove_unit: false,
                fallback_value: null,
                pipeline: null
            };

            // Apply method-specific settings
            if (!config.useDefaults) {
                switch (config.extractionMethod) {
                    case 'regex':
                        extractionRule.regex_pattern = config.regexPattern || null;
                        break;
                    case 'before_after':
                        extractionRule.before_text = config.beforeText;
                        extractionRule.after_text = config.afterText;
                        break;
                    case 'between':
                        extractionRule.between_start = config.betweenStart;
                        extractionRule.between_end = config.betweenEnd;
                        break;
                    case 'numeric':
                        extractionRule.extract_numeric = true;
                        extractionRule.remove_unit = config.removeUnit || false;
                        break;
                }
            }

            const sensorDefinition = {
                device_id: deviceId,
                friendly_name: config.name,
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
                    element_content_desc: element?.content_desc || '',
                    custom_bounds: this.validateBounds(element?.bounds)
                },
                extraction_rule: extractionRule,
                update_interval_seconds: config.updateInterval || 60,
                enabled: true,
                target_app: packageName,
                prerequisite_actions: [],
                navigation_sequence: null,
                validation_element: null,
                return_home_after: true,
                max_navigation_attempts: 3,
                navigation_timeout: 10
            };

            const response = await fetch(`${this.apiBase}/sensors`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(sensorDefinition)
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

                throw new Error(error.detail || 'Failed to create sensor');
            }

            const result = await response.json();
            const createdSensor = result.sensor;

            console.log('[FlowInteractions] Created sensor:', createdSensor);
            showToast(`Sensor "${config.name}" created successfully`, 'success');

            return {
                sensor: createdSensor,
                step: {
                    step_type: 'capture_sensors',
                    sensor_ids: [createdSensor.sensor_id],
                    element: element || {},
                    x: coords.x,
                    y: coords.y,
                    description: `Capture ${config.name} sensor`
                }
            };

        } catch (error) {
            console.error('[FlowInteractions] Failed to create sensor:', error);
            showToast(`Failed to create sensor: ${error.message}`, 'error', 5000);
            return null;
        }
    }

    /**
     * Create image sensor via API
     */
    async createImageSensor(element, coords, deviceId, selectedApp) {
        // Show configuration dialog with element info
        const config = await this.promptForSensorConfig(element?.text || 'Image Sensor', 'image', element);
        if (!config) return null;

        try {
            const packageName = selectedApp?.package || selectedApp;

            const sensorDefinition = {
                device_id: deviceId,
                friendly_name: config.name,
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
                    element_content_desc: element?.content_desc || '',
                    custom_bounds: this.validateBounds(element?.bounds)
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
                update_interval_seconds: config.updateInterval || 60,
                enabled: true,
                target_app: packageName,
                prerequisite_actions: [],
                navigation_sequence: null,
                validation_element: null,
                return_home_after: true,
                max_navigation_attempts: 3,
                navigation_timeout: 10
            };

            const response = await fetch(`${this.apiBase}/sensors`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(sensorDefinition)
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

                throw new Error(error.detail || 'Failed to create sensor');
            }

            const result = await response.json();
            const createdSensor = result.sensor;

            console.log('[FlowInteractions] Created image sensor:', createdSensor);
            showToast(`Image sensor "${config.name}" created successfully`, 'success');

            return {
                sensor: createdSensor,
                step: {
                    step_type: 'capture_sensors',
                    sensor_ids: [createdSensor.sensor_id],
                    element: element || {},
                    x: coords.x,
                    y: coords.y,
                    crop_bounds: element?.bounds,
                    description: `Capture ${config.name} image`
                }
            };

        } catch (error) {
            console.error('[FlowInteractions] Failed to create image sensor:', error);
            showToast(`Failed to create image sensor: ${error.message}`, 'error', 5000);
            return null;
        }
    }

    /**
     * Container classes to filter out
     * Use Set for O(1) lookup instead of Array.includes() O(n)
     */
    static containerClasses = new Set([
        'android.view.View',
        'android.view.ViewGroup',
        'android.widget.FrameLayout',
        'android.widget.LinearLayout',
        'android.widget.RelativeLayout',
        'android.widget.TableLayout',
        'android.widget.TableRow',
        'android.widget.GridLayout',
        'android.widget.ScrollView',
        'android.widget.HorizontalScrollView',
        'android.widget.ListView',
        'android.widget.GridView',
        'android.widget.AbsoluteLayout',
        'androidx.constraintlayout.widget.ConstraintLayout',
        'androidx.recyclerview.widget.RecyclerView',
        'androidx.viewpager.widget.ViewPager',
        'androidx.viewpager2.widget.ViewPager2',
        'androidx.coordinatorlayout.widget.CoordinatorLayout',
        'androidx.drawerlayout.widget.DrawerLayout',
        'androidx.appcompat.widget.LinearLayoutCompat',
        'androidx.cardview.widget.CardView',
        'androidx.core.widget.NestedScrollView',
        'androidx.swiperefreshlayout.widget.SwipeRefreshLayout',
        'android.widget.Space',
        'android.view.ViewStub'
    ]);

    /**
     * Find element at specific coordinates with container filtering
     * Prefers elements with text, skips containers when filtering is enabled
     * @param {Array} elements - UI elements
     * @param {number} x - Device X coordinate
     * @param {number} y - Device Y coordinate
     * @param {Object} filters - Filter options { hideContainers, hideEmptyElements }
     * @returns {Object|null} Best matching element or null
     */
    findElementAtCoordinates(elements, x, y, filters = {}) {
        if (!elements) return null;

        const hideContainers = filters.hideContainers !== false; // Default true
        const hideEmptyElements = filters.hideEmptyElements !== false; // Default true

        let bestMatch = null;

        // Search from end (top z-order) to beginning
        for (let i = elements.length - 1; i >= 0; i--) {
            const el = elements[i];
            const bounds = el.bounds || {};
            const elX = bounds.x || 0;
            const elY = bounds.y || 0;
            const elWidth = bounds.width || 0;
            const elHeight = bounds.height || 0;

            // Check if point is within bounds
            if (!(x >= elX && x <= elX + elWidth &&
                  y >= elY && y <= elY + elHeight)) {
                continue;
            }

            // Check element properties
            const hasText = el.text && el.text.trim();
            const hasContentDesc = el.content_desc && el.content_desc.trim();
            const hasResourceId = el.resource_id && el.resource_id.trim();
            const isContainer = el.class && FlowInteractions.containerClasses.has(el.class);

            // Skip containers if filter is on (BUT keep clickable containers - they're usually buttons)
            if (hideContainers && isContainer) {
                const isUsefulContainer = el.clickable || hasResourceId;
                if (!isUsefulContainer) continue;
            }

            // Skip empty elements if filter is on (except clickable buttons with resource-id)
            if (hideEmptyElements) {
                if (!hasText && !hasContentDesc && !(el.clickable && hasResourceId)) {
                    continue;
                }
            }

            // Prefer elements with text
            if (hasText || hasContentDesc) {
                return el; // Return immediately if has text
            }

            // Keep as backup if it's clickable
            if (el.clickable && !bestMatch) {
                bestMatch = el;
            }
        }

        return bestMatch;
    }
}

// Dual export
export default FlowInteractions;
window.FlowInteractions = FlowInteractions;
