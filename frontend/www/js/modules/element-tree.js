/**
 * Element Tree Module
 * Visual Mapper v0.0.4
 *
 * Hierarchical view of UI elements with search, filtering, and actions
 * v0.0.4: Enhanced element display with names and values
 */

class ElementTree {
    constructor(container, options = {}) {
        this.container = container;
        this.elements = [];
        this.filteredElements = [];
        this.searchQuery = '';
        this.highlightedElement = null;

        // Callbacks
        this.onTap = options.onTap || null;
        this.onSensor = options.onSensor || null;
        this.onHighlight = options.onHighlight || null;

        // Filter settings
        this.showClickableOnly = false;
        this.showTextOnly = false;

        console.log('[ElementTree] Initialized');
    }

    /**
     * Update elements and re-render (only if changed)
     */
    setElements(elements) {
        const newElements = elements || [];

        // Skip re-render if elements haven't changed (prevents dropdown reset)
        if (this._elementsMatch(this.elements, newElements)) {
            return;
        }

        this.elements = newElements;
        this.applyFilters();
        this.render();
    }

    /**
     * Compare two element arrays to check if they're functionally the same
     * Uses a fast hash comparison to avoid expensive deep equality checks
     */
    _elementsMatch(oldElements, newElements) {
        if (!oldElements || !newElements) return false;
        if (oldElements.length !== newElements.length) return false;
        if (oldElements.length === 0) return true;

        // Quick hash: compare first, middle, and last element key properties
        const hashElement = (el) => {
            if (!el) return '';
            return `${el.text || ''}|${el.resource_id || ''}|${el.class || ''}|${el.bounds?.x || 0},${el.bounds?.y || 0}`;
        };

        const mid = Math.floor(oldElements.length / 2);
        const oldHash = hashElement(oldElements[0]) + hashElement(oldElements[mid]) + hashElement(oldElements[oldElements.length - 1]);
        const newHash = hashElement(newElements[0]) + hashElement(newElements[mid]) + hashElement(newElements[newElements.length - 1]);

        return oldHash === newHash;
    }

    /**
     * Set search filter
     */
    setSearchFilter(query) {
        this.searchQuery = query.toLowerCase().trim();
        this.applyFilters();
        this.render();
    }

    /**
     * Set filter options
     */
    setFilterOptions(options) {
        if (options.clickableOnly !== undefined) {
            this.showClickableOnly = options.clickableOnly;
        }
        if (options.textOnly !== undefined) {
            this.showTextOnly = options.textOnly;
        }
        this.applyFilters();
        this.render();
    }

    /**
     * Apply search and filter
     */
    applyFilters() {
        this.filteredElements = this.elements.filter(el => {
            // Clickable filter
            if (this.showClickableOnly && !el.clickable) {
                return false;
            }

            // Text only filter
            if (this.showTextOnly && !el.text?.trim()) {
                return false;
            }

            // Search filter
            if (this.searchQuery) {
                const text = (el.text || '').toLowerCase();
                const className = (el.class || '').toLowerCase();
                const resourceId = (el.resource_id || '').toLowerCase();

                return text.includes(this.searchQuery) ||
                       className.includes(this.searchQuery) ||
                       resourceId.includes(this.searchQuery);
            }

            return true;
        });
    }

    /**
     * Render the element tree
     */
    render() {
        if (!this.container) return;

        if (this.filteredElements.length === 0) {
            this.container.innerHTML = `
                <div class="tree-empty">
                    ${this.searchQuery ? 'No matching elements' : 'No elements detected'}
                </div>
            `;
            return;
        }

        // Group elements by class for tree structure
        const grouped = this.groupByClass(this.filteredElements);

        let html = '<div class="element-tree">';

        for (const [className, elements] of Object.entries(grouped)) {
            const shortClass = className.split('.').pop();
            const hasClickable = elements.some(e => e.clickable);

            html += `
                <div class="tree-group">
                    <div class="tree-group-header" data-class="${className}">
                        <span class="tree-toggle">▶</span>
                        <span class="tree-class ${hasClickable ? 'has-clickable' : ''}">${shortClass}</span>
                        <span class="tree-count">(${elements.length})</span>
                    </div>
                    <div class="tree-group-items" style="display: none;">
                        ${elements.map((el, idx) => this.renderElement(el, idx)).join('')}
                    </div>
                </div>
            `;
        }

        html += '</div>';
        this.container.innerHTML = html;

        // Wire up event handlers
        this.attachEventHandlers();
    }

    /**
     * Group elements by class name
     */
    groupByClass(elements) {
        const grouped = {};
        for (const el of elements) {
            const className = el.class || 'Unknown';
            if (!grouped[className]) {
                grouped[className] = [];
            }
            grouped[className].push(el);
        }
        return grouped;
    }

