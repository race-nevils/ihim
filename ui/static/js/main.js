/**
 * main.js — Application entry point.
 * Imports the kept modules, initializes the app, wires global listeners.
 */
import { startSystemMonitor, stopSystemMonitor, updateSystemMonitor } from './app.js';
import { desktopManager } from './desktop.js';
import { stopwatchManager } from './stopwatch.js';
import { initHealthEvents } from './health-dashboard.js';
import { initVaultEvents } from './vault.js';
import { initWorkspacesEvents } from './workspaces.js';
import { initRecorderEvents } from './recorder.js';
import { initSTTEvents } from './stt.js';
import { initAgentNodeEvents, openAgentNodeWindow } from './agentnode-manager.js';
import { initCalendarEvents, pushNewCalendarEvent, syncCalendar, toggleCalendarAddForm } from './calendar.js';
import { initGlobalEscapeHandler } from './a11y.js';
import './components/ihim-panel.js';
import './components/ihim-tabs.js';

function cleanupIntervals() {
    stopSystemMonitor();
    if (stopwatchManager?.stopAll) stopwatchManager.stopAll();
}

window.addEventListener('beforeunload', cleanupIntervals);
window.addEventListener('beforeunload', () => desktopManager.cleanup());

function initializeApp() {
    desktopManager.init();
    updateSystemMonitor();
    startSystemMonitor();
    stopwatchManager.init();

    // Widget event wiring (data loads ride the panel:open contract)
    initHealthEvents();
    initVaultEvents();
    initWorkspacesEvents();
    initRecorderEvents();
    initSTTEvents();
    initAgentNodeEvents();
    initCalendarEvents();

    // Global Escape handler (panels self-register via <ihim-panel>)
    initGlobalEscapeHandler();

    // agent node bar widget -> open panel
    document.getElementById('agentnode-widget')
        ?.addEventListener('click', openAgentNodeWindow);

    // Stopwatch spawn button
    document.querySelector('.stopwatch-spawn-btn')
        ?.addEventListener('click', () => stopwatchManager.spawn());

    // Calendar window buttons
    const calWin = document.getElementById('calendar-window');
    if (calWin) {
        calWin.querySelector('.calendar-refresh-btn')?.addEventListener('click', syncCalendar);
        calWin.querySelector('.calendar-add-btn')?.addEventListener('click', toggleCalendarAddForm);
        calWin.querySelector('.cal-create-btn')?.addEventListener('click', pushNewCalendarEvent);
        calWin.querySelector('.cal-cancel-btn')?.addEventListener('click', toggleCalendarAddForm);
    }
}

// Boot
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApp);
} else {
    initializeApp();
}
