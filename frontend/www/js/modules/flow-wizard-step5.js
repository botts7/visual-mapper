/**
 * Flow Wizard Step 5 - Settings & Save
 * Visual Mapper v0.0.12
 * v0.0.12: Resume scheduler IMMEDIATELY after save (before dialog), with finally block safety
 * v0.0.11: Added timeout safety net for _savingFlow flag (60s auto-reset)
 * v0.0.10: Release wizard lock and resume scheduler BEFORE redirect to ensure flows run
 * v0.0.9: Include start-from-current-screen setting in saved flows
 * v0.0.8: Prevent duplicate save submissions
 * v0.0.7: Use connection ID for device_id and include stable_device_id in saved flows
 * v0.0.6: Added headless mode options (auto_wake_before, auto_sleep_after, verify_screen_on)
 */

import { showToast } from './toast.js?v=0.2.63';

function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Load Step 5: Settings
 */
export async function loadStep(wizard) {
    console.log('[Step5] Loading Settings');

    // Auto-generate flow name
    const appPackage = wizard.selectedApp?.package || wizard.selectedApp || '';
    const appName = appPackage ? appPackage.split('.').pop() : 'flow';
    const flowNameInput = document.getElementById('flowName');
    if (flowNameInput && !flowNameInput.value) {
        flowNameInput.value = `${appName}_flow`;
    }

    const startFromCurrent = document.getElementById('startFromCurrentScreen');
    if (startFromCurrent) {
        startFromCurrent.checked = !!wizard.startFromCurrentScreen;
        startFromCurrent.addEventListener('change', () => {
            wizard.startFromCurrentScreen = startFromCurrent.checked;
            localStorage.setItem('flowWizard.startFromCurrentScreen', String(wizard.startFromCurrentScreen));
        });
    }

    // Setup quick interval buttons
    document.querySelectorAll('[data-interval]').forEach(btn => {
        btn.addEventListener('click', () => {
            const seconds = parseInt(btn.dataset.interval);
            const minutes = seconds / 60;
            document.getElementById('intervalValue').value = minutes;
            document.getElementById('intervalUnit').value = '60';
        });
    });

    // Wire up save button
    const btnSave = document.getElementById('btnSaveFlow');
    if (btnSave) {
        btnSave.onclick = () => saveFlow(wizard);
    }
}

/**
 * Save the flow
 * Exported so it can be called by wizard.nextStep() on final step
 */
export async function saveFlow(wizard) {
    if (wizard._savingFlow) {
        showToast('Save already in progress...', 'info');
        return;
    }
    wizard._savingFlow = true;

    // Safety net: auto-reset flag after 60 seconds in case of hung save
    const saveTimeout = setTimeout(() => {
        if (wizard._savingFlow) {
            console.warn('[Step5] Save flow timeout after 60s - resetting flag');
            wizard._savingFlow = false;
            const btnSave = document.getElementById('btnSaveFlow');
            if (btnSave) {
                btnSave.disabled = false;
                btnSave.textContent = 'Save Flow';
            }
            showToast('Save operation timed out. Please try again.', 'error');
        }
    }, 60000);

    console.log('[Step5] Saving flow...');
    showToast('Saving flow...', 'info');

    const btnSave = document.getElementById('btnSaveFlow');
    if (btnSave) {
        btnSave.disabled = true;
        btnSave.textContent = 'Saving...';
    }

    try {
        const flowName = document.getElementById('flowName')?.value.trim();
        const flowDescription = document.getElementById('flowDescription')?.value.trim();
        const intervalValue = parseInt(document.getElementById('intervalValue')?.value || '60');
        const intervalUnit = parseInt(document.getElementById('intervalUnit')?.value || '60');
        const startFromCurrent = document.getElementById('startFromCurrentScreen')?.checked ?? false;

        if (!flowName) {
            showToast('Please enter a flow name', 'error');
            wizard._savingFlow = false;
            if (btnSave) {
                btnSave.disabled = false;
                btnSave.textContent = 'Save Flow';
            }
            return;
        }

        const updateIntervalSeconds = intervalValue * intervalUnit;

        // Use connection ID for execution, stable ID for storage
        const deviceId = wizard.selectedDevice;
        const stableDeviceId = wizard.selectedDeviceStableId || deviceId;

        // Check if we're editing an existing flow
        const isEditing = wizard.isFlowEditMode && wizard.isFlowEditMode();
        const flowId = isEditing ? wizard.editingFlowId : `flow_${stableDeviceId.replace(/[^a-zA-Z0-9]/g, '_')}_${Date.now()}`;

        // Headless mode options
        const autoWakeBefore = document.getElementById('autoWakeBefore')?.checked ?? true;
        const autoSleepAfter = document.getElementById('autoSleepAfter')?.checked ?? true;
        const verifyScreenOn = document.getElementById('verifyScreenOn')?.checked ?? true;

        const flowPayload = {
            flow_id: flowId,
            device_id: deviceId,
            stable_device_id: stableDeviceId,
            name: flowName,
            description: flowDescription || '',
            steps: wizard.flowSteps,
            update_interval_seconds: updateIntervalSeconds,
            enabled: true,
            stop_on_error: false,
            max_flow_retries: 3,
            flow_timeout: 60,
            start_from_current_screen: startFromCurrent,
            // Headless mode settings
            auto_wake_before: autoWakeBefore,
            auto_sleep_after: autoSleepAfter,
            verify_screen_on: verifyScreenOn,
            wake_timeout_ms: 3000
        };

        console.log(`[Step5] ${isEditing ? 'Updating' : 'Creating'} flow:`, flowPayload);

        // Use PUT for update, POST for create
        let response;
        if (isEditing) {
            response = await fetch(`${getApiBase()}/flows/${encodeURIComponent(deviceId)}/${encodeURIComponent(flowId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(flowPayload)
            });
        } else {
            response = await fetch(`${getApiBase()}/flows`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(flowPayload)
            });
        }

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Failed to ${isEditing ? 'update' : 'save'} flow`);
        }

        const savedFlow = await response.json();
        console.log(`[Step5] Flow ${isEditing ? 'updated' : 'saved'}:`, savedFlow);

        showToast(`Flow ${isEditing ? 'updated' : 'saved'} successfully!`, 'success', 3000);

        // CRITICAL: Release wizard lock and resume scheduler IMMEDIATELY after save
        // This ensures the flow can start running even if the dialog has issues
        await releaseWizardAndResumeScheduler(wizard);

        // Show dialog for user to choose next action (non-blocking for scheduler)
        const result = await showFlowSavedDialog(savedFlow);

        if (result === 'view') {
            // Add cache-busting parameter to force fresh page load
            window.location.href = `flows.html?refresh=${Date.now()}`;
        } else if (result === 'create') {
            wizard.reset();
        }

    } catch (error) {
        console.error('[Step5] Save failed:', error);
        showToast(`Failed to save flow: ${error.message}`, 'error', 5000);
    } finally {
        clearTimeout(saveTimeout);
        wizard._savingFlow = false;
        if (btnSave) {
            btnSave.disabled = false;
            btnSave.textContent = 'Save Flow';
        }
        // Safety: Always try to release wizard and resume scheduler in finally block
        await releaseWizardAndResumeScheduler(wizard);
    }
}

