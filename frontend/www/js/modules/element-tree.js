/**
 * Element Tree Module
 * Visual Mapper v0.0.6
 *
 * Hierarchical view of UI elements with search, filtering, and actions
 * v0.0.6: Redesigned to match Smart tab style with cards and alternative names
 */

class ElementTree {
    constructor(container, options = {}) {
        this.container = container;
        this.elements = [];
        this.filteredElements = [];
        this.searchQuery = '';
        this.highlightedElement = null;
        this.selectedIndices = new Set();

        // Callbacks
        this.onTap = options.onTap || null;
        this.onSensor = options.onSensor || null;
        this.onTimestamp = options.onTimestamp || null;
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
            'View': '◻️',
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
        return shortClass
            .replace(/^AppCompat/, '')
            .replace(/^Material/, '')
            .replace(/Compat$/, '');
    }

    /**
     * Get all available names/identifiers for an element
     */
    getAlternativeNames(element) {
        const alternatives = [];

        if (element.text?.trim()) {
            alternatives.push({
                value: element.text.trim(),
                source: 'text',
                icon: '📝',
                label: 'Text'
            });
        }

        if (element.content_desc?.trim()) {
            alternatives.push({
                value: element.content_desc.trim(),
                source: 'desc',
                icon: '💬',
                label: 'Description'
            });
        }

        if (element.resource_id) {
            const shortId = element.resource_id.split('/').pop();
            if (shortId) {
                alternatives.push({
                    value: shortId,
                    source: 'id',
                    icon: '🏷️',
                    label: 'Resource ID'
                });
            }
        }

        return alternatives;
    }

    /**
     * Get primary display name
     */
    getPrimaryName(element, index) {
        const alts = this.getAlternativeNames(element);
        if (alts.length > 0) {
            return alts[0];
        }
        return {
            value: `Element ${index + 1}`,
            source: 'index',
            icon: '◻️',
            label: 'Index'
        };
    }

