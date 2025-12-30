/**
 * Flow Scheduler UI Module
 * Visual Mapper v0.0.6
 *
 * Handles scheduler status display and control.
 */

class FlowSchedulerUI {
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api';
        this.showToast = options.showToast || console.log;
        this.escapeHtml = options.escapeHtml || this._defaultEscapeHtml;
    }

    /**
     * Load scheduler status from the API
     */
    async loadStatus() {
        try {
            const response = await fetch(`${this.apiBase}/scheduler/status`);
            if (!response.ok) throw new Error('Failed to fetch scheduler status');

            const data = await response.json();
            const status = data.status;

            this.renderStatus(status);
        } catch (error) {
            console.error('Failed to load scheduler status:', error);
            const deviceQueues = document.getElementById('deviceQueues') || document.getElementById('deviceQueueGrid');
            if (deviceQueues) {
                deviceQueues.innerHTML = `
                    <p style="color: var(--text-secondary); grid-column: 1 / -1; text-align: center;">
                        Unable to load scheduler status
                    </p>
                `;
            }
        }
    }

    /**
     * Render scheduler status to the DOM
     */
    renderStatus(status) {
        const statusBadge = document.getElementById('schedulerStatusBadge');
        const statusDot = document.getElementById('schedulerStatusDot');
        const statusText = document.getElementById('schedulerStatusText');
        const pauseBtn = document.getElementById('btnPauseScheduler');
        const resumeBtn = document.getElementById('btnResumeScheduler');
        const deviceQueues = document.getElementById('deviceQueues') || document.getElementById('deviceQueueGrid');

        // Update status badge
        let state = 'stopped';
        if (status.running && !status.paused) {
            state = 'running';
            if (statusText) statusText.textContent = 'Running';
        } else if (status.paused) {
            state = 'paused';
            if (statusText) statusText.textContent = 'Paused';
        } else {
            if (statusText) statusText.textContent = 'Stopped';
        }

        if (statusBadge) statusBadge.className = `scheduler-status-badge ${state}`;
        if (statusDot) statusDot.className = `status-dot ${state}`;

        // Toggle buttons
        if (pauseBtn && resumeBtn) {
            if (status.paused) {
                pauseBtn.style.display = 'none';
                resumeBtn.style.display = 'inline-block';
            } else {
                pauseBtn.style.display = 'inline-block';
                resumeBtn.style.display = 'none';
            }
        }

        // Render device queue cards
        if (!deviceQueues) return;

        const devices = status.devices || {};
        const deviceIds = Object.keys(devices);

        if (deviceIds.length === 0) {
            deviceQueues.innerHTML = `
                <p style="color: var(--text-secondary); grid-column: 1 / -1; text-align: center;">
                    No devices with active schedulers
                </p>
            `;
            return;
        }

        deviceQueues.innerHTML = deviceIds.map(deviceId => {
            const device = devices[deviceId];
            const queueDepth = device.queue_depth || 0;
            const queueClass = queueDepth > 5 ? 'critical' : (queueDepth > 2 ? 'warning' : '');

            return `
                <div class="device-queue-card">
                    <h4>
                        <span style="width: 8px; height: 8px; border-radius: 50%; background: ${device.scheduler_active ? '#22c55e' : '#94a3b8'}; display: inline-block;"></span>
                        ${this.escapeHtml(deviceId)}
                    </h4>
                    <div class="queue-stats">
                        <div class="queue-stat">
                            <span class="queue-stat-label">Queue</span>
                            <span class="queue-stat-value ${queueClass}">${queueDepth}</span>
                        </div>
                        <div class="queue-stat">
                            <span class="queue-stat-label">Total Runs</span>
                            <span class="queue-stat-value">${device.total_executions || 0}</span>
                        </div>
                        <div class="queue-stat">
                            <span class="queue-stat-label">Last Run</span>
                            <span class="queue-stat-value" style="font-size: 12px;">
                                ${device.last_execution ? this.formatTimeAgo(device.last_execution) : 'Never'}
                            </span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    /**
     * Format time ago string
     */
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

    /**
     * Pause the scheduler
     */
    async pause() {
        try {
            const response = await fetch(`${this.apiBase}/scheduler/pause`, {
                method: 'POST'
            });

            if (!response.ok) throw new Error('Failed to pause scheduler');

            this.showToast('Scheduler paused', 'success');
            await this.loadStatus();
        } catch (error) {
            this.showToast('Failed to pause scheduler: ' + error.message, 'error');
        }
    }

    /**
     * Resume the scheduler
     */
    async resume() {
        try {
            const response = await fetch(`${this.apiBase}/scheduler/resume`, {
                method: 'POST'
            });

            if (!response.ok) throw new Error('Failed to resume scheduler');

            this.showToast('Scheduler resumed', 'success');
            await this.loadStatus();
        } catch (error) {
            this.showToast('Failed to resume scheduler: ' + error.message, 'error');
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
export default FlowSchedulerUI;

// Global export for backward compatibility
window.FlowSchedulerUI = FlowSchedulerUI;
