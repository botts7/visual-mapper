/**
 * Flow Wizard Step 4 - Review & Test
 * Visual Mapper v0.0.5
 *
 * Handles flow review, testing, and step management
 * Extracted from flow-wizard.js for modularity
 */

import { showToast } from './toast.js?v=0.0.5';
import FlowStepManager from './flow-step-manager.js?v=0.0.5';

function getApiBase() {
    return window.API_BASE || '/api';
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

    const appLabel = wizard.selectedApp?.label || wizard.selectedApp?.package || wizard.selectedApp || 'Unknown';

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

        <div class="steps-review-list">
            ${wizard.flowSteps.map((step, index) => `
                <div class="step-review-item">
                    <div class="step-review-number">${index + 1}</div>
                    <div class="step-review-content">
                        <div class="step-review-type">${FlowStepManager.formatStepType(step.step_type)}</div>
                        <div class="step-review-description">${step.description || FlowStepManager.generateStepDescription(step)}</div>
                        ${FlowStepManager.renderStepDetails(step)}
                    </div>
                    <div class="step-review-actions">
                        <button class="btn btn-sm btn-danger" onclick="window.flowWizard.removeStepAt(${index})">
                            Delete
                        </button>
                    </div>
                </div>
            `).join('')}
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
        // Build flow payload
        const flowPayload = {
            flow_id: `test_${Date.now()}`,
            device_id: wizard.selectedDevice,
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
        const executeResponse = await fetch(`${getApiBase()}/flows/${wizard.selectedDevice}/${createdFlow.flow_id}/execute`, {
            method: 'POST'
        });

        if (!executeResponse.ok) {
            const error = await executeResponse.json();
            throw new Error(error.detail || 'Flow execution failed');
        }

        const result = await executeResponse.json();
        console.log('[Step4] Flow execution result:', result);

        // Display results
        if (result.success) {
            const executedSteps = result.executed_steps ?? 0;
            const executionTime = result.execution_time_ms ?? 0;
            const capturedSensors = result.captured_sensors || {};

            testResultsContent.innerHTML = `
                <div class="test-success">
                    <h4>✅ Flow Test Passed</h4>
                    <p><strong>Executed Steps:</strong> ${executedSteps} / ${wizard.flowSteps.length}</p>
                    <p><strong>Execution Time:</strong> ${executionTime}ms</p>
                    ${Object.keys(capturedSensors).length > 0 ? `
                        <div class="captured-sensors">
                            <strong>Captured Sensors:</strong>
                            <ul>
                                ${Object.entries(capturedSensors).map(([id, value]) =>
                                    `<li>${id}: ${value}</li>`
                                ).join('')}
                            </ul>
                        </div>
                    ` : ''}
                </div>
            `;
            showToast('Flow test passed!', 'success');
        } else {
            const executedSteps = result.executed_steps ?? 0;
            const failedStep = result.failed_step !== null && result.failed_step !== undefined ? result.failed_step + 1 : 'Unknown';

            testResultsContent.innerHTML = `
                <div class="test-failure">
                    <h4>❌ Flow Test Failed</h4>
                    <p><strong>Failed at Step:</strong> ${failedStep}</p>
                    <p><strong>Error:</strong> ${result.error_message || 'Unknown error'}</p>
                    <p><strong>Executed Steps:</strong> ${executedSteps} / ${wizard.flowSteps.length}</p>
                </div>
            `;
            showToast('Flow test failed', 'error');
        }

        // Clean up test flow
        await fetch(`${getApiBase()}/flows/${wizard.selectedDevice}/${createdFlow.flow_id}`, {
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
 * Validate Step 4
 */
export function validateStep(wizard) {
    if (wizard.flowSteps.length === 0) {
        alert('Please record at least one step');
        return false;
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
