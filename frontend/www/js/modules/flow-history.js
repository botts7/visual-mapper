/**
 * Flow Execution History Viewer Module
 * Visual Mapper v0.4.0-beta.4
 *
 * Displays flow execution history in a modal with:
 * - List of recent executions
 * - Success/failure status
 * - Duration and timestamps
 * - Step-by-step details
 * - Statistics summary
 */

import LoggerFactory from './debug-logger.js';

const logger = LoggerFactory.getLogger('FlowHistory');

class FlowHistoryViewer {
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api';
        this.showToast = options.showToast || window.showToast || console.log;
        this.modal = null;
        this.currentFlowId = null;
        this.currentDeviceId = null;
    }

    /**
     * Show execution history for a flow
     * @param {string} deviceId - Device ID
     * @param {string} flowId - Flow ID
     * @param {string} flowName - Flow name for display
     */
    async show(deviceId, flowId, flowName = 'Flow') {
        this.currentDeviceId = deviceId;
        this.currentFlowId = flowId;

        logger.debug(`Showing history for flow: ${flowId}`);

        // Create modal if it doesn't exist
        this._createModal();

        // Show modal with loading state
        this.modal.classList.add('active');
        this._showLoading();

        try {
            // Fetch history
            const response = await fetch(`${this.apiBase}/flows/${deviceId}/${flowId}/history?limit=50`);
            if (!response.ok) {
                throw new Error(`Failed to fetch history: ${response.statusText}`);
            }

            const data = await response.json();
            logger.debug(`Loaded ${data.history?.length || 0} history entries`);

            // Render history
            this._renderHistory(data.history || [], flowName);
        } catch (error) {
            logger.error('Failed to load history:', error);
            this._showError(error.message);
        }
    }

    /**
     * Create the modal element
     * @private
     */
    _createModal() {
        // Remove existing modal if present
        const existing = document.getElementById('flowHistoryModal');
        if (existing) {
            existing.remove();
        }

        this.modal = document.createElement('div');
        this.modal.id = 'flowHistoryModal';
        this.modal.className = 'modal';
        this.modal.innerHTML = `
            <div class="modal-content modal-large">
                <div class="modal-header">
                    <h2>Execution History</h2>
                    <button class="modal-close" onclick="window.flowHistoryViewer?.close()">&times;</button>
                </div>
                <div class="modal-body" id="flowHistoryContent">
                    <!-- Content will be injected here -->
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="window.flowHistoryViewer?.refresh()">Refresh</button>
                    <button class="btn btn-primary" onclick="window.flowHistoryViewer?.close()">Close</button>
                </div>
            </div>
        `;

        document.body.appendChild(this.modal);

        // Close on backdrop click
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.close();
            }
        });
    }

    /**
     * Close the modal
     */
    close() {
        if (this.modal) {
            this.modal.classList.remove('active');
        }
    }

    /**
     * Refresh the history
     */
    async refresh() {
        if (this.currentDeviceId && this.currentFlowId) {
            await this.show(this.currentDeviceId, this.currentFlowId);
        }
    }

    /**
     * Show loading state
     * @private
     */
    _showLoading() {
        const content = document.getElementById('flowHistoryContent');
        if (content) {
            content.innerHTML = `
                <div class="history-loading">
                    <div class="spinner"></div>
                    <p>Loading execution history...</p>
                </div>
            `;
        }
    }

    /**
     * Show error state
     * @private
     */
    _showError(message) {
        const content = document.getElementById('flowHistoryContent');
        if (content) {
            content.innerHTML = `
                <div class="history-error">
                    <p style="color: #dc2626;">Failed to load history: ${this._escapeHtml(message)}</p>
                    <button class="btn btn-secondary" onclick="window.flowHistoryViewer?.refresh()">Retry</button>
                </div>
            `;
        }
    }

    /**
     * Render history data
     * @private
     */
    _renderHistory(history, flowName) {
        const content = document.getElementById('flowHistoryContent');
        if (!content) return;

        if (!history || history.length === 0) {
            content.innerHTML = `
                <div class="history-empty">
                    <p>No execution history found for this flow.</p>
                    <p class="hint">Execute the flow to start tracking history.</p>
                </div>
            `;
            return;
        }

        // Calculate stats
        const stats = this._calculateStats(history);

        // Build HTML
        content.innerHTML = `
            <div class="history-header">
                <h3>${this._escapeHtml(flowName)}</h3>
            </div>

            <div class="history-stats">
                <div class="stat-item">
                    <span class="stat-label">Total Runs</span>
                    <span class="stat-value">${stats.total}</span>
                </div>
                <div class="stat-item success">
                    <span class="stat-label">Successful</span>
                    <span class="stat-value">${stats.success}</span>
                </div>
                <div class="stat-item failure">
                    <span class="stat-label">Failed</span>
                    <span class="stat-value">${stats.failure}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Success Rate</span>
                    <span class="stat-value">${stats.successRate}%</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Avg Duration</span>
                    <span class="stat-value">${this._formatDuration(stats.avgDuration)}</span>
                </div>
            </div>

            <div class="history-list">
                <h4>Recent Executions</h4>
                <table class="history-table">
                    <thead>
                        <tr>
                            <th>Status</th>
                            <th>Started</th>
                            <th>Duration</th>
                            <th>Steps</th>
                            <th>Triggered By</th>
                            <th>Details</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${history.slice().reverse().map(log => this._renderHistoryRow(log)).join('')}
                    </tbody>
                </table>
            </div>
        `;

        // Attach event listeners for detail expansion
        content.querySelectorAll('.history-details-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const executionId = btn.dataset.executionId;
                this._toggleDetails(executionId, history);
            });
        });
    }

    /**
     * Render a single history row
     * @private
     */
    _renderHistoryRow(log) {
        const statusClass = log.success ? 'success' : 'failure';
        const statusIcon = log.success ? '✓' : '✗';
        const startedAt = this._formatDate(log.started_at);
        const duration = this._formatDuration(log.duration_ms);
        const stepsInfo = `${log.executed_steps}/${log.total_steps}`;
        const triggeredBy = log.triggered_by || 'unknown';

        return `
            <tr class="history-row ${statusClass}">
                <td>
                    <span class="status-badge ${statusClass}">${statusIcon}</span>
                </td>
                <td>${startedAt}</td>
                <td>${duration}</td>
                <td>${stepsInfo}</td>
                <td><span class="trigger-badge">${triggeredBy}</span></td>
                <td>
                    <button class="btn btn-sm history-details-btn" data-execution-id="${log.execution_id}">
                        View
                    </button>
                </td>
            </tr>
            <tr class="history-detail-row" id="detail-${log.execution_id}" style="display: none;">
                <td colspan="6">
                    <div class="history-detail-content" id="detail-content-${log.execution_id}">
                        <!-- Details loaded on demand -->
                    </div>
                </td>
            </tr>
        `;
    }

    /**
     * Toggle detail view for an execution
     * @private
     */
    _toggleDetails(executionId, history) {
        const detailRow = document.getElementById(`detail-${executionId}`);
        const detailContent = document.getElementById(`detail-content-${executionId}`);

        if (!detailRow || !detailContent) return;

        if (detailRow.style.display === 'none') {
            // Show details
            const log = history.find(l => l.execution_id === executionId);
            if (log) {
                detailContent.innerHTML = this._renderDetailContent(log);
            }
            detailRow.style.display = 'table-row';
        } else {
            // Hide details
            detailRow.style.display = 'none';
        }
    }

    /**
     * Render detailed execution content
     * @private
     */
    _renderDetailContent(log) {
        let html = '<div class="execution-detail">';

        // Error message if failed
        if (!log.success && log.error) {
            html += `
                <div class="error-message">
                    <strong>Error:</strong> ${this._escapeHtml(log.error)}
                </div>
            `;
        }

        // Step-by-step breakdown
        if (log.steps && log.steps.length > 0) {
            html += '<div class="steps-breakdown"><h5>Step-by-Step:</h5><ul class="steps-list">';
            log.steps.forEach((step, index) => {
                const stepClass = step.success ? 'success' : 'failure';
                const stepIcon = step.success ? '✓' : '✗';
                const stepDuration = step.duration_ms ? `${step.duration_ms}ms` : '-';
                const stepDesc = step.description || step.step_type || `Step ${index + 1}`;

                html += `
                    <li class="step-item ${stepClass}">
                        <span class="step-icon">${stepIcon}</span>
                        <span class="step-desc">${this._escapeHtml(stepDesc)}</span>
                        <span class="step-duration">${stepDuration}</span>
                        ${step.error ? `<div class="step-error">${this._escapeHtml(step.error)}</div>` : ''}
                    </li>
                `;
            });
            html += '</ul></div>';
        }

        html += '</div>';
        return html;
    }

    /**
     * Calculate stats from history
     * @private
     */
    _calculateStats(history) {
        const total = history.length;
        const success = history.filter(h => h.success).length;
        const failure = total - success;
        const successRate = total > 0 ? Math.round((success / total) * 100) : 0;

        const durations = history.filter(h => h.duration_ms).map(h => h.duration_ms);
        const avgDuration = durations.length > 0
            ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
            : 0;

        return { total, success, failure, successRate, avgDuration };
    }

    /**
     * Format date for display
     * @private
     */
    _formatDate(isoDate) {
        if (!isoDate) return '-';
        try {
            const date = new Date(isoDate);
            return date.toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return isoDate;
        }
    }

    /**
     * Format duration for display
     * @private
     */
    _formatDuration(ms) {
        if (!ms && ms !== 0) return '-';
        if (ms < 1000) return `${ms}ms`;
        if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
        return `${Math.round(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
    }

    /**
     * Escape HTML to prevent XSS
     * @private
     */
    _escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Create singleton instance
const flowHistoryViewer = new FlowHistoryViewer();

// Expose globally for onclick handlers
window.flowHistoryViewer = flowHistoryViewer;

// Helper function for easy access
window.showFlowHistory = (deviceId, flowId, flowName) => {
    flowHistoryViewer.show(deviceId, flowId, flowName);
};

export default FlowHistoryViewer;
