/**
 * Device Security Module
 *
 * Handles lock screen configuration and encrypted passcode storage for Android devices.
 *
 * Features:
 * - 4 lock strategies: no_lock, smart_lock, auto_unlock, manual_only
 * - Encrypted passcode storage (PBKDF2 + Fernet)
 * - Test unlock functionality
 * - Smart Lock helper (opens settings on device)
 *
 * @module device-security
 */

import APIClient from './api-client.js?v=0.4.0-beta.3.1';

/**
 * DeviceSecurityUI - Manages device lock screen configuration UI
 */
class DeviceSecurityUI {
    constructor() {
        this.apiClient = new APIClient();
        this.currentDeviceId = null;
        this.currentConfig = null;
        this.onSaveCallback = null;
        this.onCancelCallback = null;
    }

    /**
     * Initialize security UI for device
     * @param {string} deviceId - Device identifier
     * @param {HTMLElement} container - Container element for security UI
     * @param {Object} callbacks - Optional callbacks {onSave, onCancel}
     */
    async initialize(deviceId, container, callbacks = {}) {
        this.currentDeviceId = deviceId;
        this.container = container;
        this.onSaveCallback = callbacks.onSave || null;
        this.onCancelCallback = callbacks.onCancel || null;

        // Load current configuration
        await this.loadConfig();

        // Render UI
        this.render();

        // Attach event listeners
        this.attachEventListeners();
    }

    /**
     * Load security configuration from API
     */
    async loadConfig() {
        try {
            const response = await this.apiClient.get(`/device/${this.currentDeviceId}/security`);
            this.currentConfig = response.config;
            console.log('[DeviceSecurity] Loaded config:', this.currentConfig);
        } catch (error) {
            console.error('[DeviceSecurity] Failed to load config:', error);
            this.currentConfig = null;
        }
    }

