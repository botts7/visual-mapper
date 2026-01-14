/**
 * Tutorial Module
 * Interactive step-by-step guide with spotlight highlighting
 */

const STORAGE_KEY = 'visual-mapper-tutorial';
const SESSION_KEY = 'visual-mapper-tutorial-active';

// Tutorial step definitions
const TUTORIAL_STEPS = [
    {
        id: 'welcome',
        type: 'modal',
        title: 'Welcome to Visual Mapper!',
        description: 'This quick tutorial will show you how to connect your Android device and create sensors from any app. It takes about 2 minutes.',
        icon: '&#128075;'  // Wave emoji
    },
    {
        id: 'devices',
        page: 'devices.html',
        selector: '.device-connect-btn, .btn-primary, [data-action="connect"]',
        fallbackSelector: '.card',
        title: 'Connect Your Device',
        description: 'First, connect your Android device via WiFi ADB. Make sure Wireless Debugging is enabled in Developer Options on your Android device.',
        position: 'bottom',
        screenshot: '01-devices.png'
    },
    {
        id: 'pairing',
        page: 'devices.html',
        selector: '.pair-dialog, .modal, #pairModal',
        fallbackSelector: '.card',
        title: 'Pair with Code',
        description: 'Enter the pairing code shown on your Android device. You can find this in Settings → Developer Options → Wireless Debugging → Pair device with pairing code.',
        position: 'right',
        screenshot: '02-pairing.png',
        optional: true  // Skip if modal not visible
    },
    {
        id: 'flow-start',
        page: 'flow-wizard.html',
        selector: '.wizard-step-1, #step1, .step-content:first-child',
        fallbackSelector: '.wizard-container, .container',
        title: 'Create a Flow',
        description: 'Flows let you automate app navigation to capture data. Click "Create New Flow" to start recording your first automation.',
        position: 'right',
        screenshot: '03-flow-start.png'
    },
    {
        id: 'select-app',
        page: 'flow-wizard.html',
        selector: '.app-selector, .app-list, #appList',
        fallbackSelector: '.wizard-container',
        title: 'Select an App',
        description: 'Choose the Android app you want to capture data from. Visual Mapper will navigate to this app automatically when the flow runs.',
        position: 'bottom',
        screenshot: '04-select-app.png'
    },
    {
        id: 'record-nav',
        page: 'flow-wizard.html',
        selector: '.canvas-container, #screenshotCanvas, .screenshot-container',
        fallbackSelector: '.wizard-container',
        title: 'Record Navigation',
        description: 'Tap on the screen preview to record navigation steps. Each tap becomes a step in your flow. Navigate to where your data is displayed.',
        position: 'left',
        screenshot: '05-record-nav.png'
    },
    {
        id: 'select-element',
        page: 'flow-wizard.html',
        selector: '.element-panel, .element-tree, #elementPanel',
        fallbackSelector: '.wizard-container',
        title: 'Select an Element',
        description: 'Click on the UI element you want to capture as a sensor. This could be a battery percentage, temperature, status text, or any visible value.',
        position: 'left',
        screenshot: '06-select-element.png'
    },
    {
        id: 'sensors',
        page: 'sensors.html',
        selector: '.sensor-list, .sensor-card, #sensorList',
        fallbackSelector: '.container .card',
        title: 'Your Sensors',
        description: 'Your sensors are now publishing to Home Assistant via MQTT! They update automatically each time your flow runs.',
        position: 'bottom',
        screenshot: '07-sensors.png'
    },
    {
        id: 'complete',
        type: 'modal',
        title: 'You\'re All Set!',
        description: 'You\'ve learned the basics of Visual Mapper. Create more flows and sensors to capture data from any Android app.',
        icon: '&#127881;'  // Party emoji
    }
];

class Tutorial {
    constructor() {
        this.steps = TUTORIAL_STEPS;
        this.currentStepIndex = 0;
        this.isActive = false;
        this.overlay = null;
        this.spotlight = null;
        this.tooltip = null;
        this.boundHandleResize = this.handleResize.bind(this);
    }

