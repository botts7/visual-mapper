/**
 * Prerequisite Dialog Module
 * Visual Mapper v0.4.0-beta
 *
 * Shows a dialog when required services (accessibility, streaming) are missing
 * and offers options to create or run prerequisite flows.
 */

import { showToast } from './toast.js?v=0.4.0-beta.4';
import { PREREQ_NAMES } from './prerequisite-checker.js?v=0.4.0-beta';

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Show prerequisite setup dialog
 * @param {Object} wizard - Flow wizard instance
 * @param {string[]} missing - Array of missing prerequisite types
 * @param {Object} status - Full prerequisite status from checker
 * @returns {Promise<{action: string, prereqType?: string}>} - User's choice
 */
export function showPrerequisiteDialog(wizard, missing, status) {
    return new Promise((resolve) => {
        // Remove any existing dialog
        const existingDialog = document.getElementById('prerequisiteDialog');
        if (existingDialog) {
            existingDialog.remove();
        }

        const dialog = document.createElement('div');
        dialog.id = 'prerequisiteDialog';
        dialog.className = 'prerequisite-dialog-overlay';

        const prereqs = status?.prerequisites || {};

        dialog.innerHTML = `
            <div class="prerequisite-dialog">
                <h2>Setup Required</h2>
                <p class="prereq-intro">Some services need to be enabled for this feature to work properly.</p>

                <div class="prerequisite-list">
                    ${missing.map(prereq => renderPrerequisiteItem(prereq, prereqs[prereq] || {})).join('')}
                </div>

                <div class="prerequisite-actions">
                    <button id="btnSkipPrereqs" class="btn-secondary">
                        Skip & Continue Anyway
                    </button>
                </div>

                <button id="btnClosePrereqDialog" class="prereq-close-btn" title="Close">&times;</button>
            </div>
        `;

        document.body.appendChild(dialog);

        // Wire up event handlers
        wireupDialogEvents(dialog, wizard, missing, status, resolve);
    });
}

/**
 * Render a single prerequisite item
 * @private
 */
function renderPrerequisiteItem(prereq, config) {
    const hasFlow = !!config.flow_id;
    const isEnabled = prereq === 'streaming' ? config.active : config.enabled;
    const icon = isEnabled ? '\u2713' : '\u2717';
    const statusClass = isEnabled ? 'status-ok' : 'status-missing';
    const name = PREREQ_NAMES[prereq] || prereq;

    // Get setup instructions for this prereq type
    const instructions = SETUP_INSTRUCTIONS[prereq] || 'Complete setup on your device';

    return `
        <div class="prerequisite-item ${statusClass}" data-prereq="${prereq}">
            <span class="prereq-icon">${icon}</span>
            <div class="prereq-info">
                <strong>${name}</strong>
                <span class="prereq-status">
                    ${isEnabled ? 'Enabled' : instructions}
                </span>
            </div>
            <div class="prereq-item-actions">
                ${isEnabled
                    ? `<span class="prereq-done">Done</span>`
                    : `<button class="btn-small btn-primary btn-setup-now" data-prereq="${prereq}">Set Up Now</button>`
                }
            </div>
        </div>
    `;
}

// Setup instructions shown in the dialog
const SETUP_INSTRUCTIONS = {
    'streaming': 'Tap "Start now" on device when prompted',
    'accessibility': 'Find "Visual Mapper" in settings and enable it',
    'overlay_permission': 'Enable overlay permission for Visual Mapper'
};

// Shell commands to launch setup screens
const SETUP_COMMANDS = {
    'streaming': 'am start -n com.visualmapper.companion/.streaming.MediaProjectionRequestActivity',
    'accessibility': 'am start -a android.settings.ACCESSIBILITY_SETTINGS',
    'overlay_permission': 'am start -a android.settings.action.MANAGE_OVERLAY_PERMISSION'
};

/**
 * Wire up dialog event handlers
 * @private
 */
