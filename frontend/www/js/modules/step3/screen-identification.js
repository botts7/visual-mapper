/**
 * Screen Identification Module for Flow Wizard Step 3
 *
 * Handles:
 * - UI landmark extraction for screen hashing
 * - Screen ID computation (SHA-256 based)
 * - Screen label resolution
 * - Auto-learning of new screens
 *
 * Extracted from flow-wizard-step3.js for maintainability
 * @version 0.0.1
 */

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Extract UI landmarks from elements for screen hashing
 * Looks for toolbar, tab, and title elements
 * @param {Array} elements - UI elements array
 * @returns {Array} Unique landmarks
 */
export function extractUiLandmarks(elements) {
    const landmarks = [];

    for (const el of elements || []) {
        const resourceId = el.resource_id || el['resource-id'] || '';
        const className = el.class || '';
        const text = el.text || '';
        const contentDesc = el.content_desc || el['content-desc'] || '';

        if (!text && !contentDesc) {
            continue;
        }

        const resourceLower = resourceId.toLowerCase();
        const classLower = className.toLowerCase();

        // Toolbar elements
        if (resourceLower.includes('toolbar') || resourceLower.includes('action_bar')) {
            landmarks.push({
                type: 'toolbar',
                text: text,
                resource_id: resourceId,
                content_desc: contentDesc
            });
            continue;
        }

        // Tab elements
        if (resourceLower.includes('tab') || classLower.includes('tablayout')) {
            landmarks.push({
                type: 'tab',
                text: text,
                resource_id: resourceId,
                content_desc: contentDesc
            });
            continue;
        }

        // Title/header elements
        if (className.includes('TextView') && text) {
            if (text.length < 50 && !text.includes('\n')) {
                if (['title', 'header', 'name', 'label'].some((kw) => resourceLower.includes(kw))) {
                    landmarks.push({
                        type: 'title',
                        text: text,
                        resource_id: resourceId,
                        content_desc: contentDesc
                    });
                }
            }
        }
    }

    // Deduplicate landmarks
    const seen = new Set();
    const unique = [];
    for (const lm of landmarks) {
        const key = `${lm.text || ''}|${lm.resource_id || ''}|${lm.content_desc || ''}`;
        if (!seen.has(key)) {
            seen.add(key);
            unique.push(lm);
        }
    }

    return unique;
}

/**
 * Compute a unique screen ID based on activity and UI landmarks
 * Uses SHA-256 hash truncated to 16 characters
 * @param {string} activity - Activity name
 * @param {Array} elements - UI elements
 * @returns {Promise<string|null>} Screen ID hash or null
 */
export async function computeScreenId(activity, elements) {
    if (!activity || !elements || elements.length === 0) {
        return null;
    }

    if (!window.crypto || !window.crypto.subtle || !window.TextEncoder) {
        return null;
    }

    const landmarkStrs = [];
    const landmarks = extractUiLandmarks(elements);

    for (const landmark of landmarks) {
        const text = landmark.text || '';
        const resourceId = landmark.resource_id || '';
        const contentDesc = landmark.content_desc || '';

        if (text) {
            landmarkStrs.push(`text:${text}`);
        } else if (resourceId) {
            landmarkStrs.push(`id:${resourceId}`);
        } else if (contentDesc) {
            landmarkStrs.push(`desc:${contentDesc}`);
        }
    }

    landmarkStrs.sort();
    const hashInput = `${activity}|${landmarkStrs.join(',')}`;

    try {
        const encoder = new TextEncoder();
        const hashBuffer = await window.crypto.subtle.digest('SHA-256', encoder.encode(hashInput));
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        const hex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
        return hex.slice(0, 16);
    } catch (e) {
        console.warn('[ScreenID] Failed to compute screen id:', e);
        return null;
    }
}

/**
 * Resolve a human-readable screen label
 * @param {Object} wizard - Wizard instance with navigation graph
 * @param {string} screenSignature - Screen signature/hash
 * @param {string} activityName - Activity name
 * @returns {string} Display label
 */
