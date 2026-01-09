/**
 * Flow Step Manager Module
 * Visual Mapper v0.0.7
 *
 * Handles flow steps list display and events
 * v0.0.7: Add navigation issue detection with warning and fix button
 * v0.0.6: Add move up/down buttons for reordering steps
 */

export class FlowStepManager {
    constructor(stepsListElement) {
        this.stepsList = stepsListElement;
        this.setupListeners();
    }

    /**
     * Setup event listeners for step add/remove/move
     */
    setupListeners() {
        window.addEventListener('flowStepAdded', (e) => {
            this.onStepAdded(e.detail);
        });

        window.addEventListener('flowStepRemoved', (e) => {
            this.onStepRemoved(e.detail);
        });

        window.addEventListener('flowStepMoved', (e) => {
            this.onStepMoved(e.detail);
        });
    }

    /**
     * Handle step added event
     */
    onStepAdded({ step, index }) {
        if (!this.stepsList) return;

        // Get total count to determine if move buttons should be disabled
        const totalSteps = this.stepsList.querySelectorAll('.flow-step-item').length + 1;
        const isFirst = index === 0;
        const isLast = index === totalSteps - 1;

        const stepHtml = `
            <div class="flow-step-item" data-step-index="${index}">
                <div class="step-number-badge">${index + 1}</div>
                <div class="step-content">
                    <div class="step-description">${step.description}</div>
                </div>
                <div class="step-actions">
                    <button class="btn btn-sm btn-move-up" onclick="window.flowWizard.recorder.moveStep(${index}, ${index - 1})" title="Move up" ${isFirst ? 'disabled' : ''}>↑</button>
                    <button class="btn btn-sm btn-move-down" onclick="window.flowWizard.recorder.moveStep(${index}, ${index + 1})" title="Move down" ${isLast ? 'disabled' : ''}>↓</button>
                    <button class="btn btn-sm btn-delete" onclick="window.flowWizard.recorder.removeStep(${index})" title="Delete step">✕</button>
                </div>
            </div>
        `;

        this.stepsList.insertAdjacentHTML('beforeend', stepHtml);

        // Update previous last item's down button (it's no longer last)
        this.updateMoveButtons();
    }

    /**
     * Handle step moved event - re-render the entire list
     */
    onStepMoved({ fromIndex, toIndex, step }) {
        // Re-render all steps to update indices and button states
        const steps = window.flowWizard?.recorder?.getSteps() || [];
        this.render(steps);
    }

    /**
     * Handle step removed event
     */
    onStepRemoved({ index }) {
        if (!this.stepsList) return;

        const stepEl = this.stepsList.querySelector(`[data-step-index="${index}"]`);
        if (stepEl) stepEl.remove();

        // Renumber remaining steps
        this.stepsList.querySelectorAll('.flow-step-item').forEach((el, i) => {
            el.dataset.stepIndex = i;
            el.querySelector('.step-number-badge').textContent = i + 1;
        });
    }

    /**
     * Clear all steps
     */
    clear() {
        if (this.stepsList) {
            this.stepsList.innerHTML = '';
        }
    }

    /**
     * Update move button states (enable/disable based on position)
     */
    updateMoveButtons() {
        if (!this.stepsList) return;

        const items = this.stepsList.querySelectorAll('.flow-step-item');
        const count = items.length;

        items.forEach((item, index) => {
            const upBtn = item.querySelector('.btn-move-up');
            const downBtn = item.querySelector('.btn-move-down');

            if (upBtn) {
                upBtn.disabled = index === 0;
                upBtn.onclick = () => window.flowWizard.recorder.moveStep(index, index - 1);
            }
            if (downBtn) {
                downBtn.disabled = index === count - 1;
                downBtn.onclick = () => window.flowWizard.recorder.moveStep(index, index + 1);
            }

            // Also update delete button index
            const deleteBtn = item.querySelector('.btn-delete');
            if (deleteBtn) {
                deleteBtn.onclick = () => window.flowWizard.recorder.removeStep(index);
            }
        });
    }

