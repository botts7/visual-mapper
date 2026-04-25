/**
 * Prerequisite Dialog Module
 * Visual Mapper v0.4.0-beta
 *
 * Shows a dialog when required services (accessibility, streaming) are missing
 * and offers options to create or run prerequisite flows.
 */

import { showToast } from './toast.js?v=0.4.0-beta.4';
import { PREREQ_NAMES } from './prerequisite-checker.js?v=0.4.0-beta.4';

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

        // DEPENDENCY: Streaming requires accessibility to work properly
        // If streaming is missing and accessibility is not enabled, add accessibility to the list
        let effectiveMissing = [...missing];
        if (effectiveMissing.includes('streaming')) {
            const accessStatus = prereqs.accessibility || {};
            const accessEnabled = accessStatus.enabled || accessStatus.fully_operational;
            if (!accessEnabled && !effectiveMissing.includes('accessibility')) {
                console.log('[PrerequisiteDialog] Adding accessibility as dependency for streaming');
                effectiveMissing.unshift('accessibility'); // Add at beginning (priority)
            }
        }

        // Sort: accessibility first (it's a dependency for streaming)
        effectiveMissing.sort((a, b) => {
            if (a === 'accessibility') return -1;
            if (b === 'accessibility') return 1;
            return 0;
        });

        // Use effectiveMissing instead of missing for the rest
        missing = effectiveMissing;

        // Customize message based on what's missing
        const introText = missing.length === 1
            ? `Enable ${PREREQ_NAMES[missing[0]] || missing[0]} to continue.`
            : 'Enable the following services to continue.';

        dialog.innerHTML = `
            <div class="prerequisite-dialog">
                <h2>${missing.length === 1 ? 'Quick Setup' : 'Setup Required'}</h2>
                <p class="prereq-intro">${introText}</p>

                <div class="prerequisite-list">
                    ${missing.map(prereq => renderPrerequisiteItem(prereq, prereqs[prereq] || {}, prereqs)).join('')}
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

        // AUTO-START: Only auto-start if it's the streaming prerequisite (user just needs to tap "Start now")
        // For accessibility, always show the dialog since the user needs to navigate and toggle manually
        // This keeps the dialog visible so users can see what's happening
        const firstActionableBtn = dialog.querySelector('.btn-setup-now:not([disabled])');
        if (firstActionableBtn && missing.length === 1) {
            const prereqType = firstActionableBtn.dataset.prereq;

            // Only auto-start for streaming (simpler - just tap "Start now" on device)
            // For accessibility, user needs to find and enable the service manually
            if (prereqType === 'streaming') {
                console.log('[PrerequisiteDialog] Auto-starting streaming setup (user just needs to tap Start now)');
                // Small delay for dialog to render, then auto-click
                setTimeout(() => {
                    firstActionableBtn.click();
                }, 300);
            } else {
                console.log(`[PrerequisiteDialog] Showing dialog for ${prereqType} - manual setup required`);
            }
        }
    });
}

/**
 * Render a single prerequisite item
 * @param {string} prereq - Prerequisite type
 * @param {Object} config - Prerequisite config
 * @param {Object} allPrereqs - All prerequisite configs (for dependency checking)
 * @private
 */
function renderPrerequisiteItem(prereq, config, allPrereqs = {}) {
    const hasFlow = !!config.flow_id;
    const isEnabled = prereq === 'streaming' ? config.active : config.enabled;
    const isFullyOperational = config.fully_operational || config.active;
    const icon = isEnabled ? '\u2713' : '\u2717';
    const statusClass = isEnabled ? 'status-ok' : 'status-missing';
    const name = PREREQ_NAMES[prereq] || prereq;

    // Get setup instructions for this prereq type
    let instructions = SETUP_INSTRUCTIONS[prereq] || 'Complete setup on your device';

    // Check if streaming is blocked by missing accessibility
    let blockedByDependency = false;
    let needsServerUpdate = false;
    let companionIp = null;

    if (prereq === 'streaming' && !isEnabled) {
        const accessStatus = allPrereqs.accessibility || {};
        const accessEnabled = accessStatus.enabled || accessStatus.fully_operational;
        if (!accessEnabled) {
            instructions = 'Enable Accessibility first, then set up streaming';
            blockedByDependency = true;
        }

        // Check if companion is announced via MQTT but not connected (server IP may have changed)
        if (config.needs_server_update) {
            needsServerUpdate = true;
            companionIp = config.companion_ip;
            instructions = `Companion app found on network but not connected. Update server IP in companion app settings.`;
        }
    }

    // Determine status message based on enabled + operational state
    let statusMessage = 'Ready to use';
    if (isEnabled && !isFullyOperational) {
        statusMessage = 'Enabled (waiting for connection)';
    } else if (isEnabled && isFullyOperational) {
        statusMessage = 'Ready to use';
    }

    // Determine which button to show
    let actionButton = '';
    if (isEnabled && isFullyOperational) {
        actionButton = `<span class="prereq-done">\u2713 Ready</span>`;
    } else if (isEnabled && !isFullyOperational) {
        // Enabled but not operational - show "Reconnect" or info
        actionButton = `<span class="prereq-partial">\u26a0 Connecting...</span>`;
    } else if (needsServerUpdate) {
        // Companion announced but not connected - need to update server IP
        actionButton = `<button class="btn-small btn-warning btn-update-server" data-prereq="${prereq}" data-companion-ip="${companionIp || ''}">Update Server IP</button>`;
    } else if (blockedByDependency) {
        // Blocked by dependency - show disabled button with hint
        actionButton = `<button class="btn-small btn-secondary" disabled title="Enable Accessibility first">Waiting...</button>`;
    } else if (hasFlow) {
        // Has a saved flow - show "Run Setup" to re-run it
        actionButton = `<button class="btn-small btn-primary btn-run-setup" data-prereq="${prereq}" data-flow-id="${config.flow_id}">Run Setup</button>`;
    } else {
        // No flow yet - show "Set Up Now" for first-time setup
        actionButton = `<button class="btn-small btn-primary btn-setup-now" data-prereq="${prereq}">Set Up Now</button>`;
    }

    return `
        <div class="prerequisite-item ${statusClass}" data-prereq="${prereq}">
            <span class="prereq-icon">${icon}</span>
            <div class="prereq-info">
                <strong>${name}</strong>
                <span class="prereq-status">
                    ${isEnabled ? statusMessage : instructions}
                </span>
            </div>
            <div class="prereq-item-actions">
                ${actionButton}
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
    // For streaming: first launch the companion app, wait for it to start, then request streaming permission
    'streaming': 'am start -n com.visualmapper.companion/.ui.fragments.MainContainerActivity && sleep 2 && am start -n com.visualmapper.companion/.streaming.MediaProjectionRequestActivity',
    'accessibility': 'am start -a android.settings.ACCESSIBILITY_SETTINGS',
    'overlay_permission': 'am start -a android.settings.action.MANAGE_OVERLAY_PERMISSION'
};

