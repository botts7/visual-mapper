/**
 * Flow Wizard Step 2 - App Selection
 * Visual Mapper v0.0.5
 *
 * Handles app list loading, icon detection, system app filtering, and app search
 */

import { showToast } from './toast.js?v=0.4.0-beta.2.4';

// Helper to get API base
function getApiBase() {
    return window.API_BASE || '/api';
}

let activeWizard = null;

/**
 * Load Step 2: App Selection
 * @param {Object} wizard - FlowWizard instance for state access
 * @returns {Promise<void>}
 */
export async function loadStep(wizard) {
    console.log('[Step2] Loading App Selection');
    activeWizard = wizard;

    // Reset refresh flags for new step load
    resetRefreshFlags();

    const appList = document.getElementById('appList');

    if (!wizard.selectedDevice) {
        showToast('No device selected', 'error');
        wizard.currentStep = 1;
        wizard.updateUI();
        return;
    }

    try {
        const response = await fetch(`${getApiBase()}/adb/apps/${wizard.selectedDevice}`);
        if (!response.ok) throw new Error('Failed to fetch apps');

        const data = await response.json();
        const apps = data.apps || [];
        console.log('[Step2] Apps loaded:', apps.length);

        if (apps.length === 0) {
            appList.innerHTML = `<div class="empty-state">No apps found on device</div>`;
            return;
        }

        // Sort apps alphabetically by label
        apps.sort((a, b) => {
            const labelA = (a.label || a.package).toLowerCase();
            const labelB = (b.label || b.package).toLowerCase();
            return labelA.localeCompare(labelB);
        });

        // Render app grid
        appList.className = 'app-grid';
        const iconBase = `${getApiBase()}/adb/app-icon/${encodeURIComponent(wizard.selectedDevice)}`;

        appList.innerHTML = apps.map(app => {
            const iconUrl = `${iconBase}/${encodeURIComponent(app.package)}`;
            const isSystem = app.is_system || false;
            return `
            <div class="app-item" data-package="${app.package}" data-label="${app.label || app.package}" data-is-system="${isSystem}">
                <img class="app-icon" src="${iconUrl}"
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
                     data-package="${app.package}"
                     alt="${app.label || app.package}">
                <div class="app-icon-fallback" style="display: none;">📱</div>
                <div class="app-label">${app.label || app.package}</div>
                <div class="app-package">${app.package}</div>
                <div class="app-icon-source" style="display: none; font-size: 9px; color: var(--text-secondary); margin-top: 2px; font-family: monospace;">
                    Loading...
                </div>
            </div>
        `;
        }).join('');

        // Setup filtering
        setupFiltering(wizard);

        // Handle app selection
        setupAppSelection(wizard, apps);

        // Setup icon source toggle
        setupIconSourceToggle(wizard, iconBase);

        // Setup refetch button
        setupRefetchButton(wizard);

        // Detect icon sources asynchronously
        detectIconSources(iconBase);

        // Trigger background app name prefetch
        prefetchAppNames(wizard);

        // Also trigger icon prefetch in background
        fetch(`${getApiBase()}/adb/prefetch-icons/${encodeURIComponent(wizard.selectedDevice)}`, {
            method: 'POST'
        }).then(() => console.log('[Step2] Icon prefetch triggered'))
          .catch(() => {});

        // Start queue stats polling to auto-refresh icons/names when fetching completes
        startQueueStatsPolling(wizard);

    } catch (error) {
        console.error('[Step2] Error loading apps:', error);
        appList.innerHTML = `
            <div class="error-state">
                <p>Error loading apps: ${error.message}</p>
            </div>
        `;
    }
}

/**
 * Setup app filtering (search + system apps)
 */
