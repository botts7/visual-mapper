/**
 * Flow Wizard Step 4 - Review & Test
 * Visual Mapper v0.0.17
 *
 * Handles flow review, testing, and step management
 * v0.0.12: Added step_results with sensor values display
 * v0.0.13: Added navigation issue detection - warns when sensors are on different screens without navigation steps
 * v0.0.14: Extended navigation detection to also check tap/swipe/text actions on wrong screens
 * v0.0.15: Use connection ID for device_id and include stable_device_id in test flows
 * v0.0.16: Prevent duplicate test flow submissions
 * v0.0.17: Pass start-from-current-screen setting to test flow payload
 */

import { showToast } from './toast.js?v=0.2.79';
import FlowStepManager from './flow-step-manager.js?v=0.2.79';
import { groupStepsByScreen, validateMove, moveStep } from './step-reorganizer.js?v=0.2.79';

function getApiBase() {
    return window.API_BASE || '/api';
}

let testingFlow = false;

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Build step-by-step results HTML with sensor values
 */
function buildStepResultsHtml(flowSteps, stepResults, result) {
    if (!flowSteps || flowSteps.length === 0) return '';

    const executedSteps = result.executed_steps ?? 0;

    const stepsMarkup = flowSteps.map((step, index) => {
        let statusIcon = '';
        let bgColor = '';
        let stepDetails = '';

        // Find the step result for this index
        const stepResult = stepResults.find(sr => sr.step_index === index);

        if (index < executedSteps) {
            statusIcon = '✓';
            bgColor = '#f0fdf4';
        } else if (result.failed_step !== null && result.failed_step !== undefined && index === result.failed_step) {
            statusIcon = '✗';
            bgColor = '#fef2f2';
        } else {
            statusIcon = '○';
            bgColor = '#f8fafc';
        }

        // Add sensor values for capture_sensors steps
        if (stepResult && stepResult.details && stepResult.details.sensors) {
            const sensors = stepResult.details.sensors;
            const sensorCount = Object.keys(sensors).length;
            if (sensorCount > 0) {
                const sensorItems = Object.entries(sensors).map(([id, info]) => {
                    const name = escapeHtml(info.name || id);
                    const value = escapeHtml(String(info.value ?? '--'));
                    return '<li><strong>' + name + ':</strong> <span style="color: #0369a1;">' + value + '</span></li>';
                }).join('');
                stepDetails = '<div style="margin-top: 8px; padding: 8px; background: #e0f2fe; border-radius: 4px; font-size: 0.9em;">' +
                    '<strong>Captured ' + sensorCount + ' sensor' + (sensorCount !== 1 ? 's' : '') + ':</strong>' +
                    '<ul style="margin: 4px 0 0 0; padding-left: 20px;">' + sensorItems + '</ul></div>';
            }
        }

        // Add action results for execute_action steps
        if (stepResult && stepResult.details && stepResult.details.action_name) {
            const actionName = escapeHtml(stepResult.details.action_name);
            const actionResult = stepResult.details.result ? '<br><strong>Result:</strong> ' + escapeHtml(stepResult.details.result) : '';
            stepDetails = '<div style="margin-top: 8px; padding: 8px; background: #fef3c7; border-radius: 4px; font-size: 0.9em;">' +
                '<strong>Action:</strong> ' + actionName + actionResult + '</div>';
        }

        const stepDesc = escapeHtml(step.description || step.step_type + ' step');
        const stepType = escapeHtml(step.step_type);

        return '<li style="padding: 10px 12px; margin-bottom: 6px; background: ' + bgColor + '; border-radius: 6px; display: flex; flex-direction: column;">' +
            '<div style="display: flex; align-items: center; gap: 10px;">' +
            '<span style="font-weight: bold; width: 24px;">' + statusIcon + '</span>' +
            '<span style="flex: 1;"><strong>' + stepDesc + '</strong>' +
            '<span style="color: #64748b; font-size: 0.85em;"> (' + stepType + ')</span></span>' +
            '</div>' + stepDetails + '</li>';
    }).join('');

    return '<div class="execution-steps" style="margin-top: 16px;">' +
        '<h5 style="margin-bottom: 8px;">Execution Steps:</h5>' +
        '<ol class="step-list" style="list-style: none; padding: 0; margin: 0;">' + stepsMarkup + '</ol></div>';
}

