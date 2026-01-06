/**
 * Flow Execution Module
 * Visual Mapper v0.0.12
 *
 * Handles flow execution, testing, and results display.
 * v0.0.12: Added step_results with sensor values display
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
        const stepResults = result.step_results || [];

        // Build step-by-step breakdown with sensor values
        let stepsHtml = '';
        if (flow && flow.steps && flow.steps.length > 0) {
            stepsHtml = this._buildStepResultsHtml(flow.steps, stepResults, result);
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
                        <div class="captured-sensors" style="margin-top: 16px; padding: 12px; background: #f0fdf4; border-radius: 8px;">
                            <h5>Summary - All Captured Sensors:</h5>
                            <ul>
                                ${Object.entries(capturedSensors).map(([id, value]) =>
                                    `<li><strong>${this.escapeHtml(id)}:</strong> <span style="color: #16a34a;">${this.escapeHtml(String(value))}</span></li>`
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
     * Build step-by-step results HTML with sensor values
     */
    _buildStepResultsHtml(flowSteps, stepResults, result) {
        if (!flowSteps || flowSteps.length === 0) return '';

        const executedSteps = result.executed_steps ?? 0;
        const self = this;

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
                        const name = self.escapeHtml(info.name || id);
                        const value = self.escapeHtml(String(info.value ?? '--'));
                        return '<li><strong>' + name + ':</strong> <span style="color: #0369a1;">' + value + '</span></li>';
                    }).join('');
                    stepDetails = '<div style="margin-top: 8px; padding: 8px; background: #e0f2fe; border-radius: 4px; font-size: 0.9em;">' +
                        '<strong>Captured ' + sensorCount + ' sensor' + (sensorCount !== 1 ? 's' : '') + ':</strong>' +
                        '<ul style="margin: 4px 0 0 0; padding-left: 20px;">' + sensorItems + '</ul></div>';
                }
            }

            // Add action results for execute_action steps
            if (stepResult && stepResult.details && stepResult.details.action_name) {
                const actionName = self.escapeHtml(stepResult.details.action_name);
                const actionResult = stepResult.details.result ? '<br><strong>Result:</strong> ' + self.escapeHtml(stepResult.details.result) : '';
                stepDetails = '<div style="margin-top: 8px; padding: 8px; background: #fef3c7; border-radius: 4px; font-size: 0.9em;">' +
                    '<strong>Action:</strong> ' + actionName + actionResult + '</div>';
            }

            // Add error details for failed steps
            if (result.failed_step !== null && result.failed_step !== undefined && index === result.failed_step && result.error_message) {
                stepDetails += '<div style="margin-top: 8px; padding: 8px; background: #fef2f2; border-radius: 4px; font-size: 0.9em; color: #dc2626;">' +
                    '<strong>Error:</strong> ' + self.escapeHtml(result.error_message) + '</div>';
            }

            const stepDesc = self.escapeHtml(step.description || step.step_type + ' step');
            const stepType = self.escapeHtml(step.step_type);

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
