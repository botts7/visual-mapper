/**
 * Canvas Overlay Renderer Module
 * Extracted from flow-wizard-step3.js for modularity
 *
 * Handles:
 * - Hover tooltip display and positioning
 * - Element highlight overlays (CSS-based, no canvas re-render)
 * - Drawing element bounding boxes on canvas
 * - Text label rendering with scaling
 *
 * @module canvas-overlay-renderer
 */

// Container classes to filter out (same as FlowInteractions)
// Use Set for O(1) lookup instead of Array.includes() O(n)
const CONTAINER_CLASSES = new Set([
    'android.view.View', 'android.view.ViewGroup', 'android.widget.FrameLayout',
    'android.widget.LinearLayout', 'android.widget.RelativeLayout',
    'android.widget.ScrollView', 'android.widget.HorizontalScrollView',
    'androidx.constraintlayout.widget.ConstraintLayout',
    'androidx.recyclerview.widget.RecyclerView', 'androidx.cardview.widget.CardView'
]);

// ==========================================
// Hover Tooltip Functions
// ==========================================

/**
 * Setup hover tooltip for element preview
 * @param {Object} wizard - The wizard instance
 */
export function setupHoverTooltip(wizard) {
    wizard.hoveredElement = null;
    const hoverTooltip = document.getElementById('hoverTooltip');
    const container = document.getElementById('screenshotContainer');

    if (!hoverTooltip || !container) return;

    // Handle mouse move on canvas
    wizard.canvas.addEventListener('mousemove', (e) => {
        handleCanvasHover(wizard, e, hoverTooltip, container);
    });

    // Hide tooltip when mouse leaves canvas
    wizard.canvas.addEventListener('mouseleave', () => {
        wizard.hoveredElement = null;
        hideHoverTooltip(wizard, hoverTooltip);
    });

    console.log('[CanvasOverlay] Hover tooltip initialized');
}

/**
 * Handle mouse movement over canvas for element hover
 * @param {Object} wizard - The wizard instance
 * @param {MouseEvent} e - The mouse event
 * @param {HTMLElement} hoverTooltip - The tooltip element
 * @param {HTMLElement} container - The screenshot container
 */
export function handleCanvasHover(wizard, e, hoverTooltip, container) {
    // Use elements based on current capture mode to avoid stale data
    // In streaming mode: use liveStream.elements (updated from elements API)
    // In polling mode: use recorder.screenshotMetadata.elements (from screenshot response)
    const elements = wizard.captureMode === 'streaming'
        ? (wizard.liveStream?.elements || [])
        : (wizard.recorder?.screenshotMetadata?.elements || wizard.liveStream?.elements || []);

    if (elements.length === 0) {
        hideHoverTooltip(wizard, hoverTooltip);
        clearHoverHighlight(wizard);
        wizard.hoveredElement = null;
        return;
    }

    // Get canvas coordinates (CSS display coords → canvas bitmap coords)
    const rect = wizard.canvas.getBoundingClientRect();
    const cssToCanvas = wizard.canvas.width / rect.width;
    const canvasX = (e.clientX - rect.left) * cssToCanvas;
    const canvasY = (e.clientY - rect.top) * cssToCanvas;

    // Convert to device coordinates (use appropriate converter based on mode)
    let deviceCoords;
    if (wizard.captureMode === 'streaming' && wizard.liveStream) {
        deviceCoords = wizard.liveStream.canvasToDevice(canvasX, canvasY);
    } else {
        deviceCoords = wizard.canvasRenderer.canvasToDevice(canvasX, canvasY);
    }

    // Skip if no frame loaded yet (deviceCoords will be null)
    if (!deviceCoords) {
        hoverTooltip.style.display = 'none';
        return;
    }

    // Find elements at hover position (filter containers)
    let elementsAtPoint = [];
    for (let i = elements.length - 1; i >= 0; i--) {
        const el = elements[i];
        if (!el.bounds) continue;

        // Skip containers if filter is enabled (BUT keep clickable containers - they're usually buttons)
        if (wizard.overlayFilters?.hideContainers && el.class && CONTAINER_CLASSES.has(el.class)) {
            const isUsefulContainer = el.clickable || (el.resource_id && el.resource_id.trim());
            if (!isUsefulContainer) continue;
        }

        // Skip empty elements if filter is enabled
        // Keep clickable elements (includes inherited clickable from parent)
        if (wizard.overlayFilters?.hideEmptyElements) {
            const hasText = el.text && el.text.trim();
            const hasContentDesc = el.content_desc && el.content_desc.trim();
            if (!hasText && !hasContentDesc && !el.clickable) {
                continue;
            }
        }

        const b = el.bounds;
        if (deviceCoords.x >= b.x && deviceCoords.x <= b.x + b.width &&
            deviceCoords.y >= b.y && deviceCoords.y <= b.y + b.height) {
            elementsAtPoint.push(el);
        }
    }

    // Prioritize: elements with text first, then clickable, then smallest area
    let foundElement = null;
    if (elementsAtPoint.length > 0) {
        // Prefer elements with text
        const withText = elementsAtPoint.filter(el => el.text?.trim() || el.content_desc?.trim());
        const clickable = elementsAtPoint.filter(el => el.clickable);
        const candidates = withText.length > 0 ? withText : (clickable.length > 0 ? clickable : elementsAtPoint);

        foundElement = candidates.reduce((smallest, el) => {
            const area = el.bounds.width * el.bounds.height;
            const smallestArea = smallest.bounds.width * smallest.bounds.height;
            return area < smallestArea ? el : smallest;
        });
    }

    // Check if element changed (compare by bounds, not object reference)
    const isSameElement = foundElement && wizard.hoveredElement &&
        foundElement.bounds?.x === wizard.hoveredElement.bounds?.x &&
        foundElement.bounds?.y === wizard.hoveredElement.bounds?.y &&
        foundElement.bounds?.width === wizard.hoveredElement.bounds?.width;

    if (foundElement && !isSameElement) {
        // New element - rebuild tooltip content
        wizard.hoveredElement = foundElement;
        showHoverTooltip(wizard, e, foundElement, hoverTooltip, container);
        highlightHoveredElement(wizard, foundElement);
    } else if (!foundElement && wizard.hoveredElement) {
        // No longer hovering any element
        wizard.hoveredElement = null;
        hideHoverTooltip(wizard, hoverTooltip);
        clearHoverHighlight(wizard);
    }

    // ALWAYS update position when hovering an element (fixes cursor following)
    if (foundElement) {
        updateTooltipPosition(wizard, e, hoverTooltip, container);
    }
}

