/**
 * Flow Schema Validator Module
 * Fetches step type schemas from the server and provides validation
 *
 * Phase 2 Refactor: This module uses the centralized /api/flow-schema endpoint
 * to validate flow steps on the frontend, ensuring parity with backend validation.
 *
 * @module flow-schema-validator
 */

// ==========================================
// Module State
// ==========================================

let schemaCache = null;
let schemaVersion = null;
let schemaPromise = null;

// ==========================================
// Utility Functions
// ==========================================

/**
 * Get API base URL with ingress support
 * @returns {string} The API base URL
 */
function getApiBase() {
    if (window.API_BASE) return window.API_BASE;
    if (window.opener?.API_BASE) return window.opener.API_BASE;
    const url = window.location.href;
    const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
    if (ingressMatch) return ingressMatch[0] + '/api';
    return '/api';
}

// ==========================================
// Schema Loading
// ==========================================

/**
 * Fetch the flow schema from the server
 * Uses caching to avoid repeated fetches
 * @returns {Promise<Object>} The schema object
 */
export async function fetchSchema() {
    // Return cached promise if already loading
    if (schemaPromise) {
        return schemaPromise;
    }

    // Return cache if valid
    if (schemaCache) {
        return schemaCache;
    }

    // Fetch schema
    schemaPromise = (async () => {
        try {
            const response = await fetch(`${getApiBase()}/flow-schema`);
            if (!response.ok) {
                throw new Error(`Failed to fetch schema: ${response.status}`);
            }

            const schema = await response.json();
            schemaCache = schema;
            schemaVersion = schema.version;
            console.log(`[FlowValidator] Loaded schema v${schemaVersion} with ${Object.keys(schema.step_types).length} step types`);
            return schema;
        } catch (error) {
            console.error('[FlowValidator] Failed to fetch schema:', error);
            // Return fallback schema
            return getFallbackSchema();
        } finally {
            schemaPromise = null;
        }
    })();

    return schemaPromise;
}

/**
 * Get the cached schema (sync access)
 * Returns null if not yet loaded
 * @returns {Object|null}
 */
export function getCachedSchema() {
    return schemaCache;
}

/**
 * Clear the schema cache (for testing or refresh)
 */
export function clearSchemaCache() {
    schemaCache = null;
    schemaVersion = null;
    schemaPromise = null;
}

/**
 * Get fallback schema for offline/error cases
 * This is a minimal subset for critical operations
 * @returns {Object}
 */
function getFallbackSchema() {
    return {
        version: "fallback",
        step_types: {
            launch_app: { required: ["package"], optional: ["description"] },
            tap: { required: ["x", "y"], optional: ["description"] },
            swipe: { required: ["start_x", "start_y", "end_x", "end_y"], optional: ["duration", "description"] },
            wait: { required: ["duration"], optional: ["description"] },
            text: { required: ["text"], optional: ["description"] },
            go_home: { required: [], optional: ["description"] },
            go_back: { required: [], optional: ["description"] },
            capture_sensors: { required: ["sensor_ids"], optional: ["description"] },
            execute_action: { required: ["action_id"], optional: ["description"] },
            validate_screen: { required: [], optional: ["validation_element", "description"] }
        },
        categories: {
            app_control: ["launch_app", "go_home", "go_back"],
            gestures: ["tap", "swipe"],
            timing: ["wait"],
            input: ["text"],
            sensors: ["capture_sensors", "execute_action"],
            validation: ["validate_screen"]
        }
    };
}

// ==========================================
// Validation Functions
// ==========================================

/**
 * Validate a single flow step against the schema
 * @param {Object} step - The step to validate
 * @returns {Object} { valid: boolean, errors: string[] }
 */
