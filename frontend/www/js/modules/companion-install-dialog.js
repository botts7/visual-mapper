/**
 * Companion Install Dialog Module
 * Visual Mapper v0.4.0-beta
 *
 * Shows a dialog when companion app is not installed on device,
 * listing enhanced features and offering installation options.
 */

import { showToast } from './toast.js?v=0.4.0-beta.4';

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Features provided by the companion app over basic ADB-only mode
 */
const COMPANION_FEATURES = [
    {
        icon: '\uD83D\uDCFA', // TV/Screen icon
        name: 'Native Screen Streaming',
        desc: 'Lower latency H.264 streaming directly from device'
    },
    {
        icon: '\uD83C\uDFAF', // Target icon
        name: 'Accessibility Service',
        desc: 'Real-time UI element detection without screenshots'
    },
    {
        icon: '\uD83D\uDC46', // Pointing up icon
        name: 'Native Gestures',
        desc: 'Faster, more reliable tap/swipe via accessibility'
    },
    {
        icon: '\uD83D\uDD04', // Refresh icon
        name: 'On-Device Flow Execution',
        desc: 'Run flows without constant ADB commands'
    },
    {
        icon: '\uD83D\uDCE1', // Satellite icon
        name: 'MQTT Communication',
        desc: 'Real-time bi-directional messaging'
    },
    {
        icon: '\uD83D\uDC41\uFE0F', // Eye icon
        name: 'Element Watching',
        desc: 'Monitor UI changes and trigger automations'
    }
];

/**
 * Check if user has opted out of companion install prompts
 * @returns {boolean}
 */
export function shouldCheckCompanionInstall() {
    try {
        return localStorage.getItem('companion.dontAskInstall') !== 'true';
    } catch {
        return true;
    }
}

/**
 * Reset the "don't ask again" preference
 */
export function resetCompanionInstallPreference() {
    try {
        localStorage.removeItem('companion.dontAskInstall');
    } catch {
        // Ignore storage errors
    }
}

/**
 * Check if companion app is installed on device
 * @param {string} deviceId - Device ID to check
 * @returns {Promise<{installed: boolean, version?: string, error?: string}>}
 */
export async function checkCompanionInstalled(deviceId) {
    try {
        const response = await fetch(
            `${getApiBase()}/companion/${encodeURIComponent(deviceId)}/installed`
        );

        if (!response.ok) {
            throw new Error('Failed to check companion installation');
        }

        return await response.json();
    } catch (error) {
        console.error('[CompanionInstallDialog] Check failed:', error);
        return { installed: false, error: error.message };
    }
}

/**
 * Install companion app via ADB
 * @param {string} deviceId - Device ID to install on
 * @returns {Promise<{success: boolean, message?: string, error?: string}>}
 */
export async function installCompanionApp(deviceId) {
    try {
        const response = await fetch(
            `${getApiBase()}/companion/${encodeURIComponent(deviceId)}/install`,
            { method: 'POST' }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || 'Installation failed');
        }

        return result;
    } catch (error) {
        console.error('[CompanionInstallDialog] Install failed:', error);
        return { success: false, error: error.message };
    }
}

/**
 * Show companion install dialog
 * @param {string} deviceId - Device ID
 * @param {Object} options - Optional settings
 * @param {boolean} options.showVersionInfo - Show version if installed
 * @returns {Promise<{action: 'install' | 'skip' | 'installed', dontAskAgain?: boolean}>}
 */
