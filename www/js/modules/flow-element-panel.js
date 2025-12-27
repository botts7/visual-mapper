/**
 * Flow Element Panel Module
 * Visual Mapper v0.0.5
 *
 * Handles element sidebar with search and filtering
 */

export class FlowElementPanel {
    constructor(panelElement) {
        this.panel = panelElement;
        this.allElements = [];
        this.filtersInitialized = false;

        // Callbacks for user actions
        this.onTap = null;
        this.onType = null;
        this.onSensor = null;
    }

    /**
     * Set action callbacks
     */
    setCallbacks({ onTap, onType, onSensor }) {
        this.onTap = onTap;
        this.onType = onType;
        this.onSensor = onSensor;
    }

    /**
     * Update panel with new elements
     */
    updateElements(elements) {
        if (!this.panel) {
            console.warn('[FlowElementPanel] Panel element not found');
            return;
        }

        // Store all elements for filtering
        this.allElements = elements || [];

        // Setup search and filter event listeners (once)
        if (!this.filtersInitialized) {
            this.setupFilters();
            this.filtersInitialized = true;
        }

        // Apply filters and render
        this.renderFilteredElements();
    }

    /**
     * Setup search and filter event listeners
     */
    setupFilters() {
        const searchInput = document.getElementById('elementSearchInput');
        const clickableFilter = document.getElementById('filterSidebarClickable');
        const textFilter = document.getElementById('filterSidebarText');

        if (searchInput) {
            searchInput.addEventListener('input', () => this.renderFilteredElements());
        }
        if (clickableFilter) {
            clickableFilter.addEventListener('change', () => this.renderFilteredElements());
        }
        if (textFilter) {
            textFilter.addEventListener('change', () => this.renderFilteredElements());
        }

        console.log('[FlowElementPanel] Filters initialized');
    }

    /**
     * Render filtered elements based on search and filters
     */
    renderFilteredElements() {
        if (!this.panel) return;

        const searchInput = document.getElementById('elementSearchInput');
        const clickableFilter = document.getElementById('filterSidebarClickable');
        const textFilter = document.getElementById('filterSidebarText');

        const searchTerm = searchInput?.value.toLowerCase() || '';
        const showClickable = clickableFilter?.checked !== false;
        const showWithText = textFilter?.checked !== false;

        if (!this.allElements || this.allElements.length === 0) {
            this.panel.innerHTML = '<div class="empty-state">No elements detected in screenshot</div>';
            return;
        }

        // Apply filters (OR logic: show if matches ANY checked filter)
        let filteredElements = this.allElements.filter(el => {
            // If both filters are off, show all
            if (!showClickable && !showWithText) return true;

            // Show if matches any checked filter
            const isClickable = el.clickable;
            const hasText = el.text && el.text.trim().length > 0;

            if (showClickable && isClickable) return true;
            if (showWithText && hasText) return true;

            return false;
        });

        // Apply search
        if (searchTerm) {
            filteredElements = filteredElements.filter(el => {
                const displayText = (el.text || el.content_desc || el.resource_id || '').toLowerCase();
                return displayText.includes(searchTerm);
            });
        }

        console.log(`[FlowElementPanel] Rendering ${filteredElements.length} elements (${this.allElements.length} total)`);

        // Render elements
        this.panel.innerHTML = filteredElements.map((el, index) => {
            const displayText = el.text || el.content_desc || el.resource_id?.split('/').pop() || `Element ${index}`;
            const isClickable = el.clickable === true || el.clickable === 'true';
            const icon = isClickable ? '🔘' : '📝';
            const typeLabel = isClickable ? 'Clickable' : 'Text';

            // Determine preview value (what would be captured as sensor)
            const previewValue = el.text || el.content_desc || el.resource_id || '';
            const hasPreview = previewValue.trim().length > 0;
            const truncatedPreview = previewValue.length > 50
                ? previewValue.substring(0, 50) + '...'
                : previewValue;

            return `
                <div class="element-item" data-element-index="${index}">
                    <div class="element-item-header">
                        <span class="element-icon">${icon}</span>
                        <div class="element-info">
                            <div class="element-text">${displayText}</div>
                            <div class="element-meta">${typeLabel} • ${el.class?.split('.').pop() || 'Unknown'}</div>
                        </div>
                    </div>
                    ${hasPreview ? `
                    <div class="element-preview" title="${previewValue}">
                        <span class="preview-label">Preview:</span>
                        <span class="preview-value">${truncatedPreview}</span>
                    </div>
                    ` : ''}
                    <div class="element-actions">
                        <button class="btn-element-action btn-tap" data-index="${index}" title="Add tap step">
                            👆 Tap
                        </button>
                        <button class="btn-element-action btn-type" data-index="${index}" title="Add type step">
                            ⌨️ Type
                        </button>
                        <button class="btn-element-action btn-sensor" data-index="${index}" title="Add sensor capture">
                            📊 Sensor
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        // Bind action buttons
        this.bindActionButtons(filteredElements);
    }

    /**
     * Bind click handlers to action buttons
     */
    bindActionButtons(filteredElements) {
        // Tap buttons
        this.panel.querySelectorAll('.btn-tap').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                const element = filteredElements[index];
                if (this.onTap && element) {
                    this.onTap(element);
                }
            });
        });

        // Type buttons
        this.panel.querySelectorAll('.btn-type').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                const element = filteredElements[index];
                if (this.onType && element) {
                    this.onType(element);
                }
            });
        });

        // Sensor buttons
        this.panel.querySelectorAll('.btn-sensor').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.index);
                const element = filteredElements[index];
                if (this.onSensor && element) {
                    this.onSensor(element, index);
                }
            });
        });
    }

    /**
     * Clear the panel
     */
    clear() {
        if (this.panel) {
            this.panel.innerHTML = '';
        }
        this.allElements = [];
    }

    /**
     * Get all elements
     */
    getAllElements() {
        return this.allElements;
    }
}

// Dual export
export default FlowElementPanel;
window.FlowElementPanel = FlowElementPanel;
