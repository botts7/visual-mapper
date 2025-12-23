/**
 * Visual Mapper - Device Control Module
 * Version: 0.0.4 (Phase 3)
 *
 * Handles device interaction: tap, swipe, text input, and interactive canvas.
 */

class DeviceControl {
    constructor(apiClient, screenshotCapture) {
        this.apiClient = apiClient;
        this.screenshotCapture = screenshotCapture;
        this.currentDeviceId = null;
        this.interactionMode = 'tap'; // 'tap' or 'swipe'
        this.swipeStartPos = null;

        console.log('[DeviceControl] Initialized');
    }

    /**
     * Set the current device ID for control operations
     * @param {string} deviceId - Device identifier
     */
    setDevice(deviceId) {
        this.currentDeviceId = deviceId;
        console.log(`[DeviceControl] Device set to: ${deviceId}`);
    }

    /**
     * Set interaction mode (tap or swipe)
     * @param {string} mode - 'tap' or 'swipe'
     */
    setMode(mode) {
        this.interactionMode = mode;
        console.log(`[DeviceControl] Mode set to: ${mode}`);
    }

    /**
     * Simulate tap at coordinates on device
     * @param {number} x - X coordinate
     * @param {number} y - Y coordinate
     */
    async tap(x, y) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            console.log(`[DeviceControl] Tap at (${x}, ${y}) on ${this.currentDeviceId}`);

            const response = await this.apiClient.post('/adb/tap', {
                device_id: this.currentDeviceId,
                x: x,
                y: y
            });