function setupFiltering(wizard) {
    const filterApps = () => {
        const search = (document.getElementById('appSearch')?.value || '').toLowerCase();
        document.querySelectorAll('.app-item').forEach(item => {
            const label = item.dataset.label.toLowerCase();
            const pkg = item.dataset.package.toLowerCase();
            const isSystem = item.dataset.isSystem === 'true';

            const searchMatches = !search || label.includes(search) || pkg.includes(search);
            const systemFilter = !wizard.hideSystemApps || !isSystem;

            item.style.display = (searchMatches && systemFilter) ? '' : 'none';
        });
    };

    // Search input
    const searchInput = document.getElementById('appSearch');
    if (searchInput) {
        searchInput.addEventListener('input', filterApps);
    }

    // System apps toggle
    const systemAppsBtn = document.getElementById('btnToggleSystemApps');
    if (systemAppsBtn) {
        filterApps(); // Apply initial filter
        systemAppsBtn.addEventListener('click', () => {
            wizard.hideSystemApps = !wizard.hideSystemApps;
            systemAppsBtn.textContent = wizard.hideSystemApps ? '🛠️ Hide System Apps' : '🛠️ Show System Apps';
            filterApps();
        });
    }
}

/**
 * Setup app selection handlers
 */
function setupAppSelection(wizard, apps) {
    document.querySelectorAll('.app-item').forEach((item, index) => {
        item.addEventListener('click', async () => {
            document.querySelectorAll('.app-item').forEach(i => i.classList.remove('selected'));
            item.classList.add('selected');

            const appIndex = Array.from(document.querySelectorAll('.app-item')).indexOf(item);
            wizard.selectedApp = apps[appIndex];
            console.log('[Step2] App selected:', wizard.selectedApp);

            // Load navigation graph data if available
            await loadNavigationData(wizard, wizard.selectedApp.package);

            // Dispatch tutorial event
            window.dispatchEvent(new CustomEvent('tutorial:wizard-app-selected', {
                detail: { app: wizard.selectedApp }
            }));
        });
    });
}

/**
 * Load navigation graph data for the selected app
 * Shows screen count and navigation info if the Android app has learned this app's navigation
 */
async function loadNavigationData(wizard, packageName) {
    const navInfoEl = document.getElementById('navigationInfo');

    // Create navigation info panel if it doesn't exist
    let navPanel = navInfoEl;
    if (!navPanel) {
        const appList = document.getElementById('appList');
        navPanel = document.createElement('div');
        navPanel.id = 'navigationInfo';
        navPanel.className = 'navigation-info-panel';
        appList.parentNode.insertBefore(navPanel, appList);
    }

    navPanel.innerHTML = '<div class="nav-loading">🔍 Checking navigation data...</div>';
    navPanel.style.display = 'block';

    try {
        const response = await fetch(`${getApiBase()}/navigation/${encodeURIComponent(packageName)}/stats?allow_missing=1`);

        if (!response.ok) {
            // No navigation data for this app
            navPanel.innerHTML = `
                <div class="nav-no-data">
                    <span class="nav-icon">📱</span>
                    <span class="nav-text">No navigation data yet</span>
                    <span class="nav-hint">The Android app will learn navigation as you create flows</span>
                </div>
            `;
            wizard.navigationGraph = null;
            return;
        }

        const data = await response.json();
        const stats = data.stats;
        if (!stats) {
            navPanel.innerHTML = `
                <div class="nav-no-data">
                    <span class="nav-icon">📱</span>
                    <span class="nav-text">No navigation data yet</span>
                    <span class="nav-hint">The Android app will learn navigation as you create flows</span>
                </div>
            `;
            wizard.navigationGraph = null;
            return;
        }

        // Store navigation data for use in Step 3
        wizard.navigationStats = stats;

        // Also load full graph for screen lookups
        const graphResponse = await fetch(`${getApiBase()}/navigation/${encodeURIComponent(packageName)}`);
        if (graphResponse.ok) {
            const graphData = await graphResponse.json();
            wizard.navigationGraph = graphData.graph;
        }

        console.log('[Step2] Navigation data loaded:', stats);

        navPanel.innerHTML = `
            <div class="nav-data-found">
                <span class="nav-icon">🗺️</span>
                <span class="nav-title">Navigation Data Available</span>
                <div class="nav-stats">
                    <span class="nav-stat">
                        <span class="stat-value">${stats.screen_count}</span>
                        <span class="stat-label">Screens</span>
                    </span>
                    <span class="nav-stat">
                        <span class="stat-value">${stats.transition_count}</span>
                        <span class="stat-label">Transitions</span>
                    </span>
                    ${stats.home_screen_id ? `
                    <span class="nav-stat home">
                        <span class="stat-value">✓</span>
                        <span class="stat-label">Home Screen</span>
                    </span>
                    ` : ''}
                </div>
                <span class="nav-hint">Navigation context will be shown during recording</span>
            </div>
        `;

    } catch (error) {
        console.warn('[Step2] Error loading navigation data:', error);
        navPanel.innerHTML = `
            <div class="nav-no-data">
                <span class="nav-icon">📱</span>
                <span class="nav-text">No navigation data yet</span>
                <span class="nav-hint">The Android app will learn navigation as you create flows</span>
            </div>
        `;
        wizard.navigationGraph = null;
    }
}

