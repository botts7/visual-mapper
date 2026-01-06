/**
 * Visual Mapper - API Client Module
 * Version: 0.0.4 (Phase 3)
 *
 * Handles all API communication with the backend.
 */

class APIClient {
    constructor(baseUrl = null) {
        // Auto-detect API base URL if not provided
        this.baseUrl = baseUrl || this.detectApiBase();
        console.log(`[APIClient] Initialized with base URL: ${this.baseUrl}`);
    }

    /**
     * Detect API base URL for Home Assistant ingress compatibility
     * @returns {string} API base URL
     */
    detectApiBase() {
        // Check if already set globally
        if (window.API_BASE) return window.API_BASE;
        if (window.opener?.API_BASE) return window.opener.API_BASE;

        // Check for Home Assistant ingress path
        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);

        if (ingressMatch) {
            return ingressMatch[0] + '/api';
        }

        // Default to relative path
        return '/api';
    }

    /**
     * Make HTTP request to API
     * @param {string} method - HTTP method (GET, POST, etc.)
     * @param {string} endpoint - API endpoint (without /api prefix)
     * @param {Object} data - Request body data
     * @returns {Promise<Object>} Response data
     */
    async request(method, endpoint, data = null) {
        const url = `${this.baseUrl}${endpoint}`;

        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            }
        };

        if (data) {
            options.body = JSON.stringify(data);
        }

        try {
            console.log(`[APIClient] ${method} ${url}`);

            const response = await fetch(url, options);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorMessage = typeof errorData.detail === 'object'
                    ? JSON.stringify(errorData.detail)
                    : (errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
                throw new Error(errorMessage);
            }

            const responseData = await response.json();
            return responseData;

        } catch (error) {
            console.error(`[APIClient] Request failed:`, error);
            throw error;
        }
    }

    /**
     * GET request
     * @param {string} endpoint - API endpoint
     * @returns {Promise<Object>} Response data
     */
    async get(endpoint) {
        return this.request('GET', endpoint);
    }

    /**
     * POST request
     * @param {string} endpoint - API endpoint
     * @param {Object} data - Request body data
     * @returns {Promise<Object>} Response data
     */
    async post(endpoint, data) {
        return this.request('POST', endpoint, data);
    }

    /**
     * PUT request
     * @param {string} endpoint - API endpoint
     * @param {Object} data - Request body data
     * @returns {Promise<Object>} Response data
     */
    async put(endpoint, data) {
        return this.request('PUT', endpoint, data);
    }

    /**
     * DELETE request
     * @param {string} endpoint - API endpoint
     * @returns {Promise<Object>} Response data
     */
    async delete(endpoint) {
        return this.request('DELETE', endpoint);
    }

    /**
     * Health check
     * @returns {Promise<Object>} Health status
     */
    async health() {
        return this.get('/health');
    }

    /**
     * Connect to Android device
     * @param {string} host - Device IP address
     * @param {number} port - ADB port (default: 5555)
     * @returns {Promise<Object>} Connection result
     */
    async connectDevice(host, port = 5555) {
        return this.post('/adb/connect', { host, port });
    }

    /**
     * Pair with Android 11+ device using wireless pairing
     * @param {string} pairingHost - Device IP address
     * @param {number} pairingPort - Pairing port (shown on device, e.g., 37899)
     * @param {string} pairingCode - 6-digit pairing code
     * @param {number} connectionPort - Connection port (shown on device, e.g., 45441)
     * @returns {Promise<Object>} Pairing result
     */
    async pairDevice(pairingHost, pairingPort, pairingCode, connectionPort) {
        return this.post('/adb/pair', {
            pairing_host: pairingHost,
            pairing_port: pairingPort,
            pairing_code: pairingCode,
            connection_port: connectionPort
        });
    }

    /**
     * Disconnect from Android device
     * @param {string} deviceId - Device identifier (host:port)
     * @returns {Promise<Object>} Disconnection result
     */
    async disconnectDevice(deviceId) {
        return this.post('/adb/disconnect', { device_id: deviceId });
    }

    /**
     * Get list of connected devices
     * @returns {Promise<Object>} Devices list
     */
    async getDevices() {
        return this.get('/adb/devices');
    }

    /**
     * Capture screenshot from device
     * @param {string} deviceId - Device identifier (host:port)
     * @returns {Promise<Object>} Screenshot data
     */
    async captureScreenshot(deviceId) {
        return this.post('/adb/screenshot', { device_id: deviceId });
    }
}

// ES6 export
export default APIClient;

// Global export for non-module usage
window.APIClient = APIClient;
