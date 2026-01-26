/**
 * Suggestions Module for Flow Wizard Step 3
 *
 * Handles:
 * - Suggestions tab UI and interactions
 * - Sensor and action suggestions loading
 * - Quick add and edit dialogs
 * - Bulk sensor addition
 * - Alternative name handling
 *
 * Extracted from flow-wizard-step3.js for maintainability
 * @version 0.0.1
 */

import { showToast } from '../toast.js?v=0.4.0-beta.4';

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped HTML
 */
export function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Setup the Suggestions tab in the right panel
 * @param {Object} wizard - Wizard instance
 */
export function setupSuggestionsTab(wizard) {
    console.log('[Suggestions] Setting up Suggestions tab');

    const refreshBtn = document.getElementById('refreshSuggestionsBtn');
    const selectAllBtn = document.getElementById('selectAllSuggestionsTabBtn');
    const addSelectedBtn = document.getElementById('addSelectedSuggestionsTabBtn');
    const modeTabs = document.querySelectorAll('.suggestions-toolbar .mode-tab');

    // Initialize state
    wizard._suggestionsMode = 'sensors';
    wizard._sensorSuggestions = [];
    wizard._actionSuggestions = [];
    wizard._selectedSuggestions = new Set();

    // Mode tab switching
    modeTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            modeTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            wizard._suggestionsMode = tab.dataset.mode;
            renderSuggestionsContent(wizard);
        });
    });

    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            await loadSuggestions(wizard);
        });
    }

    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => {
            const suggestions = wizard._suggestionsMode === 'sensors'
                ? wizard._sensorSuggestions
                : wizard._actionSuggestions;

            if (wizard._selectedSuggestions.size === suggestions.length) {
                wizard._selectedSuggestions.clear();
            } else {
                suggestions.forEach((_, i) => wizard._selectedSuggestions.add(i));
            }
            renderSuggestionsContent(wizard);
            updateSelectedCount(wizard);
        });
    }

    if (addSelectedBtn) {
        addSelectedBtn.addEventListener('click', async () => {
            await addSelectedSuggestions(wizard);
        });
    }

    console.log('[Suggestions] Setup complete');
}

/**
 * Load suggestions from the API
 * @param {Object} wizard - Wizard instance
 */
