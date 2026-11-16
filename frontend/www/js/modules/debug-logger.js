/**
 * Visual Mapper - Debug Logger Module
 * Version: 0.4.0
 *
 * Centralized debug logging with levels and toggle capability.
 * Provides consistent logging across all frontend modules.
 */

const LOG_LEVELS = {
    NONE: 0,
    ERROR: 1,
    WARN: 2,
    INFO: 3,
    DEBUG: 4,
    TRACE: 5
};

class DebugLogger {
    constructor(moduleName = 'App') {
        this.moduleName = moduleName;
        this._logLevel = this._loadLogLevel();
        this._enabled = this._loadEnabled();
    }

    /**
     * Load log level from localStorage
     * @private
     */
    _loadLogLevel() {
        try {
            const stored = localStorage.getItem('visual-mapper-log-level');
            if (stored && LOG_LEVELS[stored.toUpperCase()] !== undefined) {
                return LOG_LEVELS[stored.toUpperCase()];
            }
        } catch (e) {
            // localStorage not available
        }
        // Default to INFO in production, DEBUG in development
        return window.location.hostname === 'localhost' ? LOG_LEVELS.DEBUG : LOG_LEVELS.INFO;
    }

    /**
     * Load enabled state from localStorage
     * @private
     */
    _loadEnabled() {
        try {
            const stored = localStorage.getItem('visual-mapper-debug');
            return stored !== 'false';
        } catch (e) {
            return true;
        }
    }

    /**
     * Format log message with timestamp and module name
     * @private
     */
    _formatMessage(level, message) {
        const timestamp = new Date().toISOString().substr(11, 12);
        return `[${timestamp}] [${this.moduleName}] ${message}`;
    }

    /**
     * Check if logging is enabled for given level
     * @private
     */
    _shouldLog(level) {
        return this._enabled && level <= this._logLevel;
    }

    /**
     * Log error message (always visible unless logging disabled)
     */
    error(message, ...args) {
        if (this._shouldLog(LOG_LEVELS.ERROR)) {
            console.error(this._formatMessage('ERROR', message), ...args);
        }
    }

    /**
     * Log warning message
     */
    warn(message, ...args) {
        if (this._shouldLog(LOG_LEVELS.WARN)) {
            console.warn(this._formatMessage('WARN', message), ...args);
        }
    }

    /**
     * Log info message
     */
    info(message, ...args) {
        if (this._shouldLog(LOG_LEVELS.INFO)) {
            console.info(this._formatMessage('INFO', message), ...args);
        }
    }

    /**
     * Log debug message (verbose)
     */
    debug(message, ...args) {
        if (this._shouldLog(LOG_LEVELS.DEBUG)) {
            console.log(this._formatMessage('DEBUG', message), ...args);
        }
    }

    /**
     * Log trace message (very verbose)
     */
    trace(message, ...args) {
        if (this._shouldLog(LOG_LEVELS.TRACE)) {
            console.log(this._formatMessage('TRACE', message), ...args);
        }
    }

    /**
     * Log object with label
     */
    logObject(label, obj, level = 'debug') {
        const logFn = this[level] || this.debug;
        if (this._shouldLog(LOG_LEVELS[level.toUpperCase()] || LOG_LEVELS.DEBUG)) {
            console.groupCollapsed(`[${this.moduleName}] ${label}`);
            console.dir(obj);
            console.groupEnd();
        }
    }

    /**
     * Time a function execution
     */
    time(label) {
        if (this._shouldLog(LOG_LEVELS.DEBUG)) {
            console.time(`[${this.moduleName}] ${label}`);
        }
    }

    timeEnd(label) {
        if (this._shouldLog(LOG_LEVELS.DEBUG)) {
            console.timeEnd(`[${this.moduleName}] ${label}`);
        }
    }

    /**
     * Create a child logger with sub-module name
     */
    child(subModule) {
        return new DebugLogger(`${this.moduleName}:${subModule}`);
    }
}

/**
 * Logger factory - creates logger instances for modules
 */
const LoggerFactory = {
    _instances: new Map(),

    /**
     * Get or create a logger for a module
     * @param {string} moduleName - Name of the module
     * @returns {DebugLogger} Logger instance
     */
    getLogger(moduleName) {
        if (!this._instances.has(moduleName)) {
            this._instances.set(moduleName, new DebugLogger(moduleName));
        }
        return this._instances.get(moduleName);
    },

    /**
     * Set global log level
     * @param {string} level - Log level (NONE, ERROR, WARN, INFO, DEBUG, TRACE)
     */
    setLogLevel(level) {
        const upperLevel = level.toUpperCase();
        if (LOG_LEVELS[upperLevel] !== undefined) {
            try {
                localStorage.setItem('visual-mapper-log-level', upperLevel);
            } catch (e) {
                // Ignore storage errors
            }
            // Update all existing loggers
            this._instances.forEach(logger => {
                logger._logLevel = LOG_LEVELS[upperLevel];
            });
            console.info(`[LoggerFactory] Log level set to ${upperLevel}`);
        } else {
            console.error(`[LoggerFactory] Invalid log level: ${level}`);
        }
    },

    /**
     * Enable or disable all logging
     * @param {boolean} enabled
     */
    setEnabled(enabled) {
        try {
            localStorage.setItem('visual-mapper-debug', enabled ? 'true' : 'false');
        } catch (e) {
            // Ignore storage errors
        }
        this._instances.forEach(logger => {
            logger._enabled = enabled;
        });
        console.info(`[LoggerFactory] Logging ${enabled ? 'enabled' : 'disabled'}`);
    },

    /**
     * Get current log level
     * @returns {string} Current log level name
     */
    getLogLevel() {
        const instance = this._instances.values().next().value;
        if (instance) {
            const levelNum = instance._logLevel;
            return Object.keys(LOG_LEVELS).find(key => LOG_LEVELS[key] === levelNum) || 'INFO';
        }
        return 'INFO';
    }
};

// Expose to window for console debugging
window.VisualMapperLogger = LoggerFactory;

// Console helper commands
window.vmDebug = {
    setLevel: (level) => LoggerFactory.setLogLevel(level),
    enable: () => LoggerFactory.setEnabled(true),
    disable: () => LoggerFactory.setEnabled(false),
    getLevel: () => LoggerFactory.getLogLevel(),
    help: () => console.log(`
Visual Mapper Debug Commands:
  vmDebug.setLevel('DEBUG')  - Set log level (NONE, ERROR, WARN, INFO, DEBUG, TRACE)
  vmDebug.enable()           - Enable logging
  vmDebug.disable()          - Disable logging
  vmDebug.getLevel()         - Get current log level
    `)
};

export { DebugLogger, LoggerFactory, LOG_LEVELS };
export default LoggerFactory;
