/**
 * Flow Wizard Dialogs Module
 * Visual Mapper v0.0.5
 *
 * All dialog methods for sensor and action creation
 * Extracted from flow-wizard.js for better modularity
 */

import { showToast } from './toast.js?v=0.0.5';

/**
 * Prompt user for text input
 * @param {FlowWizard} wizard - FlowWizard instance
 * @returns {Promise<string|null>} Text or null if cancelled
 */
export async function promptForText(wizard) {
    const text = prompt('Enter text to type:');
    return text && text.trim() !== '' ? text.trim() : null;
}

/**
 * Create text sensor using full SensorCreator dialog
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} element - Element object
 * @param {Object} coords - Coordinate object
 */
export async function createTextSensor(wizard, element, coords) {
    // Use full SensorCreator dialog (same as sensors.html page)
    const elementIndex = element?.index || 0;
    wizard.sensorCreator.show(wizard.selectedDevice, element, elementIndex);

    // Note: SensorCreator handles saving directly via API
    // We don't add a flow step here since sensor creation is independent of flow recording
}

/**
 * Create image sensor using full SensorCreator dialog
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} element - Element object
 * @param {Object} coords - Coordinate object
 */
export async function createImageSensor(wizard, element, coords) {
    // Use full SensorCreator dialog (same as sensors.html page)
    const elementIndex = element?.index || 0;
    wizard.sensorCreator.show(wizard.selectedDevice, element, elementIndex);
    // Callback will be triggered by onSensorCreated when sensor is created
}

/**
 * Handle sensor created callback - adds capture_sensors step to flow
 * Called by SensorCreator.onSensorCreated callback
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} response - API response
 * @param {Object} sensorData - Sensor data
 */
export function handleSensorCreated(wizard, response, sensorData) {
    console.log('[FlowWizard] Sensor created, adding capture step:', response, sensorData);

    // Only add to flow if we have an active recorder (step 3)
    if (!wizard.recorder) {
        console.log('[FlowWizard] No active recorder, skipping flow step');
        return;
    }

    // Get the sensor ID from the response (API returns { sensor: { sensor_id: ... } })
    const sensorId = response?.sensor?.sensor_id || response?.sensor_id || sensorData?.sensor_id;
    if (!sensorId) {
        console.warn('[FlowWizard] No sensor ID in response, cannot add flow step');
        return;
    }

    // Get friendly name from response or sensorData
    const friendlyName = response?.sensor?.friendly_name || sensorData?.friendly_name || 'Sensor';

    // Add a capture_sensors step for this sensor
    const step = {
        step_type: 'capture_sensors',
        description: `Capture sensor: ${friendlyName}`,
        sensor_ids: [sensorId]
    };

    wizard.recorder.addStep(step);
    console.log('[FlowWizard] Added capture_sensors step for:', sensorId);
}

/**
 * Show action configuration dialog
 * Returns config object or null if cancelled
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {string} defaultName - Default action name
 * @param {number} stepCount - Number of steps
 * @returns {Promise<Object|null>} Config object or null if cancelled
 */
