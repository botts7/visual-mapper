/**
 * Flow Wizard Step 5 - Settings & Save
 * Visual Mapper v0.0.13
 * v0.0.13: Handle prerequisite mode - save flows as prerequisite flows with proper linking
 * v0.0.12: Resume scheduler IMMEDIATELY after save (before dialog), with finally block safety
 * v0.0.11: Added timeout safety net for _savingFlow flag (60s auto-reset)
 * v0.0.10: Release wizard lock and resume scheduler BEFORE redirect to ensure flows run
 * v0.0.9: Include start-from-current-screen setting in saved flows
 * v0.0.8: Prevent duplicate save submissions
 * v0.0.7: Use connection ID for device_id and include stable_device_id in saved flows
 * v0.0.6: Added headless mode options (auto_wake_before, auto_sleep_after, verify_screen_on)
 */

import { showToast } from './toast.js?v=0.4.0-beta.4';
import { PREREQ_NAMES } from './prerequisite-checker.js?v=0.4.0-beta.4';
import { hidePrerequisiteGuidance } from './prerequisite-dialog.js?v=0.4.0-beta.4';

function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Load Step 5: Settings
 */
export async function loadStep(wizard) {
    console.log('[Step5] Loading Settings');

    // Check if we're in prerequisite mode
    const isPrerequisiteMode = wizard.recordMode === 'prerequisite' && wizard.prereqType;

    // Auto-generate flow name
    const flowNameInput = document.getElementById('flowName');
    if (flowNameInput && !flowNameInput.value) {
        if (isPrerequisiteMode) {
            // For prerequisite flows, use a descriptive name
            const prereqName = PREREQ_NAMES[wizard.prereqType] || wizard.prereqType;
            flowNameInput.value = `Setup: ${prereqName}`;
        } else {
            // For normal flows, use app name
            const appPackage = wizard.selectedApp?.package || wizard.selectedApp || '';
            const appName = appPackage ? appPackage.split('.').pop() : 'flow';
            flowNameInput.value = `${appName}_flow`;
        }
    }

    // If prerequisite mode, show a banner explaining what's being saved
    if (isPrerequisiteMode) {
        const prereqName = PREREQ_NAMES[wizard.prereqType] || wizard.prereqType;
        showPrerequisiteBanner(prereqName);
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
        // Update button text for prerequisite mode
        if (isPrerequisiteMode) {
            btnSave.textContent = 'Save Setup Flow';
        }
    }
}

/**
 * Show a banner explaining that this is a prerequisite setup flow
 */
function showPrerequisiteBanner(prereqName) {
    // Remove existing banner if any
    const existing = document.getElementById('prereqBanner');
    if (existing) existing.remove();

    const banner = document.createElement('div');
    banner.id = 'prereqBanner';
    banner.style.cssText = `
        background: linear-gradient(135deg, #3b82f6, #6366f1);
        color: white;
        padding: 15px 20px;
        border-radius: 8px;
        margin-bottom: 20px;
        box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
    `;
    banner.innerHTML = `
        <strong>Creating Setup Flow: ${prereqName}</strong>
        <p style="margin: 8px 0 0 0; font-size: 0.9em; opacity: 0.9;">
            This flow will automatically run when ${prereqName.toLowerCase()} is needed but not active.
            The flow will NOT be scheduled - it only runs on demand.
        </p>
    `;

    // Insert at top of the settings form
    const settingsForm = document.querySelector('.step-content') || document.querySelector('.flow-settings');
    if (settingsForm) {
        settingsForm.insertBefore(banner, settingsForm.firstChild);
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

        // Check if we're in prerequisite recording mode
        const isPrerequisiteMode = wizard.recordMode === 'prerequisite' && wizard.prereqType;

        const flowPayload = {
            flow_id: flowId,
            device_id: deviceId,
            stable_device_id: stableDeviceId,
            name: flowName,
            description: flowDescription || '',
            steps: wizard.flowSteps,
            update_interval_seconds: updateIntervalSeconds,
            // Prerequisite flows should NOT run on schedule
            enabled: isPrerequisiteMode ? false : true,
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

        // Add prerequisite metadata if in prerequisite mode
        if (isPrerequisiteMode) {
            flowPayload.is_prerequisite = true;
            flowPayload.prereq_type = wizard.prereqType;
            console.log(`[Step5] Saving as prerequisite flow for: ${wizard.prereqType}`);
        }

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
        const savedFlowId = savedFlow.flow_id || savedFlow.id || flowId;
        console.log(`[Step5] Flow ${isEditing ? 'updated' : 'saved'}:`, savedFlow);

        // If this is a prerequisite flow, link it to the prerequisite type
        if (isPrerequisiteMode) {
            console.log(`[Step5] Linking flow ${savedFlowId} to prerequisite: ${wizard.prereqType}`);
            try {
                const linkResponse = await fetch(
                    `${getApiBase()}/prerequisites/${encodeURIComponent(deviceId)}/${wizard.prereqType}/link-flow`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ flow_id: savedFlowId })
                    }
                );
                if (linkResponse.ok) {
                    console.log(`[Step5] Successfully linked flow to ${wizard.prereqType}`);
                } else {
                    console.warn(`[Step5] Failed to link flow: ${linkResponse.status}`);
                }
            } catch (linkError) {
                console.warn('[Step5] Failed to link prerequisite flow:', linkError);
            }

            // Hide the guidance panel
            hidePrerequisiteGuidance();

            // Reset prerequisite state
            const prereqName = PREREQ_NAMES[wizard.prereqType] || wizard.prereqType;
            wizard.recordMode = 'normal';
            wizard.prereqType = null;

            showToast(`${prereqName} setup flow saved!`, 'success', 3000);

            // CRITICAL: Release wizard lock and resume scheduler
            await releaseWizardAndResumeScheduler(wizard);

            // Show simple dialog for prerequisite flows
            const result = await showPrerequisiteSavedDialog(savedFlow, prereqName);

            if (result === 'view') {
                window.location.href = `flows.html?refresh=${Date.now()}`;
            } else if (result === 'continue') {
                // Go back to step 3 to continue with normal flow recording
                wizard.goToStep(3);
            } else if (result === 'test') {
                // Test run the prerequisite flow
                await testPrerequisiteFlow(wizard, savedFlowId, prereqName);
            }
            return;
        }

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

