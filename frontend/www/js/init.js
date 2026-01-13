/**
 * Visual Mapper - Module Initialization
 * Version: 0.0.7 (Navigation Learning + Bug Fixes)
 *
 * This file handles:
 * - Version management
 * - Module loading with cache busting
 * - API base detection for HA ingress
 * - Global initialization
 */

const APP_VERSION = '0.2.95';

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

// Onboarding check - redirect to onboarding.html if not completed
// To reset onboarding for testing: localStorage.removeItem('onboarding_complete')
async function checkOnboarding() {
    // Don't check if we're already on onboarding page
    const currentPage = window.location.pathname.split('/').pop();
    if (currentPage === 'onboarding.html') {
        return false; // Don't redirect
    }

    // If onboarding already marked complete, skip
    if (localStorage.getItem('onboarding_complete') === 'true') {
        console.log('[Init] Onboarding already complete');
        return false;
    }

    // Check if there are existing devices (indicates existing user)
    try {
        const response = await fetch(`${window.API_BASE}/devices`, {
            method: 'GET',
            cache: 'no-store'
        });
        if (response.ok) {
            const data = await response.json();
            const devices = data.devices || data || [];
            if (Array.isArray(devices) && devices.length > 0) {
                // Existing user with devices - auto-complete onboarding
                console.log(`[Init] Found ${devices.length} existing device(s), auto-completing onboarding`);
                localStorage.setItem('onboarding_complete', 'true');
                return false;
            }
        }
    } catch (e) {
        console.log('[Init] Could not check for existing devices:', e.message);
        // On error, don't redirect - let user use the app normally
        return false;
    }

    // No devices found and onboarding not complete - redirect to onboarding
    console.log('[Init] New user detected, redirecting to onboarding');
    window.location.href = 'onboarding.html';
    return true; // Redirecting
}

// Modules to load
const MODULES = [
    'components/navbar.js',  // Shared navigation bar
    // Future: 'modules/api-client.js',
    // Future: 'modules/screenshot-capture.js',
];

/**
 * Initialize application
 * Phase 0: Just log that we're ready
 * Future phases: Load and initialize modules
 */
async function initApp() {
    console.log('[Init] Starting initialization');

    // Check onboarding status and redirect if needed
    if (await checkOnboarding()) {
        return; // Redirecting to onboarding, stop initialization
    }

    const startTime = performance.now();

    // Load all modules
    for (const modulePath of MODULES) {
        try {
            const module = await import(`./${modulePath}?v=${APP_VERSION}`);
            console.log(`[Init] ✅ Loaded ${modulePath}`);

            // Initialize navbar if it was loaded
            if (modulePath.includes('navbar') && module.default) {
                module.default.inject();
            }
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

// Global exports for backward compatibility (when loaded as regular script)
window.initApp = initApp;
window.getApiBase = getApiBase;