export async function promptForActionConfig(wizard, defaultName, stepCount) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.id = 'action-config-overlay';
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

        dialog.innerHTML = `
            <h3 style="margin-top: 0;">Configure Action</h3>
            <p style="color: #666; margin-bottom: 20px;">Creating action with ${stepCount} step${stepCount !== 1 ? 's' : ''}</p>

            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 4px; font-weight: 600;">Action Name:</label>
                <input type="text" id="actionName" value="${defaultName}"
                       style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
            </div>

            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 4px; font-weight: 600;">Description (optional):</label>
                <textarea id="actionDescription" rows="2" placeholder="What does this action do?"
                          style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;"></textarea>
            </div>

            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 4px;">
                    <input type="checkbox" id="stopOnError">
                    Stop if any step fails
                </label>
                <p style="color: #666; font-size: 13px; margin: 4px 0 0 24px;">
                    If checked, the action will stop executing when a step encounters an error.
                </p>
            </div>

            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 4px; font-weight: 600;">Tags (optional):</label>
                <input type="text" id="actionTags" placeholder="e.g., automation, setup, navigation"
                       style="width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">
                <p style="color: #666; font-size: 13px; margin: 4px 0 0 0;">
                    Comma-separated tags for organizing actions
                </p>
            </div>

            <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 24px;">
                <button id="cancelBtn" style="padding: 10px 20px; border: 1px solid #ccc; background: white; border-radius: 4px; cursor: pointer;">
                    Cancel
                </button>
                <button id="defaultsBtn" style="padding: 10px 20px; border: none; background: #6b7280; color: white; border-radius: 4px; cursor: pointer;">
                    Use Defaults
                </button>
                <button id="createBtn" style="padding: 10px 20px; border: none; background: #ec4899; color: white; border-radius: 4px; cursor: pointer;">
                    Create Action
                </button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Handle button clicks
        dialog.querySelector('#cancelBtn').addEventListener('click', () => {
            document.body.removeChild(overlay);
            resolve(null);
        });

        dialog.querySelector('#defaultsBtn').addEventListener('click', () => {
            const name = dialog.querySelector('#actionName').value.trim();
            if (!name) {
                alert('Please enter an action name');
                return;
            }
            document.body.removeChild(overlay);
            resolve({
                name,
                description: null,
                stopOnError: false,
                tags: []
            });
        });

        dialog.querySelector('#createBtn').addEventListener('click', () => {
            const name = dialog.querySelector('#actionName').value.trim();
            if (!name) {
                alert('Please enter an action name');
                return;
            }

            const description = dialog.querySelector('#actionDescription').value.trim() || null;
            const stopOnError = dialog.querySelector('#stopOnError').checked;
            const tagsInput = dialog.querySelector('#actionTags').value.trim();
            const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];

            document.body.removeChild(overlay);
            resolve({
                name,
                description,
                stopOnError,
                tags
            });
        });
    });
}

/**
 * Create action from recorded steps
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} element - Element object
 * @param {Object} coords - Coordinate object
 */
export async function createAction(wizard, element, coords) {
    try {
        // Get all recorded steps up to this point
        const steps = wizard.recorder.getSteps();

        if (steps.length === 0) {
            showToast('No steps recorded yet. Record some steps first!', 'warning', 3000);
            return;
        }

        // Show configuration dialog
        const config = await promptForActionConfig(wizard, element?.text || 'Custom Action', steps.length);
        if (!config) return;

        // Create action via API (using correct ActionCreateRequest structure)
        const response = await fetch(`/api/actions?device_id=${encodeURIComponent(wizard.selectedDevice)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: {
                    action_type: 'macro',
                    name: config.name,
                    description: config.description,
                    device_id: wizard.selectedDevice,
                    enabled: true,
                    actions: steps,
                    stop_on_error: config.stopOnError
                },
                tags: config.tags
            })
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

            throw new Error(error.detail || 'Failed to create action');
        }

        const result = await response.json();
        showToast(`Action "${config.name}" created successfully! (ID: ${result.action.id})`, 'success', 5000);

        console.log('[FlowWizard] Created action:', result.action);
    } catch (error) {
        console.error('[FlowWizard] Failed to create action:', error);
        showToast(`Failed to create action: ${error.message}`, 'error', 5000);
    }
}

/**
 * Prompt for sensor name
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {string} defaultName - Default sensor name
 * @returns {Promise<string|null>} Sensor name or null if cancelled
 */
export async function promptForSensorName(wizard, defaultName) {
    const name = prompt(`Enter sensor name:`, defaultName);
    return name && name.trim() !== '' ? name.trim() : null;
}

/**
 * Add action step from element - shows dialog with choice
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} element - Element object
 */
