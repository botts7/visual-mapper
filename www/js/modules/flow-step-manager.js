/**
 * Flow Step Manager Module
 * Visual Mapper v0.0.5
 *
 * Handles flow steps list display and events
 */

export class FlowStepManager {
    constructor(stepsListElement) {
        this.stepsList = stepsListElement;
        this.setupListeners();
    }

    /**
     * Setup event listeners for step add/remove
     */
    setupListeners() {
        window.addEventListener('flowStepAdded', (e) => {
            this.onStepAdded(e.detail);
        });

        window.addEventListener('flowStepRemoved', (e) => {
            this.onStepRemoved(e.detail);
        });
    }

    /**
     * Handle step added event
     */
    onStepAdded({ step, index }) {
        if (!this.stepsList) return;

        const stepHtml = `
            <div class="flow-step-item" data-step-index="${index}">
                <div class="step-number-badge">${index + 1}</div>
                <div class="step-content">
                    <div class="step-description">${step.description}</div>
                </div>
                <div class="step-actions">
                    <button class="btn btn-sm" onclick="window.flowWizard.recorder.removeStep(${index})">✕</button>
                </div>
            </div>
        `;

        this.stepsList.insertAdjacentHTML('beforeend', stepHtml);
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
                return `Swipe from (${step.x1}, ${step.y1}) to (${step.x2}, ${step.y2})`;
            case 'text':
                return `Type: "${step.text}"`;
            case 'keyevent':
                return `Press ${step.keycode}`;
            case 'wait':
                if (step.refresh_attempts) {
                    return `Wait for UI update (${step.refresh_attempts} refreshes, ${step.refresh_delay}ms delay)`;
                }
                return `Wait ${step.duration}ms`;
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
        if (step.x1 !== undefined) details.push(`start: (${step.x1}, ${step.y1})`);
        if (step.x2 !== undefined) details.push(`end: (${step.x2}, ${step.y2})`);
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
            if (step.sensor_id) details.push(`id: ${step.sensor_id}`);
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
