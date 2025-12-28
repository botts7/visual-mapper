/**
 * Smart Suggestions Panel - AI-powered sensor and action detection
 *
 * Analyzes UI elements and suggests Home Assistant sensors/actions
 * based on pattern detection heuristics.
 */

import { getApiBase } from './api-base-detection.js?v=0.0.5';
import { showToast } from './toast.js?v=0.0.5';

class SmartSuggestions {
    constructor() {
        this.suggestions = [];
        this.selectedSuggestions = new Set();
        this.onSensorsAdded = null;  // Callback when sensors are created
    }

    /**
     * Show smart suggestions modal for a device
     * @param {string} deviceId - Device ID
     * @param {Function} onSensorsAdded - Callback(sensors[]) when sensors are added
     */
    async show(deviceId, onSensorsAdded = null) {
        this.deviceId = deviceId;
        this.onSensorsAdded = onSensorsAdded;
        this.selectedSuggestions.clear();

        try {
            // Fetch suggestions from API
            showToast('Analyzing UI elements...', 'info');
            await this.fetchSuggestions(deviceId);

            // Show modal
            this.renderModal();
            this.openModal();

        } catch (error) {
            console.error('[SmartSuggestions] Error showing suggestions:', error);
            showToast(`Failed to load suggestions: ${error.message}`, 'error');
        }
    }

    /**
     * Fetch sensor suggestions from API
     */
    async fetchSuggestions(deviceId) {
        const response = await fetch(`${getApiBase()}/devices/${deviceId}/suggest-sensors`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('Failed to fetch sensor suggestions');
        }

        const data = await response.json();
        this.suggestions = data.suggestions || [];

        console.log(`[SmartSuggestions] Got ${this.suggestions.length} suggestions`);

        if (this.suggestions.length === 0) {
            showToast('No sensor suggestions found', 'warning');
        } else {
            showToast(`Found ${this.suggestions.length} sensor suggestions!`, 'success');
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
                        <h2>🤖 Smart Sensor Suggestions</h2>
                    </div>
                    <div class="modal-body">
                        <div id="suggestionsContent"></div>
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
            document.getElementById('closeSuggestionsBtn').addEventListener('click', () => {
                this.closeModal();
            });

            document.getElementById('selectAllSuggestionsBtn').addEventListener('click', () => {
                this.toggleSelectAll();
            });

            document.getElementById('addSelectedSuggestionsBtn').addEventListener('click', () => {
                this.addSelectedSensors();
            });

            // Close on background click
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeModal();
                }
            });
        }

        // Render suggestions content
        this.renderSuggestions();
    }

    /**
     * Render suggestions list
     */
    renderSuggestions() {
        const container = document.getElementById('suggestionsContent');

        if (!this.suggestions || this.suggestions.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <p>No sensor suggestions found on this screen.</p>
                    <p>Try navigating to a screen with data like battery levels, temperatures, or status information.</p>
                </div>
            `;
            return;
        }

        // Group suggestions by confidence level
        const highConfidence = this.suggestions.filter(s => s.confidence >= 0.8);
        const mediumConfidence = this.suggestions.filter(s => s.confidence >= 0.5 && s.confidence < 0.8);
        const lowConfidence = this.suggestions.filter(s => s.confidence < 0.5);

        let html = '';

        // High confidence suggestions (auto-selected)
        if (highConfidence.length > 0) {
            html += '<div class="suggestion-group">';
            html += '<h3>🎯 High Confidence Suggestions</h3>';
            html += '<p class="suggestion-group-desc">These are very likely to be useful sensors.</p>';
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
    }

    /**
     * Render a single suggestion card
     */
    renderSuggestionCard(suggestion, checked = false) {
        const confidenceClass = suggestion.confidence >= 0.8 ? 'high' :
                               suggestion.confidence >= 0.5 ? 'medium' : 'low';

        const confidencePercent = Math.round(suggestion.confidence * 100);

        return `
            <div class="suggestion-card" data-entity-id="${suggestion.entity_id}">
                <div class="suggestion-header">
                    <input type="checkbox"
                           class="suggestion-checkbox"
                           data-entity-id="${suggestion.entity_id}"
                           ${checked ? 'checked' : ''}>
                    <div class="suggestion-info">
                        <strong>${this.escapeHtml(suggestion.name)}</strong>
                        <code class="entity-id">${suggestion.entity_id}</code>
                        <span class="confidence-badge confidence-${confidenceClass}" title="Confidence: ${confidencePercent}%">
                            ${confidencePercent}%
                        </span>
                    </div>
                </div>
                <div class="suggestion-details">
                    <div class="suggestion-row">
                        <span class="label">Element:</span>
                        <span class="value">"${this.escapeHtml(suggestion.element.text || '(no text)')}"</span>
                    </div>
                    ${suggestion.current_value ? `
                        <div class="suggestion-row">
                            <span class="label">Current Value:</span>
                            <span class="value">${this.escapeHtml(suggestion.current_value)}${suggestion.unit_of_measurement ? ' ' + suggestion.unit_of_measurement : ''}</span>
                        </div>
                    ` : ''}
                    <div class="suggestion-row">
                        <span class="label">Type:</span>
                        <span class="value">${suggestion.pattern_type}</span>
                        ${suggestion.device_class && suggestion.device_class !== 'none' ? `
                            <span class="label">Device Class:</span>
                            <span class="value">${suggestion.device_class}</span>
                        ` : ''}
                    </div>
                    <div class="suggestion-row">
                        <span class="label">Icon:</span>
                        <span class="value">${suggestion.icon || 'mdi:eye'}</span>
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
     * Edit a suggestion
     */
    editSuggestion(entityId) {
        const suggestion = this.suggestions.find(s => s.entity_id === entityId);
        if (!suggestion) return;

        // Prompt for new name
        const newName = prompt('Sensor Name:', suggestion.name);
        if (newName && newName !== suggestion.name) {
            suggestion.name = newName;
        }

        // Prompt for new entity ID
        const newEntityId = prompt('Entity ID:', suggestion.entity_id);
        if (newEntityId && newEntityId !== suggestion.entity_id) {
            // Update selected set if was selected
            if (this.selectedSuggestions.has(suggestion.entity_id)) {
                this.selectedSuggestions.delete(suggestion.entity_id);
                this.selectedSuggestions.add(newEntityId);
            }
            suggestion.entity_id = newEntityId;
        }

        // Re-render
        this.renderSuggestions();
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
    addSelectedSensors() {
        if (this.selectedSuggestions.size === 0) {
            showToast('No sensors selected', 'warning');
            return;
        }

        // Get selected sensor objects
        const selectedSensors = this.suggestions.filter(s =>
            this.selectedSuggestions.has(s.entity_id)
        );

        console.log('[SmartSuggestions] Adding sensors:', selectedSensors);

        // Call callback if provided
        if (this.onSensorsAdded) {
            this.onSensorsAdded(selectedSensors);
        }

        // Close modal
        this.closeModal();

        showToast(`Added ${selectedSensors.length} sensor(s) to flow!`, 'success');
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
        const modal = document.getElementById('smartSuggestionsModal');
        if (modal) {
            modal.classList.remove('active');
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