export async function addActionStepFromElement(wizard, element) {
    try {
        // Get all recorded steps
        const steps = wizard.recorder.getSteps();

        if (steps.length === 0) {
            showToast('No steps recorded yet. Record some steps first!', 'warning', 3000);
            return;
        }

        // Show action creation dialog with choice
        const config = await promptForActionCreation(wizard, element?.text || 'Custom Action', steps.length);
        if (!config) return;

        // Create action via API
        const response = await fetch(`/api/actions?device_id=${encodeURIComponent(wizard.selectedDevice)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: {
                    action_type: 'macro',
                    name: config.name,
                    description: config.description,
                    device_id: wizard.selectedDevice,
                    enabled: true,
                    actions: steps,
                    stop_on_error: config.stopOnError || false
                },
                tags: config.tags || []
            })
        });

        if (!response.ok) {
            const error = await response.json();
            if (response.status === 422 && Array.isArray(error.detail)) {
                const errorMessages = error.detail.map(e =>
                    `${e.loc.join('.')}: ${e.msg}`
                ).join('; ');
                throw new Error(errorMessages || 'Validation failed');
            }
            throw new Error(error.detail || 'Failed to create action');
        }

        const result = await response.json();
        const actionId = result.action.id;

        showToast(`Action "${config.name}" created successfully!`, 'success', 3000);

        // Handle user's choice
        if (config.addToFlow) {
            // Replace recorded steps with execute_action step
            wizard.recorder.clearSteps();

            const executeStep = {
                step_type: 'execute_action',
                action_id: actionId,
                description: `Execute: ${config.name}`
            };

            wizard.recorder.addStep(executeStep);
            showToast('Steps replaced with execute_action step', 'info', 2000);
        } else {
            // Keep recorded steps, just notify action was saved
            showToast('Action saved for Home Assistant triggering', 'info', 2000);
        }

        console.log('[FlowWizard] Created action:', result.action);

    } catch (error) {
        console.error('[FlowWizard] Failed to create action:', error);
        showToast(`Failed to create action: ${error.message}`, 'error', 5000);
    }
}

/**
 * Show action creation dialog with choice
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {string} defaultName - Default action name
 * @param {number} stepCount - Number of steps
 * @returns {Promise<Object|null>} Config object or null if cancelled
 */
export async function promptForActionCreation(wizard, defaultName, stepCount) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'modal-content';

        dialog.innerHTML = `
            <h3>Create Action</h3>
            <p class="modal-info">Creating action from ${stepCount} recorded step${stepCount !== 1 ? 's' : ''}</p>

            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 4px; font-weight: 600;">Action Name:</label>
                <input type="text" id="actionName" value="${defaultName}"
                       style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: 4px; background: var(--card-background); color: var(--text-color);">
            </div>

            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 4px; font-weight: 600;">Description (optional):</label>
                <textarea id="actionDescription" rows="2" placeholder="What does this action do?"
                          style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: 4px; background: var(--card-background); color: var(--text-color);"></textarea>
            </div>

            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 4px; font-weight: 600;">Tags (optional):</label>
                <input type="text" id="actionTags" placeholder="e.g., navigation, setup"
                       style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: 4px; background: var(--card-background); color: var(--text-color);">
                <p style="color: var(--text-secondary); font-size: 12px; margin: 4px 0 0 0;">
                    Comma-separated tags for organizing actions
                </p>
            </div>

            <div style="margin-bottom: 20px; padding: 16px; background: var(--background-color); border: 1px solid var(--border-color); border-radius: 6px;">
                <label style="display: block; margin-bottom: 12px; font-weight: 600;">What do you want to do?</label>

                <label style="display: flex; align-items: flex-start; gap: 10px; padding: 10px; border: 2px solid var(--border-color); border-radius: 6px; cursor: pointer; margin-bottom: 8px; background: var(--card-background);" class="choice-option">
                    <input type="radio" name="actionChoice" value="add-to-flow" checked style="margin-top: 3px;">
                    <div>
                        <div style="font-weight: 600; margin-bottom: 4px;">Add to Flow</div>
                        <div style="font-size: 13px; color: var(--text-secondary);">Replace these steps with execute_action in current flow (modular)</div>
                    </div>
                </label>

                <label style="display: flex; align-items: flex-start; gap: 10px; padding: 10px; border: 2px solid var(--border-color); border-radius: 6px; cursor: pointer; background: var(--card-background);" class="choice-option">
                    <input type="radio" name="actionChoice" value="save-only" style="margin-top: 3px;">
                    <div>
                        <div style="font-weight: 600; margin-bottom: 4px;">Save Only</div>
                        <div style="font-size: 13px; color: var(--text-secondary);">Create action for HA triggering (keep detailed steps in flow)</div>
                    </div>
                </label>
            </div>

            <div class="modal-buttons">
                <button class="btn btn-secondary" id="cancelAction">Cancel</button>
                <button class="btn btn-primary" id="createAction">Create Action</button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Highlight selected choice
        dialog.querySelectorAll('.choice-option').forEach(label => {
            label.addEventListener('click', () => {
                dialog.querySelectorAll('.choice-option').forEach(l => {
                    l.style.borderColor = 'var(--border-color)';
                });
                label.style.borderColor = 'var(--primary-color)';
            });
        });

        // Pre-select first option
        dialog.querySelector('.choice-option').style.borderColor = 'var(--primary-color)';

        // Handle cancel
        dialog.querySelector('#cancelAction').addEventListener('click', () => {
            document.body.removeChild(overlay);
            resolve(null);
        });

        // Handle create
        dialog.querySelector('#createAction').addEventListener('click', () => {
            const name = dialog.querySelector('#actionName').value.trim();
            if (!name) {
                alert('Please enter an action name');
                return;
            }

            const description = dialog.querySelector('#actionDescription').value.trim() || null;
            const tagsInput = dialog.querySelector('#actionTags').value.trim();
            const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(t => t) : [];
            const choice = dialog.querySelector('input[name="actionChoice"]:checked').value;
            const addToFlow = choice === 'add-to-flow';

            document.body.removeChild(overlay);
            resolve({
                name,
                description,
                tags,
                stopOnError: false,
                addToFlow
            });
        });
    });
}

