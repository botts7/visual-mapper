/**
 * Flow Canvas Renderer Module
 * Visual Mapper v0.0.11
 *
 * Handles screenshot rendering, element overlays, and canvas scaling
 * v0.0.11: Fix applyZoom - skip if container too small, auto-retry after layout
 * v0.0.10: containerClasses Set for O(1) lookup
 * v0.0.9: Smart container filtering - keep clickable containers (icon buttons)
 * v0.0.8: Fixed canvasToDevice coordinate conversion (1:1 mapping)
 * v0.0.7: Enhanced filtering - hide empty elements, more container types
 * v0.0.6: Clickable elements on top, divider filtering
 */

export class FlowCanvasRenderer {
    constructor(canvas, ctx) {
        this.canvas = canvas;
        this.ctx = ctx;
        this.currentImage = null;
        this.currentScale = 1.0;
        this.scaleMode = 'fit'; // 'fit' or '1:1'
        this.offsetX = 0; // Image centering offset
        this.offsetY = 0; // Image centering offset
        this.zoomLevel = 1.0; // Zoom level: 0.5, 1.0, 1.5, 2.0, etc.
        this.containerWidth = 0; // Container width for fitting

        // Device dimensions (for divider filtering)
        this.deviceWidth = 1080;
        this.deviceHeight = 1920;

        // Touch gesture state
        this.lastTouchDistance = 0;
        this.isPinching = false;

        // Overlay filters (passed from parent)
        this.overlayFilters = {
            showClickable: true,
            showNonClickable: false,  // Off by default - clickable elements are most useful
            showTextLabels: true,
            hideSmall: true,          // On by default - hide tiny elements
            textOnly: false,
            hideDividers: true,
            hideContainers: true,     // Hide layout/container elements by default
            hideEmptyElements: true   // Hide elements without text or content-desc
        };

        // Container/layout classes to filter out (not useful for sensors or taps)
        // Use Set for O(1) lookup instead of Array.includes() O(n)
        this.containerClasses = new Set([
            // Core Android containers
            'android.view.View',
            'android.view.ViewGroup',
            'android.widget.FrameLayout',
            'android.widget.LinearLayout',
            'android.widget.RelativeLayout',
            'android.widget.TableLayout',
            'android.widget.TableRow',
            'android.widget.GridLayout',
            'android.widget.ScrollView',
            'android.widget.HorizontalScrollView',
            'android.widget.ListView',
            'android.widget.GridView',
            'android.widget.AbsoluteLayout',
            // AndroidX containers
            'androidx.constraintlayout.widget.ConstraintLayout',
            'androidx.recyclerview.widget.RecyclerView',
            'androidx.viewpager.widget.ViewPager',
            'androidx.viewpager2.widget.ViewPager2',
            'androidx.coordinatorlayout.widget.CoordinatorLayout',
            'androidx.drawerlayout.widget.DrawerLayout',
            'androidx.appcompat.widget.LinearLayoutCompat',
            'androidx.cardview.widget.CardView',
            'androidx.core.widget.NestedScrollView',
            'androidx.swiperefreshlayout.widget.SwipeRefreshLayout',
            // Other non-interactive elements
            'android.widget.Space',
            'android.view.ViewStub'
        ]);

        // Setup gesture listeners
        this.setupGestureListeners();
    }

    /**
     * Setup touch and wheel gesture listeners
     */
    setupGestureListeners() {
        // Pinch-to-zoom
        this.canvas.addEventListener('touchstart', (e) => this.handleTouchStart(e), { passive: false });
        this.canvas.addEventListener('touchmove', (e) => this.handleTouchMove(e), { passive: false });
        this.canvas.addEventListener('touchend', (e) => this.handleTouchEnd(e), { passive: false });

        // Mouse wheel zoom
        this.canvas.addEventListener('wheel', (e) => this.handleWheel(e), { passive: false });
    }