function wireupDialogEvents(dialog, wizard, missing, status, resolve) {
    // Close button
    const closeBtn = dialog.querySelector('#btnClosePrereqDialog');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            dialog.remove();
            resolve({ action: 'skip' });
        });
    }

    // Skip button
    const skipBtn = dialog.querySelector('#btnSkipPrereqs');
    if (skipBtn) {
        skipBtn.addEventListener('click', () => {
            dialog.remove();
            resolve({ action: 'skip' });
        });
    }

    // "Set Up Now" buttons - execute shell command directly
    dialog.querySelectorAll('.btn-setup-now').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const prereq = e.target.dataset.prereq;
            const command = SETUP_COMMANDS[prereq];

            if (!command) {
                showToast(`No setup command for ${prereq}`, 'error');
                return;
            }

            // Show loading state
            btn.disabled = true;
            btn.textContent = 'Opening...';

            try {
                // Execute shell command to open setup screen
                const response = await fetch(
                    `${getApiBase()}/shell/${encodeURIComponent(wizard.selectedDevice)}/execute`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ command })
                    }
                );

                if (!response.ok) {
                    throw new Error('Failed to execute setup command');
                }

                // Update button to show waiting state
                btn.textContent = 'Complete on device...';
                btn.classList.remove('btn-primary');
                btn.classList.add('btn-waiting');

                // Show instruction toast
                const instruction = SETUP_INSTRUCTIONS[prereq];
                showToast(instruction, 'info', 5000);

                // Start polling for completion (check every 2 seconds for 60 seconds)
                let attempts = 0;
                const maxAttempts = 30;
                const checkInterval = setInterval(async () => {
                    attempts++;

                    try {
                        const statusResponse = await fetch(
                            `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/status`
                        );
                        const newStatus = await statusResponse.json();
                        const prereqStatus = newStatus.prerequisites?.[prereq];
                        const isNowEnabled = prereq === 'streaming' ? prereqStatus?.active : prereqStatus?.enabled;

                        if (isNowEnabled) {
                            clearInterval(checkInterval);

                            // Update UI
                            const item = dialog.querySelector(`.prerequisite-item[data-prereq="${prereq}"]`);
                            if (item) {
                                item.classList.remove('status-missing');
                                item.classList.add('status-ok');
                                item.querySelector('.prereq-icon').textContent = '\u2713';
                                item.querySelector('.prereq-status').textContent = 'Enabled';
                                btn.textContent = '\u2713 Done';
                                btn.classList.remove('btn-waiting');
                                btn.classList.add('btn-success');
                            }

                            showToast(`${PREREQ_NAMES[prereq]} enabled!`, 'success');

                            // Check if all prerequisites now met
                            const stillMissing = missing.filter(p => {
                                const ps = newStatus.prerequisites?.[p];
                                return !(p === 'streaming' ? ps?.active : ps?.enabled);
                            });

                            if (stillMissing.length === 0) {
                                setTimeout(() => {
                                    dialog.remove();
                                    resolve({ action: 'completed' });
                                }, 1000);
                            }
                        }
                    } catch (err) {
                        console.warn('[PrerequisiteDialog] Status check failed:', err);
                    }

                    // Timeout - let user manually confirm
                    if (attempts >= maxAttempts) {
                        clearInterval(checkInterval);
                        btn.textContent = 'Check Again';
                        btn.classList.remove('btn-waiting');
                        btn.classList.add('btn-secondary');
                        btn.disabled = false;
                    }
                }, 2000);

            } catch (error) {
                console.error('[PrerequisiteDialog] Setup failed:', error);
                showToast(`Failed to open setup: ${error.message}`, 'error');
                btn.disabled = false;
                btn.textContent = 'Retry';
            }
        });
    });

    // Click outside to close
    dialog.addEventListener('click', (e) => {
        if (e.target === dialog) {
            dialog.remove();
            resolve({ action: 'skip' });
        }
    });

    // Escape key to close
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            dialog.remove();
            document.removeEventListener('keydown', escHandler);
            resolve({ action: 'skip' });
        }
    };
    document.addEventListener('keydown', escHandler);
}

/**
 * Run a prerequisite flow
 * @private
 */
async function runPrerequisiteFlow(wizard, prereqType, flowId) {
    const response = await fetch(
        `${getApiBase()}/flows/${encodeURIComponent(wizard.selectedDevice)}/${encodeURIComponent(flowId)}/execute`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sync: true, timeout: 60 })
        }
    );

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Flow execution failed');
    }

    const result = await response.json();

    // Record the run
    await fetch(
        `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/${prereqType}/record-run`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ success: result.success })
        }
    ).catch(() => {}); // Ignore recording errors

    if (!result.success) {
        throw new Error(result.error || 'Flow did not complete successfully');
    }

    return result;
}

/**
 * Show guidance panel for creating a prerequisite flow
 * @param {Object} wizard - Flow wizard instance
 * @param {string} prereqType - The prerequisite type being created
 * @returns {HTMLElement} - The guidance panel element
 */
