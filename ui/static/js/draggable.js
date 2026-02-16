/**
 * draggable.js — Unified drag handler for all windows + Workspace State persistence
 */

// Unified drag handler for all windows
export function makeDraggable(windowId, handleSelector, storageKey) {
    const el = document.getElementById(windowId);
    if (!el) return;
    const handle = el.querySelector(handleSelector);
    if (!handle) return;

    handle.style.cursor = 'move';
    let isDragging = false;
    let currentHandlers = null;

    handle.addEventListener('mousedown', (e) => {
        if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
        e.preventDefault();

        if (currentHandlers) {
            document.removeEventListener('mousemove', currentHandlers.move);
            document.removeEventListener('mouseup', currentHandlers.up);
            document.removeEventListener('mouseleave', currentHandlers.leave);
            currentHandlers = null;
        }

        const rect = el.getBoundingClientRect();
        el.style.transform = 'none';
        el.style.right = 'auto';
        el.style.bottom = 'auto';
        el.style.left = rect.left + 'px';
        el.style.top = rect.top + 'px';

        const mouseDownTime = Date.now();
        isDragging = false;
        const offsetX = e.clientX - rect.left;
        const offsetY = e.clientY - rect.top;
        const startX = e.clientX;
        const startY = e.clientY;

        const onMouseMove = (e) => {
            e.preventDefault();
            const dx = Math.abs(e.clientX - startX);
            const dy = Math.abs(e.clientY - startY);
            if ((dx > 5 || dy > 5 || Date.now() - mouseDownTime > 150) && !isDragging) {
                isDragging = true;
                el.style.opacity = '0.9';
                el.style.zIndex = '1000';
                document.body.style.userSelect = 'none';
            }
            if (isDragging) {
                el.style.left = (e.clientX - offsetX) + 'px';
                el.style.top = (e.clientY - offsetY) + 'px';
            }
        };

        const cleanup = () => {
            if (isDragging && storageKey) {
                localStorage.setItem(storageKey, JSON.stringify({
                    x: parseInt(el.style.left), y: parseInt(el.style.top)
                }));
            }
            isDragging = false;
            el.style.opacity = '1';
            el.style.zIndex = '';
            document.body.style.userSelect = '';
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            document.removeEventListener('mouseleave', onMouseLeave);
            currentHandlers = null;
        };

        const onMouseUp = () => cleanup();
        const onMouseLeave = (e) => {
            if (isDragging && e.target === document.documentElement) cleanup();
        };

        currentHandlers = { move: onMouseMove, up: onMouseUp, leave: onMouseLeave };
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
        document.addEventListener('mouseleave', onMouseLeave);
    });
}

// Widget resize persistence via ResizeObserver
export function initializeWidgetResize() {
    const widgetIds = ['flightpath-window', 'mc-window', 'standards-library-window', 'calendar-window', 'health-window', 'chat-window', 'vault-window', 'workspaces-window'];

    widgetIds.forEach(widgetId => {
        const savedSize = localStorage.getItem(`${widgetId}-size`);
        if (savedSize) {
            try {
                const { width, height } = JSON.parse(savedSize);
                const widget = document.getElementById(widgetId);
                if (widget) {
                    if (width) widget.style.width = `${width}px`;
                    if (height) widget.style.height = `${height}px`;
                }
            } catch (e) {
                console.warn(`Failed to restore size for ${widgetId}:`, e);
            }
        }
    });

    const observer = new ResizeObserver(entries => {
        for (const entry of entries) {
            const widget = entry.target;
            if (widget.style.display === 'none') continue;
            const widgetId = widget.id;
            if (!widgetIds.includes(widgetId)) continue;
            localStorage.setItem(`${widgetId}-size`, JSON.stringify({
                width: Math.round(entry.contentRect.width),
                height: Math.round(entry.contentRect.height)
            }));
        }
    });

    widgetIds.forEach(widgetId => {
        const widget = document.getElementById(widgetId);
        if (widget) observer.observe(widget);
    });
}

// Workspace state persistence
export const WorkspaceState = {
    STORAGE_KEY: 'ihim_workspace_state',
    AUTO_SAVE_INTERVAL: 30000,
    autoSaveTimer: null,

    TRACKED_MODALS: [
        'flightpath-modal', 'slash-modal', 'metrics-modal',
        'team-modal', 'agent-team-modal', 'terminal-modal'
    ],

    getState() {
        const state = { openModals: [], timestamp: new Date().toISOString() };
        this.TRACKED_MODALS.forEach(modalId => {
            const modal = document.getElementById(modalId);
            if (modal && modal.classList.contains('active')) {
                state.openModals.push(modalId);
            }
        });
        return state;
    },

    saveState() {
        try {
            const state = this.getState();
            if (state.openModals.length === 0) {
                const existing = this.loadState();
                if (existing && existing.openModals.length > 0) return;
            }
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state));
        } catch (err) { console.error('Failed to save workspace state:', err); }
    },

    loadState() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            if (stored) return JSON.parse(stored);
        } catch (err) { console.error('Failed to load workspace state:', err); }
        return null;
    },

    startAutoSave() {
        if (this.autoSaveTimer) clearInterval(this.autoSaveTimer);
        this.autoSaveTimer = setInterval(() => this.saveState(), this.AUTO_SAVE_INTERVAL);
    },

    stopAutoSave() {
        if (this.autoSaveTimer) { clearInterval(this.autoSaveTimer); this.autoSaveTimer = null; }
    },

    init() {
        this.startAutoSave();
        window.addEventListener('beforeunload', () => this.saveState());
        document.addEventListener('visibilitychange', () => { if (document.hidden) this.saveState(); });
    }
};
