/**
 * Playwright Screenshot Capture for User Guide
 *
 * This script captures screenshots of the Visual Mapper UI for the interactive tutorial.
 * Run with: npx playwright test scripts/capture-guide-screenshots.js
 * Or: node scripts/capture-guide-screenshots.js (if playwright is installed globally)
 *
 * Prerequisites:
 * - Backend server running on localhost:8765
 * - npm install playwright (in frontend directory)
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

// Configuration
const BASE_URL = process.env.BASE_URL || 'http://localhost:8765';
const OUTPUT_DIR = path.join(__dirname, '..', 'frontend', 'www', 'images', 'guide');
const VIEWPORT = { width: 1280, height: 800 };

// Screenshot definitions
const SCREENSHOTS = [
    {
        name: '01-devices.png',
        url: '/devices.html',
        description: 'Devices page - Connect your Android device',
        waitFor: '.card, .device-list',
        actions: []
    },
    {
        name: '02-pairing.png',
        url: '/devices.html',
        description: 'Pairing dialog with code input',
        waitFor: '.card',
        // Simulate a connect button click to show pairing UI
        actions: [
            { type: 'click', selector: '[data-action="connect"], .btn-primary', optional: true }
        ],
        delay: 1000
    },
    {
        name: '03-flow-start.png',
        url: '/flow-wizard.html',
        description: 'Flow Wizard - Step 1',
        waitFor: '.wizard-container, .container',
        actions: []
    },
    {
        name: '04-select-app.png',
        url: '/flow-wizard.html',
        description: 'Flow Wizard - App selection',
        waitFor: '.wizard-container',
        actions: [
            // Try to advance to step 2 if possible
            { type: 'click', selector: '.next-step, [data-step="2"]', optional: true }
        ],
        delay: 500
    },
    {
        name: '05-record-nav.png',
        url: '/flow-wizard.html',
        description: 'Flow Wizard - Navigation recording canvas',
        waitFor: '.wizard-container',
        actions: [],
        // Capture with highlighted canvas area
        highlight: '.canvas-container, .screenshot-container'
    },
    {
        name: '06-select-element.png',
        url: '/flow-wizard.html',
        description: 'Flow Wizard - Element selection panel',
        waitFor: '.wizard-container',
        actions: [],
        highlight: '.element-panel, .element-tree'
    },
    {
        name: '07-sensors.png',
        url: '/sensors.html',
        description: 'Sensors page - Created sensors',
        waitFor: '.card, .sensor-list',
        actions: []
    }
];

async function ensureOutputDir() {
    if (!fs.existsSync(OUTPUT_DIR)) {
        fs.mkdirSync(OUTPUT_DIR, { recursive: true });
        console.log(`Created output directory: ${OUTPUT_DIR}`);
    }
}

async function waitForServer(maxRetries = 30) {
    const http = require('http');

    for (let i = 0; i < maxRetries; i++) {
        try {
            await new Promise((resolve, reject) => {
                const req = http.get(`${BASE_URL}/api/health`, (res) => {
                    if (res.statusCode === 200) {
                        resolve();
                    } else {
                        reject(new Error(`Status: ${res.statusCode}`));
                    }
                });
                req.on('error', reject);
                req.setTimeout(2000, () => {
                    req.destroy();
                    reject(new Error('Timeout'));
                });
            });
            console.log('Server is ready');
            return true;
        } catch (e) {
            console.log(`Waiting for server... (${i + 1}/${maxRetries})`);
            await new Promise(r => setTimeout(r, 1000));
        }
    }
    throw new Error('Server not available');
}

async function captureScreenshot(page, screenshot) {
    const { name, url, description, waitFor, actions, delay, highlight } = screenshot;

    console.log(`\nCapturing: ${name}`);
    console.log(`  URL: ${url}`);
    console.log(`  Description: ${description}`);

    try {
        // Navigate to page
        await page.goto(`${BASE_URL}${url}`, {
            waitUntil: 'networkidle',
            timeout: 30000
        });

        // Wait for key element
        if (waitFor) {
            try {
                await page.waitForSelector(waitFor, { timeout: 5000 });
            } catch (e) {
                console.log(`  Warning: ${waitFor} not found, continuing...`);
            }
        }

        // Execute any actions
        for (const action of actions || []) {
            try {
                if (action.type === 'click') {
                    const element = await page.$(action.selector);
                    if (element) {
                        await element.click();
                        console.log(`  Clicked: ${action.selector}`);
                    } else if (!action.optional) {
                        console.log(`  Warning: ${action.selector} not found`);
                    }
                }
            } catch (e) {
                if (!action.optional) {
                    console.log(`  Action failed: ${e.message}`);
                }
            }
        }

        // Additional delay if specified
        if (delay) {
            await page.waitForTimeout(delay);
        }

        // Add highlight if specified
        if (highlight) {
            await page.evaluate((selector) => {
                const el = document.querySelector(selector);
                if (el) {
                    el.style.outline = '3px solid #2196F3';
                    el.style.outlineOffset = '2px';
                }
            }, highlight);
        }

        // Capture screenshot
        const outputPath = path.join(OUTPUT_DIR, name);
        await page.screenshot({
            path: outputPath,
            fullPage: false
        });

        console.log(`  Saved: ${outputPath}`);
        return true;

    } catch (error) {
        console.error(`  Error: ${error.message}`);
        return false;
    }
}

async function main() {
    console.log('='.repeat(60));
    console.log('Visual Mapper - Guide Screenshot Capture');
    console.log('='.repeat(60));
    console.log(`Base URL: ${BASE_URL}`);
    console.log(`Output: ${OUTPUT_DIR}`);
    console.log(`Viewport: ${VIEWPORT.width}x${VIEWPORT.height}`);
    console.log('='.repeat(60));

    // Ensure output directory exists
    await ensureOutputDir();

    // Wait for server
    console.log('\nChecking server availability...');
    await waitForServer();

    // Launch browser
    console.log('\nLaunching browser...');
    const browser = await chromium.launch({
        headless: true
    });

    const context = await browser.newContext({
        viewport: VIEWPORT,
        deviceScaleFactor: 2  // Retina screenshots
    });

    const page = await context.newPage();

    // Capture each screenshot
    let success = 0;
    let failed = 0;

    for (const screenshot of SCREENSHOTS) {
        const result = await captureScreenshot(page, screenshot);
        if (result) {
            success++;
        } else {
            failed++;
        }
    }

    // Cleanup
    await browser.close();

    // Summary
    console.log('\n' + '='.repeat(60));
    console.log('Summary');
    console.log('='.repeat(60));
    console.log(`Total: ${SCREENSHOTS.length}`);
    console.log(`Success: ${success}`);
    console.log(`Failed: ${failed}`);
    console.log('='.repeat(60));

    process.exit(failed > 0 ? 1 : 0);
}

// Run if called directly
if (require.main === module) {
    main().catch(error => {
        console.error('Fatal error:', error);
        process.exit(1);
    });
}

module.exports = { captureScreenshot, SCREENSHOTS, main };
