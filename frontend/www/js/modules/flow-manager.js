/**
 * Visual Mapper - Flow Manager Module (Phase 8 Week 4)
 * Client-side API wrapper for Flow System operations
 */

/**
 * Get API base URL with proper handling for HA Ingress
 */
function getApiBase() {
    if (window.API_BASE) return window.API_BASE;
    if (window.opener?.API_BASE) return window.opener.API_BASE;

    const url = window.location.href;
    const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
    if (ingressMatch) return ingressMatch[0] + '/api';

    return '/api';
}

class FlowManager {
    constructor() {
        this.apiBase = getApiBase();
    }

    /**
     * Get all flows (optionally filtered by device)
     * @param {string|null} deviceId - Optional device ID filter
     * @returns {Promise<Array>} List of flows
     */
    async getFlows(deviceId = null) {
        // Add cache-busting parameter to prevent stale data
        const cacheBust = `_=${Date.now()}`;
        const url = deviceId
            ? `${this.apiBase}/flows?device_id=${encodeURIComponent(deviceId)}&${cacheBust}`
            : `${this.apiBase}/flows?${cacheBust}`;

        const response = await fetch(url, {
            cache: 'no-store'  // Disable browser caching
        });
        if (!response.ok) {
            throw new Error(`Failed to fetch flows: ${response.statusText}`);
        }

        const data = await response.json();
        // Server returns direct array, not wrapped in {"flows": [...]}
        return Array.isArray(data) ? data : (data.flows || []);
    }

    /**
     * Get a specific flow
     * @param {string} deviceId - Device ID
     * @param {string} flowId - Flow ID
     * @returns {Promise<Object>} Flow details
     */
    async getFlow(deviceId, flowId) {
        const url = `${this.apiBase}/flows/${encodeURIComponent(deviceId)}/${encodeURIComponent(flowId)}`;

        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Failed to fetch flow: ${response.statusText}`);
        }

        return await response.json();
    }

    /**
     * Create a new flow
     * @param {Object} flowData - Flow configuration
     * @returns {Promise<Object>} Created flow
     */
    async createFlow(flowData) {
        const response = await fetch(`${this.apiBase}/flows`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(flowData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create flow');
        }

        return await response.json();
    }

    /**
     * Update an existing flow
     * @param {string} deviceId - Device ID
     * @param {string} flowId - Flow ID
     * @param {Object} flowData - Updated flow configuration
     * @returns {Promise<Object>} Updated flow
     */
    async updateFlow(deviceId, flowId, flowData) {
        const url = `${this.apiBase}/flows/${encodeURIComponent(deviceId)}/${encodeURIComponent(flowId)}`;

        const response = await fetch(url, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(flowData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update flow');
        }

        return await response.json();
    }

    /**
     * Delete a flow
     * @param {string} deviceId - Device ID
     * @param {string} flowId - Flow ID
     * @returns {Promise<Object>} Deletion result
     */
    async deleteFlow(deviceId, flowId) {
        const url = `${this.apiBase}/flows/${encodeURIComponent(deviceId)}/${encodeURIComponent(flowId)}`;

        const response = await fetch(url, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete flow');
        }

        return await response.json();
    }

    /**
     * Execute a flow on demand
     * @param {string} deviceId - Device ID
     * @param {string} flowId - Flow ID
     * @returns {Promise<Object>} Execution result
     */
    async executeFlow(deviceId, flowId) {
        const url = `${this.apiBase}/flows/${encodeURIComponent(deviceId)}/${encodeURIComponent(flowId)}/execute`;

        const response = await fetch(url, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to execute flow');
        }

        return await response.json();
    }

    /**
     * Get performance metrics
     * @param {string|null} deviceId - Optional device ID filter
     * @returns {Promise<Object>} Performance metrics
     */
    async getMetrics(deviceId = null) {
        const url = deviceId
            ? `${this.apiBase}/flows/metrics?device_id=${encodeURIComponent(deviceId)}`
            : `${this.apiBase}/flows/metrics`;

        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Failed to fetch metrics: ${response.statusText}`);
        }

        return await response.json();
    }
}

// ES6 export
export default FlowManager;

// Global export for backward compatibility
window.FlowManager = FlowManager;