/**
 * Load Step 4: Review & Test
 * v0.0.15: Added step reorganization with screen grouping and move up/down buttons
 */
export async function loadStep(wizard) {
    console.log('[Step4] Loading Review & Test');
    const reviewContainer = document.getElementById('flowStepsReview');
    const startModeToggle = document.getElementById('startFromCurrentScreenToggle');

    if (startModeToggle) {
        startModeToggle.checked = !!wizard.startFromCurrentScreen;
        startModeToggle.onchange = () => {
            wizard.startFromCurrentScreen = startModeToggle.checked;
            localStorage.setItem('flowWizard.startFromCurrentScreen', String(wizard.startFromCurrentScreen));
        };
    }

    if (wizard.flowSteps.length === 0) {
        reviewContainer.innerHTML = `
            <div class="empty-state">
                <p>No steps recorded</p>
            </div>
        `;
        return;
    }

    // Check for navigation issues
    const navIssues = checkNavigationIssues(wizard.flowSteps);
    const issueStepIndices = new Set(navIssues.map(i => i.stepIndex));

    // Group steps by screen
    const screenGroups = groupStepsByScreen(wizard.flowSteps);

    const appLabel = wizard.selectedApp?.label || wizard.selectedApp?.package || wizard.selectedApp || 'Unknown';

    // Build navigation warning banner if there are issues
    let warningBanner = '';
    if (navIssues.length > 0) {
        const issueList = navIssues.map(issue => `<li>${escapeHtml(issue.message)}</li>`).join('');
        warningBanner = `
            <div class="navigation-warning" style="background: #fef3c7; border: 1px solid #f59e0b; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <h4 style="color: #92400e; margin: 0 0 8px 0;">⚠️ Navigation Issues Detected</h4>
                <p style="color: #92400e; margin: 0 0 8px 0;">Your flow has steps on different screens but no navigation steps to reach them:</p>
                <ul style="color: #92400e; margin: 0 0 12px 0; padding-left: 20px;">${issueList}</ul>
                <div style="display: flex; gap: 12px; flex-wrap: wrap;">
                    <button class="btn btn-warning" id="btnAddMissingSteps" style="background: #f59e0b; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer;">
                        ➕ Add Missing Navigation Steps
                    </button>
                </div>
                <p style="color: #92400e; margin: 12px 0 0 0; font-size: 0.9em;">
                    <strong>Tip:</strong> You can also insert steps individually using the "Insert" button on each step below, or create separate flows for each screen.
                </p>
            </div>
        `;
    }

    // Build grouped steps HTML with collapsible sections
    const groupsHtml = screenGroups.map((group, groupIndex) => {
        const isExpanded = true; // All groups expanded by default
        const toggleIcon = isExpanded ? '▼' : '▶';
        const displayStyle = isExpanded ? 'block' : 'none';

        const stepsHtml = group.steps.map(({ step, originalIndex }) => {
            const hasIssue = issueStepIndices.has(originalIndex);
            const issueStyle = hasIssue ? 'border-left: 3px solid #f59e0b; background: #fffbeb;' : '';
            const issueIcon = hasIssue ? '<span style="color: #f59e0b; margin-left: 8px;" title="Navigation issue">⚠️</span>' : '';

            const isFirst = originalIndex === 0;
            const isLast = originalIndex === wizard.flowSteps.length - 1;

            const insertBtn = hasIssue
                ? `<button class="btn btn-sm btn-warning insert-step-btn" data-insert-index="${originalIndex}" style="background: #f59e0b; color: white; font-size: 0.7em; padding: 4px 8px;">Insert</button>`
                : `<button class="btn btn-sm btn-secondary insert-step-btn" data-insert-index="${originalIndex}" style="font-size: 0.7em; padding: 4px 8px;">Insert</button>`;

            // Add edit sensor button for capture_sensors steps
            const editSensorBtn = step.step_type === 'capture_sensors' && step.sensor_ids?.length
                ? `<button class="btn btn-sm btn-primary edit-sensor-btn" data-step-index="${originalIndex}" data-sensor-ids="${step.sensor_ids.join(',')}" style="font-size: 0.7em; padding: 4px 8px;" title="Edit linked sensor">✏️</button>`
                : '';

            return `
            <div class="step-review-item" data-original-index="${originalIndex}" style="${issueStyle}">
                <div class="step-review-number">${originalIndex + 1}</div>
                <div class="step-review-content">
                    <div class="step-review-type">${FlowStepManager.formatStepType(step.step_type)}${issueIcon}</div>
                    <div class="step-review-description">${step.description || FlowStepManager.generateStepDescription(step)}</div>
                    ${FlowStepManager.renderStepDetails(step)}
                </div>
                <div class="step-review-actions">
                    <div class="move-buttons">
                        <button class="btn btn-sm btn-move-up" data-index="${originalIndex}"
                                ${isFirst ? 'disabled' : ''} title="Move up">
                            ↑
                        </button>
                        <button class="btn btn-sm btn-move-down" data-index="${originalIndex}"
                                ${isLast ? 'disabled' : ''} title="Move down">
                            ↓
                        </button>
                    </div>
                    ${editSensorBtn}
                    ${insertBtn}
                    <button class="btn btn-sm btn-danger" onclick="window.flowWizard.removeStepAt(${originalIndex})">
                        Del
                    </button>
                </div>
            </div>
            `;
        }).join('');

        return `
        <div class="screen-group" data-group-index="${groupIndex}">
            <div class="screen-group-header" data-activity="${escapeHtml(group.activity)}">
                <span class="group-toggle">${toggleIcon}</span>
                <span class="group-icon">📱</span>
                <span class="group-name">${escapeHtml(group.shortName)}</span>
                <span class="group-count">(${group.steps.length} step${group.steps.length !== 1 ? 's' : ''})</span>
            </div>
            <div class="screen-group-items" style="display: ${displayStyle};">
                ${stepsHtml}
            </div>
        </div>
        `;
    }).join('');

    reviewContainer.innerHTML = `
        <div class="flow-summary">
            <h3>Flow Summary</h3>
            <div class="summary-stats">
                <div class="stat-item">
                    <span class="stat-label">Device:</span>
                    <span class="stat-value">${wizard.selectedDevice}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">App:</span>
                    <span class="stat-value">${appLabel}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Steps:</span>
                    <span class="stat-value">${wizard.flowSteps.length}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Screens:</span>
                    <span class="stat-value">${screenGroups.length}</span>
                </div>
            </div>
        </div>

        ${warningBanner}

        <div class="steps-review-grouped">
            ${groupsHtml}
        </div>

        <div id="testResults" class="test-results" style="display: none;">
            <h3>Test Results</h3>
            <div id="testResultsContent"></div>
        </div>
    `;

    // Wire up all event handlers
    wireUpStep4Handlers(wizard, reviewContainer, navIssues);
}

