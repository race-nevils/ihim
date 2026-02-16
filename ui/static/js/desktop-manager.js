/**
 * desktop-manager.js — Desktop icon grid layout, drag-to-rearrange, and action dispatcher
 */
import { escapeHtml, showStatus, getIcon, restartServer, API } from './app.js';

export const desktopManager = {
    icons: {},
    STORAGE_KEY: 'ihim_desktop_layout',
    GRID_SIZE: 120,
    draggingIcon: null,
    offset: { x: 0, y: 0 },
    holdTimer: null,
    isDragging: false,
    startPos: { x: 0, y: 0 },
    mouseDownTime: 0,
    HOLD_DELAY: 300,
    CLICK_THRESHOLD: 200,
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

        let defaultX = 20;
        let defaultY = 20;
        let col = 0;
        const maxCols = Math.floor((window.innerWidth - 40) / this.GRID_SIZE);

        for (const [id, action] of Object.entries(actions)) {
            if (id === 'stopwatch') continue;
            const icon = document.createElement('div');
            icon.className = 'desktop-icon';
            icon.dataset.actionId = id;

            const saved = this.icons[id];
            const x = saved ? saved.x : defaultX + (col * this.GRID_SIZE);
            const y = saved ? saved.y : defaultY + (Math.floor(col / maxCols) * this.GRID_SIZE);
            icon.style.left = x + 'px';
            icon.style.top = y + 'px';

            icon.innerHTML = `
                <div class="desktop-icon-image">${getIcon(action.icon)}</div>
                <div class="desktop-icon-label">${escapeHtml(action.name)}</div>
            `;

            icon.addEventListener('mousedown', (e) => this.handleMouseDown(e, id, icon), { signal });
            icon.addEventListener('mousemove', (e) => this.handleMouseMove(e), { signal });
            icon.addEventListener('mouseup', (e) => this.handleMouseUp(e, id), { signal });
            icon.addEventListener('mouseleave', (e) => this.handleMouseUp(e, id), { signal });

            grid.appendChild(icon);
            if (!saved) this.icons[id] = { x, y };
            col++;
        }

        document.addEventListener('mousemove', (e) => {
            if (this.isDragging && this.draggingIcon) this.handleDrag(e);
        }, { signal });

        requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
        this.saveLayout();
    },

    handleMouseDown(e, id, icon) {
        e.preventDefault();
        this.mouseDownTime = Date.now();
        this.startPos = { x: e.clientX, y: e.clientY };
        const rect = icon.getBoundingClientRect();
        this.offset.x = e.clientX - rect.left;
        this.offset.y = e.clientY - rect.top;
        this.holdTimer = setTimeout(() => {
            this.isDragging = true;
            this.draggingIcon = icon;
            icon.style.opacity = '0.7';
            icon.style.zIndex = '1000';
            icon.classList.add('dragging');
        }, this.HOLD_DELAY);
    },

    handleMouseMove(e) {
        if (this.holdTimer && !this.isDragging) {
            const dx = Math.abs(e.clientX - this.startPos.x);
            const dy = Math.abs(e.clientY - this.startPos.y);
            if (dx > 5 || dy > 5) {
                clearTimeout(this.holdTimer);
                this.isDragging = true;
                this.draggingIcon = e.currentTarget;
                this.draggingIcon.style.opacity = '0.7';
                this.draggingIcon.style.zIndex = '1000';
                this.draggingIcon.classList.add('dragging');
            }
        }
    },

    handleDrag(e) {
        if (!this.draggingIcon) return;
        const FOOTER_HEIGHT = 36;
        let x = e.clientX - this.offset.x;
        let y = e.clientY - this.offset.y;
        x = Math.max(0, Math.min(x, window.innerWidth - 100));
        y = Math.max(0, Math.min(y, window.innerHeight - FOOTER_HEIGHT - 100));
        this.draggingIcon.style.left = x + 'px';
        this.draggingIcon.style.top = y + 'px';
    },

    handleMouseUp(e, id) {
        clearTimeout(this.holdTimer);
        const duration = Date.now() - this.mouseDownTime;

        if (this.isDragging && this.draggingIcon) {
            const FOOTER_HEIGHT = 36;
            let x = e.clientX - this.offset.x;
            let y = e.clientY - this.offset.y;
            x = Math.round(x / this.GRID_SIZE) * this.GRID_SIZE;
            y = Math.round(y / this.GRID_SIZE) * this.GRID_SIZE;
            x = Math.max(0, Math.min(x, window.innerWidth - 100));
            y = Math.max(0, Math.min(y, window.innerHeight - FOOTER_HEIGHT - 100));
            this.draggingIcon.style.left = x + 'px';
            this.draggingIcon.style.top = y + 'px';
            this.draggingIcon.style.opacity = '1';
            this.draggingIcon.style.zIndex = '';
            this.draggingIcon.classList.remove('dragging');
            const actionId = this.draggingIcon.dataset.actionId;
            this.icons[actionId] = { x, y };
            this.saveLayout();
            this.draggingIcon = null;
            this.isDragging = false;
        } else if (duration < this.CLICK_THRESHOLD) {
            runAction(id);
        }
        this.holdTimer = null;
        this.mouseDownTime = 0;
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