/**
 * Prompt user for wait/delay duration
 * @param {FlowWizard} wizard - FlowWizard instance
 * @returns {Promise<number|null>} Duration in milliseconds, or null if cancelled
 */
export async function promptForWaitDuration(wizard) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'modal-content';
        dialog.style.maxWidth = '400px';

        dialog.innerHTML = `
            <h3>Add Wait/Delay Step</h3>
            <p style="margin: 0 0 20px 0; color: var(--text-secondary); font-size: 14px;">
                Add a pause between flow steps to wait for UI updates, animations, or network requests.
            </p>

            <div style="margin-bottom: 20px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 600;">
                    Wait Duration:
                </label>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <input type="number" id="waitDuration" min="0.1" max="60" step="0.1" value="1"
                        style="flex: 1; padding: 8px 12px; border: 1px solid var(--border-color); border-radius: 4px; font-size: 14px;" />
                    <select id="waitUnit" style="padding: 8px 12px; border: 1px solid var(--border-color); border-radius: 4px; font-size: 14px;">
                        <option value="1000">seconds</option>
                        <option value="60000">minutes</option>
                    </select>
                </div>
            </div>

            <div style="display: flex; gap: 10px; justify-content: flex-end;">
                <button id="btnCancelWait" class="btn btn-secondary">Cancel</button>
                <button id="btnAddWait" class="btn btn-primary">Add Wait Step</button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Focus on duration input
        const durationInput = dialog.querySelector('#waitDuration');
        setTimeout(() => durationInput?.focus(), 100);

        // Handle Add button
        dialog.querySelector('#btnAddWait').onclick = () => {
            const duration = parseFloat(durationInput.value);
            const unit = parseInt(dialog.querySelector('#waitUnit').value);

            if (isNaN(duration) || duration <= 0) {
                showToast('Please enter a valid duration', 'warning', 2000);
                return;
            }

            const durationMs = duration * unit;

            document.body.removeChild(overlay);
            resolve(durationMs);
        };

        // Handle Cancel button
        dialog.querySelector('#btnCancelWait').onclick = () => {
            document.body.removeChild(overlay);
            resolve(null);
        };

        // Close on overlay click
        overlay.onclick = (e) => {
            if (e.target === overlay) {
                document.body.removeChild(overlay);
                resolve(null);
            }
        };

        // Handle Enter key
        durationInput.onkeydown = (e) => {
            if (e.key === 'Enter') {
                dialog.querySelector('#btnAddWait').click();
            } else if (e.key === 'Escape') {
                dialog.querySelector('#btnCancelWait').click();
            }
        };
    });
}

/**
 * Prompt user for timestamp validation configuration
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} element - The timestamp element
 * @param {Object} refreshStep - The refresh step being configured
 * @returns {Promise<Object|null>} Configuration or null if cancelled
 */
export async function promptForTimestampConfig(wizard, element, refreshStep) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'modal-content';
        dialog.style.maxWidth = '500px';

        const elementName = element.text?.substring(0, 30) || element['content-desc']?.substring(0, 30) || element.class;
        const stepType = refreshStep.step_type === 'pull_refresh' ? 'Pull-to-Refresh' : 'Restart App';

        dialog.innerHTML = `
            <h3>⏱️ Configure Timestamp Validation</h3>
            <p style="margin: 0 0 20px 0; color: var(--text-secondary); font-size: 14px;">
                Verify that <strong>${stepType}</strong> actually updates data by checking if this timestamp changes:
            </p>

            <div style="margin-bottom: 20px; padding: 12px; background: var(--background-color); border: 1px solid var(--border-color); border-radius: 6px;">
                <div style="font-weight: 600; margin-bottom: 4px;">Timestamp Element:</div>
                <div style="font-family: monospace; font-size: 13px; color: var(--text-secondary);">${elementName}</div>
            </div>

            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 600;">
                    Max Refresh Retries:
                </label>
                <input type="number" id="timestampMaxRetries" min="1" max="10" step="1" value="3"
                    style="width: 100%; padding: 8px 12px; border: 1px solid var(--border-color); border-radius: 4px; font-size: 14px;" />
                <div style="margin-top: 4px; font-size: 12px; color: var(--text-secondary);">
                    How many times to retry refresh if timestamp doesn't change
                </div>
            </div>

            <div style="margin-bottom: 20px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 600;">
                    Retry Delay (ms):
                </label>
                <input type="number" id="timestampRetryDelay" min="500" max="10000" step="500" value="2000"
                    style="width: 100%; padding: 8px 12px; border: 1px solid var(--border-color); border-radius: 4px; font-size: 14px;" />
                <div style="margin-top: 4px; font-size: 12px; color: var(--text-secondary);">
                    How long to wait between retries (milliseconds)
                </div>
            </div>

            <div style="padding: 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; margin-bottom: 20px;">
                <div style="font-weight: 600; margin-bottom: 4px; color: #856404;">💡 How it works:</div>
                <div style="font-size: 13px; color: #856404;">
                    1. Execute refresh action<br>
                    2. Wait and check if timestamp changed<br>
                    3. If unchanged, refresh again (up to max retries)<br>
                    4. If changed or max retries reached, continue flow
                </div>
            </div>

            <div style="display: flex; gap: 10px; justify-content: flex-end;">
                <button id="btnCancelTimestamp" class="btn btn-secondary">Cancel</button>
                <button id="btnAddTimestamp" class="btn btn-primary">Enable Validation</button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Focus on max retries input
        const retriesInput = dialog.querySelector('#timestampMaxRetries');
        setTimeout(() => retriesInput?.focus(), 100);

        // Handle Enable button
        dialog.querySelector('#btnAddTimestamp').onclick = () => {
            const maxRetries = parseInt(retriesInput.value);
            const retryDelay = parseInt(dialog.querySelector('#timestampRetryDelay').value);

            if (isNaN(maxRetries) || maxRetries < 1 || maxRetries > 10) {
                showToast('Max retries must be between 1 and 10', 'warning', 2000);
                return;
            }

            if (isNaN(retryDelay) || retryDelay < 500 || retryDelay > 10000) {
                showToast('Retry delay must be between 500 and 10000 ms', 'warning', 2000);
                return;
            }

            document.body.removeChild(overlay);
            resolve({
                maxRetries,
                retryDelay
            });
        };

        // Handle Cancel button
        dialog.querySelector('#btnCancelTimestamp').onclick = () => {
            document.body.removeChild(overlay);
            resolve(null);
        };

        // Close on overlay click
        overlay.onclick = (e) => {
            if (e.target === overlay) {
                document.body.removeChild(overlay);
                resolve(null);
            }
        };

        // Handle Enter key
        retriesInput.onkeydown = (e) => {
            if (e.key === 'Enter') {
                dialog.querySelector('#btnAddTimestamp').click();
            } else if (e.key === 'Escape') {
                dialog.querySelector('#btnCancelTimestamp').click();
            }
        };
    });
}