/**
 * Wire up all event handlers for Step 4
 */
function wireUpStep4Handlers(wizard, container, navIssues) {
    // Group toggle (expand/collapse)
    container.querySelectorAll('.screen-group-header').forEach(header => {
        header.addEventListener('click', () => {
            const items = header.nextElementSibling;
            const toggle = header.querySelector('.group-toggle');
            const isExpanded = items.style.display !== 'none';

            items.style.display = isExpanded ? 'none' : 'block';
            toggle.textContent = isExpanded ? '▶' : '▼';
        });
    });

    // Move up buttons
    container.querySelectorAll('.btn-move-up').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            attemptMoveStep(wizard, index, index - 1);
        });
    });

    // Move down buttons
    container.querySelectorAll('.btn-move-down').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            attemptMoveStep(wizard, index, index + 1);
        });
    });

    // Test button
    const btnTestFlow = document.getElementById('btnTestFlow');
    if (btnTestFlow) {
        btnTestFlow.onclick = () => testFlow(wizard);
    }

    // Wire up "Add Missing Navigation Steps" button
    const btnAddMissingSteps = document.getElementById('btnAddMissingSteps');
    if (btnAddMissingSteps) {
        btnAddMissingSteps.onclick = () => {
            console.log('[Step4] User clicked Add Missing Navigation Steps - going back to Step 3');
            showToast('Returning to Step 3 to add navigation steps...', 'info');
            if (navIssues.length > 0) {
                wizard.insertAtIndex = navIssues[0].stepIndex;
            }
            if (typeof wizard.goToStep === 'function') {
                wizard.goToStep(3);
            } else if (window.flowWizard?.goToStep) {
                window.flowWizard.goToStep(3);
            }
        };
    }

    // Wire up individual "Insert" buttons
    container.querySelectorAll('.insert-step-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const insertIndex = parseInt(e.target.dataset.insertIndex, 10);
            console.log(`[Step4] User clicked Insert at index ${insertIndex} - going back to Step 3`);
            showToast(`Returning to Step 3 to insert step before step ${insertIndex + 1}...`, 'info');
            wizard.insertAtIndex = insertIndex;
            if (typeof wizard.goToStep === 'function') {
                wizard.goToStep(3);
            } else if (window.flowWizard?.goToStep) {
                window.flowWizard.goToStep(3);
            }
        });
    });

    // Wire up "Edit Sensor" buttons for capture_sensors steps
    container.querySelectorAll('.edit-sensor-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const stepIndex = parseInt(e.target.dataset.stepIndex, 10);
            const sensorIds = e.target.dataset.sensorIds?.split(',') || [];

            if (sensorIds.length === 0) {
                showToast('No sensors linked to this step', 'warning');
                return;
            }

            console.log(`[Step4] Edit sensor clicked for step ${stepIndex}, sensors: ${sensorIds}`);

            // For now, open the first sensor in the sensor manager
            const sensorId = sensorIds[0];
            try {
                // Fetch the sensor data
                const response = await fetch(`${window.API_BASE || '/api'}/sensors/${wizard.selectedDevice}/${sensorId}`);
                if (!response.ok) {
                    throw new Error('Sensor not found');
                }
                const sensor = await response.json();

                // Open sensor editor if available
                if (wizard.sensorCreator) {
                    wizard.sensorCreator.show(wizard.selectedDevice, sensor.element || {}, 0, {
                        name: sensor.name,
                        entity_id: sensor.entity_id,
                        device_class: sensor.device_class || 'none',
                        unit: sensor.unit_of_measurement || '',
                        icon: sensor.icon || 'mdi:eye',
                        existingSensorId: sensorId,
                        stableDeviceId: wizard.selectedDeviceStableId || wizard.selectedDevice,
                        screenActivity: sensor.screen_activity,
                        targetApp: wizard.selectedApp?.package
                    });
                } else {
                    // Fallback: navigate to sensors page
                    showToast('Opening sensor in new tab...', 'info');
                    window.open(`/sensors.html?edit=${sensorId}`, '_blank');
                }
            } catch (error) {
                console.error('[Step4] Error editing sensor:', error);
                showToast(`Could not load sensor: ${error.message}`, 'error');
            }
        });
    });
}

