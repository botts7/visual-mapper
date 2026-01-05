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

const APP_VERSION = '0.0.37';

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
// NOTE: Disabled for existing projects - set localStorage.setItem('onboarding_complete', 'true') to skip
function checkOnboarding() {
    // Don't check if we're already on onboarding page
    const currentPage = window.location.pathname.split('/').pop();
    if (currentPage === 'onboarding.html') {
        return false; // Don't redirect
    }

    // For existing projects, auto-complete onboarding (one-time migration)
    // This allows existing users to continue without seeing onboarding again
    if (!localStorage.getItem('onboarding_complete')) {
        // Check if user has any existing data (devices, sensors, flows configured)
        // For now, just auto-complete to not break existing workflows
        console.log('[Init] Auto-completing onboarding for existing project');
        localStorage.setItem('onboarding_complete', 'true');
    }

    console.log('[Init] Onboarding complete');
    return false; // Not redirecting
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
    if (checkOnboarding()) {
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
