/**
 * Visual Mapper - Mobile Navigation Module
 * Version: 0.0.4 (Phase 3)
 *
 * Handles hamburger menu toggle for mobile navigation.
 */

class MobileNav {
    constructor() {
        this.hamburger = null;
        this.nav = null;
        this.navMenu = null;
        this.isOpen = false;

        console.log('[MobileNav] Initialized');
    }

    /**
     * Initialize mobile navigation
     */
    init() {
        // Create hamburger button
        this.hamburger = this._createHamburger();

        // Get nav and menu elements
        this.nav = document.querySelector('nav');
        this.navMenu = document.querySelector('nav ul');

        if (!this.nav || !this.navMenu) {
            console.warn('[MobileNav] Navigation elements not found');
            return;
        }

        // Insert hamburger at the beginning of nav
        this.nav.insertBefore(this.hamburger, this.nav.firstChild);

        // Setup event listeners
        this._setupEventListeners();

        console.log('[MobileNav] Mobile navigation initialized');
    }

    /**
     * Create hamburger button element
     * @private
     */
    _createHamburger() {
        const button = document.createElement('button');
        button.className = 'hamburger';
        button.setAttribute('aria-label', 'Toggle menu');
        button.setAttribute('aria-expanded', 'false');

        // Create three spans for hamburger icon
        for (let i = 0; i < 3; i++) {
            const span = document.createElement('span');
            button.appendChild(span);
        }

        return button;
    }

    /**
     * Setup event listeners
     * @private
     */
    _setupEventListeners() {
        // Hamburger click
        this.hamburger.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggle();
        });

        // Close on overlay click
        this.nav.addEventListener('click', (e) => {
            if (e.target === this.nav && this.isOpen) {
                this.close();
            }
        });

        // Close on menu link click
        const menuLinks = this.navMenu.querySelectorAll('a');
        menuLinks.forEach(link => {
            link.addEventListener('click', () => {
                this.close();
            });
        });

        // Close on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });

        // Handle window resize
        let resizeTimer;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                // Close menu if resizing to desktop
                if (window.innerWidth > 768 && this.isOpen) {
                    this.close();
                }
            }, 250);
        });
    }

    /**
     * Toggle menu open/closed
     */
    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }

    /**
     * Open menu
     */
    open() {
        this.isOpen = true;
        this.hamburger.classList.add('active');
        this.navMenu.classList.add('active');
        this.nav.classList.add('menu-open');
        this.hamburger.setAttribute('aria-expanded', 'true');

        // Prevent body scroll when menu is open
        document.body.style.overflow = 'hidden';

        console.log('[MobileNav] Menu opened');
    }

    /**
     * Close menu
     */
    close() {
        this.isOpen = false;
        this.hamburger.classList.remove('active');
        this.navMenu.classList.remove('active');
        this.nav.classList.remove('menu-open');
        this.hamburger.setAttribute('aria-expanded', 'false');

        // Restore body scroll
        document.body.style.overflow = '';

        console.log('[MobileNav] Menu closed');
    }
}

// ES6 export
export default MobileNav;

// Global export for non-module usage
window.MobileNav = MobileNav;