/**
 * Setup icon source toggle button
 */
function setupIconSourceToggle(wizard, iconBase) {
    const toggleBtn = document.getElementById('btnToggleIconSources');
    const statusPanel = document.getElementById('iconFetchingStatus');

    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            wizard.showIconSources = !wizard.showIconSources;
            toggleBtn.textContent = wizard.showIconSources ? '🔍 Hide Icon Sources' : '🔍 Show Icon Sources';

            document.querySelectorAll('.app-icon-source').forEach(label => {
                label.style.display = wizard.showIconSources ? 'block' : 'none';
            });

            if (statusPanel) {
                statusPanel.style.display = wizard.showIconSources ? 'block' : 'none';
            }

            if (wizard.showIconSources) {
                startQueueStatsPolling(wizard);
            } else {
                stopQueueStatsPolling(wizard);
            }
        });
    }
}

/**
 * Setup refetch button
 */
function setupRefetchButton(wizard) {
    const refetchBtn = document.getElementById('btnRefetchIcons');
    if (refetchBtn) {
        refetchBtn.addEventListener('click', async () => {
            await refetchAllIcons(wizard);
        });
    }
}

/**
 * Detect icon sources by checking headers
 */
async function detectIconSources(iconBase) {
    const iconImages = document.querySelectorAll('.app-icon');
    const batchSize = 10;
    const packages = Array.from(iconImages).map(img => img.dataset.package).filter(Boolean);

    for (let i = 0; i < packages.length; i += batchSize) {
        const batch = packages.slice(i, i + batchSize);

        await Promise.all(batch.map(async (packageName) => {
            try {
                const iconUrl = `${iconBase}/${encodeURIComponent(packageName)}`;
                const response = await fetch(iconUrl);

                if (!response.ok) return;

                const iconSource = response.headers.get('X-Icon-Source');
                const img = Array.from(iconImages).find(el => el.dataset.package === packageName);
                const sourceLabel = img?.parentElement.querySelector('.app-icon-source');

                if (!sourceLabel) return;

                let source = 'Unknown';
                let color = 'var(--text-secondary)';

                switch (iconSource) {
                    case 'device-scraper':
                        source = '📱 Device Scraper';
                        color = '#8b5cf6';
                        break;
                    case 'playstore':
                        source = '🏪 Play Store';
                        color = '#3b82f6';
                        break;
                    case 'apk-extraction':
                        source = '📦 APK Extraction';
                        color = '#22c55e';
                        break;
                    case 'svg-placeholder':
                        source = '⚪ SVG Placeholder';
                        color = '#94a3b8';
                        break;
                    default:
                        source = `❓ ${iconSource || 'Unknown'}`;
                        break;
                }

                sourceLabel.textContent = source;
                sourceLabel.style.color = color;

            } catch (error) {
                console.debug(`[Step2] Failed to detect icon source for ${packageName}:`, error);
            }
        }));
    }

    console.log('[Step2] Icon source detection complete');
}

/**
 * Trigger background app name prefetch
 */
async function prefetchAppNames(wizard) {
    if (!wizard.selectedDevice) return;

    try {
        console.log('[Step2] Triggering app name prefetch...');
        const response = await fetch(`${getApiBase()}/adb/prefetch-app-names/${encodeURIComponent(wizard.selectedDevice)}`, {
            method: 'POST'
        });

        if (!response.ok) return;

        const result = await response.json();
        console.log(`[Step2] App name prefetch queued: ${result.queued_count} apps`);

    } catch (error) {
        console.debug('[Step2] App name prefetch error:', error);
    }
}

