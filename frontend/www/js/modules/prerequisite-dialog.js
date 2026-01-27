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

    return `
        <div class="prerequisite-item ${statusClass}" data-prereq="${prereq}">
            <span class="prereq-icon">${icon}</span>
            <div class="prereq-info">
                <strong>${name}</strong>
                <span class="prereq-status">
                    ${isEnabled ? 'Enabled' : (hasFlow ? 'Setup flow available' : 'Not configured')}
                </span>
            </div>
            <div class="prereq-item-actions">
                ${hasFlow
                    ? `<button class="btn-small btn-primary btn-run" data-prereq="${prereq}" data-flow-id="${config.flow_id}">Run Setup</button>`
                    : `<button class="btn-small btn-secondary btn-create" data-prereq="${prereq}">Create Flow</button>`
                }
                <label class="auto-run-toggle" title="Auto-run this flow when entering features that need it">
                    <input type="checkbox" ${config.auto_run ? 'checked' : ''}
                           data-prereq="${prereq}" class="auto-run-checkbox"
                           ${!hasFlow ? 'disabled' : ''}>
                    Auto
                </label>
            </div>
        </div>
    `;
}

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

    // Run flow buttons
    dialog.querySelectorAll('.btn-run').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const prereq = e.target.dataset.prereq;
            const flowId = e.target.dataset.flowId;

            // Show loading state
            btn.disabled = true;
            btn.textContent = 'Running...';

            try {
                await runPrerequisiteFlow(wizard, prereq, flowId);
                showToast(`${PREREQ_NAMES[prereq]} setup completed`, 'success');

                // Re-check status
                const response = await fetch(
                    `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/status`
                );
                const newStatus = await response.json();

                // Update the item's appearance
                const item = dialog.querySelector(`.prerequisite-item[data-prereq="${prereq}"]`);
                if (item) {
                    const prereqStatus = newStatus.prerequisites?.[prereq];
                    const isNowEnabled = prereq === 'streaming' ? prereqStatus?.active : prereqStatus?.enabled;
                    if (isNowEnabled) {
                        item.classList.remove('status-missing');
                        item.classList.add('status-ok');
                        item.querySelector('.prereq-icon').textContent = '\u2713';
                        item.querySelector('.prereq-status').textContent = 'Enabled';
                        btn.textContent = '\u2713 Done';
                        btn.classList.remove('btn-primary');
                        btn.classList.add('btn-success');
                    } else {
                        btn.textContent = 'Retry';
                        btn.disabled = false;
                    }
                }

                // Check if all now met
                const stillMissing = missing.filter(p => {
                    const ps = newStatus.prerequisites?.[p];
                    return !(p === 'streaming' ? ps?.active : ps?.enabled);
                });

                if (stillMissing.length === 0) {
                    setTimeout(() => {
                        dialog.remove();
                        resolve({ action: 'completed' });
                    }, 500);
                }

            } catch (error) {
                console.error('[PrerequisiteDialog] Run failed:', error);
                showToast(`Failed to run setup: ${error.message}`, 'error');
                btn.disabled = false;
                btn.textContent = 'Retry';
            }
        });
    });

    // Create flow buttons
    dialog.querySelectorAll('.btn-create').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const prereq = e.target.dataset.prereq;
            dialog.remove();
            resolve({ action: 'create', prereqType: prereq });
        });
    });

    // Auto-run checkboxes
    dialog.querySelectorAll('.auto-run-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', async (e) => {
            const prereq = e.target.dataset.prereq;
            const enabled = e.target.checked;

            try {
                await fetch(
                    `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/${prereq}/set-auto-run`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled })
                    }
                );
                showToast(`Auto-run ${enabled ? 'enabled' : 'disabled'} for ${PREREQ_NAMES[prereq]}`, 'info');
            } catch (error) {
                console.warn('[PrerequisiteDialog] Failed to set auto-run:', error);
                e.target.checked = !enabled; // Revert
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
            // This will trigger saving the flow as a prerequisite
            if (wizard.recorder && wizard.flowSteps && wizard.flowSteps.length > 0) {
                await saveAsPrerequisiteFlow(wizard, prereqType);
            } else {
                showToast('No steps recorded yet', 'warning');
            }
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

        // Create the flow
        const flowData = {
            name: `Setup: ${name}`,
            description: `Prerequisite flow to enable ${name}`,
            steps: wizard.flowSteps,
            is_prerequisite: true,
            prereq_type: prereqType,
            enabled: false // Don't auto-run as a regular flow
        };

        const response = await fetch(
            `${getApiBase()}/flows/${encodeURIComponent(wizard.selectedDevice)}`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(flowData)
            }
        );

        if (!response.ok) {
            throw new Error('Failed to save flow');
        }

        const savedFlow = await response.json();
        const flowId = savedFlow.flow_id || savedFlow.id;

        // Link as prerequisite
        await fetch(
            `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/${prereqType}/link-flow`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ flow_id: flowId })
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
        title: 'Start Streaming',
        steps: [
            'Go to Settings tab',
            'Tap "Start Streaming"',
            'Tap "Start now" to allow'
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
