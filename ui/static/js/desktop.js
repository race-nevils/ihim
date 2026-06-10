/**
 * desktop.js — Desktop tile grid: layout, drag-to-rearrange, activation.
 *
 * Tiles are a frontend constant — the old /api/actions round-trip (and its
 * POST /api/actions/{id} exec endpoint) is gone. Every tile opens a panel
 * via a static import; drag uses Pointer Events + setPointerCapture with a
 * 5px click/drag threshold.
 */

import { escapeHtml, getIcon, restartServer, showStatus } from './app.js';
import { toggleSTTWindow } from './stt.js';
import { toggleRecorderWindow } from './recorder.js';
import { toggleWorkspacesWindow } from './workspaces.js';
import { toggleVaultWindow } from './vault.js';
import { openCalendarWindow } from './calendar.js';
import { openHealthWindow } from './health-dashboard.js';
import { stopwatchManager } from './stopwatch.js';

// One entry per desktop tile, in default-layout order.
export const TILES = [
    { id: 'stt', name: 'STT Dictation', icon: 'mic', run: toggleSTTWindow },
    { id: 'workspaces', name: 'Workspaces', icon: 'git-branch', run: toggleWorkspacesWindow },
    { id: 'meeting_recorder', name: 'Meeting Recorder', icon: 'mic', run: toggleRecorderWindow },
    { id: 'google_calendar', name: 'Google Calendar', icon: 'calendar', run: openCalendarWindow },
    { id: 'health', name: 'Health', icon: 'heart-pulse', run: openHealthWindow },
    { id: 'vault', name: 'Vault', icon: 'archive', run: toggleVaultWindow },
    { id: 'restart_server', name: 'Restart Server', icon: 'restart', run: restartServer },
];

export function runTile(id) {
    const tile = TILES.find(t => t.id === id);
    if (tile) tile.run();
    else if (id === 'stopwatch') {
        stopwatchManager.spawn();
        showStatus('Stopwatch spawned!', 'success');
    }
}

export const desktopManager = {
    icons: {},
    STORAGE_KEY: 'ihim_desktop_layout',
    isDragging: false,
    pendingIcon: null,
    startPos: { x: 0, y: 0 },
    offset: { x: 0, y: 0 },
    abortController: null,

    init() {
        this.cleanup();
        this.restoreLayout();
        this.render();
    },

    render() {
        this.abortController = new AbortController();
        const signal = this.abortController.signal;

        const grid = document.getElementById('actions-grid');
        grid.innerHTML = '';
        grid.className = 'desktop-grid';

        const GRID_SIZE = 120;
        const maxCols = Math.max(1, Math.floor((window.innerWidth - 40) / GRID_SIZE));
        let col = 0;

        for (const tile of TILES) {
            const icon = document.createElement('div');
            icon.className = 'desktop-icon';
            icon.dataset.actionId = tile.id;
            icon.setAttribute('role', 'button');
            icon.setAttribute('tabindex', '0');
            icon.setAttribute('aria-label', tile.name);

            const saved = this.icons[tile.id];
            const x = saved ? saved.x : 20 + ((col % maxCols) * GRID_SIZE);
            const y = saved ? saved.y : 20 + (Math.floor(col / maxCols) * GRID_SIZE);
            icon.style.left = x + 'px';
            icon.style.top = y + 'px';

            icon.innerHTML = `
                <div class="desktop-icon-image">${getIcon(tile.icon)}</div>
                <div class="desktop-icon-label">${escapeHtml(tile.name)}</div>
            `;

            icon.addEventListener('pointerdown', (e) => this._onPointerDown(e, icon), { signal });
            icon.addEventListener('pointermove', (e) => this._onPointerMove(e, icon), { signal });
            icon.addEventListener('pointerup', (e) => this._onPointerUp(e, tile.id, icon), { signal });
            icon.addEventListener('pointercancel', (e) => this._onPointerUp(e, tile.id, icon), { signal });
            icon.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); runTile(tile.id); }
            }, { signal });
            icon.addEventListener('dragstart', (e) => e.preventDefault(), { signal });

            grid.appendChild(icon);
            if (!saved) this.icons[tile.id] = { x, y };
            col++;
        }

        requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
        this.saveLayout();
    },

    _onPointerDown(e, icon) {
        if (e.button !== 0) return;
        e.preventDefault();
        icon.setPointerCapture(e.pointerId);
        this.startPos = { x: e.clientX, y: e.clientY };
        // style.left/top, not getBoundingClientRect (which includes transforms)
        const iconX = parseInt(icon.style.left) || 0;
        const iconY = parseInt(icon.style.top) || 0;
        this.offset = { x: e.clientX - iconX, y: e.clientY - iconY };
        this.pendingIcon = icon;
        this.isDragging = false;
    },

    _onPointerMove(e, icon) {
        if (!icon.hasPointerCapture(e.pointerId)) return;
        if (!this.pendingIcon) return;

        const dx = Math.abs(e.clientX - this.startPos.x);
        const dy = Math.abs(e.clientY - this.startPos.y);
        if (!this.isDragging && (dx > 5 || dy > 5)) {
            this.isDragging = true;
            icon.classList.add('dragging');
        }
        if (this.isDragging) {
            icon.style.left = (e.clientX - this.offset.x) + 'px';
            icon.style.top = (e.clientY - this.offset.y) + 'px';
        }
    },

    _onPointerUp(e, id, icon) {
        icon.releasePointerCapture(e.pointerId);
        if (this.isDragging && this.pendingIcon) {
            icon.classList.remove('dragging');
            this.icons[id] = { x: parseInt(icon.style.left), y: parseInt(icon.style.top) };
            this.saveLayout();
        } else if (this.pendingIcon) {
            runTile(id);
        }
        this.isDragging = false;
        this.pendingIcon = null;
    },

    saveLayout() { localStorage.setItem(this.STORAGE_KEY, JSON.stringify(this.icons)); },

    restoreLayout() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            if (stored) this.icons = JSON.parse(stored);
        } catch (err) { console.error('Failed to restore desktop layout:', err); }
    },

    cleanup() {
        if (this.abortController) { this.abortController.abort(); this.abortController = null; }
    },
};
