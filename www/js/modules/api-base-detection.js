/**
 * Visual Mapper - API Base Detection Utility
 * Version: 0.0.5
 *
 * Standalone utility for detecting the API base URL.
 * Used by modules that need API access without creating a full APIClient instance.
 */

/**
 * Detect API base URL for Home Assistant ingress compatibility
 * @returns {string} API base URL
 */
export function getApiBase() {
    // Check if already set globally
    if (window.API_BASE) return window.API_BASE;
    if (window.opener?.API_BASE) return window.opener.API_BASE;

    // Check for Home Assistant ingress path
    const url = window.location.href;
    const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);

    if (ingressMatch) {
        return ingressMatch[0] + '/api';
    }

    // Default to relative path
    return '/api';
}

// Global export for backward compatibility
window.getApiBase = getApiBase;
