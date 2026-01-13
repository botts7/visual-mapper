/**
 * Flow Wizard Element Actions Module
 * Visual Mapper v0.0.6
 *
 * Element interaction methods for tap, type, and sensor actions
 * Extracted from flow-wizard.js for better modularity
 * v0.0.6: Fixed elementIndex passthrough to createTextSensor
 */

import { showToast } from './toast.js?v=0.3.1';

/**
 * Add tap step from element (via panel)
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} element - Element object with bounds
 */
export async function addTapStepFromElement(wizard, element) {
    const bounds = element.bounds || {};
    const x = Math.round((bounds.x || 0) + (bounds.width || 0) / 2);
    const y = Math.round((bounds.y || 0) + (bounds.height || 0) / 2);

    await wizard.executeTap(x, y, element);
    showToast(`Added tap step for "${element.text || 'element'}"`, 'success');
}

/**
 * Add type step from element (via panel)
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} element - Element object with bounds
 */
export async function addTypeStepFromElement(wizard, element) {
    const bounds = element.bounds || {};
    const x = Math.round((bounds.x || 0) + (bounds.width || 0) / 2);
    const y = Math.round((bounds.y || 0) + (bounds.height || 0) / 2);

    const text = await wizard.promptForText();
    if (text) {
        await wizard.executeTap(x, y, element);
        await wizard.recorder.typeText(text);
        showToast(`Added type step: "${text}"`, 'success');
    }
}

/**
 * Add sensor capture from element (via panel)
 * @param {FlowWizard} wizard - FlowWizard instance
 * @param {Object} element - Element object with bounds
 * @param {number} elementIndex - Index of element in array
 */
export async function addSensorCaptureFromElement(wizard, element, elementIndex) {
    const bounds = element.bounds || {};
    const coords = {
        x: Math.round((bounds.x || 0) + (bounds.width || 0) / 2),
        y: Math.round((bounds.y || 0) + (bounds.height || 0) / 2)
    };

    // Show sensor configuration dialog - pass elementIndex for proper tracking
    await wizard.createTextSensor(element, coords, elementIndex);
}

// Dual export pattern: ES6 export + window global
const FlowWizardElementActions = {
    addTapStepFromElement,
    addTypeStepFromElement,
    addSensorCaptureFromElement
};

window.FlowWizardElementActions = FlowWizardElementActions;

export default FlowWizardElementActions;
