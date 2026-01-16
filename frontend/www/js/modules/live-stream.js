/**
 * Visual Mapper - Live Stream Module
 * Version: 0.0.36 (improved smart refresh - better hash, more debug logging)
 *
 * WebSocket-based live screenshot streaming with UI element overlays.
 * Supports two modes:
 * - websocket: Base64 JSON frames (original)
 * - mjpeg: Binary JPEG frames (~30% less bandwidth)
 *
 * Quality settings:
 * - high: Native resolution (~5 FPS)
 * - medium: 720p (~12 FPS)
 * - low: 480p (~18 FPS)
 * - fast: 360p (~25 FPS)
 * - ultrafast: 240p (~30 FPS) - Optimized for WiFi
 *
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Connection state tracking
 * - Container element filtering
 * - Backend benchmark support via stream_manager
 * - Enhanced quality indicators
 * - FPS performance hints (Phase 3)
 */

class LiveStream {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.websocket = null;
        this.deviceId = null;
        this.isStreaming = false;

        // Streaming mode: 'websocket' (base64 JSON) or 'mjpeg' (binary)
        this.streamMode = 'websocket';
        this.streamQuality = 'fast'; // 'high', 'medium', 'low', 'fast' - default 'fast' for WiFi compatibility

        // Current state
        this.currentImage = null;
        this.elements = [];

        // Device dimensions (native resolution for element scaling)
        this.deviceWidth = 1080;   // Default, updated when elements are set
        this.deviceHeight = 1920;

        // Performance metrics
        this.metrics = {
            frameCount: 0,
            fps: 0,
            latency: 0,
            captureTime: 0,
            lastFrameTime: 0,
            fpsHistory: [],
            bandwidth: 0,          // KB/s
            bytesReceived: 0,
            bandwidthHistory: []
        };

        // Bandwidth tracking
        this._bandwidthStart = 0;
        this._bandwidthBytes = 0;

        // Auto-reconnect settings
        this.autoReconnect = true;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 20; // Increased for WiFi reliability
        this.reconnectDelay = 1000; // Start with 1 second
        this.maxReconnectDelay = 15000; // Max 15 seconds (reduced for faster retry)
        this._reconnectTimer = null;
        this._manualStop = false;

        // Connection state: 'disconnected', 'connecting', 'connected', 'reconnecting'
        this.connectionState = 'disconnected';

        // Callbacks
        this.onFrame = null;
        this.onConnect = null;
        this.onDisconnect = null;
        this.onError = null;
        this.onMetricsUpdate = null;
        this.onConnectionStateChange = null; // New callback for connection state
        this.onScreenChange = null;          // Smart refresh: fires when screen stabilizes after change
        this.onElementsCleared = null;       // Fires immediately when screen change detected (before stabilization)

        // Overlay settings
        this.showOverlays = true;
        this.showTextLabels = true;
        this.hideContainers = true;
        this.hideEmptyElements = true;
        this.hideSmall = true;           // Hide tiny elements (< 20px)
        this.hideDividers = true;        // Hide horizontal line dividers
        this.showClickable = true;       // Show clickable elements
        this.showNonClickable = false;   // Show non-clickable elements
        this.displayMode = 'all';        // 'all', 'hoverOnly', 'topLayer'
        this.hoveredElement = null;      // Currently hovered element (for hoverOnly mode)

        // Element staleness tracking - hide elements when screen content has changed significantly
        this.elementsTimestamp = 0;      // When elements were last fetched
        this.autoHideStaleElements = false; // DISABLED by default - but smartRefreshEnabled handles this
        this.smartRefreshEnabled = true;  // Smart refresh: detect screen changes and fire onScreenChange callback
        this._lastFrameHash = 0;         // Simple hash of last frame for change detection
        this._screenChanged = false;     // True if screen content changed since last element refresh
        this._differentFrameCount = 0;   // Count of consecutive different frames (filters compression noise)
        this._stableFrameCount = 0;      // Count of consecutive same frames (confirms stabilization)
        this._lastScreenChangeCallback = 0;  // Rate limiting for screen change callback
        this._elementsStale = false;     // True when elements should be hidden (screen changed)

        // OPTIMIZATION: Cache filtered elements to avoid re-filtering every frame
        this._filteredElements = [];
        this._lastElementsRef = null;    // Track when elements array changes
        this._filterSettingsHash = '';   // Track when filter settings change

        // Memory management: track current blob URL to prevent leaks
        this._currentBlobUrl = null;

        // Frame dropping: skip stale frames when rendering can't keep up
        this._isProcessingFrame = false;
        this._pendingFrame = null;  // Latest frame waiting to be processed
        this._droppedFrameCount = 0;

        // Pause state tracking for scheduler and sensors
        this._schedulerPaused = false;
        this._sensorsPaused = false;
        this._pausedDeviceId = null;

        // User-configurable pause options (set from dialog before start)
        this._pauseSchedulerOnStart = true;  // Default: pause scheduler
        this._pauseSensorsOnStart = true;    // Default: pause sensors

        // Container classes to filter out (reduce visual clutter)
        // Use Set for O(1) lookup instead of Array.includes() O(n)
        this.containerClasses = new Set([
            // Core Android containers
            'android.view.View',
            'android.view.ViewGroup',
            'android.widget.FrameLayout',
            'android.widget.LinearLayout',
            'android.widget.RelativeLayout',
            'android.widget.TableLayout',
            'android.widget.TableRow',
            'android.widget.GridLayout',
            'android.widget.ScrollView',
            'android.widget.HorizontalScrollView',
            'android.widget.ListView',
            'android.widget.GridView',
            'android.widget.AbsoluteLayout',
            // AndroidX containers
            'androidx.constraintlayout.widget.ConstraintLayout',
            'androidx.recyclerview.widget.RecyclerView',
            'androidx.viewpager.widget.ViewPager',
            'androidx.viewpager2.widget.ViewPager2',
            'androidx.coordinatorlayout.widget.CoordinatorLayout',
            'androidx.drawerlayout.widget.DrawerLayout',
            'androidx.appcompat.widget.LinearLayoutCompat',
            'androidx.cardview.widget.CardView',
            'androidx.core.widget.NestedScrollView',
            'androidx.swiperefreshlayout.widget.SwipeRefreshLayout',
            // Other non-interactive elements
            'android.widget.Space',
            'android.view.ViewStub'
        ]);