export function resolveScreenLabel(wizard, screenSignature, activityName) {
    if (screenSignature && wizard.navigationGraph?.screens?.[screenSignature]) {
        const screen = wizard.navigationGraph.screens[screenSignature];
        return screen.display_name || screen.activity?.split('.').pop() || screenSignature;
    }
    if (activityName) {
        const shortName = activityName.split('.').pop();
        return screenSignature ? `${shortName} (${screenSignature.slice(0, 6)})` : shortName;
    }
    return screenSignature ? screenSignature.slice(0, 6) : 'Unknown';
}

/**
 * Normalize a screen label by removing hash suffix
 * @param {string} label - Screen label
 * @returns {string|null} Normalized label
 */
export function normalizeScreenLabel(label) {
    if (!label) return null;
    return label.replace(/\s*\([0-9a-fA-F]{4,}\)\s*$/, '').trim();
}

/**
 * Get short activity name from full qualified name
 * @param {Object} wizard - Wizard instance
 * @param {string} screenSignature - Screen signature
 * @param {string} activityName - Full activity name
 * @returns {string|null} Short activity name
 */
export function getActivityShortName(wizard, screenSignature, activityName) {
    if (activityName) {
        return activityName.split('.').pop();
    }
    if (screenSignature && wizard.navigationGraph?.screens?.[screenSignature]?.activity) {
        return wizard.navigationGraph.screens[screenSignature].activity.split('.').pop();
    }
    return null;
}

/**
 * Auto-learn a new screen if enabled
 * Posts screen data to backend navigation API
 * @param {Object} wizard - Wizard instance
 * @param {Object} activityInfo - Activity information
 * @param {Array} elements - UI elements
 */
export async function maybeLearnScreen(wizard, activityInfo, elements) {
    if (!wizard.autoLearnScreens) return;
    if (!activityInfo?.activity || !activityInfo?.package) return;
    if (!elements || elements.length === 0) return;

    const signature = await computeScreenId(activityInfo.activity, elements);
    if (!signature) return;

    // Debounce - don't re-learn same screen within 5 seconds
    const now = Date.now();
    const lastSignature = wizard._lastLearnedSignature;
    const lastTime = wizard._lastLearnedAt || 0;

    if (signature === lastSignature && (now - lastTime) < 5000) {
        return;
    }

    wizard._lastLearnedSignature = signature;
    wizard._lastLearnedAt = now;

    const packageName = activityInfo.package || wizard.selectedApp?.package || wizard.selectedApp;
    if (!packageName) return;

    try {
        const response = await fetch(
            `${getApiBase()}/navigation/${encodeURIComponent(packageName)}/screens`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    activity: activityInfo.activity,
                    ui_elements: elements,
                    display_name: activityInfo.activity.split('.').pop()
                })
            }
        );

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            console.warn('[ScreenID] Screen learn failed:', error.detail || response.statusText);
            return;
        }

        const data = await response.json();
        if (data?.screen?.screen_id) {
            wizard.lastLearnedScreenId = data.screen.screen_id;
        }
        console.log('[ScreenID] Learned screen:', activityInfo.activity);
    } catch (error) {
        console.warn('[ScreenID] Screen learn error:', error);
    }
}

/**
 * Get screen context for the current elements
 * @param {Object} wizard - Wizard instance
 * @param {Object} activityInfo - Activity information
 * @param {Array} elements - UI elements
 * @returns {Promise<Object>} Screen context with signature and label
 */
export async function getScreenContext(wizard, activityInfo, elements) {
    const signature = await computeScreenId(activityInfo?.activity, elements);
    const label = resolveScreenLabel(wizard, signature, activityInfo?.activity);
    const shortName = getActivityShortName(wizard, signature, activityInfo?.activity);

    return {
        signature,
        label,
        shortName,
        activity: activityInfo?.activity,
        package: activityInfo?.package
    };
}