            console.log(`[DeviceControl] Tap successful: ${response.message}`);
            return response;

        } catch (error) {
            console.error('[DeviceControl] Tap failed:', error);
            throw error;
        }
    }

    /**
     * Simulate swipe gesture on device
     * @param {number} x1 - Start X coordinate
     * @param {number} y1 - Start Y coordinate
     * @param {number} x2 - End X coordinate
     * @param {number} y2 - End Y coordinate
     * @param {number} duration - Swipe duration in ms (default: 300)
     */
    async swipe(x1, y1, x2, y2, duration = 300) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            console.log(`[DeviceControl] Swipe (${x1},${y1}) -> (${x2},${y2}) on ${this.currentDeviceId}`);

            const response = await this.apiClient.post('/adb/swipe', {
                device_id: this.currentDeviceId,
                x1: x1,
                y1: y1,
                x2: x2,
                y2: y2,
                duration: duration
            });

            console.log(`[DeviceControl] Swipe successful: ${response.message}`);
            return response;

        } catch (error) {
            console.error('[DeviceControl] Swipe failed:', error);
            throw error;
        }
    }

    /**
     * Type text on device
     * @param {string} text - Text to type
     */
    async typeText(text) {
        if (!this.currentDeviceId) {
            throw new Error('No device selected');
        }

        try {
            console.log(`[DeviceControl] Type text on ${this.currentDeviceId}: ${text.substring(0, 20)}...`);

            const response = await this.apiClient.post('/adb/text', {
                device_id: this.currentDeviceId,
                text: text
            });

            console.log(`[DeviceControl] Text input successful: ${response.message}`);
            return response;

        } catch (error) {
            console.error('[DeviceControl] Text input failed:', error);
            throw error;
        }
    }

    /**
     * Enable interactive canvas (click to tap)
     * @param {HTMLCanvasElement} canvas - Canvas element
     * @param {Function} onInteraction - Callback for interaction feedback
     */
    enableInteractiveCanvas(canvas, onInteraction) {
        // Handle click/tap
        canvas.addEventListener('click', async (e) => {
            if (!this.currentDeviceId) {
                if (onInteraction) {
                    onInteraction({ error: 'No device selected' });
                }
                return;
            }

            const rect = canvas.getBoundingClientRect();
            const canvasX = e.clientX - rect.left;
            const canvasY = e.clientY - rect.top;

            // Scale coordinates if canvas is displayed smaller than actual size
            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;

            const deviceX = Math.round(canvasX * scaleX);
            const deviceY = Math.round(canvasY * scaleY);

            try {
                if (this.interactionMode === 'tap') {
                    // Tap mode
                    await this.tap(deviceX, deviceY);

                    // Visual feedback
                    this.drawTapIndicator(canvas, deviceX, deviceY);

                    if (onInteraction) {
                        onInteraction({
                            type: 'tap',
                            x: deviceX,
                            y: deviceY,
                            success: true
                        });
                    }
                }

            } catch (error) {
                if (onInteraction) {
                    onInteraction({ error: error.message });
                }
            }
        });

        // Handle swipe (mousedown -> mousemove -> mouseup)
        let isMouseDown = false;
        let startX, startY;

        canvas.addEventListener('mousedown', (e) => {
            if (!this.currentDeviceId || this.interactionMode !== 'swipe') return;

            isMouseDown = true;
            const rect = canvas.getBoundingClientRect();
            const canvasX = e.clientX - rect.left;
            const canvasY = e.clientY - rect.top;

            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;

            startX = Math.round(canvasX * scaleX);
            startY = Math.round(canvasY * scaleY);

            this.swipeStartPos = { x: startX, y: startY };
        });

        canvas.addEventListener('mouseup', async (e) => {
            if (!isMouseDown || !this.swipeStartPos) return;
            isMouseDown = false;

            const rect = canvas.getBoundingClientRect();
            const canvasX = e.clientX - rect.left;
            const canvasY = e.clientY - rect.top;

            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;

            const endX = Math.round(canvasX * scaleX);
            const endY = Math.round(canvasY * scaleY);

            try {
                await this.swipe(this.swipeStartPos.x, this.swipeStartPos.y, endX, endY);

                // Visual feedback
                this.drawSwipeIndicator(canvas, this.swipeStartPos.x, this.swipeStartPos.y, endX, endY);

                if (onInteraction) {
                    onInteraction({
                        type: 'swipe',
                        from: this.swipeStartPos,
                        to: { x: endX, y: endY },
                        success: true
                    });
                }

            } catch (error) {
                if (onInteraction) {
                    onInteraction({ error: error.message });
                }
            }

            this.swipeStartPos = null;
        });

        console.log('[DeviceControl] Interactive canvas enabled');
    }

    /**
     * Draw tap indicator on canvas
     * @param {HTMLCanvasElement} canvas - Canvas element
     * @param {number} x - X coordinate
     * @param {number} y - Y coordinate
     */
    drawTapIndicator(canvas, x, y) {
        const ctx = canvas.getContext('2d');

        // Draw animated circle
        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(x, y, 20, 0, 2 * Math.PI);
        ctx.stroke();

        // Draw crosshair
        ctx.beginPath();
        ctx.moveTo(x - 10, y);
        ctx.lineTo(x + 10, y);
        ctx.moveTo(x, y - 10);
        ctx.lineTo(x, y + 10);
        ctx.stroke();

        // Fade out after 500ms
        setTimeout(() => {
            // Re-render screenshot to clear indicator
            if (this.screenshotCapture.currentImage) {
                this.screenshotCapture.renderScreenshot(
                    this.screenshotCapture.currentImage,
                    this.screenshotCapture.elements
                );
            }
        }, 500);
    }

    /**
     * Draw swipe indicator on canvas
     * @param {HTMLCanvasElement} canvas - Canvas element
     * @param {number} x1 - Start X
     * @param {number} y1 - Start Y
     * @param {number} x2 - End X
     * @param {number} y2 - End Y
     */
    drawSwipeIndicator(canvas, x1, y1, x2, y2) {
        const ctx = canvas.getContext('2d');

        // Draw arrow
        ctx.strokeStyle = '#00ffff';
        ctx.fillStyle = '#00ffff';
        ctx.lineWidth = 3;

        // Line
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();

        // Arrowhead
        const angle = Math.atan2(y2 - y1, x2 - x1);
        const headLength = 15;

        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(
            x2 - headLength * Math.cos(angle - Math.PI / 6),
            y2 - headLength * Math.sin(angle - Math.PI / 6)
        );
        ctx.lineTo(
            x2 - headLength * Math.cos(angle + Math.PI / 6),
            y2 - headLength * Math.sin(angle + Math.PI / 6)
        );
        ctx.closePath();
        ctx.fill();

        // Fade out after 500ms
        setTimeout(() => {
            if (this.screenshotCapture.currentImage) {
                this.screenshotCapture.renderScreenshot(
                    this.screenshotCapture.currentImage,
                    this.screenshotCapture.elements
                );
            }
        }, 500);
    }
}

// ES6 export
export default DeviceControl;

// Global export for non-module usage
window.DeviceControl = DeviceControl;
