/**
 * Flow Wizard Step 4 - Review & Test
 * Visual Mapper v0.0.14
 *
 * Handles flow review, testing, and step management
 * v0.0.12: Added step_results with sensor values display
 * v0.0.13: Added navigation issue detection - warns when sensors are on different screens without navigation steps
 * v0.0.14: Extended navigation detection to also check tap/swipe/text actions on wrong screens
 */

import { showToast } from './toast.js?v=0.0.5';
import FlowStepManager from './flow-step-manager.js?v=0.0.5';

function getApiBase() {
    return window.API_BASE || '/api';
}

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
 */
export async function loadStep(wizard) {
    console.log('[Step4] Loading Review & Test');
    const reviewContainer = document.getElementById('flowStepsReview');

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

    const appLabel = wizard.selectedApp?.label || wizard.selectedApp?.package || wizard.selectedApp || 'Unknown';

    // Build navigation warning banner if there are issues
    let warningBanner = '';
    if (navIssues.length > 0) {
        const issueList = navIssues.map(issue => `<li>${escapeHtml(issue.message)}</li>`).join('');
        warningBanner = `
            <div class="navigation-warning" style="background: #fef3c7; border: 1px solid #f59e0b; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <h4 style="color: #92400e; margin: 0 0 8px 0;">⚠️ Navigation Issues Detected</h4>
                <p style="color: #92400e; margin: 0 0 8px 0;">Your flow has sensors on different screens but no navigation steps to reach them:</p>
                <ul style="color: #92400e; margin: 0 0 8px 0; padding-left: 20px;">${issueList}</ul>
                <p style="color: #92400e; margin: 0; font-size: 0.9em;">
                    <strong>Tip:</strong> Add tap/swipe steps to navigate between screens, or create separate flows for each screen.
                </p>
            </div>
        `;
    }

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
                    <span class="stat-label">Total Steps:</span>
                    <span class="stat-value">${wizard.flowSteps.length}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Mode:</span>
                    <span class="stat-value">${wizard.recordMode === 'execute' ? 'Execute' : 'Record Only'}</span>
                </div>
            </div>
        </div>

        ${warningBanner}

        <div class="steps-review-list">
            ${wizard.flowSteps.map((step, index) => {
                const hasIssue = issueStepIndices.has(index);
                const issueStyle = hasIssue ? 'border: 2px solid #f59e0b; background: #fffbeb;' : '';
                const issueIcon = hasIssue ? '<span style="color: #f59e0b; margin-left: 8px;" title="Navigation issue: missing steps to reach this screen">⚠️</span>' : '';
                const screenInfo = step.screen_activity ? `<div class="step-screen-info" style="font-size: 0.8em; color: #64748b; margin-top: 4px;">Screen: ${step.screen_activity.split('.').pop()}</div>` : '';

                return `
                <div class="step-review-item" style="${issueStyle}">
                    <div class="step-review-number">${index + 1}</div>
                    <div class="step-review-content">
                        <div class="step-review-type">${FlowStepManager.formatStepType(step.step_type)}${issueIcon}</div>
                        <div class="step-review-description">${step.description || FlowStepManager.generateStepDescription(step)}</div>
                        ${FlowStepManager.renderStepDetails(step)}
                        ${screenInfo}
                    </div>
                    <div class="step-review-actions">
                        <button class="btn btn-sm btn-danger" onclick="window.flowWizard.removeStepAt(${index})">
                            Delete
                        </button>
                    </div>
                </div>
            `}).join('')}
        </div>

        <div id="testResults" class="test-results" style="display: none;">
            <h3>Test Results</h3>
            <div id="testResultsContent"></div>
        </div>
    `;

    // Wire up test button
    const btnTestFlow = document.getElementById('btnTestFlow');
    if (btnTestFlow) {
        btnTestFlow.onclick = () => testFlow(wizard);
    }
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
        // Build flow payload - use stable device ID for storage
        const stableDeviceId = wizard.selectedDeviceStableId || wizard.selectedDevice;
        const flowPayload = {
            flow_id: `test_${Date.now()}`,
            device_id: stableDeviceId,
            name: 'Test Flow',
            description: 'Flow test execution',
            steps: wizard.flowSteps,
            update_interval_seconds: 60,
            enabled: false, // Don't enable test flows
            stop_on_error: true
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
        const executeResponse = await fetch(`${getApiBase()}/flows/${stableDeviceId}/${createdFlow.flow_id}/execute`, {
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
        await fetch(`${getApiBase()}/flows/${stableDeviceId}/${createdFlow.flow_id}`, {
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

    // Step types that have screen_activity and need to be on the right screen
    const screenDependentTypes = ['capture_sensors', 'tap', 'swipe', 'text'];
    // Step types that can change screens (navigation actions)
    const screenChangingTypes = ['tap', 'swipe', 'go_back'];

    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];

        // launch_app sets initial screen
        if (step.step_type === 'launch_app') {
            currentActivity = step.screen_activity || step.expected_activity || null;
            currentActivityIndex = i;
            continue;
        }

        // restart_app resets to app's home screen
        if (step.step_type === 'restart_app') {
            currentActivity = null; // Unknown - will be app's home screen
            currentActivityIndex = i;
            continue;
        }

        // go_home/go_back - leaves the app context
        if (step.step_type === 'go_home' || step.step_type === 'go_back') {
            currentActivity = null;
            currentActivityIndex = i;
            continue;
        }

        // Check steps that depend on being on the right screen
        if (step.screen_activity && screenDependentTypes.includes(step.step_type)) {
            const stepActivity = step.screen_activity;

            // If we have a known current activity and it's different
            if (currentActivity && stepActivity !== currentActivity) {
                const currentActName = currentActivity.split('.').pop();
                const stepActName = stepActivity.split('.').pop();

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

            // Update current activity to this step's activity (we're now "expecting" this screen)
            // But only if this step doesn't change screens (sensors don't change screens)
            if (step.step_type === 'capture_sensors') {
                currentActivity = stepActivity;
                currentActivityIndex = i;
            }
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
