/**
 * Flow Recorder Module
 * Visual Mapper v0.0.13
 *
 * Handles interactive flow recording with screenshot capture,
 * tap detection, and step management
 * v0.0.13: Add forceRestart option - force-stop app before launch for fresh start
 * v0.0.12: Fix addStep - respect existing screen_activity if provided (for pre-action capture)
 * v0.0.11: Add moveStep() method for reordering steps
 */

import { showToast } from './toast.js?v=0.4.0-beta.3.20';
import { ensureDeviceUnlocked as sharedEnsureUnlocked } from './device-unlock.js?v=0.4.0-beta.3.20';

/**
 * Get API base URL for proper routing (supports Home Assistant ingress)
 */
function getApiBase() {
    if (window.API_BASE) return window.API_BASE;
    if (window.opener?.API_BASE) return window.opener.API_BASE;
    const url = window.location.href;
    const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
    if (ingressMatch) return ingressMatch[0] + '/api';
    return '/api';
}

class FlowRecorder {
    constructor(deviceId, appPackage, recordMode = 'execute') {
        this.deviceId = deviceId;
        this.appPackage = appPackage;
        this.recordMode = recordMode; // 'execute' or 'record-only'
        this.forceRestart = true; // Default to fresh start - force-stop app before launching
        this.steps = [];
        this.currentScreenshot = null;
        this.screenshotMetadata = null;
        this.apiBase = getApiBase();

        // Navigation context from the wizard (set by FlowWizard)
        this.currentScreenId = null;
        this.navigationGraph = null;
        this.currentScreenSignature = null;

        console.log(`[FlowRecorder] Initialized for ${deviceId} - ${appPackage} (mode: ${recordMode}, forceRestart: ${this.forceRestart})`);
    }

    /**
     * Set the navigation context from FlowWizard
     * Called when navigation data is available or screen changes
     * @param {string|null} screenId - Current screen ID from navigation graph
     * @param {Object|null} graph - Navigation graph object
     */
    setNavigationContext(screenId, graph = null) {
        this.currentScreenId = screenId;
        if (graph !== null) {
            this.navigationGraph = graph;
        }
        console.log(`[FlowRecorder] Navigation context updated: screenId=${screenId}`);
    }

    /**
     * Set the current screen signature (activity + landmarks hash)
     * @param {string|null} signature - Current screen signature
     */
    setScreenSignature(signature) {
        this.currentScreenSignature = signature;
        console.log(`[FlowRecorder] Screen signature updated: ${signature}`);
    }

    /**
     * Start recording session
     * Launches app and captures initial quick screenshot
     */
    async start() {
        try {
            console.log('[FlowRecorder] Starting recording session...');

            // NOTE: Device unlock is now handled by prepareDeviceForStreaming() in streaming mode
            // or by captureScreenshot() in polling mode. Removed duplicate unlock call here
            // to prevent "max attempts reached" cooldown issues.

            // Launch the app (includes force-stop if forceRestart is true)
            await this.launchApp();

            // Brief wait for app to initialize (reduced from 3s)
            await this.wait(1500);

            // Capture quick screenshot for initial preview (no UI elements)
            await this.captureQuickScreenshot();

            showToast('Quick preview loaded - Choose capture method', 'info', 3000);
            return true;
        } catch (error) {
            console.error('[FlowRecorder] Failed to start:', error);
            showToast(`Failed to start recording: ${error.message}`, 'error');
            return false;
        }
    }

    /**
     * Wait for UI to settle by detecting loading indicators and toast notifications
     * Keeps capturing until no loading elements are detected
     */
    async waitForUIToSettle() {
        console.log('[FlowRecorder] Waiting for UI to settle (smart detection)...');

        const maxAttempts = 10;
        const checkInterval = 1000; // 1 second between checks
        let attempt = 0;

        // Initial wait for app to start rendering
        await this.wait(1500);

        while (attempt < maxAttempts) {
            attempt++;
            console.log(`[FlowRecorder] UI settle check ${attempt}/${maxAttempts}...`);

            // Capture screenshot and check elements
            await this.captureScreenshot();

            // Check if UI is still loading/refreshing
            const isLoading = this.detectLoadingIndicators();

            if (!isLoading) {
                console.log('[FlowRecorder] UI settled - no loading indicators detected');
                break;
            }

            console.log('[FlowRecorder] Loading indicators detected, waiting...');
            await this.wait(checkInterval);
        }

        if (attempt >= maxAttempts) {
            console.warn('[FlowRecorder] Max settle attempts reached, proceeding anyway');
        }
    }

    /**
     * Detect loading indicators, toast notifications, and refresh animations
     * Returns true if any loading elements are detected
     */
    detectLoadingIndicators() {
        if (!this.screenshotMetadata || !this.screenshotMetadata.elements) {
            return false;
        }

        const elements = this.screenshotMetadata.elements;

        // Common loading indicator patterns (case-insensitive)
        const loadingPatterns = [
            /loading/i,
            /refreshing/i,
            /please wait/i,
            /updating/i,
            /syncing/i,
            /processing/i,
            /spinner/i,
            /progress/i
        ];

        // Check for toast notifications or snackbars
        const toastPatterns = [
            /toast/i,
            /snackbar/i,
            /notification/i
        ];

        // Android loading view class patterns
        const loadingClassPatterns = [
            /progressbar/i,              // android.widget.ProgressBar
            /circularprogressindicator/i, // Material Design spinner
            /swiperefreshlayout/i,       // Pull-to-refresh container
            /loadingview/i,              // Custom loading views
            /shimmer/i                   // Shimmer loading effects
        ];

        // Check element text and resource IDs
        for (const el of elements) {
            const text = el.text || '';
            const resourceId = el.resource_id || '';
            const className = el.class || '';

            // Check for loading indicators in text/resourceId
            for (const pattern of loadingPatterns) {
                if (pattern.test(text) || pattern.test(resourceId) || pattern.test(className)) {
                    console.log(`[FlowRecorder] Loading indicator detected: "${text}" (class: ${className}, id: ${resourceId})`);
                    return true;
                }
            }

            // Check for Android loading view classes
            for (const pattern of loadingClassPatterns) {
                if (pattern.test(className)) {
                    console.log(`[FlowRecorder] Loading view detected: ${className} (text: "${text}", id: ${resourceId})`);
                    return true;
                }
            }

            // Check for toast notifications
            for (const pattern of toastPatterns) {
                if (pattern.test(resourceId) || pattern.test(className)) {
                    console.log(`[FlowRecorder] Toast notification detected: "${text}" (${resourceId})`);
                    return true;
                }
            }

            // NOTE: "Updated:" timestamps are NOT loading indicators
            // They're static displays showing last refresh time, not active loading state
            // Removed check that was causing infinite loops in BYD app
        }

        console.log('[FlowRecorder] No loading indicators detected');
        return false;
    }