/**
 * Add a wait/delay step to the flow
 * @param {FlowWizard} wizard - FlowWizard instance
 */
export async function addWaitStep(wizard) {
    const duration = await promptForWaitDuration(wizard);

    if (duration === null) {
        return; // User cancelled
    }

    // Add wait step to recorder
    wizard.recorder.addStep({
        step_type: 'wait',
        duration: duration,
        description: `Wait ${duration >= 1000 ? (duration / 1000).toFixed(1) + 's' : duration + 'ms'}`
    });

    const durationText = duration >= 1000 ? `${(duration / 1000).toFixed(1)}s` : `${duration}ms`;
    showToast(`Added ${durationText} wait step`, 'success', 2000);
}

/**
 * Show dialog to insert an existing sensor into the flow
 * Uses smart element detection at runtime
 * @param {FlowWizard} wizard - FlowWizard instance
 * @returns {Promise<boolean>} True if sensor was inserted
 */
export async function showInsertSensorDialog(wizard) {
    return new Promise(async (resolve) => {
        try {
            // Fetch existing sensors for this device
            const response = await fetch(`/api/sensors/${encodeURIComponent(wizard.selectedDevice)}`);
            const data = await response.json();
            const sensors = data.sensors || [];

            if (sensors.length === 0) {
                showToast('No sensors found for this device. Create one first!', 'warning', 3000);
                resolve(false);
                return;
            }

            // Create dialog overlay
            const overlay = document.createElement('div');
            overlay.id = 'insert-sensor-overlay';
            overlay.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0, 0, 0, 0.7); z-index: 10000;
                display: flex; align-items: center; justify-content: center;
            `;

            const dialog = document.createElement('div');
            dialog.style.cssText = `
                background: var(--card-background, #1e1e1e); border-radius: 8px;
                padding: 20px; max-width: 500px; width: 90%; max-height: 70vh;
                overflow-y: auto; color: var(--text-color, #e0e0e0);
            `;

            dialog.innerHTML = `
                <h3 style="margin: 0 0 15px 0;">📊 Insert Existing Sensor</h3>
                <p style="margin-bottom: 15px; color: #888; font-size: 0.9em;">
                    Select a sensor to add to this flow. Smart detection will find the element at runtime,
                    even if it has moved.
                </p>
                <div id="sensorList" style="max-height: 400px; overflow-y: auto;">
                    ${sensors.map(s => {
                        // Extract useful display info
                        const resourceId = s.source?.element_resource_id ? s.source.element_resource_id.split('/').pop() : null;
                        const elementText = s.source?.element_text || null;
                        // Extract app name from resource_id (e.g., "com.byd.bydautolink:id/tem_tv" -> "bydautolink")
                        const appPackage = s.source?.element_resource_id ? s.source.element_resource_id.split(':')[0].split('.').pop() : null;
                        const extractionMethod = s.extraction_rule?.method || 'exact';
                        const deviceClass = s.device_class && s.device_class !== 'none' ? s.device_class : null;
                        const currentValue = s.current_value;
                        const unit = s.unit_of_measurement || '';
                        const lastUpdated = s.updated_at ? new Date(s.updated_at).toLocaleString() : null;

                        return `
                        <div class="sensor-option" data-sensor-id="${s.sensor_id}" data-sensor-name="${s.friendly_name}" style="
                            padding: 12px; margin: 5px 0; background: rgba(255,255,255,0.05);
                            border-radius: 6px; cursor: pointer; border: 2px solid transparent;
                            transition: all 0.2s;
                        " onmouseover="this.style.borderColor='#4CAF50'" onmouseout="this.style.borderColor='transparent'">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-weight: bold; font-size: 1.05em;">${s.friendly_name}</span>
                                ${currentValue !== null && currentValue !== undefined ?
                                    `<span style="background: #4CAF50; color: white; padding: 2px 8px; border-radius: 10px; font-size: 0.85em; font-weight: 600;">${currentValue}${unit}</span>` :
                                    `<span style="background: #666; color: #ccc; padding: 2px 8px; border-radius: 10px; font-size: 0.8em;">No value</span>`
                                }
                            </div>
                            <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px;">
                                ${appPackage ? `<span style="background: rgba(33,150,243,0.2); color: #64B5F6; padding: 2px 6px; border-radius: 4px; font-size: 0.75em;">📱 ${appPackage}</span>` : ''}
                                ${deviceClass ? `<span style="background: rgba(156,39,176,0.2); color: #CE93D8; padding: 2px 6px; border-radius: 4px; font-size: 0.75em;">📊 ${deviceClass}</span>` : ''}
                                ${extractionMethod ? `<span style="background: rgba(255,152,0,0.2); color: #FFB74D; padding: 2px 6px; border-radius: 4px; font-size: 0.75em;">🔧 ${extractionMethod}</span>` : ''}
                            </div>
                            <div style="font-size: 0.8em; color: #888; margin-top: 6px;">
                                ${resourceId ? `<div>🆔 <code style="background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 3px;">${resourceId}</code></div>` : ''}
                                ${elementText ? `<div style="margin-top: 2px;">📝 "${elementText.length > 40 ? elementText.substring(0, 40) + '...' : elementText}"</div>` : ''}
                            </div>
                            ${lastUpdated ? `<div style="font-size: 0.7em; color: #666; margin-top: 4px;">⏱️ Last: ${lastUpdated}</div>` : ''}
                        </div>
                    `;}).join('')}
                </div>
                <div style="display: flex; gap: 10px; margin-top: 15px; justify-content: flex-end;">
                    <button id="cancelBtn" class="btn" style="background: #666;">Cancel</button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            // Handle sensor selection
            dialog.querySelectorAll('.sensor-option').forEach(option => {
                option.addEventListener('click', () => {
                    const sensorId = option.dataset.sensorId;
                    const sensorName = option.querySelector('div').textContent;

                    // Add capture_sensors step to flow
                    if (wizard.recorder) {
                        wizard.recorder.addStep({
                            step_type: 'capture_sensors',
                            sensor_ids: [sensorId],
                            description: `Capture: ${sensorName}`
                        });
                        showToast(`Added sensor: ${sensorName}`, 'success', 2000);
                    }

                    document.body.removeChild(overlay);
                    resolve(true);
                });
            });

            // Handle cancel
            dialog.querySelector('#cancelBtn').addEventListener('click', () => {
                document.body.removeChild(overlay);
                resolve(false);
            });

            // Click outside to cancel
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    document.body.removeChild(overlay);
                    resolve(false);
                }
            });

        } catch (error) {
            console.error('[FlowWizard] Failed to load sensors:', error);
            showToast('Failed to load sensors', 'error', 3000);
            resolve(false);
        }
    });
}

