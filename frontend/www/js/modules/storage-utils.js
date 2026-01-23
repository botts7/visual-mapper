/**
 * Safe LocalStorage Utilities
 * Visual Mapper v0.1.0
 *
 * Provides safe localStorage operations with error handling.
 * Prevents application crashes from corrupted or unavailable localStorage.
 */

const StorageUtils = {
    /**
     * Safely get an item from localStorage
     * @param {string} key - Storage key
     * @param {*} defaultValue - Default value if key not found or error
     * @returns {string|null} Value or defaultValue
     */
    getItem(key, defaultValue = null) {
        try {
            const value = localStorage.getItem(key);
            return value !== null ? value : defaultValue;
        } catch (error) {
            console.warn(`[StorageUtils] Failed to get '${key}':`, error.message);
            return defaultValue;
        }
    },

    /**
     * Safely set an item in localStorage
     * @param {string} key - Storage key
     * @param {string} value - Value to store
     * @returns {boolean} True if successful
     */
    setItem(key, value) {
        try {
            localStorage.setItem(key, value);
            return true;
        } catch (error) {
            console.warn(`[StorageUtils] Failed to set '${key}':`, error.message);
            // QuotaExceededError - try to clear old data
            if (error.name === 'QuotaExceededError') {
                console.warn('[StorageUtils] Storage quota exceeded, attempting cleanup...');
                this._cleanupOldEntries();
                try {
                    localStorage.setItem(key, value);
                    return true;
                } catch (retryError) {
                    console.error('[StorageUtils] Failed after cleanup:', retryError.message);
                }
            }
            return false;
        }
    },

    /**
     * Safely remove an item from localStorage
     * @param {string} key - Storage key
     * @returns {boolean} True if successful
     */
    removeItem(key) {
        try {
            localStorage.removeItem(key);
            return true;
        } catch (error) {
            console.warn(`[StorageUtils] Failed to remove '${key}':`, error.message);
            return false;
        }
    },

    /**
     * Safely get and parse JSON from localStorage
     * @param {string} key - Storage key
     * @param {*} defaultValue - Default value if key not found, parse fails, or error
     * @returns {*} Parsed value or defaultValue
     */
    getJSON(key, defaultValue = null) {
        try {
            const value = localStorage.getItem(key);
            if (value === null) return defaultValue;
            return JSON.parse(value);
        } catch (error) {
            console.warn(`[StorageUtils] Failed to get/parse JSON '${key}':`, error.message);
            return defaultValue;
        }
    },

    /**
     * Safely stringify and store JSON in localStorage
     * @param {string} key - Storage key
     * @param {*} value - Value to stringify and store
     * @returns {boolean} True if successful
     */
    setJSON(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (error) {
            console.warn(`[StorageUtils] Failed to set JSON '${key}':`, error.message);
            if (error.name === 'QuotaExceededError') {
                this._cleanupOldEntries();
                try {
                    localStorage.setItem(key, JSON.stringify(value));
                    return true;
                } catch (retryError) {
                    console.error('[StorageUtils] Failed after cleanup:', retryError.message);
                }
            }
            return false;
        }
    },

    /**
     * Check if localStorage is available
     * @returns {boolean} True if localStorage is available and working
     */
    isAvailable() {
        try {
            const testKey = '__storage_test__';
            localStorage.setItem(testKey, testKey);
            localStorage.removeItem(testKey);
            return true;
        } catch (error) {
            return false;
        }
    },

    /**
     * Get all keys matching a prefix
     * @param {string} prefix - Key prefix to match
     * @returns {string[]} Array of matching keys
     */
    getKeysByPrefix(prefix) {
        try {
            const keys = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.startsWith(prefix)) {
                    keys.push(key);
                }
            }
            return keys;
        } catch (error) {
            console.warn(`[StorageUtils] Failed to get keys by prefix '${prefix}':`, error.message);
            return [];
        }
    },

    /**
     * Remove all keys matching a prefix
     * @param {string} prefix - Key prefix to match
     * @returns {number} Number of keys removed
     */
    removeByPrefix(prefix) {
        const keys = this.getKeysByPrefix(prefix);
        let removed = 0;
        keys.forEach(key => {
            if (this.removeItem(key)) removed++;
        });
        return removed;
    },

    /**
     * Attempt to clean up old/temporary entries to free space
     * @private
     */
    _cleanupOldEntries() {
        try {
            // Remove known temporary keys
            const tempPrefixes = ['temp_', 'cache_', '__'];
            tempPrefixes.forEach(prefix => {
                this.removeByPrefix(prefix);
            });
            console.log('[StorageUtils] Cleanup completed');
        } catch (error) {
            console.error('[StorageUtils] Cleanup failed:', error.message);
        }
    }
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = StorageUtils;
}

// Make available globally
window.StorageUtils = StorageUtils;