    /**
     * Render a single element with name and value details
     */
    renderElement(element, index) {
        const text = element.text?.trim() || '';
        const resourceId = element.resource_id || '';
        const shortId = resourceId.split('/').pop() || '';
        const contentDesc = element.content_desc || '';
        const isClickable = element.clickable;
        const bounds = element.bounds;

        // Primary display: text > content-desc > resource-id > generic
        const primaryText = text || contentDesc || shortId || `Element ${index + 1}`;
        const truncatedPrimary = primaryText.length > 35 ? primaryText.substring(0, 32) + '...' : primaryText;

        // Build info lines for details
        const infoLines = [];
        if (shortId) {
            infoLines.push(`<span class="tree-detail-label">id:</span> <span class="tree-detail-value">${this.escapeHtml(shortId)}</span>`);
        }
        if (contentDesc && contentDesc !== text) {
            const truncDesc = contentDesc.length > 30 ? contentDesc.substring(0, 27) + '...' : contentDesc;
            infoLines.push(`<span class="tree-detail-label">desc:</span> <span class="tree-detail-value">${this.escapeHtml(truncDesc)}</span>`);
        }
        if (text && text !== contentDesc) {
            const truncText = text.length > 30 ? text.substring(0, 27) + '...' : text;
            infoLines.push(`<span class="tree-detail-label">text:</span> <span class="tree-detail-value">"${this.escapeHtml(truncText)}"</span>`);
        }

        const detailsHtml = infoLines.length > 0
            ? `<div class="tree-element-details">${infoLines.join('<br>')}</div>`
            : '';

        return `
            <div class="tree-element ${isClickable ? 'clickable' : ''}"
                 data-index="${index}"
                 data-bounds='${JSON.stringify(bounds)}'>
                <div class="tree-element-content">
                    <span class="tree-element-text" title="${this.escapeHtml(primaryText)}">${this.escapeHtml(truncatedPrimary)}</span>
                    ${isClickable ? '<span class="tree-badge clickable-badge">tap</span>' : ''}
                </div>
                ${detailsHtml}
                <div class="tree-element-actions">
                    ${isClickable ? `<button class="tree-btn tree-btn-tap" title="Add tap action">👆</button>` : ''}
                    <button class="tree-btn tree-btn-sensor" title="Add as sensor">📊</button>
                    <button class="tree-btn tree-btn-timestamp" title="Mark as timestamp (for refresh validation)">⏱️</button>
                    <button class="tree-btn tree-btn-highlight" title="Highlight on screen">🔍</button>
                </div>
            </div>
        `;
    }

    /**
     * Escape HTML special characters
     */
    escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    /**
     * Attach event handlers to rendered elements
     */
    attachEventHandlers() {
        // Toggle group expand/collapse
        this.container.querySelectorAll('.tree-group-header').forEach(header => {
            header.addEventListener('click', () => {
                const items = header.nextElementSibling;
                const toggle = header.querySelector('.tree-toggle');
                const isExpanded = items.style.display !== 'none';

                items.style.display = isExpanded ? 'none' : 'block';
                toggle.textContent = isExpanded ? '▶' : '▼';
            });
        });

        // Element action buttons
        this.container.querySelectorAll('.tree-btn-tap').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const element = this.getElementFromButton(btn);
                if (element && this.onTap) {
                    this.onTap(element);
                }
            });
        });

        this.container.querySelectorAll('.tree-btn-sensor').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const element = this.getElementFromButton(btn);
                if (element && this.onSensor) {
                    this.onSensor(element);
                }
            });
        });

        this.container.querySelectorAll('.tree-btn-timestamp').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const element = this.getElementFromButton(btn);
                if (element && this.onTimestamp) {
                    this.onTimestamp(element);
                }
            });
        });

        this.container.querySelectorAll('.tree-btn-highlight').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const element = this.getElementFromButton(btn);
                if (element && this.onHighlight) {
                    this.highlightElement(element);
                    this.onHighlight(element);
                }
            });
        });

        // Hover to highlight
        this.container.querySelectorAll('.tree-element').forEach(el => {
            el.addEventListener('mouseenter', () => {
                const element = this.getElementFromRow(el);
                if (element && this.onHighlight) {
                    this.onHighlight(element);
                }
            });
        });
    }

    /**
     * Get element data from button click
     */
    getElementFromButton(btn) {
        const row = btn.closest('.tree-element');
        return this.getElementFromRow(row);
    }

    /**
     * Get element data from row
     */
    getElementFromRow(row) {
        if (!row) return null;
        const bounds = JSON.parse(row.dataset.bounds || '{}');
        const index = parseInt(row.dataset.index, 10);
        return { ...this.filteredElements[index], bounds };
    }

    /**
     * Highlight an element and scroll to it
     */
    highlightElement(element) {
        // Remove previous highlight
        this.container.querySelectorAll('.tree-element.highlighted').forEach(el => {
            el.classList.remove('highlighted');
        });

        // Find and highlight the element row
        const rows = this.container.querySelectorAll('.tree-element');
        for (const row of rows) {
            const rowBounds = JSON.parse(row.dataset.bounds || '{}');
            if (rowBounds.x === element.bounds?.x && rowBounds.y === element.bounds?.y) {
                row.classList.add('highlighted');
                row.scrollIntoView({ behavior: 'smooth', block: 'center' });

                // Expand parent group if collapsed
                const group = row.closest('.tree-group');
                if (group) {
                    const items = group.querySelector('.tree-group-items');
                    const toggle = group.querySelector('.tree-toggle');
                    if (items.style.display === 'none') {
                        items.style.display = 'block';
                        toggle.textContent = '▼';
                    }
                }
                break;
            }
        }

        this.highlightedElement = element;
    }

    /**
     * Clear all highlights
     */
    clearHighlight() {
        this.container.querySelectorAll('.tree-element.highlighted').forEach(el => {
            el.classList.remove('highlighted');
        });
        this.highlightedElement = null;
    }
}

// Export for module use
export default ElementTree;

// Export for global access (dual export pattern)
window.ElementTree = ElementTree;
