/**
 * Tutorial Module
 * Non-blocking guided walkthrough with event-based progression
 *
 * Key features:
 * - Overlay is purely visual (pointer-events: none)
 * - Users can interact with ALL page elements while tutorial is active
 * - Steps auto-advance when completion events fire
 * - Manual Next button always available as fallback
 */

const STORAGE_KEY = 'visual-mapper-tutorial';
const SESSION_KEY = 'visual-mapper-tutorial-active';

// Tutorial step definitions with event-based completion
const TUTORIAL_STEPS = [
    {
        id: 'welcome',
        type: 'modal',
        title: 'Welcome to Visual Mapper!',
        description: 'This quick guide will show you how to connect your Android device and create sensors from any app. You can interact with everything normally - the tutorial will follow along!',
        icon: '&#128075;'  // Wave emoji
    },
    {
        id: 'devices',
        page: 'devices.html',
        selector: '#tab-connect .section-card:first-child, .section-card:has(#connectBtn)',
        fallbackSelector: '.section-card, .container',
        title: 'Connect Your Device',
        description: 'Enter your Android device\'s IP address and port from Wireless Debugging settings, then click Connect. The tutorial will auto-advance when connected!',
        position: 'right',
        completionEvent: 'tutorial:device-connected',
        completionCheck: async () => {
            // Check if any device is connected
            try {
                const response = await fetch('/api/devices');
                const devices = await response.json();
                return devices.some(d => d.status === 'online' || d.connected);
            } catch {
                return false;
            }
        },
        waitingMessage: 'Waiting for device connection...',
        successMessage: 'Device connected!',
        autoAdvance: true,
        autoAdvanceDelay: 1500
    },
    {
        id: 'pairing',
        page: 'devices.html',
        selector: '.section-card:has(#pairBtn), #pairBtn',
        fallbackSelector: '.section-card',
        title: 'Pair with Code (Optional)',
        description: 'If you need to pair first, enter the pairing code from your Android device. Otherwise, click Next to continue.',
        position: 'right',
        optional: true,
        completionEvent: 'tutorial:device-paired',
        waitingMessage: 'Enter pairing code if needed...',
        autoAdvance: false  // Manual advance - pairing is optional
    },
    {
        id: 'flow-start',
        page: 'flows.html',
        selector: '.flow-actions .btn-primary, .flow-actions button:first-child',
        fallbackSelector: '.flow-header, .flow-container',
        title: 'Create Your First Flow',
        description: 'Flows automate app navigation to capture data. Click "Create Flow" to start the wizard!',
        position: 'bottom',
        completionEvent: 'tutorial:page-navigate',
        completionCheck: () => window.location.pathname.includes('flow-wizard'),
        waitingMessage: 'Click Create Flow to continue...',
        successMessage: 'Starting flow wizard!',
        autoAdvance: true,
        autoAdvanceDelay: 500
    },
    {
        id: 'wizard-device',
        page: 'flow-wizard.html',
        selector: '#step1 #deviceList, #step1.wizard-step',
        fallbackSelector: '.wizard-container',
        title: 'Select Your Device',
        description: 'Click on your connected device to use it for this flow.',
        position: 'right',
        completionEvent: 'tutorial:wizard-device-selected',
        waitingMessage: 'Select a device...',
        successMessage: 'Device selected!',
        autoAdvance: true,
        autoAdvanceDelay: 1000
    },
    {
        id: 'wizard-app',
        page: 'flow-wizard.html',
        selector: '#step2 #appList, #step2.wizard-step.active',
        fallbackSelector: '.wizard-container',
        title: 'Select an App',
        description: 'Choose the Android app you want to capture data from. Visual Mapper will navigate to this app automatically.',
        position: 'bottom',
        completionEvent: 'tutorial:wizard-app-selected',
        waitingMessage: 'Select an app...',
        successMessage: 'App selected!',
        autoAdvance: true,
        autoAdvanceDelay: 1000
    },
    {
        id: 'wizard-record',
        page: 'flow-wizard.html',
        selector: '#step3 .screenshot-panel, #step3 .recording-layout',
        fallbackSelector: '.wizard-container',
        title: 'Record Navigation',
        description: 'Tap on the screen preview to record navigation steps. Navigate to the screen with the data you want to capture. Click Next when ready.',
        position: 'left',
        completionEvent: 'tutorial:wizard-step-recorded',
        waitingMessage: 'Tap screen to record steps...',
        autoAdvance: false  // Manual - user may record multiple steps
    },
    {
        id: 'wizard-sensor',
        page: 'flow-wizard.html',
        selector: '#elementTreeContainer, .panel-tab[data-tab="elements"], .tree-content',
        fallbackSelector: '#step3 .recording-layout',
        title: 'Create a Sensor',
        description: 'Click on a UI element to capture it as a sensor. This could be battery level, temperature, or any text value on screen.',
        position: 'left',
        completionEvent: 'tutorial:sensor-created',
        waitingMessage: 'Click a UI element to create sensor...',
        successMessage: 'Sensor created!',
        autoAdvance: true,
        autoAdvanceDelay: 1500
    },
    {
        id: 'sensors',
        page: 'sensors.html',
        selector: '#sensorsContainer, .container .card',
        fallbackSelector: '.container',
        title: 'Your Sensors',
        description: 'Your sensors are now publishing to Home Assistant via MQTT! They update automatically when your flow runs.',
        position: 'bottom',
        autoAdvance: false  // End of main flow
    },
    {
        id: 'complete',
        type: 'modal',
        title: 'You\'re All Set!',
        description: 'You\'ve learned the basics of Visual Mapper. Create more flows and sensors to capture data from any Android app. Click the ? button anytime to restart this guide.',
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
        this.currentTarget = null;
        this.completionListeners = [];
        this.pollingInterval = null;
        this.stepCompleted = false;
        this.mutationObserver = null;
        this.positionUpdateInterval = null;
        this.lastTargetRect = null;
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

        // Listen for page navigation (for cross-page steps)
        this.setupNavigationListener();

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

        // Create overlay container (purely visual, non-blocking)
        this.overlay = document.createElement('div');
        this.overlay.className = 'tutorial-overlay';

        // Create spotlight (purely visual)
        this.spotlight = document.createElement('div');
        this.spotlight.className = 'tutorial-spotlight';
        this.overlay.appendChild(this.spotlight);

        // Create tooltip (only interactive element)
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

        // Clean up previous step
        this.cleanupCompletionListener();
        this.removeTargetHighlight();
        this.stopPositionWatcher();
        this.stepCompleted = false;

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
        let target = this.findTargetElement(step.selector);
        if (!target && step.fallbackSelector) {
            target = this.findTargetElement(step.fallbackSelector);
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

        // Position spotlight (visual only)
        this.positionSpotlight(target);

        // Add highlight to target element
        this.addTargetHighlight(target);

        // Show tooltip
        this.showTooltip(step, target);

        // Setup completion listener for this step
        this.setupCompletionListener(step);

        // Start watching for DOM changes to update position
        this.startPositionWatcher();
    }

    /**
     * Find target element, handling complex selectors
     */
    findTargetElement(selector) {
        if (!selector) return null;

        // Try each selector in a comma-separated list
        const selectors = selector.split(',').map(s => s.trim());
        for (const sel of selectors) {
            try {
                const element = document.querySelector(sel);
                if (element && element.offsetParent !== null) {
                    return element;
                }
            } catch (e) {
                // Invalid selector, skip
                console.warn('[Tutorial] Invalid selector:', sel);
            }
        }
        return null;
    }

    /**
     * Add highlight class to target element
     */
    addTargetHighlight(element) {
        if (!element) return;
        this.currentTarget = element;
        element.classList.add('tutorial-target');

        // Scroll element into view if needed
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    /**
     * Remove highlight from previous target
     */
    removeTargetHighlight() {
        if (this.currentTarget) {
            this.currentTarget.classList.remove('tutorial-target');
            this.currentTarget = null;
        }

        // Also clean up any orphaned highlights
        document.querySelectorAll('.tutorial-target').forEach(el => {
            el.classList.remove('tutorial-target');
        });
    }

    /**
     * Setup completion listener for auto-advancement
     */
    setupCompletionListener(step) {
        // Listen for custom completion event
        if (step.completionEvent) {
            const handler = (e) => {
                console.log('[Tutorial] Completion event received:', step.completionEvent);
                this.handleStepComplete(step);
            };
            window.addEventListener(step.completionEvent, handler);
            this.completionListeners.push({ event: step.completionEvent, handler });
        }

        // Setup polling for completion check
        if (step.completionCheck) {
            this.pollingInterval = setInterval(async () => {
                if (this.stepCompleted) return;

                try {
                    const completed = await step.completionCheck();
                    if (completed) {
                        console.log('[Tutorial] Completion check passed for step:', step.id);
                        this.handleStepComplete(step);
                    }
                } catch (e) {
                    console.warn('[Tutorial] Completion check error:', e);
                }
            }, 1000);
        }
    }

    /**
     * Clean up completion listeners
     */
    cleanupCompletionListener() {
        // Remove event listeners
        this.completionListeners.forEach(({ event, handler }) => {
            window.removeEventListener(event, handler);
        });
        this.completionListeners = [];

        // Clear polling interval
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
    }

    /**
     * Handle step completion (show success, auto-advance)
     */
    handleStepComplete(step) {
        if (this.stepCompleted) return;
        this.stepCompleted = true;

        // Show success message if defined
        if (step.successMessage) {
            this.showSuccessMessage(step.successMessage);
        }

        // Auto-advance if enabled
        if (step.autoAdvance) {
            const delay = step.autoAdvanceDelay || 1500;
            setTimeout(() => {
                if (this.isActive && this.currentStepIndex === this.steps.indexOf(step)) {
                    this.nextStep();
                }
            }, delay);
        }
    }

    /**
     * Show success message in tooltip
     */
    showSuccessMessage(message) {
        const successEl = document.createElement('div');
        successEl.className = 'tutorial-success';
        successEl.innerHTML = `
            <span class="tutorial-success-icon">&#10003;</span>
            <span>${message}</span>
        `;

        // Insert at top of tooltip content
        const description = this.tooltip.querySelector('.tutorial-description');
        if (description) {
            description.parentNode.insertBefore(successEl, description);
        }

        // Remove waiting indicator
        const waiting = this.tooltip.querySelector('.tutorial-waiting');
        if (waiting) {
            waiting.remove();
        }
    }

    /**
     * Setup listener for page navigation
     */
    setupNavigationListener() {
        // Listen for navigation events
        const handler = () => {
            window.dispatchEvent(new CustomEvent('tutorial:page-navigate'));
        };

        // Check for navigation on next tick
        const checkNavigation = () => {
            const step = this.steps[this.currentStepIndex];
            if (step && step.completionCheck) {
                step.completionCheck().then(result => {
                    if (result) {
                        this.handleStepComplete(step);
                    }
                });
            }
        };

        // Use beforeunload as a hint, actual check on new page load
        window.addEventListener('beforeunload', handler);
        this.completionListeners.push({ event: 'beforeunload', handler });
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
     * Position the spotlight on target element (visual only)
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

        // Waiting indicator
        const waitingHtml = step.waitingMessage ? `
            <div class="tutorial-waiting">
                <div class="tutorial-waiting-spinner"></div>
                <span>${step.waitingMessage}</span>
            </div>
        ` : '';

        const html = `
            <div class="tutorial-header">
                <span class="tutorial-step-indicator">Step ${currentNum} of ${totalSteps}</span>
                <button class="tutorial-close" onclick="window.tutorialInstance.skip()">&times;</button>
            </div>
            <h3 class="tutorial-title">${step.title}</h3>
            <p class="tutorial-description">${step.description}</p>
            ${waitingHtml}
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
     * Reset tutorial state (for testing or restart)
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

        const target = this.findTargetElement(step.selector) ||
                       this.findTargetElement(step.fallbackSelector);
        if (target) {
            this.positionSpotlight(target);
            this.positionTooltip(target, step.position || 'bottom');
        }
    }

    /**
     * Start watching for DOM changes and position updates
     * Uses MutationObserver + interval fallback for reliable tracking
     */
    startPositionWatcher() {
        this.stopPositionWatcher(); // Clean up any existing watchers

        const step = this.steps[this.currentStepIndex];
        if (!step || step.type === 'modal') return;

        // Update position function
        const updatePosition = () => {
            if (!this.isActive) return;

            const target = this.findTargetElement(step.selector) ||
                           this.findTargetElement(step.fallbackSelector);

            if (!target) return;

            const rect = target.getBoundingClientRect();

            // Check if position actually changed
            if (this.lastTargetRect &&
                this.lastTargetRect.top === rect.top &&
                this.lastTargetRect.left === rect.left &&
                this.lastTargetRect.width === rect.width &&
                this.lastTargetRect.height === rect.height) {
                return; // No change, skip update
            }

            // Save current rect
            this.lastTargetRect = {
                top: rect.top,
                left: rect.left,
                width: rect.width,
                height: rect.height
            };

            // Update spotlight and tooltip positions
            this.positionSpotlight(target);
            this.positionTooltip(target, step.position || 'bottom');

            // Update target highlight if element changed
            if (this.currentTarget !== target) {
                this.removeTargetHighlight();
                this.addTargetHighlight(target);
            }
        };

        // MutationObserver for DOM structure changes
        this.mutationObserver = new MutationObserver((mutations) => {
            // Debounce updates - use requestAnimationFrame
            requestAnimationFrame(updatePosition);
        });

        // Observe the entire body for changes
        this.mutationObserver.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['class', 'style', 'hidden']
        });

        // Interval fallback for position changes not caught by MutationObserver
        // (e.g., CSS transitions, scroll position changes)
        this.positionUpdateInterval = setInterval(updatePosition, 200);

        console.log('[Tutorial] Position watcher started');
    }

    /**
     * Stop watching for DOM changes
     */
    stopPositionWatcher() {
        if (this.mutationObserver) {
            this.mutationObserver.disconnect();
            this.mutationObserver = null;
        }

        if (this.positionUpdateInterval) {
            clearInterval(this.positionUpdateInterval);
            this.positionUpdateInterval = null;
        }

        this.lastTargetRect = null;
        console.log('[Tutorial] Position watcher stopped');
    }

    /**
     * Destroy tutorial overlay
     */
    destroy() {
        this.isActive = false;
        window.removeEventListener('resize', this.boundHandleResize);

        // Stop position watcher
        this.stopPositionWatcher();

        // Clean up completion listeners
        this.cleanupCompletionListener();

        // Remove target highlight
        this.removeTargetHighlight();

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
