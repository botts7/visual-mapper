/**
 * Onboarding Wizard Module
 *
 * Multi-step wizard for first-time device setup.
 *
 * Steps:
 * 1. Welcome - Introduction and requirements
 * 2. Connect Device - Network scan or manual entry
 * 3. Test Connection - Verify device connectivity
 * 4. Security - Configure lock screen settings
 * 5. Complete - Success screen with next steps
 *
 * @module OnboardingWizard
 */

import DeviceSecurityUI from './device-security.js?v=0.0.5';

class OnboardingWizard {
    constructor() {
        this.currentStep = 1;
        this.totalSteps = 5;
        this.selectedMethod = null; // 'scan' or 'manual'
        this.selectedDevice = null; // { ip, port, device_id }
        this.scannedDevices = [];
        this.isScanning = false;
        this.securityUI = null;
    }

    /**
     * Initialize the wizard
     */
    async init() {
        console.log('[Onboarding] Initializing wizard');

        // Check if onboarding was already completed
        if (this.isOnboardingComplete()) {
            console.log('[Onboarding] Already completed, redirecting to main app');
            window.location.href = 'devices.html';
            return;
        }

        this.updateUI();
    }

    /**
     * Check if onboarding has been completed
     */
    isOnboardingComplete() {
        return localStorage.getItem('onboarding_complete') === 'true';
    }

    /**
     * Mark onboarding as complete
     */
    markOnboardingComplete() {
        localStorage.setItem('onboarding_complete', 'true');
        localStorage.setItem('onboarding_completed_at', new Date().toISOString());
    }

    /**
     * Navigate to next step
     */
    async nextStep() {
        console.log(`[Onboarding] Next step requested from step ${this.currentStep}`);

        // Validate current step before proceeding
        const isValid = await this.validateCurrentStep();
        if (!isValid) {
            console.log('[Onboarding] Validation failed, staying on current step');
            return;
        }

        // Handle step-specific actions
        if (this.currentStep === 2) {
            // Move to connection test
            await this.testConnection();
        } else if (this.currentStep === 3) {
            // Connection test complete, move to security
            await this.initializeSecurity();
        } else if (this.currentStep === 4) {
            // Security configured, complete onboarding
            this.completeOnboarding();
        } else if (this.currentStep === 5) {
            // Done - redirect to main app
            window.location.href = 'devices.html';
            return;
        }

        // Move to next step
        if (this.currentStep < this.totalSteps) {
            this.currentStep++;
            this.updateUI();
        }
    }