/**
 * Attempt to move a step with validation
 */
function attemptMoveStep(wizard, fromIndex, toIndex) {
    const validation = validateMove(wizard.flowSteps, fromIndex, toIndex);

    if (!validation.valid) {
        showMoveBlockedError(validation.error);
        return;
    }

    // Perform the move
    moveStep(wizard.flowSteps, fromIndex, toIndex);
    showToast(`Moved step ${fromIndex + 1} to position ${toIndex + 1}`, 'success');

    // Re-render the step list
    loadStep(wizard);
}

/**
 * Show error dialog when move is blocked
 */
function showMoveBlockedError(message) {
    // Create modal overlay
    const overlay = document.createElement('div');
    overlay.className = 'move-error-overlay';
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;
    overlay.innerHTML = `
        <div class="move-error-modal" style="
            background: white;
            padding: 30px;
            border-radius: 12px;
            text-align: center;
            max-width: 400px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
        ">
            <div style="font-size: 48px; margin-bottom: 16px;">⛔</div>
            <h4 style="margin: 0 0 12px 0; color: #dc2626;">Cannot Move Step</h4>
            <p style="margin: 0 0 20px 0; color: #64748b; line-height: 1.5;">${escapeHtml(message)}</p>
            <button class="btn btn-primary" id="btnDismissMoveError" style="
                background: #2196f3;
                color: white;
                border: none;
                padding: 10px 24px;
                border-radius: 6px;
                cursor: pointer;
            ">OK</button>
        </div>
    `;
    document.body.appendChild(overlay);

    // Wire up dismiss
    document.getElementById('btnDismissMoveError').addEventListener('click', () => {
        overlay.remove();
    });

    // Close on overlay click
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.remove();
        }
    });
}

