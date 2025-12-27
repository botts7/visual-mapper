/**
 * Toast Notification Module
 * Visual Mapper v0.0.5
 *
 * Simple toast notifications for user feedback
 */

class ToastManager {
    constructor() {
        this.container = null;
        this.activeToasts = new Set();
        this.init();
    }

    init() {
        // Wait for body to be available
        if (!document.body) {
            console.warn('[ToastManager] DOM not ready, deferring init');
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => this.init());
            } else {
                // Use setTimeout as fallback
                setTimeout(() => this.init(), 100);
            }
            return;
        }

        // Create toast container if it doesn't exist
        if (!document.getElementById('toast-container')) {
            this.container = document.createElement('div');
            this.container.id = 'toast-container';
            this.container.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 10000;
                display: flex;
                flex-direction: column;
                gap: 10px;
                pointer-events: none;
            `;
            document.body.appendChild(this.container);
            console.log('[ToastManager] Container created');
        } else {
            this.container = document.getElementById('toast-container');
            console.log('[ToastManager] Container found');
        }
    }

    show(message, type = 'info', duration = 3000) {
        // Ensure container exists
        if (!this.container) {
            console.error('[ToastManager] Container not initialized, reinitializing...');
            this.init();
            if (!this.container) {
                console.error('[ToastManager] Failed to create container, toast will not appear:', message);
                return null;
            }
        }

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            padding: 12px 20px;
            border-radius: 8px;
            background: ${this.getBackgroundColor(type)};
            color: white;
            font-size: 14px;
            font-weight: 500;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            pointer-events: auto;
            cursor: pointer;
            animation: slideIn 0.3s ease-out;
            max-width: 400px;
            word-wrap: break-word;
        `;

        // Add animation styles
        if (!document.getElementById('toast-animations')) {
            const style = document.createElement('style');
            style.id = 'toast-animations';
            style.textContent = `
                @keyframes slideIn {
                    from {
                        transform: translateX(100%);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
                @keyframes slideOut {
                    from {
                        transform: translateX(0);
                        opacity: 1;
                    }
                    to {
                        transform: translateX(100%);
                        opacity: 0;
                    }
                }
            `;
            document.head.appendChild(style);
        }

        this.container.appendChild(toast);
        this.activeToasts.add(toast);
        console.log(`[ToastManager] Toast shown: ${message} (${type})`);


        // Click to dismiss
        toast.addEventListener('click', () => {
            this.dismiss(toast);
        });

        // Auto-dismiss after duration
        if (duration > 0) {
            setTimeout(() => {
                this.dismiss(toast);
            }, duration);
        }

        return toast;
    }

    dismiss(toast) {
        if (!this.activeToasts.has(toast)) return;

        toast.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
            this.activeToasts.delete(toast);
        }, 300);
    }

    dismissAll() {
        this.activeToasts.forEach(toast => this.dismiss(toast));
    }

    getBackgroundColor(type) {
        const colors = {
            success: '#22c55e',
            error: '#ef4444',
            warning: '#f59e0b',
            info: '#3b82f6'
        };
        return colors[type] || colors.info;
    }
}

// Create singleton instance
const toastManager = new ToastManager();

/**
 * Show a toast notification
 * @param {string} message - Message to display
 * @param {string} type - Toast type: 'success', 'error', 'warning', 'info'
 * @param {number} duration - Duration in ms (0 = no auto-dismiss)
 */
export function showToast(message, type = 'info', duration = 3000) {
    return toastManager.show(message, type, duration);
}

/**
 * Dismiss all active toasts
 */
export function dismissAllToasts() {
    toastManager.dismissAll();
}

// Export for global access (dual export pattern)
window.showToast = showToast;
window.dismissAllToasts = dismissAllToasts;

export default { showToast, dismissAllToasts };
