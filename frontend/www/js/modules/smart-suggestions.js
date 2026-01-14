/**
 * Smart Suggestions Panel - AI-powered sensor and action detection
 *
 * Analyzes UI elements and suggests Home Assistant sensors/actions
 * based on pattern detection heuristics.
 */

import { getApiBase } from './api-base-detection.js?v=0.4.0-beta.2.6';
import { showToast } from './toast.js?v=0.4.0-beta.2.6';

class SmartSuggestions {
    constructor() {
        this.sensorSuggestions = [];
        this.actionSuggestions = [];
        this.selectedSuggestions = new Set();
        this.currentMode = 'sensors';  // 'sensors' or 'actions'
        this.onSensorsAdded = null;  // Callback when sensors are created
        this.onActionsAdded = null;  // Callback when actions are created
        this.editModal = null;  // Edit dialog
        this.editingSuggestion = null;  // Currently editing suggestion
        this.deviceClasses = null;  // Device classes from API

        // Load device classes
        this._loadDeviceClasses();
    }

    /**
     * Load device class reference from API
     * @private
     */
    async _loadDeviceClasses() {
        try {
            const response = await fetch(`${getApiBase()}/device-classes`);
            this.deviceClasses = await response.json();
            console.log('[SmartSuggestions] Loaded device classes:', this.deviceClasses);
        } catch (error) {
            console.error('[SmartSuggestions] Error loading device classes:', error);
        }
    }

    /**
     * Show smart suggestions modal for a device
     * @param {Object} wizard - FlowWizard instance (for opening full creator dialogs)
     * @param {string} deviceId - Device ID
     * @param {Function} onSensorsAdded - Callback(sensors[]) when sensors are added
     * @param {Function} onActionsAdded - Callback(actions[]) when actions are added
     */
    async show(wizard, deviceId, onSensorsAdded = null, onActionsAdded = null) {
        this.wizard = wizard;
        this.deviceId = deviceId;
        this.onSensorsAdded = onSensorsAdded;
        this.onActionsAdded = onActionsAdded;
        this.selectedSuggestions.clear();
        this.currentMode = 'sensors';  // Start with sensors tab

        try {
            // Fetch both sensor and action suggestions
            showToast('Analyzing UI elements...', 'info');
            await this.fetchAllSuggestions(deviceId);

            // Show modal
            this.renderModal();
            this.openModal();

        } catch (error) {
            console.error('[SmartSuggestions] Error showing suggestions:', error);
            showToast(`Failed to load suggestions: ${error.message}`, 'error');
        }
    }