/**
 * Show hover tooltip with element info
 * @param {Object} wizard - The wizard instance
 * @param {MouseEvent} e - The mouse event
 * @param {Object} element - The element being hovered
 * @param {HTMLElement} hoverTooltip - The tooltip element
 * @param {HTMLElement} container - The screenshot container
 */
export function showHoverTooltip(wizard, e, element, hoverTooltip, container) {
    const header = hoverTooltip.querySelector('.tooltip-header');
    const body = hoverTooltip.querySelector('.tooltip-body');

    // Header: element text or class name
    const displayName = element.text?.trim() ||
                       element.content_desc?.trim() ||
                       element.class?.split('.').pop() ||
                       'Element';
    header.textContent = displayName;

    // Body: element details
    const clickableBadge = element.clickable
        ? '<span class="clickable-badge">Clickable</span>'
        : '<span class="not-clickable-badge">Not Clickable</span>';

    let bodyHtml = `<div class="tooltip-row"><span class="tooltip-label">Class:</span><span class="tooltip-value">${element.class?.split('.').pop() || '-'}</span></div>`;

    const resourceId = element.resource_id;
    if (resourceId) {
        const resId = resourceId.split('/').pop() || resourceId;
        bodyHtml += `<div class="tooltip-row"><span class="tooltip-label">ID:</span><span class="tooltip-value">${resId}</span></div>`;
    }

    if (element.bounds) {
        bodyHtml += `<div class="tooltip-row"><span class="tooltip-label">Size:</span><span class="tooltip-value">${element.bounds.width}x${element.bounds.height}</span></div>`;
    }

    bodyHtml += `<div class="tooltip-row"><span class="tooltip-label">Status:</span><span class="tooltip-value">${clickableBadge}</span></div>`;

    body.innerHTML = bodyHtml;

    updateTooltipPosition(wizard, e, hoverTooltip, container);
    hoverTooltip.style.display = 'block';
}

/**
 * Update tooltip position near cursor
 * @param {Object} wizard - The wizard instance
 * @param {MouseEvent} e - The mouse event
 * @param {HTMLElement} hoverTooltip - The tooltip element
 * @param {HTMLElement} container - The screenshot container
 */