export function showPrerequisiteGuidance(wizard, prereqType) {
    // Remove existing guidance panel
    const existing = document.getElementById('prereqGuidanceOverlay');
    if (existing) {
        existing.remove();
    }

    const guidance = PREREQUISITE_GUIDANCE[prereqType] || {
        title: 'Setup',
        steps: ['Complete the setup']
    };

    // Create a simple, minimal banner
    const overlay = document.createElement('div');
    overlay.id = 'prereqGuidanceOverlay';
    overlay.className = 'guidance-banner';

    // Simple single instruction - no complex navigation
    const allSteps = guidance.steps.join(' → ');

    overlay.innerHTML = `
        <div class="guidance-banner-simple">
            <div class="guidance-banner-icon">📋</div>
            <div class="guidance-banner-text">
                <strong>${guidance.title}:</strong> ${allSteps}
            </div>
            <div class="guidance-banner-buttons">
                <button id="btnCancelGuidance" class="btn-small btn-secondary">Cancel</button>
                <button id="btnFinishGuidance" class="btn-small btn-primary">Done</button>
            </div>
        </div>
    `;

    // Append to screenshot panel
    const screenshotPanel = document.querySelector('.screenshot-panel');
    if (screenshotPanel) {
        screenshotPanel.appendChild(overlay);
    } else {
        document.body.appendChild(overlay);
    }

    // Wire up events
    const cancelBtn = overlay.querySelector('#btnCancelGuidance');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            overlay.remove();
            wizard.recordMode = 'normal';
            wizard.prereqType = null;
        });
    }

    const finishBtn = overlay.querySelector('#btnFinishGuidance');
    if (finishBtn) {
        finishBtn.addEventListener('click', async () => {
            // Save the prerequisite flow
            // For streaming: just the launch step (auto-click handles the rest)
            // For accessibility: the recorded steps from wizard
            await saveAsPrerequisiteFlow(wizard, prereqType);
        });
    }

    return overlay;
}

/**
 * Hide the prerequisite guidance panel
 */
export function hidePrerequisiteGuidance() {
    const overlay = document.getElementById('prereqGuidanceOverlay');
    if (overlay) {
        overlay.remove();
    }
}

/**
 * Save the current flow as a prerequisite flow
 * @param {Object} wizard - Flow wizard instance
 * @param {string} prereqType - The prerequisite type
 */
async function saveAsPrerequisiteFlow(wizard, prereqType) {
    try {
        const name = PREREQ_NAMES[prereqType] || prereqType;

        // Generate a unique flow ID
        const flowId = `prereq_${prereqType}_${Date.now().toString(36)}`;

        // Build steps based on prereqType
        let steps = [];

        if (prereqType === 'streaming') {
            // Streaming: single step to launch permission dialog (auto-click handles the rest)
            steps = [{
                step_type: 'shell',
                command: 'am start -n com.visualmapper.companion/.streaming.MediaProjectionRequestActivity'
            }];
        } else if (prereqType === 'accessibility') {
            // Accessibility: use recorded steps, or default to opening settings
            steps = wizard.flowSteps?.length > 0 ? wizard.flowSteps : [{
                step_type: 'shell',
                command: 'am start -a android.settings.ACCESSIBILITY_SETTINGS'
            }];
        } else if (prereqType === 'overlay_permission') {
            // Overlay: use recorded steps, or default to opening settings
            steps = wizard.flowSteps?.length > 0 ? wizard.flowSteps : [{
                step_type: 'shell',
                command: 'am start -a android.settings.action.MANAGE_OVERLAY_PERMISSION'
            }];
        } else {
            // Other: use whatever was recorded
            steps = wizard.flowSteps || [];
        }

        // Create the flow
        const flowData = {
            flow_id: flowId,
            device_id: wizard.selectedDevice,
            name: `Setup: ${name}`,
            description: `Prerequisite flow to enable ${name}`,
            steps: steps,
            enabled: false // Don't auto-run as a regular flow
        };

        console.log('[PrerequisiteDialog] Saving flow:', JSON.stringify(flowData, null, 2));

        const response = await fetch(
            `${getApiBase()}/flows`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(flowData)
            }
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            console.error('[PrerequisiteDialog] Server error:', errorData);
            throw new Error(errorData.detail || 'Failed to save flow');
        }

        const savedFlow = await response.json();
        const savedFlowId = savedFlow.flow_id || savedFlow.id || flowId;

        // Link as prerequisite
        await fetch(
            `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/${prereqType}/link-flow`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ flow_id: savedFlowId })
            }
        );

        showToast(`Saved ${name} setup flow`, 'success');
        hidePrerequisiteGuidance();

        // Reset wizard state
        wizard.recordMode = 'normal';
        wizard.prereqType = null;
        wizard.flowSteps = [];

        return flowId;

    } catch (error) {
        console.error('[PrerequisiteDialog] Failed to save prerequisite flow:', error);
        showToast(`Failed to save: ${error.message}`, 'error');
        throw error;
    }
}

/**
 * Guidance text for each prerequisite type
 * Keep it simple - just one clear instruction
 */
const PREREQUISITE_GUIDANCE = {
    'accessibility': {
        title: 'Enable Accessibility',
        steps: [
            'Scroll to find "Visual Mapper" and tap it',
            'Toggle the switch ON',
            'Tap "Allow" to confirm'
        ]
    },
    'streaming': {
        title: 'Allow Screen Capture',
        steps: [
            'Tap "Start now" on your device (auto-clicks when accessibility enabled)'
        ]
    },
    'overlay_permission': {
        title: 'Enable Overlay',
        steps: [
            'Find "Visual Mapper Companion" and enable it'
        ]
    }
};

export default showPrerequisiteDialog;
