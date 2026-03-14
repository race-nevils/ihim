/**
 * main.js — Application entry point
 * Imports all modules, initializes the app, and wires up event listeners.
 */
import { API, showStatus, updateSystemMonitor, startSystemMonitor, stopSystemMonitor, updateWatcherStatus } from './app.js';
import { initializeWidgetResize, WorkspaceState } from './draggable.js';
import { desktopManager } from './desktop-manager.js';
import { stopwatchManager } from './stopwatch.js';
import { flightPath } from './flight-path.js';
import { initChatEvents, toggleChatWindow } from './chat-manager.js';
import { initSlashEvents } from './slash-commands.js';
import { initStandardsLibraryEvents } from './standards-library.js';
import { initHealthEvents } from './health-dashboard.js';
import { initVaultEvents } from './vault-dashboard.js';
import { initMCEvents } from './terminal-manager.js';
import { initRecorderEvents } from './recorder.js';
import { initSTTEvents } from './stt.js';
import { pipelineObserver, closePipelineObserver } from './pipeline-observer.js';
import { syncCalendar, toggleCalendarAddForm, pushNewCalendarEvent } from './calendar.js';
import { initGlobalEscapeHandler } from './a11y.js';
import './components/ihim-panel.js';
import './components/ihim-tabs.js';

// =====================
// Global Cleanup
// =====================

function cleanupIntervals() {
    stopSystemMonitor();
    if (flightPath?.stopHealthPolling) flightPath.stopHealthPolling();
    if (pipelineObserver?.stopPolling) pipelineObserver.stopPolling();
    if (WorkspaceState?.stopAutoSave) WorkspaceState.stopAutoSave();
    if (stopwatchManager?.stopAll) stopwatchManager.stopAll();
}

window.addEventListener('beforeunload', cleanupIntervals);
window.addEventListener('beforeunload', () => desktopManager.cleanup());

// =====================
// Load Actions & Init
// =====================

async function loadActions() {
    try {
        const res = await fetch(`${API}/api/actions`);
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        const data = await res.json();
        desktopManager.init(data.actions);
    } catch (err) {
        console.error('Failed to load actions:', err);
        showStatus('Failed to load actions - check console', 'error');
    }
}

function initializeApp() {
    loadActions();
    updateSystemMonitor();
    startSystemMonitor();
    updateWatcherStatus();
    setInterval(updateWatcherStatus, 5000);
    initializeWidgetResize();
    WorkspaceState.init();
    stopwatchManager.init();

    // Wire up event listeners (replacing inline onclick handlers)
    initChatEvents();
    initSlashEvents();
    initStandardsLibraryEvents();
    initHealthEvents();
    initVaultEvents();
    initMCEvents();
    initRecorderEvents();
    initSTTEvents();

    // Global Escape handler (individual windows self-register via <ihim-panel>)
    initGlobalEscapeHandler();

    // Bottom bar: Chat toggle
    document.querySelector('#bottom-bar [title="Brain Chat"]')
        ?.closest('.bar-widget')
        ?.addEventListener('click', toggleChatWindow);

    // Stopwatch spawn button
    document.querySelector('.stopwatch-spawn-btn')
        ?.addEventListener('click', () => stopwatchManager.spawn());

    // Calendar window buttons (event delegation)
    const calWin = document.getElementById('calendar-window');
    if (calWin) {
        calWin.querySelector('.calendar-refresh-btn')?.addEventListener('click', syncCalendar);
        calWin.querySelector('.calendar-add-btn')?.addEventListener('click', toggleCalendarAddForm);
        calWin.querySelector('.cal-create-btn')?.addEventListener('click', pushNewCalendarEvent);
        calWin.querySelector('.cal-cancel-btn')?.addEventListener('click', toggleCalendarAddForm);
    }

    // Flight path window buttons
    const fpWin = document.getElementById('flightpath-window');
    if (fpWin) {
        fpWin.querySelector('.fp-control-btn')?.addEventListener('click', () => flightPath.refresh());

        // Event delegation for flight path list interactions
        fpWin.querySelector('#fp-system-list')?.addEventListener('click', (e) => {
            const header = e.target.closest('.fp-list-header');
            if (header) {
                const id = header.dataset.id;
                const hasChildren = !header.querySelector('.no-children');
                if (hasChildren) flightPath.toggleGroup(id);
                else flightPath.selectItem(id);
            }
            const item = e.target.closest('.fp-list-item');
            if (item) flightPath.selectItem(item.dataset.id);
        });
    }

    // Standards library search
    const slWin = document.getElementById('standards-library-window');
    if (slWin) {
        slWin.querySelector('#standards-library-search-input')?.addEventListener('input', () => {
            import('./standards-library.js').then(m => m.filterStandardsLibraryModules());
        });
    }

    // Team modal close + spawn
    document.querySelector('#team-modal .close-btn')?.addEventListener('click', () => {
        import('./chat-manager.js').then(m => m.closeTeamModal());
    });
    document.querySelector('#team-modal .spawn-btn')?.addEventListener('click', () => {
        import('./chat-manager.js').then(m => m.spawnTeam());
    });

    // Agent team modal close + spawn
    document.querySelector('#agent-team-modal .close-btn')?.addEventListener('click', () => {
        import('./chat-manager.js').then(m => m.closeAgentTeamModal());
    });
    document.querySelector('.spawn-team-btn')?.addEventListener('click', () => {
        import('./chat-manager.js').then(m => m.spawnAgentTeam());
    });
}

// Boot
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApp);
} else {
    initializeApp();
}
