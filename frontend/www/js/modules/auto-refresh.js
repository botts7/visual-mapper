/**
 * Visual Mapper - Auto-Refresh Module
 * Version: 0.0.3 (Phase 2)
 *
 * Manages automatic screenshot refresh with configurable intervals.
 */

class AutoRefresh {
    constructor(screenshotCapture) {
        this.screenshotCapture = screenshotCapture;
        this.interval = null;
        this.isCapturing = false;
        this.isPaused = false;
        this.resumeTimeout = null;

        console.log('[AutoRefresh] Initialized');
    }

    /**
     * Start auto-refresh with specified interval
     * @param {number} intervalMs - Refresh interval in milliseconds
     * @param {string} deviceId - Device to capture from
     * @param {Function} onCapture - Callback after each capture (success: boolean)
     */
    start(intervalMs, deviceId, onCapture) {
        if (this.interval) {
            console.warn('[AutoRefresh] Already running, stopping first');
            this.stop();
        }

        console.log(`[AutoRefresh] Starting with interval: ${intervalMs}ms`);

        // Capture immediately
        this._captureWrapper(deviceId, onCapture, false);

        // Then start interval
        this.interval = setInterval(() => {
            this._captureWrapper(deviceId, onCapture, false);
        }, intervalMs);
    }

    /**
     * Stop auto-refresh
     */
    stop() {
        if (this.interval) {
            clearInterval(this.interval);
            this.interval = null;
            console.log('[AutoRefresh] Stopped');
        }

        if (this.resumeTimeout) {
            clearTimeout(this.resumeTimeout);
            this.resumeTimeout = null;
        }

        this.isPaused = false;
        this.isCapturing = false;
    }

    /**
     * Pause auto-refresh temporarily (e.g., during user interaction)
     * @param {number} durationMs - Pause duration in milliseconds
     */
    pauseTemporarily(durationMs) {
        if (!this.interval) {
            return; // Not running, nothing to pause
        }

        this.isPaused = true;
        console.log(`[AutoRefresh] Paused for ${durationMs}ms`);

        // Clear any existing resume timeout
        if (this.resumeTimeout) {
            clearTimeout(this.resumeTimeout);
        }

        // Schedule resume
        this.resumeTimeout = setTimeout(() => {
            this.isPaused = false;
            console.log('[AutoRefresh] Resumed after pause');
        }, durationMs);
    }

    /**
     * Trigger immediate capture (ignores pause, cancels in-progress)
     * @param {string} deviceId - Device to capture from
     * @param {Function} onCapture - Callback after capture
     */
    async captureNow(deviceId, onCapture) {
        await this._captureWrapper(deviceId, onCapture, true);
    }

    /**
     * Internal capture wrapper with pause/skip logic
     * @param {string} deviceId - Device ID
     * @param {Function} onCapture - Callback
     * @param {boolean} force - Force capture even if paused
     */
    async _captureWrapper(deviceId, onCapture, force) {
        // Skip if already capturing
        if (this.isCapturing && !force) {
            console.log('[AutoRefresh] Skipping - already in progress');
            return;
        }

        // Skip if paused (unless forced)
        if (this.isPaused && !force) {
            console.log('[AutoRefresh] Skipping - paused');
            return;
        }

        try {
            this.isCapturing = true;
            const result = await this.screenshotCapture.capture(deviceId);

            if (onCapture) {
                onCapture(true, result);
            }
        } catch (error) {
            console.error('[AutoRefresh] Capture failed:', error);

            if (onCapture) {
                onCapture(false, error);
            }
        } finally {
            this.isCapturing = false;
        }
    }

    /**
     * Check if auto-refresh is running
     * @returns {boolean}
     */
    isRunning() {
        return this.interval !== null;
    }

    /**
     * Get current state
     * @returns {Object} State object
     */
    getState() {
        return {
            running: this.isRunning(),
            paused: this.isPaused,
            capturing: this.isCapturing
        };
    }
}

// ES6 export
export default AutoRefresh;

// Global export for non-module usage
window.AutoRefresh = AutoRefresh;
