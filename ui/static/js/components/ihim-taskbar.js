/**
 * <ihim-taskbar> — Windows-style taskbar for the bottom status bar.
 * One chip per open panel window; click minimizes a visible window and
 * restores a minimized one. Panels opt in declaratively:
 *
 *   <ihim-todo ... taskbar-icon="list-todo" taskbar-label="To-Do"></ihim-todo>
 *
 * State is fully derived — the taskbar owns nothing. It re-renders from the
 * DOM ([taskbar-label][open] + .minimized + [recording]) on every panel:*
 * event (panels dispatch panel:state on live-state changes like recording),
 * so open/minimize persistence lives where it already does: IhimPanel's
 * -open / -min keys through ui-state.js.
 *
 * The ONE thing the taskbar persists itself is chip order: chips are
 * drag-to-reorder (native HTML5 DnD), saved as an id array under
 * ihim_taskbar_order via ui-state.js so every client shares the layout.
 *
 * Right-click on a chip opens a context menu (Close window) — one owned
 * element that survives the wholesale innerHTML re-renders by being
 * re-appended after each one. It positions fixed at the cursor, opening
 * upward (the bar sits at the bottom of the screen).
 *
 * Usage: <ihim-taskbar id="taskbar" class="taskbar"></ihim-taskbar>
 */

import { escapeHtml, getIcon } from '../app.js';
import { persist } from '../ui-state.js';

const PANEL_EVENTS = ['panel:open', 'panel:close', 'panel:minimize', 'panel:restore', 'panel:state'];
const ORDER_KEY = 'ihim_taskbar_order';

class IhimTaskbar extends HTMLElement {
    connectedCallback() {
        this.setAttribute('role', 'toolbar');
        this.setAttribute('aria-label', 'Open windows');

        // Mid-drag re-renders would yank the dragged chip out from under the
        // cursor; dragend re-renders to catch anything skipped.
        this._onPanelEvent = () => { if (!this._dragging) this._render(); };
        for (const ev of PANEL_EVENTS) {
            document.addEventListener(ev, this._onPanelEvent);
        }

        // Chip clicks are delegated — chips are re-rendered wholesale.
        // (A completed drag suppresses the click natively.)
        this.addEventListener('click', (e) => {
            const chip = e.target.closest('.taskbar-chip');
            if (!chip) return;
            const win = document.getElementById(chip.dataset.target);
            if (!win) return;
            if (win.classList.contains('minimized')) win.restore();
            else win.minimize();
        });

        // Drag-to-reorder: chips move live in the DOM while dragging; the
        // resulting order is persisted on dragend.
        this.addEventListener('dragstart', (e) => {
            const chip = e.target.closest('.taskbar-chip');
            if (!chip) return;
            this._dragging = chip;
            chip.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', chip.dataset.target);
        });

        this.addEventListener('dragover', (e) => {
            if (!this._dragging) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            const over = e.target.closest('.taskbar-chip');
            if (!over) {
                // Empty strip past the chips — dragging to the end
                const last = this.querySelector('.taskbar-chip:last-child');
                if (last && last !== this._dragging &&
                    e.clientX > last.getBoundingClientRect().right) {
                    this.appendChild(this._dragging);
                }
                return;
            }
            if (over === this._dragging) return;
            const rect = over.getBoundingClientRect();
            const before = e.clientX < rect.left + rect.width / 2;
            this.insertBefore(this._dragging, before ? over : over.nextSibling);
        });

        this.addEventListener('drop', (e) => {
            if (this._dragging) e.preventDefault();
        });

        this.addEventListener('dragend', () => {
            if (!this._dragging) return;
            this._dragging.classList.remove('dragging');
            this._dragging = null;
            const visible = [...this.querySelectorAll('.taskbar-chip')]
                .map(c => c.dataset.target);
            // Closed windows keep their saved slots relative to each other
            const rest = this._order().filter(id => !visible.includes(id));
            persist(ORDER_KEY, JSON.stringify([...visible, ...rest]));
            this._render();
        });

        // Right-click context menu — built once, re-appended after re-renders.
        this._ctx = document.createElement('div');
        this._ctx.className = 'hud-menu taskbar-ctx';
        this._ctx.setAttribute('role', 'menu');
        this._ctx.hidden = true;
        this._ctx.innerHTML = `
            <button type="button" class="hud-menu-item" role="menuitem" data-action="close">
                <i data-lucide="x"></i>Close window
            </button>`;
        this._ctx.querySelector('[data-action="close"]').addEventListener('click', () => {
            const win = document.getElementById(this._ctx.dataset.target || '');
            this._closeCtx();
            if (win) win.close();
        });
        this.appendChild(this._ctx);

        this.addEventListener('contextmenu', (e) => {
            const chip = e.target.closest('.taskbar-chip');
            if (!chip) return;
            e.preventDefault();
            this._openCtx(chip.dataset.target, e.clientX, e.clientY);
        });

        this._onDocPointer = (e) => {
            if (!this._ctx.hidden && !this._ctx.contains(e.target)) this._closeCtx();
        };
        this._onDocKey = (e) => {
            if (e.key === 'Escape' && !this._ctx.hidden) this._closeCtx();
        };
        document.addEventListener('pointerdown', this._onDocPointer);
        document.addEventListener('keydown', this._onDocKey);

        // Panels restore their persisted open state in deferred microtasks;
        // a first paint after the current frame catches any that upgraded
        // (and opened) before this element's listeners attached.
        requestAnimationFrame(() => this._render());
    }