export function showCompanionInstallDialog(deviceId, options = {}) {
    return new Promise((resolve) => {
        // Check "don't ask again" preference
        if (!shouldCheckCompanionInstall()) {
            resolve({ action: 'skip', dontAskAgain: true });
            return;
        }

        // Remove any existing dialog
        const existingDialog = document.getElementById('companionInstallDialog');
        if (existingDialog) {
            existingDialog.remove();
        }

        // Create dialog
        const dialog = document.createElement('div');
        dialog.id = 'companionInstallDialog';
        dialog.className = 'companion-install-dialog-overlay';

        dialog.innerHTML = `
            <div class="companion-install-dialog">
                <h2>Enhanced Features Available</h2>
                <p class="companion-intro">
                    Install the Visual Mapper Companion app on your device to unlock these enhanced features:
                </p>

                <div class="companion-feature-list">
                    ${COMPANION_FEATURES.map(f => `
                        <div class="companion-feature-item">
                            <span class="feature-icon">${f.icon}</span>
                            <div class="feature-info">
                                <strong>${f.name}</strong>
                                <span class="feature-desc">${f.desc}</span>
                            </div>
                        </div>
                    `).join('')}
                </div>

                <div class="companion-dont-ask">
                    <label>
                        <input type="checkbox" id="companionDontAskAgain">
                        <span>Don't ask again (use ADB-only mode)</span>
                    </label>
                </div>

                <div class="companion-actions">
                    <button id="btnInstallCompanion" class="btn btn-primary">
                        <span class="btn-icon">\uD83D\uDCE5</span> Install via ADB
                    </button>
                    <button id="btnSkipCompanion" class="btn btn-secondary">
                        Continue with ADB Only
                    </button>
                </div>

                <button id="btnCloseCompanionDialog" class="companion-close-btn" title="Close">&times;</button>
            </div>
        `;

        document.body.appendChild(dialog);

        // Wire up event handlers
        const closeHandler = (action) => {
            const dontAskAgain = document.getElementById('companionDontAskAgain')?.checked || false;

            if (dontAskAgain) {
                try {
                    localStorage.setItem('companion.dontAskInstall', 'true');
                } catch {
                    // Ignore storage errors
                }
            }

            dialog.remove();
            resolve({ action, dontAskAgain });
        };

        // Close button
        document.getElementById('btnCloseCompanionDialog').addEventListener('click', () => {
            closeHandler('skip');
        });

        // Skip button
        document.getElementById('btnSkipCompanion').addEventListener('click', () => {
            closeHandler('skip');
        });

        // Install button
        document.getElementById('btnInstallCompanion').addEventListener('click', async () => {
            const btn = document.getElementById('btnInstallCompanion');
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-icon">\u23F3</span> Installing...';

            try {
                const result = await installCompanionApp(deviceId);

                if (result.success) {
                    btn.innerHTML = '<span class="btn-icon">\u2713</span> Installed!';
                    btn.classList.remove('btn-primary');
                    btn.classList.add('btn-success');

                    showToast('Companion app installed successfully!', 'success', 3000);

                    // Auto-close after success
                    setTimeout(() => {
                        dialog.remove();
                        resolve({ action: 'installed', dontAskAgain: false });
                    }, 1500);
                } else {
                    throw new Error(result.error || 'Installation failed');
                }
            } catch (error) {
                btn.disabled = false;
                btn.innerHTML = '<span class="btn-icon">\uD83D\uDCE5</span> Retry Install';

                showToast(`Installation failed: ${error.message}`, 'error', 5000);
            }
        });

        // Click outside to close
        dialog.addEventListener('click', (e) => {
            if (e.target === dialog) {
                closeHandler('skip');
            }
        });

        // Escape key to close
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                document.removeEventListener('keydown', escHandler);
                closeHandler('skip');
            }
        };
        document.addEventListener('keydown', escHandler);
    });
}

/**
 * Check companion installation and show dialog if not installed
 * Convenience function that combines check and dialog
 * @param {string} deviceId - Device ID to check
 * @returns {Promise<{installed: boolean, skipped: boolean, dontAskAgain?: boolean, version?: string}>}
 */
export async function checkAndPromptCompanionInstall(deviceId) {
    // Skip if user opted out
    if (!shouldCheckCompanionInstall()) {
        console.log('[CompanionInstallDialog] User opted out of install prompts');
        return { installed: false, skipped: true, dontAskAgain: true };
    }

    // Check installation status
    const status = await checkCompanionInstalled(deviceId);

    if (status.installed) {
        const version = status.version || 'unknown';
        console.log(`[CompanionInstallDialog] Companion app already installed (v${version})`);

        // Show positive feedback that companion was detected
        showToast(`Companion app detected (v${version})`, 'success', 2500);

        return { installed: true, skipped: false, version };
    }

    // Show dialog
    console.log('[CompanionInstallDialog] Companion not installed, showing prompt');
    const result = await showCompanionInstallDialog(deviceId);

    return {
        installed: result.action === 'installed',
        skipped: result.action === 'skip',
        dontAskAgain: result.dontAskAgain
    };
}

export default {
    shouldCheckCompanionInstall,
    resetCompanionInstallPreference,
    checkCompanionInstalled,
    installCompanionApp,
    showCompanionInstallDialog,
    checkAndPromptCompanionInstall
};