/**
 * Show dialog to insert an existing action into the flow
 * @param {FlowWizard} wizard - FlowWizard instance
 * @returns {Promise<boolean>} True if action was inserted
 */
export async function showInsertActionDialog(wizard) {
    return new Promise(async (resolve) => {
        try {
            // Fetch existing actions for this device
            const response = await fetch(`/api/actions/${encodeURIComponent(wizard.selectedDevice)}`);
            const data = await response.json();
            const actions = data.actions || [];

            if (actions.length === 0) {
                showToast('No actions found for this device. Create one first!', 'warning', 3000);
                resolve(false);
                return;
            }

            // Create dialog overlay
            const overlay = document.createElement('div');
            overlay.id = 'insert-action-overlay';
            overlay.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0, 0, 0, 0.7); z-index: 10000;
                display: flex; align-items: center; justify-content: center;
            `;

            const dialog = document.createElement('div');
            dialog.style.cssText = `
                background: var(--card-background, #1e1e1e); border-radius: 8px;
                padding: 20px; max-width: 500px; width: 90%; max-height: 70vh;
                overflow-y: auto; color: var(--text-color, #e0e0e0);
            `;

            dialog.innerHTML = `
                <h3 style="margin: 0 0 15px 0;">⚡ Insert Existing Action</h3>
                <p style="margin-bottom: 15px; color: #888; font-size: 0.9em;">
                    Select an action to add to this flow. The action will execute its steps when the flow runs.
                </p>
                <div id="actionList" style="max-height: 300px; overflow-y: auto;">
                    ${actions.map(a => `
                        <div class="action-option" data-action-id="${a.id}" style="
                            padding: 12px; margin: 5px 0; background: rgba(255,255,255,0.05);
                            border-radius: 6px; cursor: pointer; border: 2px solid transparent;
                            transition: all 0.2s;
                        " onmouseover="this.style.borderColor='#2196F3'" onmouseout="this.style.borderColor='transparent'">
                            <div style="font-weight: bold;">${a.action?.name || 'Unnamed Action'}</div>
                            <div style="font-size: 0.85em; color: #888; margin-top: 4px;">
                                Type: ${a.action?.action_type || 'unknown'}
                                ${a.action?.actions ? ` • ${a.action.actions.length} steps` : ''}
                            </div>
                            <div style="font-size: 0.8em; color: #666; margin-top: 2px;">
                                ${a.execution_count ? `Executed ${a.execution_count} times` : 'Never executed'}
                            </div>
                        </div>
                    `).join('')}
                </div>
                <div style="display: flex; gap: 10px; margin-top: 15px; justify-content: flex-end;">
                    <button id="cancelBtn" class="btn" style="background: #666;">Cancel</button>
                </div>
            `;

            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            // Handle action selection
            dialog.querySelectorAll('.action-option').forEach(option => {
                option.addEventListener('click', () => {
                    const actionId = option.dataset.actionId;
                    const actionName = option.querySelector('div').textContent;

                    // Add execute_action step to flow
                    if (wizard.recorder) {
                        wizard.recorder.addStep({
                            step_type: 'execute_action',
                            action_id: actionId,
                            description: `Execute: ${actionName}`
                        });
                        showToast(`Added action: ${actionName}`, 'success', 2000);
                    }

                    document.body.removeChild(overlay);
                    resolve(true);
                });
            });

            // Handle cancel
            dialog.querySelector('#cancelBtn').addEventListener('click', () => {
                document.body.removeChild(overlay);
                resolve(false);
            });

            // Click outside to cancel
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    document.body.removeChild(overlay);
                    resolve(false);
                }
            });

        } catch (error) {
            console.error('[FlowWizard] Failed to load actions:', error);
            showToast('Failed to load actions', 'error', 3000);
            resolve(false);
        }
    });
}

// Dual export pattern: ES6 export + window global
const FlowWizardDialogs = {
    promptForText,
    createTextSensor,
    createImageSensor,
    handleSensorCreated,
    promptForActionConfig,
    createAction,
    promptForSensorName,
    addActionStepFromElement,
    promptForActionCreation,
    promptForWaitDuration,
    promptForTimestampConfig,
    addWaitStep,
    showInsertSensorDialog,
    showInsertActionDialog
};

window.FlowWizardDialogs = FlowWizardDialogs;

export default FlowWizardDialogs;
