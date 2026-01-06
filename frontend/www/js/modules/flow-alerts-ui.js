/**
 * Flow Alerts UI Module
 * Visual Mapper v0.0.6
 *
 * Handles performance alerts display and management.
 */

class FlowAlertsUI {
    constructor(options = {}) {
        this.apiBase = options.apiBase || '/api';
        this.showToast = options.showToast || console.log;
        this.escapeHtml = options.escapeHtml || this._defaultEscapeHtml;
        this.formatDateTime = options.formatDateTime || this._defaultFormatDateTime;
    }

    /**
     * Load alerts from the API
     */
    async loadAlerts() {
        try {
            const response = await fetch(`${this.apiBase}/flows/alerts?limit=10`);
            if (!response.ok) throw new Error('Failed to fetch alerts');

            const data = await response.json();
            const alerts = data.alerts || [];

            this.renderAlerts(alerts);
        } catch (error) {
            console.error('Failed to load alerts:', error);
        }
    }

    /**
     * Render alerts to the DOM
     */
    renderAlerts(alerts) {
        const alertsPanel = document.getElementById('alertsPanel');
        const alertsList = document.getElementById('alertsList');

        if (!alertsPanel || !alertsList) {
            console.warn('[FlowAlertsUI] Alerts panel or list not found');
            return;
        }

        if (alerts.length === 0) {
            alertsPanel.classList.add('hidden');
            alertsPanel.style.display = 'none';
            return;
        }

        alertsPanel.classList.remove('hidden');
        alertsPanel.style.display = '';

        alertsList.innerHTML = alerts.map(alert => `
            <div class="alert-card severity-${alert.severity}">
                <div class="alert-content">
                    <div class="alert-message">
                        ${this.getSeverityIcon(alert.severity)} ${this.escapeHtml(alert.message)}
                    </div>
                    <div class="alert-timestamp">
                        ${this.formatDateTime(alert.timestamp)}
                        ${alert.device_id ? ` • Device: ${alert.device_id}` : ''}
                        ${alert.flow_id ? ` • Flow: ${alert.flow_id}` : ''}
                    </div>
                    ${alert.recommendations && alert.recommendations.length > 0 ? `
                        <ul class="alert-recommendations">
                            ${alert.recommendations.map(rec => `<li>${this.escapeHtml(rec)}</li>`).join('')}
                        </ul>
                    ` : ''}
                </div>
                <button type="button" class="alert-dismiss" onclick="window.flowAlertsUI.dismissAlert('${alert.device_id}', event)" title="Dismiss alert">
                    ×
                </button>
            </div>
        `).join('');
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
     * Clear all alerts
     */
    async clearAllAlerts() {
        if (!confirm('Clear all performance alerts?')) {
            return;
        }

        try {
            const response = await fetch(`${this.apiBase}/flows/alerts`, {
                method: 'DELETE'
            });

            if (!response.ok) throw new Error('Failed to clear alerts');

            this.showToast('Alerts cleared', 'success');
            await this.loadAlerts();
        } catch (error) {
            this.showToast('Failed to clear alerts: ' + error.message, 'error');
        }
    }

    /**
     * Dismiss a specific alert
     */
    async dismissAlert(deviceId, event) {
        if (event) event.stopPropagation();

        try {
            const url = deviceId
                ? `${this.apiBase}/flows/alerts?device_id=${encodeURIComponent(deviceId)}`
                : `${this.apiBase}/flows/alerts`;

            const response = await fetch(url, {
                method: 'DELETE'
            });

            if (!response.ok) throw new Error('Failed to dismiss alert');

            await this.loadAlerts();
        } catch (error) {
            this.showToast('Failed to dismiss alert: ' + error.message, 'error');
        }
    }

    // Default utility methods
    _defaultEscapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    _defaultFormatDateTime(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleString();
    }
}

// ES6 export
export default FlowAlertsUI;

// Global export for backward compatibility
window.FlowAlertsUI = FlowAlertsUI;
