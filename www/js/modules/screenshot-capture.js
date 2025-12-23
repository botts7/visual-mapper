/**
 * Visual Mapper - Screenshot Capture Module
 * Version: 0.0.2 (Phase 1)
 *
 * Handles screenshot capture, canvas rendering, and UI element overlays.
 */

class ScreenshotCapture {
    constructor(apiClient, canvas) {
        this.apiClient = apiClient;
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.currentImage = null;
        this.elements = [];
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;

        // Overlay filters (default: show everything)
        this.filters = {
            showClickable: true,
            showNonClickable: true,
            showTextLabels: true,
            hideSmall: false,
            textOnly: false
        };

        console.log('[ScreenshotCapture] Initialized');
    }

    /**
     * Set overlay filters
     * @param {Object} filters - Filter configuration
     */
    setFilters(filters) {
        this.filters = { ...this.filters, ...filters };
        console.log('[ScreenshotCapture] Filters updated:', this.filters);
    }

    /**
     * Capture screenshot and UI elements from device
     * @param {string} deviceId - Device identifier (host:port)
     */
    async capture(deviceId) {
        try {
            console.log(`[ScreenshotCapture] Capturing from ${deviceId}...`);

            // Call screenshot API
            const response = await this.apiClient.post('/adb/screenshot', {
                device_id: deviceId
            });

            console.log(`[ScreenshotCapture] Received ${response.elements.length} UI elements`);

            // Create image from base64 data
            const img = new Image();

            // Wait for image to load
            await new Promise((resolve, reject) => {
                img.onload = resolve;
                img.onerror = reject;
                img.src = 'data:image/png;base64,' + response.screenshot;
            });

            this.currentImage = img;
            this.elements = response.elements;

            // Render screenshot with overlays
            this.renderScreenshot(img, response.elements);

            console.log('[ScreenshotCapture] Capture complete');
            return {
                image: img,
                elements: response.elements,
                timestamp: response.timestamp
            };

        } catch (error) {
            console.error('[ScreenshotCapture] Capture failed:', error);
            throw error;
        }
    }

    /**
     * Render screenshot on canvas with UI element overlays
     * @param {Image} img - Screenshot image
     * @param {Array} elements - UI elements array
     */
    renderScreenshot(img, elements) {
        // Resize canvas to match image dimensions exactly (no letterboxing)
        this.canvas.width = img.width;
        this.canvas.height = img.height;

        // No scaling needed - display at 1:1
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;

        // Draw screenshot image at full size
        this.ctx.drawImage(img, 0, 0);

        // Draw UI element overlays
        this.drawElements(elements);

        console.log(`[ScreenshotCapture] Rendered at ${img.width}x${img.height} (1:1 scale)`);
    }

    /**
     * Draw UI element overlays on canvas
     * @param {Array} elements - UI elements array
     */
    drawElements(elements) {
        console.log(`[ScreenshotCapture] Drawing ${elements.length} elements with filters:`, this.filters);

        let visibleCount = 0;
        let drawnCount = 0;
        let filteredCount = 0;

        elements.forEach(el => {
            // Only draw elements with bounds (ignore visibility flag - it's often false even for visible elements)
            if (!el.bounds) {
                return;
            }

            visibleCount++;

            // Apply filters
            // Filter by clickable/non-clickable
            if (el.clickable && !this.filters.showClickable) {
                filteredCount++;
                return;
            }
            if (!el.clickable && !this.filters.showNonClickable) {
                filteredCount++;
                return;
            }

            // Filter by size (hide small elements < 50px width or height)
            if (this.filters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) {
                filteredCount++;
                return;
            }

            // Filter: text elements only
            if (this.filters.textOnly && (!el.text || !el.text.trim())) {
                filteredCount++;
                return;
            }

            // Scale and offset coordinates
            const x = (el.bounds.x * this.scale) + this.offsetX;
            const y = (el.bounds.y * this.scale) + this.offsetY;
            const w = el.bounds.width * this.scale;
            const h = el.bounds.height * this.scale;

            // Skip elements outside canvas
            if (x + w < 0 || x > this.canvas.width || y + h < 0 || y > this.canvas.height) {
                return;
            }

            // Draw bounding box
            // Green for clickable, yellow for non-clickable
            this.ctx.strokeStyle = el.clickable ? '#00ff00' : '#ffff00';
            this.ctx.lineWidth = 2;
            this.ctx.strokeRect(x, y, w, h);
            drawnCount++;

            // Draw text label if element has text (and labels are enabled)
            if (this.filters.showTextLabels && el.text && el.text.trim()) {
                this.drawTextLabel(el.text, x, y, w);
            }
        });

        console.log(`[ScreenshotCapture] Total: ${visibleCount}, Filtered: ${filteredCount}, Drawn: ${drawnCount}`);
    }