/**
 * Remove a step from the flow at the specified index
 */
export function removeStepAt(wizard, index) {
    if (index >= 0 && index < wizard.flowSteps.length) {
        const removed = wizard.flowSteps.splice(index, 1)[0];
        console.log(`[Step4] Removed step ${index}:`, removed);
        showToast(`Step ${index + 1} removed`, 'info');
        loadStep(wizard); // Refresh the review display
    }
}

/**
 * Test the flow execution
 */
export async function testFlow(wizard) {
    if (testingFlow) {
        showToast('Flow test already running...', 'info');
        return;
    }
    testingFlow = true;

    console.log('[Step4] Testing flow...');
    showToast('Running flow test...', 'info');

    const testResults = document.getElementById('testResults');
    const testResultsContent = document.getElementById('testResultsContent');

    if (!testResults || !testResultsContent) {
        console.warn('[Step4] Test results elements not found');
        return;
    }

    testResults.style.display = 'block';
    testResultsContent.innerHTML = '<div class="loading">Executing flow...</div>';

    try {
        // Build flow payload - use connection ID for execution, stable ID for storage
        const deviceId = wizard.selectedDevice;
        const stableDeviceId = wizard.selectedDeviceStableId || deviceId;
        const flowPayload = {
            flow_id: `test_${Date.now()}`,
            device_id: deviceId,
            stable_device_id: stableDeviceId,
            name: 'Test Flow',
            description: 'Flow test execution',
            steps: wizard.flowSteps,
            update_interval_seconds: 60,
            enabled: false, // Don't enable test flows
            stop_on_error: true,
            start_from_current_screen: !!wizard.startFromCurrentScreen
        };

        console.log('[Step4] Testing flow:', flowPayload);

        // Create test flow
        const response = await fetch(`${getApiBase()}/flows`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(flowPayload)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create test flow');
        }

        const createdFlow = await response.json();
        console.log('[Step4] Test flow created:', createdFlow);

        // Execute the flow
        const executeResponse = await fetch(`${getApiBase()}/flows/${deviceId}/${createdFlow.flow_id}/execute`, {
            method: 'POST'
        });

        if (!executeResponse.ok) {
            const error = await executeResponse.json();
            throw new Error(error.detail || 'Flow execution failed');
        }

        const result = await executeResponse.json();
        console.log('[Step4] Flow execution result:', result);

        // Display results
        const executedSteps = result.executed_steps ?? 0;
        const executionTime = result.execution_time_ms ?? 0;
        const capturedSensors = result.captured_sensors || {};
        const stepResults = result.step_results || [];

        // Build step-by-step breakdown with sensor values
        const stepsHtml = buildStepResultsHtml(wizard.flowSteps, stepResults, result);

        if (result.success) {
            testResultsContent.innerHTML = `
                <div class="test-success">
                    <h4>✅ Flow Test Passed</h4>
                    <p><strong>Executed Steps:</strong> ${executedSteps} / ${wizard.flowSteps.length}</p>
                    <p><strong>Execution Time:</strong> ${executionTime}ms</p>
                    ${stepsHtml}
                    ${Object.keys(capturedSensors).length > 0 ? `
                        <div class="captured-sensors" style="margin-top: 16px; padding: 12px; background: #f0fdf4; border-radius: 8px;">
                            <strong>Summary - All Captured Sensors:</strong>
                            <ul style="margin: 8px 0 0 0; padding-left: 20px;">
                                ${Object.entries(capturedSensors).map(([id, value]) =>
                                    `<li><strong>${escapeHtml(id)}:</strong> <span style="color: #16a34a;">${escapeHtml(String(value))}</span></li>`
                                ).join('')}
                            </ul>
                        </div>
                    ` : ''}
                </div>
            `;
            showToast('Flow test passed!', 'success');
        } else {
            const failedStep = result.failed_step !== null && result.failed_step !== undefined ? result.failed_step + 1 : 'Unknown';

            testResultsContent.innerHTML = `
                <div class="test-failure">
                    <h4>❌ Flow Test Failed</h4>
                    <p><strong>Failed at Step:</strong> ${failedStep}</p>
                    <p><strong>Error:</strong> ${escapeHtml(result.error_message || 'Unknown error')}</p>
                    <p><strong>Executed Steps:</strong> ${executedSteps} / ${wizard.flowSteps.length}</p>
                    ${stepsHtml}
                </div>
            `;
            showToast('Flow test failed', 'error');
        }

        // Clean up test flow
        await fetch(`${getApiBase()}/flows/${deviceId}/${createdFlow.flow_id}`, {
            method: 'DELETE'
        });

    } catch (error) {
        console.error('[Step4] Flow test error:', error);
        testResultsContent.innerHTML = `
            <div class="test-error">
                <h4>⚠️ Test Error</h4>
                <p>${error.message}</p>
            </div>
        `;
        showToast(`Test error: ${error.message}`, 'error');
    } finally {
        testingFlow = false;
    }
}

