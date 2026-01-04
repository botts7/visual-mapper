/**
 * Flow Wizard Step 1 - Device Selection
 * Visual Mapper v0.0.6
 *
 * v0.0.6: Pause sensor updates when device is selected
 */

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

/**
 * Load Step 1: Device Selection
 * @param {Object} wizard - FlowWizard instance for state access
 * @returns {Promise<void>}
 */
export async function loadStep(wizard) {
    console.log('[Step1] Loading Device Selection');
    const deviceList = document.getElementById('deviceList');

    if (!deviceList) {
        console.error('[Step1] deviceList element not found');
        return;
    }

    try {
        const response = await fetch(`${getApiBase()}/adb/devices`);
        if (!response.ok) throw new Error('Failed to fetch devices');

        const data = await response.json();
        const devices = data.devices || [];
        console.log('[Step1] Devices loaded:', devices.length);

        if (devices.length === 0) {
            deviceList.innerHTML = `
                <div class="empty-state">
                    <p>No devices connected</p>
                    <p><a href="devices.html" class="btn btn-primary">Connect a Device</a></p>
                </div>
            `;
            return;
        }

        // Render device grid
        deviceList.className = 'device-grid';
        deviceList.innerHTML = devices.map(device => `
            <div class="device-card" data-device="${device.id}">
                <div class="device-icon">📱</div>
                <div class="device-name">${device.model || device.id}</div>
                <div class="device-status">
                    <span class="status-dot" style="background: ${device.state === 'device' ? '#22c55e' : '#ef4444'}"></span>
                    ${device.state}
                </div>
            </div>
        `).join('');

        // Add "Add New Device" card
        deviceList.insertAdjacentHTML('beforeend', `
            <div class="device-card" onclick="window.location.href='devices.html'">
                <div class="device-icon">➕</div>
                <div class="device-name">Add Device</div>
                <div class="device-status">Connect new</div>
            </div>
        `);

        // Handle device selection
        deviceList.querySelectorAll('.device-card[data-device]').forEach(card => {
            card.addEventListener('click', async () => {
                deviceList.querySelectorAll('.device-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');

                const connectionId = card.dataset.device;
                wizard.selectedDevice = connectionId;

                // Resolve to stable device ID for data storage
                try {
                    const response = await fetch(`${getApiBase()}/adb/identity/${encodeURIComponent(connectionId)}`);
                    if (response.ok) {
                        const identity = await response.json();
                        wizard.selectedDeviceStableId = identity.stable_device_id || connectionId;
                        console.log(`[Step1] Device selected: ${connectionId} -> stable ID: ${wizard.selectedDeviceStableId}`);
                    } else {
                        wizard.selectedDeviceStableId = connectionId;
                        console.log('[Step1] Device selected (no stable ID):', connectionId);
                    }
                } catch (error) {
                    wizard.selectedDeviceStableId = connectionId;
                    console.warn('[Step1] Could not resolve stable ID:', error);
                }

                // Pause sensor updates for this device to reduce ADB contention
                if (wizard.pauseSensorUpdates) {
                    await wizard.pauseSensorUpdates(wizard.selectedDevice);
                }
            });
        });

    } catch (error) {
        console.error('[Step1] Error loading devices:', error);
        deviceList.innerHTML = `
            <div class="error-state">
                <p>Error loading devices: ${error.message}</p>
                <button class="btn btn-secondary" onclick="location.reload()">Retry</button>
            </div>
        `;
    }
}

/**
 * Validate Step 1
 * @param {Object} wizard - FlowWizard instance
 * @returns {boolean}
 */
export function validateStep(wizard) {
    if (!wizard.selectedDevice) {
        alert('Please select a device');
        return false;
    }
    return true;
}

/**
 * Get Step 1 data
 * @param {Object} wizard - FlowWizard instance
 * @returns {Object}
 */
export function getStepData(wizard) {
    return {
        selectedDevice: wizard.selectedDevice,
        selectedDeviceStableId: wizard.selectedDeviceStableId || wizard.selectedDevice
    };
}

export default { loadStep, validateStep, getStepData };
