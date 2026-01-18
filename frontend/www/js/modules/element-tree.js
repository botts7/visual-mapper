/**
 * Element Tree Module
 * Visual Mapper v0.0.5
 *
 * Hierarchical view of UI elements with search, filtering, and actions
 * v0.0.5: Redesigned for cleaner, more intuitive display
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

        // Race condition prevention
        this._isUpdating = false;
        this._pendingElements = null;

        // Element type icons mapping
        this.typeIcons = {
            'Button': '🔘',
            'ImageButton': '🖼️',
            'TextView': '📝',
            'EditText': '✏️',
            'ImageView': '🖼️',
            'CheckBox': '☑️',
            'RadioButton': '⭕',
            'Switch': '🔀',
            'ToggleButton': '🔄',
            'SeekBar': '📊',
            'ProgressBar': '⏳',
            'Spinner': '📋',
            'ListView': '📃',
            'RecyclerView': '📜',
            'ScrollView': '📜',
            'WebView': '🌐',
            'VideoView': '🎬',
            'CardView': '🃏',
            'TabLayout': '📑',
            'ViewPager': '📖',
            'FloatingActionButton': '⭐',
            'Toolbar': '🔧',
            'NavigationView': '🧭',
            'BottomNavigationView': '⬇️',
            'default': '◻️'
        };

        console.log('[ElementTree] Initialized');
    }

    /**
     * Get icon for element type
     */
    getTypeIcon(className) {
        if (!className) return this.typeIcons.default;
        const shortClass = className.split('.').pop();

        // Check for exact match first
        if (this.typeIcons[shortClass]) {
            return this.typeIcons[shortClass];
        }

        // Check for partial matches
        for (const [key, icon] of Object.entries(this.typeIcons)) {
            if (shortClass.includes(key)) {
                return icon;
            }
        }

        // Layout types
        if (shortClass.includes('Layout') || shortClass.includes('Group') || shortClass.includes('Container')) {
            return '📦';
        }

        return this.typeIcons.default;
    }

    /**
     * Get short readable type name
     */
    getTypeName(className) {
        if (!className) return 'View';
        const shortClass = className.split('.').pop();
        // Remove common prefixes/suffixes for cleaner display
        return shortClass
            .replace(/^AppCompat/, '')
            .replace(/^Material/, '')
            .replace(/Compat$/, '');
    }

    /**
     * Get best display name for element
     */
    getDisplayName(element, index) {
        const text = element.text?.trim();
        const contentDesc = element.content_desc?.trim();
        const resourceId = element.resource_id;
        const shortId = resourceId ? resourceId.split('/').pop() : '';

        // Priority: text > content-desc > resource-id > generic
        if (text && text.length > 0) {
            return { name: text, source: 'text' };
        }
        if (contentDesc && contentDesc.length > 0) {
            return { name: contentDesc, source: 'desc' };
        }
        if (shortId && shortId.length > 0) {
            // Convert resource IDs to readable format: btn_submit -> "Submit"
            const readable = this.formatResourceId(shortId);
            return { name: readable, source: 'id', rawId: shortId };
        }

        return { name: `Element ${index + 1}`, source: 'index' };
    }

    /**
     * Format resource ID to readable name
     */
    formatResourceId(id) {
        if (!id) return '';
        // Remove common prefixes
        let clean = id
            .replace(/^(btn_|txt_|img_|et_|tv_|iv_|cb_|rb_|sw_|ll_|rl_|fl_|cl_|rv_)/, '')
            .replace(/_/g, ' ');
        // Capitalize first letter of each word
        return clean.split(' ')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    /**
     * Update elements and re-render (only if changed)
     * Includes race condition prevention to avoid concurrent updates
     */
    setElements(elements) {
        const newElements = elements || [];

        // If already updating, queue the new elements for later
        if (this._isUpdating) {
            this._pendingElements = newElements;
            return;
        }

        // Skip re-render if elements haven't changed (prevents dropdown reset)
        if (this._elementsMatch(this.elements, newElements)) {
            return;
        }

        this._isUpdating = true;
        try {
            this.elements = newElements;
            this.applyFilters();
            this.render();
        } finally {
            this._isUpdating = false;

            // Process any pending update that came in during rendering
            if (this._pendingElements !== null) {
                const pending = this._pendingElements;
                this._pendingElements = null;
                this.setElements(pending);
            }
        }
    }

    /**
     * Compare two element arrays to check if they're functionally the same
     */
    _elementsMatch(oldElements, newElements) {
        if (!oldElements || !newElements) return false;
        if (oldElements.length !== newElements.length) return false;
        if (oldElements.length === 0) return true;

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
                const contentDesc = (el.content_desc || '').toLowerCase();

                return text.includes(this.searchQuery) ||
                       className.includes(this.searchQuery) ||
                       resourceId.includes(this.searchQuery) ||
                       contentDesc.includes(this.searchQuery);
            }

            return true;
        });
    }

    /**
     * Render the element tree with new cleaner design
     */
    render() {
        if (!this.container) return;

        if (this.filteredElements.length === 0) {
            this.container.innerHTML = `
                <div class="tree-empty">
                    <div class="tree-empty-icon">📱</div>
                    <div class="tree-empty-text">${this.searchQuery ? 'No matching elements' : 'No elements detected'}</div>
                    <div class="tree-empty-hint">${this.searchQuery ? 'Try a different search term' : 'Elements will appear when a screen is loaded'}</div>
                </div>
            `;
            return;
        }

        // Sort elements: clickable first, then by position (top to bottom, left to right)
        const sorted = [...this.filteredElements].sort((a, b) => {
            // Clickable elements first
            if (a.clickable && !b.clickable) return -1;
            if (!a.clickable && b.clickable) return 1;
            // Then by Y position (top to bottom)
            const yDiff = (a.bounds?.y || 0) - (b.bounds?.y || 0);
            if (Math.abs(yDiff) > 20) return yDiff;
            // Then by X position (left to right)
            return (a.bounds?.x || 0) - (b.bounds?.x || 0);
        });

        let html = '<div class="element-tree">';

        sorted.forEach((el, idx) => {
            html += this.renderElement(el, idx);
        });

        html += '</div>';
        this.container.innerHTML = html;

        // Wire up event handlers
        this.attachEventHandlers();
    }

    /**
     * Render a single element with clean, compact design
     */
    renderElement(element, index) {
        const displayInfo = this.getDisplayName(element, index);
        const typeName = this.getTypeName(element.class);
        const typeIcon = this.getTypeIcon(element.class);
        const isClickable = element.clickable;
        const bounds = element.bounds;
        const resourceId = element.resource_id;
        const shortId = resourceId ? resourceId.split('/').pop() : '';

        // Truncate name if too long
        const maxLen = 28;
        const truncatedName = displayInfo.name.length > maxLen
            ? displayInfo.name.substring(0, maxLen - 1) + '…'
            : displayInfo.name;

        // Build subtitle - show ID if name came from text/desc
        let subtitle = '';
        if (displayInfo.source === 'text' && shortId) {
            subtitle = shortId;
        } else if (displayInfo.source === 'desc' && shortId) {
            subtitle = shortId;
        } else if (displayInfo.source === 'id') {
            subtitle = typeName;
        } else {
            subtitle = typeName;
        }

        return `
            <div class="tree-element ${isClickable ? 'clickable' : ''}"
                 data-index="${index}"
                 data-bounds='${JSON.stringify(bounds)}'>
                <div class="tree-element-main">
                    <span class="tree-element-icon">${typeIcon}</span>
                    <div class="tree-element-info">
                        <span class="tree-element-name" title="${this.escapeHtml(displayInfo.name)}">${this.escapeHtml(truncatedName)}</span>
                        <span class="tree-element-subtitle">${this.escapeHtml(subtitle)}</span>
                    </div>
                </div>
                <div class="tree-element-right">
                    ${isClickable ? '<span class="tree-badge clickable-badge">tap</span>' : ''}
                    <div class="tree-element-actions">
                        ${isClickable ? `<button class="tree-btn tree-btn-tap" title="Add tap action">👆</button>` : ''}
                        <button class="tree-btn tree-btn-sensor" title="Add as sensor">📊</button>
                        <button class="tree-btn tree-btn-highlight" title="Highlight on screen">🔍</button>
                    </div>
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

        // Click on row to highlight
        this.container.querySelectorAll('.tree-element').forEach(el => {
            el.addEventListener('click', (e) => {
                // Don't trigger if clicking a button
                if (e.target.closest('.tree-btn')) return;

                const element = this.getElementFromRow(el);
                if (element) {
                    this.highlightElement(element);
                    if (this.onHighlight) {
                        this.onHighlight(element);
                    }
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

        // Find the element in filteredElements that matches this position
        const sorted = [...this.filteredElements].sort((a, b) => {
            if (a.clickable && !b.clickable) return -1;
            if (!a.clickable && b.clickable) return 1;
            const yDiff = (a.bounds?.y || 0) - (b.bounds?.y || 0);
            if (Math.abs(yDiff) > 20) return yDiff;
            return (a.bounds?.x || 0) - (b.bounds?.x || 0);
        });

        return { ...sorted[index], bounds };
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
