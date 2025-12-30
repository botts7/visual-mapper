/**
 * Performance Dashboard Module
 * Visual Mapper v0.0.6
 *
 * Handles real-time performance monitoring and threshold configuration.
 */

class PerformanceDashboard {
    constructor() {
        this.apiBase = this.detectApiBase();
        this.currentDevice = ''; // Empty = all devices
        this.autoRefreshInterval = null;
        this.autoRefreshMs = 30000;
    }

    /**
     * Detect API base URL for Home Assistant ingress compatibility
     */
    detectApiBase() {
        if (window.API_BASE) return window.API_BASE;
        if (window.opener?.API_BASE) return window.opener.API_BASE;

        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);

        if (ingressMatch) {
            return ingressMatch[0] + '/api';
        }

        return '/api';
    }

    /**
     * Initialize the dashboard
     */
    async init() {
        console.log('[PerformanceDashboard] Initializing...');

        try {
            // Load devices for selector
            await this.loadDevices();

            // Load initial data
            await this.refresh();

            // Load thresholds
            await this.loadThresholds();

            // Start auto-refresh if checkbox is checked
            const autoRefreshToggle = document.getElementById('autoRefreshToggle');
            if (autoRefreshToggle && autoRefreshToggle.checked) {
                this.startAutoRefresh(this.autoRefreshMs);
            }

            console.log('[PerformanceDashboard] Initialized successfully');
        } catch (error) {
            console.error('[PerformanceDashboard] Initialization failed:', error);
        }
    }

    /**
     * Load available devices for the selector
     */
    async loadDevices() {
        try {
            const response = await fetch(`${this.apiBase}/adb/devices`);
            if (!response.ok) throw new Error('Failed to load devices');

            const data = await response.json();
            const selector = document.getElementById('deviceSelector');
            if (!selector) return;

            // Clear existing options except "All Devices"
            selector.innerHTML = '<option value="">All Devices</option>';

            // Add device options
            if (data.devices) {
                for (const device of data.devices) {
                    const option = document.createElement('option');
                    option.value = device.id || device.serial;
                    option.textContent = device.model || device.id || device.serial;
                    selector.appendChild(option);
                }
            }

            console.log(`[PerformanceDashboard] Loaded ${data.devices?.length || 0} devices`);
        } catch (error) {
            console.error('[PerformanceDashboard] Failed to load devices:', error);
        }
    }

    /**
     * Set current device filter
     */
    setDevice(deviceId) {
        this.currentDevice = deviceId || '';
        console.log(`[PerformanceDashboard] Device filter set to: ${this.currentDevice || 'All'}`);
        this.refresh();
    }

    /**
     * Refresh all dashboard data
     */
    async refresh() {
        console.log('[PerformanceDashboard] Refreshing data...');

        try {
            await Promise.all([
                this.loadSystemStatus(),
                this.loadMetrics(),
                this.loadAlerts()
            ]);

            this.updateLastUpdated();
        } catch (error) {
            console.error('[PerformanceDashboard] Refresh failed:', error);
        }
    }

    /**
     * Load system status (CPU, memory, etc.)
     */
    async loadSystemStatus() {
        try {
            const response = await fetch(`${this.apiBase}/diagnostics/system`);
            if (!response.ok) throw new Error('Failed to load system status');

            const data = await response.json();

            // Update system status bar
            this.updateElement('sysCpu', `${data.cpu_percent || 0}%`);
            this.updateElement('sysMemory',
                data.memory_total_mb ? `${data.memory_used_mb}/${data.memory_total_mb} MB` : '--');
            this.updateElement('sysDevices', data.connected_devices || 0);

            // MQTT status
            const mqttEl = document.getElementById('sysMqtt');
            if (mqttEl) {
                mqttEl.textContent = data.mqtt_connected ? 'Connected' : 'Disconnected';
                mqttEl.className = `status-value ${data.mqtt_connected ? 'connected' : 'disconnected'}`;
            }

            // Uptime
            if (data.uptime_seconds > 0) {
                this.updateElement('sysUptime', this.formatUptime(data.uptime_seconds));
            }

            // Update scheduler status in metrics
            if (data.flow_scheduler) {
                const status = data.flow_scheduler.paused ? 'Paused' :
                               data.flow_scheduler.running ? 'Running' : 'Stopped';
                this.updateElement('metricSchedulerStatus', `Scheduler: ${status}`);
                this.updateElement('metricActiveFlows', data.flow_scheduler.active_flows || 0);
            }

        } catch (error) {
            console.error('[PerformanceDashboard] Failed to load system status:', error);
        }
    }

    /**
     * Load performance metrics
     */
    async loadMetrics() {
        try {
            const url = this.currentDevice
                ? `${this.apiBase}/flows/metrics?device_id=${encodeURIComponent(this.currentDevice)}`
                : `${this.apiBase}/flows/metrics`;

            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to load metrics');

            const data = await response.json();

            // Process metrics based on whether it's single device or all
            let metrics;
            let slowestFlows = [];

            if (this.currentDevice && data.metrics) {
                metrics = data.metrics;
                slowestFlows = metrics.slowest_flows || [];
            } else if (data.all_devices) {
                // Aggregate metrics from all devices
                metrics = this.aggregateMetrics(data.all_devices);
                // Combine slowest flows from all devices
                for (const deviceMetrics of Object.values(data.all_devices)) {
                    if (deviceMetrics.slowest_flows) {
                        slowestFlows.push(...deviceMetrics.slowest_flows);
                    }
                }
                // Sort and take top 5
                slowestFlows.sort((a, b) => b.avg_time_ms - a.avg_time_ms);
                slowestFlows = slowestFlows.slice(0, 5);
            }

            // Update metrics cards
            if (metrics && !metrics.no_data) {
                // Success Rate
                const successRate = (metrics.success_rate * 100).toFixed(1);
                const recentSuccessRate = (metrics.recent_success_rate * 100).toFixed(1);
                this.updateElement('metricSuccessRate', `${successRate}%`);
                this.updateElement('metricSuccessRateSub', `Recent: ${recentSuccessRate}%`);

                // Color code success rate
                const successEl = document.getElementById('metricSuccessRate');
                if (successEl) {
                    successEl.className = 'metric-value';
                    if (metrics.success_rate >= 0.9) successEl.classList.add('success');
                    else if (metrics.success_rate >= 0.7) successEl.classList.add('warning');
                    else successEl.classList.add('critical');
                }

                // Avg Execution Time
                const avgTime = metrics.avg_execution_time_ms || 0;
                this.updateElement('metricAvgTime', this.formatTime(avgTime));
                this.updateElement('metricTotalExecutions',
                    `Total: ${metrics.total_executions || 0} executions`);

                // Queue Depth
                const queueDepth = metrics.queue_depth || 0;
                this.updateElement('metricQueueDepth', queueDepth);

                // Color code queue depth
                const queueEl = document.getElementById('metricQueueDepth');
                if (queueEl) {
                    queueEl.className = 'metric-value';
                    if (queueDepth >= 10) {
                        queueEl.classList.add('critical');
                        this.updateElement('metricQueueStatus', 'Critical - High backlog');
                    } else if (queueDepth >= 5) {
                        queueEl.classList.add('warning');
                        this.updateElement('metricQueueStatus', 'Warning - Building up');
                    } else {
                        this.updateElement('metricQueueStatus', 'Normal');
                    }
                }
            } else {
                // No data
                this.updateElement('metricSuccessRate', '--');
                this.updateElement('metricSuccessRateSub', 'No executions yet');
                this.updateElement('metricAvgTime', '--');
                this.updateElement('metricTotalExecutions', 'No data');
                this.updateElement('metricQueueDepth', '0');
                this.updateElement('metricQueueStatus', 'Normal');
            }

            // Render slowest flows table
            this.renderSlowestFlows(slowestFlows);

        } catch (error) {
            console.error('[PerformanceDashboard] Failed to load metrics:', error);
        }
    }

    /**
     * Aggregate metrics from multiple devices
     */
    aggregateMetrics(allDevices) {
        const deviceList = Object.values(allDevices).filter(m => !m.no_data);

        if (deviceList.length === 0) {
            return { no_data: true };
        }

        let totalExecutions = 0;
        let successfulExecutions = 0;
        let totalTime = 0;
        let totalQueueDepth = 0;

        for (const metrics of deviceList) {
            totalExecutions += metrics.total_executions || 0;
            successfulExecutions += metrics.successful_executions || 0;
            totalTime += (metrics.avg_execution_time_ms || 0) * (metrics.total_executions || 0);
            totalQueueDepth += metrics.queue_depth || 0;
        }

        return {
            total_executions: totalExecutions,
            successful_executions: successfulExecutions,
            success_rate: totalExecutions > 0 ? successfulExecutions / totalExecutions : 0,
            recent_success_rate: totalExecutions > 0 ? successfulExecutions / totalExecutions : 0,
            avg_execution_time_ms: totalExecutions > 0 ? Math.round(totalTime / totalExecutions) : 0,
            queue_depth: totalQueueDepth
        };
    }

    /**
     * Load performance alerts
     */
    async loadAlerts() {
        try {
            const url = this.currentDevice
                ? `${this.apiBase}/flows/alerts?device_id=${encodeURIComponent(this.currentDevice)}&limit=10`
                : `${this.apiBase}/flows/alerts?limit=10`;

            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to load alerts');

            const data = await response.json();
            this.renderAlerts(data.alerts || []);
            this.updateElement('alertCount', `${data.count || 0} alerts`);

        } catch (error) {
            console.error('[PerformanceDashboard] Failed to load alerts:', error);
        }
    }

    /**
     * Render alerts list
     */
    renderAlerts(alerts) {
        const container = document.getElementById('alertsList');
        if (!container) return;

        if (!alerts || alerts.length === 0) {
            container.innerHTML = '<p class="no-alerts">No alerts</p>';
            return;
        }

        container.innerHTML = alerts.map(alert => {
            const icon = this.getSeverityIcon(alert.severity);
            const timeAgo = this.formatTimeAgo(alert.timestamp);

            return `
                <div class="alert-item ${alert.severity || 'info'}">
                    <span class="alert-icon">${icon}</span>
                    <div class="alert-content">
                        <div class="alert-message">${this.escapeHtml(alert.message)}</div>
                        ${alert.recommendation ?
                            `<div class="alert-recommendation">${this.escapeHtml(alert.recommendation)}</div>` : ''}
                    </div>
                    <span class="alert-time">${timeAgo}</span>
                </div>
            `;
        }).join('');
    }

    /**
     * Get icon for alert severity
     */
    getSeverityIcon(severity) {
        const icons = {
            info: 'i',
            warning: '!',
            error: '!!',
            critical: '!!!'
        };
        return icons[severity] || 'i';
    }

    /**
     * Render slowest flows table
     */
    renderSlowestFlows(flows) {
        const tbody = document.getElementById('slowestFlowsBody');
        if (!tbody) return;

        if (!flows || flows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty-message">No data available</td></tr>';
            return;
        }

        tbody.innerHTML = flows.map((flow, index) => {
            const avgTime = flow.avg_time_ms || 0;
            const isSlow = avgTime > 5000;

            return `
                <tr>
                    <td class="flow-rank">#${index + 1}</td>
                    <td class="flow-name">${this.escapeHtml(flow.flow_id || flow.name || 'Unknown')}</td>
                    <td class="flow-time ${isSlow ? 'slow' : ''}">${this.formatTime(avgTime)}</td>
                    <td>${flow.execution_count || 0}</td>
                </tr>
            `;
        }).join('');
    }

    /**
     * Load current threshold configuration
     */
    async loadThresholds() {
        try {
            const response = await fetch(`${this.apiBase}/flows/thresholds`);
            if (!response.ok) throw new Error('Failed to load thresholds');

            const data = await response.json();

            // Populate form fields
            this.setInputValue('queueWarning', data.queue_depth_warning || 5);
            this.setInputValue('queueCritical', data.queue_depth_critical || 10);
            this.setInputValue('failureWarning', Math.round((data.failure_rate_warning || 0.2) * 100));
            this.setInputValue('failureCritical', Math.round((data.failure_rate_critical || 0.5) * 100));
            this.setInputValue('alertCooldown', data.alert_cooldown_seconds || 300);

            console.log('[PerformanceDashboard] Thresholds loaded');
        } catch (error) {
            console.error('[PerformanceDashboard] Failed to load thresholds:', error);
        }
    }

    /**
     * Save threshold configuration
     */
    async saveThresholds() {
        try {
            const thresholds = {
                queue_depth_warning: parseInt(document.getElementById('queueWarning')?.value || 5),
                queue_depth_critical: parseInt(document.getElementById('queueCritical')?.value || 10),
                failure_rate_warning: (parseInt(document.getElementById('failureWarning')?.value || 20)) / 100,
                failure_rate_critical: (parseInt(document.getElementById('failureCritical')?.value || 50)) / 100,
                alert_cooldown_seconds: parseInt(document.getElementById('alertCooldown')?.value || 300)
            };

            const response = await fetch(`${this.apiBase}/flows/thresholds`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(thresholds)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to save thresholds');
            }

            console.log('[PerformanceDashboard] Thresholds saved successfully');
            alert('Thresholds saved successfully!');
        } catch (error) {
            console.error('[PerformanceDashboard] Failed to save thresholds:', error);
            alert(`Failed to save thresholds: ${error.message}`);
        }
    }

    /**
     * Clear all alerts
     */
    async clearAlerts() {
        try {
            const url = this.currentDevice
                ? `${this.apiBase}/flows/alerts?device_id=${encodeURIComponent(this.currentDevice)}`
                : `${this.apiBase}/flows/alerts`;

            const response = await fetch(url, { method: 'DELETE' });
            if (!response.ok) throw new Error('Failed to clear alerts');

            console.log('[PerformanceDashboard] Alerts cleared');
            await this.loadAlerts();
        } catch (error) {
            console.error('[PerformanceDashboard] Failed to clear alerts:', error);
            alert(`Failed to clear alerts: ${error.message}`);
        }
    }

    /**
     * Start auto-refresh
     */
    startAutoRefresh(intervalMs) {
        this.stopAutoRefresh();
        this.autoRefreshMs = intervalMs;
        this.autoRefreshInterval = setInterval(() => this.refresh(), intervalMs);
        console.log(`[PerformanceDashboard] Auto-refresh started (${intervalMs}ms)`);
    }

    /**
     * Stop auto-refresh
     */
    stopAutoRefresh() {
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
            this.autoRefreshInterval = null;
            console.log('[PerformanceDashboard] Auto-refresh stopped');
        }
    }

    /**
     * Update last updated timestamp
     */
    updateLastUpdated() {
        const now = new Date();
        const timeStr = now.toLocaleTimeString();
        this.updateElement('lastUpdated', `Last updated: ${timeStr}`);
    }

    // Utility Methods

    updateElement(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    setInputValue(id, value) {
        const el = document.getElementById(id);
        if (el) el.value = value;
    }

    formatTime(ms) {
        if (ms < 1000) return `${ms}ms`;
        return `${(ms / 1000).toFixed(1)}s`;
    }

    formatUptime(seconds) {
        if (seconds < 60) return `${seconds}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
        return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
    }

    formatTimeAgo(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);

        if (diff < 60) return 'Just now';
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return `${Math.floor(diff / 86400)}d ago`;
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// ES6 export
export default PerformanceDashboard;

// Global export for backward compatibility
window.PerformanceDashboard = PerformanceDashboard;
