/**
 * <ihim-taskbar> — Windows-style taskbar for the bottom status bar.
 * One chip per open panel window; click minimizes a visible window and
 * restores a minimized one. Panels opt in declaratively:
 *
 *   <ihim-health ... taskbar-icon="heart-pulse" taskbar-label="Health"></ihim-health>
 *
 * State is fully derived — the taskbar owns nothing. It re-renders from the
 * DOM ([taskbar-label][open] + .minimized + [recording]) on every panel:*
 * event (panels dispatch panel:state on live-state changes like recording),
 * so open/minimize persistence lives where it already does: IhimPanel's
 * -open / -min keys through ui-state.js.
 *
 * Usage: <ihim-taskbar id="taskbar" class="taskbar"></ihim-taskbar>
 */

import { escapeHtml, getIcon } from '../app.js';

const PANEL_EVENTS = ['panel:open', 'panel:close', 'panel:minimize', 'panel:restore', 'panel:state'];

class IhimTaskbar extends HTMLElement {
    connectedCallback() {
        this.setAttribute('role', 'toolbar');
        this.setAttribute('aria-label', 'Open windows');

        this._onPanelEvent = () => this._render();
        for (const ev of PANEL_EVENTS) {
            document.addEventListener(ev, this._onPanelEvent);
        }

        // Chip clicks are delegated — chips are re-rendered wholesale.
        this.addEventListener('click', (e) => {
            const chip = e.target.closest('.taskbar-chip');
            if (!chip) return;
            const win = document.getElementById(chip.dataset.target);
            if (!win) return;
            if (win.classList.contains('minimized')) win.restore();
            else win.minimize();
        });

        // Panels restore their persisted open state in deferred microtasks;
        // a first paint after the current frame catches any that upgraded
        // (and opened) before this element's listeners attached.
        requestAnimationFrame(() => this._render());
    }

    disconnectedCallback() {
        for (const ev of PANEL_EVENTS) {
            document.removeEventListener(ev, this._onPanelEvent);
        }
    }

    _render() {
        const windows = [...document.querySelectorAll('[taskbar-label][open]')];
        this.innerHTML = windows.map(win => {
            const label = win.getAttribute('taskbar-label');
            const minimized = win.classList.contains('minimized');
            // e.g. the recorder while capturing — red outline on the chip
            const recording = win.hasAttribute('recording');
            return `
                <button type="button"
                        class="taskbar-chip${minimized ? ' minimized' : ''}${recording ? ' recording' : ''}"
                        data-target="${escapeHtml(win.id)}"
                        aria-pressed="${minimized ? 'false' : 'true'}"
                        title="${escapeHtml(label)} — ${minimized ? 'restore' : 'minimize'}">
                    ${getIcon(win.getAttribute('taskbar-icon') || 'default')}
                    <span>${escapeHtml(label)}</span>
                </button>`;
        }).join('');
        requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
    }
}

customElements.define('ihim-taskbar', IhimTaskbar);