    /**
     * Fetch both sensor and action suggestions from API
     * Note: The suggest endpoints automatically get fresh UI elements internally
     */
    async fetchAllSuggestions(deviceId) {
        console.log('[SmartSuggestions] Fetching sensor and action suggestions...');

        // Fetch sensors and actions in parallel
        const [sensorResponse, actionResponse] = await Promise.all([
            fetch(`${getApiBase()}/devices/suggest-sensors`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ device_id: deviceId })
            }),
            fetch(`${getApiBase()}/devices/suggest-actions`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ device_id: deviceId })
            })
        ]);

        if (!sensorResponse.ok || !actionResponse.ok) {
            throw new Error('Failed to fetch suggestions');
        }

        const sensorData = await sensorResponse.json();
        const actionData = await actionResponse.json();

        this.sensorSuggestions = sensorData.suggestions || [];
        this.actionSuggestions = actionData.suggestions || [];

        console.log(`[SmartSuggestions] Got ${this.sensorSuggestions.length} sensor suggestions, ${this.actionSuggestions.length} action suggestions`);
        console.log('[SmartSuggestions] Sensor suggestions:', JSON.stringify(this.sensorSuggestions, null, 2));
        console.log('[SmartSuggestions] Action suggestions:', JSON.stringify(this.actionSuggestions, null, 2));

        // Debug alternative names
        const sensorsWithAlts = this.sensorSuggestions.filter(s => s.alternative_names?.length > 0);
        console.log(`[SmartSuggestions] Sensors with alternative_names: ${sensorsWithAlts.length}/${this.sensorSuggestions.length}`);
        if (sensorsWithAlts.length > 0) {
            console.log('[SmartSuggestions] First sensor with alternatives:', sensorsWithAlts[0]);
        }

        const totalSuggestions = this.sensorSuggestions.length + this.actionSuggestions.length;
        if (totalSuggestions === 0) {
            showToast('No suggestions found', 'warning');
        } else {
            showToast(`Found ${totalSuggestions} suggestions!`, 'success');
        }
    }

    /**
     * Render the suggestions modal
     */
    renderModal() {
        // Check if modal already exists
        let modal = document.getElementById('smartSuggestionsModal');

        if (!modal) {
            // Create modal HTML
            modal = document.createElement('div');
            modal.id = 'smartSuggestionsModal';
            modal.className = 'modal-overlay';
            modal.innerHTML = `
                <div class="modal-content smart-suggestions-modal">
                    <div class="modal-header">
                        <h2>🤖 Smart Suggestions</h2>
                    </div>
                    <div class="suggestion-tabs">
                        <button type="button" class="tab-btn active" id="sensorsTabBtn">
                            📊 Sensors (<span id="sensorCount">0</span>)
                        </button>
                        <button type="button" class="tab-btn" id="actionsTabBtn">
                            ⚡ Actions (<span id="actionCount">0</span>)
                        </button>
                    </div>
                    <div class="modal-body">
                        <div id="modalSuggestionsContent"></div>
                    </div>
                    <div class="modal-actions">
                        <button type="button" class="btn btn-secondary" id="closeSuggestionsBtn">
                            Cancel
                        </button>
                        <button type="button" class="btn btn-secondary" id="selectAllSuggestionsBtn">
                            Select All
                        </button>
                        <button type="button" class="btn btn-primary" id="addSelectedSuggestionsBtn">
                            Add Selected (<span id="selectedCount">0</span>)
                        </button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            // Attach event listeners
            // Tab switching
            document.getElementById('sensorsTabBtn').addEventListener('click', () => {
                this.switchTab('sensors');
            });

            document.getElementById('actionsTabBtn').addEventListener('click', () => {
                this.switchTab('actions');
            });

            const cancelBtn = document.getElementById('closeSuggestionsBtn');
            console.log('[SmartSuggestions] Attaching cancel handler to:', cancelBtn);
            if (cancelBtn) {
                cancelBtn.addEventListener('click', (e) => {
                    console.log('[SmartSuggestions] Cancel button clicked!', e);
                    e.preventDefault();
                    e.stopPropagation();
                    this.closeModal();
                }, { capture: true }); // Use capture phase to ensure it fires
            } else {
                console.error('[SmartSuggestions] Cancel button not found!');
            }

            document.getElementById('selectAllSuggestionsBtn').addEventListener('click', () => {
                this.toggleSelectAll();
            });

            document.getElementById('addSelectedSuggestionsBtn').addEventListener('click', () => {
                this.addSelected();
            });

            // Close on background click
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeModal();
                }
            });
        }

        // Update counts
        this.updateCounts();

        // Render suggestions content
        this.renderSuggestions();
    }

    /**
     * Switch between sensors and actions tab
     */
    switchTab(mode) {
        this.currentMode = mode;
        this.selectedSuggestions.clear();

        // Update tab buttons
        const sensorsTab = document.getElementById('sensorsTabBtn');
        const actionsTab = document.getElementById('actionsTabBtn');

        if (mode === 'sensors') {
            sensorsTab.classList.add('active');
            actionsTab.classList.remove('active');
        } else {
            sensorsTab.classList.remove('active');
            actionsTab.classList.add('active');
        }

        // Re-render suggestions
        this.renderSuggestions();
    }

    /**
     * Update counts in tabs and selected counter
     */
    updateCounts() {
        const sensorCountSpan = document.getElementById('sensorCount');
        const actionCountSpan = document.getElementById('actionCount');

        if (sensorCountSpan) {
            sensorCountSpan.textContent = this.sensorSuggestions.length;
        }

        if (actionCountSpan) {
            actionCountSpan.textContent = this.actionSuggestions.length;
        }

        this.updateSelectedCount();
    }

    /**
     * Render suggestions list
     */
    renderSuggestions() {
        const container = document.getElementById('modalSuggestionsContent');

        // Get suggestions for current mode
        const suggestions = this.currentMode === 'sensors' ? this.sensorSuggestions : this.actionSuggestions;
        const itemType = this.currentMode === 'sensors' ? 'sensors' : 'actions';
        const emptyMessage = this.currentMode === 'sensors' ?
            'No sensor suggestions found on this screen. Try navigating to a screen with data like battery levels, temperatures, or status information.' :
            'No action suggestions found on this screen. Try navigating to a screen with buttons, switches, or input fields.';

        if (!suggestions || suggestions.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <p>${emptyMessage}</p>
                </div>
            `;
            return;
        }

        // Group suggestions by confidence level
        const highConfidence = suggestions.filter(s => s.confidence >= 0.8);
        const mediumConfidence = suggestions.filter(s => s.confidence >= 0.5 && s.confidence < 0.8);
        const lowConfidence = suggestions.filter(s => s.confidence < 0.5);

        let html = '';

        // High confidence suggestions (auto-selected)
        if (highConfidence.length > 0) {
            html += '<div class="suggestion-group">';
            html += '<h3>🎯 High Confidence Suggestions</h3>';
            html += `<p class="suggestion-group-desc">These are very likely to be useful ${itemType}.</p>`;
            html += highConfidence.map(s => this.renderSuggestionCard(s, true)).join('');
            html += '</div>';

            // Auto-select high confidence suggestions
            highConfidence.forEach(s => {
                this.selectedSuggestions.add(s.entity_id);
            });
        }

        // Medium confidence suggestions
        if (mediumConfidence.length > 0) {
            html += '<div class="suggestion-group">';
            html += '<h3>💡 Possible Sensors</h3>';
            html += '<p class="suggestion-group-desc">These might be useful depending on your needs.</p>';
            html += mediumConfidence.map(s => this.renderSuggestionCard(s, false)).join('');
            html += '</div>';
        }

        // Low confidence suggestions (collapsed by default)
        if (lowConfidence.length > 0) {
            html += '<div class="suggestion-group">';
            html += '<details>';
            html += '<summary>⚠️ Low Confidence Suggestions (${lowConfidence.length})</summary>';
            html += lowConfidence.map(s => this.renderSuggestionCard(s, false)).join('');
            html += '</details>';
            html += '</div>';
        }

        container.innerHTML = html;

        // Update selected count
        this.updateSelectedCount();

        // Attach checkbox event listeners
        container.querySelectorAll('.suggestion-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const entityId = e.target.dataset.entityId;
                if (e.target.checked) {
                    this.selectedSuggestions.add(entityId);
                } else {
                    this.selectedSuggestions.delete(entityId);
                }
                this.updateSelectedCount();
            });
        });

        // Attach edit button listeners
        container.querySelectorAll('.edit-suggestion-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const entityId = e.target.dataset.entityId;
                this.editSuggestion(entityId);
            });
        });

        // Attach alternative name dropdown listeners
        container.querySelectorAll('.alt-name-select').forEach(select => {
            select.addEventListener('change', (e) => {
                const newName = e.target.value;
                if (newName) {
                    const entityId = e.target.dataset.entityId;
                    this.useAlternativeName(entityId, newName);
                }
            });
        });

        // Attach hover listeners for element highlighting on screenshot
        container.querySelectorAll('.suggestion-card').forEach(card => {
            card.addEventListener('mouseenter', (e) => {
                const entityId = card.dataset.entityId;
                this.highlightSuggestionElement(entityId);
            });
            card.addEventListener('mouseleave', () => {
                this.clearSuggestionHighlight();
            });
        });
    }

    /**
     * Highlight a suggestion's element on the screenshot
     */
    highlightSuggestionElement(entityId) {
        if (!this.wizard) return;

        // Find the suggestion
        const suggestions = this.currentMode === 'sensors' ? this.sensorSuggestions : this.actionSuggestions;
        const suggestion = suggestions.find(s => s.entity_id === entityId);
        if (!suggestion?.element?.bounds) return;

        // Import and use the canvas overlay renderer
        import('./canvas-overlay-renderer.js').then(module => {
            const element = {
                bounds: suggestion.element.bounds,
                text: suggestion.element.text,
                class: suggestion.element.class
            };
            module.highlightHoveredElement(this.wizard, element);
        }).catch(err => {
            console.warn('[SmartSuggestions] Could not highlight element:', err);
        });
    }

    /**
     * Clear suggestion highlight
     */
    clearSuggestionHighlight() {
        if (!this.wizard) return;

        import('./canvas-overlay-renderer.js').then(module => {
            module.clearHoverHighlight(this.wizard);
        }).catch(() => {});
    }

    /**
     * Use an alternative name for a suggestion
     */
    useAlternativeName(entityId, altName) {
        // Find the suggestion
        const suggestions = this.currentMode === 'sensors' ? this.sensorSuggestions : this.actionSuggestions;
        const suggestion = suggestions.find(s => s.entity_id === entityId);
        if (!suggestion) return;

        // Swap names: current name becomes an alternative, alt becomes primary
        const oldName = suggestion.name;
        suggestion.name = altName;

        // Update alternatives list
        if (suggestion.alternative_names) {
            // Remove the selected alternative
            suggestion.alternative_names = suggestion.alternative_names.filter(
                alt => alt.name.toLowerCase() !== altName.toLowerCase()
            );
            // Add old name as alternative (if not already there)
            if (!suggestion.alternative_names.some(alt => alt.name.toLowerCase() === oldName.toLowerCase())) {
                suggestion.alternative_names.unshift({
                    name: oldName,
                    location: 'previous',
                    score: 100
                });
            }
        }

        // Update the display
        const nameEl = document.querySelector(`.suggestion-name[data-entity-id="${entityId}"]`);
        if (nameEl) {
            nameEl.textContent = altName;
        }

        // Re-render to update alternative buttons
        this.renderSuggestions();

        showToast(`Name changed to "${altName}"`, 'success', 2000);
    }

    /**
     * Render a single suggestion card
     */
    renderSuggestionCard(suggestion, checked = false) {
        console.log('[SmartSuggestions] Rendering card for suggestion:', suggestion);

        const confidenceClass = suggestion.confidence >= 0.8 ? 'high' :
                               suggestion.confidence >= 0.5 ? 'medium' : 'low';

        const confidencePercent = Math.round(suggestion.confidence * 100);

        // Build alternative names dropdown if available
        let alternativeNamesHtml = '';
        if (suggestion.alternative_names && suggestion.alternative_names.length > 0) {
            const locationIcons = {
                'above': '⬆️', 'below': '⬇️', 'left': '⬅️', 'right': '➡️',
                'resource_id': '🏷️', 'pattern': '🔍', 'content_desc': '📝'
            };
            const options = suggestion.alternative_names.map(alt => {
                const icon = locationIcons[alt.location] || '📍';
                const locationDesc = alt.location === 'above' ? 'from label above' :
                                    alt.location === 'below' ? 'from label below' :
                                    alt.location === 'left' ? 'from label left' :
                                    alt.location === 'right' ? 'from label right' :
                                    alt.location === 'resource_id' ? 'from resource ID' :
                                    alt.location === 'pattern' ? 'pattern match' :
                                    alt.location === 'content_desc' ? 'from description' : '';
                return `<option value="${this.escapeHtml(alt.name)}" title="${locationDesc}">${icon} ${this.escapeHtml(alt.name)}</option>`;
            }).join('');

            alternativeNamesHtml = `
                <div class="suggestion-row alternative-names-row">
                    <span class="label">Name:</span>
                    <select class="alt-name-select" data-entity-id="${suggestion.entity_id}">
                        <option value="" disabled>── Select sensor name ──</option>
                        <option value="" selected>✓ ${this.escapeHtml(suggestion.name)} (suggested)</option>
                        ${options}
                    </select>
                </div>
            `;
        }

        return `
            <div class="suggestion-card" data-entity-id="${suggestion.entity_id}">
                <div class="suggestion-header">
                    <input type="checkbox"
                           class="suggestion-checkbox"
                           data-entity-id="${suggestion.entity_id}"
                           ${checked ? 'checked' : ''}>
                    <div class="suggestion-info">
                        <strong class="suggestion-name" data-entity-id="${suggestion.entity_id}">${this.escapeHtml(suggestion.name)}</strong>
                        <code class="entity-id">${suggestion.entity_id}</code>
                        <span class="confidence-badge confidence-${confidenceClass}" title="Confidence: ${confidencePercent}%">
                            ${confidencePercent}%
                        </span>
                    </div>
                </div>
                <div class="suggestion-details">
                    ${alternativeNamesHtml}
                    <div class="suggestion-row">
                        <span class="label">Element:</span>
                        <span class="value">"${this.escapeHtml(suggestion.element.text || '(no text)')}"</span>
                    </div>
                    ${suggestion.element.resource_id ? `
                        <div class="suggestion-row">
                            <span class="label">Resource ID:</span>
                            <span class="value"><code>${this.escapeHtml(suggestion.element.resource_id)}</code></span>
                        </div>
                    ` : ''}
                    ${suggestion.element.class ? `
                        <div class="suggestion-row">
                            <span class="label">Class:</span>
                            <span class="value"><code>${this.escapeHtml(suggestion.element.class)}</code></span>
                        </div>
                    ` : ''}
                    ${suggestion.current_value ? `
                        <div class="suggestion-row">
                            <span class="label">Current Value:</span>
                            <span class="value">${this.escapeHtml(suggestion.current_value)}${suggestion.unit_of_measurement ? ' ' + suggestion.unit_of_measurement : ''}</span>
                        </div>
                    ` : ''}
                    <div class="suggestion-row">
                        <span class="label">Pattern:</span>
                        <span class="value">${this.escapeHtml(suggestion.pattern_type)}</span>
                    </div>
                    ${suggestion.action_type ? `
                        <div class="suggestion-row">
                            <span class="label">Action Type:</span>
                            <span class="value">${this.escapeHtml(suggestion.action_type)}</span>
                        </div>
                    ` : ''}
                    ${suggestion.device_class && suggestion.device_class !== 'none' ? `
                        <div class="suggestion-row">
                            <span class="label">Device Class:</span>
                            <span class="value">${this.escapeHtml(suggestion.device_class)}</span>
                        </div>
                    ` : ''}
                    ${suggestion.unit_of_measurement && !suggestion.current_value ? `
                        <div class="suggestion-row">
                            <span class="label">Unit:</span>
                            <span class="value">${this.escapeHtml(suggestion.unit_of_measurement)}</span>
                        </div>
                    ` : ''}
                    <div class="suggestion-row">
                        <span class="label">Icon:</span>
                        <span class="value">${this.escapeHtml(suggestion.icon || 'mdi:eye')}</span>
                    </div>
                </div>
                <div class="suggestion-actions">
                    <button class="btn-small edit-suggestion-btn" data-entity-id="${suggestion.entity_id}">
                        ✏️ Edit
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Edit a suggestion - opens full creator dialog with pre-filled data
     */
    async editSuggestion(entityId) {
        // Get suggestions based on current mode
        const suggestions = this.currentMode === 'sensors' ? this.sensorSuggestions : this.actionSuggestions;
        const suggestion = suggestions.find(s => s.entity_id === entityId);
        if (!suggestion) return;

        if (!this.wizard) {
            console.error('[SmartSuggestions] No wizard reference - cannot open full editor');
            showToast('Cannot edit - wizard not available', 'error');
            return;
        }

        // Close the smart suggestions modal first
        this.closeModal();

        if (this.currentMode === 'sensors') {
            // Open full sensor creator with suggestion data pre-filled
            // Convert suggestion to element format
            const element = {
                text: suggestion.element?.text || '',
                'resource_id': suggestion.element?.resource_id || '',
                'content_desc': suggestion.element?.content_desc || '',
                'class': suggestion.element?.class || '',
                'bounds': suggestion.element?.bounds || '',
                clickable: suggestion.element?.clickable || false,
                index: suggestion.element?.index || 0
            };

            this.wizard.sensorCreator.show(this.deviceId, element, element.index, {
                // Pre-fill with suggestion data
                name: suggestion.name,
                entity_id: suggestion.entity_id,
                device_class: suggestion.device_class || 'none',
                unit: suggestion.unit || '',
                icon: suggestion.icon || 'mdi:eye',
                stableDeviceId: this.wizard?.selectedDeviceStableId || this.deviceId,
                screenActivity: this.wizard?.recorder?.currentScreenActivity || this.wizard?.currentActivity || null,
                targetApp: this.wizard?.selectedApp?.package || null
            });
        } else {
            // For actions, use action creator
            const element = {
                text: suggestion.element?.text || '',
                'resource_id': suggestion.element?.resource_id || '',
                'content_desc': suggestion.element?.content_desc || '',
                'class': suggestion.element?.class || '',
                'bounds': suggestion.element?.bounds || '',
                clickable: suggestion.element?.clickable || false,
                index: suggestion.element?.index || 0
            };

            // Import Dialogs module to create action
            const Dialogs = await import('./flow-wizard-dialogs.js?v=0.4.0-beta.2.6');
            await Dialogs.createAction(this.wizard, element, null);
        }
    }

    /**
     * Create edit modal dialog
     * @private
     */
    _createEditModal() {
        const modal = document.createElement('div');
        modal.id = 'suggestionEditModal';
        modal.className = 'modal-overlay';

        const isSensor = this.currentMode === 'sensors';
        const itemType = isSensor ? 'Sensor' : 'Action';

        modal.innerHTML = `
            <div class="modal-content">
                <h2>Edit ${itemType}</h2>

                <form id="suggestionEditForm">
                    <!-- Element Info -->
                    <div class="info-box" style="background: var(--bg-secondary); padding: 12px; border-radius: 6px; margin-bottom: 20px; border: 1px solid var(--border);">
                        <strong style="color: var(--text-primary);">Selected Element:</strong><br>
                        <span id="editElementInfo" style="color: var(--text-secondary); font-size: 13px;"></span>
                    </div>

                    <!-- Name -->
                    <div class="form-group">
                        <label class="form-label" style="color: var(--text-primary); font-weight: 600; display: block; margin-bottom: 8px;">${itemType} Name *</label>
                        <input type="text" id="editName" required class="form-input" style="width: 100%; padding: 10px; background: var(--input-background); border: 1px solid var(--input-border); color: var(--text-primary); border-radius: 4px;">
                    </div>

                    <!-- Entity ID -->
                    <div class="form-group">
                        <label class="form-label" style="color: var(--text-primary); font-weight: 600; display: block; margin-bottom: 8px;">Entity ID</label>
                        <input type="text" id="editEntityId" class="form-input" style="width: 100%; padding: 10px; background: var(--input-background); border: 1px solid var(--input-border); color: var(--text-primary); border-radius: 4px;">
                        <small style="color: var(--text-secondary); font-size: 12px;">Changing this may break existing automations</small>
                    </div>

                    <!-- Sensor-specific fields -->
                    <div id="sensorFields" style="display: none;">
                        <!-- Device Class -->
                        <div class="form-group">
                            <label class="form-label" style="color: var(--text-primary); font-weight: 600; display: block; margin-bottom: 8px;">Device Class</label>
                            <select id="editDeviceClass" class="form-select" style="width: 100%; padding: 10px; background: var(--input-background); border: 1px solid var(--input-border); color: var(--text-primary); border-radius: 4px;">
                                <option value="none">None (Generic Sensor)</option>
                            </select>
                            <small id="editDeviceClassHelp" style="color: var(--text-secondary); font-size: 12px;"></small>
                        </div>

                        <!-- Unit of Measurement -->
                        <div class="form-group">
                            <label class="form-label" style="color: var(--text-primary); font-weight: 600; display: block; margin-bottom: 8px;">Unit of Measurement</label>
                            <select id="editUnit" class="form-select" style="width: 100%; padding: 10px; background: var(--input-background); border: 1px solid var(--input-border); color: var(--text-primary); border-radius: 4px;">
                                <option value="">No unit</option>
                            </select>
                            <small style="color: var(--text-secondary); font-size: 12px;">Leave empty for text sensors</small>
                        </div>
                    </div>

                    <!-- Action-specific fields -->
                    <div id="actionFields" style="display: none;">
                        <!-- Action Type -->
                        <div class="form-group">
                            <label class="form-label" style="color: var(--text-primary); font-weight: 600; display: block; margin-bottom: 8px;">Action Type</label>
                            <select id="editActionType" class="form-select" style="width: 100%; padding: 10px; background: var(--input-background); border: 1px solid var(--input-border); color: var(--text-primary); border-radius: 4px;">
                                <option value="tap">Tap</option>
                                <option value="toggle">Toggle</option>
                                <option value="swipe">Swipe</option>
                                <option value="input_text">Input Text</option>
                            </select>
                        </div>
                    </div>

                    <!-- Icon -->
                    <div class="form-group">
                        <label class="form-label" style="color: var(--text-primary); font-weight: 600; display: block; margin-bottom: 8px;">Icon (MDI)</label>
                        <select id="editIcon" class="form-select" style="width: 100%; padding: 10px; background: var(--input-background); border: 1px solid var(--input-border); color: var(--text-primary); border-radius: 4px;">
                            <option value="mdi:eye">mdi:eye</option>
                        </select>
                        <small style="color: var(--text-secondary); font-size: 12px;">Material Design Icon name</small>
                    </div>

                    <!-- Modal Actions -->
                    <div class="modal-actions" style="display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--border);">
                        <button type="button" class="btn btn-secondary" id="cancelEditBtn">Cancel</button>
                        <button type="submit" class="btn btn-primary">Save Changes</button>
                    </div>
                </form>
            </div>
        `;

        document.body.appendChild(modal);
        this.editModal = modal;

        // Attach event listeners
        modal.querySelector('#suggestionEditForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this._saveEdit();
        });

        modal.querySelector('#cancelEditBtn').addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.editModal.style.display = 'none';
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.editModal.style.display = 'none';
            }
        });

        // Device class change handler (for sensors)
        const deviceClassSelect = modal.querySelector('#editDeviceClass');
        if (deviceClassSelect) {
            deviceClassSelect.addEventListener('change', () => {
                this._updateEditUnitOptions();
                this._updateEditIconOptions();
            });
        }
    }

    /**
     * Populate edit form with suggestion data
     * @private
     */
    _populateEditForm(suggestion) {
        const modal = this.editModal;

        // Set element info
        const elementInfo = modal.querySelector('#editElementInfo');
        elementInfo.textContent = `${suggestion.element.text || '(no text)'} [${suggestion.element.class || 'unknown class'}]`;

        // Set name and entity ID
        modal.querySelector('#editName').value = suggestion.name || '';
        modal.querySelector('#editEntityId').value = suggestion.entity_id || '';

        // Show/hide fields based on mode
        const sensorFields = modal.querySelector('#sensorFields');
        const actionFields = modal.querySelector('#actionFields');

        if (this.currentMode === 'sensors') {
            sensorFields.style.display = 'block';
            actionFields.style.display = 'none';

            // Populate device class dropdown
            this._populateEditDeviceClasses();

            // Set device class
            const deviceClassSelect = modal.querySelector('#editDeviceClass');
            deviceClassSelect.value = suggestion.device_class || 'none';

            // Update unit and icon options
            this._updateEditUnitOptions();
            this._updateEditIconOptions();

            // Set unit
            const unitSelect = modal.querySelector('#editUnit');
            if (suggestion.unit_of_measurement) {
                // Add option if it doesn't exist
                if (!Array.from(unitSelect.options).some(opt => opt.value === suggestion.unit_of_measurement)) {
                    const option = document.createElement('option');
                    option.value = suggestion.unit_of_measurement;
                    option.textContent = suggestion.unit_of_measurement;
                    unitSelect.appendChild(option);
                }
                unitSelect.value = suggestion.unit_of_measurement;
            }
        } else {
            sensorFields.style.display = 'none';
            actionFields.style.display = 'block';

            // Set action type
            const actionTypeSelect = modal.querySelector('#editActionType');
            actionTypeSelect.value = suggestion.action_type || 'tap';
        }

        // Set icon
        const iconSelect = modal.querySelector('#editIcon');
        if (suggestion.icon) {
            // Add option if it doesn't exist
            if (!Array.from(iconSelect.options).some(opt => opt.value === suggestion.icon)) {
                const option = document.createElement('option');
                option.value = suggestion.icon;
                option.textContent = suggestion.icon;
                iconSelect.appendChild(option);
            }
            iconSelect.value = suggestion.icon;
        }
    }

    /**
     * Populate device class dropdown
     * @private
     */
    _populateEditDeviceClasses() {
        if (!this.deviceClasses || !this.deviceClasses.device_classes) {
            // Wait for device classes to load
            setTimeout(() => this._populateEditDeviceClasses(), 100);
            return;
        }

        const select = this.editModal.querySelector('#editDeviceClass');

        // Clear existing options
        select.innerHTML = '<option value="none">None (Generic Sensor)</option>';

        // Add device classes
        this.deviceClasses.device_classes.forEach(dc => {
            const option = document.createElement('option');
            option.value = dc.value;
            option.textContent = `${dc.name} - ${dc.description}`;
            select.appendChild(option);
        });
    }

    /**
     * Update unit options based on selected device class
     * @private
     */
    _updateEditUnitOptions() {
        if (!this.deviceClasses) return;

        const deviceClassSelect = this.editModal.querySelector('#editDeviceClass');
        const unitSelect = this.editModal.querySelector('#editUnit');
        const selectedClass = deviceClassSelect.value;

        // Clear unit options
        unitSelect.innerHTML = '<option value="">No unit</option>';

        if (selectedClass && selectedClass !== 'none') {
            const dcData = this.deviceClasses.device_classes.find(dc => dc.value === selectedClass);
            if (dcData && dcData.units) {
                dcData.units.forEach(unit => {
                    const option = document.createElement('option');
                    option.value = unit;
                    option.textContent = unit;
                    if (dcData.default_unit === unit) {
                        option.selected = true;
                    }
                    unitSelect.appendChild(option);
                });
            }
        }
    }

    /**
     * Update icon options based on selected device class
     * @private
     */
    _updateEditIconOptions() {
        if (!this.deviceClasses) return;

        const deviceClassSelect = this.editModal.querySelector('#editDeviceClass');
        const iconSelect = this.editModal.querySelector('#editIcon');
        const selectedClass = deviceClassSelect.value;

        // Clear icon options
        iconSelect.innerHTML = '';

        let defaultIcon = 'mdi:eye';

        if (selectedClass && selectedClass !== 'none') {
            const dcData = this.deviceClasses.device_classes.find(dc => dc.value === selectedClass);
            if (dcData && dcData.icon) {
                defaultIcon = dcData.icon;
            }
        }

        const option = document.createElement('option');
        option.value = defaultIcon;
        option.textContent = defaultIcon;
        option.selected = true;
        iconSelect.appendChild(option);
    }

    /**
     * Save edited suggestion
     * @private
     */
    _saveEdit() {
        if (!this.editingSuggestion) return;

        const modal = this.editModal;
        const suggestion = this.editingSuggestion;
        const oldEntityId = suggestion.entity_id;

        // Get form values
        const newName = modal.querySelector('#editName').value.trim();
        const newEntityId = modal.querySelector('#editEntityId').value.trim();
        const newIcon = modal.querySelector('#editIcon').value;

        if (!newName) {
            showToast('Name is required', 'error');
            return;
        }

        // Update suggestion
        suggestion.name = newName;

        if (newEntityId && newEntityId !== oldEntityId) {
            // Update selected set if was selected
            if (this.selectedSuggestions.has(oldEntityId)) {
                this.selectedSuggestions.delete(oldEntityId);
                this.selectedSuggestions.add(newEntityId);
            }
            suggestion.entity_id = newEntityId;
        }

        suggestion.icon = newIcon;

        if (this.currentMode === 'sensors') {
            suggestion.device_class = modal.querySelector('#editDeviceClass').value;
            suggestion.unit_of_measurement = modal.querySelector('#editUnit').value || null;
        } else {
            suggestion.action_type = modal.querySelector('#editActionType').value;
        }

        // Hide modal
        this.editModal.style.display = 'none';

        // Re-render suggestions
        this.renderSuggestions();

        showToast('Changes saved!', 'success');
    }

    /**
     * Toggle select/deselect all
     */
    toggleSelectAll() {
        const allCheckboxes = document.querySelectorAll('.suggestion-checkbox');
        const allChecked = Array.from(allCheckboxes).every(cb => cb.checked);

        allCheckboxes.forEach(checkbox => {
            checkbox.checked = !allChecked;
            const entityId = checkbox.dataset.entityId;

            if (!allChecked) {
                this.selectedSuggestions.add(entityId);
            } else {
                this.selectedSuggestions.delete(entityId);
            }
        });

        this.updateSelectedCount();
    }

    /**
     * Update selected count display
     */
    updateSelectedCount() {
        const countSpan = document.getElementById('selectedCount');
        if (countSpan) {
            countSpan.textContent = this.selectedSuggestions.size;
        }
    }

    /**
     * Add selected sensors
     */
    addSelected() {
        if (this.selectedSuggestions.size === 0) {
            const itemType = this.currentMode === 'sensors' ? 'sensors' : 'actions';
            showToast(`No ${itemType} selected`, 'warning');
            return;
        }

        // Get selected items based on current mode
        const suggestions = this.currentMode === 'sensors' ? this.sensorSuggestions : this.actionSuggestions;
        const selectedItems = suggestions.filter(s =>
            this.selectedSuggestions.has(s.entity_id)
        );

        console.log(`[SmartSuggestions] Adding ${this.currentMode}:`, selectedItems);

        // Call appropriate callback
        if (this.currentMode === 'sensors' && this.onSensorsAdded) {
            this.onSensorsAdded(selectedItems);
        } else if (this.currentMode === 'actions' && this.onActionsAdded) {
            this.onActionsAdded(selectedItems);
        }

        // Close modal
        this.closeModal();

        const itemType = this.currentMode === 'sensors' ? 'sensor(s)' : 'action(s)';
        showToast(`Added ${selectedItems.length} ${itemType} to flow!`, 'success');
    }

    /**
     * Open modal
     */
    openModal() {
        const modal = document.getElementById('smartSuggestionsModal');
        if (modal) {
            modal.classList.add('active');
        }
    }

    /**
     * Close modal
     */
    closeModal() {
        console.log('[SmartSuggestions] Closing modal...');
        const modal = document.getElementById('smartSuggestionsModal');
        console.log('[SmartSuggestions] Modal element:', modal);
        if (modal) {
            modal.classList.remove('active');
            console.log('[SmartSuggestions] Modal closed');
        } else {
            console.error('[SmartSuggestions] Modal element not found!');
        }
    }

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// ES6 export
export default SmartSuggestions;

// Global export for backward compatibility
window.SmartSuggestions = SmartSuggestions;