// Map frontend prereq names to backend PREREQUISITE_TYPES names
const PREREQ_TYPE_MAP = {
    'streaming': 'start_streaming',
    'accessibility': 'enable_accessibility',
    'overlay_permission': 'grant_overlay_permission'
};

/**
 * Create a setup button click handler
 * @private
 */
function createSetupHandler(wizard, dialog, missing, resolve) {
    return async function(e) {
        const btn = e.target;
        const prereq = btn.dataset.prereq;
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

            // Update button to show waiting state with clearer messaging
            btn.textContent = '⏳ Waiting for you...';
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-waiting');

            // Update the status text in the item to be more helpful
            const statusEl = btn.closest('.prerequisite-item')?.querySelector('.prereq-status');
            if (statusEl) {
                statusEl.textContent = SETUP_INSTRUCTIONS[prereq];
                statusEl.style.color = '#3b82f6'; // Blue for active instruction
            }

            // Show instruction toast
            const instruction = SETUP_INSTRUCTIONS[prereq];
            showToast(`👆 ${instruction}`, 'info', 5000);

            // Start polling for completion
            startSetupPolling(wizard, dialog, missing, resolve, prereq, btn, command);

        } catch (error) {
            console.error('[PrerequisiteDialog] Setup failed:', error);
            showToast(`Failed to open setup: ${error.message}`, 'error');
            btn.disabled = false;
            btn.textContent = 'Retry';
        }
    };
}

/**
 * Start polling for prerequisite completion
 * @private
 */
function startSetupPolling(wizard, dialog, missing, resolve, prereq, btn, command) {
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

                // Save flow for future re-runs (in background, don't block)
                savePrerequisiteFlowForLater(wizard, prereq, command).catch(err => {
                    console.warn('[PrerequisiteDialog] Failed to save flow for later:', err);
                });

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

                // If accessibility was just enabled, unblock streaming setup
                if (prereq === 'accessibility') {
                    enableStreamingButton(dialog, wizard, missing, resolve);
                }

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
}