        console.log('[LiveStream] Initialized (WebSocket + MJPEG + Auto-reconnect + Container filtering)');
    }

    /**
     * Set connection state and notify listeners
     */
    _setConnectionState(state) {
        const oldState = this.connectionState;
        this.connectionState = state;
        console.log(`[LiveStream] Connection state: ${oldState} -> ${state}`);

        if (this.onConnectionStateChange) {
            this.onConnectionStateChange(state, this.reconnectAttempts);
        }
    }

    /**
     * Get WebSocket URL for device
     * @param {string} deviceId - Device identifier
     * @param {string} mode - 'websocket' or 'mjpeg'
     * @param {string} quality - 'high', 'medium', 'low', 'fast'
     * @returns {string} WebSocket URL
     */
    _getWebSocketUrl(deviceId, mode = 'websocket', quality = 'fast') {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const encodedDeviceId = encodeURIComponent(deviceId);

        // Endpoint based on mode
        let endpoint = 'ws/stream';
        if (mode === 'mjpeg') {
            endpoint = 'ws/stream-mjpeg';
        } else if (mode === 'mjpeg-v2') {
            endpoint = 'ws/stream-mjpeg-v2';
        }

        // Handle Home Assistant ingress
        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);

        // Add quality as query parameter
        const queryParams = `?quality=${quality}`;

        if (ingressMatch) {
            return `${protocol}//${host}${ingressMatch[0]}/${endpoint}/${encodedDeviceId}${queryParams}`;
        }

        return `${protocol}//${host}/api/${endpoint}/${encodedDeviceId}${queryParams}`;
    }

    /**
     * Start streaming from device
     * @param {string} deviceId - Device identifier (host:port)
     * @param {string} mode - 'websocket' (base64) or 'mjpeg' (binary)
     * @param {string} quality - 'high', 'medium', 'low', 'fast'
     */
    async start(deviceId, mode = 'websocket', quality = 'fast') {
        if (this.isStreaming) {
            console.warn('[LiveStream] Already streaming, stopping first');
            await this.stop();
        }

        this._manualStop = false;
        this.deviceId = deviceId;
        this.streamMode = mode;
        this.streamQuality = quality;

        // Pause scheduler and sensor updates to reduce ADB contention
        await this.pauseForStreaming(deviceId);

        this._connect();
    }

    /**
     * Internal connect method (used for initial connect and reconnect)
     */
    _connect() {
        const wsUrl = this._getWebSocketUrl(this.deviceId, this.streamMode, this.streamQuality);

        this._setConnectionState(this.reconnectAttempts > 0 ? 'reconnecting' : 'connecting');
        console.log(`[LiveStream] Connecting to ${wsUrl} (mode: ${this.streamMode}, quality: ${this.streamQuality}, attempt: ${this.reconnectAttempts + 1})`);

        // Reset bandwidth tracking
        this._bandwidthStart = performance.now();
        this._bandwidthBytes = 0;

        try {
            this.websocket = new WebSocket(wsUrl);

            // Enable binary type for MJPEG modes (v1 and v2)
            if (this.streamMode === 'mjpeg' || this.streamMode === 'mjpeg-v2') {
                this.websocket.binaryType = 'arraybuffer';
            }

            this.websocket.onopen = () => {
                console.log(`[LiveStream] Connected (${this.streamMode} mode)`);
                this.isStreaming = true;
                this.reconnectAttempts = 0; // Reset on successful connection
                this.reconnectDelay = 1000; // Reset delay
                this.metrics.frameCount = 0;
                this.metrics.lastFrameTime = performance.now();

                this._setConnectionState('connected');

                if (this.onConnect) {
                    this.onConnect();
                }
            };

            this.websocket.onmessage = (event) => {
                // Track bandwidth
                const dataSize = event.data instanceof ArrayBuffer
                    ? event.data.byteLength
                    : event.data.length;
                this._bandwidthBytes += dataSize;
                this._updateBandwidth();

                // Route to appropriate handler based on data type
                if (event.data instanceof ArrayBuffer) {
                    // Binary MJPEG frame
                    this._handleMjpegFrame(event.data);
                } else {
                    // JSON frame (websocket mode or MJPEG config message)
                    const data = JSON.parse(event.data);
                    if (data.type === 'config') {
                        console.log('[LiveStream] MJPEG config received:', data);
                        // Store native device dimensions for overlay scaling
                        if (data.width && data.height) {
                            this.deviceWidth = data.width;
                            this.deviceHeight = data.height;
                            console.log(`[LiveStream] Device dimensions: ${data.width}x${data.height}`);
                        }
                    } else {
                        this._handleFrame(data);
                    }
                }
            };

            this.websocket.onclose = () => {
                console.log('[LiveStream] Disconnected');
                this.isStreaming = false;
                this.websocket = null;

                if (this.onDisconnect) {
                    this.onDisconnect();
                }

                // Auto-reconnect if not manually stopped
                if (!this._manualStop && this.autoReconnect && this.deviceId) {
                    this._scheduleReconnect();
                } else {
                    this._setConnectionState('disconnected');
                }
            };

            this.websocket.onerror = (error) => {
                console.error('[LiveStream] WebSocket error:', error);

                if (this.onError) {
                    this.onError(error);
                }
            };

        } catch (error) {
            console.error('[LiveStream] Failed to connect:', error);
            this._setConnectionState('disconnected');
            if (this.onError) {
                this.onError(error);
            }
        }
    }

    /**
     * Schedule a reconnection attempt with exponential backoff
     */
    _scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('[LiveStream] Max reconnect attempts reached, giving up');
            this._setConnectionState('disconnected');
            return;
        }

        // Calculate delay with exponential backoff
        const delay = Math.min(
            this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts),
            this.maxReconnectDelay
        );

        console.log(`[LiveStream] Reconnecting in ${Math.round(delay / 1000)}s (attempt ${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
        this._setConnectionState('reconnecting');

        this._reconnectTimer = setTimeout(() => {
            this.reconnectAttempts++;
            this._connect();
        }, delay);
    }

    /**
     * Cancel any pending reconnection
     */
    _cancelReconnect() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
    }

    /**
     * Update bandwidth metrics (called on each message)
     */
    _updateBandwidth() {
        const now = performance.now();
        const elapsed = (now - this._bandwidthStart) / 1000; // seconds

        if (elapsed >= 1.0) {
            // Calculate KB/s
            const kbps = Math.round(this._bandwidthBytes / 1024 / elapsed);

            // Rolling average
            this.metrics.bandwidthHistory.push(kbps);
            if (this.metrics.bandwidthHistory.length > 5) {
                this.metrics.bandwidthHistory.shift();
            }
            this.metrics.bandwidth = Math.round(
                this.metrics.bandwidthHistory.reduce((a, b) => a + b, 0) /
                this.metrics.bandwidthHistory.length
            );
            this.metrics.bytesReceived += this._bandwidthBytes;

            // Reset for next second
            this._bandwidthStart = now;
            this._bandwidthBytes = 0;
        }
    }

    /**
     * Handle binary MJPEG frame
     * Implements frame dropping for slow connections - skips stale frames when rendering can't keep up
     * @param {ArrayBuffer} buffer - Binary frame data
     */
    async _handleMjpegFrame(buffer) {
        // Guard: Ignore frames if streaming was stopped (prevents race condition on quality switch)
        if (!this.isStreaming) {
            return;
        }

        // Frame dropping: if still processing previous frame, queue this one and skip
        if (this._isProcessingFrame) {
            this._pendingFrame = buffer;  // Keep only the latest frame
            this._droppedFrameCount++;
            return;
        }

        // Process this frame
        await this._processFrame(buffer);

        // Check if a newer frame arrived while processing
        while (this._pendingFrame && this.isStreaming) {
            const nextFrame = this._pendingFrame;
            this._pendingFrame = null;
            await this._processFrame(nextFrame);
        }
    }

    /**
     * Process a single MJPEG frame
     * @param {ArrayBuffer} buffer - Binary frame data
     */
    async _processFrame(buffer) {
        this._isProcessingFrame = true;

        const now = performance.now();

        // Parse header (8 bytes: 4 frame_number + 4 capture_time)
        const view = new DataView(buffer);
        const frameNumber = view.getUint32(0, false); // big-endian
        const captureTime = view.getUint32(4, false); // big-endian

        // Extract JPEG data (after 8-byte header)
        const jpegData = buffer.slice(8);

        // Calculate FPS
        const frameDelta = now - this.metrics.lastFrameTime;
        this.metrics.lastFrameTime = now;

        this.metrics.fpsHistory.push(1000 / frameDelta);
        if (this.metrics.fpsHistory.length > 10) {
            this.metrics.fpsHistory.shift();
        }
        this.metrics.fps = Math.round(
            this.metrics.fpsHistory.reduce((a, b) => a + b, 0) / this.metrics.fpsHistory.length
        );

        this.metrics.captureTime = captureTime;
        this.metrics.frameCount = frameNumber;
        // Note: latency can't be calculated for binary frames without timestamp

        // Create blob URL and load image
        try {
            // Clean up previous blob URL to prevent memory leak
            if (this._currentBlobUrl) {
                URL.revokeObjectURL(this._currentBlobUrl);
                this._currentBlobUrl = null;
            }

            const blob = new Blob([jpegData], { type: 'image/jpeg' });
            const blobUrl = URL.createObjectURL(blob);
            this._currentBlobUrl = blobUrl; // Track for cleanup

            const img = new Image();
            await new Promise((resolve, reject) => {
                img.onload = () => {
                    // Don't revoke here - let next frame or stop() handle it
                    // This prevents race conditions if streaming stops mid-load
                    resolve();
                };
                img.onerror = () => {
                    reject(new Error('Failed to load JPEG image'));
                };
                img.src = blobUrl;
            });

            this.currentImage = img;

            // Render frame (no elements from MJPEG stream - fetched on-demand)
            this._renderFrame(img, this.elements);

            // Callback
            if (this.onFrame) {
                this.onFrame({ frame_number: frameNumber, capture_ms: captureTime });
            }

            // Update metrics callback
            if (this.onMetricsUpdate) {
                this.onMetricsUpdate(this.metrics);
            }

        } catch (error) {
            console.error('[LiveStream] Failed to render MJPEG frame:', error);
        } finally {
            this._isProcessingFrame = false;
        }
    }

    /**
     * Stop streaming
     * Removes event handlers before closing to prevent stale frame processing during quality switch
     */
    async stop() {
        console.log('[LiveStream] Stopping stream');
        this._manualStop = true;
        this.isStreaming = false;  // Set immediately to reject any pending frames
        this._cancelReconnect();
        this.reconnectAttempts = 0;

        if (this.websocket) {
            // Remove event handlers BEFORE closing to prevent stale frame processing
            this.websocket.onmessage = null;
            this.websocket.onerror = null;
            this.websocket.onclose = null;
            this.websocket.close();
            this.websocket = null;
        }

        // Clean up blob URL to prevent memory leak
        if (this._currentBlobUrl) {
            URL.revokeObjectURL(this._currentBlobUrl);
            this._currentBlobUrl = null;
        }

        // Clean up frame dropping state
        this._isProcessingFrame = false;
        this._pendingFrame = null;
        if (this._droppedFrameCount > 0) {
            console.log(`[LiveStream] Dropped ${this._droppedFrameCount} frames during session (slow connection)`);
        }
        this._droppedFrameCount = 0;

        // Release image reference
        if (this.currentImage) {
            this.currentImage.src = '';  // Release image data
            this.currentImage = null;
        }

        this.deviceId = null;
        this._setConnectionState('disconnected');

        // Resume scheduler and sensor updates
        await this.resumeAfterStreaming();
    }

    /**
     * Pause scheduler and sensor updates to reduce ADB contention during streaming
     * @param {string} deviceId - Device identifier
     */
    async pauseForStreaming(deviceId) {
        const apiBase = window.API_BASE || '/api';

        // Pause flow scheduler (if enabled)
        if (this._pauseSchedulerOnStart) {
            try {
                const response = await fetch(`${apiBase}/scheduler/pause`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.ok) {
                    const data = await response.json();
                    if (data.success) {
                        console.log('[LiveStream] Paused flow scheduler for streaming');
                        this._schedulerPaused = true;
                    } else {
                        console.warn('[LiveStream] Scheduler pause returned:', data);
                    }
                } else {
                    console.warn('[LiveStream] Scheduler pause failed:', response.status, response.statusText);
                }
            } catch (e) {
                console.warn('[LiveStream] Could not pause scheduler:', e);
            }
        } else {
            console.log('[LiveStream] Scheduler pause disabled by user');
        }

        // Pause sensor updates for this device (if enabled)
        if (this._pauseSensorsOnStart && deviceId) {
            try {
                const response = await fetch(`${apiBase}/sensors/pause/${encodeURIComponent(deviceId)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.ok) {
                    const data = await response.json();
                    if (data.success && data.paused) {
                        console.log(`[LiveStream] Paused sensor updates for ${deviceId}`);
                        this._sensorsPaused = true;
                        this._pausedDeviceId = deviceId;
                    } else if (data.message && data.message.includes('No sensor update loop')) {
                        // This is fine - no active sensor polling to pause
                        console.log(`[LiveStream] No active sensor polling for ${deviceId} (OK)`);
                    } else {
                        console.warn('[LiveStream] Sensor pause returned:', data);
                    }
                } else {
                    console.warn('[LiveStream] Sensor pause failed:', response.status, response.statusText);
                }
            } catch (e) {
                console.warn('[LiveStream] Could not pause sensor updates:', e);
            }
        } else if (!this._pauseSensorsOnStart) {
            console.log('[LiveStream] Sensor pause disabled by user');
        }
    }

    /**
     * Resume scheduler and sensor updates after streaming stops
     */
    async resumeAfterStreaming() {
        const apiBase = window.API_BASE || '/api';

        // Resume sensor updates first
        if (this._sensorsPaused && this._pausedDeviceId) {
            try {
                await fetch(`${apiBase}/sensors/resume/${encodeURIComponent(this._pausedDeviceId)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                console.log(`[LiveStream] Resumed sensor updates for ${this._pausedDeviceId}`);
                this._sensorsPaused = false;
                this._pausedDeviceId = null;
            } catch (e) {
                console.warn('[LiveStream] Could not resume sensor updates:', e);
            }
        }

        // Resume flow scheduler
        if (this._schedulerPaused) {
            try {
                await fetch(`${apiBase}/scheduler/resume`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                console.log('[LiveStream] Resumed flow scheduler after streaming');
                this._schedulerPaused = false;
            } catch (e) {
                console.warn('[LiveStream] Could not resume scheduler:', e);
            }
        }
    }

    /**
     * Get current connection state
     * @returns {string} 'disconnected', 'connecting', 'connected', or 'reconnecting'
     */
    getConnectionState() {
        return this.connectionState;
    }

    /**
     * Enable/disable auto-reconnect
     * @param {boolean} enable
     */
    setAutoReconnect(enable) {
        this.autoReconnect = enable;
        if (!enable) {
            this._cancelReconnect();
        }
    }

    /**
     * Handle incoming frame from WebSocket
     * @param {Object} data - Frame data
     */
    async _handleFrame(data) {
        // Guard: Ignore frames if streaming was stopped (prevents race condition on quality switch)
        if (!this.isStreaming) {
            return;
        }

        if (data.type === 'error') {
            console.warn('[LiveStream] Server error:', data.message);
            return;
        }

        if (data.type !== 'frame') {
            return;
        }

        const now = performance.now();

        // Calculate FPS
        const frameDelta = now - this.metrics.lastFrameTime;
        this.metrics.lastFrameTime = now;

        // Update FPS using rolling average
        this.metrics.fpsHistory.push(1000 / frameDelta);
        if (this.metrics.fpsHistory.length > 10) {
            this.metrics.fpsHistory.shift();
        }
        this.metrics.fps = Math.round(
            this.metrics.fpsHistory.reduce((a, b) => a + b, 0) / this.metrics.fpsHistory.length
        );

        // Calculate latency (server timestamp to now)
        this.metrics.latency = Math.round((Date.now() / 1000 - data.timestamp) * 1000);
        this.metrics.captureTime = data.capture_ms;
        this.metrics.frameCount = data.frame_number;

        // Load and render image
        try {
            const img = new Image();

            await new Promise((resolve, reject) => {
                img.onload = resolve;
                img.onerror = reject;
                img.src = 'data:image/png;base64,' + data.image;
            });

            this.currentImage = img;

            // Update elements if provided
            if (data.elements && data.elements.length > 0) {
                this.elements = data.elements;

                // Infer device dimensions from element bounds (fixes coordinate issues when switching apps)
                // Elements are always in device pixel coordinates, so we can extract the native dimensions
                let maxX = 0, maxY = 0;
                data.elements.forEach(el => {
                    if (el.bounds) {
                        maxX = Math.max(maxX, el.bounds.x + el.bounds.width);
                        maxY = Math.max(maxY, el.bounds.y + el.bounds.height);
                    }
                });

                // Only update if we found valid bounds and they differ significantly
                if (maxX > 100 && maxY > 100) {
                    // Round to common device widths/heights
                    const inferredWidth = Math.round(maxX / 10) * 10;
                    const inferredHeight = Math.round(maxY / 10) * 10;

                    if (inferredWidth !== this.deviceWidth || inferredHeight !== this.deviceHeight) {
                        this.deviceWidth = inferredWidth;
                        this.deviceHeight = inferredHeight;
                        console.log(`[LiveStream] Updated device dimensions from elements: ${inferredWidth}x${inferredHeight}`);
                    }
                }
            }

            // CRITICAL FIX: Detect app changes by screenshot dimension changes
            // When user manually switches apps during streaming, screenshot dimensions change
            // but elements array is empty (streaming sends [] to save bandwidth)
            // Clear old cached elements to prevent misaligned overlays on new app
            if (this.currentImage && this.elements && this.elements.length > 0) {
                const dimensionsChanged =
                    img.naturalWidth !== this.currentImage.naturalWidth ||
                    img.naturalHeight !== this.currentImage.naturalHeight;

                if (dimensionsChanged) {
                    console.log(`[LiveStream] Screenshot dimensions changed: ${this.currentImage.naturalWidth}x${this.currentImage.naturalHeight} → ${img.naturalWidth}x${img.naturalHeight}`);
                    console.log(`[LiveStream] App switch detected - clearing ${this.elements.length} cached elements`);
                    this.elements = [];
                    // NOTE: Do NOT update deviceWidth/deviceHeight here!
                    // Stream resolution (img dimensions) != device native resolution
                    // Device dimensions should only come from elements API
                }
            }

            // Render frame
            this._renderFrame(img, this.elements);

            // Callback
            if (this.onFrame) {
                this.onFrame(data);
            }

            // Update metrics callback
            if (this.onMetricsUpdate) {
                this.onMetricsUpdate(this.metrics);
            }

        } catch (error) {
            console.error('[LiveStream] Failed to render frame:', error);
        }
    }

    /**
     * Render frame on canvas
     * @param {Image} img - Screenshot image
     * @param {Array} elements - UI elements
     */
    _renderFrame(img, elements) {
        // Resize canvas if needed
        if (this.canvas.width !== img.width || this.canvas.height !== img.height) {
            this.canvas.width = img.width;
            this.canvas.height = img.height;

            // FIX: Update deviceWidth/deviceHeight from actual frame dimensions
            // The config message may have sent default 1080x1920, but actual device
            // could be in landscape mode (1920x1080) or different resolution
            // Use frame dimensions as device dimensions for correct overlay scaling
            const imgAspect = img.width / img.height;
            const deviceAspect = this.deviceWidth / this.deviceHeight;
            const aspectMismatch = Math.abs(imgAspect - deviceAspect) > 0.1;

            if (aspectMismatch || (this.deviceWidth === 1080 && this.deviceHeight === 1920)) {
                // Aspect ratio mismatch or still using defaults - update from frame
                this.deviceWidth = img.width;
                this.deviceHeight = img.height;
                console.log(`[LiveStream] Updated device dimensions from frame: ${img.width}x${img.height}`);
            }
        }

        // Detect if screen content has changed (for stale element detection or smart refresh)
        // Enabled when: autoHideStaleElements OR smartRefreshEnabled with callback
        // Note: Adds ~5-10ms per frame due to canvas sampling + hash
        if (this.autoHideStaleElements || (this.smartRefreshEnabled && this.onScreenChange)) {
            this._detectScreenChange(img);
        }

        // Clear canvas to remove old overlays
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw screenshot
        this.ctx.drawImage(img, 0, 0);

        // Draw overlays based on display mode
        if (this.showOverlays && elements.length > 0) {
            switch (this.displayMode) {
                case 'hoverOnly':
                    // Only draw the currently hovered element
                    if (this.hoveredElement) {
                        this._drawElements([this.hoveredElement]);
                    }
                    break;

                case 'topLayer':
                    // Only draw elements that are not occluded by other elements
                    const topLayerElements = this._filterTopLayerElements(elements);
                    this._drawElements(topLayerElements);
                    break;

                case 'all':
                default:
                    // Draw all elements (original behavior)
                    this._drawElements(elements);
                    break;
            }
        }
    }

    /**
     * Filter elements to only include those in the top layer (not occluded)
     * Uses heuristics: elements that significantly overlap with later elements are likely occluded
     * @param {Array} elements - All elements
     * @returns {Array} Elements that appear to be in the top layer
     */
    _filterTopLayerElements(elements) {
        const filtered = this._getFilteredElements(elements);
        if (filtered.length === 0) return filtered;

        // Find potential popup/dialog by looking for large elements near the end
        // that might be covering earlier elements
        const topLayerCandidates = [];
        let potentialPopup = null;

        // Look for popup-like elements (large elements in the later part of the array)
        for (let i = filtered.length - 1; i >= 0; i--) {
            const el = filtered[i];
            const area = el.bounds.width * el.bounds.height;
            const screenArea = this.deviceWidth * this.deviceHeight;

            // If element covers more than 10% of screen and is in top half of z-order
            if (area > screenArea * 0.1 && i > filtered.length / 2) {
                potentialPopup = el;
                break;
            }
        }

        // If we found a popup, only include elements that are:
        // 1. Inside the popup bounds, OR
        // 2. Come after the popup in the array (on top of popup)
        if (potentialPopup) {
            const popupIdx = filtered.indexOf(potentialPopup);
            for (let i = 0; i < filtered.length; i++) {
                const el = filtered[i];

                // Elements after popup are always included
                if (i > popupIdx) {
                    topLayerCandidates.push(el);
                    continue;
                }

                // Check if element is inside popup bounds
                const isInsidePopup =
                    el.bounds.x >= potentialPopup.bounds.x &&
                    el.bounds.y >= potentialPopup.bounds.y &&
                    el.bounds.x + el.bounds.width <= potentialPopup.bounds.x + potentialPopup.bounds.width &&
                    el.bounds.y + el.bounds.height <= potentialPopup.bounds.y + potentialPopup.bounds.height;

                if (isInsidePopup) {
                    topLayerCandidates.push(el);
                }
            }
            return topLayerCandidates;
        }

        // No popup detected - return all filtered elements
        return filtered;
    }

    /**
     * Get current filter settings as a hash for cache invalidation
     */
    _getFilterSettingsHash() {
        return `${this.showClickable}-${this.showNonClickable}-${this.hideContainers}-${this.hideSmall}-${this.hideDividers}-${this.hideEmptyElements}-${this.deviceWidth}`;
    }

    /**
     * Get filtered elements (cached for performance)
     * Only re-filters when elements array or filter settings change
     */
    _getFilteredElements(elements) {
        const currentHash = this._getFilterSettingsHash();

        // Return cached if elements and settings haven't changed
        if (elements === this._lastElementsRef && currentHash === this._filterSettingsHash) {
            return this._filteredElements;
        }

        // Re-filter elements
        this._filteredElements = elements.filter(el => {
            if (!el.bounds) return false;

            // Filter based on clickable state
            if (el.clickable && !this.showClickable) return false;
            if (!el.clickable && !this.showNonClickable) return false;

            // Filter out container elements
            if (this.hideContainers && el.class && this.containerClasses.has(el.class)) {
                return false;
            }

            // Filter out small elements (< 20px)
            if (this.hideSmall && (el.bounds.width < 20 || el.bounds.height < 20)) {
                return false;
            }

            // Filter out dividers (full-width horizontal lines)
            if (this.hideDividers && el.bounds.height <= 5 && el.bounds.width >= this.deviceWidth * 0.9) {
                return false;
            }

            // Filter out empty elements
            if (this.hideEmptyElements) {
                const hasText = el.text && el.text.trim();
                const hasContentDesc = el.content_desc && el.content_desc.trim();
                if (!el.clickable && !hasText && !hasContentDesc) {
                    return false;
                }
            }

            return true;
        });

        // Update cache references
        this._lastElementsRef = elements;
        this._filterSettingsHash = currentHash;

        return this._filteredElements;
    }

    /**
     * Draw UI element overlays
     * Scales element coordinates from device resolution to canvas resolution
     * @param {Array} elements - UI elements
     */
    _drawElements(elements) {
        // OPTIMIZATION: Use cached filtered elements
        const filteredElements = this._getFilteredElements(elements);

        // Calculate scale factor: stream may be at lower resolution than device
        const scaleX = this.canvas.width / this.deviceWidth;
        const scaleY = this.canvas.height / this.deviceHeight;

        // Draw all filtered elements (no per-element filtering needed)
        for (const el of filteredElements) {
            // Scale coordinates from device to canvas resolution
            const x = Math.floor(el.bounds.x * scaleX);
            const y = Math.floor(el.bounds.y * scaleY);
            const width = Math.floor(el.bounds.width * scaleX);
            const height = Math.floor(el.bounds.height * scaleY);

            // Draw bounding box
            this.ctx.strokeStyle = el.clickable ? '#00ff00' : '#ffff00';
            this.ctx.lineWidth = 2;
            this.ctx.strokeRect(x, y, width, height);

            // Draw text label
            if (this.showTextLabels && el.text && el.text.trim()) {
                this._drawTextLabel(el.text, x, y, width);
            }
        }
    }

    /**
     * Set container filtering
     * @param {boolean} hide - Whether to hide containers
     */
    setHideContainers(hide) {
        this.hideContainers = hide;
        // Next frame will automatically use updated filter
    }

    /**
     * Set empty element filtering
     * @param {boolean} hide - Whether to hide empty elements
     */
    setHideEmptyElements(hide) {
        this.hideEmptyElements = hide;
        // Next frame will automatically use updated filter
    }

    /**
     * Set small element filtering
     * @param {boolean} hide - Whether to hide small elements (< 20px)
     */
    setHideSmall(hide) {
        this.hideSmall = hide;
    }

    /**
     * Set divider filtering
     * @param {boolean} hide - Whether to hide horizontal line dividers
     */
    setHideDividers(hide) {
        this.hideDividers = hide;
    }

    /**
     * Set clickable element visibility
     * @param {boolean} show - Whether to show clickable elements
     */
    setShowClickable(show) {
        this.showClickable = show;
    }

    /**
     * Set non-clickable element visibility
     * @param {boolean} show - Whether to show non-clickable elements
     */
    setShowNonClickable(show) {
        this.showNonClickable = show;
    }

    /**
     * Set overlay display mode
     * @param {string} mode - 'all', 'hoverOnly', or 'topLayer'
     */
    setDisplayMode(mode) {
        this.displayMode = mode;
        console.log(`[LiveStream] Display mode set to: ${mode}`);
    }

    /**
     * Set currently hovered element (for hoverOnly display mode)
     * @param {Object|null} element - The element being hovered, or null
     */
    setHoveredElement(element) {
        this.hoveredElement = element;
    }

    /**
     * Set device dimensions for proper coordinate scaling
     * Call this when device dimensions are known (e.g., from elements API)
     * @param {number} width - Device width in pixels
     * @param {number} height - Device height in pixels
     */
    setDeviceDimensions(width, height) {
        if (width > 0 && height > 0) {
            this.deviceWidth = width;
            this.deviceHeight = height;
            this.elementsTimestamp = Date.now(); // Track when elements were refreshed
            this.resetScreenChangeTracking(); // Reset change detection
            console.log(`[LiveStream] Device dimensions updated: ${width}x${height}`);
        }
    }

    /**
     * Check if elements are stale (screen has changed since elements were fetched)
     * @returns {boolean} True if elements are stale
     */
    areElementsStale() {
        // No elements fetched yet
        if (this.elementsTimestamp === 0) return true;
        // Check if elements were marked stale by screen change detection
        // _elementsStale is set when screen change is detected and cleared when new elements arrive
        if (this._elementsStale) return true;
        // Also check if screen is currently changing (transitional state)
        return this._screenChanged;
    }

    /**
     * Mark elements as fresh (call after new elements are fetched)
     * This clears the stale flag so overlays will be drawn again
     */
    markElementsFresh() {
        this._elementsStale = false;
        this._elementsStaleTime = 0;
        this.elementsTimestamp = Date.now();
    }

    /**
     * Enable/disable auto-hiding of stale elements when screen changes
     * @param {boolean} enable - Whether to auto-hide stale elements
     */
    setAutoHideStaleElements(enable) {
        this.autoHideStaleElements = enable;
        console.log(`[LiveStream] Auto-hide stale elements: ${enable}`);
    }

    /**
     * Compute a simple hash of image data for change detection
     * Samples pixels in a grid pattern for better coverage of screen changes
     * @param {ImageData} imageData - Canvas image data
     * @returns {number} Simple hash value
     */
    _computeFrameHash(imageData) {
        const data = imageData.data;
        let hash = 0;
        // Sample more densely for better change detection
        // With 100x100 canvas (40000 bytes), sample every ~40 bytes = 1000 samples
        const step = Math.max(4, Math.floor(data.length / 4000));
        for (let i = 0; i < data.length; i += step) {
            // Combine R, G, B channels (skip alpha) for better sensitivity
            hash = ((hash << 5) - hash + data[i] + data[i+1] + data[i+2]) | 0;
        }
        return hash;
    }

    /**
     * Detect if screen content has changed significantly
     * When screen changes and then stabilizes, fires onScreenChange callback
     * @param {Image} img - New frame image
     */
    _detectScreenChange(img) {
        try {
            // Create temporary canvas to sample pixels
            const tempCanvas = document.createElement('canvas');
            tempCanvas.width = Math.min(img.width, 100); // Sample at low res for speed
            tempCanvas.height = Math.min(img.height, 100);
            const tempCtx = tempCanvas.getContext('2d');
            tempCtx.drawImage(img, 0, 0, tempCanvas.width, tempCanvas.height);

            const imageData = tempCtx.getImageData(0, 0, tempCanvas.width, tempCanvas.height);
            const newHash = this._computeFrameHash(imageData);

            // Compare with previous frame
            if (this._lastFrameHash !== 0 && newHash !== this._lastFrameHash) {
                // Frame is different - could be real change or compression noise
                this._differentFrameCount = (this._differentFrameCount || 0) + 1;
                this._stableFrameCount = 0;

                // Only mark as "screen changing" after multiple consecutive different frames
                // This filters out compression noise (single-frame differences)
                // CHANGED: Require 2 consecutive different frames before marking elements stale
                if (this._differentFrameCount >= 2 && !this._screenChanged) {
                    console.log('[LiveStream] Smart: significant change detected, marking elements stale');
                    this._screenChanged = true;
                    this._elementsStale = true;
                    this._elementsStaleTime = Date.now();
                }
            } else {
                // Frame is same as previous
                this._differentFrameCount = 0;
                this._stableFrameCount++;

                // Screen stabilized after a change - fire callback
                // Wait for 3 consecutive stable frames to confirm stabilization
                if (this._screenChanged && this._stableFrameCount >= 3) {
                    this._screenChanged = false;

                    // Rate limit: don't fire more than once per second
                    const now = Date.now();
                    if (!this._lastScreenChangeCallback || now - this._lastScreenChangeCallback > 1000) {
                        this._lastScreenChangeCallback = now;
                        console.log('[LiveStream] Smart: screen stabilized, triggering refresh');
                        if (this.onScreenChange) {
                            this.onScreenChange();
                        }
                    } else {
                        console.log('[LiveStream] Smart: screen stabilized but rate limited');
                    }
                }
            }

            this._lastFrameHash = newHash;
            this._framesSinceElements++;
        } catch (e) {
            // Ignore errors in change detection
        }
    }

    /**
     * Reset screen change tracking (call when elements are refreshed)
     */
    resetScreenChangeTracking() {
        this._screenChanged = false;
        this._elementsStale = false;  // Clear stale flag when new elements arrive
        this._framesSinceElements = 0;
        this._stableFrameCount = 0;
        // Don't log - this is called frequently and creates noise
    }

    /**
     * Draw text label
     * Scales font size based on canvas width to look appropriate at all resolutions
     * Uses cached font settings when canvas size hasn't changed
     * @param {string} text - Label text
     * @param {number} x - X position
     * @param {number} y - Y position
     * @param {number} w - Width
     */
    _drawTextLabel(text, x, y, w) {
        // Cache font settings based on canvas width (avoid recalculating per label)
        if (this._cachedFontCanvasWidth !== this.canvas.width) {
            const scaleFactor = Math.max(0.6, Math.min(1.5, this.canvas.width / 720));
            this._cachedFontSize = Math.round(11 * scaleFactor);
            this._cachedLabelHeight = Math.round(18 * scaleFactor);
            this._cachedCharWidth = Math.round(7 * scaleFactor);
            this._cachedLabelOffset = Math.round(3 * scaleFactor);
            this._cachedFontString = `${this._cachedFontSize}px monospace`;
            this._cachedFontCanvasWidth = this.canvas.width;
        }

        const maxChars = Math.floor(w / this._cachedCharWidth);
        const displayText = text.length > maxChars
            ? text.substring(0, maxChars - 2) + '..'
            : text;

        // Background
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
        this.ctx.fillRect(x, y - this._cachedLabelHeight, Math.min(w, displayText.length * this._cachedCharWidth + 4), this._cachedLabelHeight);

        // Text
        this.ctx.fillStyle = '#ffffff';
        this.ctx.font = this._cachedFontString;
        this.ctx.textBaseline = 'top';
        this.ctx.fillText(displayText, x + 2, y - this._cachedLabelHeight + this._cachedLabelOffset);
    }

    /**
     * Update cached scale factors for coordinate conversion
     * Called when canvas or device dimensions change
     */
    _updateScaleFactors() {
        if (this.canvas.width > 0 && this.canvas.height > 0 &&
            this.deviceWidth > 0 && this.deviceHeight > 0) {
            this._cachedScaleX = this.deviceWidth / this.canvas.width;
            this._cachedScaleY = this.deviceHeight / this.canvas.height;
            this._cachedScaleCanvasWidth = this.canvas.width;
            this._cachedScaleCanvasHeight = this.canvas.height;
            this._cachedScaleDeviceWidth = this.deviceWidth;
            this._cachedScaleDeviceHeight = this.deviceHeight;
        }
    }

    /**
     * Convert canvas coordinates to device coordinates
     * Accounts for stream quality scaling (canvas may be at lower resolution than device)
     * Uses cached scale factors for performance
     * @param {number} canvasX - Canvas X
     * @param {number} canvasY - Canvas Y
     * @returns {Object} Device coordinates {x, y}
     */
    canvasToDevice(canvasX, canvasY) {
        if (!this.currentImage) {
            // Return null instead of throwing - caller should check
            return null;
        }
        // Update cache if dimensions changed
        if (this._cachedScaleCanvasWidth !== this.canvas.width ||
            this._cachedScaleCanvasHeight !== this.canvas.height ||
            this._cachedScaleDeviceWidth !== this.deviceWidth ||
            this._cachedScaleDeviceHeight !== this.deviceHeight) {
            this._updateScaleFactors();
        }
        return {
            x: Math.round(canvasX * this._cachedScaleX),
            y: Math.round(canvasY * this._cachedScaleY)
        };
    }

    /**
     * Convert device coordinates to canvas coordinates
     * Inverse of canvasToDevice - used for drawing overlays at device positions
     * @param {number} deviceX - Device X
     * @param {number} deviceY - Device Y
     * @returns {Object} Canvas coordinates {x, y}
     */
    deviceToCanvas(deviceX, deviceY) {
        if (!this.currentImage) {
            return { x: deviceX, y: deviceY };
        }
        // Update cache if dimensions changed
        if (this._cachedScaleCanvasWidth !== this.canvas.width ||
            this._cachedScaleCanvasHeight !== this.canvas.height ||
            this._cachedScaleDeviceWidth !== this.deviceWidth ||
            this._cachedScaleDeviceHeight !== this.deviceHeight) {
            this._updateScaleFactors();
        }
        // Inverse scale: canvas = device / scale
        return {
            x: Math.round(deviceX / this._cachedScaleX),
            y: Math.round(deviceY / this._cachedScaleY)
        };
    }

    /**
     * Find element at canvas position
     * Scales canvas coordinates to device coordinates before comparing
     * @param {number} x - Canvas X
     * @param {number} y - Canvas Y
     * @returns {Object|null} Element or null
     */
    findElementAtPoint(x, y) {
        // Convert canvas position to device coordinates
        const scaleX = this.deviceWidth / this.canvas.width;
        const scaleY = this.deviceHeight / this.canvas.height;
        const deviceX = x * scaleX;
        const deviceY = y * scaleY;

        // Elements are in device coordinates - search from top (last) to bottom (first)
        // Prefer elements with text, skip containers
        let bestMatch = null;

        for (let i = this.elements.length - 1; i >= 0; i--) {
            const el = this.elements[i];
            if (!el.bounds) continue;

            const b = el.bounds;
            // Check if point is within element bounds
            if (!(deviceX >= b.x && deviceX <= b.x + b.width &&
                  deviceY >= b.y && deviceY <= b.y + b.height)) {
                continue;
            }

            // Check element properties
            const hasText = el.text && el.text.trim();
            const hasContentDesc = el.content_desc && el.content_desc.trim();
            const isContainer = el.class && this.containerClasses.has(el.class);

            // Always skip containers if filter is on
            if (this.hideContainers && isContainer) {
                continue;
            }

            // Skip empty elements if filter is on (except clickable buttons)
            if (this.hideEmptyElements) {
                const hasResourceId = el.resource_id && el.resource_id.trim();
                if (!hasText && !hasContentDesc && !(el.clickable && hasResourceId)) {
                    continue;
                }
            }

            // Prefer elements with text over those without
            if (hasText || hasContentDesc) {
                return el; // Return immediately if has text
            }

            // Keep as backup if it's clickable
            if (el.clickable && !bestMatch) {
                bestMatch = el;
            }
        }

        return bestMatch;
    }

    /**
     * Get current metrics
     * @returns {Object} Metrics
     */
    getMetrics() {
        return { ...this.metrics };
    }

    /**
     * Check if streaming
     * @returns {boolean}
     */
    isActive() {
        return this.isStreaming;
    }

    /**
     * Toggle overlay visibility
     * @param {boolean} show
     */
    setOverlaysVisible(show) {
        this.showOverlays = show;
    }

    /**
     * Toggle text labels
     * @param {boolean} show
     */
    setTextLabelsVisible(show) {
        this.showTextLabels = show;
    }

    /**
     * Get API base URL for REST calls
     * @returns {string} API base URL
     */
    _getApiBase() {
        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
        if (ingressMatch) {
            return ingressMatch[0] + '/api';
        }
        return '/api';
    }

    /**
     * Run backend benchmark to compare capture methods
     * Uses stream_manager.benchmark_capture() on server
     * @param {string} deviceId - Device to benchmark
     * @param {number} iterations - Number of captures per backend (default: 5)
     * @returns {Promise<Object>} Benchmark results
     */
    async runBenchmark(deviceId, iterations = 5) {
        const apiBase = this._getApiBase();
        const url = `${apiBase}/diagnostics/benchmark/${encodeURIComponent(deviceId)}?iterations=${iterations}`;

        console.log(`[LiveStream] Running capture benchmark for ${deviceId}...`);

        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`Benchmark failed: ${response.status}`);
            }
            const results = await response.json();
            console.log('[LiveStream] Benchmark results:', results);
            return results;
        } catch (error) {
            console.error('[LiveStream] Benchmark error:', error);
            throw error;
        }
    }

    /**
     * Get server-side stream metrics for device
     * @param {string} deviceId - Device ID
     * @returns {Promise<Object>} Server metrics
     */
    async getServerMetrics(deviceId) {
        const apiBase = this._getApiBase();
        const url = `${apiBase}/diagnostics/stream-metrics/${encodeURIComponent(deviceId)}`;

        try {
            const response = await fetch(url);
            if (!response.ok) {
                return null;
            }
            return await response.json();
        } catch (error) {
            console.warn('[LiveStream] Could not fetch server metrics:', error);
            return null;
        }
    }

    /**
     * Get connection quality rating based on current metrics
     * @returns {Object} Quality rating { level: 'good'|'ok'|'slow', description: string }
     */
    getConnectionQuality() {
        const fps = this.metrics.fps || 0;
        const latency = this.metrics.latency || 0;
        const captureTime = this.metrics.captureTime || 0;

        // Determine quality level
        if (fps >= 8 && latency < 500 && captureTime < 1000) {
            return { level: 'good', description: `${fps} FPS, ${captureTime}ms capture` };
        } else if (fps >= 4 && captureTime < 2000) {
            return { level: 'ok', description: `${fps} FPS, ${captureTime}ms capture` };
        } else {
            return { level: 'slow', description: `${fps} FPS, ${captureTime}ms capture - WiFi ADB is slow` };
        }
    }
}

// ES6 export
export default LiveStream;

// Global export for non-module usage
window.LiveStream = LiveStream;