    disconnectedCallback() {
        for (const ev of PANEL_EVENTS) {
            document.removeEventListener(ev, this._onPanelEvent);
        }
        document.removeEventListener('pointerdown', this._onDocPointer);
        document.removeEventListener('keydown', this._onDocKey);
    }

    _openCtx(targetId, x, y) {
        this._ctx.dataset.target = targetId;
        this._ctx.hidden = false;
        // Clamp so the menu never runs off the right edge; anchor its bottom
        // just above the cursor so it opens upward.
        const w = this._ctx.offsetWidth || 160;
        this._ctx.style.left = `${Math.min(x, window.innerWidth - w - 8)}px`;
        this._ctx.style.bottom = `${window.innerHeight - y + 4}px`;
        if (window.lucide) lucide.createIcons();
    }

    _closeCtx() {
        this._ctx.hidden = true;
        delete this._ctx.dataset.target;
    }

    _order() {
        try { return JSON.parse(localStorage.getItem(ORDER_KEY)) || []; }
        catch { return []; }
    }

    _render() {
        if (this._ctx && !this._ctx.hidden) this._closeCtx();
        const order = this._order();
        const rank = (el) => {
            const i = order.indexOf(el.id);
            return i === -1 ? order.length : i;  // unknown ids after known, DOM order (stable sort)
        };
        const windows = [...document.querySelectorAll('[taskbar-label][open]')]
            .sort((a, b) => rank(a) - rank(b));
        this.innerHTML = windows.map(win => {
            const label = win.getAttribute('taskbar-label');
            const minimized = win.classList.contains('minimized');
            // e.g. the recorder while capturing — red outline on the chip
            const recording = win.hasAttribute('recording');
            return `
                <button type="button"
                        draggable="true"
                        class="taskbar-chip${minimized ? ' minimized' : ''}${recording ? ' recording' : ''}"
                        data-target="${escapeHtml(win.id)}"
                        aria-pressed="${minimized ? 'false' : 'true'}"
                        title="${escapeHtml(label)} — ${minimized ? 'restore' : 'minimize'}">
                    ${getIcon(win.getAttribute('taskbar-icon') || 'default')}
                    <span>${escapeHtml(label)}</span>
                </button>`;
        }).join('');
        if (this._ctx) this.appendChild(this._ctx);
        // Synchronous, not rAF-deferred: lucide is a sync <head> script, and a
        // deferred pass leaves one painted frame of icon-less chips whenever a
        // re-render lands in animation-frame timing (visible as a taskbar
        // blink — chips snap narrower while the icon slots are empty).
        if (window.lucide) lucide.createIcons();
    }
}

customElements.define('ihim-taskbar', IhimTaskbar);