export function updateTooltipPosition(wizard, e, hoverTooltip, container) {
    const containerRect = container.getBoundingClientRect();

    // Account for container scroll offset
    const scrollLeft = container.scrollLeft || 0;
    const scrollTop = container.scrollTop || 0;

    // Position tooltip near cursor (add scroll offset for scrolled containers)
    let x = e.clientX - containerRect.left + scrollLeft + 15;
    let y = e.clientY - containerRect.top + scrollTop + 15;

    // Get tooltip dimensions (use cached if not visible yet)
    const tooltipWidth = hoverTooltip.offsetWidth || 280;
    const tooltipHeight = hoverTooltip.offsetHeight || 100;

    // Keep tooltip within visible viewport (not scrolled content)
    const visibleWidth = containerRect.width;
    const visibleHeight = containerRect.height;

    // Flip to left if would overflow right
    if (x - scrollLeft + tooltipWidth > visibleWidth - 10) {
        x = e.clientX - containerRect.left + scrollLeft - tooltipWidth - 15;
    }
    // Flip to top if would overflow bottom
    if (y - scrollTop + tooltipHeight > visibleHeight - 10) {
        y = e.clientY - containerRect.top + scrollTop - tooltipHeight - 15;
    }

    // Ensure minimum position
    x = Math.max(scrollLeft + 5, x);
    y = Math.max(scrollTop + 5, y);

    hoverTooltip.style.left = x + 'px';
    hoverTooltip.style.top = y + 'px';
}

/**
 * Hide hover tooltip
 * @param {Object} wizard - The wizard instance
 * @param {HTMLElement} hoverTooltip - The tooltip element
 */
export function hideHoverTooltip(wizard, hoverTooltip) {
    if (hoverTooltip) {
        hoverTooltip.style.display = 'none';
    }
}

// ==========================================
// Element Highlight Functions
// ==========================================

/**
 * Highlight hovered element using CSS overlay (no canvas re-render)
 * Handles both polling mode (screenshot) and streaming mode (live stream)
 * @param {Object} wizard - The wizard instance
 * @param {Object} element - The element to highlight
 */
export function highlightHoveredElement(wizard, element) {
    const container = document.getElementById('screenshotContainer');
    if (!container || !element?.bounds) {
        clearHoverHighlight(wizard);
        return;
    }

    // Create or reuse highlight overlay
    let highlight = document.getElementById('hoverHighlight');
    if (!highlight) {
        highlight = document.createElement('div');
        highlight.id = 'hoverHighlight';
        highlight.className = 'hover-highlight';
        container.appendChild(highlight);
    }

    // Calculate position relative to canvas
    const canvasRect = wizard.canvas.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();

    // CRITICAL: For scroll containers, the highlight must be positioned relative to scroll position
    // canvasRect is viewport position (affected by scroll), but absolute positioning is relative to container
    // So we need the canvas offset WITHIN the scrollable content, not the viewport offset
    const offsetX = canvasRect.left - containerRect.left + container.scrollLeft;
    const offsetY = canvasRect.top - containerRect.top + container.scrollTop;

    // Get CSS scale (canvas bitmap size to display size)
    const cssScaleX = canvasRect.width / wizard.canvas.width;
    const cssScaleY = canvasRect.height / wizard.canvas.height;

    // In streaming mode, element bounds are in device coords, canvas may be at lower res
    // We need to scale: device coords → canvas coords → CSS display coords
    // IMPORTANT: Use separate X and Y scales to handle aspect ratio differences
    let deviceToCanvasScaleX = 1;
    let deviceToCanvasScaleY = 1;
    if (wizard.captureMode === 'streaming' && wizard.liveStream) {
        // Scale from device resolution to canvas resolution (separate X/Y for aspect ratio)
        deviceToCanvasScaleX = wizard.canvas.width / wizard.liveStream.deviceWidth;
        deviceToCanvasScaleY = wizard.canvas.height / wizard.liveStream.deviceHeight;
    }

    const b = element.bounds;
    // First scale from device to canvas, then from canvas to CSS display
    const totalScaleX = deviceToCanvasScaleX * cssScaleX;
    const totalScaleY = deviceToCanvasScaleY * cssScaleY;
    const x = b.x * totalScaleX + offsetX;
    const y = b.y * totalScaleY + offsetY;
    const w = b.width * totalScaleX;
    const h = b.height * totalScaleY;

    highlight.style.cssText = `
        position: absolute;
        left: ${x}px;
        top: ${y}px;
        width: ${w}px;
        height: ${h}px;
        border: 2px solid #00ffff;
        border-radius: 4px;
        background: rgba(0, 255, 255, 0.1);
        pointer-events: none;
        z-index: 50;
        transition: all 0.1s ease-out;
    `;
}

