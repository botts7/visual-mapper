/**
 * Device Unlock Module
 * Visual Mapper v0.0.1
 *
 * Consolidates device wake/unlock logic and keep-awake functionality.
 * Used by flow-recorder.js and flow-wizard-step3.js.
 */

import { showToast } from './toast.js?v=0.0.5';

// Configuration
const DEFAULT_KEEP_AWAKE_INTERVAL = 12000; // 12 seconds (safe for 15-30s Android timeout)

/**
 * Send wake signal to device
 * @param {string} deviceId - Device identifier
 * @param {string} apiBase - API base URL
 */
async function sendWakeSignal(deviceId, apiBase) {
    try {
        await fetch(`${apiBase}/adb/keyevent`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: deviceId, keycode: 224 })  // KEYCODE_WAKEUP
        });
    } catch (e) {
        // Silently ignore errors - non-critical operation
        console.debug('[DeviceUnlock] Wake signal failed (non-critical):', e);
    }
}

/**
 * Start keep-awake interval to prevent screen timeout
 * @param {string} deviceId - Device identifier
 * @param {string} apiBase - API base URL
 * @param {number} interval - Interval in ms (default: 12000)
 * @returns {number} Interval ID for stopping later
 */
function startKeepAwake(deviceId, apiBase, interval = DEFAULT_KEEP_AWAKE_INTERVAL) {
    console.log(`[DeviceUnlock] Starting keep-awake (${interval}ms interval)`);

    // Send immediate wake signal
    sendWakeSignal(deviceId, apiBase);

    return setInterval(async () => {
        await sendWakeSignal(deviceId, apiBase);
    }, interval);
}

/**
 * Stop keep-awake interval
 * @param {number} intervalId - ID returned from startKeepAwake
 */
function stopKeepAwake(intervalId) {
    if (intervalId) {
        clearInterval(intervalId);
        console.log('[DeviceUnlock] Keep-awake stopped');
    }
}

/**
 * Helper to wait for specified duration
 * @param {number} ms - Milliseconds to wait
 */
