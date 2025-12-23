/**
 * Icon Renderer Module
 * Renders Material Design Icons (MDI) from mdi: format to HTML
 * @version 0.0.5
 */

class IconRenderer {
    constructor() {
        // Ensure MDI web font is loaded
        this._ensureMDIFont();
    }

    /**
     * Ensure MDI web font is loaded
     */
    _ensureMDIFont() {
        // Check if MDI font link already exists
        if (document.querySelector('link[href*="materialdesignicons"]')) {
            return;
        }

        // Add MDI web font from CDN
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'https://cdn.jsdelivr.net/npm/@mdi/font@7.4.47/css/materialdesignicons.min.css';
        document.head.appendChild(link);
    }

    /**
     * Render an MDI icon
     * @param {string} iconString - Icon in format "mdi:icon-name" or just "icon-name"
     * @param {object} options - Rendering options
     * @param {string} options.size - Size in CSS units (default: '1.2em')
     * @param {string} options.color - Color in CSS (default: inherit)
     * @param {string} options.style - Additional inline styles
     * @returns {string} HTML string for icon
     */
    render(iconString, options = {}) {
        if (!iconString) {
            return '';
        }

        // Parse mdi:icon-name format
        const iconName = iconString.startsWith('mdi:')
            ? iconString.substring(4)
            : iconString;

        // Build MDI class name
        const mdiClass = `mdi mdi-${iconName}`;

        // Build style attributes
        const size = options.size || '1.2em';
        const color = options.color || 'inherit';
        const customStyle = options.style || '';

        const style = `font-size: ${size}; color: ${color}; vertical-align: middle; ${customStyle}`;

        // Return icon HTML
        return `<i class="${mdiClass}" style="${style}" aria-hidden="true"></i>`;
    }

    /**
     * Render icon directly into DOM element
     * @param {HTMLElement} element - Target element
     * @param {string} iconString - Icon in format "mdi:icon-name"
     * @param {object} options - Rendering options
     */
    renderInto(element, iconString, options = {}) {
        element.innerHTML = this.render(iconString, options);
    }

    /**
     * Get icon class name from mdi: string
     * @param {string} iconString - Icon in format "mdi:icon-name"
     * @returns {string} MDI class name
     */
    getClassName(iconString) {
        if (!iconString) {
            return '';
        }

        const iconName = iconString.startsWith('mdi:')
            ? iconString.substring(4)
            : iconString;

        return `mdi mdi-${iconName}`;
    }
}

// Export as ES6 module
export default IconRenderer;

// Also export as global for non-module scripts
window.IconRenderer = IconRenderer;