/**
 * Start polling queue stats
 */
function startQueueStatsPolling(wizard) {
    updateQueueStats();
    wizard.queueStatsInterval = setInterval(() => updateQueueStats(), 2000);
    console.log('[Step2] Started queue stats polling');
}

/**
 * Stop polling queue stats
 */
function stopQueueStatsPolling(wizard) {
    if (wizard.queueStatsInterval) {
        clearInterval(wizard.queueStatsInterval);
        wizard.queueStatsInterval = null;
        console.log('[Step2] Stopped queue stats polling');
    }
}

// Track previous queue state for detecting completion
let previousIconQueuePending = -1;
let previousAppNameQueuePending = -1;
let lastIconRefreshPending = -1;  // Track queue size at last refresh (for progressive updates)
let lastAppNameRefreshPending = -1;
let hasRefreshedIcons = false;  // Prevent multiple final refreshes per session
let hasRefreshedAppNames = false;
let wasIconWorkerRunning = false;  // Track if worker was running (for stuck detection)
let wasAppNameWorkerRunning = false;

/**
 * Reset refresh flags (call when step loads)
 */
export function resetRefreshFlags() {
    previousIconQueuePending = -1;
    previousAppNameQueuePending = -1;
    lastIconRefreshPending = -1;
    lastAppNameRefreshPending = -1;
    hasRefreshedIcons = false;
    hasRefreshedAppNames = false;
    wasIconWorkerRunning = false;
    wasAppNameWorkerRunning = false;
    console.log('[Step2] Reset refresh flags');
}

/**
 * Refresh all icon images by adding cache-buster
 * @param {boolean} finalRefresh - If true, this is the final refresh after queue completes
 */
function refreshIconImages(finalRefresh = false) {
    // Skip if we've done the final refresh (queue completed)
    if (hasRefreshedIcons && finalRefresh) {
        console.log('[Step2] Final icon refresh already done, skipping');
        return;
    }

    if (finalRefresh) {
        hasRefreshedIcons = true;
    }

    const cacheBust = Date.now();
    document.querySelectorAll('.app-icon').forEach(img => {
        const originalSrc = img.src.split('?')[0]; // Remove any existing cache buster
        img.src = `${originalSrc}?t=${cacheBust}`;
    });
    console.log('[Step2] Refreshed all icon images with cache buster');
}

/**
 * Refresh all app labels by re-fetching app names
 * @param {boolean} finalRefresh - If true, this is the final refresh after queue completes
 */
async function refreshAppNames(finalRefresh = false) {
    // Skip if we've done the final refresh (queue completed)
    if (hasRefreshedAppNames && finalRefresh) {
        console.log('[Step2] Final app names refresh already done, skipping');
        return;
    }

    if (finalRefresh) {
        hasRefreshedAppNames = true;
    }

    try {
        const deviceId = activeWizard?.selectedDevice || activeWizard?.selectedDeviceStableId;
        if (!deviceId) return;

        console.log('[Step2] Refreshing app names...');
        const response = await fetch(`${getApiBase()}/adb/apps/${encodeURIComponent(deviceId)}`);
        if (!response.ok) return;

        const data = await response.json();
        const apps = data.apps || [];

        // Update app labels in the DOM
        let updatedCount = 0;
        apps.forEach(app => {
            const appItem = document.querySelector(`.app-item[data-package="${app.package}"]`);
            if (appItem && app.label && app.label !== app.package) {
                const labelEl = appItem.querySelector('.app-label');
                if (labelEl && labelEl.textContent !== app.label) {
                    labelEl.textContent = app.label;
                    appItem.dataset.label = app.label;
                    updatedCount++;
                }
            }
        });

        console.log(`[Step2] App names refreshed, updated ${updatedCount} labels`);
    } catch (error) {
        console.debug('[Step2] Failed to refresh app names:', error);
    }
}

/**
 * Update queue stats display
 */
