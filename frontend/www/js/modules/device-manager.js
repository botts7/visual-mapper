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

            // Trigger background prefetch for app icons and names
            if (response.device_id) {
                this.prefetchAppData(response.device_id);
            }

            return response.device_id;
        } catch (error) {
            console.error('[DeviceManager] Connection failed:', error);
            throw error;
        }
    }

    /**
     * Prefetch app icons and names in background for a device
     * Improves UX by caching data before user needs it
     * @param {string} deviceId - Device ID to prefetch for
     */
    async prefetchAppData(deviceId) {
        console.log(`[DeviceManager] Starting background prefetch for ${deviceId}`);

        try {
            // Prefetch app names (faster, from Play Store)
            fetch(`${this.apiClient.baseUrl}/adb/prefetch-app-names/${encodeURIComponent(deviceId)}`, {
                method: 'POST'
            }).then(resp => {
                if (resp.ok) console.log(`[DeviceManager] App names prefetch queued for ${deviceId}`);
            }).catch(err => console.warn('[DeviceManager] App names prefetch failed:', err));

            // Prefetch app icons (slower, may extract from APKs)
            fetch(`${this.apiClient.baseUrl}/adb/prefetch-icons/${encodeURIComponent(deviceId)}`, {
                method: 'POST'
            }).then(resp => {
                if (resp.ok) console.log(`[DeviceManager] App icons prefetch queued for ${deviceId}`);
            }).catch(err => console.warn('[DeviceManager] App icons prefetch failed:', err));

        } catch (error) {
            console.warn('[DeviceManager] Prefetch failed (non-critical):', error);
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

    /**
     * Get device identity information including stable device ID
     * @param {string} deviceId - Device ID (connection or stable)
     * @returns {Promise<Object>} Device identity info
     */
    async getDeviceIdentity(deviceId) {
        try {
            const response = await this.apiClient.get(`/adb/identity/${encodeURIComponent(deviceId)}`);
            return response;
        } catch (error) {
            console.error('[DeviceManager] Failed to get device identity:', error);
            return null;
        }
    }

    /**
     * Resolve a connection ID to a stable device ID
     * @param {string} connectionId - Device connection ID (e.g., 192.168.1.2:46747)
     * @returns {Promise<string>} Stable device ID (e.g., R9YT50J4S9D) or original ID if resolution fails
     */
    async getStableDeviceId(connectionId) {
        try {
            const identity = await this.getDeviceIdentity(connectionId);
            if (identity && identity.stable_device_id) {
                console.log(`[DeviceManager] Resolved ${connectionId} -> ${identity.stable_device_id}`);
                return identity.stable_device_id;
            }
            return connectionId;
        } catch (error) {
            console.warn('[DeviceManager] Could not resolve stable ID, using connection ID:', error);
            return connectionId;
        }
    }

    /**
     * Get all known devices with stable identifiers
     * @returns {Promise<Array>} List of known devices
     */
    async getKnownDevices() {
        try {
            const response = await this.apiClient.get('/adb/devices');
            return response.devices || [];
        } catch (error) {
            console.error('[DeviceManager] Failed to get known devices:', error);
            return [];
        }
    }

    /**
     * Get display name for device (prefers stable ID with model info)
     * @param {string} deviceId - Device ID
     * @returns {Promise<string>} Display-friendly device name
     */
    async getDeviceDisplayName(deviceId) {
        try {
            const identity = await this.getDeviceIdentity(deviceId);
            if (identity) {
                const parts = [];

                // Show model if available
                if (identity.model) {
                    parts.push(identity.model);
                }

                // Show stable ID (hardware serial)
                if (identity.stable_device_id && identity.stable_device_id !== deviceId) {
                    parts.push(`[${identity.stable_device_id}]`);
                } else {
                    parts.push(`[${deviceId}]`);
                }

                return parts.join(' ');
            }
            return deviceId;
        } catch (error) {
            return deviceId;
        }
    }

    /**
     * Format device info for UI display
     * @param {Object} device - Device object
     * @param {Object} identity - Identity info (optional)
     * @returns {Object} Formatted device info
     */
    formatDeviceForDisplay(device, identity = null) {
        return {
            id: device.id || device.device_id,
            stableId: identity?.stable_device_id || device.stable_device_id || device.id,
            displayName: identity?.model
                ? `${identity.model} [${identity.stable_device_id || device.id}]`
                : device.id,
            model: identity?.model || device.model || 'Unknown',
            manufacturer: identity?.manufacturer || device.manufacturer || 'Unknown',
            isConnected: identity?.is_connected ?? true,
            connectionId: identity?.current_connection || device.id
        };
    }
}

// ES6 export
export default DeviceManager;

// Global export for non-module usage
window.DeviceManager = DeviceManager;