/**
 * Check if flow has navigation issues (steps on different screens without proper flow)
 * Returns validation result with warnings for:
 * - Sensors on different screens without navigation
 * - Taps/actions recorded on screens that won't be reached
 */
function checkNavigationIssues(steps) {
    const issues = [];
    let currentActivity = null;  // What screen we expect to be on
    let currentActivityIndex = -1;  // Step that set current activity
    let lastStepWasAppLaunch = false;  // Track if previous step was launch_app

    // Step types that have screen_activity and need to be on the right screen
    const screenDependentTypes = ['capture_sensors', 'tap', 'swipe', 'text'];
    // Step types that can change screens (navigation actions)
    const screenChangingTypes = ['tap', 'swipe', 'go_back'];

    // Common splash/loading screen patterns (case insensitive check)
    const splashPatterns = ['splash', 'launch', 'loading', 'startup', 'intro', 'welcome'];
    const isSplashScreen = (activity) => {
        if (!activity) return false;
        const actLower = activity.toLowerCase();
        return splashPatterns.some(pattern => actLower.includes(pattern));
    };

    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];

        // launch_app sets initial screen (might be splash screen)
        if (step.step_type === 'launch_app') {
            currentActivity = step.screen_activity || step.expected_activity || null;
            currentActivityIndex = i;
            lastStepWasAppLaunch = true;
            continue;
        }

        // restart_app resets to app's home screen
        if (step.step_type === 'restart_app') {
            currentActivity = null; // Unknown - will be app's home screen
            currentActivityIndex = i;
            lastStepWasAppLaunch = true;  // Treat like a new app launch (may show splash)
            continue;
        }

        // go_home/go_back - leaves the app context
        if (step.step_type === 'go_home' || step.step_type === 'go_back') {
            currentActivity = null;
            currentActivityIndex = i;
            lastStepWasAppLaunch = false;
            continue;
        }

        // wait steps don't change screens but shouldn't clear the app launch flag
        if (step.step_type === 'wait') {
            continue;
        }

        // Check steps that depend on being on the right screen
        if (step.screen_activity && screenDependentTypes.includes(step.step_type)) {
            const stepActivity = step.screen_activity;

            // If we have a known current activity and it's different
            if (currentActivity && stepActivity !== currentActivity) {
                const currentActName = currentActivity.split('.').pop();
                const stepActName = stepActivity.split('.').pop();

                // Skip warning if this is a natural splash → main screen transition after app launch
                // Apps commonly show a splash screen briefly before the main screen
                const isPostLaunchTransition = lastStepWasAppLaunch && isSplashScreen(currentActivity);

                if (isPostLaunchTransition) {
                    console.log(`[Step4] Skipping warning: splash→main transition after launch (${currentActName} → ${stepActName})`);
                    // Update to the actual screen the user is on
                    currentActivity = stepActivity;
                    currentActivityIndex = i;
                    lastStepWasAppLaunch = false;
                } else {
                    // Check if there was a screen-changing action between currentActivityIndex and this step
                    let hasNavigationBetween = false;
                    for (let j = currentActivityIndex + 1; j < i; j++) {
                        if (screenChangingTypes.includes(steps[j].step_type)) {
                            hasNavigationBetween = true;
                            break;
                        }
                    }

                    if (!hasNavigationBetween) {
                        const stepTypeLabel = step.step_type === 'capture_sensors' ? 'Sensor' :
                                             step.step_type === 'tap' ? 'Tap action' :
                                             step.step_type === 'swipe' ? 'Swipe action' : 'Step';

                        issues.push({
                            stepIndex: i,
                            stepType: step.step_type,
                            currentActivity: stepActName,
                            previousActivity: currentActName,
                            message: `${stepTypeLabel} at step ${i + 1} expects "${stepActName}" but flow is on "${currentActName}". Add navigation steps to reach the correct screen.`
                        });
                    }
                }
            }

            // Update current activity to this step's activity (we're now "expecting" this screen)
            // But only if this step doesn't change screens (sensors don't change screens)
            if (step.step_type === 'capture_sensors') {
                currentActivity = stepActivity;
                currentActivityIndex = i;
            }

            // Clear the app launch flag after processing a screen-dependent step
            lastStepWasAppLaunch = false;
        }

        // Taps and swipes CAN change screens - after them we don't know where we are
        // unless the next step tells us
        if (screenChangingTypes.includes(step.step_type)) {
            // If the tap/swipe has screen_activity, that's where we ARE when executing
            // After execution, we might be somewhere else
            if (step.screen_activity) {
                // We were on this screen when this action was recorded
                // But the action might navigate us elsewhere
                currentActivity = null; // Unknown after navigation action
                currentActivityIndex = i;
            }
        }
    }

    return issues;
}

/**
 * Validate Step 4
 */
export function validateStep(wizard) {
    if (wizard.flowSteps.length === 0) {
        alert('Please record at least one step');
        return false;
    }

    // Check for screen navigation issues
    const navIssues = checkNavigationIssues(wizard.flowSteps);

    if (navIssues.length > 0) {
        const issueMessages = navIssues.map(issue => `• ${issue.message}`).join('\n');
        const warningMsg = `⚠️ Navigation Warning:\n\n${issueMessages}\n\n` +
            `Your flow has sensors on different screens but no navigation steps (tap/swipe) between them.\n\n` +
            `This will cause sensor capture to fail because the app won't automatically navigate to the correct screens.\n\n` +
            `Options:\n` +
            `1. Add tap/swipe steps to navigate between screens\n` +
            `2. Create separate flows for each screen\n\n` +
            `Do you want to continue anyway?`;

        if (!confirm(warningMsg)) {
            return false;
        }
    }

    return true;
}

/**
 * Get Step 4 data
 */
export function getStepData(wizard) {
    return {
        flowSteps: wizard.flowSteps
    };
}

// Export all Step 4 methods
export default {
    loadStep,
    validateStep,
    getStepData,
    removeStepAt,
    testFlow
};
