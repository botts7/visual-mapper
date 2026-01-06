/**
 * Visual Mapper - Overlay Filters Module
 * Version: 0.0.3 (Phase 2)
 *
 * Manages UI element overlay filter controls.
 */

class OverlayFilters {
    constructor(screenshotCapture) {
        this.screenshotCapture = screenshotCapture;
        this.filters = {
            showClickable: true,
            showNonClickable: true,
            showTextLabels: true,
            hideSmall: false,
            textOnly: false
        };

        console.log('[OverlayFilters] Initialized');
    }

    /**
     * Initialize filter controls (bind to checkboxes)
     * @param {Object} elements - Object with checkbox element IDs
     * @param {string} elements.clickable - Clickable checkbox ID
     * @param {string} elements.nonClickable - Non-clickable checkbox ID
     * @param {string} elements.textLabels - Text labels checkbox ID
     * @param {string} elements.hideSmall - Hide small checkbox ID
     * @param {string} elements.textOnly - Text-only checkbox ID
     */
    init(elements) {
        const checkboxIds = {
            showClickable: elements.clickable,
            showNonClickable: elements.nonClickable,
            showTextLabels: elements.textLabels,
            hideSmall: elements.hideSmall,
            textOnly: elements.textOnly
        };

        // Bind change events
        Object.entries(checkboxIds).forEach(([filterName, elementId]) => {
            const checkbox = document.getElementById(elementId);
            if (!checkbox) {
                console.warn(`[OverlayFilters] Checkbox not found: ${elementId}`);
                return;
            }

            checkbox.addEventListener('change', () => {
                this.setFilter(filterName, checkbox.checked);
                this.applyFilters();
            });

            // Set initial state
            checkbox.checked = this.filters[filterName];
        });

        console.log('[OverlayFilters] Initialized with checkboxes');
    }

    /**
     * Set a filter value
     * @param {string} filterName - Filter name
     * @param {boolean} value - Filter value
     */
    setFilter(filterName, value) {
        if (!(filterName in this.filters)) {
            console.warn(`[OverlayFilters] Unknown filter: ${filterName}`);
            return;
        }

        this.filters[filterName] = value;
        console.log(`[OverlayFilters] ${filterName} = ${value}`);
    }

    /**
     * Apply current filters to screenshot capture
     */
    applyFilters() {
        this.screenshotCapture.setFilters(this.filters);

        // Re-render current screenshot if one exists
        if (this.screenshotCapture.currentImage) {
            this.screenshotCapture.renderScreenshot(
                this.screenshotCapture.currentImage,
                this.screenshotCapture.elements
            );
        }
    }

    /**
     * Get current filters
     * @returns {Object} Current filter state
     */
    getFilters() {
        return { ...this.filters };
    }

    /**
     * Reset filters to default
     */
    reset() {
        this.filters = {
            showClickable: true,
            showNonClickable: true,
            showTextLabels: true,
            hideSmall: false,
            textOnly: false
        };

        this.applyFilters();
        console.log('[OverlayFilters] Reset to defaults');
    }
}

// ES6 export
export default OverlayFilters;

// Global export for non-module usage
window.OverlayFilters = OverlayFilters;