    /**
     * Render security configuration UI
     */
    render() {
        const currentStrategy = this.currentConfig?.strategy || 'manual_only';
        const hasPasscode = this.currentConfig?.has_passcode || false;
        const notes = this.currentConfig?.notes || '';
        const sleepGracePeriod = this.currentConfig?.sleep_grace_period || 300;

        this.container.innerHTML = `
            <div class="security-config">
                <h3>Lock Screen Configuration</h3>
                <p class="security-description">
                    Choose how Visual Mapper handles device lock screen security.
                </p>

                <div class="strategy-options">
                    <label class="strategy-option">
                        <input type="radio" name="lock-strategy" value="no_lock" ${currentStrategy === 'no_lock' ? 'checked' : ''}>
                        <div class="strategy-info">
                            <strong>No Lock Screen</strong>
                            <p>Remove lock screen for convenience (least secure)</p>
                        </div>
                    </label>

                    <label class="strategy-option recommended">
                        <input type="radio" name="lock-strategy" value="smart_lock" ${currentStrategy === 'smart_lock' ? 'checked' : ''}>
                        <div class="strategy-info">
                            <strong>Smart Lock / Trusted Places</strong>
                            <span class="badge">Recommended</span>
                            <p>Use Android's built-in Smart Lock feature (secure + convenient)</p>
                            <button type="button" class="btn btn-secondary btn-sm" id="open-smart-lock">
                                Configure Smart Lock on Device
                            </button>
                        </div>
                    </label>

                    <label class="strategy-option">
                        <input type="radio" name="lock-strategy" value="auto_unlock" ${currentStrategy === 'auto_unlock' ? 'checked' : ''}>
                        <div class="strategy-info">
                            <strong>Automatic Unlock</strong>
                            <p>Store encrypted passcode (moderate security)</p>
                        </div>
                    </label>

                    <label class="strategy-option">
                        <input type="radio" name="lock-strategy" value="manual_only" ${currentStrategy === 'manual_only' ? 'checked' : ''}>
                        <div class="strategy-info">
                            <strong>Manual Unlock Only</strong>
                            <p>You unlock device manually (most secure)</p>
                        </div>
                    </label>
                </div>

                <div class="passcode-section" id="passcode-section" style="display: ${currentStrategy === 'auto_unlock' ? 'block' : 'none'};">
                    <h4>Device Passcode</h4>
                    <p class="help-text">
                        ${hasPasscode ? 'Passcode is already saved (encrypted). Enter a new passcode to update it.' : 'Enter your device passcode. It will be encrypted and stored securely.'}
                    </p>

                    <div class="security-warning" style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; padding: 12px; margin-bottom: 15px;">
                        <strong style="color: #856404;">⚠️ Privacy Notice:</strong>
                        <p style="color: #856404; margin: 8px 0 0 0; font-size: 13px;">
                            When auto-unlock runs, each PIN digit will briefly appear on the device screen before being masked.
                            This is Android's built-in behavior and cannot be hidden via ADB.
                            Consider using <strong>Smart Lock</strong> for a more discrete unlock experience.
                        </p>
                    </div>

                    <div class="security-info" style="background: #e3f2fd; border: 1px solid #2196f3; border-radius: 6px; padding: 12px; margin-bottom: 15px;">
                        <strong style="color: #1565c0;">🔒 Lockout Protection:</strong>
                        <p style="color: #1565c0; margin: 8px 0 0 0; font-size: 13px;">
                            To prevent device lockout, auto-unlock will only attempt <strong>2 times</strong> before entering a 5-minute cooldown.
                            If unlock fails, you'll need to manually unlock the device.
                        </p>
                    </div>

                    <div class="form-group">
                        <label for="passcode-input">Passcode / PIN:</label>
                        <input type="password" id="passcode-input" class="form-control" placeholder="Enter passcode">
                        <small class="form-text">Numeric passcode or PIN only (pattern locks not supported)</small>
                    </div>

                    <div class="passcode-actions">
                        <button type="button" class="btn btn-secondary" id="test-unlock">
                            Test Unlock
                        </button>
                        <button type="button" class="btn btn-secondary" id="toggle-passcode-visibility">
                            Show Passcode
                        </button>
                    </div>

                    <div id="test-result" class="test-result" style="display: none;"></div>
                </div>

                <div class="form-group">
                    <label for="security-notes">Notes (optional):</label>
                    <textarea id="security-notes" class="form-control" rows="2" placeholder="Add notes about this configuration">${notes}</textarea>
                </div>

                <div class="form-group" id="grace-period-section" style="display: ${currentStrategy === 'auto_unlock' ? 'block' : 'none'};">
                    <label for="sleep-grace-period">Sleep Grace Period:</label>
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <input type="range" id="sleep-grace-period" class="form-range"
                               min="60" max="600" step="30" value="${sleepGracePeriod}"
                               style="flex: 1;">
                        <span id="grace-period-value" style="min-width: 60px;">${Math.round(sleepGracePeriod / 60)} min</span>
                    </div>
                    <small class="form-text">Don't sleep screen if another flow is scheduled within this time</small>
                </div>

                <div class="security-actions">
                    <button type="button" class="btn btn-primary" id="save-security">
                        Save Configuration
                    </button>
                    <button type="button" class="btn btn-secondary" id="cancel-security">
                        Cancel
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Attach event listeners to UI elements
     */
    attachEventListeners() {
        // Strategy radio buttons
        const strategyRadios = this.container.querySelectorAll('input[name="lock-strategy"]');
        strategyRadios.forEach(radio => {
            radio.addEventListener('change', () => this.onStrategyChange());
        });

        // Smart Lock button
        const smartLockBtn = this.container.querySelector('#open-smart-lock');
        if (smartLockBtn) {
            smartLockBtn.addEventListener('click', () => this.openSmartLockSettings());
        }

        // Test unlock button
        const testUnlockBtn = this.container.querySelector('#test-unlock');
        if (testUnlockBtn) {
            testUnlockBtn.addEventListener('click', () => this.testUnlock());
        }

        // Toggle passcode visibility
        const toggleVisibilityBtn = this.container.querySelector('#toggle-passcode-visibility');
        if (toggleVisibilityBtn) {
            toggleVisibilityBtn.addEventListener('click', () => this.togglePasscodeVisibility());
        }

        // Save button
        const saveBtn = this.container.querySelector('#save-security');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveConfiguration());
        }

        // Cancel button
        const cancelBtn = this.container.querySelector('#cancel-security');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.cancel());
        }

        // Grace period slider
        const gracePeriodSlider = this.container.querySelector('#sleep-grace-period');
        const gracePeriodValue = this.container.querySelector('#grace-period-value');
        if (gracePeriodSlider && gracePeriodValue) {
            gracePeriodSlider.addEventListener('input', () => {
                const minutes = Math.round(gracePeriodSlider.value / 60);
                gracePeriodValue.textContent = `${minutes} min`;
            });
        }
    }

    /**
     * Handle strategy change
     */
    onStrategyChange() {
        const selectedStrategy = this.container.querySelector('input[name="lock-strategy"]:checked')?.value;
        const passcodeSection = this.container.querySelector('#passcode-section');
        const gracePeriodSection = this.container.querySelector('#grace-period-section');

        if (selectedStrategy === 'auto_unlock') {
            passcodeSection.style.display = 'block';
            gracePeriodSection.style.display = 'block';
        } else {
            passcodeSection.style.display = 'none';
            gracePeriodSection.style.display = 'none';
        }
    }

    /**
     * Open Smart Lock settings on device
     */
    async openSmartLockSettings() {
        try {
            console.log('[DeviceSecurity] Opening Smart Lock settings on device');

            // Use shell API to open Smart Lock settings
            const response = await this.apiClient.post(`/shell/${this.currentDeviceId}/execute`, {
                command: 'am start -a android.settings.SECURITY_SETTINGS'
            });

            alert('Smart Lock settings opened on device.\n\nTo configure:\n1. Find "Smart Lock" in security settings\n2. Add your home location as a "Trusted Place"\n3. Device will stay unlocked when at this location');
        } catch (error) {
            console.error('[DeviceSecurity] Failed to open Smart Lock settings:', error);
            alert('Failed to open Smart Lock settings on device. Please open Security settings manually.');
        }
    }

    /**
     * Test unlock with entered passcode
     */
    async testUnlock() {
        const passcodeInput = this.container.querySelector('#passcode-input');
        const passcode = passcodeInput?.value;
        const testResult = this.container.querySelector('#test-result');

        if (!passcode) {
            testResult.style.display = 'block';
            testResult.className = 'test-result error';
            testResult.textContent = 'Please enter a passcode first';
            return;
        }

        try {
            testResult.style.display = 'block';
            testResult.className = 'test-result info';
            testResult.textContent = 'Testing unlock...';

            const response = await this.apiClient.post(`/device/${this.currentDeviceId}/unlock`, {
                passcode: passcode
            });

            if (response.success) {
                testResult.className = 'test-result success';
                testResult.textContent = '✅ Unlock successful! Passcode is correct.';
            } else {
                testResult.className = 'test-result error';
                testResult.textContent = '❌ Unlock failed. Please check your passcode and try again.';
            }
        } catch (error) {
            console.error('[DeviceSecurity] Failed to test unlock:', error);
            testResult.style.display = 'block';
            testResult.className = 'test-result error';
            testResult.textContent = '❌ Error testing unlock: ' + error.message;
        }
    }

    /**
     * Toggle passcode visibility
     */
    togglePasscodeVisibility() {
        const passcodeInput = this.container.querySelector('#passcode-input');
        const toggleBtn = this.container.querySelector('#toggle-passcode-visibility');

        if (passcodeInput.type === 'password') {
            passcodeInput.type = 'text';
            toggleBtn.textContent = 'Hide Passcode';
        } else {
            passcodeInput.type = 'password';
            toggleBtn.textContent = 'Show Passcode';
        }
    }

    /**
     * Save security configuration
     */
    async saveConfiguration() {
        const selectedStrategy = this.container.querySelector('input[name="lock-strategy"]:checked')?.value;
        const passcodeInput = this.container.querySelector('#passcode-input');
        const passcode = passcodeInput?.value;
        const notesInput = this.container.querySelector('#security-notes');
        const notes = notesInput?.value;
        const gracePeriodSlider = this.container.querySelector('#sleep-grace-period');
        const sleepGracePeriod = gracePeriodSlider ? parseInt(gracePeriodSlider.value) : 300;

        // Validate
        if (!selectedStrategy) {
            alert('Please select a lock strategy');
            return;
        }

        if (selectedStrategy === 'auto_unlock' && !passcode && !this.currentConfig?.has_passcode) {
            alert('Please enter a passcode for automatic unlock strategy');
            return;
        }

        try {
            console.log('[DeviceSecurity] Saving configuration:', { strategy: selectedStrategy, sleepGracePeriod });

            const payload = {
                strategy: selectedStrategy,
                notes: notes,
                sleep_grace_period: sleepGracePeriod
            };

            // Only include passcode if it's entered (for auto_unlock or updating existing)
            if (passcode) {
                payload.passcode = passcode;
            }

            const response = await this.apiClient.post(`/device/${this.currentDeviceId}/security`, payload);

            if (response.success) {
                alert('Security configuration saved successfully!');
                await this.loadConfig();
                this.render();
                this.attachEventListeners();

                // Call onSave callback if provided
                if (this.onSaveCallback) {
                    this.onSaveCallback();
                }
            } else {
                alert('Failed to save configuration');
            }
        } catch (error) {
            console.error('[DeviceSecurity] Failed to save configuration:', error);
            alert('Error saving configuration: ' + error.message);
        }
    }

    /**
     * Cancel configuration changes
     */
    cancel() {
        // Call onCancel callback if provided, otherwise just reload
        if (this.onCancelCallback) {
            this.onCancelCallback();
        } else {
            // Reload config and re-render
            this.loadConfig().then(() => {
                this.render();
                this.attachEventListeners();
            });
        }
    }
}

// Export for use in other modules
export default DeviceSecurityUI;

// Also expose globally for onclick handlers
window.DeviceSecurityUI = DeviceSecurityUI;
