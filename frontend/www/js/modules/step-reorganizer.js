/**
 * Step Reorganizer Module
 * Visual Mapper v0.0.1
 *
 * Handles step reordering with navigation validation for Flow Wizard Step 4.
 * Groups steps by screen_activity and validates moves to prevent breaking flow logic.
 */

/**
 * Group steps by screen_activity
 * Creates sequential groups where each group contains steps on the same screen.
 * @param {Array} steps - Flow steps array
 * @returns {Array} Array of {activity, shortName, steps: [{step, originalIndex}]}
 */
export function groupStepsByScreen(steps) {
    if (!steps || steps.length === 0) {
        return [];
    }

    const groups = [];
    let currentActivity = null;
    let currentGroup = null;

    steps.forEach((step, index) => {
        // Get activity from step, falling back to expected_activity for launch_app
        const activity = step.screen_activity || step.expected_activity || 'Unknown Screen';

        // Start new group if activity changes
        if (activity !== currentActivity) {
            if (currentGroup) {
                groups.push(currentGroup);
            }
            currentGroup = {
                activity: activity,
                shortName: activity.includes('.') ? activity.split('.').pop() : activity,
                steps: []
            };
            currentActivity = activity;
        }

        currentGroup.steps.push({
            step: step,
            originalIndex: index
        });
    });

    // Don't forget the last group
    if (currentGroup && currentGroup.steps.length > 0) {
        groups.push(currentGroup);
    }

    return groups;
}

/**
 * Check if moving a step would break navigation logic
 * @param {Array} steps - Current steps array
 * @param {number} fromIndex - Source index
 * @param {number} toIndex - Target index
 * @returns {Object} {valid: boolean, error?: string}
 */
export function validateMove(steps, fromIndex, toIndex) {
    // Same position - no move needed
    if (fromIndex === toIndex) {
        return { valid: true };
    }

    // Bounds check
    if (fromIndex < 0 || fromIndex >= steps.length) {
        return { valid: false, error: 'Invalid source position' };
    }
    if (toIndex < 0 || toIndex >= steps.length) {
        return { valid: false, error: 'Invalid target position' };
    }

    const step = steps[fromIndex];

    // Rule 1: launch_app must stay at index 0
    if (step.step_type === 'launch_app' && toIndex !== 0) {
        return {
            valid: false,
            error: 'Launch App step must remain at the beginning of the flow'
        };
    }

    // Rule 2: Cannot move a non-launch step to position 0 if there's a launch_app
    if (steps[0]?.step_type === 'launch_app' && toIndex === 0 && step.step_type !== 'launch_app') {
        return {
            valid: false,
            error: 'Cannot move steps before the Launch App step'
        };
    }

    // Rule 3: Check navigation continuity after move
    // Create a copy with the move applied
    const newSteps = [...steps];
    const [movedStep] = newSteps.splice(fromIndex, 1);
    newSteps.splice(toIndex, 0, movedStep);

    const navIssues = checkNavigationAfterMove(newSteps);
    if (navIssues.length > 0) {
        const issue = navIssues[0];
        return {
            valid: false,
            error: `Move would break navigation: Step ${issue.stepIndex + 1} expects screen "${issue.stepActivity}" but flow would be on "${issue.currentActivity}"`
        };
    }

    return { valid: true };
}

/**
 * Check navigation issues in step array
 * Adapted from flow-wizard-step4.js checkNavigationIssues
 * @param {Array} steps - Steps array to check
 * @returns {Array} Array of issues found
 */
function checkNavigationAfterMove(steps) {
    const issues = [];
    let currentActivity = null;
    let lastNavStepIndex = -1;

    // Step types that must be on the correct screen
    const screenDependentTypes = ['capture_sensors', 'tap', 'swipe', 'text'];
    // Step types that can change the screen
    const screenChangingTypes = ['tap', 'swipe', 'go_back'];

    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];

        // launch_app sets initial screen
        if (step.step_type === 'launch_app') {
            currentActivity = step.screen_activity || step.expected_activity || null;
            lastNavStepIndex = i;
            continue;
        }

        // restart_app, go_home, go_back - screen becomes unknown
        if (step.step_type === 'restart_app' || step.step_type === 'go_home' || step.step_type === 'go_back') {
            currentActivity = null;
            lastNavStepIndex = i;
            continue;
        }

        // Check steps that depend on being on the right screen
        if (step.screen_activity && screenDependentTypes.includes(step.step_type)) {
            if (currentActivity && step.screen_activity !== currentActivity) {
                // Check for navigation between last nav step and this one
                let hasNavigation = false;
                for (let j = lastNavStepIndex + 1; j < i; j++) {
                    if (screenChangingTypes.includes(steps[j].step_type)) {
                        hasNavigation = true;
                        break;
                    }
                }

                if (!hasNavigation) {
                    issues.push({
                        stepIndex: i,
                        stepActivity: step.screen_activity.split('.').pop(),
                        currentActivity: currentActivity.split('.').pop()
                    });
                }
            }

            // capture_sensors updates current activity
            if (step.step_type === 'capture_sensors') {
                currentActivity = step.screen_activity;
                lastNavStepIndex = i;
            }
        }

        // Screen-changing actions make current activity unknown
        if (screenChangingTypes.includes(step.step_type)) {
            if (step.screen_activity) {
                currentActivity = null;
                lastNavStepIndex = i;
            }
        }
    }

    return issues;
}

/**
 * Move step within array (mutates the array)
 * @param {Array} steps - Steps array to modify
 * @param {number} fromIndex - Source index
 * @param {number} toIndex - Target index
 * @returns {boolean} Success
 */
export function moveStep(steps, fromIndex, toIndex) {
    if (fromIndex < 0 || fromIndex >= steps.length) return false;
    if (toIndex < 0 || toIndex >= steps.length) return false;
    if (fromIndex === toIndex) return true;

    const [movedStep] = steps.splice(fromIndex, 1);
    steps.splice(toIndex, 0, movedStep);
    return true;
}

// Default export
export default {
    groupStepsByScreen,
    validateMove,
    moveStep
};

// Global export for non-module usage
window.StepReorganizer = {
    groupStepsByScreen,
    validateMove,
    moveStep
};