    /**
     * Navigate to previous step
     */
    previousStep() {
        console.log(`[Onboarding] Previous step requested from step ${this.currentStep}`);

        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateUI();
        }
    }

    /**
     * Validate current step before proceeding
     */
    async validateCurrentStep() {
        switch (this.currentStep) {
            case 1:
                // Welcome - always valid
                return true;

            case 2:
                // Connect Device - must select a device
                if (!this.selectedDevice) {
                    this.showStatus('step2Status', 'Please select a device or enter device details', 'error');
                    return false;
                }
                return true;

            case 3:
                // Test Connection - auto-handled by testConnection()
                return true;

            case 4:
                // Security - optional, can skip
                return true;

            case 5:
                // Complete - always valid
                return true;

            default:
                return true;
        }
    }

    /**
     * Update UI for current step
     */
    updateUI() {
        console.log(`[Onboarding] Updating UI for step ${this.currentStep}`);

        // Update step indicator
        document.querySelectorAll('.step').forEach((step, index) => {
            const stepNumber = index + 1;
            step.classList.remove('active', 'completed');

            if (stepNumber < this.currentStep) {
                step.classList.add('completed');
            } else if (stepNumber === this.currentStep) {
                step.classList.add('active');
            }
        });

        // Update progress bar
        const progress = ((this.currentStep - 1) / (this.totalSteps - 1)) * 100;
        document.getElementById('progressFill').style.width = `${progress}%`;

        // Update step content visibility
        document.querySelectorAll('.step-content').forEach((content, index) => {
            const stepNumber = index + 1;
            content.classList.toggle('active', stepNumber === this.currentStep);
        });

        // Update navigation buttons
        this.updateNavigationButtons();
    }

    /**
     * Update navigation button states
     */
    updateNavigationButtons() {
        const btnBack = document.getElementById('btnBack');
        const btnNext = document.getElementById('btnNext');
        const skipContainer = document.getElementById('skipContainer');

        // Back button - show on steps 2-5
        btnBack.style.display = this.currentStep > 1 ? 'block' : 'none';

        // Skip button - only on step 1
        skipContainer.style.display = this.currentStep === 1 ? 'block' : 'none';

        // Next button text
        const nextTexts = {
            1: 'Get Started →',
            2: 'Connect Device →',
            3: 'Continue →',
            4: 'Finish Setup →',
            5: 'Go to Dashboard →'
        };
        btnNext.textContent = nextTexts[this.currentStep] || 'Next →';

        // Disable next button on step 3 (auto-progresses)
        btnNext.disabled = this.currentStep === 3;
    }

    /**
     * Select connection method (scan or manual)
     */
    async selectConnectionMethod(method) {
        console.log(`[Onboarding] Selected connection method: ${method}`);
        this.selectedMethod = method;

        // Update UI
        document.querySelectorAll('.method-card').forEach(card => {
            card.classList.remove('selected');
        });
        document.getElementById(`method${method.charAt(0).toUpperCase() + method.slice(1)}`).classList.add('selected');

        // Show appropriate UI
        const scanResults = document.getElementById('scanResults');
        const manualForm = document.getElementById('manualForm');

        if (method === 'scan') {
            scanResults.classList.remove('hidden');
            manualForm.classList.add('hidden');
            await this.scanNetwork();
        } else {
            scanResults.classList.add('hidden');
            manualForm.classList.remove('hidden');
            this.setupManualEntry();
        }
    }

    /**
     * Scan network for devices
     */
    async scanNetwork() {
        if (this.isScanning) return;

        console.log('[Onboarding] Starting network scan');
        this.isScanning = true;
        this.showStatus('step2Status', 'Scanning network for devices...', 'info');

        try {
            const response = await fetch(`${window.API_BASE}/adb/scan`);

            if (!response.ok) {
                throw new Error(`Scan failed: ${response.statusText}`);
            }

            const data = await response.json();
            this.scannedDevices = data.devices || [];

            console.log(`[Onboarding] Found ${this.scannedDevices.length} devices`);

            if (this.scannedDevices.length === 0) {
                this.showStatus('step2Status', 'No devices found. Try manual entry or check your device settings.', 'error');
                this.renderDeviceList([]);
            } else {
                this.showStatus('step2Status', `Found ${this.scannedDevices.length} device(s)`, 'success');
                this.renderDeviceList(this.scannedDevices);
            }
        } catch (error) {
            console.error('[Onboarding] Scan error:', error);
            this.showStatus('step2Status', `Scan failed: ${error.message}`, 'error');
            this.renderDeviceList([]);
        } finally {
            this.isScanning = false;
        }
    }

    /**
     * Render device list
     */
    renderDeviceList(devices) {
        const deviceList = document.getElementById('deviceList');
        deviceList.innerHTML = '';

        if (devices.length === 0) {
            deviceList.innerHTML = '<div style="padding: 16px; text-align: center; color: #999;">No devices found</div>';
            return;
        }

        // Separate connected and discovered devices
        const connectedDevices = devices.filter(d => d.state === 'connected' || d.connected);
        const discoveredDevices = devices.filter(d => d.state !== 'connected' && !d.connected);

        // Render connected devices first
        if (connectedDevices.length > 0) {
            const connectedHeader = document.createElement('div');
            connectedHeader.style.cssText = 'font-weight: 600; color: #4caf50; margin-bottom: 8px; font-size: 14px;';
            connectedHeader.textContent = '✓ Already Connected';
            deviceList.appendChild(connectedHeader);

            connectedDevices.forEach(device => {
                deviceList.appendChild(this.createDeviceItem(device, true));
            });

            // Add separator if there are also discovered devices
            if (discoveredDevices.length > 0) {
                const separator = document.createElement('div');
                separator.style.cssText = 'border-top: 1px solid #e0e0e0; margin: 16px 0;';
                deviceList.appendChild(separator);

                const discoveredHeader = document.createElement('div');
                discoveredHeader.style.cssText = 'font-weight: 600; color: #666; margin-bottom: 8px; font-size: 14px;';
                discoveredHeader.textContent = '🔍 Discovered Devices';
                deviceList.appendChild(discoveredHeader);
            }
        }

        // Render discovered devices
        discoveredDevices.forEach(device => {
            deviceList.appendChild(this.createDeviceItem(device, false));
        });
    }

    /**
     * Create a device list item
     */
    createDeviceItem(device, isConnected) {
        const deviceItem = document.createElement('div');
        deviceItem.className = 'device-item';

        const statusBadge = isConnected
            ? '<span style="background: #4caf50; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-left: 8px;">Connected</span>'
            : '';

        deviceItem.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <div style="font-weight: 600;">${device.ip}:${device.port}${statusBadge}</div>
                    <div style="font-size: 14px; color: #666; margin-top: 4px;">
                        ${device.name || device.model || 'Android Device'}
                    </div>
                </div>
            </div>
        `;
        deviceItem.onclick = () => this.selectDevice(device);

        return deviceItem;
    }

    /**
     * Setup manual entry
     */
    setupManualEntry() {
        const connectionType = document.getElementById('connectionType');

        // Connection type change handler
        connectionType.addEventListener('change', () => {
            this.updateConnectionTypeUI();
        });

        // Setup input handlers for each connection type
        this.setupTcpInputs();
        this.setupPairingInputs();

        // Initialize UI
        this.updateConnectionTypeUI();
    }

    /**
     * Update UI based on selected connection type
     */
    updateConnectionTypeUI() {
        const connectionType = document.getElementById('connectionType').value;

        const tcpConfig = document.getElementById('tcpConfig');
        const pairingConfig = document.getElementById('pairingConfig');
        const wirelessConfig = document.getElementById('wirelessConfig');
        const tlsConfig = document.getElementById('tlsConfig');

        // Hide all configs
        tcpConfig.classList.add('hidden');
        pairingConfig.classList.add('hidden');
        wirelessConfig.classList.add('hidden');
        tlsConfig.classList.add('hidden');

        // Show appropriate config
        switch (connectionType) {
            case 'tcp':
            case 'tls':
                tcpConfig.classList.remove('hidden');
                if (connectionType === 'tls') {
                    tlsConfig.classList.remove('hidden');
                }
                break;
            case 'wireless':
                tcpConfig.classList.remove('hidden');
                wirelessConfig.classList.remove('hidden');
                break;
            case 'pairing':
                pairingConfig.classList.remove('hidden');
                break;
        }

        // Clear selected device when connection type changes
        this.selectedDevice = null;
    }

    /**
     * Setup TCP/Wireless/TLS input handlers
     */
    setupTcpInputs() {
        const deviceIp = document.getElementById('deviceIp');
        const devicePort = document.getElementById('devicePort');

        const updateDevice = () => {
            const connectionType = document.getElementById('connectionType').value;
            const ip = deviceIp.value.trim();
            const port = parseInt(devicePort.value);

            if (ip && port) {
                this.selectedDevice = {
                    ip: ip,
                    port: port,
                    device_id: `${ip}:${port}`,
                    connection_type: connectionType
                };
                console.log('[Onboarding] Manual device entered:', this.selectedDevice);
            } else {
                this.selectedDevice = null;
            }
        };

        deviceIp.addEventListener('input', updateDevice);
        devicePort.addEventListener('input', updateDevice);
    }

    /**
     * Setup pairing input handlers
     */
    setupPairingInputs() {
        const pairingCode = document.getElementById('pairingCode');
        const pairingHost = document.getElementById('pairingHost');
        const pairingPort = document.getElementById('pairingPort');
        const connectionPort = document.getElementById('connectionPort');

        const updatePairingDevice = () => {
            const code = pairingCode.value.trim();
            const ip = pairingHost.value.trim();
            const pPort = parseInt(pairingPort.value);
            const cPort = parseInt(connectionPort.value);

            if (code && ip && pPort && cPort) {
                this.selectedDevice = {
                    ip: ip,
                    pairing_code: code,
                    pairing_port: pPort,
                    port: cPort,
                    device_id: `${ip}:${cPort}`,
                    connection_type: 'pairing'
                };
                console.log('[Onboarding] Pairing device entered:', this.selectedDevice);
            } else {
                this.selectedDevice = null;
            }
        };

        pairingCode.addEventListener('input', updatePairingDevice);
        pairingHost.addEventListener('input', updatePairingDevice);
        pairingPort.addEventListener('input', updatePairingDevice);
        connectionPort.addEventListener('input', updatePairingDevice);
    }

    /**
     * Select a device
     */
    selectDevice(device) {
        console.log('[Onboarding] Selected device:', device);
        this.selectedDevice = device;

        // Update UI
        document.querySelectorAll('.device-item').forEach(item => {
            item.classList.remove('selected');
        });
        event.target.closest('.device-item')?.classList.add('selected');
    }

    /**
     * Test connection to selected device
     */
    async testConnection() {
        if (!this.selectedDevice) {
            this.showStatus('step3Status', 'No device selected', 'error');
            return;
        }

        console.log('[Onboarding] Testing connection to device:', this.selectedDevice);

        try {
            // Handle pairing connection type differently
            if (this.selectedDevice.connection_type === 'pairing') {
                await this.pairAndConnect();
            } else {
                await this.directConnect();
            }
        } catch (error) {
            console.error('[Onboarding] Connection test failed:', error);
            this.showStatus('step3Status', `Connection failed: ${error.message}`, 'error');

            // Go back to step 2
            setTimeout(() => {
                this.currentStep = 2;
                this.updateUI();
            }, 2000);
        }
    }

    /**
     * Handle pairing connection (Android 11+)
     */
    async pairAndConnect() {
        this.showStatus('step3Status', 'Pairing with device...', 'info');

        // Step 1: Pair with device
        const pairResponse = await fetch(`${window.API_BASE}/adb/pair`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ip: this.selectedDevice.ip,
                pairing_port: this.selectedDevice.pairing_port,
                pairing_code: this.selectedDevice.pairing_code
            })
        });

        if (!pairResponse.ok) {
            throw new Error(`Pairing failed: ${pairResponse.statusText}`);
        }

        const pairData = await pairResponse.json();

        if (!pairData.success) {
            throw new Error(pairData.message || 'Pairing failed');
        }

        this.showStatus('step3Status', 'Paired! Now connecting...', 'info');

        // Step 2: Connect to device
        const connectResponse = await fetch(`${window.API_BASE}/adb/connect`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ip: this.selectedDevice.ip,
                port: this.selectedDevice.port
            })
        });

        if (!connectResponse.ok) {
            throw new Error(`Connection failed: ${connectResponse.statusText}`);
        }

        const connectData = await connectResponse.json();

        if (connectData.success) {
            // Update device_id if returned from server
            if (connectData.device_id) {
                this.selectedDevice.device_id = connectData.device_id;
            }

            this.showStatus('step3Status', 'Pairing and connection successful!', 'success');
            console.log('[Onboarding] Pairing connection test passed');

            // Auto-advance to next step after delay
            setTimeout(() => {
                this.nextStep();
            }, 1500);
        } else {
            throw new Error(connectData.message || 'Connection failed');
        }
    }

    /**
     * Handle direct connection (TCP/IP, Wireless ADB, TLS)
     */
    async directConnect() {
        this.showStatus('step3Status', 'Connecting to device...', 'info');

        const connectResponse = await fetch(`${window.API_BASE}/adb/connect`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ip: this.selectedDevice.ip,
                port: this.selectedDevice.port
            })
        });

        if (!connectResponse.ok) {
            throw new Error(`Connection failed: ${connectResponse.statusText}`);
        }

        const connectData = await connectResponse.json();

        if (connectData.success) {
            // Update device_id if returned from server
            if (connectData.device_id) {
                this.selectedDevice.device_id = connectData.device_id;
            }

            this.showStatus('step3Status', 'Connection successful!', 'success');
            console.log('[Onboarding] Connection test passed');

            // Auto-advance to next step after delay
            setTimeout(() => {
                this.nextStep();
            }, 1500);
        } else {
            throw new Error(connectData.message || 'Connection failed');
        }
    }

    /**
     * Initialize security configuration
     */
    async initializeSecurity() {
        if (!this.selectedDevice) {
            console.error('[Onboarding] No device selected for security setup');
            return;
        }

        console.log('[Onboarding] Initializing security configuration');

        const container = document.getElementById('securityConfigContainer');

        // Create security UI
        this.securityUI = new DeviceSecurityUI();
        await this.securityUI.initialize(this.selectedDevice.device_id, container);
    }

    /**
     * Complete onboarding
     */
    completeOnboarding() {
        console.log('[Onboarding] Onboarding complete');
        this.markOnboardingComplete();
    }

    /**
     * Skip onboarding
     */
    skip() {
        console.log('[Onboarding] User skipped onboarding');

        if (confirm('Are you sure you want to skip setup? You can always add devices later from the Devices page.')) {
            this.markOnboardingComplete();
            window.location.href = 'devices.html';
        }
    }

    /**
     * Show status message
     */
    showStatus(elementId, message, type = 'info') {
        const statusElement = document.getElementById(elementId);
        if (!statusElement) return;

        statusElement.className = `status-message ${type} show`;
        statusElement.textContent = message;

        // Auto-hide after 5 seconds for success messages
        if (type === 'success') {
            setTimeout(() => {
                statusElement.classList.remove('show');
            }, 5000);
        }
    }

    /**
     * Reset onboarding (for development/testing)
     */
    static reset() {
        localStorage.removeItem('onboarding_complete');
        localStorage.removeItem('onboarding_completed_at');
        console.log('[Onboarding] Reset complete');
    }
}

// Dual export pattern
export default OnboardingWizard;
export { OnboardingWizard };
window.OnboardingWizard = OnboardingWizard;
