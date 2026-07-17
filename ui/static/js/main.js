/**
 * main.js — Application entry point.
 * The UI is Web Components: every widget is a custom element that renders
 * its own markup and manages its own lifecycle (connected/disconnected,
 * panel:open/panel:close). Importing a component registers it; upgrades
 * initialize everything — no manual init calls.
 */
import { initGlobalEscapeHandler } from './a11y.js';

// Window base + tab system
import './components/ihim-panel.js';
import './components/ihim-tabs.js';

// Widget windows (IhimPanel subclasses)
import './components/ihim-stt.js';
import './components/ihim-recorder.js';
import './components/ihim-health.js';
import './components/ihim-vault.js';
import './components/ihim-agentnode.js';

// Standalone components
import './components/ihim-desktop.js';
import './components/ihim-stopwatch.js';
import './components/ihim-system-monitor.js';
import './components/ihim-agentnode-bar.js';

// Global Escape handler (windows self-register via IhimPanel)
initGlobalEscapeHandler();