export async function loadSuggestions(wizard) {
    const suggestionsContent = document.getElementById('suggestionsContent');
    if (!suggestionsContent) return;

    if (!wizard.selectedDevice) {
        suggestionsContent.innerHTML = '<div class="suggestions-empty"><p>No device selected</p></div>';
        return;
    }

    suggestionsContent.innerHTML = '<div class="suggestions-loading"><div class="spinner"></div><p>Analyzing screen...</p></div>';

    try {
        // Load sensor suggestions
        const sensorResponse = await fetch(`${getApiBase()}/devices/suggest-sensors`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: wizard.selectedDevice,
                package_name: wizard.selectedApp?.package || null
            })
        });

        if (sensorResponse.ok) {
            const sensorData = await sensorResponse.json();
            wizard._sensorSuggestions = sensorData.suggestions || [];
            const sensorCountEl = document.getElementById('sensorSuggestionsCount');
            if (sensorCountEl) sensorCountEl.textContent = wizard._sensorSuggestions.length;
        }

        // Load action suggestions
        const actionResponse = await fetch(`${getApiBase()}/devices/suggest-actions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: wizard.selectedDevice,
                package_name: wizard.selectedApp?.package || null
            })
        });

        if (actionResponse.ok) {
            const actionData = await actionResponse.json();
            wizard._actionSuggestions = actionData.suggestions || [];
            const actionCountEl = document.getElementById('actionSuggestionsCount');
            if (actionCountEl) actionCountEl.textContent = wizard._actionSuggestions.length;
        }

        // Update total count
        const totalCount = wizard._sensorSuggestions.length + wizard._actionSuggestions.length;
        const totalCountEl = document.getElementById('suggestionsCount');
        if (totalCountEl) totalCountEl.textContent = totalCount;

        wizard._selectedSuggestions.clear();
        renderSuggestionsContent(wizard);
        updateSelectedCount(wizard);

    } catch (error) {
        console.error('[Suggestions] Failed to load:', error);
        suggestionsContent.innerHTML = `<div class="suggestions-empty"><p>Failed to load suggestions: ${error.message}</p></div>`;
    }
}

/**
 * Handle alternative name click
 * @param {Object} wizard - Wizard instance
 * @param {number} index - Suggestion index
 * @param {string} altName - Alternative name selected
 */
export function handleAlternativeNameClick(wizard, index, altName) {
    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    const suggestion = suggestions[index];
    if (!suggestion) return;

    const oldName = suggestion.name || suggestion.suggested_name;
    suggestion.name = altName;
    suggestion.suggested_name = altName;

    if (suggestion.alternative_names) {
        suggestion.alternative_names = suggestion.alternative_names.filter(
            alt => alt.name.toLowerCase() !== altName.toLowerCase()
        );
        if (!suggestion.alternative_names.some(alt => alt.name.toLowerCase() === oldName.toLowerCase())) {
            suggestion.alternative_names.unshift({
                name: oldName,
                location: 'previous',
                score: 100
            });
        }
    }

    renderSuggestionsContent(wizard);
    showToast(`Name changed to "${altName}"`, 'success', 2000);
}

/**
 * Highlight suggestion element on screenshot
 * @param {Object} wizard - Wizard instance
 * @param {Object} suggestion - Suggestion object
 */
export function highlightSuggestionElement(wizard, suggestion) {
    if (!wizard || !suggestion?.element?.bounds) return;

    import('../canvas-overlay-renderer.js').then(module => {
        const element = {
            bounds: suggestion.element.bounds,
            text: suggestion.element.text,
            class: suggestion.element.class
        };
        module.highlightHoveredElement(wizard, element);
    }).catch(err => {
        console.warn('[Suggestions] Could not highlight element:', err);
    });
}

/**
 * Clear suggestion highlight
 * @param {Object} wizard - Wizard instance
 */
export function clearSuggestionHighlight(wizard) {
    if (!wizard) return;

    import('../canvas-overlay-renderer.js').then(module => {
        module.clearHoverHighlight(wizard);
    }).catch(err => console.warn('[Suggestions] Failed to clear highlight:', err));
}

/**
 * Render the suggestions content
 * @param {Object} wizard - Wizard instance
 * @param {Object} callbacks - Optional callbacks
 */
export function renderSuggestionsContent(wizard, callbacks = {}) {
    const suggestionsContent = document.getElementById('suggestionsContent');
    if (!suggestionsContent) return;

    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    if (suggestions.length === 0) {
        suggestionsContent.innerHTML = `
            <div class="suggestions-empty">
                <p>No ${wizard._suggestionsMode} found on current screen</p>
                <p class="hint">Try scrolling or navigating to a different screen</p>
            </div>
        `;
        return;
    }

    const iconEmoji = {
        'mdi:thermometer': '🌡️',
        'mdi:water-percent': '💧',
        'mdi:battery': '🔋',
        'mdi:lightning-bolt': '⚡',
        'mdi:current-ac': '🔌',
        'mdi:flash': '💡',
        'mdi:speedometer': '🚗',
        'mdi:map-marker-distance': '📍',
        'mdi:signal': '📶',
        'mdi:toggle-switch': '🔘',
        'mdi:gesture-tap': '👆',
        'mdi:gesture-tap-button': '🔘',
        'mdi:form-textbox': '📝',
        'mdi:checkbox-marked': '☑️',
        'mdi:timer': '⏱️',
        'mdi:percent': '📊',
        'mdi:clock': '🕐'
    };

    const locationIcons = {
        'above': '⬆️',
        'below': '⬇️',
        'left': '⬅️',
        'right': '➡️',
        'resource_id': '🏷️',
        'pattern': '🔍',
        'content_desc': '📝',
        'previous': '↩️'
    };

    const itemsHtml = suggestions.map((suggestion, index) => {
        const isSelected = wizard._selectedSuggestions.has(index);
        const icon = wizard._suggestionsMode === 'sensors'
            ? (suggestion.icon || 'mdi:eye')
            : (suggestion.icon || 'mdi:gesture-tap');

        const currentValue = suggestion.current_value || '';
        const elementText = suggestion.element?.text || suggestion.text || '';
        const displayValue = currentValue || elementText || '--';
        const unit = suggestion.unit_of_measurement || '';
        const deviceClass = suggestion.device_class || suggestion.pattern_type || '';
        const confidence = suggestion.confidence ? Math.round(suggestion.confidence * 100) : 0;
        const displayIcon = iconEmoji[icon] || '📊';

        let alternativeNamesHtml = '';
        if (suggestion.alternative_names && suggestion.alternative_names.length > 0) {
            const altOptions = suggestion.alternative_names.map(alt => {
                const locIcon = locationIcons[alt.location] || '📍';
                return `<option value="${escapeHtml(alt.name)}" title="${alt.location}: score ${alt.score}">${locIcon} ${escapeHtml(alt.name)}</option>`;
            }).join('');

            alternativeNamesHtml = `
                <div class="suggestion-alt-names">
                    <select class="alt-name-select" data-index="${index}">
                        <option value="" disabled selected>Select name...</option>
                        ${altOptions}
                    </select>
                </div>
            `;
        }

        return `
            <div class="suggestion-item ${isSelected ? 'selected' : ''}" data-index="${index}">
                <label class="suggestion-checkbox">
                    <input type="checkbox" ${isSelected ? 'checked' : ''}>
                </label>
                <div class="suggestion-icon">${displayIcon}</div>
                <div class="suggestion-details">
                    <div class="suggestion-name">${escapeHtml(suggestion.name || suggestion.suggested_name || 'Unnamed')}</div>
                    <div class="suggestion-value-big">${escapeHtml(displayValue)}${unit ? ' ' + escapeHtml(unit) : ''}</div>
                    ${alternativeNamesHtml}
                    <div class="suggestion-meta">
                        <span class="suggestion-device-class">${escapeHtml(deviceClass)}</span>
                        <span class="suggestion-confidence">${confidence}%</span>
                    </div>
                </div>
                <div class="suggestion-buttons">
                    <button class="btn-edit" data-index="${index}" title="Edit before adding">Edit</button>
                    <button class="btn-quick-add" data-index="${index}" title="Add with defaults">+ Add</button>
                </div>
            </div>
        `;
    }).join('');

    suggestionsContent.innerHTML = `<div class="suggestions-list">${itemsHtml}</div>`;

    // Wire up event handlers
    suggestionsContent.querySelectorAll('.suggestion-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.closest('.suggestion-buttons') || e.target.closest('.alt-name-select')) return;

            const index = parseInt(item.dataset.index);
            if (wizard._selectedSuggestions.has(index)) {
                wizard._selectedSuggestions.delete(index);
                item.classList.remove('selected');
                item.querySelector('input[type="checkbox"]').checked = false;
            } else {
                wizard._selectedSuggestions.add(index);
                item.classList.add('selected');
                item.querySelector('input[type="checkbox"]').checked = true;
            }
            updateSelectedCount(wizard);
        });

        item.addEventListener('mouseenter', () => {
            const index = parseInt(item.dataset.index);
            const suggestion = suggestions[index];
            if (suggestion) highlightSuggestionElement(wizard, suggestion);
        });

        item.addEventListener('mouseleave', () => {
            clearSuggestionHighlight(wizard);
        });
    });

    suggestionsContent.querySelectorAll('.btn-edit').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            handleEditSuggestion(wizard, index, callbacks);
        });
    });

    suggestionsContent.querySelectorAll('.btn-quick-add').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            handleQuickAddSuggestion(wizard, index, callbacks);
        });
    });

    suggestionsContent.querySelectorAll('.alt-name-select').forEach(select => {
        select.addEventListener('change', (e) => {
            e.stopPropagation();
            const index = parseInt(select.dataset.index);
            const altName = e.target.value;
            if (altName) {
                handleAlternativeNameClick(wizard, index, altName);
                select.selectedIndex = 0;
            }
        });
    });
}

/**
 * Handle Edit button click
 * @param {Object} wizard - Wizard instance
 * @param {number} index - Suggestion index
 * @param {Object} callbacks - Callbacks for external functions
 */
export function handleEditSuggestion(wizard, index, callbacks = {}) {
    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    const suggestion = suggestions[index];
    if (!suggestion) return;

    if (wizard._suggestionsMode === 'sensors') {
        const element = suggestion.element || {
            text: suggestion.current_value || suggestion.name,
            bounds: suggestion.bounds,
            resource_id: suggestion.resource_id,
            class: suggestion.element_class,
            index: suggestion.element_index || 0
        };

        const screenActivity = wizard.recorder?.currentScreenActivity || wizard.currentActivity || null;

        wizard.sensorCreator.show(wizard.selectedDevice, element, element.index || 0, {
            stableDeviceId: wizard.selectedDeviceStableId || wizard.selectedDevice,
            screenActivity: screenActivity,
            targetApp: wizard.selectedApp?.package || null,
            name: suggestion.name || suggestion.suggested_name,
            device_class: suggestion.device_class || 'none',
            unit: suggestion.unit_of_measurement || '',
            icon: suggestion.icon || 'mdi:eye'
        });

        console.log('[Suggestions] Opened SensorCreator for:', suggestion.name);
    } else {
        showSuggestionEditDialog(wizard, suggestion, index, callbacks);
    }
}

/**
 * Handle Quick Add button click
 * @param {Object} wizard - Wizard instance
 * @param {number} index - Suggestion index
 * @param {Object} callbacks - Callbacks for external functions
 */
export async function handleQuickAddSuggestion(wizard, index, callbacks = {}) {
    const { addSensorWithNavigationCheck, buildElementMetadata } = callbacks;

    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    const suggestion = suggestions[index];
    if (!suggestion) return;

    if (wizard._suggestionsMode === 'sensors') {
        const sensorName = suggestion.name || suggestion.suggested_name || 'Sensor';

        try {
            const hasUnit = suggestion.unit_of_measurement && suggestion.unit_of_measurement.trim() !== '';
            const hasDeviceClass = suggestion.device_class && suggestion.device_class !== 'none';
            const sensorData = {
                device_id: wizard.selectedDevice,
                stable_device_id: wizard.selectedDeviceStableId || null,
                friendly_name: sensorName,
                sensor_type: 'sensor',
                device_class: suggestion.device_class || 'none',
                state_class: (hasDeviceClass && hasUnit) ? 'measurement' : 'none',
                unit_of_measurement: hasUnit ? suggestion.unit_of_measurement : null,
                icon: suggestion.icon || 'mdi:eye',
                target_app: wizard.selectedApp?.package || null,
                source: {
                    source_type: 'element',
                    element_index: suggestion.element?.index || 0,
                    element_text: suggestion.element?.text || null,
                    element_class: suggestion.element?.class || null,
                    element_resource_id: suggestion.element?.resource_id || null,
                    screen_activity: wizard.recorder?.currentScreenActivity || wizard.currentActivity || null,
                    custom_bounds: suggestion.element?.bounds || null
                },
                extraction_rule: {
                    method: 'exact',
                    extract_numeric: hasDeviceClass && ['battery', 'temperature', 'humidity', 'voltage', 'current', 'power', 'energy'].includes(suggestion.device_class)
                }
            };

            const response = await wizard.apiClient.post('/sensors', sensorData);
            console.log('[Suggestions] Sensor created/reused:', response);

            const sensorId = response?.sensor?.sensor_id || response?.sensor_id;
            if (!sensorId) throw new Error('No sensor_id in response');

            const sensorStep = {
                step_type: 'capture_sensors',
                description: `Capture: ${sensorName}`,
                sensor_ids: [sensorId]
            };

            if (addSensorWithNavigationCheck) {
                const added = await addSensorWithNavigationCheck(wizard, sensorStep);
                if (added) {
                    const wasReused = response?.reused;
                    showToast(`${wasReused ? 'Reused' : 'Created'} sensor: ${sensorName}`, 'success');
                }
            } else {
                wizard.recorder.addStep(sensorStep);
                showToast(`Created sensor: ${sensorName}`, 'success');
            }
        } catch (error) {
            console.error('[Suggestions] Failed to create sensor:', error);
            showToast(`Failed to create sensor: ${error.message}`, 'error');
        }
    } else {
        if (suggestion.element?.bounds) {
            const tapStep = {
                step_type: 'tap',
                x: Math.round(suggestion.element.bounds.x + suggestion.element.bounds.width / 2),
                y: Math.round(suggestion.element.bounds.y + suggestion.element.bounds.height / 2),
                description: suggestion.name || suggestion.suggested_name || 'Tap action',
                element: buildElementMetadata ? buildElementMetadata(suggestion.element) : suggestion.element
            };
            wizard.recorder.addStep(tapStep);
            showToast(`Added action: ${suggestion.name || 'Tap'}`, 'success');
        }
    }

    wizard.updateFlowStepsUI();
}

/**
 * Show edit dialog for a suggestion
 * @param {Object} wizard - Wizard instance
 * @param {Object} suggestion - Suggestion object
 * @param {number} index - Suggestion index
 * @param {Object} callbacks - Callbacks for external functions
 */
export function showSuggestionEditDialog(wizard, suggestion, index, callbacks = {}) {
    const { addSensorWithNavigationCheck } = callbacks;

    const dialogOverlay = document.createElement('div');
    dialogOverlay.className = 'dialog-overlay suggestion-edit-dialog-overlay';
    dialogOverlay.innerHTML = `
        <div class="dialog suggestion-edit-dialog">
            <div class="dialog-header">
                <h3>Edit ${wizard._suggestionsMode === 'sensors' ? 'Sensor' : 'Action'}</h3>
                <button class="dialog-close">&times;</button>
            </div>
            <div class="dialog-body">
                <div class="form-group">
                    <label>Name</label>
                    <input type="text" id="editSuggestionName" value="${suggestion.name || suggestion.suggested_name || ''}" placeholder="Enter name">
                </div>
                ${wizard._suggestionsMode === 'sensors' ? `
                    <div class="form-group">
                        <label>Device Class</label>
                        <select id="editSuggestionDeviceClass">
                            <option value="none" ${suggestion.device_class === 'none' ? 'selected' : ''}>None</option>
                            <option value="battery" ${suggestion.device_class === 'battery' ? 'selected' : ''}>Battery</option>
                            <option value="temperature" ${suggestion.device_class === 'temperature' ? 'selected' : ''}>Temperature</option>
                            <option value="humidity" ${suggestion.device_class === 'humidity' ? 'selected' : ''}>Humidity</option>
                            <option value="voltage" ${suggestion.device_class === 'voltage' ? 'selected' : ''}>Voltage</option>
                            <option value="current" ${suggestion.device_class === 'current' ? 'selected' : ''}>Current</option>
                            <option value="power" ${suggestion.device_class === 'power' ? 'selected' : ''}>Power</option>
                            <option value="energy" ${suggestion.device_class === 'energy' ? 'selected' : ''}>Energy</option>
                            <option value="speed" ${suggestion.device_class === 'speed' ? 'selected' : ''}>Speed</option>
                            <option value="distance" ${suggestion.device_class === 'distance' ? 'selected' : ''}>Distance</option>
                            <option value="signal_strength" ${suggestion.device_class === 'signal_strength' ? 'selected' : ''}>Signal Strength</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Unit of Measurement</label>
                        <input type="text" id="editSuggestionUnit" value="${suggestion.unit_of_measurement || ''}" placeholder="e.g., %, °C, km">
                    </div>
                ` : `
                    <div class="form-group">
                        <label>Action Type</label>
                        <select id="editSuggestionActionType">
                            <option value="tap" ${suggestion.action_type === 'tap' ? 'selected' : ''}>Tap</option>
                            <option value="toggle" ${suggestion.action_type === 'toggle' ? 'selected' : ''}>Toggle</option>
                            <option value="input_text" ${suggestion.action_type === 'input_text' ? 'selected' : ''}>Input Text</option>
                            <option value="swipe" ${suggestion.action_type === 'swipe' ? 'selected' : ''}>Swipe</option>
                        </select>
                    </div>
                `}
                <div class="suggestion-preview">
                    <strong>Current Value:</strong> ${suggestion.current_value || suggestion.element?.text || 'N/A'}
                </div>
            </div>
            <div class="dialog-footer">
                <button class="btn btn-secondary dialog-cancel">Cancel</button>
                <button class="btn btn-primary dialog-save">Add to Flow</button>
            </div>
        </div>
    `;

    document.body.appendChild(dialogOverlay);

    dialogOverlay.querySelector('.dialog-close').addEventListener('click', () => dialogOverlay.remove());
    dialogOverlay.querySelector('.dialog-cancel').addEventListener('click', () => dialogOverlay.remove());

    dialogOverlay.querySelector('.dialog-save').addEventListener('click', async () => {
        const name = document.getElementById('editSuggestionName').value.trim();

        if (wizard._suggestionsMode === 'sensors') {
            const deviceClass = document.getElementById('editSuggestionDeviceClass').value;
            const unit = document.getElementById('editSuggestionUnit').value.trim();
            const sensorName = name || 'Sensor';

            try {
                const hasUnit = unit && unit.trim() !== '';
                const hasDeviceClass = deviceClass && deviceClass !== 'none';
                const sensorData = {
                    device_id: wizard.selectedDevice,
                    stable_device_id: wizard.selectedDeviceStableId || null,
                    friendly_name: sensorName,
                    sensor_type: 'sensor',
                    device_class: deviceClass || 'none',
                    state_class: (hasDeviceClass && hasUnit) ? 'measurement' : 'none',
                    unit_of_measurement: hasUnit ? unit : null,
                    icon: suggestion.icon || 'mdi:eye',
                    target_app: wizard.selectedApp?.package || null,
                    source: {
                        source_type: 'element',
                        element_index: suggestion.element?.index || 0,
                        element_text: suggestion.element?.text || null,
                        element_class: suggestion.element?.class || null,
                        element_resource_id: suggestion.element?.resource_id || null,
                        screen_activity: wizard.recorder?.currentScreenActivity || wizard.currentActivity || null,
                        custom_bounds: suggestion.element?.bounds || null
                    },
                    extraction_rule: {
                        method: 'exact',
                        extract_numeric: hasDeviceClass && ['battery', 'temperature', 'humidity', 'voltage', 'current', 'power', 'energy'].includes(deviceClass)
                    }
                };

                const response = await wizard.apiClient.post('/sensors', sensorData);
                const sensorId = response?.sensor?.sensor_id || response?.sensor_id;
                if (!sensorId) throw new Error('No sensor_id in response');

                const sensorStep = {
                    step_type: 'capture_sensors',
                    description: `Capture: ${sensorName}`,
                    sensor_ids: [sensorId]
                };

                if (addSensorWithNavigationCheck) {
                    const added = await addSensorWithNavigationCheck(wizard, sensorStep);
                    if (added) {
                        const wasReused = response?.reused;
                        showToast(`${wasReused ? 'Reused' : 'Created'} sensor: ${sensorName}`, 'success');
                    }
                } else {
                    wizard.recorder.addStep(sensorStep);
                    showToast(`Created sensor: ${sensorName}`, 'success');
                }
            } catch (error) {
                console.error('[Suggestions Edit] Failed to create sensor:', error);
                showToast(`Failed to create sensor: ${error.message}`, 'error');
            }
        } else {
            const actionType = document.getElementById('editSuggestionActionType').value;

            if (suggestion.element?.bounds) {
                const tapStep = {
                    step_type: actionType,
                    x: Math.round(suggestion.element.bounds.x + suggestion.element.bounds.width / 2),
                    y: Math.round(suggestion.element.bounds.y + suggestion.element.bounds.height / 2),
                    description: name || 'Action'
                };
                wizard.recorder.addStep(tapStep);
                showToast(`Added action: ${name}`, 'success');
            }
        }

        wizard.updateFlowStepsUI();
        dialogOverlay.remove();
    });

    dialogOverlay.addEventListener('click', (e) => {
        if (e.target === dialogOverlay) dialogOverlay.remove();
    });
}

/**
 * Update selected count display
 * @param {Object} wizard - Wizard instance
 */
export function updateSelectedCount(wizard) {
    const countEl = document.getElementById('selectedSuggestionsCount');
    if (countEl) {
        countEl.textContent = wizard._selectedSuggestions.size;
    }
}

/**
 * Add selected suggestions to flow
 * @param {Object} wizard - Wizard instance
 * @param {Object} callbacks - Callbacks for external functions
 */
export async function addSelectedSuggestions(wizard, callbacks = {}) {
    const { switchToTab, buildElementMetadata } = callbacks;

    if (wizard._selectedSuggestions.size === 0) {
        showToast('No suggestions selected', 'warning');
        return;
    }

    const suggestions = wizard._suggestionsMode === 'sensors'
        ? wizard._sensorSuggestions
        : wizard._actionSuggestions;

    const selectedItems = Array.from(wizard._selectedSuggestions).map(i => suggestions[i]);

    if (wizard._suggestionsMode === 'sensors') {
        let createdCount = 0;
        let reusedCount = 0;
        let failedCount = 0;

        for (const sensor of selectedItems) {
            const sensorName = sensor.name || sensor.suggested_name || 'Sensor';

            try {
                const hasUnit = sensor.unit_of_measurement && sensor.unit_of_measurement.trim() !== '';
                const hasDeviceClass = sensor.device_class && sensor.device_class !== 'none';
                const sensorData = {
                    device_id: wizard.selectedDevice,
                    stable_device_id: wizard.selectedDeviceStableId || null,
                    friendly_name: sensorName,
                    sensor_type: 'sensor',
                    device_class: sensor.device_class || 'none',
                    state_class: (hasDeviceClass && hasUnit) ? 'measurement' : 'none',
                    unit_of_measurement: hasUnit ? sensor.unit_of_measurement : null,
                    icon: sensor.icon || 'mdi:eye',
                    target_app: wizard.selectedApp?.package || null,
                    source: {
                        source_type: 'element',
                        element_index: sensor.element?.index || 0,
                        element_text: sensor.element?.text || null,
                        element_class: sensor.element?.class || null,
                        element_resource_id: sensor.element?.resource_id || null,
                        screen_activity: wizard.recorder?.currentScreenActivity || wizard.currentActivity || null,
                        custom_bounds: sensor.element?.bounds || null
                    },
                    extraction_rule: {
                        method: 'exact',
                        extract_numeric: hasDeviceClass && ['battery', 'temperature', 'humidity', 'voltage', 'current', 'power', 'energy'].includes(sensor.device_class)
                    }
                };

                const response = await wizard.apiClient.post('/sensors', sensorData);
                const sensorId = response?.sensor?.sensor_id || response?.sensor_id;
                if (!sensorId) throw new Error('No sensor_id in response');

                const sensorStep = {
                    step_type: 'capture_sensors',
                    description: `Capture: ${sensorName}`,
                    sensor_ids: [sensorId]
                };
                wizard.recorder.addStep(sensorStep);

                if (response?.reused) reusedCount++;
                else createdCount++;
            } catch (error) {
                console.error(`[Suggestions Batch] Failed to create sensor ${sensorName}:`, error);
                failedCount++;
            }
        }

        const parts = [];
        if (createdCount > 0) parts.push(`${createdCount} created`);
        if (reusedCount > 0) parts.push(`${reusedCount} reused`);
        if (failedCount > 0) parts.push(`${failedCount} failed`);
        showToast(`Sensors: ${parts.join(', ')}`, failedCount > 0 ? 'warning' : 'success');
    } else {
        for (const action of selectedItems) {
            if (action.element?.bounds) {
                const tapStep = {
                    step_type: 'tap',
                    x: Math.round(action.element.bounds.x + action.element.bounds.width / 2),
                    y: Math.round(action.element.bounds.y + action.element.bounds.height / 2),
                    description: action.name || action.suggested_name || 'Tap action',
                    element: buildElementMetadata ? buildElementMetadata(action.element) : action.element
                };
                wizard.recorder.addStep(tapStep);
            }
        }
        showToast(`Added ${selectedItems.length} action(s) to flow`, 'success');
    }

    wizard.updateFlowStepsUI();
    wizard._selectedSuggestions.clear();
    renderSuggestionsContent(wizard);
    updateSelectedCount(wizard);

    if (switchToTab) switchToTab(wizard, 'flow');
}

/**
 * Handle Smart Suggestions button click
 * @param {Object} wizard - Wizard instance
 */
export async function handleSmartSuggestions(wizard) {
    if (!wizard.selectedDevice) {
        showToast('Please select a device first', 'warning');
        return;
    }

    // Switch to Suggestions tab (external function needed)
    if (wizard.switchToTab) {
        wizard.switchToTab(wizard, 'suggestions');
    }

    if (!wizard._suggestionsTabInitialized) {
        setupSuggestionsTab(wizard);
        wizard._suggestionsTabInitialized = true;
    }

    await loadSuggestions(wizard);
}

/**
 * Handle bulk sensor addition
 * @param {Object} wizard - Wizard instance
 * @param {Array} sensors - Array of sensor objects
 * @param {Object} callbacks - Callbacks for external functions
 */
export async function handleBulkSensorAddition(wizard, sensors, callbacks = {}) {
    const { checkScreenMismatch, showNavigationMismatchDialog } = callbacks;

    console.log('[Suggestions] Adding bulk sensors:', sensors);
    if (sensors.length === 0) return;

    const firstSensor = sensors[0];
    const dummyStep = {
        step_type: 'capture_sensors',
        description: `Capture: ${firstSensor.name}`,
        element: firstSensor.element
    };

    if (checkScreenMismatch) {
        const mismatchInfo = await checkScreenMismatch(wizard, dummyStep);

        if (mismatchInfo && showNavigationMismatchDialog) {
            const choice = await showNavigationMismatchDialog(wizard, mismatchInfo);

            if (choice === 'cancel') {
                showToast('Bulk sensor addition cancelled', 'info');
                return;
            }

            if (choice === 'add_nav' && wizard._lastExecutedAction) {
                const navStep = { ...wizard._lastExecutedAction };
                delete navStep._timestamp;
                wizard.recorder.addStep(navStep);
                console.log('[Suggestions] Added navigation step before bulk sensors:', navStep);
            }
        }
    }

    let createdCount = 0;
    let reusedCount = 0;
    let failedCount = 0;

    for (const sensor of sensors) {
        const sensorName = sensor.name || 'Sensor';

        try {
            const hasUnit = sensor.unit_of_measurement && sensor.unit_of_measurement.trim() !== '';
            const hasDeviceClass = sensor.device_class && sensor.device_class !== 'none';
            const sensorData = {
                device_id: wizard.selectedDevice,
                stable_device_id: wizard.selectedDeviceStableId || null,
                friendly_name: sensorName,
                sensor_type: 'sensor',
                device_class: sensor.device_class || 'none',
                state_class: (hasDeviceClass && hasUnit) ? 'measurement' : 'none',
                unit_of_measurement: hasUnit ? sensor.unit_of_measurement : null,
                icon: sensor.icon || 'mdi:eye',
                target_app: wizard.selectedApp?.package || null,
                source: {
                    source_type: 'element',
                    element_index: sensor.element?.index || 0,
                    element_text: sensor.element?.text || null,
                    element_class: sensor.element?.class || null,
                    element_resource_id: sensor.element?.resource_id || null,
                    screen_activity: wizard.recorder?.currentScreenActivity || wizard.currentActivity || null,
                    custom_bounds: sensor.element?.bounds || null
                },
                extraction_rule: {
                    method: 'exact',
                    extract_numeric: hasDeviceClass && ['battery', 'temperature', 'humidity', 'voltage', 'current', 'power', 'energy'].includes(sensor.device_class)
                }
            };

            const response = await wizard.apiClient.post('/sensors', sensorData);
            const sensorId = response?.sensor?.sensor_id || response?.sensor_id;
            if (!sensorId) throw new Error('No sensor_id in response');

            const sensorStep = {
                step_type: 'capture_sensors',
                description: `Capture: ${sensorName}`,
                sensor_ids: [sensorId]
            };
            wizard.recorder.addStep(sensorStep);

            if (response?.reused) reusedCount++;
            else createdCount++;
        } catch (error) {
            console.error(`[Bulk Sensors] Failed to create sensor ${sensorName}:`, error);
            failedCount++;
        }
    }

    wizard.updateFlowStepsUI();

    const parts = [];
    if (createdCount > 0) parts.push(`${createdCount} created`);
    if (reusedCount > 0) parts.push(`${reusedCount} reused`);
    if (failedCount > 0) parts.push(`${failedCount} failed`);
    showToast(`Sensors: ${parts.join(', ')}`, failedCount > 0 ? 'warning' : 'success');
}