/**
 * Clear hover highlight overlay
 * @param {Object} wizard - The wizard instance
 */
export function clearHoverHighlight(wizard) {
    const highlight = document.getElementById('hoverHighlight');
    if (highlight) {
        highlight.remove();
    }
}

/**
 * Clear all elements and hover state across all modes
 * Call this when an action is performed that changes the screen
 * @param {Object} wizard - The wizard instance
 */
export function clearAllElementsAndHover(wizard) {
    // Clear hover state
    clearHoverHighlight(wizard);
    wizard.hoveredElement = null;

    // Clear recorder metadata (used in polling mode)
    if (wizard.recorder?.screenshotMetadata) {
        wizard.recorder.screenshotMetadata.elements = [];
    }

    // Clear liveStream elements (used in streaming mode)
    if (wizard.liveStream) {
        wizard.liveStream.elements = [];
    }

    console.log('[CanvasOverlay] Cleared all elements and hover state');
}

// ==========================================
// Canvas Drawing Functions
// ==========================================

/**
 * Draw UI element overlays on canvas
 * @param {Object} wizard - The wizard instance
 */
export function drawElementOverlays(wizard) {
    if (!wizard.currentImage || !wizard.recorder.screenshotMetadata) {
        console.warn('[CanvasOverlay] Cannot draw overlays: no screenshot loaded');
        return;
    }

    // Redraw the screenshot image first (to clear old overlays)
    wizard.ctx.drawImage(wizard.currentImage, 0, 0);

    const elements = wizard.recorder.screenshotMetadata.elements || [];

    // Count elements by type
    const clickableElements = elements.filter(e => e.clickable === true);
    const nonClickableElements = elements.filter(e => e.clickable === false || e.clickable === undefined);

    console.log(`[CanvasOverlay] Drawing ${elements.length} elements (${clickableElements.length} clickable, ${nonClickableElements.length} non-clickable)`);
    console.log('[CanvasOverlay] Overlay filters:', wizard.overlayFilters);

    let visibleCount = 0;
    let drawnCount = 0;
    let filteredClickable = 0;
    let filteredNonClickable = 0;
    let drawnClickable = 0;
    let drawnNonClickable = 0;

    elements.forEach(el => {
        // Only draw elements with bounds
        if (!el.bounds) {
            return;
        }

        visibleCount++;

        // Apply filters (same as screenshot-capture.js)
        if (el.clickable && !wizard.overlayFilters.showClickable) {
            filteredClickable++;
            return;
        }
        if (!el.clickable && !wizard.overlayFilters.showNonClickable) {
            filteredNonClickable++;
            return;
        }

        // Filter by size (hide small elements < 50px width or height)
        if (wizard.overlayFilters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) {
            if (el.clickable) filteredClickable++; else filteredNonClickable++;
            return;
        }

        // Filter: text elements only
        if (wizard.overlayFilters.textOnly && (!el.text || !el.text.trim())) {
            if (el.clickable) filteredClickable++; else filteredNonClickable++;
            return;
        }

        // Get coordinates (no scaling - 1:1)
        const x = el.bounds.x;
        const y = el.bounds.y;
        const w = el.bounds.width;
        const h = el.bounds.height;

        // Skip elements outside canvas
        if (x + w < 0 || x > wizard.canvas.width || y + h < 0 || y > wizard.canvas.height) {
            return;
        }

        // Draw bounding box
        // Green for clickable, blue for non-clickable (matching flow-wizard colors)
        wizard.ctx.strokeStyle = el.clickable ? '#22c55e' : '#3b82f6';
        wizard.ctx.fillStyle = el.clickable ? 'rgba(34, 197, 94, 0.1)' : 'rgba(59, 130, 246, 0.1)';
        wizard.ctx.lineWidth = 2;

        // Fill background
        wizard.ctx.fillRect(x, y, w, h);

        // Draw border
        wizard.ctx.strokeRect(x, y, w, h);
        drawnCount++;
        if (el.clickable) drawnClickable++; else drawnNonClickable++;

        // Draw text label if element has text (and labels are enabled)
        if (wizard.overlayFilters.showTextLabels && el.text && el.text.trim()) {
            drawTextLabel(wizard, el.text, x, y, w, el.clickable);
        }
    });

    console.log(`[CanvasOverlay] Total visible: ${visibleCount}`);
    console.log(`[CanvasOverlay] Filtered: ${filteredClickable + filteredNonClickable} (${filteredClickable} clickable, ${filteredNonClickable} non-clickable)`);
    console.log(`[CanvasOverlay] Drawn: ${drawnCount} (${drawnClickable} clickable, ${drawnNonClickable} non-clickable)`);
}

