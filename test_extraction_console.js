/**
 * Browser Console Test Script for Text Extraction
 *
 * USAGE:
 * 1. Open browser console (F12)
 * 2. Copy this entire file and paste into console
 * 3. Run test commands to verify extraction
 *
 * Example:
 *   testExtraction("Updated: 22/12/25 5:29 pm", "regex", { regex_pattern: "(\\d{2}/\\d{2}/\\d{2})" })
 */

// Test helper function
async function testExtraction(text, method, params = {}) {
    console.log("=== Text Extraction Test ===");
    console.log("Input text:", text);
    console.log("Method:", method);
    console.log("Parameters:", params);

    const requestBody = {
        text: text,
        extraction_rule: {
            method: method,
            ...params
        }
    };

    try {
        const response = await fetch('/api/test/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        const result = await response.json();
        console.log("✅ Result:", result.extracted_value);
        console.log("Full response:", result);
        return result.extracted_value;
    } catch (error) {
        console.error("❌ Error:", error);
        return null;
    }
}

// Predefined test cases
const TEST_CASES = {
    datetime: {
        text: "Updated: 22/12/25 5:29 pm",
        tests: [
            {
                name: "Extract full datetime",
                method: "after",
                params: { after_text: "Updated: " },
                expected: "22/12/25 5:29 pm"
            },
            {
                name: "Extract date only",
                method: "regex",
                params: { regex_pattern: "(\\d{2}/\\d{2}/\\d{2})" },
                expected: "22/12/25"
            },
            {
                name: "Extract time only",
                method: "regex",
                params: { regex_pattern: "(\\d{1,2}:\\d{2}\\s*[ap]m)" },
                expected: "5:29 pm"
            }
        ]
    },
    battery: {
        text: "Battery: 94%",
        tests: [
            {
                name: "Extract numeric value",
                method: "numeric",
                params: {},
                expected: "94"
            },
            {
                name: "Extract with regex",
                method: "regex",
                params: { regex_pattern: "(\\d+)%" },
                expected: "94"
            },
            {
                name: "Extract after label",
                method: "after",
                params: { after_text: "Battery: ", remove_unit: true },
                expected: "94"
            }
        ]
    },
    wifi: {
        text: "Connected to WiFi: MyNetwork",
        tests: [
            {
                name: "Extract network name",
                method: "after",
                params: { after_text: "Connected to WiFi: " },
                expected: "MyNetwork"
            }
        ]
    }
};

// Run all tests for a category
async function runTests(category) {
    if (!TEST_CASES[category]) {
        console.error("Unknown category:", category);
        console.log("Available categories:", Object.keys(TEST_CASES));
        return;
    }

    const testCase = TEST_CASES[category];
    console.log(`\n====== Running ${category.toUpperCase()} tests ======`);
    console.log("Source text:", testCase.text);

    for (const test of testCase.tests) {
        console.log(`\n--- ${test.name} ---`);
        const result = await testExtraction(testCase.text, test.method, test.params);

        if (result === test.expected) {
            console.log("✅ PASS");
        } else {
            console.log("❌ FAIL");
            console.log("  Expected:", test.expected);
            console.log("  Got:", result);
        }
    }
}

// Run all tests
async function runAllTests() {
    for (const category of Object.keys(TEST_CASES)) {
        await runTests(category);
        await new Promise(resolve => setTimeout(resolve, 500)); // Small delay between categories
    }
}

console.log("✅ Text Extraction Test Helper Loaded!");
console.log("\nAvailable commands:");
console.log("  testExtraction(text, method, params) - Test single extraction");
console.log("  runTests('datetime') - Run datetime tests");
console.log("  runTests('battery') - Run battery tests");
console.log("  runTests('wifi') - Run wifi tests");
console.log("  runAllTests() - Run all test categories");
console.log("\nExample:");
console.log('  testExtraction("Updated: 22/12/25 5:29 pm", "regex", { regex_pattern: "(\\\\d{2}/\\\\d{2}/\\\\d{2})" })');
