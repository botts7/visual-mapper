/**
 * Visual Mapper - Live Stream Module
 * Version: 0.0.7 (Quality settings for optimized streaming)
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

        console.log('[LiveStream] Initialized (WebSocket + MJPEG + Auto-reconnect)');
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

        return `${protocol}//${host}/${endpoint}/${deviceId}${queryParams}`;
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

        // Draw screenshot
        this.ctx.drawImage(img, 0, 0);

        // Draw overlays
        if (this.showOverlays && elements.length > 0) {
            this._drawElements(elements);
        }
    }

    /**
     * Draw UI element overlays
     * @param {Array} elements - UI elements
     */
    _drawElements(elements) {
        elements.forEach(el => {
            if (!el.bounds) return;

            const { x, y, width, height } = el.bounds;

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
     * @param {number} canvasX - Canvas X
     * @param {number} canvasY - Canvas Y
     * @returns {Object} Device coordinates {x, y}
     */
    canvasToDevice(canvasX, canvasY) {
        if (!this.currentImage) {
            throw new Error('No frame loaded');
        }
        return {
            x: Math.round(canvasX),
            y: Math.round(canvasY)
        };
    }

    /**
     * Find element at canvas position
     * @param {number} x - Canvas X
     * @param {number} y - Canvas Y
     * @returns {Object|null} Element or null
     */
    findElementAtPoint(x, y) {
        for (let i = this.elements.length - 1; i >= 0; i--) {
            const el = this.elements[i];
            if (!el.bounds) continue;

            const b = el.bounds;
            if (x >= b.x && x <= b.x + b.width &&
                y >= b.y && y <= b.y + b.height) {
                return el;
            }
        }
        return null;
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
}

// ES6 export
export default LiveStream;

// Global export for non-module usage
window.LiveStream = LiveStream;
