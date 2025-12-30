/**
 * Visual Mapper - Live Stream Module
 * Version: 0.0.18 (Auto-clear cached elements when screenshot dimensions change - fixes manual app switching)
 *
 * WebSocket-based live screenshot streaming with UI element overlays.
 * Supports two modes:
 * - websocket: Base64 JSON frames (original)
 * - mjpeg: Binary JPEG frames (~30% less bandwidth)
 *
 * Quality settings:
 * - high: Native resolution (~5 FPS)
 * - medium: 720p (~10 FPS)
 * - low: 480p (~15 FPS)
 * - fast: 360p (~20 FPS)
 *
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Connection state tracking
 * - Container element filtering
 * - Backend benchmark support via stream_manager
 * - Enhanced quality indicators
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
        this.streamQuality = 'medium'; // 'high', 'medium', 'low', 'fast'

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
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000; // Start with 1 second
        this.maxReconnectDelay = 30000; // Max 30 seconds
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

        // Overlay settings
        this.showOverlays = true;
        this.showTextLabels = true;
        this.hideContainers = true;
        this.hideEmptyElements = true;

        // Container classes to filter out (reduce visual clutter)
        this.containerClasses = [
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
        ];

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
    _getWebSocketUrl(deviceId, mode = 'websocket', quality = 'medium') {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;

        // Endpoint based on mode
        const endpoint = mode === 'mjpeg' ? 'ws/stream-mjpeg' : 'ws/stream';

        // Handle Home Assistant ingress
        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);

        // Add quality as query parameter
        const queryParams = `?quality=${quality}`;

        if (ingressMatch) {
            return `${protocol}//${host}${ingressMatch[0]}/${endpoint}/${deviceId}${queryParams}`;
        }

        return `${protocol}//${host}/api/${endpoint}/${deviceId}${queryParams}`;
    }

    /**
     * Start streaming from device
     * @param {string} deviceId - Device identifier (host:port)
     * @param {string} mode - 'websocket' (base64) or 'mjpeg' (binary)
     * @param {string} quality - 'high', 'medium', 'low', 'fast'
     */
    start(deviceId, mode = 'websocket', quality = 'medium') {
        if (this.isStreaming) {
            console.warn('[LiveStream] Already streaming, stopping first');
            this.stop();
        }

        this._manualStop = false;
        this.deviceId = deviceId;
        this.streamMode = mode;
        this.streamQuality = quality;
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

            // Enable binary type for MJPEG mode
            if (this.streamMode === 'mjpeg') {
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
     * @param {ArrayBuffer} buffer - Binary frame data
     */
    async _handleMjpegFrame(buffer) {
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
            const blob = new Blob([jpegData], { type: 'image/jpeg' });
            const blobUrl = URL.createObjectURL(blob);

            const img = new Image();
            await new Promise((resolve, reject) => {
                img.onload = () => {
                    URL.revokeObjectURL(blobUrl); // Clean up
                    resolve();
                };
                img.onerror = () => {
                    URL.revokeObjectURL(blobUrl);
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
        }
    }

    /**
     * Stop streaming
     */
    stop() {
        console.log('[LiveStream] Stopping stream');
        this._manualStop = true;
        this._cancelReconnect();
        this.reconnectAttempts = 0;

        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
        this.isStreaming = false;
        this.deviceId = null;
        this._setConnectionState('disconnected');
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
                    // Update device dimensions to match new screenshot
                    this.deviceWidth = img.naturalWidth;
                    this.deviceHeight = img.naturalHeight;
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
        }

        // Clear canvas to remove old overlays
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw screenshot
        this.ctx.drawImage(img, 0, 0);

        // Draw overlays
        if (this.showOverlays && elements.length > 0) {
            this._drawElements(elements);
        }
    }

    /**
     * Draw UI element overlays
     * Scales element coordinates from device resolution to canvas resolution
     * @param {Array} elements - UI elements
     */
    _drawElements(elements) {
        // Calculate scale factor: stream may be at lower resolution than device
        const scaleX = this.canvas.width / this.deviceWidth;
        const scaleY = this.canvas.height / this.deviceHeight;

        elements.forEach(el => {
            if (!el.bounds) return;

            // Filter out container elements if hideContainers is enabled
            if (this.hideContainers && el.class && this.containerClasses.includes(el.class)) {
                return;
            }

            // Filter out empty elements (no text or content-desc)
            // IMPORTANT: Always show clickable elements (they're interactive buttons/icons)
            if (this.hideEmptyElements) {
                const hasText = el.text && el.text.trim();
                const hasContentDesc = el.content_desc && el.content_desc.trim();
                // Skip only if: not clickable AND no text AND no content-desc
                if (!el.clickable && !hasText && !hasContentDesc) {
                    return;
                }
            }

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
        });
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
     * Set device dimensions for proper coordinate scaling
     * Call this when device dimensions are known (e.g., from elements API)
     * @param {number} width - Device width in pixels
     * @param {number} height - Device height in pixels
     */
    setDeviceDimensions(width, height) {
        if (width > 0 && height > 0) {
            this.deviceWidth = width;
            this.deviceHeight = height;
            console.log(`[LiveStream] Device dimensions updated: ${width}x${height}`);
        }
    }

    /**
     * Draw text label
     * @param {string} text - Label text
     * @param {number} x - X position
     * @param {number} y - Y position
     * @param {number} w - Width
     */
    _drawTextLabel(text, x, y, w) {
        const labelHeight = 18;
        const maxChars = Math.floor(w / 7);
        const displayText = text.length > maxChars
            ? text.substring(0, maxChars - 2) + '..'
            : text;

        // Background
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
        this.ctx.fillRect(x, y - labelHeight, Math.min(w, displayText.length * 7 + 4), labelHeight);

        // Text
        this.ctx.fillStyle = '#ffffff';
        this.ctx.font = '11px monospace';
        this.ctx.textBaseline = 'top';
        this.ctx.fillText(displayText, x + 2, y - labelHeight + 3);
    }

    /**
     * Convert canvas coordinates to device coordinates
     * Accounts for stream quality scaling (canvas may be at lower resolution than device)
     * @param {number} canvasX - Canvas X
     * @param {number} canvasY - Canvas Y
     * @returns {Object} Device coordinates {x, y}
     */
    canvasToDevice(canvasX, canvasY) {
        if (!this.currentImage) {
            throw new Error('No frame loaded');
        }
        // Scale from canvas resolution to device resolution
        const scaleX = this.deviceWidth / this.canvas.width;
        const scaleY = this.deviceHeight / this.canvas.height;
        return {
            x: Math.round(canvasX * scaleX),
            y: Math.round(canvasY * scaleY)
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
            const isContainer = el.class && this.containerClasses.includes(el.class);

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