/**
 * Show prerequisite flow saved dialog
 */
async function showPrerequisiteSavedDialog(flow, prereqName) {
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
                <h2 style="margin: 0 0 15px 0; color: #22c55e;">Setup Flow Saved!</h2>
                <p style="margin: 0 0 20px 0; color: #64748b;">
                    <strong>${prereqName}</strong> setup flow has been saved.
                    It will run automatically when this service is needed but not running.
                </p>
                <div style="margin: 0 0 20px 0; padding: 15px; background: #f1f5f9; border-radius: 4px;">
                    <div style="margin-bottom: 8px;"><strong>Name:</strong> ${flow.name}</div>
                    <div style="margin-bottom: 8px;"><strong>Steps:</strong> ${flow.steps?.length || 0}</div>
                    <div><strong>Auto-run:</strong> When ${prereqName.toLowerCase()} is required</div>
                </div>
                <div style="display: flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap;">
                    <button id="btnTestPrereq" class="btn btn-secondary">Test Flow</button>
                    <button id="btnViewPrereqFlows" class="btn btn-secondary">View All Flows</button>
                    <button id="btnContinueWizard" class="btn btn-primary">Continue Recording</button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        document.getElementById('btnTestPrereq').onclick = () => {
            document.body.removeChild(overlay);
            resolve('test');
        };

        document.getElementById('btnViewPrereqFlows').onclick = () => {
            document.body.removeChild(overlay);
            resolve('view');
        };

        document.getElementById('btnContinueWizard').onclick = () => {
            document.body.removeChild(overlay);
            resolve('continue');
        };

        overlay.onclick = (e) => {
            if (e.target === overlay) {
                document.body.removeChild(overlay);
                resolve('continue');
            }
        };
    });
}

/**
 * Test run a prerequisite flow
 */
async function testPrerequisiteFlow(wizard, flowId, prereqName) {
    showToast(`Running ${prereqName} setup flow...`, 'info');

    try {
        const response = await fetch(
            `${getApiBase()}/flows/${encodeURIComponent(wizard.selectedDevice)}/${encodeURIComponent(flowId)}/execute`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sync: true, timeout: 60 })
            }
        );

        const result = await response.json();

        if (result.success) {
            showToast(`${prereqName} setup completed successfully!`, 'success', 3000);
        } else {
            showToast(`${prereqName} setup failed: ${result.error || 'Unknown error'}`, 'error', 5000);
        }

        // Go back to step 3 to continue
        wizard.goToStep(3);

    } catch (error) {
        console.error('[Step5] Test flow failed:', error);
        showToast(`Test failed: ${error.message}`, 'error', 5000);
        wizard.goToStep(3);
    }
}

export default { loadStep, validateStep, getStepData, saveFlow };
