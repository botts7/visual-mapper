/**
 * Visual Mapper - Theme Toggle Module
 * Version: 0.0.4 (Phase 3)
 *
 * Handles light/dark theme switching with localStorage persistence.
 */

class ThemeToggle {
    constructor() {
        this.STORAGE_KEY = 'visual-mapper-theme';
        this.currentTheme = this._loadTheme();

        console.log('[ThemeToggle] Initialized with theme:', this.currentTheme);
    }

    /**
     * Initialize theme from localStorage or system preference
     * @private
     */
    _loadTheme() {
        // Check localStorage first
        const stored = localStorage.getItem(this.STORAGE_KEY);
        if (stored) {
            return stored;
        }

        // Fall back to system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }

        return 'light';
    }

    /**
     * Apply current theme to document
     */
    apply() {
        if (this.currentTheme === 'dark') {
            document.body.classList.add('dark-mode');
        } else {
            document.body.classList.remove('dark-mode');
        }

        console.log('[ThemeToggle] Applied theme:', this.currentTheme);
    }

    /**
     * Toggle between light and dark themes
     */
    toggle() {
        this.currentTheme = this.currentTheme === 'light' ? 'dark' : 'light';
        localStorage.setItem(this.STORAGE_KEY, this.currentTheme);
        this.apply();

        console.log('[ThemeToggle] Toggled to theme:', this.currentTheme);

        return this.currentTheme;
    }

    /**
     * Get current theme
     */
    getCurrentTheme() {
        return this.currentTheme;
    }

    /**
     * Set specific theme
     * @param {string} theme - 'light' or 'dark'
     */
    setTheme(theme) {
        if (theme !== 'light' && theme !== 'dark') {
            console.error('[ThemeToggle] Invalid theme:', theme);
            return;
        }

        this.currentTheme = theme;
        localStorage.setItem(this.STORAGE_KEY, this.currentTheme);
        this.apply();

        console.log('[ThemeToggle] Set theme:', this.currentTheme);
    }

    /**
     * Create toggle button
     * @param {Function} onChange - Callback when theme changes
     * @returns {HTMLElement} Toggle button element
     */
    createToggleButton(onChange) {
        const button = document.createElement('button');
        button.id = 'themeToggle';
        button.style.cssText = `
            padding: 8px 16px;
            background: rgba(255, 255, 255, 0.1);
            color: white;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: background-color 0.2s;
        `;

        const updateButtonText = () => {
            button.textContent = this.currentTheme === 'light' ? '🌙 Dark' : '☀️ Light';
        };

        updateButtonText();

        button.addEventListener('click', () => {
            const newTheme = this.toggle();
            updateButtonText();

            if (onChange) {
                onChange(newTheme);
            }
        });

        button.addEventListener('mouseenter', () => {
            button.style.background = 'rgba(255, 255, 255, 0.2)';
        });

        button.addEventListener('mouseleave', () => {
            button.style.background = 'rgba(255, 255, 255, 0.1)';
        });

        return button;
    }
}

// ES6 export
export default ThemeToggle;

// Global export for non-module usage
window.ThemeToggle = ThemeToggle;
