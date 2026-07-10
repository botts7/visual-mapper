/**
 * Debug Logger Module Tests
 * Visual Mapper v0.4.0-beta.4
 */

// Mock localStorage
const localStorageMock = (() => {
    let store = {};
    return {
        getItem: jest.fn((key) => store[key] || null),
        setItem: jest.fn((key, value) => {
            store[key] = value.toString();
        }),
        removeItem: jest.fn((key) => {
            delete store[key];
        }),
        clear: jest.fn(() => {
            store = {};
        }),
    };
})();

Object.defineProperty(window, 'localStorage', {
    value: localStorageMock,
});

// Mock console methods
const consoleMock = {
    log: jest.fn(),
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
    groupCollapsed: jest.fn(),
    groupEnd: jest.fn(),
    dir: jest.fn(),
    time: jest.fn(),
    timeEnd: jest.fn(),
};

Object.keys(consoleMock).forEach((key) => {
    global.console[key] = consoleMock[key];
});

// Import after mocking
const { DebugLogger, LoggerFactory, LOG_LEVELS } = require('../www/js/modules/debug-logger.js');

describe('LOG_LEVELS', () => {
    test('has correct level values', () => {
        expect(LOG_LEVELS.NONE).toBe(0);
        expect(LOG_LEVELS.ERROR).toBe(1);
        expect(LOG_LEVELS.WARN).toBe(2);
        expect(LOG_LEVELS.INFO).toBe(3);
        expect(LOG_LEVELS.DEBUG).toBe(4);
        expect(LOG_LEVELS.TRACE).toBe(5);
    });
});

describe('DebugLogger', () => {
    let logger;

    beforeEach(() => {
        localStorageMock.clear();
        jest.clearAllMocks();
        logger = new DebugLogger('TestModule');
        // Force enable logging for tests
        logger._enabled = true;
        logger._logLevel = LOG_LEVELS.TRACE;
    });

    describe('constructor', () => {
        test('creates logger with module name', () => {
            const testLogger = new DebugLogger('MyModule');
            expect(testLogger.moduleName).toBe('MyModule');
        });

        test('uses default module name if not provided', () => {
            const testLogger = new DebugLogger();
            expect(testLogger.moduleName).toBe('App');
        });
    });

    describe('logging methods', () => {
        test('error logs to console.error', () => {
            logger.error('Test error message');
            expect(consoleMock.error).toHaveBeenCalled();
            expect(consoleMock.error.mock.calls[0][0]).toContain('[TestModule]');
            expect(consoleMock.error.mock.calls[0][0]).toContain('Test error message');
        });

        test('warn logs to console.warn', () => {
            logger.warn('Test warning');
            expect(consoleMock.warn).toHaveBeenCalled();
            expect(consoleMock.warn.mock.calls[0][0]).toContain('[TestModule]');
        });

        test('info logs to console.info', () => {
            logger.info('Test info');
            expect(consoleMock.info).toHaveBeenCalled();
            expect(consoleMock.info.mock.calls[0][0]).toContain('[TestModule]');
        });

        test('debug logs to console.log', () => {
            logger.debug('Test debug');
            expect(consoleMock.log).toHaveBeenCalled();
            expect(consoleMock.log.mock.calls[0][0]).toContain('[TestModule]');
        });

        test('trace logs to console.log', () => {
            logger.trace('Test trace');
            expect(consoleMock.log).toHaveBeenCalled();
        });
    });

    describe('log level filtering', () => {
        test('respects ERROR level - only errors shown', () => {
            logger._logLevel = LOG_LEVELS.ERROR;

            logger.error('error');
            logger.warn('warn');
            logger.info('info');
            logger.debug('debug');

            expect(consoleMock.error).toHaveBeenCalledTimes(1);
            expect(consoleMock.warn).not.toHaveBeenCalled();
            expect(consoleMock.info).not.toHaveBeenCalled();
            expect(consoleMock.log).not.toHaveBeenCalled();
        });

        test('respects WARN level - errors and warnings shown', () => {
            logger._logLevel = LOG_LEVELS.WARN;

            logger.error('error');
            logger.warn('warn');
            logger.info('info');

            expect(consoleMock.error).toHaveBeenCalledTimes(1);
            expect(consoleMock.warn).toHaveBeenCalledTimes(1);
            expect(consoleMock.info).not.toHaveBeenCalled();
        });

        test('respects INFO level', () => {
            logger._logLevel = LOG_LEVELS.INFO;

            logger.error('error');
            logger.warn('warn');
            logger.info('info');
            logger.debug('debug');

            expect(consoleMock.error).toHaveBeenCalledTimes(1);
            expect(consoleMock.warn).toHaveBeenCalledTimes(1);
            expect(consoleMock.info).toHaveBeenCalledTimes(1);
            expect(consoleMock.log).not.toHaveBeenCalled();
        });

        test('NONE level suppresses all logs', () => {
            logger._logLevel = LOG_LEVELS.NONE;

            logger.error('error');
            logger.warn('warn');
            logger.info('info');
            logger.debug('debug');
            logger.trace('trace');

            expect(consoleMock.error).not.toHaveBeenCalled();
            expect(consoleMock.warn).not.toHaveBeenCalled();
            expect(consoleMock.info).not.toHaveBeenCalled();
            expect(consoleMock.log).not.toHaveBeenCalled();
        });
    });

    describe('enabled/disabled', () => {
        test('disabled logger does not log', () => {
            logger._enabled = false;
            logger._logLevel = LOG_LEVELS.TRACE;

            logger.error('error');
            logger.warn('warn');
            logger.info('info');

            expect(consoleMock.error).not.toHaveBeenCalled();
            expect(consoleMock.warn).not.toHaveBeenCalled();
            expect(consoleMock.info).not.toHaveBeenCalled();
        });
    });

    describe('child logger', () => {
        test('creates child logger with combined name', () => {
            const child = logger.child('SubModule');
            expect(child.moduleName).toBe('TestModule:SubModule');
        });
    });

    describe('logObject', () => {
        test('logs object with groupCollapsed', () => {
            logger.logObject('TestObject', { a: 1 });
            expect(consoleMock.groupCollapsed).toHaveBeenCalled();
            expect(consoleMock.dir).toHaveBeenCalled();
            expect(consoleMock.groupEnd).toHaveBeenCalled();
        });
    });

    describe('time/timeEnd', () => {
        test('calls console.time and timeEnd', () => {
            logger.time('operation');
            logger.timeEnd('operation');
            expect(consoleMock.time).toHaveBeenCalled();
            expect(consoleMock.timeEnd).toHaveBeenCalled();
        });
    });
});

