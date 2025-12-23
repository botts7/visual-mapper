/**
 * Action Manager Module
 *
 * Manages device actions - create, list, execute, update, delete
 * Mirrors sensor-creator.js architecture
 */

export default class ActionManager {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.currentDeviceId = null;
        this.actions = [];
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
     * Create a new action
     */
    async createAction(actionConfig, tags = []) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        // Ensure device_id is set
        actionConfig.device_id = this.currentDeviceId;

        try {
            const response = await this.apiClient.post(
                `/actions?device_id=${this.currentDeviceId}`,
                {
                    action: actionConfig,
                    tags: tags
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
        const action = this.actions.find(a => a.id === actionId);
        if (!action) return;

        // TODO: Show edit modal
        alert('Edit functionality coming soon! For now, delete and recreate the action.');
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