    /**
     * Update elements and re-render
     */
    setElements(elements) {
        const newElements = elements || [];

        if (this._isUpdating) {
            this._pendingElements = newElements;
            return;
        }

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

            if (this._pendingElements !== null) {
                const pending = this._pendingElements;
                this._pendingElements = null;
                this.setElements(pending);
            }
        }
    }

    /**
     * Compare two element arrays
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
            if (this.showClickableOnly && !el.clickable) {
                return false;
            }

            if (this.showTextOnly && !el.text?.trim()) {
                return false;
            }

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
     * Render the element list
     */
    render() {
        if (!this.container) return;

        if (this.filteredElements.length === 0) {
            this.container.innerHTML = `
                <div class="element-empty">
                    <div class="element-empty-icon">📱</div>
                    <div class="element-empty-text">${this.searchQuery ? 'No matching elements' : 'No elements detected'}</div>
                    <div class="element-empty-hint">${this.searchQuery ? 'Try a different search term' : 'Elements will appear when a screen is loaded'}</div>
                </div>
            `;
            return;
        }

        // Sort: clickable first, then by position
        const sorted = [...this.filteredElements].sort((a, b) => {
            if (a.clickable && !b.clickable) return -1;
            if (!a.clickable && b.clickable) return 1;
            const yDiff = (a.bounds?.y || 0) - (b.bounds?.y || 0);
            if (Math.abs(yDiff) > 20) return yDiff;
            return (a.bounds?.x || 0) - (b.bounds?.x || 0);
        });

        let html = '<div class="element-list">';
        sorted.forEach((el, idx) => {
            html += this.renderElement(el, idx);
        });
        html += '</div>';

        this.container.innerHTML = html;
        this.attachEventHandlers();
    }

    /**
     * Render a single element card (matching Smart tab style)
     */
    renderElement(element, index) {
        const primaryName = this.getPrimaryName(element, index);
        const alternatives = this.getAlternativeNames(element);
        const typeName = this.getTypeName(element.class);
        const typeIcon = this.getTypeIcon(element.class);
        const isClickable = element.clickable;
        const bounds = element.bounds;
        const isSelected = this.selectedIndices.has(index);

        // Truncate display value
        const maxLen = 32;
        const displayValue = primaryName.value.length > maxLen
            ? primaryName.value.substring(0, maxLen - 1) + '…'
            : primaryName.value;

        // Build alternatives dropdown if multiple names available
        let alternativesHtml = '';
        if (alternatives.length > 1) {
            const options = alternatives.map(alt => {
                const truncVal = alt.value.length > 25 ? alt.value.substring(0, 22) + '…' : alt.value;
                return `<option value="${this.escapeHtml(alt.source)}" title="${this.escapeHtml(alt.value)}">${alt.icon} ${this.escapeHtml(truncVal)}</option>`;
            }).join('');

            alternativesHtml = `
                <div class="element-alt-names">
                    <select class="alt-name-select" data-index="${index}" title="Alternative identifiers">
                        ${options}
                    </select>
                </div>
            `;
        }

        return `
            <div class="element-item ${isSelected ? 'selected' : ''} ${isClickable ? 'clickable' : ''}"
                 data-index="${index}"
                 data-bounds='${JSON.stringify(bounds)}'>
                <label class="element-checkbox">
                    <input type="checkbox" ${isSelected ? 'checked' : ''}>
                </label>
                <div class="element-icon">${typeIcon}</div>
                <div class="element-details">
                    <div class="element-name">${this.escapeHtml(displayValue)}</div>
                    ${alternativesHtml}
                    <div class="element-meta">
                        <span class="element-type-badge">${typeName}</span>
                        ${isClickable ? '<span class="element-clickable-badge">Clickable</span>' : ''}
                    </div>
                </div>
                <div class="element-buttons">
                    ${isClickable ? `<button class="btn-tap" data-index="${index}" title="Tap this element">👆 Tap</button>` : ''}
                    <button class="btn-sensor" data-index="${index}" title="Add as sensor">📊</button>
                    <button class="btn-highlight" data-index="${index}" title="Highlight on screen">🔍</button>
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
     * Attach event handlers
     */
    attachEventHandlers() {
        // Checkbox selection
        this.container.querySelectorAll('.element-checkbox input').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                e.stopPropagation();
                const item = e.target.closest('.element-item');
                const index = parseInt(item.dataset.index, 10);

                if (e.target.checked) {
                    this.selectedIndices.add(index);
                    item.classList.add('selected');
                } else {
                    this.selectedIndices.delete(index);
                    item.classList.remove('selected');
                }
            });
        });

        // Tap button
        this.container.querySelectorAll('.btn-tap').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const element = this.getElementFromButton(btn);
                if (element && this.onTap) {
                    this.onTap(element);
                }
            });
        });

        // Sensor button
        this.container.querySelectorAll('.btn-sensor').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const element = this.getElementFromButton(btn);
                if (element && this.onSensor) {
                    this.onSensor(element);
                }
            });
        });

        // Highlight button
        this.container.querySelectorAll('.btn-highlight').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const element = this.getElementFromButton(btn);
                if (element) {
                    this.highlightElement(element);
                    if (this.onHighlight) {
                        this.onHighlight(element);
                    }
                }
            });
        });

        // Hover to highlight
        this.container.querySelectorAll('.element-item').forEach(item => {
            item.addEventListener('mouseenter', () => {
                const element = this.getElementFromRow(item);
                if (element && this.onHighlight) {
                    this.onHighlight(element);
                }
            });
        });

        // Click row to select
        this.container.querySelectorAll('.element-item').forEach(item => {
            item.addEventListener('click', (e) => {
                // Don't trigger if clicking button, checkbox, or dropdown
                if (e.target.closest('button') || e.target.closest('input') || e.target.closest('select')) return;

                const checkbox = item.querySelector('.element-checkbox input');
                checkbox.checked = !checkbox.checked;
                checkbox.dispatchEvent(new Event('change', { bubbles: true }));
            });
        });

        // Alternative name dropdown change
        this.container.querySelectorAll('.alt-name-select').forEach(select => {
            select.addEventListener('click', (e) => {
                e.stopPropagation();
            });
        });
    }

    /**
     * Get element data from button
     */
    getElementFromButton(btn) {
        const item = btn.closest('.element-item');
        return this.getElementFromRow(item);
    }

    /**
     * Get element data from row
     */
    getElementFromRow(row) {
        if (!row) return null;
        const bounds = JSON.parse(row.dataset.bounds || '{}');
        const index = parseInt(row.dataset.index, 10);

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
     * Highlight an element
     */
    highlightElement(element) {
        this.container.querySelectorAll('.element-item.highlighted').forEach(el => {
            el.classList.remove('highlighted');
        });

        const rows = this.container.querySelectorAll('.element-item');
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
        this.container.querySelectorAll('.element-item.highlighted').forEach(el => {
            el.classList.remove('highlighted');
        });
        this.highlightedElement = null;
    }

    /**
     * Get selected elements
     */
    getSelectedElements() {
        const sorted = [...this.filteredElements].sort((a, b) => {
            if (a.clickable && !b.clickable) return -1;
            if (!a.clickable && b.clickable) return 1;
            const yDiff = (a.bounds?.y || 0) - (b.bounds?.y || 0);
            if (Math.abs(yDiff) > 20) return yDiff;
            return (a.bounds?.x || 0) - (b.bounds?.x || 0);
        });

        return Array.from(this.selectedIndices).map(idx => sorted[idx]).filter(Boolean);
    }

    /**
     * Select all elements
     */
    selectAll() {
        const sorted = [...this.filteredElements];
        sorted.forEach((_, idx) => this.selectedIndices.add(idx));
        this.render();
    }

    /**
     * Clear selection
     */
    clearSelection() {
        this.selectedIndices.clear();
        this.render();
    }
}

// Export for module use
export default ElementTree;

// Export for global access
window.ElementTree = ElementTree;
