/**
 * Device Unlock Module
 * Visual Mapper v0.0.4
 *
 * Consolidates device wake/unlock logic and keep-awake functionality.
 * Used by flow-recorder.js and flow-wizard-step3.js.
 *
 * v0.0.4: Added 30s debounce to prevent duplicate unlock calls, removed redundant fallback
 * v0.0.3: Fixed timing - reduced interval to 5s, made startKeepAwake async, await first signal
 * v0.0.2: Fixed unlock order - try swipe first (like scheduler), then passcode
 */

import { showToast } from './toast.js?v=0.4.0-beta.3.13';

// Configuration
const DEFAULT_KEEP_AWAKE_INTERVAL = 5000; // 5 seconds (safer margin for 15-30s Android timeout)
const UNLOCK_DEBOUNCE_MS = 30000; // Skip unlock if done within last 30 seconds

// Track last successful unlock time per device to prevent duplicate calls
const lastUnlockTime = new Map();

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
 * @param {number} interval - Interval in ms (default: 5000)
 * @returns {Promise<number>} Interval ID for stopping later
 */
async function startKeepAwake(deviceId, apiBase, interval = DEFAULT_KEEP_AWAKE_INTERVAL) {
    console.log(`[DeviceUnlock] Starting keep-awake (${interval}ms interval)`);

    // AWAIT first wake signal to ensure it completes before continuing
    await sendWakeSignal(deviceId, apiBase);
    console.log('[DeviceUnlock] First wake signal sent, starting interval');

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
 * Show a prominent cooldown banner when device is in lockout protection mode
 * @param {number} remainingSeconds - Seconds remaining in cooldown
 */
function showCooldownBanner(remainingSeconds) {
    // Remove any existing banner
    const existingBanner = document.getElementById('cooldownBanner');
    if (existingBanner) existingBanner.remove();

    const remainingMins = Math.ceil(remainingSeconds / 60);

    const banner = document.createElement('div');
    banner.id = 'cooldownBanner';
    banner.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 10000;
        background: linear-gradient(135deg, #fef2f2, #fee2e2);
        border-bottom: 3px solid #ef4444;
        padding: 16px 20px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    `;

    banner.innerHTML = `
        <span style="font-size: 2em;">🔒</span>
        <div style="text-align: left;">
            <strong style="color: #dc2626; font-size: 1.1em;">Device Unlock Cooldown Active</strong>
            <p style="margin: 4px 0 0 0; color: #b91c1c; font-size: 0.95em;">
                To prevent device lockout, auto-unlock is paused for <strong>${remainingMins} minute(s)</strong>.
                Please <strong>unlock the device manually</strong> to continue.
            </p>
        </div>
        <button id="btnDismissCooldown" style="
            background: #dc2626;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
        ">Dismiss</button>
    `;

    document.body.prepend(banner);

    // Wire up dismiss button
    document.getElementById('btnDismissCooldown').addEventListener('click', () => {
        banner.remove();
    });

    // Auto-dismiss after cooldown expires
    setTimeout(() => {
        if (document.getElementById('cooldownBanner')) {
            banner.remove();
        }
    }, remainingSeconds * 1000);

    console.log(`[DeviceUnlock] Cooldown banner shown (${remainingMins} min remaining)`);
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

    // DEBOUNCE: Skip if this device was unlocked recently (within 30 seconds)
    const lastUnlock = lastUnlockTime.get(deviceId);
    if (lastUnlock && (Date.now() - lastUnlock) < UNLOCK_DEBOUNCE_MS) {
        const secondsAgo = Math.round((Date.now() - lastUnlock) / 1000);
        console.log(`[DeviceUnlock] Skipping - device was unlocked ${secondsAgo}s ago (debounce: ${UNLOCK_DEBOUNCE_MS/1000}s)`);
        onStepUpdate('step-screen', 'skip');
        onStepUpdate('step-wake', 'skip');
        onStepUpdate('step-unlock', 'skip');
        return { success: true, status: 'debounced' };
    }

    try {
        // FIRST: Check if device is in unlock cooldown (lockout protection)
        try {
            const cooldownResponse = await fetch(`${apiBase}/device/${encodeURIComponent(deviceId)}/unlock-status`);
            if (cooldownResponse.ok) {
                const cooldownStatus = await cooldownResponse.json();

                if (cooldownStatus.in_cooldown) {
                    const remainingMins = Math.ceil(cooldownStatus.cooldown_remaining_seconds / 60);
                    const message = `Device unlock blocked - in cooldown for ${remainingMins} minute(s) to prevent lockout. Please unlock manually.`;
                    updateStatus(message);
                    showToast(`⚠️ Cooldown Active: ${message}`, 'warning', 8000);

                    // Show prominent banner if possible
                    showCooldownBanner(cooldownStatus.cooldown_remaining_seconds);

                    onStepUpdate('step-screen', 'fail');
                    onStepUpdate('step-wake', 'skip');
                    onStepUpdate('step-unlock', 'fail');

                    return {
                        success: false,
                        status: 'cooldown',
                        cooldownSeconds: cooldownStatus.cooldown_remaining_seconds,
                        message: message
                    };
                }

                if (cooldownStatus.failure_count > 0) {
                    const remaining = cooldownStatus.max_attempts - cooldownStatus.failure_count;
                    showToast(`⚠️ Previous unlock attempts failed. ${remaining} attempts remaining before cooldown.`, 'warning', 5000);
                }
            }
        } catch (e) {
            console.debug('[DeviceUnlock] Could not check cooldown status (non-critical):', e);
        }

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
            // Record as "unlocked" to prevent redundant checks
            lastUnlockTime.set(deviceId, Date.now());
            return { success: true, status: 'unlocked' };
        }

        onStepUpdate('step-unlock', 'working');
        updateStatus('Unlocking device...');

        // Single call to auto-unlock endpoint - handles swipe + passcode in one request
        // This mirrors the flow scheduler's approach (swipe first, then passcode if needed)
        // NO FALLBACK - the endpoint already does everything needed
        let unlockSuccess = false;
        try {
            const unlockResponse = await fetch(`${apiBase}/device/${encodeURIComponent(deviceId)}/auto-unlock`, {
                method: 'POST'
            });

            if (unlockResponse.ok) {
                const result = await unlockResponse.json();
                console.log('[DeviceUnlock] Auto-unlock result:', result);
                unlockSuccess = result.success;
            }
        } catch (e) {
            console.debug('[DeviceUnlock] Auto-unlock error:', e);
        }

        if (isCancelled()) return { success: false, status: 'cancelled' };

        if (unlockSuccess) {
            // VERIFY: Check lock status again to confirm device is actually unlocked
            await wait(500); // Give device time to update state
            let actuallyUnlocked = true;

            try {
                const verifyResponse = await fetch(`${apiBase}/adb/lock-status/${encodeURIComponent(deviceId)}`);
                if (verifyResponse.ok) {
                    const verifyState = await verifyResponse.json();
                    if (verifyState.is_locked) {
                        console.log('[DeviceUnlock] Verification failed - device still locked after unlock');
                        actuallyUnlocked = false;

                        // Retry unlock once with longer wait
                        onStepUpdate('step-unlock', 'working');
                        updateStatus('Retrying unlock...');
                        await wait(500);

                        const retryResponse = await fetch(`${apiBase}/device/${encodeURIComponent(deviceId)}/auto-unlock`, {
                            method: 'POST'
                        });

                        if (retryResponse.ok) {
                            const retryResult = await retryResponse.json();
                            await wait(700); // Longer wait after retry

                            // Verify again
                            const reVerifyResponse = await fetch(`${apiBase}/adb/lock-status/${encodeURIComponent(deviceId)}`);
                            if (reVerifyResponse.ok) {
                                const reVerifyState = await reVerifyResponse.json();
                                actuallyUnlocked = !reVerifyState.is_locked;
                                console.log(`[DeviceUnlock] Retry verification: ${actuallyUnlocked ? 'success' : 'still locked'}`);
                            } else {
                                actuallyUnlocked = retryResult.success;
                            }
                        }
                    }
                }
            } catch (e) {
                console.debug('[DeviceUnlock] Verification check failed (non-critical):', e);
                // Trust the original unlock result if verification fails
            }

            if (actuallyUnlocked) {
                updateStatus('Device unlocked!');
                onStepUpdate('step-unlock', 'done');
                showToast('Device unlocked', 'success', 2000);
                // Record successful unlock to prevent duplicate unlock calls
                lastUnlockTime.set(deviceId, Date.now());
                await wait(300);
                return { success: true, status: 'unlocked' };
            }
            // If still locked after retry, fall through to manual unlock section below
            console.log('[DeviceUnlock] Device still locked after retry - needs manual intervention');
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
    showCooldownBanner,
    DEFAULT_KEEP_AWAKE_INTERVAL
};

// Global exports for non-module usage
window.DeviceUnlock = {
    ensureDeviceUnlocked,
    startKeepAwake,
    stopKeepAwake,
    sendWakeSignal,
    showCooldownBanner,
    DEFAULT_KEEP_AWAKE_INTERVAL
};

export default {
    ensureDeviceUnlocked,
    startKeepAwake,
    stopKeepAwake,
    sendWakeSignal,
    showCooldownBanner,
    DEFAULT_KEEP_AWAKE_INTERVAL
};
