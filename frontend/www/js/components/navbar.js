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
        { href: 'services.html', label: 'Services', priority: 'med' },
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
                    <span class="theme-icon">🌙</span> Dark
                </button>
            </li>
        </ul>`;
    },

    // Initialize mobile hamburger menu
    initMobileNav() {
        const nav = document.querySelector('nav');
        const navMenu = document.querySelector('nav ul');
        if (!nav || !navMenu) return;

        // Create hamburger button
        const hamburger = document.createElement('button');
        hamburger.className = 'hamburger';
        hamburger.setAttribute('aria-label', 'Toggle menu');
        hamburger.setAttribute('aria-expanded', 'false');
        for (let i = 0; i < 3; i++) {
            hamburger.appendChild(document.createElement('span'));
        }

        // Insert at beginning of nav
        nav.insertBefore(hamburger, nav.firstChild);

        let isOpen = false;

        const openMenu = () => {
            isOpen = true;
            hamburger.classList.add('active');
            navMenu.classList.add('active');
            nav.classList.add('menu-open');
            hamburger.setAttribute('aria-expanded', 'true');
            document.body.style.overflow = 'hidden';
        };

        const closeMenu = () => {
            isOpen = false;
            hamburger.classList.remove('active');
            navMenu.classList.remove('active');
            nav.classList.remove('menu-open');
            hamburger.setAttribute('aria-expanded', 'false');
            document.body.style.overflow = '';
        };

        // Event listeners
        hamburger.addEventListener('click', (e) => {
            e.stopPropagation();
            isOpen ? closeMenu() : openMenu();
        });

        nav.addEventListener('click', (e) => {
            if (e.target === nav && isOpen) closeMenu();
        });

        navMenu.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', closeMenu);
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && isOpen) closeMenu();
        });

        window.addEventListener('resize', () => {
            if (window.innerWidth > 768 && isOpen) closeMenu();
        });

        console.log('[NavBar] Mobile navigation initialized');
    },

    // Initialize theme toggle
    initThemeToggle() {
        const toggle = document.getElementById('themeToggle');
        if (!toggle) return;

        // Get saved theme or detect system preference
        const savedTheme = localStorage.getItem('visual-mapper-theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const currentTheme = savedTheme || (prefersDark ? 'dark' : 'light');

        // Apply initial theme
        this.setTheme(currentTheme);

        // Toggle handler
        toggle.addEventListener('click', () => {
            const isDark = document.body.classList.contains('dark-mode');
            this.setTheme(isDark ? 'light' : 'dark');
        });

        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (!localStorage.getItem('visual-mapper-theme')) {
                this.setTheme(e.matches ? 'dark' : 'light');
            }
        });

        console.log('[NavBar] Theme toggle initialized, current theme:', currentTheme);
    },

    // Set theme
    setTheme(theme) {
        // Apply theme using body class (matches existing CSS)
        if (theme === 'dark') {
            document.body.classList.add('dark-mode');
        } else {
            document.body.classList.remove('dark-mode');
        }

        localStorage.setItem('visual-mapper-theme', theme);

        // Update toggle button text
        const toggle = document.getElementById('themeToggle');
        if (toggle) {
            toggle.innerHTML = theme === 'dark'
                ? '<span class="theme-icon">☀️</span> Light'
                : '<span class="theme-icon">🌙</span> Dark';
        }
    },

    // Inject navbar into page
    inject(targetSelector = 'nav') {
        // Skip navbar on onboarding page (standalone full-screen wizard)
        const currentPage = window.location.pathname.split('/').pop() || 'index.html';
        if (currentPage === 'onboarding.html') {
            console.log('[NavBar] Skipping navbar on onboarding page');
            return;
        }

        let nav = document.querySelector(targetSelector);

        // If no nav element, create one at start of body
        if (!nav) {
            nav = document.createElement('nav');
            document.body.insertBefore(nav, document.body.firstChild);
        }

        // Clear existing content and inject new
        nav.innerHTML = this.generateHTML();

        // Initialize components
        this.initThemeToggle();
        this.initMobileNav();

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