/**
 * Draw UI element overlays with scaling
 * @param {Object} wizard - The wizard instance
 * @param {number} scale - The scale factor to apply
 */
export function drawElementOverlaysScaled(wizard, scale) {
    if (!wizard.currentImage || !wizard.recorder.screenshotMetadata) {
        console.warn('[CanvasOverlay] Cannot draw overlays: no screenshot loaded');
        return;
    }

    const elements = wizard.recorder.screenshotMetadata.elements || [];

    elements.forEach(el => {
        if (!el.bounds) return;

        // Apply overlay filters
        if (el.clickable && !wizard.overlayFilters.showClickable) return;
        if (!el.clickable && !wizard.overlayFilters.showNonClickable) return;
        if (wizard.overlayFilters.hideSmall && (el.bounds.width < 50 || el.bounds.height < 50)) return;
        if (wizard.overlayFilters.textOnly && (!el.text || !el.text.trim())) return;

        // Scale coordinates
        const x = Math.floor(el.bounds.x * scale);
        const y = Math.floor(el.bounds.y * scale);
        const w = Math.floor(el.bounds.width * scale);
        const h = Math.floor(el.bounds.height * scale);

        // Skip elements outside canvas
        if (x + w < 0 || x > wizard.canvas.width || y + h < 0 || y > wizard.canvas.height) return;

        // Draw bounding box
        wizard.ctx.strokeStyle = el.clickable ? '#22c55e' : '#3b82f6';
        wizard.ctx.lineWidth = 2;
        wizard.ctx.strokeRect(x, y, w, h);

        // Draw text label if element has text and showTextLabels is enabled
        if (el.text && el.text.trim() && wizard.overlayFilters.showTextLabels) {
            drawTextLabel(wizard, el.text.trim(), x, y, w, el.clickable);
        }
    });
}

/**
 * Draw text label for UI element on canvas
 * Scales font size based on canvas width to look appropriate at all resolutions
 * @param {Object} wizard - The wizard instance
 * @param {string} text - The text to display
 * @param {number} x - X coordinate
 * @param {number} y - Y coordinate
 * @param {number} w - Width of the element
 * @param {boolean} isClickable - Whether the element is clickable
 */
export function drawTextLabel(wizard, text, x, y, w, isClickable) {
    // Scale font based on canvas width (reference: 720px = 12px font)
    const scaleFactor = Math.max(0.6, Math.min(1.5, wizard.canvas.width / 720));
    const fontSize = Math.round(12 * scaleFactor);
    const labelHeight = Math.round(20 * scaleFactor);
    const charWidth = Math.round(7 * scaleFactor);
    const padding = Math.round(2 * scaleFactor);

    // Truncate long text
    const maxChars = Math.floor(w / charWidth); // Approximate chars that fit
    const displayText = text.length > maxChars
        ? text.substring(0, maxChars - 3) + '...'
        : text;

    // Draw background (matching element color)
    wizard.ctx.fillStyle = isClickable ? '#22c55e' : '#3b82f6';
    wizard.ctx.fillRect(x, y, w, labelHeight);

    // Draw text
    wizard.ctx.fillStyle = '#ffffff';
    wizard.ctx.font = `${fontSize}px monospace`;
    wizard.ctx.textBaseline = 'top';
    wizard.ctx.fillText(displayText, x + padding, y + padding);
}

// ==========================================
// Default Export
// ==========================================

export default {
    // Hover tooltip functions
    setupHoverTooltip,
    handleCanvasHover,
    showHoverTooltip,
    updateTooltipPosition,
    hideHoverTooltip,

    // Element highlight functions
    highlightHoveredElement,
    clearHoverHighlight,
    clearAllElementsAndHover,

    // Canvas drawing functions
    drawElementOverlays,
    drawElementOverlaysScaled,
    drawTextLabel
};

// Global export for non-module usage
if (typeof window !== 'undefined') {
    window.CanvasOverlayRenderer = {
        setupHoverTooltip,
        handleCanvasHover,
        showHoverTooltip,
        updateTooltipPosition,
        hideHoverTooltip,
        highlightHoveredElement,
        clearHoverHighlight,
        clearAllElementsAndHover,
        drawElementOverlays,
        drawElementOverlaysScaled,
        drawTextLabel
    };
}