describe('LoggerFactory', () => {
    beforeEach(() => {
        localStorageMock.clear();
        jest.clearAllMocks();
        // Clear instances
        LoggerFactory._instances = new Map();
    });

    describe('getLogger', () => {
        test('returns a logger instance', () => {
            const logger = LoggerFactory.getLogger('TestModule');
            expect(logger).toBeInstanceOf(DebugLogger);
        });

        test('returns same instance for same module name', () => {
            const logger1 = LoggerFactory.getLogger('TestModule');
            const logger2 = LoggerFactory.getLogger('TestModule');
            expect(logger1).toBe(logger2);
        });

        test('returns different instances for different modules', () => {
            const logger1 = LoggerFactory.getLogger('Module1');
            const logger2 = LoggerFactory.getLogger('Module2');
            expect(logger1).not.toBe(logger2);
        });
    });

    describe('setLogLevel', () => {
        test('updates log level for all loggers', () => {
            const logger1 = LoggerFactory.getLogger('Module1');
            const logger2 = LoggerFactory.getLogger('Module2');

            LoggerFactory.setLogLevel('ERROR');

            expect(logger1._logLevel).toBe(LOG_LEVELS.ERROR);
            expect(logger2._logLevel).toBe(LOG_LEVELS.ERROR);
        });

        test('saves level to localStorage', () => {
            LoggerFactory.setLogLevel('DEBUG');
            expect(localStorageMock.setItem).toHaveBeenCalledWith(
                'visual-mapper-log-level',
                'DEBUG'
            );
        });

        test('handles invalid level gracefully', () => {
            LoggerFactory.setLogLevel('INVALID');
            expect(consoleMock.error).toHaveBeenCalled();
        });
    });

    describe('setEnabled', () => {
        test('updates enabled state for all loggers', () => {
            const logger1 = LoggerFactory.getLogger('Module1');
            const logger2 = LoggerFactory.getLogger('Module2');

            LoggerFactory.setEnabled(false);

            expect(logger1._enabled).toBe(false);
            expect(logger2._enabled).toBe(false);
        });

        test('saves state to localStorage', () => {
            LoggerFactory.setEnabled(false);
            expect(localStorageMock.setItem).toHaveBeenCalledWith(
                'visual-mapper-debug',
                'false'
            );
        });
    });

    describe('getLogLevel', () => {
        test('returns current log level name', () => {
            const logger = LoggerFactory.getLogger('Test');
            logger._logLevel = LOG_LEVELS.DEBUG;

            const level = LoggerFactory.getLogLevel();
            expect(level).toBe('DEBUG');
        });
    });
});

describe('window.vmDebug helper', () => {
    test('exposes setLevel function', () => {
        expect(typeof window.vmDebug.setLevel).toBe('function');
    });

    test('exposes enable function', () => {
        expect(typeof window.vmDebug.enable).toBe('function');
    });

    test('exposes disable function', () => {
        expect(typeof window.vmDebug.disable).toBe('function');
    });

    test('exposes getLevel function', () => {
        expect(typeof window.vmDebug.getLevel).toBe('function');
    });

    test('exposes help function', () => {
        expect(typeof window.vmDebug.help).toBe('function');
    });
});
