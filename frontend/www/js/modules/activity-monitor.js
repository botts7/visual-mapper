/**
 * Visual Mapper - Activity Monitor Module
 * Version: 0.0.9 (Phase 2)
 *
 * Monitors Android device for activity/page changes and triggers callbacks.
 * Includes smart refresh mode with automatic retry logic.
 */

class ActivityMonitor {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.interval = null;
        this.lastActivity = '';
        this.deviceId = null;
        this.captureCallback = null; // For smart refresh

        console.log('[ActivityMonitor] Initialized');
    }

    /**
     * Start monitoring device for activity changes
     * @param {string} deviceId - Device to monitor
     * @param {Function} onChange - Callback when activity changes (oldActivity, newActivity)
     * @param {number} pollIntervalMs - Polling interval (default: 2000ms)
     */
    async start(deviceId, onChange, pollIntervalMs = 2000) {
        if (this.interval) {
            console.warn('[ActivityMonitor] Already running, stopping first');
            this.stop();
        }

        this.deviceId = deviceId;

        // Get initial activity
        try {
            const response = await this.apiClient.get(`/adb/activity/${deviceId}`);
            this.lastActivity = response.activity || '';
            console.log(`[ActivityMonitor] Initial activity: ${this.lastActivity}`);
        } catch (error) {
            console.error('[ActivityMonitor] Failed to get initial activity:', error);
            this.lastActivity = '';
        }

        // Start polling
        this.interval = setInterval(async () => {
            await this._checkActivity(onChange);
        }, pollIntervalMs);

        console.log(`[ActivityMonitor] Started monitoring ${deviceId} (polling every ${pollIntervalMs}ms)`);
    }

    /**
     * Stop monitoring
     */
    stop() {
        if (this.interval) {
            clearInterval(this.interval);
            this.interval = null;
            console.log('[ActivityMonitor] Stopped');
        }

        this.lastActivity = '';
        this.deviceId = null;
    }

    /**
     * Internal method to check for activity changes
     * @param {Function} onChange - Callback function
     */
    async _checkActivity(onChange) {
        if (!this.deviceId) {
            return;
        }

        try {
            const response = await this.apiClient.get(`/adb/activity/${this.deviceId}`);
            const currentActivity = response.activity || '';

            // If activity changed, trigger callback
            if (currentActivity && currentActivity !== this.lastActivity) {
                console.log(`[ActivityMonitor] Page changed: ${this.lastActivity} → ${currentActivity}`);

                const oldActivity = this.lastActivity;
                this.lastActivity = currentActivity;

                if (onChange) {
                    onChange(oldActivity, currentActivity);
                }
            }
        } catch (error) {
            // Silently fail - don't spam console
        }
    }

    /**
     * Check if monitor is running
     * @returns {boolean}
     */
    isRunning() {
        return this.interval !== null;
    }

    /**
     * Start smart refresh mode (auto-capture on page change with retry)
     * @param {string} deviceId - Device to monitor
     * @param {Function} captureFunc - Async function to capture screenshot
     * @param {Function} onSuccess - Callback on successful capture (elementCount, timestamp)
     * @param {number} pollIntervalMs - Polling interval (default: 2000ms)
     */
    async startSmartRefresh(deviceId, captureFunc, onSuccess, pollIntervalMs = 2000) {
        this.captureCallback = captureFunc;

        await this.start(deviceId, async (oldActivity, newActivity) => {
            console.log(`[ActivityMonitor] Smart refresh triggered: ${oldActivity} → ${newActivity}`);

            // Wait 500ms for UI to stabilize
            await new Promise(resolve => setTimeout(resolve, 500));

            // First capture attempt
            try {
                const result = await captureFunc(deviceId);
                if (onSuccess) {
                    onSuccess(result.elements.length, new Date().toLocaleTimeString());
                }
                console.log('[ActivityMonitor] Smart refresh successful');
            } catch (error) {
                // First attempt failed, retry after 500ms
                console.warn('[ActivityMonitor] First capture failed, retrying in 500ms...', error);
                await new Promise(resolve => setTimeout(resolve, 500));

                try {
                    const result = await captureFunc(deviceId);
                    if (onSuccess) {
                        onSuccess(result.elements.length, new Date().toLocaleTimeString());
                    }
                    console.log('[ActivityMonitor] Smart refresh retry successful');
                } catch (retryError) {
                    console.warn('[ActivityMonitor] Retry failed, will capture on next poll', retryError);
                }
            }
        }, pollIntervalMs);

        console.log('[ActivityMonitor] Smart refresh mode enabled');
    }

    /**
     * Get current state
     * @returns {Object} State object
     */
    getState() {
        return {
            running: this.isRunning(),
            deviceId: this.deviceId,
            lastActivity: this.lastActivity,
            smartRefresh: this.captureCallback !== null
        };
    }
}

// ES6 export
export default ActivityMonitor;

// Global export for non-module usage
window.ActivityMonitor = ActivityMonitor;
