/**
 * Debug Utility Module
 * Visual Mapper v0.4.0-beta.3
 *
 * Provides controlled logging to reduce console spam in production.
 * Set window.VM_DEBUG = true to enable verbose logging.
 *
 * Usage:
 *   import { debug, debugWarn, debugError } from './debug.js';
 *   debug('[Module]', 'message', data);  // Only logs if VM_DEBUG is true
 *   debugWarn('[Module]', 'warning');    // Always logs warnings
 *   debugError('[Module]', 'error');     // Always logs errors
 */

// Check if debug mode is enabled (can be set in localStorage or window)
function isDebugEnabled() {
    if (typeof window !== 'undefined') {
        // Check window flag first (for runtime toggling)
        if (window.VM_DEBUG !== undefined) {
            return window.VM_DEBUG;
        }
        // Check localStorage for persistence
        try {
            return localStorage.getItem('VM_DEBUG') === 'true';
        } catch (e) {
            return false;
        }
    }
    return false;
}

/**
 * Debug log - only outputs when VM_DEBUG is enabled
 * @param {...any} args - Arguments to log
 */
export function debug(...args) {
    if (isDebugEnabled()) {
        console.log(...args);
    }
}

/**
 * Debug warn - always outputs (warnings are important)
 * @param {...any} args - Arguments to log
 */
export function debugWarn(...args) {
    console.warn(...args);
}

/**
 * Debug error - always outputs (errors are critical)
 * @param {...any} args - Arguments to log
 */
export function debugError(...args) {
    console.error(...args);
}

/**
 * Enable debug mode
 */
export function enableDebug() {
    if (typeof window !== 'undefined') {
        window.VM_DEBUG = true;
        try {
            localStorage.setItem('VM_DEBUG', 'true');
        } catch (e) {
            // Ignore localStorage errors
        }
        console.log('[Debug] Debug mode ENABLED - verbose logging active');
    }
}

/**
 * Disable debug mode
 */
export function disableDebug() {
    if (typeof window !== 'undefined') {
        window.VM_DEBUG = false;
        try {
            localStorage.setItem('VM_DEBUG', 'false');
        } catch (e) {
            // Ignore localStorage errors
        }
        console.log('[Debug] Debug mode DISABLED - only warnings/errors will be logged');
    }
}

/**
 * Toggle debug mode
 */
export function toggleDebug() {
    if (isDebugEnabled()) {
        disableDebug();
    } else {
        enableDebug();
    }
}

// Expose toggle functions globally for console access
if (typeof window !== 'undefined') {
    window.vmDebug = {
        enable: enableDebug,
        disable: disableDebug,
        toggle: toggleDebug,
        isEnabled: isDebugEnabled
    };
}

export default {
    debug,
    debugWarn,
    debugError,
    enableDebug,
    disableDebug,
    toggleDebug,
    isDebugEnabled
};