    /**
     * Draw text label for UI element
     * @param {string} text - Element text
     * @param {number} x - X coordinate
     * @param {number} y - Y coordinate
     * @param {number} w - Width
     */
    drawTextLabel(text, x, y, w) {
        const labelHeight = 20;
        const padding = 2;

        // Truncate long text
        const maxChars = Math.floor(w / 7); // Approximate chars that fit
        const displayText = text.length > maxChars
            ? text.substring(0, maxChars - 3) + '...'
            : text;

        // Draw background
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        this.ctx.fillRect(x, y - labelHeight, w, labelHeight);

        // Draw text
        this.ctx.fillStyle = '#ffffff';
        this.ctx.font = '12px monospace';
        this.ctx.textBaseline = 'top';
        this.ctx.fillText(displayText, x + padding, y - labelHeight + padding);
    }

    /**
     * Convert canvas coordinates to device coordinates
     * @param {number} canvasX - Canvas X coordinate
     * @param {number} canvasY - Canvas Y coordinate
     * @returns {Object} Device coordinates {x, y}
     */
    canvasToDevice(canvasX, canvasY) {
        if (!this.currentImage || this.scale === 0) {
            throw new Error('No screenshot loaded');
        }

        // Remove offset and scale
        const deviceX = Math.round((canvasX - this.offsetX) / this.scale);
        const deviceY = Math.round((canvasY - this.offsetY) / this.scale);

        return { x: deviceX, y: deviceY };
    }

    /**
     * Find UI element at canvas coordinates
     * @param {number} canvasX - Canvas X coordinate
     * @param {number} canvasY - Canvas Y coordinate
     * @returns {Object|null} UI element or null
     */
    findElementAtPoint(canvasX, canvasY) {
        const deviceCoords = this.canvasToDevice(canvasX, canvasY);

        // Search elements in reverse order (top to bottom in UI hierarchy)
        for (let i = this.elements.length - 1; i >= 0; i--) {
            const el = this.elements[i];

            if (!el.bounds || !el.visible) continue;

            const { x, y, width, height } = el.bounds;

            // Check if point is within element bounds
            if (deviceCoords.x >= x && deviceCoords.x <= x + width &&
                deviceCoords.y >= y && deviceCoords.y <= y + height) {
                return el;
            }
        }

        return null;
    }

    /**
     * Clear canvas
     */
    clear() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.currentImage = null;
        this.elements = [];
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;
        console.log('[ScreenshotCapture] Canvas cleared');
    }

    /**
     * Get current screenshot metadata
     * @returns {Object} Metadata
     */
    getMetadata() {
        return {
            hasScreenshot: this.currentImage !== null,
            elementCount: this.elements.length,
            scale: this.scale,
            offset: { x: this.offsetX, y: this.offsetY },
            imageSize: this.currentImage ? {
                width: this.currentImage.width,
                height: this.currentImage.height
            } : null
        };
    }
}

// ES6 export
export default ScreenshotCapture;

// Global export for non-module usage
window.ScreenshotCapture = ScreenshotCapture;
