/**
 * Visual Mapper - Device Manager Module
 * Version: 0.0.3 (Phase 2)
 *
 * Manages device connection, discovery, and selection.
 */

class DeviceManager {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.devices = [];
        this.selectedDevice = null;

        console.log('[DeviceManager] Initialized');
    }

    /**
     * Load/discover all connected devices
     * @returns {Promise<Array>} List of devices
     */
    async loadDevices() {
        try {
            const response = await this.apiClient.get('/adb/devices');
            this.devices = response.devices || [];
            console.log(`[DeviceManager] Loaded ${this.devices.length} devices`);
            return this.devices;
        } catch (error) {
            console.error('[DeviceManager] Failed to load devices:', error);
            this.devices = [];
            throw error;
        }
    }

    /**
     * Connect to device via TCP/IP
     * @param {string} host - Device IP
     * @param {number} port - ADB port (default: 5555)
     * @returns {Promise<string>} Device ID
     */
    async connect(host, port = 5555) {
        try {
            console.log(`[DeviceManager] Connecting to ${host}:${port}`);
            const response = await this.apiClient.post('/adb/connect', { host, port });

            // Reload devices
            await this.loadDevices();

            return response.device_id;
        } catch (error) {
            console.error('[DeviceManager] Connection failed:', error);
            throw error;
        }
    }

    /**
     * Pair with Android 11+ device
     * @param {string} host - Device IP
     * @param {number} port - Pairing port
     * @param {string} code - 6-digit pairing code
     * @returns {Promise<boolean>} Success
     */
    async pair(host, port, code) {
        try {
            console.log(`[DeviceManager] Pairing with ${host}:${port}`);
            const response = await this.apiClient.post('/adb/pair', {
                pairing_host: host,
                pairing_port: port,
                pairing_code: code
            });

            return response.success || false;
        } catch (error) {
            console.error('[DeviceManager] Pairing failed:', error);
            throw error;
        }
    }

    /**
     * Disconnect from device
     * @param {string} deviceId - Device to disconnect
     */
    async disconnect(deviceId) {
        try {
            console.log(`[DeviceManager] Disconnecting ${deviceId}`);
            await this.apiClient.post('/adb/disconnect', { device_id: deviceId });

            // Reload devices
            await this.loadDevices();

            // Clear selection if this was the selected device
            if (this.selectedDevice === deviceId) {
                this.selectedDevice = null;
            }
        } catch (error) {
            console.error('[DeviceManager] Disconnect failed:', error);
            throw error;
        }
    }

    /**
     * Set selected device
     * @param {string} deviceId - Device ID
     */
    setSelectedDevice(deviceId) {
        this.selectedDevice = deviceId;
        console.log(`[DeviceManager] Selected device: ${deviceId}`);
    }

    /**
     * Get selected device ID
     * @returns {string|null}
     */
    getSelectedDevice() {
        return this.selectedDevice;
    }

    /**
     * Get all devices
     * @returns {Array}
     */
    getDevices() {
        return this.devices;
    }

    /**
     * Get device by ID
     * @param {string} deviceId - Device ID
     * @returns {Object|null}
     */
    getDevice(deviceId) {
        return this.devices.find(d => d.id === deviceId) || null;
    }

    /**
     * Check if device exists
     * @param {string} deviceId - Device ID
     * @returns {boolean}
     */
    hasDevice(deviceId) {
        return this.devices.some(d => d.id === deviceId);
    }
}

// ES6 export
export default DeviceManager;

// Global export for non-module usage
window.DeviceManager = DeviceManager;
