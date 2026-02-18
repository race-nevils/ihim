/**
 * draggable.js — Unified drag handler for all windows + Workspace State persistence
 * Uses Pointer Events + setPointerCapture for reliable drag.
 * Includes viewport clamping, keyboard movement, and resize re-clamping.
 */

const allDraggables = new Set();

// Unified drag handler for all windows
export function makeDraggable(windowId, handleSelector, storageKey) {
    const el = document.getElementById(windowId);
    if (!el) return;
    const handle = el.querySelector(handleSelector);
    if (!handle) return;

    handle.style.cursor = 'move';
    handle.setAttribute('tabindex', '0');
    handle.setAttribute('aria-roledescription', 'draggable window');
    allDraggables.add(el);

    let isDragging = false;

    handle.addEventListener('pointerdown', (e) => {
        if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
        if (e.button !== 0) return;
        e.preventDefault();

        handle.setPointerCapture(e.pointerId);
        const rect = el.getBoundingClientRect();
        el.style.transform = 'none';
        el.style.right = 'auto';
        el.style.bottom = 'auto';
        el.style.left = rect.left + 'px';
        el.style.top = rect.top + 'px';

        isDragging = false;
        const offsetX = e.clientX - rect.left;
        const offsetY = e.clientY - rect.top;
        const startX = e.clientX;
        const startY = e.clientY;
        const mouseDownTime = Date.now();

        const onPointerMove = (e) => {
            const dx = Math.abs(e.clientX - startX);
            const dy = Math.abs(e.clientY - startY);
            if ((dx > 5 || dy > 5 || Date.now() - mouseDownTime > 150) && !isDragging) {
                isDragging = true;
                el.style.opacity = '0.9';
                el.style.zIndex = '1000';
                document.body.style.userSelect = 'none';
            }
            if (isDragging) {
                let x = e.clientX - offsetX;
                let y = e.clientY - offsetY;
                // Viewport clamp: title bar always visible (40px minimum)
                const minVisible = 40;
                x = Math.max(-el.offsetWidth + 100, Math.min(x, window.innerWidth - 100));
                y = Math.max(0, Math.min(y, window.innerHeight - minVisible));
                el.style.left = x + 'px';
                el.style.top = y + 'px';
            }
        };

        const onPointerUp = () => {
            handle.removeEventListener('pointermove', onPointerMove);
            handle.removeEventListener('pointerup', onPointerUp);
            if (isDragging && storageKey) {
                localStorage.setItem(storageKey, JSON.stringify({
                    x: parseInt(el.style.left), y: parseInt(el.style.top)
                }));
            }
            isDragging = false;
            el.style.opacity = '1';
            el.style.zIndex = '';
            document.body.style.userSelect = '';
        };

        handle.addEventListener('pointermove', onPointerMove);
        handle.addEventListener('pointerup', onPointerUp);
    });

    // Keyboard movement: Ctrl+Arrow keys (20px per press)
    handle.addEventListener('keydown', (e) => {
        if (!e.ctrlKey) return;
        const STEP = 20;
        let x = parseInt(el.style.left) || 0;
        let y = parseInt(el.style.top) || 0;

        switch (e.key) {
            case 'ArrowUp': y -= STEP; break;
            case 'ArrowDown': y += STEP; break;
            case 'ArrowLeft': x -= STEP; break;
            case 'ArrowRight': x += STEP; break;
            default: return;
        }
        e.preventDefault();

        // Ensure CSS positioning mode
        el.style.transform = 'none';
        el.style.right = 'auto';
        el.style.bottom = 'auto';

        // Viewport clamp
        const minVisible = 40;
        x = Math.max(-el.offsetWidth + 100, Math.min(x, window.innerWidth - 100));
        y = Math.max(0, Math.min(y, window.innerHeight - minVisible));
        el.style.left = x + 'px';
        el.style.top = y + 'px';

        if (storageKey) {
            localStorage.setItem(storageKey, JSON.stringify({ x, y }));
        }
    });
}

// Re-clamp all open windows on browser resize
window.addEventListener('resize', () => {
    for (const el of allDraggables) {
        if (el.style.display === 'none') continue;
        const x = parseInt(el.style.left);
        const y = parseInt(el.style.top);
        if (isNaN(x) || isNaN(y)) continue;

        const minVisible = 40;
        const clampedX = Math.max(-el.offsetWidth + 100, Math.min(x, window.innerWidth - 100));
        const clampedY = Math.max(0, Math.min(y, window.innerHeight - minVisible));

        if (clampedX !== x || clampedY !== y) {
            el.style.left = clampedX + 'px';
            el.style.top = clampedY + 'px';
        }
    }
});

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