function wait(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Check and unlock device if needed
 * Supports both simple callback and wizard-style step updates
 *
 * @param {string} deviceId - Device identifier
 * @param {string} apiBase - API base URL
 * @param {Object} callbacks - Optional callbacks for UI updates
 * @param {Function} callbacks.onStatus - Called with status messages (msg: string)
 * @param {Function} callbacks.onStepUpdate - Called with (stepName: string, status: string) for wizard UI
 * @param {Function} callbacks.onNeedsManualUnlock - Called when manual unlock required, should return Promise
 * @param {Function} callbacks.isCancelled - Returns true if operation should abort
 * @returns {Promise<{success: boolean, status: string, needsManualUnlock?: boolean}>}
 */
async function ensureDeviceUnlocked(deviceId, apiBase, callbacks = {}) {
    const {
        onStatus = () => {},
        onStepUpdate = () => {},
        onNeedsManualUnlock = null,
        isCancelled = () => false
    } = callbacks;

    const updateStatus = (msg) => {
        console.log(`[DeviceUnlock] ${msg}`);
        onStatus(msg);
    };

    try {
        // Step 1: Check screen and lock state
        onStepUpdate('step-screen', 'working');
        updateStatus('Checking device state...');

        // Send wake signal to ensure screen is responsive during check
        await sendWakeSignal(deviceId, apiBase);

        const lockResponse = await fetch(`${apiBase}/adb/lock-status/${encodeURIComponent(deviceId)}`);

        if (isCancelled()) return { success: false, status: 'cancelled' };

        if (!lockResponse.ok) {
            console.warn('[DeviceUnlock] Could not check lock status');
            onStepUpdate('step-screen', 'skip');
            onStepUpdate('step-wake', 'skip');
            onStepUpdate('step-unlock', 'skip');
            return { success: true, status: 'unknown' }; // Continue anyway
        }

        const lockState = await lockResponse.json();
        console.log('[DeviceUnlock] Lock state:', lockState);
        onStepUpdate('step-screen', 'done');

        if (isCancelled()) return { success: false, status: 'cancelled' };

        // Step 2: Wake screen if needed
        if (!lockState.screen_on) {
            onStepUpdate('step-wake', 'working');
            updateStatus('Waking screen...');
            await fetch(`${apiBase}/adb/wake/${encodeURIComponent(deviceId)}`, { method: 'POST' });
            await wait(500);
            onStepUpdate('step-wake', 'done');
        } else {
            onStepUpdate('step-wake', 'skip');
        }

        if (isCancelled()) return { success: false, status: 'cancelled' };

        // Step 3: Unlock if needed
        if (!lockState.is_locked) {
            updateStatus('Device ready!');
            onStepUpdate('step-unlock', 'skip');
            return { success: true, status: 'unlocked' };
        }

        onStepUpdate('step-unlock', 'working');
        updateStatus('Device is locked, attempting unlock...');
        showToast('Unlocking device...', 'info', 3000);

        // Send wake signal before unlock attempt
        await sendWakeSignal(deviceId, apiBase);

        // Try auto-unlock first (if configured with stored passcode)
        const securityResponse = await fetch(`${apiBase}/device/${encodeURIComponent(deviceId)}/security`);

        if (isCancelled()) return { success: false, status: 'cancelled' };

        let unlockSuccess = false;

        if (securityResponse.ok) {
            const securityConfig = await securityResponse.json();
            console.log('[DeviceUnlock] Security config:', securityConfig.config?.strategy);

            if (securityConfig.config?.strategy === 'auto_unlock' && securityConfig.config?.has_passcode) {
                updateStatus('Using stored passcode...');

                // Send wake signal before entering passcode
                await sendWakeSignal(deviceId, apiBase);

                const unlockResponse = await fetch(`${apiBase}/device/${encodeURIComponent(deviceId)}/auto-unlock`, {
                    method: 'POST'
                });

                if (unlockResponse.ok) {
                    const result = await unlockResponse.json();
                    unlockSuccess = result.success;

                    if (!unlockSuccess && result.message) {
                        console.warn('[DeviceUnlock] Auto-unlock failed:', result.message);
                    }
                }
            }
        }

        if (isCancelled()) return { success: false, status: 'cancelled' };

        // Fallback: Try swipe unlock
        if (!unlockSuccess) {
            updateStatus('Trying swipe unlock...');

            // Send wake signal before swipe
            await sendWakeSignal(deviceId, apiBase);

            const swipeResponse = await fetch(`${apiBase}/adb/unlock/${encodeURIComponent(deviceId)}`, {
                method: 'POST'
            });

            if (swipeResponse.ok) {
                const result = await swipeResponse.json();
                unlockSuccess = result.success;
            }
        }

        if (isCancelled()) return { success: false, status: 'cancelled' };

        if (unlockSuccess) {
            updateStatus('Device unlocked!');
            onStepUpdate('step-unlock', 'done');
            showToast('Device unlocked', 'success', 2000);
            await wait(300);
            return { success: true, status: 'unlocked' };
        }

        // Unlock failed - needs manual intervention
        updateStatus('Please unlock device manually');
        onStepUpdate('step-unlock', 'fail');
        showToast('Please unlock device manually to continue', 'warning', 4000);

        // If caller provided manual unlock handler, call it
        if (onNeedsManualUnlock) {
            await onNeedsManualUnlock();
        }

        return { success: false, status: 'locked', needsManualUnlock: true };

    } catch (error) {
        console.warn('[DeviceUnlock] Error checking/unlocking device:', error);
        onStepUpdate('step-screen', 'skip');
        onStepUpdate('step-wake', 'skip');
        onStepUpdate('step-unlock', 'skip');
        return { success: true, status: 'error' }; // Continue anyway
    }
}

// ES6 exports
export {
    ensureDeviceUnlocked,
    startKeepAwake,
    stopKeepAwake,
    sendWakeSignal,
    DEFAULT_KEEP_AWAKE_INTERVAL
};

// Global exports for non-module usage
window.DeviceUnlock = {
    ensureDeviceUnlocked,
    startKeepAwake,
    stopKeepAwake,
    sendWakeSignal,
    DEFAULT_KEEP_AWAKE_INTERVAL
};

export default {
    ensureDeviceUnlocked,
    startKeepAwake,
    stopKeepAwake,
    sendWakeSignal,
    DEFAULT_KEEP_AWAKE_INTERVAL
};