    /**
     * Get distance between two touch points
     */
    getTouchDistance(touch1, touch2) {
        const dx = touch2.clientX - touch1.clientX;
        const dy = touch2.clientY - touch1.clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }

    /**
     * Handle touch start
     */
    handleTouchStart(e) {
        if (e.touches.length === 2) {
            e.preventDefault();
            e.stopPropagation(); // Prevent event from bubbling to page
            this.isPinching = true;
            this.lastTouchDistance = this.getTouchDistance(e.touches[0], e.touches[1]);
        }
    }

    /**
     * Handle touch move (pinch zoom)
     */
    handleTouchMove(e) {
        if (e.touches.length === 2 && this.isPinching) {
            e.preventDefault();
            e.stopPropagation(); // Prevent event from bubbling to page

            const currentDistance = this.getTouchDistance(e.touches[0], e.touches[1]);
            const delta = currentDistance - this.lastTouchDistance;

            // Zoom in/out based on pinch direction
            if (Math.abs(delta) > 5) { // Threshold to prevent jitter
                const zoomDelta = delta > 0 ? 0.05 : -0.05;
                this.setZoomLevel(this.zoomLevel + zoomDelta);
                this.applyZoom();
                this.lastTouchDistance = currentDistance;

                // Notify parent to update display
                this.canvas.dispatchEvent(new CustomEvent('zoomChanged', { detail: { zoom: this.zoomLevel } }));
            }
        }
    }

    /**
     * Handle touch end
     */
    handleTouchEnd(e) {
        if (e.touches.length < 2) {
            this.isPinching = false;
            this.lastTouchDistance = 0;
        }
    }

