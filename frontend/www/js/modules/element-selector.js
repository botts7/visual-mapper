/**
 * Visual Mapper - Element Selector Module
 * Version: 0.0.4 (Phase 3)
 *
 * Handles element selection mode on the screenshot canvas.
 * Allows users to click on UI elements to select them for sensor creation.
 */

class ElementSelector {
    constructor(canvas, screenshotCapture) {
        this.canvas = canvas;
        this.screenshotCapture = screenshotCapture;
        this.isActive = false;
        this.selectedElement = null;
        this.selectedElementIndex = null;
        this.onSelectCallback = null;

        // Bind event handlers
        this.handleCanvasClick = this._handleClick.bind(this);
        this.handleCanvasMouseMove = this._handleMouseMove.bind(this);

        console.log('[ElementSelector] Initialized');
    }

    /**
     * Enable element selection mode
     * @param {Function} onSelect - Callback when element is selected (element, index)
     */
    enable(onSelect) {
        if (this.isActive) {
            console.warn('[ElementSelector] Already active');
            return;
        }

        this.isActive = true;
        this.onSelectCallback = onSelect;
        this.selectedElement = null;
        this.selectedElementIndex = null;

        // Add event listeners
        this.canvas.addEventListener('click', this.handleCanvasClick);
        this.canvas.addEventListener('mousemove', this.handleCanvasMouseMove);

        // Change cursor
        this.canvas.style.cursor = 'crosshair';

        console.log('[ElementSelector] Enabled');
    }

    /**
     * Disable element selection mode
     */
    disable() {
        if (!this.isActive) {
            return;
        }

        this.isActive = false;
        this.onSelectCallback = null;

        // Remove event listeners
        this.canvas.removeEventListener('click', this.handleCanvasClick);
        this.canvas.removeEventListener('mousemove', this.handleCanvasMouseMove);

        // Reset cursor
        this.canvas.style.cursor = 'default';

        // Clear selection highlight
        this._clearHighlight();

        console.log('[ElementSelector] Disabled');
    }

    /**
     * Handle canvas click
     * @private
     */
    _handleClick(event) {
        if (!this.isActive || !this.screenshotCapture.elements) {
            return;
        }

        const rect = this.canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;

        // Convert canvas coords to device coords
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        const deviceX = Math.round(x * scaleX);
        const deviceY = Math.round(y * scaleY);

        // Find element at click position
        const element = this._findElementAtPosition(deviceX, deviceY);

        if (element) {
            this.selectedElement = element.element;
            this.selectedElementIndex = element.index;

            // Highlight selected element
            this._highlightElement(element.element);

            // Trigger callback
            if (this.onSelectCallback) {
                this.onSelectCallback(element.element, element.index);
            }

            console.log(`[ElementSelector] Selected element ${element.index}:`, element.element);
        } else {
            console.log('[ElementSelector] No element at click position');
        }
    }

    /**
     * Handle mouse move (show hover preview)
     * @private
     */
    _handleMouseMove(event) {
        if (!this.isActive || !this.screenshotCapture.elements) {
            return;
        }

        const rect = this.canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;

        // Convert to device coords
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        const deviceX = Math.round(x * scaleX);
        const deviceY = Math.round(y * scaleY);

        // Find element at hover position
        const element = this._findElementAtPosition(deviceX, deviceY);

        if (element) {
            // Show tooltip with element info
            this.canvas.title = `${element.element.class}\nText: "${element.element.text || '(empty)'}"`;
        } else {
            this.canvas.title = '';
        }
    }

    /**
     * Find element at specific position
     * @private
     */
    _findElementAtPosition(x, y) {
        const elements = this.screenshotCapture.elements;
        if (!elements || elements.length === 0) {
            return null;
        }

        // Search in reverse order (topmost elements first)
        for (let i = elements.length - 1; i >= 0; i--) {
            const elem = elements[i];
            const bounds = elem.bounds;

            if (!bounds) continue;

            // Check if point is within bounds
            if (x >= bounds.x && x <= bounds.x + bounds.width &&
                y >= bounds.y && y <= bounds.y + bounds.height) {
                return { element: elem, index: i };
            }
        }

        return null;
    }

    /**
     * Highlight selected element on canvas
     * @private
     */
    _highlightElement(element) {
        if (!element || !element.bounds) {
            return;
        }

        // Re-render screenshot to clear previous highlights
        if (this.screenshotCapture.currentImage && this.screenshotCapture.elements) {
            this.screenshotCapture.renderScreenshot(
                this.screenshotCapture.currentImage,
                this.screenshotCapture.elements
            );
        }

        // Draw selection highlight
        const ctx = this.canvas.getContext('2d');
        const bounds = element.bounds;

        // Blue highlight box
        ctx.strokeStyle = '#2196F3';
        ctx.lineWidth = 4;
        ctx.strokeRect(bounds.x, bounds.y, bounds.width, bounds.height);

        // Semi-transparent blue fill
        ctx.fillStyle = 'rgba(33, 150, 243, 0.2)';
        ctx.fillRect(bounds.x, bounds.y, bounds.width, bounds.height);

        // Label with element info
        ctx.fillStyle = '#2196F3';
        ctx.fillRect(bounds.x, bounds.y - 25, 200, 25);
        ctx.fillStyle = '#FFFFFF';
        ctx.font = '12px monospace';
        ctx.fillText(`Selected: ${element.text || element.class}`, bounds.x + 5, bounds.y - 8);
    }

    /**
     * Clear selection highlight
     * @private
     */
    _clearHighlight() {
        // Re-render screenshot without selection
        if (this.screenshotCapture.currentImage && this.screenshotCapture.elements) {
            this.screenshotCapture.renderScreenshot(
                this.screenshotCapture.currentImage,
                this.screenshotCapture.elements
            );
        }
    }

    /**
     * Get currently selected element
     * @returns {Object|null}
     */
    getSelectedElement() {
        return this.selectedElement;
    }

    /**
     * Get selected element index
     * @returns {number|null}
     */
    getSelectedElementIndex() {
        return this.selectedElementIndex;
    }

    /**
     * Check if selector is active
     * @returns {boolean}
     */
    isEnabled() {
        return this.isActive;
    }
}

// ES6 export
export default ElementSelector;

// Global export for non-module usage
window.ElementSelector = ElementSelector;
