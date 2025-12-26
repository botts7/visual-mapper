/**
 * Visual Mapper - Live Stream Module
 * Version: 0.0.4 (Phase 4 POC)
 *
 * WebSocket-based live screenshot streaming with UI element overlays.
 * Target: 5-10 FPS, ~200-500ms latency
 */

class LiveStream {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.websocket = null;
        this.deviceId = null;
        this.isStreaming = false;

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
            fpsHistory: []
        };

        // Callbacks
        this.onFrame = null;
        this.onConnect = null;
        this.onDisconnect = null;
        this.onError = null;
        this.onMetricsUpdate = null;

        // Overlay settings
        this.showOverlays = true;
        this.showTextLabels = true;

        console.log('[LiveStream] Initialized');
    }

    /**
     * Get WebSocket URL for device
     * @param {string} deviceId - Device identifier
     * @returns {string} WebSocket URL
     */
    _getWebSocketUrl(deviceId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;

        // Handle Home Assistant ingress
        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);

        if (ingressMatch) {
            return `${protocol}//${host}${ingressMatch[0]}/ws/stream/${deviceId}`;
        }

        return `${protocol}//${host}/ws/stream/${deviceId}`;
    }

    /**
     * Start streaming from device
     * @param {string} deviceId - Device identifier (host:port)
     */
    start(deviceId) {
        if (this.isStreaming) {
            console.warn('[LiveStream] Already streaming, stopping first');
            this.stop();
        }

        this.deviceId = deviceId;
        const wsUrl = this._getWebSocketUrl(deviceId);

        console.log(`[LiveStream] Connecting to ${wsUrl}`);

        try {
            this.websocket = new WebSocket(wsUrl);

            this.websocket.onopen = () => {
                console.log('[LiveStream] Connected');
                this.isStreaming = true;
                this.metrics.frameCount = 0;
                this.metrics.lastFrameTime = performance.now();

                if (this.onConnect) {
                    this.onConnect();
                }
            };

            this.websocket.onmessage = (event) => {
                this._handleFrame(JSON.parse(event.data));
            };

            this.websocket.onclose = () => {
                console.log('[LiveStream] Disconnected');
                this.isStreaming = false;

                if (this.onDisconnect) {
                    this.onDisconnect();
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
            if (this.onError) {
                this.onError(error);
            }
        }
    }

    /**
     * Stop streaming
     */
    stop() {
        if (this.websocket) {
            console.log('[LiveStream] Stopping stream');
            this.websocket.close();
            this.websocket = null;
        }
        this.isStreaming = false;
        this.deviceId = null;
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
