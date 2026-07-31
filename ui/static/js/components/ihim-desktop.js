/**
 * <ihim-desktop> — Desktop tile grid Web Component: layout, drag-to-rearrange,
 * activation. Replaces the old desktop.js manager module.
 *
 * Tiles are a frontend constant — every tile opens its window via the
 * IhimPanel element API (open()/toggle()); drag uses Pointer Events +
 * setPointerCapture with a 5px click/drag threshold.
 *
 * Positions are PROPORTIONAL: stored as fractions
 * of the desktop area's usable travel (area minus one icon), re-applied on
 * every window resize — resize/maximize keeps the layout's ratios, an
 * edge-flush icon stays flush, and nothing ever leaves the surface. Pixels
 * exist only transiently during a drag.
 *
 * Usage (the element IS the grid; role="main" keeps the landmark):
 *   <ihim-desktop id="actions-grid" class="desktop-grid" role="main"></ihim-desktop>
 */

import { escapeHtml, getIcon } from '../app.js';
import { persist } from '../ui-state.js';

const panel = (id) => document.getElementById(id);

// Must match .desktop-icon width/height in style.css
const ICON_SIZE = 100;
const clamp01 = (v) => (Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0);

// One entry per desktop tile, in default-layout order.
export const TILES = [
    { id: 'stt', name: 'STT', icon: 'mic', run: () => panel('stt-window')?.toggle() },
    { id: 'meeting_recorder', name: 'Meeting Recorder', icon: 'mic', run: () => panel('recorder-window')?.toggle() },
    { id: 'todo', name: 'To-Do', icon: 'list-todo', run: () => panel('todo-window')?.toggle() },
    { id: 'yt_transcriber', name: 'YT Transcriber', icon: 'play', run: () => panel('yt-window')?.toggle() },
    { id: 'travel', name: 'Travel', icon: 'hard-drive', run: () => panel('travel-window')?.toggle() },
];

class IhimDesktop extends HTMLElement {
    icons = {};
    STORAGE_KEY = 'ihim_desktop_layout';
    isDragging = false;
    pendingIcon = null;
    startPos = { x: 0, y: 0 };
    offset = { x: 0, y: 0 };
    abortController = null;

    connectedCallback() {
        this._restoreLayout();
        this._render();
    }

    disconnectedCallback() {
        if (this.abortController) { this.abortController.abort(); this.abortController = null; }
    }

    runTile(id) {
        TILES.find(t => t.id === id)?.run();
    }

    // Usable travel for an icon's top-left corner. Normalizing fractions by
    // (area - icon) instead of the raw area means fx/fy = 1 puts the icon
    // exactly flush with the edge at ANY window size — icons can never land
    // off-surface, which is what makes "the page never scrolls" hold.
    _bounds() {
        return {
            w: Math.max(1, this.clientWidth - ICON_SIZE),
            h: Math.max(1, this.clientHeight - ICON_SIZE),
        };
    }

    _applyPositions() {
        const b = this._bounds();
        for (const el of this.querySelectorAll('.desktop-icon')) {
            const f = this.icons[el.dataset.actionId];
            if (!f) continue;
            el.style.left = Math.round(f.fx * b.w) + 'px';
            el.style.top = Math.round(f.fy * b.h) + 'px';
        }
    }

    _render() {
        this.abortController = new AbortController();
        const signal = this.abortController.signal;

        this.innerHTML = '';

        const GRID_SIZE = 120;
        const maxCols = Math.max(1, Math.floor((window.innerWidth - 40) / GRID_SIZE));
        const b = this._bounds();
        let col = 0;

        for (const tile of TILES) {
            const icon = document.createElement('div');
            icon.className = 'desktop-icon';
            icon.dataset.actionId = tile.id;
            icon.setAttribute('role', 'button');
            icon.setAttribute('tabindex', '0');
            icon.setAttribute('aria-label', tile.name);

            let f = this.icons[tile.id];
            if (f && f.fx === undefined && f.x !== undefined) {
                // Legacy absolute-px entry from before the proportional
                // layout — convert once against the current surface
                f = { fx: clamp01(f.x / b.w), fy: clamp01(f.y / b.h) };
            }
            if (!f || f.fx === undefined) {
                const x = 20 + ((col % maxCols) * GRID_SIZE);
                const y = 20 + (Math.floor(col / maxCols) * GRID_SIZE);
                f = { fx: clamp01(x / b.w), fy: clamp01(y / b.h) };
            }
            this.icons[tile.id] = f;
            icon.style.left = Math.round(f.fx * b.w) + 'px';
            icon.style.top = Math.round(f.fy * b.h) + 'px';

            icon.innerHTML = `
                <div class="desktop-icon-image">${getIcon(tile.icon)}</div>
                <div class="desktop-icon-label">${escapeHtml(tile.name)}</div>
            `;

            icon.addEventListener('pointerdown', (e) => this._onPointerDown(e, icon), { signal });
            icon.addEventListener('pointermove', (e) => this._onPointerMove(e, icon), { signal });
            icon.addEventListener('pointerup', (e) => this._onPointerUp(e, tile.id, icon), { signal });
            icon.addEventListener('pointercancel', (e) => this._onPointerUp(e, tile.id, icon), { signal });
            icon.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.runTile(tile.id); }
            }, { signal });
            icon.addEventListener('dragstart', (e) => e.preventDefault(), { signal });

            this.appendChild(icon);
            col++;
        }

        window.addEventListener('resize', () => this._applyPositions(), { signal });

        requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
        this._saveLayout();
    }

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
    }

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
    }

    _onPointerUp(e, id, icon) {
        icon.releasePointerCapture(e.pointerId);
        if (this.isDragging && this.pendingIcon) {
            icon.classList.remove('dragging');
            const b = this._bounds();
            const fx = clamp01((parseInt(icon.style.left) || 0) / b.w);
            const fy = clamp01((parseInt(icon.style.top) || 0) / b.h);
            this.icons[id] = { fx, fy };
            // Snap back onto the surface if the drop overshot an edge
            icon.style.left = Math.round(fx * b.w) + 'px';
            icon.style.top = Math.round(fy * b.h) + 'px';
            this._saveLayout();
        } else if (this.pendingIcon) {
            this.runTile(id);
        }
        this.isDragging = false;
        this.pendingIcon = null;
    }

    _saveLayout() {
        // Persist only live tiles — the store had accumulated years of keys
        // for deleted tiles (vault, google_calendar, …) in stale px form
        const live = {};
        for (const t of TILES) if (this.icons[t.id]) live[t.id] = this.icons[t.id];
        this.icons = live;
        persist(this.STORAGE_KEY, JSON.stringify(live));
    }

    _restoreLayout() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            if (stored) this.icons = JSON.parse(stored);
        } catch (err) { console.error('Failed to restore desktop layout:', err); }
    }
}

customElements.define('ihim-desktop', IhimDesktop);