    /**
     * Check if user has completed the tutorial
     */
    hasCompleted() {
        const data = this.getStorageData();
        return data.completed === true;
    }

    /**
     * Check if tutorial should auto-start (first visit)
     */
    shouldAutoStart() {
        const data = this.getStorageData();
        return !data.completed && !data.skipped;
    }

    /**
     * Check if tutorial is currently in progress (across pages)
     */
    isInProgress() {
        return sessionStorage.getItem(SESSION_KEY) === 'true';
    }

    /**
     * Get storage data
     */
    getStorageData() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
        } catch {
            return {};
        }
    }

    /**
     * Save storage data
     */
    saveStorageData(data) {
        const current = this.getStorageData();
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...current, ...data }));
    }

    /**
     * Start the tutorial
     */
    start(fromStep = 0) {
        this.currentStepIndex = fromStep;
        this.isActive = true;
        sessionStorage.setItem(SESSION_KEY, 'true');

        // Create DOM elements
        this.createOverlay();

        // Show first step
        this.showStep(this.currentStepIndex);

        // Listen for resize
        window.addEventListener('resize', this.boundHandleResize);

        console.log('[Tutorial] Started from step', fromStep);
    }

    /**
     * Resume tutorial on page load if in progress
     */
    resume() {
        if (!this.isInProgress()) return false;

        const data = this.getStorageData();
        const currentPage = window.location.pathname.split('/').pop() || 'index.html';

        // Find the step for this page
        let stepIndex = data.currentStepIndex || 0;

        // Check if we're on the right page for this step
        const step = this.steps[stepIndex];
        if (step && step.page && !currentPage.includes(step.page.replace('.html', ''))) {
            // Wrong page, try to find step for current page
            const pageStep = this.steps.findIndex(s => s.page && currentPage.includes(s.page.replace('.html', '')));
            if (pageStep !== -1) {
                stepIndex = pageStep;
            }
        }

        this.start(stepIndex);
        return true;
    }

    /**
     * Create overlay DOM elements
     */
    createOverlay() {
        // Remove existing if any
        this.destroy();

        // Create overlay container
        this.overlay = document.createElement('div');
        this.overlay.className = 'tutorial-overlay';

        // Create spotlight
        this.spotlight = document.createElement('div');
        this.spotlight.className = 'tutorial-spotlight';
        this.overlay.appendChild(this.spotlight);

        // Create tooltip
        this.tooltip = document.createElement('div');
        this.tooltip.className = 'tutorial-tooltip';
        this.overlay.appendChild(this.tooltip);

        document.body.appendChild(this.overlay);

        // Activate with slight delay for animation
        requestAnimationFrame(() => {
            this.overlay.classList.add('active');
        });
    }

    /**
     * Show a specific step
     */
    showStep(index) {
        const step = this.steps[index];
        if (!step) {
            this.complete();
            return;
        }

        this.currentStepIndex = index;
        this.saveStorageData({ currentStepIndex: index });

        // Handle modal-type steps (welcome/complete)
        if (step.type === 'modal') {
            this.showModal(step);
            return;
        }

        // Check if we're on the right page
        const currentPage = window.location.pathname.split('/').pop() || 'index.html';
        if (step.page && !currentPage.includes(step.page.replace('.html', ''))) {
            // Navigate to the correct page
            window.location.href = step.page;
            return;
        }

        // Find target element
        let target = document.querySelector(step.selector);
        if (!target && step.fallbackSelector) {
            target = document.querySelector(step.fallbackSelector);
        }

        // Skip optional steps if element not found
        if (!target && step.optional) {
            this.nextStep();
            return;
        }

        // Wait for element if not found
        if (!target) {
            setTimeout(() => this.showStep(index), 500);
            return;
        }

        // Position spotlight
        this.positionSpotlight(target);

        // Show tooltip
        this.showTooltip(step, target);
    }

    /**
     * Show modal (for welcome/complete steps)
     */
    showModal(step) {
        // Hide spotlight
        if (this.spotlight) {
            this.spotlight.style.opacity = '0';
        }

        const isWelcome = step.id === 'welcome';
        const isComplete = step.id === 'complete';

        const modalHtml = `
            <div class="tutorial-welcome">
                <div class="tutorial-welcome-icon">${step.icon}</div>
                <h2>${step.title}</h2>
                <p>${step.description}</p>
                <div class="tutorial-welcome-actions">
                    ${isWelcome ? `
                        <button class="tutorial-btn tutorial-btn-secondary" onclick="window.tutorialInstance.skip()">Skip Tutorial</button>
                        <button class="tutorial-btn tutorial-btn-primary" onclick="window.tutorialInstance.nextStep()">Start Tutorial</button>
                    ` : `
                        <button class="tutorial-btn tutorial-btn-primary" onclick="window.tutorialInstance.complete()">Done</button>
                    `}
                </div>
            </div>
        `;

        if (this.tooltip) {
            this.tooltip.innerHTML = modalHtml;
            this.tooltip.className = 'tutorial-tooltip';
            this.tooltip.style.cssText = '';
            this.tooltip.classList.add('visible');
        }
    }

    /**
     * Position the spotlight on target element
     */
    positionSpotlight(target) {
        const rect = target.getBoundingClientRect();
        const padding = 8;

        this.spotlight.style.opacity = '1';
        this.spotlight.style.top = `${rect.top - padding + window.scrollY}px`;
        this.spotlight.style.left = `${rect.left - padding}px`;
        this.spotlight.style.width = `${rect.width + padding * 2}px`;
        this.spotlight.style.height = `${rect.height + padding * 2}px`;
    }

    /**
     * Show tooltip for a step
     */
    showTooltip(step, target) {
        const totalSteps = this.steps.filter(s => s.type !== 'modal').length;
        const currentNum = this.steps.slice(0, this.currentStepIndex + 1).filter(s => s.type !== 'modal').length;

        // Generate progress dots
        const dots = this.steps
            .filter(s => s.type !== 'modal')
            .map((s, i) => {
                const stepNum = i + 1;
                let className = 'tutorial-progress-dot';
                if (stepNum < currentNum) className += ' completed';
                if (stepNum === currentNum) className += ' current';
                return `<div class="${className}"></div>`;
            })
            .join('');

        const html = `
            <div class="tutorial-header">
                <span class="tutorial-step-indicator">Step ${currentNum} of ${totalSteps}</span>
                <button class="tutorial-close" onclick="window.tutorialInstance.skip()">&times;</button>
            </div>
            <h3 class="tutorial-title">${step.title}</h3>
            <p class="tutorial-description">${step.description}</p>
            ${step.screenshot ? `<img class="tutorial-screenshot" src="images/guide/${step.screenshot}" alt="${step.title}" onerror="this.style.display='none'">` : ''}
            <div class="tutorial-nav">
                <div class="tutorial-progress">${dots}</div>
                <div class="tutorial-buttons">
                    ${this.currentStepIndex > 1 ? `<button class="tutorial-btn tutorial-btn-secondary" onclick="window.tutorialInstance.prevStep()">Back</button>` : ''}
                    <button class="tutorial-btn tutorial-btn-primary" onclick="window.tutorialInstance.nextStep()">
                        ${this.currentStepIndex < this.steps.length - 2 ? 'Next' : 'Finish'}
                    </button>
                </div>
            </div>
            <span class="tutorial-skip" onclick="window.tutorialInstance.skip()">Skip tutorial</span>
        `;

        this.tooltip.innerHTML = html;
        this.tooltip.setAttribute('data-position', step.position || 'bottom');

        // Position tooltip
        this.positionTooltip(target, step.position || 'bottom');

        // Show with animation
        this.tooltip.classList.remove('visible');
        requestAnimationFrame(() => {
            this.tooltip.classList.add('visible');
        });
    }

    /**
     * Position tooltip relative to target
     */
    positionTooltip(target, position) {
        const rect = target.getBoundingClientRect();
        const tooltipRect = this.tooltip.getBoundingClientRect();
        const gap = 16;
        const scrollY = window.scrollY;

        let top, left;

        switch (position) {
            case 'top':
                top = rect.top + scrollY - tooltipRect.height - gap;
                left = rect.left + (rect.width - tooltipRect.width) / 2;
                break;
            case 'bottom':
                top = rect.bottom + scrollY + gap;
                left = rect.left + (rect.width - tooltipRect.width) / 2;
                break;
            case 'left':
                top = rect.top + scrollY + (rect.height - tooltipRect.height) / 2;
                left = rect.left - tooltipRect.width - gap;
                break;
            case 'right':
                top = rect.top + scrollY + (rect.height - tooltipRect.height) / 2;
                left = rect.right + gap;
                break;
            default:
                top = rect.bottom + scrollY + gap;
                left = rect.left;
        }

        // Keep tooltip within viewport
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        if (left < 16) left = 16;
        if (left + tooltipRect.width > viewportWidth - 16) {
            left = viewportWidth - tooltipRect.width - 16;
        }

        if (top < scrollY + 16) top = scrollY + 16;
        if (top + tooltipRect.height > scrollY + viewportHeight - 16) {
            top = scrollY + viewportHeight - tooltipRect.height - 16;
        }

        this.tooltip.style.top = `${top}px`;
        this.tooltip.style.left = `${left}px`;
    }

    /**
     * Go to next step
     */
    nextStep() {
        this.showStep(this.currentStepIndex + 1);
    }

    /**
     * Go to previous step
     */
    prevStep() {
        if (this.currentStepIndex > 0) {
            this.showStep(this.currentStepIndex - 1);
        }
    }

    /**
     * Skip the tutorial
     */
    skip() {
        this.saveStorageData({ skipped: true });
        this.destroy();
        sessionStorage.removeItem(SESSION_KEY);
        console.log('[Tutorial] Skipped');
    }

    /**
     * Complete the tutorial
     */
    complete() {
        this.saveStorageData({ completed: true, completedAt: Date.now() });
        this.destroy();
        sessionStorage.removeItem(SESSION_KEY);
        console.log('[Tutorial] Completed');
    }

    /**
     * Reset tutorial state (for testing)
     */
    reset() {
        localStorage.removeItem(STORAGE_KEY);
        sessionStorage.removeItem(SESSION_KEY);
        console.log('[Tutorial] Reset');
    }

    /**
     * Handle window resize
     */
    handleResize() {
        if (!this.isActive) return;

        const step = this.steps[this.currentStepIndex];
        if (!step || step.type === 'modal') return;

        const target = document.querySelector(step.selector) ||
                       document.querySelector(step.fallbackSelector);
        if (target) {
            this.positionSpotlight(target);
            this.positionTooltip(target, step.position || 'bottom');
        }
    }

    /**
     * Destroy tutorial overlay
     */
    destroy() {
        this.isActive = false;
        window.removeEventListener('resize', this.boundHandleResize);

        if (this.overlay && this.overlay.parentNode) {
            this.overlay.classList.remove('active');
            setTimeout(() => {
                if (this.overlay && this.overlay.parentNode) {
                    this.overlay.parentNode.removeChild(this.overlay);
                }
            }, 300);
        }

        this.overlay = null;
        this.spotlight = null;
        this.tooltip = null;
    }
}

// Create singleton instance
const tutorialInstance = new Tutorial();

// Expose to window for onclick handlers
window.tutorialInstance = tutorialInstance;

// Export for ES6 modules
export default tutorialInstance;

// Also export class for testing
export { Tutorial, TUTORIAL_STEPS };
