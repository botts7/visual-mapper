/**
 * Visual Mapper - Shared Navbar Component
 * Injects consistent navigation across all pages
 */

const NavBar = {
    // Navigation items configuration
    items: [
        // High priority - always visible
        { href: 'main.html', label: 'Dashboard', priority: 'high' },
        { href: 'devices.html', label: 'Devices', priority: 'high' },
        { href: 'sensors.html', label: 'Sensors', priority: 'high' },
        // Medium priority - hidden on mobile
        { href: 'actions.html', label: 'Actions', priority: 'med' },
        { href: 'flows.html', label: 'Flows', priority: 'med' },
        { href: 'performance.html', label: 'Performance', priority: 'med' },
        { href: 'diagnostic.html', label: 'Diagnostics', priority: 'med' },
        // Low priority - hidden on tablet
        { href: 'navigation-learn.html', label: 'Learn Nav', priority: 'med' },
        { href: 'live-stream.html', label: 'Live Stream', priority: 'low' },
        { href: 'dev.html', label: 'Dev Tools', priority: 'low' },
    ],

    // Get current page filename
    getCurrentPage() {
        const path = window.location.pathname;
        const page = path.split('/').pop() || 'index.html';
        // Map index.html to main.html
        return page === 'index.html' ? 'main.html' : page;
    },

    // Get version from global or meta tag
    getVersion() {
        if (window.APP_VERSION) return window.APP_VERSION;
        const meta = document.querySelector('meta[name="version"]');
        return meta ? meta.content : '0.0.0';
    },

    // Generate navbar HTML
    generateHTML() {
        const currentPage = this.getCurrentPage();
        const version = this.getVersion();

        const navItems = this.items.map(item => {
            const isActive = item.href === currentPage;
            return `<li class="nav-priority-${item.priority}"><a href="${item.href}"${isActive ? ' class="active"' : ''}>${item.label}</a></li>`;
        }).join('\n            ');

        return `
        <ul>
            ${navItems}
            <li class="version">v${version}</li>
            <li class="nav-logo"><img src="favicon.svg" alt="Visual Mapper"></li>
            <li id="themeToggleContainer">
                <button id="themeToggle" class="theme-toggle" title="Toggle dark/light mode" aria-label="Toggle theme">
                    <span class="theme-icon-dark">🌙</span>
                    <span class="theme-icon-light">☀️</span>
                </button>
            </li>
        </ul>`;
    },

    // Initialize theme toggle
    initThemeToggle() {
        const toggle = document.getElementById('themeToggle');
        if (!toggle) return;

        // Get saved theme or detect system preference
        const savedTheme = localStorage.getItem('theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const currentTheme = savedTheme || (prefersDark ? 'dark' : 'light');

        // Apply initial theme
        this.setTheme(currentTheme);

        // Toggle handler
        toggle.addEventListener('click', () => {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            this.setTheme(isDark ? 'light' : 'dark');
        });

        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (!localStorage.getItem('theme')) {
                this.setTheme(e.matches ? 'dark' : 'light');
            }
        });
    },

    // Set theme
    setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);

        // Update toggle button appearance
        const toggle = document.getElementById('themeToggle');
        if (toggle) {
            toggle.setAttribute('data-theme', theme);
        }
    },

    // Inject navbar into page
    inject(targetSelector = 'nav') {
        let nav = document.querySelector(targetSelector);

        // If no nav element, create one at start of body
        if (!nav) {
            nav = document.createElement('nav');
            document.body.insertBefore(nav, document.body.firstChild);
        }

        // Clear existing content and inject new
        nav.innerHTML = this.generateHTML();

        // Initialize theme toggle
        this.initThemeToggle();

        console.log('[NavBar] Initialized');
    },

    // Initialize - call this on page load
    init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.inject());
        } else {
            this.inject();
        }
    }
};

// Auto-initialize if loaded as module
if (typeof window !== 'undefined') {
    window.NavBar = NavBar;
}

// Export for ES modules
export default NavBar;
