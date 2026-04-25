/**
 * Prerequisite Checker Module
 * Visual Mapper v0.4.0-beta
 *
 * Detects when required services (accessibility, streaming) are not running
 * and helps users set up or run prerequisite flows to enable them.
 */

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Prerequisite display names
 */
export const PREREQ_NAMES = {
    'accessibility': 'Accessibility Service',
    'streaming': 'Screen Streaming',
    'overlay_permission': 'Overlay Permission'
};

/**
 * Prerequisite Checker
 * Checks if required services are enabled and manages prerequisite flows
 */
export class PrerequisiteChecker {
    /**
     * @param {string} deviceId - The device to check prerequisites for
     */
    constructor(deviceId) {
        this.deviceId = deviceId;
        this.status = null;
        this.apiBase = getApiBase();
    }

    /**
     * Check all prerequisites and return status
     * @returns {Promise<Object>} - Full prerequisite status
     */
    async checkAll() {
        try {
            const response = await fetch(
                `${this.apiBase}/prerequisites/${encodeURIComponent(this.deviceId)}/status`
            );

            if (!response.ok) {
                console.warn('[PrerequisiteChecker] Failed to fetch status:', response.status);
                return this._getDefaultStatus();
            }

            this.status = await response.json();
            return this.status;
        } catch (error) {
            console.error('[PrerequisiteChecker] Error checking prerequisites:', error);
            return this._getDefaultStatus();
        }
    }

    /**
     * Get default status when API unavailable
     * @private
     */
    _getDefaultStatus() {
        return {
            success: false,
            device_id: this.deviceId,
            prerequisites: {
                accessibility: { enabled: false, flow_id: null, auto_run: false },
                streaming: { active: false, flow_id: null, auto_run: false },
                overlay_permission: { enabled: false, flow_id: null, auto_run: false }
            }
        };
    }

    /**
     * Check if specific prerequisites are met
     * @param {string[]} required - Array of required prerequisites ['accessibility', 'streaming']
     * @returns {Promise<{allMet: boolean, missing: string[]}>}
     */
    async checkRequired(required) {
        await this.checkAll();

        const missing = [];
        const prereqs = this.status?.prerequisites || {};

        for (const prereq of required) {
            if (prereq === 'accessibility') {
                const accessStatus = prereqs.accessibility || {};
                if (!accessStatus.enabled && !accessStatus.fully_operational) {
                    missing.push('accessibility');
                }
            }
            if (prereq === 'streaming') {
                const streamStatus = prereqs.streaming || {};
                if (!streamStatus.active) {
                    missing.push('streaming');
                }
            }
            if (prereq === 'overlay_permission') {
                const overlayStatus = prereqs.overlay_permission || {};
                if (!overlayStatus.enabled) {
                    missing.push('overlay_permission');
                }
            }
        }

        return { allMet: missing.length === 0, missing };
    }

    /**
     * Run auto-run flows for missing prerequisites
     * @param {string[]} missing - Array of missing prerequisite types
     * @returns {Promise<Object>} - Results of auto-run attempts
     */
    async runAutoFlows(missing) {
        const results = {};

        for (const prereq of missing) {
            const config = this.status?.prerequisites?.[prereq];

            if (config?.auto_run && config?.flow_id) {
                console.log(`[PrerequisiteChecker] Auto-running flow for ${prereq}`);
                try {
                    const result = await this.runPrerequisiteFlow(prereq, config.flow_id);
                    results[prereq] = result;
                } catch (error) {
                    console.error(`[PrerequisiteChecker] Auto-run failed for ${prereq}:`, error);
                    results[prereq] = { success: false, error: error.message };
                }
            }
        }

        return results;
    }

    /**
     * Run a specific prerequisite flow
     * @param {string} prereqType - The prerequisite type
     * @param {string} flowId - The flow ID to run
     * @returns {Promise<Object>} - Execution result
     */
    async runPrerequisiteFlow(prereqType, flowId) {
        try {
            console.log(`[PrerequisiteChecker] Running flow ${flowId} for ${prereqType}`);

            // Execute the flow
            const response = await fetch(
                `${this.apiBase}/flows/${encodeURIComponent(this.deviceId)}/${encodeURIComponent(flowId)}/execute`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sync: true, timeout: 60 })
                }
            );

            const result = await response.json();

            // Record the run result
            await this.recordRun(prereqType, result.success);

            return result;
        } catch (error) {
            console.error(`[PrerequisiteChecker] Failed to run flow ${flowId}:`, error);
            await this.recordRun(prereqType, false);
            throw error;
        }
    }

    /**
     * Record that a prerequisite flow was run
     * @param {string} prereqType - The prerequisite type
     * @param {boolean} success - Whether the run was successful
     */
    async recordRun(prereqType, success) {
        try {
            await fetch(
                `${this.apiBase}/prerequisites/${encodeURIComponent(this.deviceId)}/${prereqType}/record-run`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ success })
                }
            );
        } catch (error) {
            console.warn('[PrerequisiteChecker] Failed to record run:', error);
        }
    }

    /**
     * Link a flow as a prerequisite flow
     * @param {string} prereqType - The prerequisite type
     * @param {string} flowId - The flow ID to link
     */
    async linkFlow(prereqType, flowId) {
        const response = await fetch(
            `${this.apiBase}/prerequisites/${encodeURIComponent(this.deviceId)}/${prereqType}/link-flow`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ flow_id: flowId })
            }
        );

        if (!response.ok) {
            throw new Error(`Failed to link flow: ${response.status}`);
        }

        return response.json();
    }

    /**
     * Set auto-run setting for a prerequisite
     * @param {string} prereqType - The prerequisite type
     * @param {boolean} enabled - Whether auto-run should be enabled
     */
    async setAutoRun(prereqType, enabled) {
        const response = await fetch(
            `${this.apiBase}/prerequisites/${encodeURIComponent(this.deviceId)}/${prereqType}/set-auto-run`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            }
        );

        if (!response.ok) {
            throw new Error(`Failed to set auto-run: ${response.status}`);
        }

        return response.json();
    }

    /**
     * Get guidance steps for creating a prerequisite flow
     * @param {string} prereqType - The prerequisite type
     * @returns {Promise<Object>} - Guidance information
     */
    async getGuidance(prereqType) {
        try {
            const response = await fetch(
                `${this.apiBase}/prerequisites/${encodeURIComponent(this.deviceId)}/${prereqType}/guidance`
            );

            if (!response.ok) {
                return { steps: [] };
            }

            return response.json();
        } catch (error) {
            console.error('[PrerequisiteChecker] Failed to get guidance:', error);
            return { steps: [] };
        }
    }

    /**
     * Get all available prerequisite types
     * @returns {Promise<Object>} - Prerequisite types and metadata
     */
    async getPrerequisiteTypes() {
        try {
            const response = await fetch(`${this.apiBase}/prerequisites/types`);

            if (!response.ok) {
                return { types: {} };
            }

            return response.json();
        } catch (error) {
            console.error('[PrerequisiteChecker] Failed to get types:', error);
            return { types: {} };
        }
    }
}

/**
 * Quick check if prerequisites are met (without creating checker instance)
 * @param {string} deviceId - Device to check
 * @param {string[]} required - Required prerequisites
 * @returns {Promise<{allMet: boolean, missing: string[], status: Object}>}
 */
export async function quickCheckPrerequisites(deviceId, required = ['accessibility', 'streaming']) {
    const checker = new PrerequisiteChecker(deviceId);
    const { allMet, missing } = await checker.checkRequired(required);
    return { allMet, missing, status: checker.status };
}

export default PrerequisiteChecker;