    /**
     * Handle mouse wheel zoom
     */
    handleWheel(e) {
        // Only handle wheel zoom if Ctrl key is pressed (standard browser zoom gesture)
        // This prevents interfering with normal scrolling
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            e.stopPropagation();

            const delta = e.deltaY > 0 ? -0.1 : 0.1; // Scroll down = zoom out, up = zoom in
            this.setZoomLevel(this.zoomLevel + delta);
            this.applyZoom();

            // Notify parent to update display
            this.canvas.dispatchEvent(new CustomEvent('zoomChanged', { detail: { zoom: this.zoomLevel } }));
        }
    }

    /**
     * Update overlay filters from external source
     */
    setOverlayFilters(filters) {
        this.overlayFilters = { ...this.overlayFilters, ...filters };
    }

    /**
     * Toggle scale mode between fit and 1:1
     */
    toggleScale() {
        this.scaleMode = this.scaleMode === 'fit' ? '1:1' : 'fit';
        console.log(`[FlowCanvasRenderer] Scale mode: ${this.scaleMode}`);
        return this.scaleMode;
    }

    /**
     * Get current scale mode
     */
    getScaleMode() {
        return this.scaleMode;
    }

    /**
     * Get current scale factor
     */
    getCurrentScale() {
        return this.currentScale;
    }

    /**
     * Set zoom level
     */
    setZoomLevel(level) {
        this.zoomLevel = Math.max(0.5, Math.min(3.0, level)); // Clamp between 0.5x and 3.0x
        console.log(`[FlowCanvasRenderer] Zoom level: ${this.zoomLevel}x`);
        return this.zoomLevel;
    }

    /**
     * Get current zoom level
     */
    getZoomLevel() {
        return this.zoomLevel;
    }

    /**
     * Zoom in
     */
    zoomIn() {
        this.setZoomLevel(this.zoomLevel + 0.25);
        return this.zoomLevel;
    }

    /**
     * Zoom out
     */
    zoomOut() {
        this.setZoomLevel(this.zoomLevel - 0.25);
        return this.zoomLevel;
    }

    /**
     * Reset zoom to fit
     */
    resetZoom() {
        this.setZoomLevel(1.0);
        return this.zoomLevel;
    }

    /**
     * Convert canvas coordinates to device coordinates
     *
     * NOTE: The canvas bitmap is rendered at full screenshot resolution (e.g., 1200x1920),
     * which matches the device resolution exactly. CSS handles scaling for display purposes only.
     * The input coordinates (canvasX, canvasY) are already in canvas bitmap space (converted
     * from CSS coordinates in the event handler), so they map 1:1 to device coordinates.
     *
     * @param {number} canvasX - X coordinate in canvas bitmap space
     * @param {number} canvasY - Y coordinate in canvas bitmap space
     * @returns {{x: number, y: number}} Device coordinates
     */
    canvasToDevice(canvasX, canvasY) {
        if (!this.currentImage || !this.canvas.width) {
            console.warn('[FlowCanvasRenderer] No screenshot loaded');
            return { x: Math.round(canvasX), y: Math.round(canvasY) };
        }

        // Canvas bitmap resolution = device resolution (1:1 mapping)
        // No conversion needed - just round to integers
        return {
            x: Math.round(canvasX),
            y: Math.round(canvasY)
        };
    }

    /**
     * Render screenshot with element overlays
     *
     * ANTI-BOUNCING STRATEGY:
     * - Canvas dimensions are set ONCE on first render to container size
     * - All subsequent renders draw scaled images into this fixed-size canvas
     * - This prevents any layout shifts from dimension changes
     */
    render(dataUrl, metadata) {
        return new Promise((resolve, reject) => {
            const img = new Image();

            img.onload = async () => {
                // Store current image
                this.currentImage = img;

                // Store device dimensions for divider filtering
                this.deviceWidth = img.width;
                this.deviceHeight = img.height;

                // Set canvas bitmap to SCREENSHOT dimensions (full resolution)
                // This ensures sharp, high-quality rendering
                this.canvas.width = img.width;
                this.canvas.height = img.height;

                console.log(`[FlowCanvasRenderer] Canvas set to screenshot size: ${img.width}x${img.height}`);

                // Clear canvas
                this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

                // Draw image at full resolution (1:1, no scaling in canvas)
                this.ctx.drawImage(img, 0, 0, img.width, img.height);

                // Apply zoom level to CSS size
                // Zoom level modifies the display size while keeping bitmap at full resolution
                this.applyZoom();

                // No offset needed since we're drawing 1:1
                this.currentScale = 1.0;
                this.offsetX = 0;
                this.offsetY = 0;

                // TIMING FIX: Wait for CSS layout to stabilize before drawing overlays
                // Double requestAnimationFrame ensures browser has completed reflow
                await new Promise(r => requestAnimationFrame(r));
                await new Promise(r => requestAnimationFrame(r));

                // Draw UI element overlays at full resolution (1:1)
                if (metadata && metadata.elements && metadata.elements.length > 0) {
                    this.drawElementOverlaysScaled(metadata.elements, 1.0);
                }

                // Canvas is always visible - no display toggle to prevent layout thrashing
                // REMOVED: this.canvas.style.display = 'block';

                console.log(`[FlowCanvasRenderer] Rendered ${img.width}x${img.height} at full resolution, zoom: ${this.zoomLevel}x`);

                resolve({ displayWidth: img.width, displayHeight: img.height, scale: 1.0 });
            };

            img.onerror = () => {
                console.error('[FlowCanvasRenderer] Failed to load screenshot');
                reject(new Error('Failed to load screenshot'));
            };

            img.src = dataUrl;
        });
    }

    /**
     * Draw UI element overlays with scaling
     * Draws non-clickable elements first, then clickable on top
     */
    drawElementOverlaysScaled(elements, scale) {
        if (!this.currentImage) {
            console.warn('[FlowCanvasRenderer] Cannot draw overlays: no screenshot loaded');
            return;
        }

        let drawnCount = 0;
        let filteredCount = 0;

        // Helper to check if element should be drawn
        const shouldDraw = (el) => {
            if (!el.bounds) return false;
            if (el.clickable && !this.overlayFilters.showClickable) return false;
            if (!el.clickable && !this.overlayFilters.showNonClickable) return false;
            if (this.overlayFilters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) return false;
            if (this.overlayFilters.textOnly && (!el.text || !el.text.trim())) return false;
            // Filter out horizontal/vertical divider lines (full width/height, very thin)
            if (this.overlayFilters.hideDividers) {
                const deviceW = this.deviceWidth || 1080;
                const deviceH = this.deviceHeight || 1920;
                const isHorizontalLine = el.bounds.height < 15 && el.bounds.width > deviceW * 0.8;
                const isVerticalLine = el.bounds.width < 15 && el.bounds.height > deviceH * 0.5;
                if (isHorizontalLine || isVerticalLine) return false;
            }
            // Filter out container/layout elements (not useful for interaction)
            // BUT keep clickable containers (they're usually buttons) or containers with resource IDs
            if (this.overlayFilters.hideContainers && el.class) {
                const isContainer = this.containerClasses.has(el.class);
                const isUsefulContainer = el.clickable || (el.resource_id && el.resource_id.trim());
                if (isContainer && !isUsefulContainer) return false;
            }
            // Filter out empty elements (no text or content-desc) - not useful for sensors
            if (this.overlayFilters.hideEmptyElements) {
                const hasText = el.text && el.text.trim();
                const hasContentDesc = el.content_desc && el.content_desc.trim();
                const hasResourceId = el.resource_id && el.resource_id.trim();
                // Keep if it has text, content-desc, or is clickable with a resource-id
                if (!hasText && !hasContentDesc && !(el.clickable && hasResourceId)) {
                    return false;
                }
            }
            return true;
        };

        // Helper to draw single element
        const drawElement = (el) => {
            const x = Math.floor(el.bounds.x * scale);
            const y = Math.floor(el.bounds.y * scale);
            const w = Math.floor(el.bounds.width * scale);
            const h = Math.floor(el.bounds.height * scale);

            // Skip elements outside canvas
            if (x + w < 0 || x > this.canvas.width || y + h < 0 || y > this.canvas.height) {
                return;
            }

            // Draw bounding box
            this.ctx.strokeStyle = el.clickable ? '#22c55e' : '#3b82f6';
            this.ctx.lineWidth = el.clickable ? 2.5 : 1.5;
            this.ctx.strokeRect(x, y, w, h);
            drawnCount++;

            // Draw text label if element has text and showTextLabels is enabled
            if (el.text && el.text.trim() && this.overlayFilters.showTextLabels) {
                this.drawTextLabel(el.text.trim(), x, y, w, el.clickable);
            }
        };

        // Draw non-clickable elements first (underneath)
        elements.forEach(el => {
            if (!el.clickable && shouldDraw(el)) {
                drawElement(el);
            } else if (!shouldDraw(el)) {
                filteredCount++;
            }
        });

        // Draw clickable elements on top
        elements.forEach(el => {
            if (el.clickable && shouldDraw(el)) {
                drawElement(el);
            }
        });

        console.log(`[FlowCanvasRenderer] Drew ${drawnCount} overlays (${filteredCount} filtered)`);
    }

    /**
     * Draw UI element overlays with scaling and offset (for centered rendering)
     * Draws non-clickable elements first, then clickable on top
     */
    drawElementOverlaysWithOffset(elements, scale, offsetX, offsetY) {
        if (!this.currentImage) {
            console.warn('[FlowCanvasRenderer] Cannot draw overlays: no screenshot loaded');
            return;
        }

        let drawnCount = 0;
        let filteredCount = 0;

        // Helper to check if element should be drawn
        const shouldDraw = (el) => {
            if (!el.bounds) return false;
            if (el.clickable && !this.overlayFilters.showClickable) return false;
            if (!el.clickable && !this.overlayFilters.showNonClickable) return false;
            if (this.overlayFilters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) return false;
            if (this.overlayFilters.textOnly && (!el.text || !el.text.trim())) return false;
            // Filter out horizontal/vertical divider lines (full width/height, very thin)
            if (this.overlayFilters.hideDividers) {
                const deviceW = this.deviceWidth || 1080;
                const deviceH = this.deviceHeight || 1920;
                const isHorizontalLine = el.bounds.height < 15 && el.bounds.width > deviceW * 0.8;
                const isVerticalLine = el.bounds.width < 15 && el.bounds.height > deviceH * 0.5;
                if (isHorizontalLine || isVerticalLine) return false;
            }
            // Filter out container/layout elements (not useful for interaction)
            // BUT keep clickable containers (they're usually buttons) or containers with resource IDs
            if (this.overlayFilters.hideContainers && el.class) {
                const isContainer = this.containerClasses.has(el.class);
                const isUsefulContainer = el.clickable || (el.resource_id && el.resource_id.trim());
                if (isContainer && !isUsefulContainer) return false;
            }
            // Filter out empty elements (no text or content-desc) - not useful for sensors
            if (this.overlayFilters.hideEmptyElements) {
                const hasText = el.text && el.text.trim();
                const hasContentDesc = el.content_desc && el.content_desc.trim();
                const hasResourceId = el.resource_id && el.resource_id.trim();
                // Keep if it has text, content-desc, or is clickable with a resource-id
                if (!hasText && !hasContentDesc && !(el.clickable && hasResourceId)) {
                    return false;
                }
            }
            return true;
        };

        // Helper to draw single element
        const drawElement = (el) => {
            const x = Math.floor(el.bounds.x * scale + offsetX);
            const y = Math.floor(el.bounds.y * scale + offsetY);
            const w = Math.floor(el.bounds.width * scale);
            const h = Math.floor(el.bounds.height * scale);

            // Skip elements outside canvas
            if (x + w < 0 || x > this.canvas.width || y + h < 0 || y > this.canvas.height) {
                return;
            }

            // Draw bounding box
            this.ctx.strokeStyle = el.clickable ? '#22c55e' : '#3b82f6';
            this.ctx.lineWidth = el.clickable ? 2.5 : 1.5;
            this.ctx.strokeRect(x, y, w, h);
            drawnCount++;

            // Draw text label if element has text and showTextLabels is enabled
            if (el.text && el.text.trim() && this.overlayFilters.showTextLabels) {
                this.drawTextLabel(el.text.trim(), x, y, w, el.clickable);
            }
        };

        // Draw non-clickable elements first (underneath)
        elements.forEach(el => {
            if (!el.clickable && shouldDraw(el)) {
                drawElement(el);
            } else if (!shouldDraw(el)) {
                filteredCount++;
            }
        });

        // Draw clickable elements on top
        elements.forEach(el => {
            if (el.clickable && shouldDraw(el)) {
                drawElement(el);
            }
        });

        console.log(`[FlowCanvasRenderer] Drew ${drawnCount} overlays (${filteredCount} filtered)`);
    }

    /**
     * Draw text label for UI element
     */
    drawTextLabel(text, x, y, w, isClickable) {
        const labelHeight = 20;
        const padding = 2;

        // Truncate long text
        const maxChars = Math.floor(w / 7); // Approximate chars that fit
        const displayText = text.length > maxChars
            ? text.substring(0, maxChars - 3) + '...'
            : text;

        // Draw background (matching element color)
        this.ctx.fillStyle = isClickable ? '#22c55e' : '#3b82f6';
        this.ctx.fillRect(x, y, w, labelHeight);

        // Draw text
        this.ctx.fillStyle = '#ffffff';
        this.ctx.font = '12px monospace';
        this.ctx.textBaseline = 'top';
        this.ctx.fillText(displayText, x + padding, y + padding);
    }

    /**
     * Show visual tap indicator on canvas
     * Device coordinates are 1:1 with canvas bitmap
     */
    showTapIndicator(x, y) {
        const size = 40;
        const radius = size / 2;

        // Coordinates are already in bitmap space (1:1)
        const canvasX = x;
        const canvasY = y;

        // Draw pulsing circle
        this.ctx.save();
        this.ctx.strokeStyle = '#3b82f6';
        this.ctx.lineWidth = 3;
        this.ctx.globalAlpha = 0.8;
        this.ctx.beginPath();
        this.ctx.arc(canvasX, canvasY, radius, 0, Math.PI * 2);
        this.ctx.stroke();
        this.ctx.restore();
    }

    /**
     * Apply zoom level to canvas CSS size
     * Supports two base modes:
     * - 'fit': Fits canvas to container (height or width, whichever is smaller)
     * - '1:1': Shows canvas at native pixel size (1:1 mapping)
     * Zoom level is applied on top of the base mode
     */
    applyZoom() {
        // In streaming mode, canvas dimensions are set by LiveStream
        // In polling mode, they're set during render()
        if (!this.canvas.width || !this.canvas.height) {
            console.log('[FlowCanvasRenderer] applyZoom skipped - no canvas dimensions');
            return;
        }

        // Get container dimensions
        const container = this.canvas.parentElement;
        if (!container) {
            console.log('[FlowCanvasRenderer] applyZoom skipped - no container');
            return;
        }

        const containerWidth = container.clientWidth;
        const containerHeight = container.clientHeight;

        // Skip if container hasn't been laid out yet
        if (containerWidth < 100) {
            console.log(`[FlowCanvasRenderer] applyZoom skipped - container too small (${containerWidth}px), will retry`);
            // Retry after layout settles
            requestAnimationFrame(() => this.applyZoom());
            return;
        }

        let baseScale;
        if (this.scaleMode === '1:1') {
            // 1:1 mode: native pixel size
            baseScale = 1.0;
        } else {
            // Fit mode: fit canvas to container while maintaining aspect ratio
            // Use minimum of width-fit and height-fit to ensure full canvas is visible
            const widthScale = containerWidth / this.canvas.width;
            const heightScale = containerHeight / this.canvas.height;
            baseScale = Math.min(widthScale, heightScale);
        }

        // Apply zoom on top of base scale
        const finalScale = baseScale * this.zoomLevel;

        const displayWidth = this.canvas.width * finalScale;
        const displayHeight = this.canvas.height * finalScale;

        // Apply via CSS - override max-width when zoomed in or 1:1 mode to allow canvas to grow
        this.canvas.style.width = `${displayWidth}px`;
        this.canvas.style.height = `${displayHeight}px`;
        this.canvas.style.maxWidth = (this.zoomLevel > 1 || this.scaleMode === '1:1') ? 'none' : '100%';

        console.log(`[FlowCanvasRenderer] Applied zoom ${this.zoomLevel}x (mode: ${this.scaleMode}, canvas: ${this.canvas.width}x${this.canvas.height}, container: ${containerWidth}px, base: ${baseScale.toFixed(2)}x, final: ${finalScale.toFixed(2)}x): ${Math.round(displayWidth)}x${Math.round(displayHeight)}`);
    }

    /**
     * Fit to screen - reset zoom and set fit mode
     */
    fitToScreen() {
        this.scaleMode = 'fit';
        this.zoomLevel = 1.0;
        this.applyZoom();
        return this.zoomLevel;
    }

    /**
     * Redraw the current image (clears overlays)
     */
    redraw() {
        if (this.currentImage) {
            this.ctx.drawImage(this.currentImage, 0, 0, this.canvas.width, this.canvas.height);
        }
    }

    /**
     * Clear the canvas
     */
    clear() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
}

// Dual export
export default FlowCanvasRenderer;
window.FlowCanvasRenderer = FlowCanvasRenderer;
