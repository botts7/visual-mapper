/**
 * HTML Sanitization Utility
 * Prevents XSS attacks by escaping user-provided content
 * Version: 0.0.5
 */

class Sanitizer {
    /**
     * Escape HTML special characters to prevent XSS
     * @param {string} str - String to escape
     * @returns {string} Escaped string safe for HTML insertion
     */
    static escapeHTML(str) {
        if (str === null || str === undefined) return '';

        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    /**
     * Sanitize a string for use in HTML attributes
     * @param {string} str - String to sanitize
     * @returns {string} Sanitized string
     */
    static escapeAttribute(str) {
        if (str === null || str === undefined) return '';

        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#x27;')
            .replace(/\//g, '&#x2F;');
    }

    /**
     * Sanitize user input for display
     * Same as escapeHTML but with explicit name for clarity
     * @param {string} input - User input to sanitize
     * @returns {string} Sanitized string
     */
    static sanitizeUserInput(input) {
        return this.escapeHTML(input);
    }

    /**
     * Create a safe text node (preferred method for displaying user content)
     * @param {string} text - Text content
     * @returns {Text} Text node safe from XSS
     */
    static createTextNode(text) {
        return document.createTextNode(text || '');
    }

    /**
     * Safely set text content of an element
     * @param {HTMLElement} element - Target element
     * @param {string} text - Text to set
     */
    static setText(element, text) {
        element.textContent = text || '';
    }

    /**
     * Validate and sanitize a coordinate value
     * @param {*} value - Value to validate
     * @param {number} defaultValue - Default value if invalid
     * @returns {number} Valid coordinate
     */
    static sanitizeCoordinate(value, defaultValue = 0) {
        const num = Number(value);
        if (isNaN(num) || num < 0 || num > 100000) {
            return defaultValue;
        }
        return Math.round(num);
    }

    /**
     * Validate and sanitize a device ID
     * @param {string} deviceId - Device ID to validate
     * @returns {string} Sanitized device ID
     */
    static sanitizeDeviceId(deviceId) {
        if (!deviceId || typeof deviceId !== 'string') {
            throw new Error('Invalid device ID');
        }
        // Device IDs should be IP:port format or similar
        // Allow alphanumeric, dots, colons, hyphens, underscores
        const sanitized = deviceId.replace(/[^a-zA-Z0-9.:_-]/g, '');
        if (sanitized !== deviceId) {
            console.warn('[Sanitizer] Device ID contained invalid characters:', deviceId);
        }
        return sanitized;
    }

    /**
     * Validate and sanitize a sensor/action ID (UUID)
     * @param {string} id - ID to validate
     * @returns {string} Sanitized ID
     */
    static sanitizeId(id) {
        if (!id || typeof id !== 'string') {
            throw new Error('Invalid ID');
        }
        // UUIDs are alphanumeric with hyphens
        const sanitized = id.replace(/[^a-zA-Z0-9-]/g, '');
        if (sanitized !== id) {
            console.warn('[Sanitizer] ID contained invalid characters:', id);
        }
        return sanitized;
    }

    /**
     * Sanitize a string for use in RegExp
     * @param {string} str - String to escape
     * @returns {string} Escaped string safe for RegExp
     */
    static escapeRegExp(str) {
        if (!str) return '';
        return String(str).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    /**
     * Validate a URL to prevent javascript: and data: URLs
     * @param {string} url - URL to validate
     * @returns {boolean} True if URL is safe
     */
    static isSafeURL(url) {
        if (!url) return false;

        const urlLower = url.toLowerCase().trim();

        // Block dangerous protocols
        const dangerousProtocols = ['javascript:', 'data:', 'vbscript:', 'file:'];
        for (const protocol of dangerousProtocols) {
            if (urlLower.startsWith(protocol)) {
                return false;
            }
        }

        return true;
    }

    /**
     * Sanitize HTML while allowing specific safe tags
     * NOTE: Use with caution - prefer escapeHTML for user content
     * @param {string} html - HTML to sanitize
     * @param {Array<string>} allowedTags - Tags to allow (default: none)
     * @returns {string} Sanitized HTML
     */
    static sanitizeHTML(html, allowedTags = []) {
        if (!html) return '';

        // If no tags allowed, just escape everything
        if (allowedTags.length === 0) {
            return this.escapeHTML(html);
        }

        // Create a temporary div to parse HTML
        const temp = document.createElement('div');
        temp.innerHTML = html;

        // Remove all script tags and event handlers
        const scripts = temp.querySelectorAll('script');
        scripts.forEach(script => script.remove());

        // Remove all event handler attributes
        const allElements = temp.querySelectorAll('*');
        allElements.forEach(el => {
            // Remove event handler attributes (onclick, onerror, etc.)
            Array.from(el.attributes).forEach(attr => {
                if (attr.name.startsWith('on')) {
                    el.removeAttribute(attr.name);
                }
            });

            // Remove dangerous attributes
            const dangerousAttrs = ['src', 'href', 'data', 'action', 'formaction'];
            dangerousAttrs.forEach(attr => {
                const value = el.getAttribute(attr);
                if (value && !this.isSafeURL(value)) {
                    el.removeAttribute(attr);
                }
            });

            // Remove elements not in allowed list
            if (!allowedTags.includes(el.tagName.toLowerCase())) {
                el.replaceWith(this.createTextNode(el.textContent));
            }
        });

        return temp.innerHTML;
    }
}

// Export for ES6 modules
export default Sanitizer;

// Also expose globally for non-module scripts
window.Sanitizer = Sanitizer;