/**
 * Enable the streaming button after accessibility is enabled
 * @private
 */
function enableStreamingButton(dialog, wizard, missing, resolve) {
    const streamingItem = dialog.querySelector('.prerequisite-item[data-prereq="streaming"]');
    if (!streamingItem) return;

    const streamingBtn = streamingItem.querySelector('button[disabled]');
    if (!streamingBtn || streamingBtn.textContent !== 'Waiting...') return;

    // Enable the streaming button
    streamingBtn.disabled = false;
    streamingBtn.textContent = 'Set Up Now';
    streamingBtn.classList.remove('btn-secondary');
    streamingBtn.classList.add('btn-primary', 'btn-setup-now');
    streamingBtn.dataset.prereq = 'streaming';

    // Update instruction text
    const statusEl = streamingItem.querySelector('.prereq-status');
    if (statusEl) {
        statusEl.textContent = SETUP_INSTRUCTIONS['streaming'];
    }

    // Wire the click event
    streamingBtn.addEventListener('click', createSetupHandler(wizard, dialog, missing, resolve));
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

    // "Set Up Now" buttons - use the extracted handler
    dialog.querySelectorAll('.btn-setup-now').forEach(btn => {
        btn.addEventListener('click', createSetupHandler(wizard, dialog, missing, resolve));
    });

    // "Run Setup" buttons - use the same extracted handler (always uses latest SETUP_COMMANDS)
    dialog.querySelectorAll('.btn-run-setup').forEach(btn => {
        btn.addEventListener('click', createSetupHandler(wizard, dialog, missing, resolve));
    });

    // "Update Server IP" buttons - show dialog to update companion server URL
    dialog.querySelectorAll('.btn-update-server').forEach(btn => {
        btn.addEventListener('click', async () => {
            const companionIp = btn.dataset.companionIp || '';
            await showServerUrlUpdateDialog(wizard, companionIp);
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
 * Save a prerequisite flow for future re-runs
 * Called automatically after successful setup
 * @private
 */
async function savePrerequisiteFlowForLater(wizard, prereqType, command) {
    const name = PREREQ_NAMES[prereqType] || prereqType;
    const flowId = `prereq_${prereqType}_${Date.now().toString(36)}`;

    // Create the flow with the shell command
    const flowData = {
        flow_id: flowId,
        device_id: wizard.selectedDevice,
        name: `Setup: ${name}`,
        description: `Auto-saved prerequisite flow to enable ${name}`,
        steps: [{
            step_type: 'shell',
            command: command
        }],
        enabled: false // Don't run on schedule, only on-demand
    };

    console.log('[PrerequisiteDialog] Saving flow for later:', flowId);

    // Save the flow
    const saveResponse = await fetch(`${getApiBase()}/flows`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(flowData)
    });

    if (!saveResponse.ok) {
        const err = await saveResponse.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to save flow');
    }

    // Link it to the prerequisite type (use backend's expected type name)
    const backendPrereqType = PREREQ_TYPE_MAP[prereqType] || prereqType;
    await fetch(
        `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/${backendPrereqType}/link-flow`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flow_id: flowId })
        }
    );

    console.log('[PrerequisiteDialog] Flow saved and linked:', flowId);
    return flowId;
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

    // Record the run (use backend's expected type name)
    const backendPrereqType = PREREQ_TYPE_MAP[prereqType] || prereqType;
    await fetch(
        `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/${backendPrereqType}/record-run`,
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
            // Streaming: use the SETUP_COMMANDS which launches companion first then permission dialog
            steps = [{
                step_type: 'shell',
                command: SETUP_COMMANDS['streaming']
            }];
        } else if (prereqType === 'accessibility') {
            // Accessibility: use recorded steps, or default to SETUP_COMMANDS
            steps = wizard.flowSteps?.length > 0 ? wizard.flowSteps : [{
                step_type: 'shell',
                command: SETUP_COMMANDS['accessibility']
            }];
        } else if (prereqType === 'overlay_permission') {
            // Overlay: use recorded steps, or default to SETUP_COMMANDS
            steps = wizard.flowSteps?.length > 0 ? wizard.flowSteps : [{
                step_type: 'shell',
                command: SETUP_COMMANDS['overlay_permission']
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

        // Link as prerequisite (use backend's expected type name)
        const backendPrereqType = PREREQ_TYPE_MAP[prereqType] || prereqType;
        await fetch(
            `${getApiBase()}/prerequisites/${encodeURIComponent(wizard.selectedDevice)}/${backendPrereqType}/link-flow`,
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

/**
 * Show dialog to update companion app server URL
 * Used when companion is on network but not connecting (server IP changed)
 * @param {Object} wizard - FlowWizard instance
 * @param {string} companionIp - IP address of the companion device
 */
async function showServerUrlUpdateDialog(wizard, companionIp) {
    // Get the current server URL (best guess)
    let currentHost = window.location.hostname || 'localhost';
    const currentPort = window.location.port || '3000';

    // If accessing locally, try to get a better IP suggestion
    if (currentHost === 'localhost' || currentHost === '127.0.0.1') {
        // Try to get server's LAN IP from health endpoint or use companion's network
        try {
            const healthResp = await fetch(`${getApiBase()}/health`);
            const healthData = await healthResp.json();
            // Check if server reports its IP (we could add this to health endpoint)
            if (healthData.server_ip) {
                currentHost = healthData.server_ip;
            } else if (companionIp) {
                // Use same network prefix as companion
                const parts = companionIp.split('.');
                if (parts.length >= 3) {
                    // Suggest checking the server's IP on same subnet
                    currentHost = `${parts[0]}.${parts[1]}.${parts[2]}.XXX`;
                }
            }
        } catch (e) {
            console.warn('[PrerequisiteDialog] Could not determine server IP:', e);
        }
    }

    const suggestedUrl = `http://${currentHost}:${currentPort}`;

    const dialog = document.createElement('div');
    dialog.className = 'prerequisite-dialog-overlay';
    dialog.innerHTML = `
        <div class="prerequisite-dialog" style="max-width: 450px;">
            <h3>Update Server URL on Companion</h3>
            <p style="color: var(--text-secondary); margin-bottom: 15px;">
                The companion app at <strong>${companionIp || 'device'}</strong> is on the network but not connected.
                The server IP may have changed.
            </p>
            <div style="margin-bottom: 15px;">
                <label style="display: block; margin-bottom: 5px;">New Server URL:</label>
                <input type="text" id="serverUrlInput" value="${suggestedUrl}"
                    style="width: 100%; padding: 10px; border: 1px solid var(--border-color); border-radius: 6px; font-size: 14px;">
            </div>
            <p style="font-size: 12px; color: var(--text-secondary); margin-bottom: 15px;">
                This will send the new URL to the companion app via MQTT.
                The app will update automatically.
            </p>
            <div class="prerequisite-actions">
                <button class="btn-secondary" id="cancelServerUpdate">Cancel</button>
                <button class="btn-primary" id="sendServerUpdate">Send Update</button>
            </div>
        </div>
    `;

    document.body.appendChild(dialog);

    // Cancel button
    dialog.querySelector('#cancelServerUpdate').addEventListener('click', () => {
        dialog.remove();
    });

    // Send update button
    dialog.querySelector('#sendServerUpdate').addEventListener('click', async () => {
        const serverUrl = dialog.querySelector('#serverUrlInput').value.trim();
        if (!serverUrl) {
            alert('Please enter a server URL');
            return;
        }

        const sendBtn = dialog.querySelector('#sendServerUpdate');
        sendBtn.disabled = true;
        sendBtn.textContent = 'Sending...';

        try {
            const response = await fetch(
                `${getApiBase()}/companion/${encodeURIComponent(wizard.selectedDevice)}/update-server-url`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ server_url: serverUrl })
                }
            );

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to send update');
            }

            showToast('Server URL update sent to companion', 'success');
            dialog.remove();

            // Wait a moment for companion to reconnect, then refresh status
            setTimeout(() => {
                // Trigger a status refresh if the wizard has a method for it
                if (wizard.checkPrerequisites) {
                    wizard.checkPrerequisites();
                }
            }, 3000);

        } catch (error) {
            console.error('[PrerequisiteDialog] Failed to send server URL update:', error);
            showToast(`Failed: ${error.message}`, 'error');
            sendBtn.disabled = false;
            sendBtn.textContent = 'Send Update';
        }
    });

    // Click outside to close
    dialog.addEventListener('click', (e) => {
        if (e.target === dialog) {
            dialog.remove();
        }
    });
}

export default showPrerequisiteDialog;