    /**
     * Detect if current screen is a splash/loading screen
     * Returns true if splash screen is detected
     */
    detectSplashScreen() {
        if (!this.screenshotMetadata?.current_activity) {
            return false;
        }

        const activity = this.screenshotMetadata.current_activity;
        const activityName = (activity.activity || '').toLowerCase();
        const packageName = (activity.package || '').toLowerCase();

        // Common splash screen activity name patterns
        const splashPatterns = [
            /splash/i,
            /launch/i,
            /loading/i,
            /intro/i,
            /welcome/i,
            /startup/i,
            /bootstrap/i,
            /initializ/i,
            /preload/i,
            /^\.main$/i,  // Some apps use .Main as splash
            /logo/i       // BYD uses BYDLogo
        ];

        // Check activity name for splash patterns
        for (const pattern of splashPatterns) {
            if (pattern.test(activityName)) {
                console.log(`[FlowRecorder] Splash screen detected: ${activityName} (pattern: ${pattern})`);
                return true;
            }
        }

        // Also check if very few interactive elements (splash screens are usually minimal)
        const elements = this.screenshotMetadata?.elements || [];
        const clickableElements = elements.filter(el => el.clickable);
        if (clickableElements.length < 3 && elements.length < 10) {
            console.log(`[FlowRecorder] Possible splash screen: only ${clickableElements.length} clickable elements`);
            // Only flag as splash if activity name is somewhat suspicious
            if (/activity|main|app/i.test(activityName)) {
                return true;
            }
        }

        return false;
    }

    /**
     * Wait for splash screen to finish
     * Keeps capturing screenshots until splash screen is gone or timeout
     */
    async waitForSplashScreen(maxWaitMs = 8000, checkIntervalMs = 500) {
        const startTime = Date.now();
        let attempts = 0;
        const maxAttempts = Math.ceil(maxWaitMs / checkIntervalMs);

        console.log(`[FlowRecorder] Waiting for splash screen to finish (max ${maxWaitMs}ms)...`);

        while (attempts < maxAttempts) {
            // Capture current screen state
            await this.captureScreenshot();

            // Check if we're past the splash screen
            if (!this.detectSplashScreen()) {
                const elapsed = Date.now() - startTime;
                console.log(`[FlowRecorder] Splash screen finished after ${elapsed}ms`);
                return true;
            }

            attempts++;
            console.log(`[FlowRecorder] Still on splash screen, waiting... (attempt ${attempts}/${maxAttempts})`);
            await this.wait(checkIntervalMs);
        }

        console.warn(`[FlowRecorder] Splash screen timeout after ${maxWaitMs}ms - proceeding anyway`);
        return false;
    }

