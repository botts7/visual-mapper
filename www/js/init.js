/**
 * Visual Mapper - Module Initialization
 * Version: 0.0.5 (Phase 4 - MQTT Integration)
 *
 * This file handles:
 * - Version management
 * - Module loading with cache busting
 * - API base detection for HA ingress
 * - Global initialization
 */

const APP_VERSION = '0.0.5';

// API Base Detection (for Home Assistant ingress)
function getApiBase() {
    // Check if already set
    if (window.API_BASE) return window.API_BASE;

    // Check parent/opener window
    if (window.opener?.API_BASE) return window.opener.API_BASE;

    // Extract from current URL for HA ingress
    const url = window.location.href;
    const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
    if (ingressMatch) {
        return ingressMatch[0] + '/api';
    }

    // Fallback to relative path
    return '/api';
}

// Set global API base
window.API_BASE = getApiBase();
window.APP_VERSION = APP_VERSION;

// Log initialization
console.log(`[Init] Visual Mapper v${APP_VERSION}`);
console.log(`[Init] API Base: ${window.API_BASE}`);

// Modules to load (Phase 0: none yet, this is the framework)
const MODULES = [
    // Phase 1 will add: 'modules/api-client.js',
    // Phase 1 will add: 'modules/screenshot-capture.js',
    // etc.
];

/**
 * Initialize application
 * Phase 0: Just log that we're ready
 * Future phases: Load and initialize modules
 */
async function initApp() {
    console.log('[Init] Starting initialization');

    const startTime = performance.now();

    // Load all modules (when we have them)
    for (const modulePath of MODULES) {
        try {
            await import(`./${modulePath}?v=${APP_VERSION}`);
            console.log(`[Init] ✅ Loaded ${modulePath}`);
        } catch (error) {
            console.error(`[Init] ❌ Failed to load ${modulePath}:`, error);
        }
    }

    const loadTime = performance.now() - startTime;
    console.log(`[Init] Initialization complete in ${loadTime.toFixed(2)}ms`);

    // Dispatch ready event
    window.dispatchEvent(new Event('visualmapper:ready'));
}

// Start when DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
