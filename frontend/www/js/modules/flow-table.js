/**
 * Flow Table Module
 * Visual Mapper v0.0.6
 *
 * Handles flow table rendering and utility functions.
 */

class FlowTable {
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api';
        this.flowManager = options.flowManager || window.flowManager;
        this.deviceInfoMap = options.deviceInfoMap || new Map();
        this.runningFlows = options.runningFlows || new Set();
    }

    /**
     * Render the flow table
     */
    renderTable(flows) {
        const tbody = document.getElementById('flowTableBody');
        if (!tbody) {
            console.warn('[FlowTable] Table body not found');
            return;
        }

        if (!flows || flows.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="11" class="empty-state">
                        <p>No flows configured yet.</p>
                        <p>Flows will appear here once you create them via the API.</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = flows.map(flow => {
            const flowKey = `${flow.device_id}:${flow.flow_id}`;
            const isRunning = this.runningFlows.has(flowKey);

            // Extract apps from launch_app steps
            const apps = this.getFlowApps(flow);
            const appsDisplay = apps.length > 0 ? apps.join(', ') : '-';

            // Parse device ID into name and IP
            const { deviceName, deviceIP } = this.parseDeviceId(flow.device_id);
            const safeFlowId = flow.flow_id.replace(/[^a-zA-Z0-9]/g, '_');

            return `
            <tr>
                <td><strong>${this.escapeHtml(flow.name)}</strong></td>
                <td><code style="font-size: 11px;">${this.escapeHtml(appsDisplay)}</code></td>
                <td>${this.escapeHtml(deviceName)}</td>
                <td><code>${this.escapeHtml(deviceIP)}</code></td>
                <td>${flow.steps.length} steps</td>
                <td>${flow.update_interval_seconds}s</td>
                <td>
                    <label class="toggle-switch">
                        <input type="checkbox"
                               ${flow.enabled ? 'checked' : ''}
                               onchange="toggleFlowEnabled('${flow.device_id}', '${flow.flow_id}', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </td>
                <td>
                    <span class="flow-status ${isRunning ? 'running' : (flow.enabled ? 'enabled' : 'disabled')}">
                        ${isRunning ? 'Running' : (flow.enabled ? 'Enabled' : 'Disabled')}
                    </span>
                </td>
                <td>${this.formatDateTime(flow.last_executed)}</td>
                <td>${this.formatSuccessRate(flow)}</td>
                <td id="last-run-status-${safeFlowId}">
                    <span class="status-loading">Loading...</span>
                </td>
                <td>
                    <div class="flow-row-actions">
                        <button id="execute-btn-${safeFlowId}"
                                class="btn-icon execute ${isRunning ? 'running' : ''}"
                                data-device-id="${flow.device_id}"
                                data-flow-id="${flow.flow_id}"
                                onclick="executeFlow('${flow.device_id}', '${flow.flow_id}')"
                                title="Execute Now"
                                ${isRunning ? 'disabled' : ''}>
                            ${isRunning ? '...' : '>'}
                        </button>
                        <button class="btn-icon logs"
                                onclick="viewFlowLogs('${flow.device_id}', '${flow.flow_id}', '${this.escapeHtml(flow.name)}')"
                                title="View Execution Logs">
                            L
                        </button>
                        <button class="btn-icon test dev-only"
                                onclick="testFlow('${flow.device_id}', '${flow.flow_id}')"
                                title="Test Flow (Dev Mode Only)"
                                ${isRunning ? 'disabled' : ''}>
                            T
                        </button>
                        <button class="btn-icon edit"
                                onclick="editFlow('${flow.device_id}', '${flow.flow_id}')"
                                title="Edit">
                            E
                        </button>
                        <button class="btn-icon delete"
                                onclick="deleteFlow('${flow.device_id}', '${flow.flow_id}', '${this.escapeHtml(flow.name)}')"
                                title="Delete">
                            X
                        </button>
                    </div>
                </td>
            </tr>
        `;
        }).join('');
    }

    /**
     * Update statistics cards
     */
    async updateStats(flows) {
        const totalFlows = flows.length;
        const enabledFlows = flows.filter(f => f.enabled).length;

        const statTotal = document.getElementById('statTotal');
        const statEnabled = document.getElementById('statEnabled');
        const statQueueDepth = document.getElementById('statQueueDepth');
        const statSuccessRate = document.getElementById('statSuccessRate');

        if (statTotal) statTotal.textContent = totalFlows;
        if (statEnabled) statEnabled.textContent = enabledFlows;

        // Get metrics for queue depth and success rate
        try {
            const metricsData = await this.flowManager.getMetrics();
            const metrics = metricsData.all_devices || {};

            let totalQueueDepth = 0;
            let totalSuccessRate = 0;
            let deviceCount = 0;

            Object.values(metrics).forEach(m => {
                if (m.queue_depth !== undefined) {
                    totalQueueDepth += m.queue_depth;
                    deviceCount++;
                }
                if (m.success_rate !== undefined) {
                    totalSuccessRate += m.success_rate;
                }
            });

            if (statQueueDepth) statQueueDepth.textContent = totalQueueDepth;

            if (deviceCount > 0 && statSuccessRate) {
                const avgSuccessRate = (totalSuccessRate / deviceCount) * 100;
                statSuccessRate.textContent = avgSuccessRate.toFixed(1) + '%';
            } else if (statSuccessRate) {
                statSuccessRate.textContent = '-';
            }
        } catch (error) {
            console.error('Failed to load metrics:', error);
        }
    }

    /**
     * Update flow status cell
     */
    updateFlowStatus(flowId, executionData) {
        const safeFlowId = flowId.replace(/[^a-zA-Z0-9]/g, '_');
        const statusCell = document.getElementById(`last-run-status-${safeFlowId}`);
        if (!statusCell) return;

        if (!executionData) {
            statusCell.innerHTML = '<span class="status-none">No runs yet</span>';
            return;
        }

        const { success, started_at, duration_ms, executed_steps, total_steps, error } = executionData;
        const timeAgo = this.formatTimeAgo(started_at);

        let statusHTML = '';
        if (success) {
            const title = `Success - ${timeAgo}\n${executed_steps}/${total_steps} steps completed in ${duration_ms}ms`;
            statusHTML = `<span class="status-success" title="${title}">OK ${timeAgo}</span>`;
        } else {
            const errorMsg = error || 'Unknown error';
            const title = `Failed - ${timeAgo}\n${executed_steps}/${total_steps} steps completed\nError: ${errorMsg}`;
            statusHTML = `<span class="status-failed" title="${title}">X ${timeAgo}</span>`;
        }
        statusCell.innerHTML = statusHTML;
    }

    // Utility methods
    formatDateTime(dateStr) {
        if (!dateStr) return 'Never';
        const date = new Date(dateStr);
        return date.toLocaleString();
    }

    formatSuccessRate(flow) {
        if (!flow.execution_count || flow.execution_count === 0) return '-';
        const rate = (flow.success_count / flow.execution_count) * 100;
        return `${flow.success_count}/${flow.execution_count} (${rate.toFixed(0)}%)`;
    }

    formatTimeAgo(dateStr) {
        if (!dateStr) return 'Never';
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);

        if (diffSec < 60) return `${diffSec}s ago`;
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHour < 24) return `${diffHour}h ago`;
        return date.toLocaleDateString();
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    getFlowApps(flow) {
        const apps = new Set();
        for (const step of flow.steps || []) {
            if (step.step_type === 'launch_app' && step.package) {
                const parts = step.package.split('.');
                const shortName = parts[parts.length - 1] || step.package;
                apps.add(shortName);
            }
        }
        return Array.from(apps);
    }

    parseDeviceId(deviceId) {
        if (!deviceId) {
            return { deviceName: '-', deviceIP: '-' };
        }

        const deviceInfo = this.deviceInfoMap.get(deviceId);
        const ipPortMatch = deviceId.match(/^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):?(\d+)?$/);

        if (ipPortMatch) {
            const ip = ipPortMatch[1];
            const port = ipPortMatch[2] || '5555';
            return {
                deviceName: deviceInfo?.model || ip,
                deviceIP: `${ip}:${port}`
            };
        }

        return {
            deviceName: deviceInfo?.model || deviceId,
            deviceIP: '-'
        };
    }
}

// ES6 export
export default FlowTable;

// Global export for backward compatibility
window.FlowTable = FlowTable;