    /**
     * Launch the target app
     */
    async launchApp() {
        console.log(`[FlowRecorder] Launching ${this.appPackage} (forceRestart: ${this.forceRestart})...`);

        const response = await fetch(`${this.apiBase}/adb/launch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: this.deviceId,
                package: this.appPackage,
                force_restart: this.forceRestart
            })
        });

        if (!response.ok) {
            throw new Error('Failed to launch app');
        }

        const result = await response.json();
        console.log('[FlowRecorder] App launched:', result);

        // Brief wait for app to start
        await this.wait(500);

        // Wait for any splash screen to finish before capturing activity
        // This ensures we record the main app activity, not a splash/loading screen
        await this.waitForSplashScreen(8000, 500);

        // Also wait for any loading indicators to clear
        await this.waitForUIToSettle(3, 500);

        // Capture the activity that was launched for state validation
        // This is now the ACTUAL main screen, not the splash screen
        const screenInfo = await this.getCurrentScreen();
        const expectedActivity = screenInfo?.activity?.activity || null;
        const screenPackage = screenInfo?.activity?.package || this.appPackage;

        console.log(`[FlowRecorder] Launched to activity: ${expectedActivity}`);

        // Add launch step to flow with state validation data
        await this.addStep({
            step_type: 'launch_app',
            package: this.appPackage,
            description: `Launch ${this.appPackage}`,
            expected_activity: expectedActivity,
            screen_activity: expectedActivity,
            screen_package: screenPackage,
            validate_state: true,
            recovery_action: 'force_restart_app'
        });
    }

    /**
     * Ensure device is unlocked before screenshot capture
     * Delegates to shared device-unlock.js module
     * @param {Function} statusCallback - Optional callback to update status text
     */
    async ensureDeviceUnlocked(statusCallback = null) {
        // Delegate to shared module with simple callback
        return await sharedEnsureUnlocked(this.deviceId, this.apiBase, {
            onStatus: (msg) => {
                console.log(`[FlowRecorder] ${msg}`);
                if (statusCallback) statusCallback(msg);
            }
        });
    }

    /**
     * Capture screenshot from device
     * @param {number} retryCount - Internal retry counter for screen change detection
     */
    async captureScreenshot(retryCount = 0) {
        const MAX_RETRIES = 3;
        console.log('[FlowRecorder] Capturing screenshot...' + (retryCount > 0 ? ` (retry ${retryCount}/${MAX_RETRIES})` : ''));

        // Ensure device is unlocked before capturing
        await this.ensureDeviceUnlocked();

        // Show progress
        this.showStitchProgress('📸 Capturing screenshot with UI elements...');

        try {
            const response = await fetch(`${this.apiBase}/adb/screenshot`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: this.deviceId, quick: false })
            });

            if (!response.ok) {
                throw new Error('Failed to capture screenshot');
            }

            this.updateStitchProgress('🔍 Extracting UI elements...');

            const data = await response.json();

            // Check if screen changed during capture - retry if so
            if (data.screen_changed && retryCount < MAX_RETRIES) {
                console.warn(`[FlowRecorder] Screen changed during capture, retry ${retryCount + 1}/${MAX_RETRIES}`);
                this.hideStitchProgress();
                // Wait briefly for screen to stabilize, then retry
                await new Promise(resolve => setTimeout(resolve, 400));
                return this.captureScreenshot(retryCount + 1);
            }

            if (data.screen_changed) {
                console.error('[FlowRecorder] Screen still changing after max retries, proceeding with last capture');
            }

            // Store screenshot data
            this.currentScreenshot = data.screenshot; // Base64 image
            this.screenshotMetadata = {
                elements: data.elements || [],
                timestamp: data.timestamp,
                width: null,
                height: null,
                quick: data.quick || false,
                current_activity: data.current_activity || null
            };

            // Store current activity for sensor/step creation
            // This is the ACTUAL activity from the device at capture time
            this.currentScreenActivity = data.current_activity
                ? `${data.current_activity.package}/${data.current_activity.activity}`
                : null;

            // Load image to get dimensions immediately
            await this.loadImageDimensions();

            console.log('[FlowRecorder] Screenshot captured:', this.screenshotMetadata);

            // Hide progress
            this.hideStitchProgress();

            return data;
        } catch (error) {
            // Hide progress on error
            this.hideStitchProgress();
            throw error;
        }
    }

    /**
     * Capture quick screenshot (no UI elements extraction)
     * Used for initial preview to improve responsiveness
     */
    async captureQuickScreenshot() {
        console.log('[FlowRecorder] Capturing quick screenshot (no UI elements)...');

        const response = await fetch(`${this.apiBase}/adb/screenshot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: this.deviceId, quick: true })
        });

        if (!response.ok) {
            throw new Error('Failed to capture quick screenshot');
        }

        const data = await response.json();

        // Store screenshot data (no elements in quick mode)
        this.currentScreenshot = data.screenshot; // Base64 image
        this.screenshotMetadata = {
            elements: [],  // Empty in quick mode
            timestamp: data.timestamp,
            width: null,
            height: null,
            quick: true
        };

        // Load image to get dimensions immediately
        await this.loadImageDimensions();

        console.log('[FlowRecorder] Quick screenshot captured (no UI elements)');

        return data;
    }

    /**
     * Load image dimensions from current screenshot
     */
    async loadImageDimensions() {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
                this.screenshotMetadata.width = img.naturalWidth;
                this.screenshotMetadata.height = img.naturalHeight;
                console.log(`[FlowRecorder] Image dimensions loaded: ${img.naturalWidth}x${img.naturalHeight}`);
                resolve();
            };
            img.onerror = () => {
                console.error('[FlowRecorder] Failed to load image dimensions');
                reject(new Error('Failed to load image'));
            };
            img.src = `data:image/png;base64,${this.currentScreenshot}`;
        });
    }

    /**
     * Handle tap on screenshot
     * @param {number} screenX - X coordinate on screenshot element
     * @param {number} screenY - Y coordinate on screenshot element
     * @param {HTMLImageElement} imgElement - Screenshot img element
     */
    async handleTap(screenX, screenY, imgElement) {
        console.log(`[FlowRecorder] Tap detected at screen (${screenX}, ${screenY})`);

        // Ensure image dimensions are captured
        this.ensureImageDimensions(imgElement);

        // Map screenshot coordinates to device coordinates
        const deviceCoords = this.mapCoordinates(screenX, screenY, imgElement);
        console.log(`[FlowRecorder] Mapped to device (${deviceCoords.x}, ${deviceCoords.y})`);

        // Phase 8: Find tapped UI element for state validation
        const tappedElement = this.findElementAtCoordinates(deviceCoords.x, deviceCoords.y);

        // Phase 9: Capture screen BEFORE action for navigation learning
        const beforeScreen = await this.getCurrentScreen();

        // Show tap indicator
        this.showTapIndicator(screenX, screenY);

        // Execute tap if in execute mode
        if (this.recordMode === 'execute') {
            await this.executeTap(deviceCoords.x, deviceCoords.y);
        }

        // Phase 8: Get current activity for state validation
        const currentActivity = await this.getCurrentActivity();

        // Add tap step to flow with state validation data
        const step = {
            step_type: 'tap',
            x: deviceCoords.x,
            y: deviceCoords.y,
            description: tappedElement ?
                `Tap "${tappedElement.text || tappedElement.class}"` :
                `Tap at (${deviceCoords.x}, ${deviceCoords.y})`
        };

        // Add state validation fields
        if (tappedElement) {
            step.expected_ui_elements = [this.extractElementInfo(tappedElement)];
            step.ui_elements_required = 1;
        }
        if (currentActivity) {
            step.expected_activity = currentActivity;
        }
        step.validate_state = true; // Enable state validation by default
        step.recovery_action = 'force_restart_app';
        step.state_match_threshold = 0.80;

        await this.addStep(step);

        // Capture new screenshot after tap
        if (this.recordMode === 'execute') {
            await this.wait(500); // Wait for UI to update
            await this.captureScreenshot();

            // Phase 9: Capture screen AFTER action and report transition
            const afterScreen = await this.getCurrentScreen();
            if (beforeScreen && afterScreen) {
                await this.reportScreenTransition(beforeScreen, afterScreen, {
                    action_type: 'tap',
                    x: deviceCoords.x,
                    y: deviceCoords.y,
                    element_resource_id: tappedElement?.resource_id || null,
                    element_text: tappedElement?.text || null,
                    description: step.description
                });
            }
        }

        return deviceCoords;
    }

    /**
     * Ensure screenshot metadata has image dimensions
     */
    ensureImageDimensions(imgElement) {
        if (!this.screenshotMetadata.width || !this.screenshotMetadata.height) {
            // Extract natural dimensions from loaded image
            this.screenshotMetadata.width = imgElement.naturalWidth;
            this.screenshotMetadata.height = imgElement.naturalHeight;
            console.log(`[FlowRecorder] Image dimensions: ${this.screenshotMetadata.width}x${this.screenshotMetadata.height}`);
        }
    }

    /**
     * Map screenshot coordinates to device coordinates
     */
    mapCoordinates(screenX, screenY, imgElement) {
        const rect = imgElement.getBoundingClientRect();
        const scaleX = this.screenshotMetadata.width / rect.width;
        const scaleY = this.screenshotMetadata.height / rect.height;

        return {
            x: Math.round(screenX * scaleX),
            y: Math.round(screenY * scaleY)
        };
    }

    /**
     * Execute tap on device
     */
    async executeTap(x, y) {
        console.log(`[FlowRecorder] Executing tap at (${x}, ${y})`);

        const response = await fetch(`${this.apiBase}/adb/tap`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: this.deviceId,
                x: x,
                y: y
            })
        });

        if (!response.ok) {
            throw new Error('Failed to execute tap');
        }

        return await response.json();
    }

    /**
     * Show visual tap indicator on screenshot
     */
    showTapIndicator(x, y) {
        const container = document.getElementById('screenshotContainer');
        const indicator = document.createElement('div');

        indicator.style.cssText = `
            position: absolute;
            left: ${x}px;
            top: ${y}px;
            width: 40px;
            height: 40px;
            margin-left: -20px;
            margin-top: -20px;
            border: 3px solid #3b82f6;
            border-radius: 50%;
            pointer-events: none;
            animation: tapPulse 0.6s ease-out;
        `;

        container.appendChild(indicator);

        // Remove after animation
        setTimeout(() => indicator.remove(), 600);
    }

    /**
     * Type text on device
     * @param {string} text - Text to type
     */
    async typeText(text) {
        console.log(`[FlowRecorder] Typing text: ${text}`);

        const response = await fetch(`${this.apiBase}/adb/text`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: this.deviceId,
                text: text
            })
        });

        if (!response.ok) {
            throw new Error('Failed to type text');
        }

        await this.addStep({
            step_type: 'text',
            text: text,
            description: `Type: "${text}"`
        });

        await this.wait(300);
        await this.captureScreenshot();

        showToast(`Typed: ${text}`, 'info', 1000);
    }

    /**
     * Navigate back on device
     */
    async goBack() {
        console.log('[FlowRecorder] Going back...');

        // Phase 9: Capture screen BEFORE action
        const beforeScreen = await this.getCurrentScreen();

        const response = await fetch(`${this.apiBase}/adb/back`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: this.deviceId })
        });

        if (!response.ok) {
            throw new Error('Failed to go back');
        }

        await this.addStep({
            step_type: 'go_back',
            description: 'Press back button'
        });

        await this.wait(300);
        await this.captureScreenshot();

        // Phase 9: Report transition if screen changed
        const afterScreen = await this.getCurrentScreen();
        if (beforeScreen && afterScreen) {
            await this.reportScreenTransition(beforeScreen, afterScreen, {
                action_type: 'go_back',
                keycode: 'KEYCODE_BACK',
                description: 'Press back button'
            });
        }

        showToast('Back', 'info', 1000);
    }

    /**
     * Navigate to home on device
     */
    async goHome() {
        console.log('[FlowRecorder] Going home...');

        const response = await fetch(`${this.apiBase}/adb/home`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: this.deviceId })
        });

        if (!response.ok) {
            throw new Error('Failed to go home');
        }

        await this.addStep({
            step_type: 'go_home',
            description: 'Press home button'
        });

        await this.wait(300);
        await this.captureScreenshot();

        showToast('Home', 'info', 1000);
    }

    /**
     * Perform swipe gesture
     * @param {string} direction - 'up', 'down', 'left', 'right'
     */
    async swipe(direction) {
        console.log(`[FlowRecorder] Swiping ${direction}...`);

        // Phase 9: Capture screen BEFORE action
        this._beforeSwipeScreen = await this.getCurrentScreen();

        // Ensure dimensions are available
        if (!this.screenshotMetadata.width || !this.screenshotMetadata.height) {
            console.warn('[FlowRecorder] Screenshot dimensions not available, using defaults');
            this.screenshotMetadata.width = 1080;
            this.screenshotMetadata.height = 1920;
        }

        // Calculate swipe coordinates based on device dimensions
        const width = this.screenshotMetadata.width;
        const height = this.screenshotMetadata.height;
        const centerX = Math.round(width / 2);
        const centerY = Math.round(height / 2);
        const margin = Math.round(width * 0.1); // 10% margin

        let startX, startY, endX, endY;

        switch(direction) {
            case 'up':
                startX = centerX;
                startY = height - margin;
                endX = centerX;
                endY = margin;
                break;
            case 'down':
                startX = centerX;
                startY = margin;
                endX = centerX;
                endY = height - margin;
                break;
            case 'left':
                startX = width - margin;
                startY = centerY;
                endX = margin;
                endY = centerY;
                break;
            case 'right':
                startX = margin;
                startY = centerY;
                endX = width - margin;
                endY = centerY;
                break;
        }

        const response = await fetch(`${this.apiBase}/adb/swipe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: this.deviceId,
                x1: startX,
                y1: startY,
                x2: endX,
                y2: endY,
                duration: 300
            })
        });

        if (!response.ok) {
            throw new Error('Failed to swipe');
        }

        await this.addStep({
            step_type: 'swipe',
            start_x: startX,
            start_y: startY,
            end_x: endX,
            end_y: endY,
            duration: 300,
            description: `Swipe ${direction}`
        });

        await this.wait(300);
        await this.captureScreenshot();

        // Phase 9: Report transition if screen changed
        const afterScreen = await this.getCurrentScreen();
        if (this._beforeSwipeScreen && afterScreen) {
            await this.reportScreenTransition(this._beforeSwipeScreen, afterScreen, {
                action_type: 'swipe',
                start_x: startX,
                start_y: startY,
                end_x: endX,
                end_y: endY,
                swipe_direction: direction,
                description: `Swipe ${direction}`
            });
        }
        this._beforeSwipeScreen = null;

        showToast(`Swipe ${direction}`, 'info', 1000);
    }

    /**
     * Perform pull-to-refresh gesture on the Android app
     * More specific than swipe('down') - uses optimal coordinates for refresh
     */
    async pullRefresh() {
        console.log('[FlowRecorder] Sending pull-to-refresh...');

        // Ensure dimensions are available
        if (!this.screenshotMetadata.width || !this.screenshotMetadata.height) {
            this.screenshotMetadata.width = 1080;
            this.screenshotMetadata.height = 1920;
        }

        const width = this.screenshotMetadata.width;
        const height = this.screenshotMetadata.height;

        // Pull-to-refresh: start near top (15%), drag to middle (55%)
        // This is a shorter swipe than full swipe('down') and more natural
        const startX = Math.round(width / 2);
        const startY = Math.round(height * 0.15);
        const endX = startX;
        const endY = Math.round(height * 0.55);
        const duration = 350; // Slightly slower for refresh to register

        const response = await fetch(`${this.apiBase}/adb/swipe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: this.deviceId,
                x1: startX,
                y1: startY,
                x2: endX,
                y2: endY,
                duration: duration
            })
        });

        if (!response.ok) {
            throw new Error('Failed to send pull-to-refresh');
        }

        await this.addStep({
            step_type: 'pull_refresh',
            description: 'Pull-to-refresh app content'
        });

        showToast('Pull-to-refresh sent', 'info', 1000);
    }

    /**
     * Restart the current app (force stop and relaunch)
     * Useful when pull-to-refresh doesn't work
     */
    async restartApp() {
        if (!this.appPackage) {
            throw new Error('No app package set');
        }

        console.log(`[FlowRecorder] Restarting app ${this.appPackage}...`);

        // Force stop the app
        const stopResponse = await fetch(`${this.apiBase}/adb/stop-app`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: this.deviceId,
                package: this.appPackage
            })
        });

        if (!stopResponse.ok) {
            throw new Error('Failed to stop app');
        }

        // Wait a moment for the stop to complete
        await this.wait(500);

        // Relaunch the app
        const launchResponse = await fetch(`${this.apiBase}/adb/launch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: this.deviceId,
                package: this.appPackage
            })
        });

        if (!launchResponse.ok) {
            throw new Error('Failed to launch app');
        }

        await this.addStep({
            step_type: 'restart_app',
            package: this.appPackage,
            description: `Restart ${this.appPackage}`
        });

        showToast(`Restarted ${this.appPackage}`, 'success', 1500);
    }

    /**
     * Refresh current screenshot
     * @param {boolean} addStep - Whether to add refresh as a flow step (default: false)
     */
    async refresh(addStep = false) {
        console.log('[FlowRecorder] Refreshing screenshot...');
        await this.captureScreenshot();

        if (addStep) {
            await this.addStep({
                step_type: 'wait',
                duration: 500,
                description: 'Refresh screen (wait for UI update)'
            });
        }

        showToast('Screenshot refreshed', 'info', 1000);
    }

    /**
     * Capture stitched screenshot (2-capture bookend - stable version)
     */
    async stitchCapture() {
        console.log('[FlowRecorder] Starting stitch capture with new modular stitcher...');

        // Show progress modal
        this.showStitchProgress('Initializing smart stitcher...');

        try {
            // Show progress updates (estimated timing)
            setTimeout(() => this.updateStitchProgress('📸 Scrolling to top...'), 500);
            setTimeout(() => this.updateStitchProgress('📸 Capturing top screenshot...'), 1500);
            setTimeout(() => this.updateStitchProgress('⬇️ Scrolling to bottom...'), 3000);
            setTimeout(() => this.updateStitchProgress('📸 Capturing bottom screenshot...'), 5000);
            setTimeout(() => this.updateStitchProgress('🔍 Analyzing overlap...'), 6500);
            setTimeout(() => this.updateStitchProgress('🧩 Stitching images...'), 8000);

            // Use new modular stitcher with BOOKEND strategy
            // Smart algorithm: Captures top & bottom first, then fills middle if needed
            const response = await fetch(`${this.apiBase}/adb/screenshot/stitch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    device_id: this.deviceId,
                    stitcher_version: 'v2',
                    max_scrolls: 20,       // Maximum scrolls for long pages
                    scroll_ratio: 0.40,    // Scroll 40% of screen height (optimized)
                    overlap_ratio: 0.30,   // 30% overlap for reliable matching
                    debug: false
                })
            });

            if (!response.ok) {
                throw new Error('Failed to capture stitched screenshot');
            }

            const data = await response.json();

            // Store stitched screenshot data
            this.currentScreenshot = data.screenshot; // Base64 stitched image
            this.screenshotMetadata = {
                elements: data.elements || [],
                timestamp: data.timestamp,
                width: null,
                height: null,
                stitched: true,
                metadata: data.metadata  // Store stitch metadata
            };

            // Load image to get dimensions
            await this.loadImageDimensions();

            // Count clickable vs non-clickable elements
            const elements = this.screenshotMetadata.elements;
            const clickableCount = elements.filter(e => e.clickable === true).length;
            const nonClickableCount = elements.length - clickableCount;

            console.log('[FlowRecorder] Stitched screenshot captured:', this.screenshotMetadata);
            console.log(`[FlowRecorder] Elements: ${elements.length} total (${clickableCount} clickable, ${nonClickableCount} non-clickable)`);
            console.log('[FlowRecorder] Stitch metadata:', data.metadata);

            // Add stitch capture step to flow
            const meta = data.metadata || {};
            await this.addStep({
                step_type: 'stitch_capture',
                scroll_count: meta.scroll_count || 0,
                capture_count: meta.capture_count || 0,
                strategy: meta.strategy || 'unknown',
                description: `Capture stitched screenshot (${meta.scroll_count || 0} scrolls, ${meta.capture_count || 0} captures)`
            });

            this.hideStitchProgress();
            showToast(`Stitched screenshot captured! (${meta.scroll_count || 0} scrolls, ${meta.capture_count || 0} captures)`, 'success', 2000);

        } catch (error) {
            console.error('[FlowRecorder] Stitch capture failed:', error);
            this.hideStitchProgress();
            showToast(`Stitch capture failed: ${error.message}`, 'error', 3000);
            throw error;
        }
    }

    /**
     * Show stitch progress modal
     */
    showStitchProgress(message) {
        // Remove existing progress modal if any
        this.hideStitchProgress();

        // Create overlay
        const overlay = document.createElement('div');
        overlay.id = 'stitchProgressOverlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
        `;

        // Create progress modal
        const modal = document.createElement('div');
        modal.style.cssText = `
            background: white;
            padding: 30px 40px;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
            max-width: 400px;
            text-align: center;
        `;

        // Add spinner
        const spinner = document.createElement('div');
        spinner.className = 'stitch-spinner';
        spinner.style.cssText = `
            width: 50px;
            height: 50px;
            border: 4px solid #e5e7eb;
            border-top-color: #3b82f6;
            border-radius: 50%;
            margin: 0 auto 20px;
            animation: spin 1s linear infinite;
        `;

        // Add message text
        const messageEl = document.createElement('div');
        messageEl.id = 'stitchProgressMessage';
        messageEl.style.cssText = `
            font-size: 16px;
            color: #1f2937;
            font-weight: 500;
        `;
        messageEl.textContent = message;

        modal.appendChild(spinner);
        modal.appendChild(messageEl);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        console.log('[FlowRecorder] Progress modal shown:', message);
    }

    /**
     * Update stitch progress message
     */
    updateStitchProgress(message) {
        const messageEl = document.getElementById('stitchProgressMessage');
        if (messageEl) {
            messageEl.textContent = message;
            console.log('[FlowRecorder] Progress updated:', message);
        }
    }

    /**
     * Hide stitch progress modal
     */
    hideStitchProgress() {
        const overlay = document.getElementById('stitchProgressOverlay');
        if (overlay) {
            overlay.remove();
            console.log('[FlowRecorder] Progress modal hidden');
        }
    }

    /**
     * Insert a step at a specific index in the flow
     * Used when returning from step 4 to add missing navigation steps
     * @param {Object} step - The step to insert
     * @param {number} index - The index to insert at
     */
    async insertStepAt(step, index) {
        // Capture screen info same as addStep
        const skipScreenCapture = ['launch_app', 'go_home', 'restart_app'];
        if (!skipScreenCapture.includes(step.step_type)) {
            try {
                const screenInfo = await this.getCurrentScreen();
                if (screenInfo?.activity) {
                    step.screen_activity = screenInfo.activity.activity || null;
                    step.screen_package = screenInfo.activity.package || null;
                }
            } catch (e) {
                console.warn('[FlowRecorder] Failed to capture screen info:', e);
            }
        }

        // Add navigation screen ID if available
        if (this.currentScreenId) {
            step.expected_screen_id = this.currentScreenId;
        }
        if (this.currentScreenSignature) {
            step.screen_signature = this.currentScreenSignature;
        }

        // Insert at the specified index
        if (index >= 0 && index <= this.steps.length) {
            this.steps.splice(index, 0, step);
            console.log(`[FlowRecorder] Inserted step at index ${index}:`, step);
        } else {
            // Fall back to append if index is out of bounds
            this.steps.push(step);
            console.log(`[FlowRecorder] Appended step (index ${index} out of bounds):`, step);
        }

        // Trigger step inserted event for UI update
        window.dispatchEvent(new CustomEvent('flowStepInserted', {
            detail: {
                step: step,
                index: index
            }
        }));
    }

    /**
     * Set insert mode - next steps will be inserted at the given index
     * @param {number|null} index - Index to insert at, or null to disable insert mode
     */
    setInsertMode(index) {
        this.insertAtIndex = index;
        console.log(`[FlowRecorder] Insert mode ${index !== null ? 'enabled at index ' + index : 'disabled'}`);
    }

    /**
     * Add a step to the flow
     * Automatically captures screen activity info for Phase 1 screen awareness
     * Also includes navigation screen ID if available from the wizard
     * If insert mode is active, inserts at the specified index instead of appending
     */
    async addStep(step) {
        // Phase 1 Screen Awareness: Capture screen info before adding step
        // Skip for certain step types that don't need screen context
        const skipScreenCapture = ['launch_app', 'go_home', 'restart_app'];
        if (!skipScreenCapture.includes(step.step_type)) {
            // Only capture if not already provided (allows capturing BEFORE action)
            if (!step.screen_activity || !step.screen_package) {
                try {
                    const screenInfo = await this.getCurrentScreen();
                    if (screenInfo?.activity) {
                        if (!step.screen_activity) step.screen_activity = screenInfo.activity.activity || null;
                        if (!step.screen_package) step.screen_package = screenInfo.activity.package || null;
                        console.log(`[FlowRecorder] Captured screen: ${step.screen_activity} (${step.screen_package})`);
                    }
                } catch (e) {
                    console.warn('[FlowRecorder] Failed to capture screen info:', e);
                }
            }
        }

        // Add navigation screen ID if available from wizard
        // This links the step to the navigation graph for smarter flow execution
        if (this.currentScreenId) {
            step.expected_screen_id = this.currentScreenId;
            console.log(`[FlowRecorder] Added navigation screen ID: ${this.currentScreenId}`);
        }
        if (this.currentScreenSignature) {
            step.screen_signature = this.currentScreenSignature;
            console.log(`[FlowRecorder] Added screen signature: ${this.currentScreenSignature}`);
        }

        // Check if we're in insert mode
        if (this.insertAtIndex !== undefined && this.insertAtIndex !== null) {
            // Insert at the specified index
            this.steps.splice(this.insertAtIndex, 0, step);
            console.log(`[FlowRecorder] Inserted step at index ${this.insertAtIndex}:`, step);

            // Trigger step inserted event for UI update
            window.dispatchEvent(new CustomEvent('flowStepInserted', {
                detail: {
                    step: step,
                    index: this.insertAtIndex
                }
            }));

            // Increment insert index for next step
            this.insertAtIndex++;
        } else {
            // Normal append mode
            this.steps.push(step);
            console.log(`[FlowRecorder] Added step ${this.steps.length}:`, step);

            // Trigger step added event for UI update
            window.dispatchEvent(new CustomEvent('flowStepAdded', {
                detail: {
                    step: step,
                    index: this.steps.length - 1
                }
            }));

            // Dispatch tutorial event for wizard step recording
            window.dispatchEvent(new CustomEvent('tutorial:wizard-step-recorded', {
                detail: { step: step }
            }));
        }
    }

    /**
     * Remove a step from the flow
     */
    removeStep(index) {
        if (index >= 0 && index < this.steps.length) {
            const removed = this.steps.splice(index, 1)[0];
            console.log(`[FlowRecorder] Removed step ${index}:`, removed);

            window.dispatchEvent(new CustomEvent('flowStepRemoved', {
                detail: { index: index }
            }));
        }
    }

    /**
     * Move a step from one position to another
     * @param {number} fromIndex - Current index of the step
     * @param {number} toIndex - Target index to move to
     */
    moveStep(fromIndex, toIndex) {
        if (fromIndex < 0 || fromIndex >= this.steps.length) {
            console.warn(`[FlowRecorder] Invalid fromIndex: ${fromIndex}`);
            return;
        }
        if (toIndex < 0 || toIndex >= this.steps.length) {
            console.warn(`[FlowRecorder] Invalid toIndex: ${toIndex}`);
            return;
        }
        if (fromIndex === toIndex) {
            return; // No change needed
        }

        // Remove step from original position
        const [step] = this.steps.splice(fromIndex, 1);
        // Insert at new position
        this.steps.splice(toIndex, 0, step);

        console.log(`[FlowRecorder] Moved step from ${fromIndex} to ${toIndex}:`, step.description);

        window.dispatchEvent(new CustomEvent('flowStepMoved', {
            detail: { fromIndex, toIndex, step }
        }));
    }

    /**
     * Clear all steps
     */
    clearSteps() {
        const count = this.steps.length;
        this.steps = [];
        console.log(`[FlowRecorder] Cleared ${count} steps`);

        window.dispatchEvent(new CustomEvent('flowStepsCleared', {
            detail: { count: count }
        }));
    }

    /**
     * Get all recorded steps
     */
    getSteps() {
        return this.steps;
    }

    /**
     * Load existing steps (for edit mode)
     * Converts action format (x1/y1/x2/y2) to flow format (start_x/start_y/end_x/end_y) if needed
     * @param {Array} steps - Array of step objects to load
     * @param {boolean} skipLaunchStep - If true, skip any launch_app steps (already on screen)
     */
    loadSteps(steps, skipLaunchStep = false) {
        if (!Array.isArray(steps)) {
            console.warn('[FlowRecorder] loadSteps: steps must be an array');
            return;
        }

        this.steps = steps.map(step => {
            const normalized = { ...step };

            // Convert action_type to step_type if needed
            if (step.action_type && !step.step_type) {
                normalized.step_type = step.action_type;
            }

            // Convert action swipe format (x1/y1/x2/y2) to flow format (start_x/start_y/end_x/end_y)
            if (normalized.step_type === 'swipe' || normalized.action_type === 'swipe') {
                if (step.x1 !== undefined && step.start_x === undefined) {
                    normalized.start_x = step.x1;
                    normalized.start_y = step.y1;
                    normalized.end_x = step.x2;
                    normalized.end_y = step.y2;
                }
            }

            // Mark as pre-existing for UI differentiation
            normalized._preExisting = true;

            return normalized;
        });

        // Optionally filter out launch steps if already on the app
        if (skipLaunchStep) {
            this.steps = this.steps.filter(s => s.step_type !== 'launch_app');
        }

        console.log(`[FlowRecorder] Loaded ${this.steps.length} existing steps`);
    }

    /**
     * Clear all steps
     */
    clearSteps() {
        this.steps = [];
        console.log('[FlowRecorder] Steps cleared');
    }

    /**
     * Get count of pre-existing steps (loaded in edit mode)
     */
    getPreExistingCount() {
        return this.steps.filter(s => s._preExisting).length;
    }

    /**
     * Wait for specified duration
     */
    wait(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Get current screenshot as data URL
     */
    getScreenshotDataUrl() {
        return `data:image/png;base64,${this.currentScreenshot}`;
    }

    /**
     * Phase 8: Find UI element at given coordinates
     * @param {number} x - Device X coordinate
     * @param {number} y - Device Y coordinate
     * @returns {Object|null} - UI element or null if not found
     */
    findElementAtCoordinates(x, y) {
        if (!this.screenshotMetadata || !this.screenshotMetadata.elements) {
            return null;
        }

        // Find element whose bounds contain the coordinates
        // Backend returns bounds as {x, y, width, height}
        for (const element of this.screenshotMetadata.elements) {
            if (element.bounds) {
                const { x: left, y: top, width, height } = element.bounds;
                const right = left + width;
                const bottom = top + height;
                if (x >= left && x <= right && y >= top && y <= bottom) {
                    console.log(`[FlowRecorder] Found element at (${x}, ${y}):`, element);
                    return element;
                }
            }
        }

        console.log(`[FlowRecorder] No element found at (${x}, ${y})`);
        return null;
    }

    /**
     * Phase 8: Get current activity from device
     * @returns {Promise<string|null>} - Current activity name or null
     */
    async getCurrentActivity() {
        try {
            const response = await fetch(`${this.apiBase}/adb/activity/${encodeURIComponent(this.deviceId)}`);
            if (!response.ok) {
                console.warn('[FlowRecorder] Failed to get current activity');
                return null;
            }
            const data = await response.json();
            return data.activity || null;
        } catch (error) {
            console.error('[FlowRecorder] Error getting activity:', error);
            return null;
        }
    }

    /**
     * Phase 1 Screen Awareness: Get current screen info (activity with package breakdown)
     * @returns {Promise<Object|null>} - {activity: {package, activity, full_name}} or null
     */
    async getCurrentScreen() {
        try {
            const response = await fetch(`${this.apiBase}/adb/screen/current/${encodeURIComponent(this.deviceId)}`);
            if (!response.ok) {
                console.warn('[FlowRecorder] Failed to get current screen info');
                return null;
            }
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('[FlowRecorder] Error getting screen info:', error);
            return null;
        }
    }

    /**
     * Phase 8: Extract key info from UI element for state validation
     * @param {Object} element - UI element
     * @returns {Object} - Extracted element info
     */
    extractElementInfo(element) {
        const info = {};

        // Only include fields that are useful for matching
        if (element.text && element.text.trim()) {
            info.text = element.text.trim();
        }
        if (element.class) {
            info.class = element.class;
        }
        if (element.resource_id) {
            info.resource_id = element.resource_id;
        }

        return info;
    }

    /**
     * Phase 9 Navigation Learning: Report a screen transition to the backend
     * Called when an action causes a screen change
     *
     * @param {Object} beforeScreen - Screen info before action
     * @param {Object} afterScreen - Screen info after action
     * @param {Object} action - The action that caused the transition
     */
    async reportScreenTransition(beforeScreen, afterScreen, action) {
        if (!beforeScreen?.activity || !afterScreen?.activity) {
            console.warn('[FlowRecorder] Cannot report transition: missing screen info');
            return;
        }

        // Check if screen actually changed
        if (beforeScreen.activity.activity === afterScreen.activity.activity &&
            beforeScreen.activity.package === afterScreen.activity.package) {
            console.log('[FlowRecorder] No screen change detected, skipping transition report');
            return;
        }

        const package_name = beforeScreen.activity.package || this.appPackage;

        try {
            const payload = {
                before_activity: beforeScreen.activity.activity,
                before_package: beforeScreen.activity.package,
                before_ui_elements: this.screenshotMetadata?.elements || [],
                after_activity: afterScreen.activity.activity,
                after_package: afterScreen.activity.package,
                after_ui_elements: [],  // Will be populated after next screenshot
                action: action
            };

            const response = await fetch(`${this.apiBase}/navigation/${encodeURIComponent(package_name)}/learn-transition`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                console.log(`[FlowRecorder] Learned transition: ${beforeScreen.activity.activity} -> ${afterScreen.activity.activity}`);
            } else {
                console.warn('[FlowRecorder] Failed to report transition:', await response.text());
            }
        } catch (error) {
            console.error('[FlowRecorder] Error reporting transition:', error);
        }
    }
}

// Add animations to document if not already present
if (!document.getElementById('flow-recorder-animations')) {
    const style = document.createElement('style');
    style.id = 'flow-recorder-animations';
    style.textContent = `
        @keyframes tapPulse {
            0% {
                transform: scale(0.5);
                opacity: 1;
            }
            100% {
                transform: scale(2);
                opacity: 0;
            }
        }
        @keyframes spin {
            0% {
                transform: rotate(0deg);
            }
            100% {
                transform: rotate(360deg);
            }
        }
    `;
    document.head.appendChild(style);
}

// Export for module use
export default FlowRecorder;

// Export for global access (dual export pattern)
window.FlowRecorder = FlowRecorder;