/**
 * Release wizard lock and resume scheduler
 * Safe to call multiple times - operations are idempotent
 */
async function releaseWizardAndResumeScheduler(wizard) {
    // Release wizard lock
    if (wizard._wizardActiveDevice) {
        try {
            console.log('[Step5] Releasing wizard lock...');
            await fetch(`${getApiBase()}/wizard/release/${encodeURIComponent(wizard._wizardActiveDevice)}`, { method: 'POST' });
            wizard._wizardActiveDevice = null;
            console.log('[Step5] Wizard lock released');
        } catch (e) {
            console.warn('[Step5] Could not release wizard lock:', e);
        }
    }

    // Resume scheduler (safe to call even if not paused)
    try {
        await fetch(`${getApiBase()}/scheduler/resume`, { method: 'POST' });
        console.log('[Step5] Scheduler resumed');
    } catch (e) {
        console.warn('[Step5] Could not resume scheduler:', e);
    }
}

/**
 * Show flow saved dialog
 */
async function showFlowSavedDialog(flow) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.style.cssText = `
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
        `;

        overlay.innerHTML = `
            <div style="background: white; border-radius: 8px; padding: 30px; max-width: 500px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                <h2 style="margin: 0 0 15px 0; color: #22c55e;">Flow Saved!</h2>
                <p style="margin: 0 0 20px 0; color: #64748b;">
                    <strong>${flow.name}</strong> has been saved and enabled.
                </p>
                <div style="margin: 0 0 20px 0; padding: 15px; background: #f1f5f9; border-radius: 4px;">
                    <div style="margin-bottom: 8px;"><strong>Device:</strong> ${flow.device_id}</div>
                    <div style="margin-bottom: 8px;"><strong>Steps:</strong> ${flow.steps.length}</div>
                    <div style="margin-bottom: 8px;"><strong>Update Interval:</strong> ${formatInterval(flow.update_interval_seconds)}</div>
                    <div><strong>Headless Mode:</strong> ${flow.auto_wake_before !== false ? 'Enabled' : 'Disabled'}</div>
                </div>
                <div style="display: flex; gap: 10px; justify-content: flex-end;">
                    <button id="btnCreateAnother" class="btn btn-secondary">Create Another</button>
                    <button id="btnViewFlows" class="btn btn-primary">View All Flows</button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        document.getElementById('btnCreateAnother').onclick = () => {
            document.body.removeChild(overlay);
            resolve('create');
        };

        document.getElementById('btnViewFlows').onclick = () => {
            document.body.removeChild(overlay);
            resolve('view');
        };

        overlay.onclick = (e) => {
            if (e.target === overlay) {
                document.body.removeChild(overlay);
                resolve('view');
            }
        };
    });
}

/**
 * Format interval for display
 */
function formatInterval(seconds) {
    if (seconds < 60) {
        return `${seconds} seconds`;
    } else if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        return `${minutes} minute${minutes > 1 ? 's' : ''}`;
    } else {
        const hours = Math.floor(seconds / 3600);
        return `${hours} hour${hours > 1 ? 's' : ''}`;
    }
}

/**
 * Validate Step 5
 */
export function validateStep(wizard) {
    const flowName = document.getElementById('flowName')?.value.trim();
    if (!flowName) {
        alert('Please enter a flow name');
        return false;
    }
    return true;
}

/**
 * Get Step 5 data
 */
export function getStepData(wizard) {
    return {
        flowName: document.getElementById('flowName')?.value.trim(),
        flowDescription: document.getElementById('flowDescription')?.value.trim(),
        intervalValue: parseInt(document.getElementById('intervalValue')?.value || '60'),
        intervalUnit: parseInt(document.getElementById('intervalUnit')?.value || '60')
    };
}

export default { loadStep, validateStep, getStepData, saveFlow };