async function updateQueueStats() {
    // Icon queue stats
    try {
        const response = await fetch(`${getApiBase()}/adb/icon-queue-stats`);
        if (!response.ok) return;

        const stats = await response.json();
        const statusIcon = document.getElementById('fetchingStatusIcon');
        const statusText = document.getElementById('fetchingStatusText');

        if (!statusIcon || !statusText) return;

        const { queue_size, processing_count, is_running } = stats;
        const totalPending = queue_size + processing_count;

        if (totalPending === 0) {
            statusIcon.textContent = '✅';
            statusText.textContent = 'All icons fetched';
            statusText.style.color = '#22c55e';

            // Final refresh when queue completes
            if (previousIconQueuePending > 0) {
                console.log('[Step2] Icon fetching completed, final refresh...');
                setTimeout(() => refreshIconImages(true), 500);
            }
        } else {
            // Check if worker is stuck (items in queue but not processing and not running)
            if (queue_size > 0 && processing_count === 0 && !is_running) {
                statusIcon.textContent = '⚠️';
                statusText.textContent = `Worker stopped (${queue_size} queued) - Click Refetch`;
                statusText.style.color = '#f59e0b';

                // Trigger refresh when worker BECOMES stuck
                if (wasIconWorkerRunning) {
                    console.log('[Step2] Icon worker became stuck, refreshing any fetched icons...');
                    setTimeout(() => refreshIconImages(false), 500);
                }
            } else {
                statusIcon.textContent = '⏳';
                statusText.textContent = `Fetching icons... (${totalPending} remaining, ${processing_count} in progress)`;
                statusText.style.color = '#3b82f6';

                // Periodic refresh while fetching - refresh every ~3 icons fetched
                // (Backend has 0.5s delay between fetches, poll is 2s, so ~4 max per poll)
                // Use lastIconRefreshPending to accumulate across multiple polls
                if (lastIconRefreshPending < 0) {
                    lastIconRefreshPending = totalPending; // Initialize on first poll with pending items
                }
                if (lastIconRefreshPending - totalPending >= 3) {
                    console.log(`[Step2] Progress: ${lastIconRefreshPending - totalPending} icons fetched since last refresh, refreshing...`);
                    refreshIconImages(false);
                    lastIconRefreshPending = totalPending; // Reset counter after refresh
                }
            }
        }

        // Track running state for stuck detection
        wasIconWorkerRunning = is_running || processing_count > 0;
        previousIconQueuePending = totalPending;

    } catch (error) {
        console.debug('[Step2] Failed to fetch icon queue stats:', error);
    }

    // App name queue stats
    try {
        const response = await fetch(`${getApiBase()}/adb/app-name-queue-stats`);
        if (!response.ok) return;

        const stats = await response.json();
        const statusIcon = document.getElementById('appNameStatusIcon');
        const statusText = document.getElementById('appNameStatusText');

        if (!statusIcon || !statusText) return;

        const { queue_size, processing_count, completed_count, total_requested, progress_percentage, is_running } = stats;
        const totalPending = queue_size + processing_count;

        if (total_requested === 0) {
            statusIcon.textContent = '⏱️';
            statusText.textContent = 'No app name fetch requested';
            statusText.style.color = '#94a3b8';
        } else if (totalPending === 0 && completed_count > 0) {
            statusIcon.textContent = '✅';
            statusText.textContent = `All app names fetched (${completed_count} apps)`;
            statusText.style.color = '#22c55e';

            // Final refresh when queue completes
            if (previousAppNameQueuePending > 0) {
                console.log('[Step2] App name fetching completed, final refresh...');
                setTimeout(() => refreshAppNames(true), 500);
            }
        } else if (totalPending > 0) {
            // Check if worker is stuck
            if (queue_size > 0 && processing_count === 0 && is_running === false) {
                statusIcon.textContent = '⚠️';
                statusText.textContent = `Name worker stopped (${queue_size} queued)`;
                statusText.style.color = '#f59e0b';

                // Trigger refresh when worker BECOMES stuck
                if (wasAppNameWorkerRunning) {
                    console.log('[Step2] App name worker became stuck, refreshing any fetched names...');
                    setTimeout(() => refreshAppNames(false), 500);
                }
            } else {
                statusIcon.textContent = '📝';
                statusText.textContent = `Fetching app names... ${progress_percentage}% (${completed_count}/${total_requested}, ${processing_count} in progress)`;
                statusText.style.color = '#3b82f6';

                // Periodic refresh while fetching - refresh every ~5 names fetched
                // (Backend has 1.5s delay between fetches, poll is 2s, so ~1 per poll)
                // Use lastAppNameRefreshPending to accumulate across multiple polls
                if (lastAppNameRefreshPending < 0) {
                    lastAppNameRefreshPending = totalPending; // Initialize on first poll with pending items
                }
                if (lastAppNameRefreshPending - totalPending >= 5) {
                    console.log(`[Step2] Progress: ${lastAppNameRefreshPending - totalPending} names fetched since last refresh, refreshing...`);
                    refreshAppNames(false);
                    lastAppNameRefreshPending = totalPending; // Reset counter after refresh
                }
            }
        }

        // Track running state for stuck detection
        wasAppNameWorkerRunning = is_running || processing_count > 0;
        previousAppNameQueuePending = totalPending;

    } catch (error) {
        console.debug('[Step2] Failed to fetch app name queue stats:', error);
    }
}