    /**
     * Render all steps (for refreshing the list)
     * Groups steps by screen_activity for visual clarity
     * Detects navigation issues and shows warnings
     */
    render(steps) {
        this.clear();
        if (!steps || !Array.isArray(steps)) return;

        const count = steps.length;
        let currentScreen = null;
        let expectedScreen = null;  // Track what screen we expect to be on

        // Detect navigation issues
        const navIssues = this.detectNavigationIssues(steps);

        steps.forEach((step, index) => {
            const isFirst = index === 0;
            const isLast = index === count - 1;

            // Get screen for this step (skip undefined/null values)
            const stepScreen = step.screen_activity || step.screen_package || null;

            // Only show screen headers for valid screen names
            if (stepScreen && stepScreen !== currentScreen && stepScreen !== 'undefined' && stepScreen !== 'null') {
                // Add screen header
                const screenName = this.formatScreenName(stepScreen);
                const screenHeaderHtml = `
                    <div class="screen-group-header" data-screen="${this.escapeHtml(stepScreen)}">
                        <span class="screen-icon">📱</span>
                        <span class="screen-name">${this.escapeHtml(screenName)}</span>
                    </div>
                `;
                this.stepsList.insertAdjacentHTML('beforeend', screenHeaderHtml);
                currentScreen = stepScreen;
            }

            // Check if this step has a navigation issue
            const hasNavIssue = navIssues.some(issue => issue.stepIndex === index);
            const navIssue = navIssues.find(issue => issue.stepIndex === index);

            // Determine if step should be nested (has valid screen)
            const isNested = stepScreen && stepScreen !== 'undefined' && stepScreen !== 'null';

            let warningHtml = '';
            if (hasNavIssue && navIssue) {
                warningHtml = `
                    <div class="wrong-screen-warning">
                        <span>⚠️ Expected on "${this.escapeHtml(navIssue.expectedScreen)}" but recorded on "${this.escapeHtml(navIssue.actualScreen)}"</span>
                        <button class="btn-fix" data-step-index="${index}" title="Add navigation step before this">Fix</button>
                    </div>
                `;
            }

            const stepHtml = `
                <div class="flow-step-item ${isNested ? 'nested-step' : ''} ${hasNavIssue ? 'wrong-screen' : ''}" data-step-index="${index}">
                    <div class="step-number-badge">${index + 1}</div>
                    <div class="step-content">
                        <div class="step-description">${this.escapeHtml(step.description || FlowStepManager.generateStepDescription(step))}</div>
                        ${warningHtml}
                    </div>
                    <div class="step-actions">
                        <button class="btn btn-sm btn-move-up" title="Move up" ${isFirst ? 'disabled' : ''}>↑</button>
                        <button class="btn btn-sm btn-move-down" title="Move down" ${isLast ? 'disabled' : ''}>↓</button>
                        <button class="btn btn-sm btn-delete" title="Delete step">✕</button>
                    </div>
                </div>
            `;

            this.stepsList.insertAdjacentHTML('beforeend', stepHtml);

            // Update expected screen based on step type
            if (step.step_type === 'launch_app') {
                expectedScreen = step.screen_activity || step.expected_activity;
            } else if (['tap', 'swipe', 'go_back'].includes(step.step_type)) {
                expectedScreen = null; // Screen may change
            }
        });

        // Bind click handlers after rendering
        this.updateMoveButtons();
        this.bindFixButtons();
    }

    /**
     * Detect navigation issues - steps that expect to be on a different screen
     */
    detectNavigationIssues(steps) {
        const issues = [];
        let currentScreen = null;

        for (let i = 0; i < steps.length; i++) {
            const step = steps[i];

            // launch_app sets the current screen
            if (step.step_type === 'launch_app') {
                currentScreen = step.screen_activity || step.expected_activity || null;
                continue;
            }

            // Steps that could navigate (make current screen unknown)
            if (['tap', 'swipe', 'go_back', 'go_home'].includes(step.step_type)) {
                // After navigation action, screen becomes uncertain regardless of pre-action screen
                currentScreen = null;
            }

            // validate_screen asserts a target activity - treat as known screen
            if (step.step_type === 'validate_screen' && step.expected_activity) {
                currentScreen = step.expected_activity;
            }

            // Check capture_sensors and other screen-dependent steps
            const screenDependentTypes = ['capture_sensors'];
            if (screenDependentTypes.includes(step.step_type) && step.screen_activity) {
                if (currentScreen && step.screen_activity !== currentScreen) {
                    issues.push({
                        stepIndex: i,
                        actualScreen: this.formatScreenName(step.screen_activity),
                        expectedScreen: this.formatScreenName(currentScreen),
                        stepType: step.step_type
                    });
                }
                // Update current screen to what was captured
                currentScreen = step.screen_activity;
            }
        }

        return issues;
    }

    /**
     * Bind fix button click handlers
     */
    bindFixButtons() {
        if (!this.stepsList) return;

        this.stepsList.querySelectorAll('.btn-fix').forEach(btn => {
            btn.onclick = () => {
                const stepIndex = parseInt(btn.dataset.stepIndex);
                this.promptFixNavigation(stepIndex);
            };
        });
    }

