/**
 * Action Manager Module
 *
 * Manages device actions - create, list, execute, update, delete
 * Mirrors sensor-creator.js architecture
 *
 * Includes duplicate detection (warning-only) to help users avoid creating
 * similar actions that already exist.
 */

export default class ActionManager {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.currentDeviceId = null;
        this.actions = [];
        this.pendingActionData = null;  // For duplicate check flow
        this.actionTypes = [
            'tap', 'swipe', 'text', 'keyevent',
            'launch_app', 'delay', 'macro'
        ];

        // Keycodes for keyevent actions
        this.keycodes = [
            'KEYCODE_HOME', 'KEYCODE_BACK', 'KEYCODE_MENU',
            'KEYCODE_VOLUME_UP', 'KEYCODE_VOLUME_DOWN', 'KEYCODE_VOLUME_MUTE',
            'KEYCODE_POWER', 'KEYCODE_CAMERA', 'KEYCODE_APP_SWITCH',
            'KEYCODE_ENTER', 'KEYCODE_DEL', 'KEYCODE_SPACE',
            'KEYCODE_DPAD_UP', 'KEYCODE_DPAD_DOWN', 'KEYCODE_DPAD_LEFT', 'KEYCODE_DPAD_RIGHT',
            'KEYCODE_MEDIA_PLAY', 'KEYCODE_MEDIA_PAUSE', 'KEYCODE_MEDIA_PLAY_PAUSE',
            'KEYCODE_MEDIA_STOP', 'KEYCODE_MEDIA_NEXT', 'KEYCODE_MEDIA_PREVIOUS'
        ];
    }

    /**
     * Set current device ID for all action operations
     */
    setDevice(deviceId) {
        this.currentDeviceId = deviceId;
        this.actions = [];
    }

    /**
     * Load all actions for current device
     */
    async loadActions() {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            const response = await this.apiClient.get(`/actions/${this.currentDeviceId}`);
            this.actions = response.actions || [];
            return this.actions;
        } catch (error) {
            console.error('[ActionManager] Load actions failed:', error);
            throw error;
        }
    }

    /**
     * Create a new action with optional duplicate check
     *
     * @param {Object} actionConfig - Action configuration
     * @param {Array} tags - Optional tags
     * @param {boolean} skipDuplicateCheck - If true, skip the duplicate check
     * @param {string} sourceApp - App package name where action was created
     * @returns {Object} Created action or null if user chose to use existing
     */
    async createAction(actionConfig, tags = [], skipDuplicateCheck = false, sourceApp = null) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        // Ensure device_id is set
        actionConfig.device_id = this.currentDeviceId;

        // Check for duplicates before creating (unless explicitly skipped)
        if (!skipDuplicateCheck) {
            try {
                const dupCheck = await this._checkForDuplicates(actionConfig);
                if (dupCheck.hasSimilar) {
                    // Store pending data and show warning
                    this.pendingActionData = { actionConfig, tags };
                    const userChoice = await this._showDuplicateWarning(dupCheck);

                    if (userChoice === 'use_existing') {
                        console.log('[ActionManager] User chose to use existing action');
                        return dupCheck.bestMatch;
                    } else if (userChoice === 'cancel') {
                        console.log('[ActionManager] User cancelled action creation');
                        return null;
                    }
                    // userChoice === 'create_anyway' - continue below
                }
            } catch (dupError) {
                // Log but don't block creation if dedup check fails
                console.warn('[ActionManager] Duplicate check failed, proceeding:', dupError);
            }
        }

        try {
            const response = await this.apiClient.post(
                `/actions?device_id=${this.currentDeviceId}`,
                {
                    action: actionConfig,
                    tags: tags,
                    source_app: sourceApp
                }
            );

            if (response.success) {
                this.actions.push(response.action);
                return response.action;
            } else {
                throw new Error(response.error?.message || 'Failed to create action');
            }
        } catch (error) {
            console.error('[ActionManager] Create action failed:', error);
            throw error;
        }
    }

    /**
     * Check for duplicate/similar actions before creation
     * @private
     */
    async _checkForDuplicates(actionConfig) {
        const response = await this.apiClient.post('/dedup/actions/check', {
            device_id: this.currentDeviceId,
            action: {
                action_type: actionConfig.action_type,
                name: actionConfig.name,
                x: actionConfig.x,
                y: actionConfig.y,
                x1: actionConfig.x1,
                y1: actionConfig.y1,
                x2: actionConfig.x2,
                y2: actionConfig.y2,
                package_name: actionConfig.package_name,
                text: actionConfig.text,
                keycode: actionConfig.keycode,
                screen_activity: actionConfig.screen_activity
            }
        });

        return {
            hasSimilar: response.has_similar,
            matches: response.matches || [],
            recommendation: response.recommendation,
            bestMatch: response.best_match
        };
    }

    /**
     * Show duplicate warning modal and get user choice
     * @private
     */
    async _showDuplicateWarning(dupCheck) {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'modal-overlay';
            modal.id = 'action-duplicate-modal';

            const bestMatch = dupCheck.bestMatch;
            const similarity = bestMatch?.similarity_score
                ? Math.round(bestMatch.similarity_score * 100)
                : '?';

            const matchDetails = bestMatch?.details || {};
            const existingName = matchDetails.existing_name || 'Unknown';
            const existingType = matchDetails.existing_type || 'Unknown';
            const matchReason = matchDetails.match_reason || 'Similar configuration';

            modal.innerHTML = `
                <div class="modal-content" style="max-width: 500px;">
                    <div class="modal-header">
                        <h3>Similar Action Found</h3>
                        <button class="close-btn" onclick="document.getElementById('action-duplicate-modal').remove()">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="duplicate-warning" style="background: #fff3cd; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                            <p style="margin: 0 0 10px 0;"><strong>${similarity}% similar</strong> to existing action:</p>
                            <div style="background: white; padding: 10px; border-radius: 4px; margin-bottom: 10px;">
                                <strong>${this.escapeHtml(existingName)}</strong><br>
                                <small>Type: ${existingType} | ${matchReason}</small>
                            </div>
                            <p style="margin: 0; color: #856404; font-size: 0.9em;">
                                ${dupCheck.recommendation === 'use_existing'
                                    ? '💡 Recommended: Use the existing action instead of creating a duplicate.'
                                    : '⚠️ You may want to review the existing action before creating a new one.'}
                            </p>
                        </div>
                    </div>
                    <div class="modal-footer" style="display: flex; gap: 10px; justify-content: flex-end;">
                        <button class="btn btn-secondary" id="dup-cancel-btn">Cancel</button>
                        <button class="btn btn-primary" id="dup-use-existing-btn">Use Existing</button>
                        <button class="btn btn-warning" id="dup-create-anyway-btn">Create Anyway</button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            // Wire up button handlers
            document.getElementById('dup-cancel-btn').onclick = () => {
                modal.remove();
                resolve('cancel');
            };

            document.getElementById('dup-use-existing-btn').onclick = () => {
                modal.remove();
                resolve('use_existing');
            };

            document.getElementById('dup-create-anyway-btn').onclick = () => {
                modal.remove();
                resolve('create_anyway');
            };

            // Close on backdrop click
            modal.onclick = (e) => {
                if (e.target === modal) {
                    modal.remove();
                    resolve('cancel');
                }
            };
        });
    }

    /**
     * Update an existing action
     */
    async updateAction(actionId, updates) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            const response = await this.apiClient.put(
                `/actions/${this.currentDeviceId}/${actionId}`,
                updates
            );

            if (response.success) {
                // Update local cache
                const index = this.actions.findIndex(a => a.id === actionId);
                if (index !== -1) {
                    this.actions[index] = response.action;
                }
                return response.action;
            } else {
                throw new Error(response.error?.message || 'Failed to update action');
            }
        } catch (error) {
            console.error('[ActionManager] Update action failed:', error);
            throw error;
        }
    }

    /**
     * Delete an action
     */
    async deleteAction(actionId) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            const response = await this.apiClient.delete(
                `/actions/${this.currentDeviceId}/${actionId}`
            );

            if (response.success) {
                // Remove from local cache
                this.actions = this.actions.filter(a => a.id !== actionId);
                return true;
            } else {
                throw new Error(response.error?.message || 'Failed to delete action');
            }
        } catch (error) {
            console.error('[ActionManager] Delete action failed:', error);
            throw error;
        }
    }

    /**
     * Execute an action (saved or inline)
     */
    async executeAction(actionIdOrConfig) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            const requestBody = typeof actionIdOrConfig === 'string'
                ? { action_id: actionIdOrConfig }
                : { action: actionIdOrConfig };

            const response = await this.apiClient.post(
                `/actions/execute?device_id=${this.currentDeviceId}`,
                requestBody
            );

            return response;
        } catch (error) {
            console.error('[ActionManager] Execute action failed:', error);
            throw error;
        }
    }

    /**
     * Export actions to JSON string
     */
    async exportActions() {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            const response = await this.apiClient.get(`/actions/export/${this.currentDeviceId}`);
            return response.actions_json;
        } catch (error) {
            console.error('[ActionManager] Export actions failed:', error);
            throw error;
        }
    }

    /**
     * Import actions from JSON string
     */
    async importActions(actionsJson) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            const response = await this.apiClient.post(
                `/actions/import/${this.currentDeviceId}`,
                { actions_json: actionsJson }
            );

            if (response.success) {
                // Reload actions
                await this.loadActions();
                return response.imported_count;
            } else {
                throw new Error(response.error?.message || 'Failed to import actions');
            }
        } catch (error) {
            console.error('[ActionManager] Import actions failed:', error);
            throw error;
        }
    }

    /**
     * Render action card HTML
     */
    renderActionCard(action) {
        const actionData = action.action;
        const isEnabled = actionData.enabled !== false;
        const executionInfo = action.execution_count > 0
            ? `Executed ${action.execution_count}x | Last: ${action.last_result || 'N/A'}`
            : 'Never executed';

        const tags = action.tags && action.tags.length > 0
            ? action.tags.map(tag => `<span class="tag">${tag}</span>`).join(' ')
            : '<span class="tag-empty">No tags</span>';

        // Action type badge
        const typeBadge = `<span class="action-type-badge action-type-${actionData.action_type}">${actionData.action_type}</span>`;

        // Action details based on type
        let details = '';
        switch (actionData.action_type) {
            case 'tap':
                details = `Tap at (${actionData.x}, ${actionData.y})`;
                break;
            case 'swipe':
                details = `Swipe from (${actionData.x1}, ${actionData.y1}) to (${actionData.x2}, ${actionData.y2}) in ${actionData.duration}ms`;
                break;
            case 'text':
                details = `Type: "${actionData.text.substring(0, 50)}${actionData.text.length > 50 ? '...' : ''}"`;
                break;
            case 'keyevent':
                details = `Press ${actionData.keycode}`;
                break;
            case 'launch_app':
                details = `Launch ${actionData.package_name}`;
                break;
            case 'delay':
                details = `Wait ${actionData.duration}ms`;
                break;
            case 'macro':
                details = `${actionData.actions.length} steps${actionData.stop_on_error ? ' (stop on error)' : ''}`;
                break;
            default:
                details = 'Unknown action type';
        }

        return `
            <div class="action-card ${!isEnabled ? 'action-disabled' : ''}" data-action-id="${action.id}">
                <div class="action-header">
                    <div class="action-title">
                        <h3>${this.escapeHtml(actionData.name)}</h3>
                        ${typeBadge}
                    </div>
                    <div class="action-controls">
                        <button class="btn btn-sm btn-primary" onclick="window.actionManagerInstance.executeActionById('${action.id}')">
                            ▶ Execute
                        </button>
                        <button class="btn btn-sm btn-secondary" onclick="window.actionManagerInstance.toggleActionEnabled('${action.id}')">
                            ${isEnabled ? '⏸ Disable' : '▶ Enable'}
                        </button>
                        <button class="btn btn-sm btn-warning" onclick="window.actionManagerInstance.editAction('${action.id}')">
                            ✏ Edit
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="window.actionManagerInstance.confirmDeleteAction('${action.id}')">
                            🗑 Delete
                        </button>
                    </div>
                </div>
                <div class="action-details">
                    <p class="action-description">${actionData.description || '<em>No description</em>'}</p>
                    <p class="action-config">${details}</p>
                    <p class="action-tags">${tags}</p>
                    <p class="action-stats"><small>${executionInfo}</small></p>
                </div>
            </div>
        `;
    }

    /**
     * Execute action by ID (called from UI)
     */
    async executeActionById(actionId) {
        try {
            const result = await this.executeAction(actionId);

            if (result.success) {
                alert(`✅ Action executed successfully in ${result.execution_time.toFixed(1)}ms`);
                // Reload to show updated execution count
                await this.loadActions();
                this.renderActionsList();
            } else {
                alert(`❌ Action failed: ${result.message}`);
            }
        } catch (error) {
            alert(`❌ Execution error: ${error.message}`);
        }
    }

    /**
     * Toggle action enabled/disabled status
     */
    async toggleActionEnabled(actionId) {
        const action = this.actions.find(a => a.id === actionId);
        if (!action) return;

        const newEnabledState = !action.action.enabled;

        try {
            await this.updateAction(actionId, {
                enabled: newEnabledState
            });
            alert(`✅ Action ${newEnabledState ? 'enabled' : 'disabled'}`);
            this.renderActionsList();
        } catch (error) {
            alert(`❌ Failed to toggle action: ${error.message}`);
        }
    }

    /**
     * Show edit action dialog
     */
    editAction(actionId) {
        const actionDef = this.actions.find(a => a.id === actionId);
        if (!actionDef) return;

        const action = actionDef.action;

        // Create edit modal if it doesn't exist
        let modal = document.getElementById('actionEditModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'actionEditModal';
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content" style="max-width: 500px;">
                    <div class="modal-header">
                        <h3>Edit Action</h3>
                        <button class="btn-close" onclick="document.getElementById('actionEditModal').style.display='none'">&times;</button>
                    </div>
                    <form id="actionEditForm">
                        <div class="modal-body" style="padding: 20px;">
                            <div class="form-group">
                                <label>Action Name</label>
                                <input type="text" id="editActionName" class="form-control" required>
                            </div>
                            <div class="form-group">
                                <label>Description</label>
                                <textarea id="editActionDesc" class="form-control" rows="2"></textarea>
                            </div>
                            <div id="editActionTypeFields"></div>
                            <div class="form-group">
                                <label>Tags (comma-separated)</label>
                                <input type="text" id="editActionTags" class="form-control">
                            </div>
                            <div class="form-group">
                                <label style="display: flex; align-items: center; gap: 8px;">
                                    <input type="checkbox" id="editActionEnabled" checked>
                                    Enabled
                                </label>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" onclick="document.getElementById('actionEditModal').style.display='none'">Cancel</button>
                            <button type="submit" class="btn btn-primary">Save Changes</button>
                        </div>
                    </form>
                </div>
            `;
            document.body.appendChild(modal);
        }

        // Populate form
        document.getElementById('editActionName').value = action.name || '';
        document.getElementById('editActionDesc').value = action.description || '';
        document.getElementById('editActionTags').value = (actionDef.tags || []).join(', ');
        document.getElementById('editActionEnabled').checked = actionDef.enabled !== false;

        // Render type-specific fields
        const typeFields = document.getElementById('editActionTypeFields');
        typeFields.innerHTML = this._renderEditTypeFields(action);

        // Handle form submit
        const form = document.getElementById('actionEditForm');
        form.onsubmit = async (e) => {
            e.preventDefault();
            await this._saveActionEdit(actionId, actionDef);
        };

        modal.style.display = 'flex';

        // Wire up "Edit in Wizard" button for macro actions
        const editInWizardBtn = document.getElementById('editInWizardBtn');
        if (editInWizardBtn) {
            editInWizardBtn.onclick = () => {
                modal.style.display = 'none';
                this._openInWizard(actionDef);
            };
        }
    }

    /**
     * Open action in Visual Wizard for step editing
     * @private
     */
    _openInWizard(actionDef) {
        // Navigate to wizard with edit params
        const wizardUrl = `flow-wizard.html?edit=true&device=${encodeURIComponent(this.currentDeviceId)}&action=${encodeURIComponent(actionDef.id)}`;
        window.location.href = wizardUrl;
    }

    /**
     * Format a step for display in the edit modal
     * @private
     */
    _formatStepDescription(step) {
        const type = step.step_type || step.action_type || 'unknown';
        switch (type) {
            case 'tap':
                return `👆 Tap at (${step.x || 0}, ${step.y || 0})`;
            case 'swipe':
                const x1 = step.x1 ?? step.start_x ?? 0;
                const y1 = step.y1 ?? step.start_y ?? 0;
                const x2 = step.x2 ?? step.end_x ?? 0;
                const y2 = step.y2 ?? step.end_y ?? 0;
                return `👉 Swipe (${x1},${y1}) → (${x2},${y2})`;
            case 'text':
                return `⌨️ Type "${step.text?.substring(0, 20) || ''}${step.text?.length > 20 ? '...' : ''}"`;
            case 'keyevent':
                return `🔘 Key: ${step.keycode || 'unknown'}`;
            case 'launch_app':
                return `🚀 Launch ${step.package || step.package_name || 'app'}`;
            case 'delay':
            case 'wait':
                return `⏱️ Wait ${step.duration || 0}ms`;
            case 'go_back':
                return `⬅️ Back`;
            case 'go_home':
                return `🏠 Home`;
            case 'pull_refresh':
                return `🔄 Pull to refresh`;
            case 'restart_app':
                return `🔄 Restart app`;
            default:
                return `${type}`;
        }
    }

    /**
     * Render type-specific edit fields
     * @private
     */
    _renderEditTypeFields(action) {
        switch (action.action_type) {
            case 'tap':
                return `
                    <div class="form-row" style="display: flex; gap: 10px;">
                        <div class="form-group" style="flex: 1;">
                            <label>X Coordinate</label>
                            <input type="number" id="editX" class="form-control" value="${action.x || 0}">
                        </div>
                        <div class="form-group" style="flex: 1;">
                            <label>Y Coordinate</label>
                            <input type="number" id="editY" class="form-control" value="${action.y || 0}">
                        </div>
                    </div>
                `;
            case 'swipe':
                return `
                    <div class="form-row" style="display: flex; gap: 10px;">
                        <div class="form-group" style="flex: 1;">
                            <label>Start X</label>
                            <input type="number" id="editX1" class="form-control" value="${action.x1 || 0}">
                        </div>
                        <div class="form-group" style="flex: 1;">
                            <label>Start Y</label>
                            <input type="number" id="editY1" class="form-control" value="${action.y1 || 0}">
                        </div>
                    </div>
                    <div class="form-row" style="display: flex; gap: 10px; margin-top: 10px;">
                        <div class="form-group" style="flex: 1;">
                            <label>End X</label>
                            <input type="number" id="editX2" class="form-control" value="${action.x2 || 0}">
                        </div>
                        <div class="form-group" style="flex: 1;">
                            <label>End Y</label>
                            <input type="number" id="editY2" class="form-control" value="${action.y2 || 0}">
                        </div>
                    </div>
                    <div class="form-group" style="margin-top: 10px;">
                        <label>Duration (ms)</label>
                        <input type="number" id="editDuration" class="form-control" value="${action.duration || 300}">
                    </div>
                `;
            case 'text':
                return `
                    <div class="form-group">
                        <label>Text to Type</label>
                        <input type="text" id="editText" class="form-control" value="${action.text || ''}">
                    </div>
                `;
            case 'keyevent':
                return `
                    <div class="form-group">
                        <label>Keycode</label>
                        <select id="editKeycode" class="form-control">
                            ${this.keycodes.map(k => `<option value="${k}" ${action.keycode === k ? 'selected' : ''}>${k}</option>`).join('')}
                        </select>
                    </div>
                `;
            case 'launch_app':
                return `
                    <div class="form-group">
                        <label>Package Name</label>
                        <input type="text" id="editPackageName" class="form-control" value="${action.package_name || ''}">
                    </div>
                `;
            case 'delay':
                return `
                    <div class="form-group">
                        <label>Delay Duration (ms)</label>
                        <input type="number" id="editDelayDuration" class="form-control" value="${action.duration || 1000}">
                    </div>
                `;
            case 'macro':
                return `
                    <div class="form-group">
                        <label>Macro Steps (${action.actions?.length || 0} steps)</label>
                        <div style="background: var(--card-background); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; margin: 10px 0; max-height: 200px; overflow-y: auto;">
                            ${(action.actions || []).map((step, i) => `
                                <div style="display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border-color);">
                                    <span style="color: var(--text-secondary); font-size: 11px; min-width: 24px;">${i + 1}.</span>
                                    <span style="font-size: 13px;">${this._formatStepDescription(step)}</span>
                                </div>
                            `).join('')}
                        </div>
                        <button type="button" class="btn btn-primary" id="editInWizardBtn" style="width: 100%; margin-top: 10px;">
                            🪄 Edit Steps in Visual Wizard
                        </button>
                        <p style="color: var(--text-secondary); font-size: 0.8em; margin-top: 8px; text-align: center;">
                            Opens the wizard to add, remove, or modify steps visually
                        </p>
                    </div>
                `;
            default:
                return `<p style="color: var(--text-secondary);">Action type: ${action.action_type}</p>`;
        }
    }

    /**
     * Save action edits
     * @private
     */
    async _saveActionEdit(actionId, actionDef) {
        const action = { ...actionDef.action };

        // Update common fields
        action.name = document.getElementById('editActionName').value.trim();
        action.description = document.getElementById('editActionDesc').value.trim();

        // Update type-specific fields
        switch (action.action_type) {
            case 'tap':
                action.x = parseInt(document.getElementById('editX')?.value) || 0;
                action.y = parseInt(document.getElementById('editY')?.value) || 0;
                break;
            case 'swipe':
                action.x1 = parseInt(document.getElementById('editX1')?.value) || 0;
                action.y1 = parseInt(document.getElementById('editY1')?.value) || 0;
                action.x2 = parseInt(document.getElementById('editX2')?.value) || 0;
                action.y2 = parseInt(document.getElementById('editY2')?.value) || 0;
                action.duration = parseInt(document.getElementById('editDuration')?.value) || 300;
                break;
            case 'text':
                action.text = document.getElementById('editText')?.value || '';
                break;
            case 'keyevent':
                action.keycode = document.getElementById('editKeycode')?.value || '';
                break;
            case 'launch_app':
                action.package_name = document.getElementById('editPackageName')?.value || '';
                break;
            case 'delay':
                action.duration = parseInt(document.getElementById('editDelayDuration')?.value) || 1000;
                break;
        }

        // Parse tags
        const tagsInput = document.getElementById('editActionTags').value;
        const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];
        const enabled = document.getElementById('editActionEnabled').checked;

        try {
            await this.updateAction(actionId, { action, tags, enabled });
            document.getElementById('actionEditModal').style.display = 'none';
            alert('✅ Action updated successfully');
            this.renderActionsList();
        } catch (error) {
            alert(`❌ Failed to update action: ${error.message}`);
        }
    }

    /**
     * Confirm and delete action
     */
    async confirmDeleteAction(actionId) {
        const action = this.actions.find(a => a.id === actionId);
        if (!action) return;

        if (confirm(`Delete action "${action.action.name}"?`)) {
            try {
                await this.deleteAction(actionId);
                alert('✅ Action deleted');
                this.renderActionsList();
            } catch (error) {
                alert(`❌ Failed to delete action: ${error.message}`);
            }
        }
    }

    /**
     * Render actions list to container
     */
    renderActionsList(containerId = 'actionsContainer') {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (this.actions.length === 0) {
            container.innerHTML = '<p class="status info">No actions found. Create your first action below.</p>';
            return;
        }

        container.innerHTML = this.actions.map(action => this.renderActionCard(action)).join('');
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

// Dual export pattern
window.ActionManager = ActionManager;
