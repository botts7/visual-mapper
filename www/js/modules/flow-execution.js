/**
 * Flow Execution Module
 * Visual Mapper v0.0.6
 *
 * Handles flow execution, testing, and results display.
 */

class FlowExecution {
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api';
        this.flowManager = options.flowManager || window.flowManager;
        this.showToast = options.showToast || console.log;
        this.escapeHtml = options.escapeHtml || this._defaultEscapeHtml;
        this.runningFlows = options.runningFlows || new Set();
        this.flows = options.flows || [];
        this.loadFlows = options.loadFlows || (() => {});
        this.fetchFlowExecutionStatus = options.fetchFlowExecutionStatus || (() => {});
    }

    /**
     * Execute a flow
     */
    async execute(deviceId, flowId) {
        const flowKey = `${deviceId}:${flowId}`;
        const safeFlowId = flowId.replace(/[^a-zA-Z0-9]/g, '_');
        const executeBtn = document.getElementById(`execute-btn-${safeFlowId}`);

        // Prevent double-execution
        if (this.runningFlows.has(flowKey)) {
            this.showToast('Flow is already running', 'warning');
            return;
        }

        try {
            // Add to running set and update only this button's UI
            this.runningFlows.add(flowKey);
            if (executeBtn) {
                executeBtn.classList.add('running');
                executeBtn.disabled = true;
                executeBtn.innerHTML = '...';
            }

            this.showToast('Flow execution started...', 'info');

            // Execute the flow via API and get execution result
            const response = await fetch(`${this.apiBase}/flows/${deviceId}/${flowId}/execute`, {
                method: 'POST'
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Flow execution failed');
            }

            const result = await response.json();
            console.log('[FlowExecution] Flow execution result:', result);

            // Show execution results
            this.showResults(result);

            // Show success or failure toast
            if (result.success) {
                this.showToast('Flow execution completed!', 'success');
            } else {
                this.showToast('Flow execution failed: ' + (result.error_message || 'Unknown error'), 'error');
            }

            // Update the last run status for this flow immediately
            this.fetchFlowExecutionStatus(deviceId, flowId);

            // Keep running state visible for 1 second, then reset button
            setTimeout(async () => {
                this.runningFlows.delete(flowKey);
                if (executeBtn) {
                    executeBtn.classList.remove('running');
                    executeBtn.disabled = false;
                    executeBtn.innerHTML = '>';
                }
                await this.loadFlows();
            }, 1000);

        } catch (error) {
            // Remove from running set on error and reset button
            this.runningFlows.delete(flowKey);
            if (executeBtn) {
                executeBtn.classList.remove('running');
                executeBtn.disabled = false;
                executeBtn.innerHTML = '>';
            }
            this.showToast('Failed to execute flow: ' + error.message, 'error');
        }
    }

    /**
     * Show execution results in modal
     */
    showResults(result) {
        const modal = document.getElementById('executionResultsModal');
        const content = document.getElementById('executionResultsContent') || document.getElementById('executionResultsBody');

        if (!modal || !content) {
            console.warn('[FlowExecution] Results modal not found');
            return;
        }

        // Get flow definition to show step details
        const flow = this.flows.find(f => f.flow_id === result.flow_id);
        const totalSteps = flow ? flow.steps.length : result.executed_steps ?? 0;
        const executedSteps = result.executed_steps ?? 0;
        const executionTime = result.execution_time_ms ?? 0;
        const capturedSensors = result.captured_sensors || {};

        // Build step-by-step breakdown
        let stepsHtml = '';
        if (flow && flow.steps && flow.steps.length > 0) {
            stepsHtml = `
                <div class="execution-steps">
                    <h5>Execution Steps:</h5>
                    <ol class="step-list">
                        ${flow.steps.map((step, index) => {
                            let statusIcon = '';
                            let statusClass = '';
                            let errorDetail = '';

                            if (index < executedSteps) {
                                statusIcon = 'OK';
                                statusClass = 'step-success';
                            } else if (result.failed_step !== null && result.failed_step !== undefined && index === result.failed_step) {
                                statusIcon = 'X';
                                statusClass = 'step-failed';
                                errorDetail = `<div class="step-error">${this.escapeHtml(result.error_message || 'Unknown error')}</div>`;
                            } else {
                                statusIcon = '-';
                                statusClass = 'step-skipped';
                            }

                            const stepDesc = step.description || `${step.step_type} step`;

                            return `
                                <li class="step-item ${statusClass}">
                                    <span class="step-status">${statusIcon}</span>
                                    <span class="step-info">
                                        <strong>${this.escapeHtml(stepDesc)}</strong>
                                        <span class="step-type">(${this.escapeHtml(step.step_type)})</span>
                                    </span>
                                    ${errorDetail}
                                </li>
                            `;
                        }).join('')}
                    </ol>
                </div>
            `;
        }

        // Display results based on success/failure
        if (result.success) {
            content.innerHTML = `
                <div class="test-success">
                    <h4>Flow Execution Successful</h4>
                    <div class="execution-summary">
                        <p><strong>Executed Steps:</strong> ${executedSteps} / ${totalSteps}</p>
                        <p><strong>Execution Time:</strong> ${executionTime}ms</p>
                    </div>
                    ${stepsHtml}
                    ${Object.keys(capturedSensors).length > 0 ? `
                        <div class="captured-sensors">
                            <h5>Captured Sensors:</h5>
                            <ul>
                                ${Object.entries(capturedSensors).map(([id, value]) =>
                                    `<li><strong>${this.escapeHtml(id)}:</strong> ${this.escapeHtml(String(value))}</li>`
                                ).join('')}
                            </ul>
                        </div>
                    ` : ''}
                </div>
            `;
        } else {
            const failedStepNum = result.failed_step !== null && result.failed_step !== undefined ? result.failed_step + 1 : 'Unknown';

            content.innerHTML = `
                <div class="test-failure">
                    <h4>Flow Execution Failed</h4>
                    <div class="execution-summary">
                        <p><strong>Failed at Step:</strong> ${failedStepNum}</p>
                        <p><strong>Error:</strong> ${this.escapeHtml(result.error_message || 'Unknown error')}</p>
                        <p><strong>Executed Steps:</strong> ${executedSteps} / ${totalSteps}</p>
                    </div>
                    ${stepsHtml}
                </div>
            `;
        }

        // Show modal
        modal.classList.add('active');
    }

    /**
     * Close execution results modal
     */
    closeResultsModal() {
        const modal = document.getElementById('executionResultsModal');
        if (modal) modal.classList.remove('active');
    }

    /**
     * Test a flow
     */
    async test(deviceId, flowId) {
        try {
            this.showToast('Testing flow...', 'info');

            const response = await fetch(`${this.apiBase}/flows/${deviceId}/${flowId}/execute`, {
                method: 'POST'
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Flow test failed');
            }

            const result = await response.json();
            console.log('[FlowExecution] Flow test result:', result);

            this.showResults(result);

            if (result.success) {
                this.showToast('Flow test passed!', 'success');
            } else {
                this.showToast('Flow test failed', 'error');
            }

        } catch (error) {
            console.error('[FlowExecution] Flow test error:', error);
            this.showToast(`Test error: ${error.message}`, 'error');
        }
    }

    /**
     * Delete a flow
     */
    async delete(deviceId, flowId, flowName) {
        if (!confirm(`Are you sure you want to delete flow "${flowName}"?`)) {
            return;
        }

        try {
            await this.flowManager.deleteFlow(deviceId, flowId);
            this.showToast('Flow deleted successfully', 'success');
            await this.loadFlows();
        } catch (error) {
            this.showToast('Failed to delete flow: ' + error.message, 'error');
        }
    }

    // Default utility methods
    _defaultEscapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// ES6 export
export default FlowExecution;

// Global export for backward compatibility
window.FlowExecution = FlowExecution;