export async function validateStep(step) {
    const schema = await fetchSchema();
    const errors = [];

    // Check step_type exists
    if (!step.step_type) {
        errors.push("Missing step_type");
        return { valid: false, errors };
    }

    // Get step schema
    const stepSchema = schema.step_types[step.step_type];
    if (!stepSchema) {
        errors.push(`Unknown step_type: ${step.step_type}. Valid types: ${Object.keys(schema.step_types).join(", ")}`);
        return { valid: false, errors };
    }

    // Check required fields
    const requiredFields = stepSchema.required || [];
    for (const field of requiredFields) {
        if (step[field] === undefined || step[field] === null) {
            errors.push(`Missing required field: ${field} for step type ${step.step_type}`);
        }
    }

    // Type-specific validation
    switch (step.step_type) {
        case 'tap':
            if (typeof step.x !== 'number' || step.x < 0) {
                errors.push("x coordinate must be a positive number");
            }
            if (typeof step.y !== 'number' || step.y < 0) {
                errors.push("y coordinate must be a positive number");
            }
            break;

        case 'swipe':
            ['start_x', 'start_y', 'end_x', 'end_y'].forEach(field => {
                if (typeof step[field] !== 'number' || step[field] < 0) {
                    errors.push(`${field} must be a positive number`);
                }
            });
            if (step.duration !== undefined && (typeof step.duration !== 'number' || step.duration < 0)) {
                errors.push("duration must be a positive number");
            }
            break;

        case 'wait':
            if (typeof step.duration !== 'number' || step.duration < 0) {
                errors.push("duration must be a positive number");
            }
            if (step.duration > 60000) {
                errors.push("duration exceeds maximum (60000ms)");
            }
            break;

        case 'launch_app':
            if (typeof step.package !== 'string' || !step.package.trim()) {
                errors.push("package must be a non-empty string");
            }
            break;

        case 'text':
            if (typeof step.text !== 'string') {
                errors.push("text must be a string");
            }
            break;

        case 'capture_sensors':
            if (!Array.isArray(step.sensor_ids) || step.sensor_ids.length === 0) {
                errors.push("sensor_ids must be a non-empty array");
            }
            break;

        case 'execute_action':
            if (typeof step.action_id !== 'string' || !step.action_id.trim()) {
                errors.push("action_id must be a non-empty string");
            }
            break;

        case 'loop':
            if (typeof step.iterations !== 'number' || step.iterations < 1 || step.iterations > 100) {
                errors.push("iterations must be a number between 1 and 100");
            }
            if (!Array.isArray(step.loop_steps)) {
                errors.push("loop_steps must be an array");
            }
            break;
    }

    return {
        valid: errors.length === 0,
        errors
    };
}

/**
 * Validate a complete flow
 * @param {Object} flow - The flow to validate
 * @returns {Object} { valid: boolean, errors: string[], stepErrors: Object[] }
 */
export async function validateFlow(flow) {
    const errors = [];
    const stepErrors = [];

    // Check basic flow structure
    if (!flow.flow_id) {
        errors.push("Missing flow_id");
    }
    if (!flow.device_id) {
        errors.push("Missing device_id");
    }
    if (!flow.name || !flow.name.trim()) {
        errors.push("Missing or empty name");
    }
    if (!Array.isArray(flow.steps)) {
        errors.push("steps must be an array");
        return { valid: false, errors, stepErrors };
    }
    if (flow.steps.length === 0) {
        errors.push("Flow must have at least one step");
    }

    // Validate each step
    for (let i = 0; i < flow.steps.length; i++) {
        const step = flow.steps[i];
        const result = await validateStep(step);
        if (!result.valid) {
            stepErrors.push({
                stepIndex: i,
                step_type: step.step_type || 'unknown',
                errors: result.errors
            });
        }
    }

    return {
        valid: errors.length === 0 && stepErrors.length === 0,
        errors,
        stepErrors
    };
}

/**
 * Get list of valid step types
 * @returns {Promise<string[]>}
 */
export async function getValidStepTypes() {
    const schema = await fetchSchema();
    return Object.keys(schema.step_types);
}

/**
 * Get step types by category
 * @returns {Promise<Object>}
 */
export async function getStepTypesByCategory() {
    const schema = await fetchSchema();
    return schema.categories || {};
}

/**
 * Get schema for a specific step type
 * @param {string} stepType
 * @returns {Promise<Object|null>}
 */
export async function getStepTypeSchema(stepType) {
    const schema = await fetchSchema();
    return schema.step_types[stepType] || null;
}

// ==========================================
// Quick Validation (Sync with cached schema)
// ==========================================

/**
 * Quick sync validation using cached schema
 * Falls back to basic validation if schema not loaded
 * @param {Object} step
 * @returns {Object} { valid: boolean, errors: string[] }
 */
export function validateStepSync(step) {
    const schema = schemaCache || getFallbackSchema();
    const errors = [];

    if (!step.step_type) {
        errors.push("Missing step_type");
        return { valid: false, errors };
    }

    const stepSchema = schema.step_types[step.step_type];
    if (!stepSchema) {
        // Don't fail for unknown types in sync mode (schema might be stale)
        console.warn(`[FlowValidator] Unknown step_type: ${step.step_type} (using cached schema)`);
        return { valid: true, errors: [] };
    }

    // Check required fields
    const requiredFields = stepSchema.required || [];
    for (const field of requiredFields) {
        if (step[field] === undefined || step[field] === null) {
            errors.push(`Missing required field: ${field}`);
        }
    }

    return {
        valid: errors.length === 0,
        errors
    };
}

// ==========================================
// Default Export
// ==========================================

export default {
    fetchSchema,
    getCachedSchema,
    clearSchemaCache,
    validateStep,
    validateFlow,
    validateStepSync,
    getValidStepTypes,
    getStepTypesByCategory,
    getStepTypeSchema
};

// Global export for non-module usage
if (typeof window !== 'undefined') {
    window.FlowSchemaValidator = {
        fetchSchema,
        getCachedSchema,
        clearSchemaCache,
        validateStep,
        validateFlow,
        validateStepSync,
        getValidStepTypes,
        getStepTypesByCategory,
        getStepTypeSchema
    };
}
