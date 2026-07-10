/**
 * Storage Utils Module Tests
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
        get length() {
            return Object.keys(store).length;
        },
        key: jest.fn((i) => Object.keys(store)[i] || null),
    };
})();

Object.defineProperty(window, 'localStorage', {
    value: localStorageMock,
});

// Import after mocking
const StorageUtils = require('../www/js/modules/storage-utils.js').default ||
                     require('../www/js/modules/storage-utils.js').StorageUtils;

describe('StorageUtils', () => {
    beforeEach(() => {
        localStorageMock.clear();
        jest.clearAllMocks();
    });

    describe('getItem', () => {
        test('returns value when key exists', () => {
            localStorageMock.setItem('test-key', 'test-value');
            const result = StorageUtils.getItem('test-key');
            expect(result).toBe('test-value');
        });

        test('returns defaultValue when key does not exist', () => {
            const result = StorageUtils.getItem('nonexistent', 'default');
            expect(result).toBe('default');
        });

        test('returns null when key does not exist and no default', () => {
            const result = StorageUtils.getItem('nonexistent');
            expect(result).toBeNull();
        });
    });

    describe('setItem', () => {
        test('stores value in localStorage', () => {
            const result = StorageUtils.setItem('key', 'value');
            expect(result).toBe(true);
            expect(localStorageMock.setItem).toHaveBeenCalledWith('key', 'value');
        });

        test('returns false when localStorage throws', () => {
            localStorageMock.setItem.mockImplementationOnce(() => {
                throw new Error('QuotaExceededError');
            });
            const result = StorageUtils.setItem('key', 'value');
            expect(result).toBe(false);
        });
    });

    describe('getJSON', () => {
        test('parses JSON value correctly', () => {
            localStorageMock.setItem('json-key', JSON.stringify({ a: 1, b: 2 }));
            const result = StorageUtils.getJSON('json-key');
            expect(result).toEqual({ a: 1, b: 2 });
        });

        test('returns defaultValue for invalid JSON', () => {
            localStorageMock.setItem('bad-json', 'not valid json');
            const result = StorageUtils.getJSON('bad-json', { default: true });
            expect(result).toEqual({ default: true });
        });

        test('returns defaultValue when key does not exist', () => {
            const result = StorageUtils.getJSON('nonexistent', []);
            expect(result).toEqual([]);
        });
    });

    describe('setJSON', () => {
        test('stores object as JSON string', () => {
            const obj = { name: 'test', count: 42 };
            const result = StorageUtils.setJSON('obj-key', obj);
            expect(result).toBe(true);
            expect(localStorageMock.setItem).toHaveBeenCalledWith(
                'obj-key',
                JSON.stringify(obj)
            );
        });

        test('stores array as JSON string', () => {
            const arr = [1, 2, 3];
            const result = StorageUtils.setJSON('arr-key', arr);
            expect(result).toBe(true);
            expect(localStorageMock.setItem).toHaveBeenCalledWith(
                'arr-key',
                JSON.stringify(arr)
            );
        });
    });

    describe('removeItem', () => {
        test('removes item from localStorage', () => {
            localStorageMock.setItem('to-remove', 'value');
            const result = StorageUtils.removeItem('to-remove');
            expect(result).toBe(true);
            expect(localStorageMock.removeItem).toHaveBeenCalledWith('to-remove');
        });
    });

    describe('isAvailable', () => {
        test('returns true when localStorage works', () => {
            const result = StorageUtils.isAvailable();
            expect(result).toBe(true);
        });

        test('returns false when localStorage throws', () => {
            const originalSetItem = localStorageMock.setItem;
            localStorageMock.setItem = jest.fn(() => {
                throw new Error('SecurityError');
            });

            const result = StorageUtils.isAvailable();
            expect(result).toBe(false);

            localStorageMock.setItem = originalSetItem;
        });
    });

    describe('clear', () => {
        test('clears all items from localStorage', () => {
            localStorageMock.setItem('key1', 'value1');
            localStorageMock.setItem('key2', 'value2');

            const result = StorageUtils.clear();
            expect(result).toBe(true);
            expect(localStorageMock.clear).toHaveBeenCalled();
        });
    });
});
