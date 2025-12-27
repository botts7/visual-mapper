/**
 * Flow Wizard Step 4 - Review & Test
 * Visual Mapper v0.0.6
 * v0.0.6: Fixed execute/delete endpoint URLs to include device_id
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
 * Test the flow
 */
async function testFlow(wizard) {
    console.log('[Step4] Testing flow...');
    showToast('Testing flow...', 'info');

    const testResults = document.getElementById('testResults');
    const testContent = document.getElementById('testResultsContent');

    if (!testResults || !testContent) return;

    testResults.style.display = 'block';
    testContent.innerHTML = '<p>Running flow test...</p>';

    try {
        // Create temporary flow
        const tempFlow = {
            flow_id: `test_${Date.now()}`,
            device_id: wizard.selectedDevice,
            name: 'Test Flow',
            steps: wizard.flowSteps,
            enabled: false
        };

        // Save temp flow
        const saveResponse = await fetch(`${getApiBase()}/flows`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(tempFlow)
        });

        if (!saveResponse.ok) throw new Error('Failed to create test flow');

        // Execute flow (endpoint requires device_id and flow_id)
        const execResponse = await fetch(`${getApiBase()}/flows/${wizard.selectedDevice}/${tempFlow.flow_id}/execute`, {
            method: 'POST'
        });

        if (!execResponse.ok) throw new Error('Failed to execute test flow');

        const results = await execResponse.json();

        // Display results
        testContent.innerHTML = `
            <div class="test-result ${results.success ? 'success' : 'error'}">
                <strong>Status:</strong> ${results.success ? '✅ Success' : '❌ Failed'}
            </div>
            <div class="test-details">
                <p><strong>Steps Executed:</strong> ${results.steps_completed || 0}/${wizard.flowSteps.length}</p>
                ${results.error ? `<p><strong>Error:</strong> ${results.error}</p>` : ''}
            </div>
        `;

        // Delete temp flow (also requires device_id)
        await fetch(`${getApiBase()}/flows/${wizard.selectedDevice}/${tempFlow.flow_id}`, { method: 'DELETE' });

        showToast(results.success ? 'Test passed!' : 'Test failed', results.success ? 'success' : 'error');

    } catch (error) {
        console.error('[Step4] Test failed:', error);
        testContent.innerHTML = `<p class="error">Test failed: ${error.message}</p>`;
        showToast('Test failed', 'error');
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

export default { loadStep, validateStep, getStepData };
