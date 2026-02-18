/**
 * desktop-manager.js — Desktop icon grid layout, drag-to-rearrange, and action dispatcher
 * Uses Pointer Events + setPointerCapture for reliable drag at any speed.
 */
import { escapeHtml, showStatus, getIcon, restartServer, API } from './app.js';

export const desktopManager = {
    icons: {},
    STORAGE_KEY: 'ihim_desktop_layout',
    isDragging: false,
    pendingIcon: null,
    pendingActionId: null,
    startPos: { x: 0, y: 0 },
    offset: { x: 0, y: 0 },
    abortController: null,

    init(actions) {
        this.cleanup();
        this.restoreLayout();
        this.renderDesktop(actions);
    },

    renderDesktop(actions) {
        if (this.abortController) this.abortController.abort();
        this.abortController = new AbortController();
        const signal = this.abortController.signal;

        const grid = document.getElementById('actions-grid');
        grid.innerHTML = '';
        grid.className = 'desktop-grid';

        const GRID_SIZE = 120;
        let defaultX = 20;
        let defaultY = 20;
        let col = 0;
        const maxCols = Math.floor((window.innerWidth - 40) / GRID_SIZE);

        for (const [id, action] of Object.entries(actions)) {
            if (id === 'stopwatch') continue;
            const icon = document.createElement('div');
            icon.className = 'desktop-icon';
            icon.dataset.actionId = id;
            icon.setAttribute('role', 'button');
            icon.setAttribute('tabindex', '0');
            icon.setAttribute('aria-label', action.name);

            const saved = this.icons[id];
            const x = saved ? saved.x : defaultX + (col * GRID_SIZE);
            const y = saved ? saved.y : defaultY + (Math.floor(col / maxCols) * GRID_SIZE);
            icon.style.left = x + 'px';
            icon.style.top = y + 'px';

            icon.innerHTML = `
                <div class="desktop-icon-image">${getIcon(action.icon)}</div>
                <div class="desktop-icon-label">${escapeHtml(action.name)}</div>
            `;

            // Pointer Events for drag (captures all events to the element)
            icon.addEventListener('pointerdown', (e) => this._onPointerDown(e, id, icon), { signal });
            icon.addEventListener('pointermove', (e) => this._onPointerMove(e, icon), { signal });
            icon.addEventListener('pointerup', (e) => this._onPointerUp(e, id, icon), { signal });
            icon.addEventListener('pointercancel', (e) => this._onPointerUp(e, id, icon), { signal });

            // Keyboard activation
            icon.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); runAction(id); }
            }, { signal });

            // Prevent default drag ghost
            icon.addEventListener('dragstart', (e) => e.preventDefault(), { signal });

            grid.appendChild(icon);
            if (!saved) this.icons[id] = { x, y };
            col++;
        }

        requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
        this.saveLayout();
    },

    _onPointerDown(e, id, icon) {
        if (e.button !== 0) return; // Left button only
        e.preventDefault();
        icon.setPointerCapture(e.pointerId);
        this.startPos = { x: e.clientX, y: e.clientY };
        // Use style.left/top directly (not getBoundingClientRect which includes transforms)
        const iconX = parseInt(icon.style.left) || 0;
        const iconY = parseInt(icon.style.top) || 0;
        this.offset = { x: e.clientX - iconX, y: e.clientY - iconY };
        this.pendingIcon = icon;
        this.pendingActionId = id;
        this.isDragging = false;
    },

    _onPointerMove(e, icon) {
        if (!icon.hasPointerCapture(e.pointerId)) return;
        if (!this.pendingIcon) return;

        const dx = Math.abs(e.clientX - this.startPos.x);
        const dy = Math.abs(e.clientY - this.startPos.y);

        // Start drag after 5px movement threshold
        if (!this.isDragging && (dx > 5 || dy > 5)) {
            this.isDragging = true;
            icon.classList.add('dragging');
        }

        if (this.isDragging) {
            const FOOTER_HEIGHT = 36;
            let x = e.clientX - this.offset.x;
            let y = e.clientY - this.offset.y;
            // Viewport clamp — icon stays fully on screen
            x = Math.max(0, Math.min(x, window.innerWidth - 100));
            y = Math.max(0, Math.min(y, window.innerHeight - FOOTER_HEIGHT - 100));
            icon.style.left = x + 'px';
            icon.style.top = y + 'px';
        }
    },

    _onPointerUp(e, id, icon) {
        icon.releasePointerCapture(e.pointerId);

        if (this.isDragging && this.pendingIcon) {
            // Drop — save position (free-form, no grid snap)
            icon.classList.remove('dragging');
            const actionId = icon.dataset.actionId;
            this.icons[actionId] = { x: parseInt(icon.style.left), y: parseInt(icon.style.top) };
            this.saveLayout();
        } else if (this.pendingIcon) {
            // Click — fire action
            runAction(id);
        }

        this.isDragging = false;
        this.pendingIcon = null;
        this.pendingActionId = null;
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
    }
};

// Action dispatcher — uses dynamic imports to avoid circular deps
export async function runAction(actionId, btn = null) {
    if (actionId === 'software_dev_team') {
        const { openTeamModal } = await import('./chat-manager.js');
        openTeamModal(); return;
    }
    if (actionId === 'flight_path') {
        const { openFlightPathWindow } = await import('./flight-path.js');
        openFlightPathWindow(); return;
    }
    if (actionId === 'slash_commands') {
        const { openSlashModal } = await import('./slash-commands.js');
        openSlashModal(); return;
    }
    if (actionId === 'agent_team_builder') {
        const { openAgentTeamModal } = await import('./chat-manager.js');
        openAgentTeamModal(); return;
    }
    if (actionId === 'restart_server') { restartServer(); return; }
    if (actionId === 'stopwatch') {
        const { stopwatchManager } = await import('./stopwatch.js');
        stopwatchManager.spawn();
        const container = document.getElementById('stopwatch-container');
        if (container) { container.classList.add('highlight'); setTimeout(() => container.classList.remove('highlight'), 1000); }
        showStatus('Stopwatch spawned!', 'success'); return;
    }
    if (actionId === 'mission_control') {
        const { openMCWindow } = await import('./terminal-manager.js');
        openMCWindow(); return;
    }
    if (actionId === 'standards_library') {
        const { openStandardsLibraryWindow } = await import('./standards-library.js');
        openStandardsLibraryWindow(); return;
    }
    if (actionId === 'google_calendar') {
        const { openCalendarWindow } = await import('./calendar.js');
        openCalendarWindow(); return;
    }
    if (actionId === 'health') {
        const { openHealthWindow } = await import('./health-dashboard.js');
        openHealthWindow(); return;
    }
    if (actionId === 'workspaces') {
        const { toggleWorkspacesWindow } = await import('./vault-dashboard.js');
        toggleWorkspacesWindow(); return;
    }
    if (actionId === 'vault') {
        const { toggleVaultWindow } = await import('./vault-dashboard.js');
        toggleVaultWindow(); return;
    }

    if (btn) btn.classList.add('loading');
    showStatus('Running...', 'pending');
    try {
        const res = await fetch(`${API}/api/actions/${actionId}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) showStatus(data.message, 'success');
        else showStatus(data.message, 'error');
    } catch (err) { showStatus('Failed to execute action', 'error'); }
    finally { if (btn) btn.classList.remove('loading'); }
}