/**
 * Refetch all app icons
 */
async function refetchAllIcons(wizard) {
    if (!wizard.selectedDevice) {
        showToast('No device selected', 'error');
        return;
    }

    const refetchBtn = document.getElementById('btnRefetchIcons');
    const originalText = refetchBtn?.textContent;

    // Reset refresh flags so we can refresh again when fetching completes
    hasRefreshedIcons = false;
    hasRefreshedAppNames = false;
    wasIconWorkerRunning = false;
    wasAppNameWorkerRunning = false;
    console.log('[Step2] Reset refresh flags for manual refetch');

    try {
        if (refetchBtn) {
            refetchBtn.disabled = true;
            refetchBtn.textContent = '⏳ Refetching...';
        }

        // Start both icon and app name prefetch in parallel
        const [iconResponse, appNameResponse] = await Promise.all([
            fetch(`${getApiBase()}/adb/prefetch-icons/${encodeURIComponent(wizard.selectedDevice)}`, { method: 'POST' }),
            fetch(`${getApiBase()}/adb/prefetch-app-names/${encodeURIComponent(wizard.selectedDevice)}`, { method: 'POST' })
        ]);

        if (!iconResponse.ok) throw new Error('Icon refetch failed');

        const iconResult = await iconResponse.json();
        let message = `Queued ${iconResult.apps_queued} icons`;

        if (appNameResponse.ok) {
            const appNameResult = await appNameResponse.json();
            message += ` and ${appNameResult.queued_count || 0} names`;
        }

        showToast(message, 'success');
        updateQueueStats();

        setTimeout(() => {
            const iconBase = `${getApiBase()}/adb/app-icon/${encodeURIComponent(wizard.selectedDevice)}`;
            detectIconSources(iconBase);
        }, 3000);

    } catch (error) {
        console.error('[Step2] Refetch failed:', error);
        showToast('Failed to refetch icons', 'error');
    } finally {
        if (refetchBtn) {
            refetchBtn.disabled = false;
            refetchBtn.textContent = originalText || '🔄 Refetch All Icons';
        }
    }
}

/**
 * Validate Step 2
 * @param {Object} wizard - FlowWizard instance
 * @returns {boolean}
 */
export function validateStep(wizard) {
    if (!wizard.selectedApp) {
        alert('Please select an app');
        return false;
    }
    return true;
}

/**
 * Get Step 2 data
 * @param {Object} wizard - FlowWizard instance
 * @returns {Object}
 */
export function getStepData(wizard) {
    return {
        selectedApp: wizard.selectedApp,
        recordMode: wizard.recordMode
    };
}

/**
 * Cleanup when leaving Step 2
 */
export function cleanup(wizard) {
    stopQueueStatsPolling(wizard);
    if (activeWizard === wizard) {
        activeWizard = null;
    }
}

export default { loadStep, validateStep, getStepData, cleanup };