    /**
     * Prompt user to fix navigation issue
     */
    promptFixNavigation(stepIndex) {
        // Trigger a custom event that the wizard can handle
        window.dispatchEvent(new CustomEvent('fixNavigationRequest', {
            detail: { stepIndex }
        }));

        // Also show a toast with guidance
        if (window.showToast) {
            window.showToast('Go to Step 3 to record the missing navigation steps', 'info', 3000);
        }
    }

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    /**
     * Format screen activity name to be more readable
     */
    formatScreenName(screenActivity) {
        if (!screenActivity) return 'Unknown Screen';

        // Extract just the activity class name (last part after /)
        const parts = screenActivity.split('/');
        let name = parts[parts.length - 1] || screenActivity;

        // Remove common suffixes
        name = name.replace(/Activity$/, '');
        name = name.replace(/Fragment$/, '');

        // Split camelCase into words
        name = name.replace(/([a-z])([A-Z])/g, '$1 $2');

        // Capitalize first letter
        name = name.charAt(0).toUpperCase() + name.slice(1);

        return name;
    }

    /**
     * Format step type with emoji
     */
    static formatStepType(stepType) {
        const types = {
            'launch_app': '🚀 Launch App',
            'tap': '👆 Tap',
            'swipe': '👉 Swipe',
            'text': '⌨️ Type Text',
            'keyevent': '🔘 Key Press',
            'wait': '⏱️ Wait',
            'go_back': '⬅️ Back',
            'go_home': '🏠 Home',
            'execute_action': '⚡ Action',
            'capture_sensors': '📊 Capture Sensor',
            'stitch_capture': '📸 Stitch Capture'
        };
        return types[stepType] || stepType;
    }

    /**
     * Generate step description
     */
    static generateStepDescription(step) {
        switch (step.step_type) {
            case 'launch_app':
                return `Launch ${step.package}`;
            case 'tap':
                return `Tap at (${step.x}, ${step.y})`;
            case 'swipe':
                return `Swipe from (${step.start_x}, ${step.start_y}) to (${step.end_x}, ${step.end_y})`;
            case 'text':
                return `Type: "${step.text}"`;
            case 'keyevent':
                return `Press ${step.keycode}`;
            case 'wait':
                if (step.validate_timestamp && step.timestamp_element) {
                    const elementText = step.timestamp_element.text?.substring(0, 20) || 'element';
                    return `Wait for "${elementText}" to change (${step.refresh_max_retries || 3} checks)`;
                }
                if (step.refresh_attempts) {
                    return `Wait for UI update (${step.refresh_attempts} refreshes, ${step.refresh_delay}ms delay)`;
                }
                const durationSec = (step.duration || 0) / 1000;
                return `Wait ${durationSec >= 1 ? durationSec.toFixed(1) + 's' : step.duration + 'ms'}`;
            case 'capture_sensors':
                const sensorType = step.sensor_type || 'unknown';
                const sensorName = step.sensor_name || 'unnamed';
                return `Capture ${sensorType} sensor: "${sensorName}"`;
            default:
                return step.step_type;
        }
    }

    /**
     * Render step details
     */
    static renderStepDetails(step) {
        let details = [];

        if (step.x !== undefined) details.push(`x: ${step.x}`);
        if (step.y !== undefined) details.push(`y: ${step.y}`);
        if (step.start_x !== undefined) details.push(`start: (${step.start_x}, ${step.start_y})`);
        if (step.end_x !== undefined) details.push(`end: (${step.end_x}, ${step.end_y})`);
        if (step.duration !== undefined) {
            if (step.refresh_attempts) {
                details.push(`${step.refresh_attempts} refreshes`);
                details.push(`${step.refresh_delay}ms delay`);
            } else {
                details.push(`duration: ${step.duration}ms`);
            }
        }
        if (step.text) details.push(`text: "${step.text}"`);
        if (step.package) details.push(`package: ${step.package}`);

        // Sensor-specific details
        if (step.step_type === 'capture_sensors') {
            if (step.sensor_ids?.length) details.push(`sensors: ${step.sensor_ids.length}`);
            if (step.element?.text) details.push(`element text: "${step.element.text}"`);
            if (step.element?.class) details.push(`element class: ${step.element.class}`);
        }

        if (details.length === 0) return '';

        return `<div class="step-review-details">${details.join(' • ')}</div>`;
    }
}

// Dual export
export default FlowStepManager;
window.FlowStepManager = FlowStepManager;
