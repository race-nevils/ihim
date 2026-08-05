/**
 * <ihim-panel> — Draggable window Web Component base class.
 * Thin delegation layer over Phase 3 utilities:
 *   - draggable.js: pointer drag, keyboard move, viewport clamping, position persistence
 *   - a11y.js: global Escape-key close via window registry
 *
 * Dashboard windows subclass IhimPanel (is-a: every widget window IS a
 * draggable panel). A subclass renders its CONTENT synchronously in
 * connectedCallback, then calls super.connectedCallback():
 *
 *   class IhimSTT extends IhimPanel {
 *       connectedCallback() {
 *           this.innerHTML = `...window content, NO header...`;
 *           this.addEventListener('panel:open', () => ...);
 *           super.connectedCallback();
 *       }
 *   }
 *
 * Window chrome is the STANDARD TITLEBAR: one bare strip, controls only (− □ ✕) — no icon,
 * no title text. IhimPanel injects it; subclasses never author their own
 * header. Window identity lives on the taskbar chip + control aria-labels.
 * A subclass element marked [data-titlebar-slot] (e.g. stt's status
 * badge) is moved into the strip's left side at setup.
 *
 * The bare element remains usable for markup-authored windows:
 *   <ihim-panel id="my-window" persist-key="myWindowPosition">...</ihim-panel>
 *
 * Visibility controlled by [open] attribute (like <dialog>/<details>).
 * CSS: subclasses must appear in style.css's window selector list
 * (position: fixed / [open] display rules + [open].minimized hide rule
 * + the [maximized] fill rule).
 * Minimize keeps [open] set and adds .minimized — the window stays "running"
 * (taskbar chip, persisted open flag) but is hidden until restore().
 * Maximize is an attribute, not geometry: the [maximized] CSS wins over the
 * inline drag/resize styles while it's on, and the old geometry is still
 * there when it comes off — nothing to save or restore by hand.
 * Persistence keys: persistKey (position), -size, -open, -min, -max.
 * Public API: open(), close(), toggle(), minimize(), restore(), toggleMaximize()
 * Events: panel:open, panel:close, panel:minimize, panel:restore (bubble)
 */

import { makeDraggable } from '../draggable.js';
import { initWindowEscapeClose } from '../a11y.js';
import { persist, unpersist } from '../ui-state.js';

// Click-to-focus: monotonic counter shared across all ihim-panels.
// Pointerdown anywhere in a panel raises it above its siblings.
let topZ = 100;

// 1px-stroke glyphs matching the native Windows caption cluster in the
// shell's title strip
const GLYPHS = {
    min: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M0 5.5h10" stroke="currentColor" fill="none"/></svg>',
    max: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><rect x="0.5" y="0.5" width="9" height="9" stroke="currentColor" fill="none"/></svg>',
    restore: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2.5 2.5v-2h7v7h-2" stroke="currentColor" fill="none"/><rect x="0.5" y="2.5" width="7" height="7" stroke="currentColor" fill="none"/></svg>',
    close: '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M0.5 0.5l9 9M9.5 0.5l-9 9" stroke="currentColor" fill="none"/></svg>',
};

export class IhimPanel extends HTMLElement {
    connectedCallback() {
        // Defer to ensure light-DOM children are parsed
        queueMicrotask(() => this._setup());
    }

    _setup() {
        if (this._initialized) return;
        this._initialized = true;

        const persistKey = this.getAttribute('persist-key');

        // Standard titlebar first — makeDraggable queries [data-drag-handle]
        this._buildTitlebar();

        // Delegate drag to Phase 3 draggable.js
        makeDraggable(this.id, '[data-drag-handle]', persistKey);

        // Delegate escape-close to Phase 3 a11y.js
        initWindowEscapeClose(this, () => this.close());

        // Auto-wire close buttons
        for (const btn of this.querySelectorAll('[data-close-btn]')) {
            btn.addEventListener('click', () => this.close());
        }

        // Click-to-focus: capture-phase so it runs before any child handler
        this.addEventListener('pointerdown', () => {
            topZ += 1;
            this.style.zIndex = String(topZ);
        }, { capture: true });

        // Size persistence: localStorage[`${persistKey}-size`]
        if (persistKey) this._wireSizePersistence(persistKey);

        // Restore maximized state (attribute survives close/reopen)
        if (persistKey && localStorage.getItem(`${persistKey}-max`) === '1') {
            this.setAttribute('maximized', '');
            this._syncMaxBtn(true);
        }

        // Open-state persistence: re-open panels that were open last session.
        // localStorage[`${persistKey}-open`] = "1" while open, removed on close.
        // Read the minimized flag BEFORE open() — open() clears it.
        if (persistKey && localStorage.getItem(`${persistKey}-open`) === '1') {
            const wasMinimized = localStorage.getItem(`${persistKey}-min`) === '1';
            this.open();
            if (wasMinimized) this.minimize();
        }
    }

    // Standard window chrome:
    // one bare strip, controls only. Skipped if the subclass already has one
    // (re-connect after a DOM move).
    _buildTitlebar() {
        if (this.querySelector('.window-titlebar')) return;
        const name = this.getAttribute('taskbar-label') || this.id;
        const bar = document.createElement('div');
        bar.className = 'window-titlebar';
        bar.setAttribute('data-drag-handle', '');
        bar.innerHTML = `
            <div class="window-controls">
                <button type="button" class="window-btn min" aria-label="Minimize ${name}">${GLYPHS.min}</button>
                <button type="button" class="window-btn max" aria-label="Maximize ${name}">${GLYPHS.max}</button>
                <button type="button" class="window-btn close" data-close-btn aria-label="Close ${name}">${GLYPHS.close}</button>
            </div>`;
        const slot = this.querySelector('[data-titlebar-slot]');
        if (slot) bar.prepend(slot);
        bar.querySelector('.min').addEventListener('click', () => this.minimize());
        this._maxBtn = bar.querySelector('.max');
        this._maxBtn.addEventListener('click', () => this.toggleMaximize());
        bar.addEventListener('dblclick', (e) => {
            if (!e.target.closest('button')) this.toggleMaximize();
        });
        this.prepend(bar);
    }

    _syncMaxBtn(on) {
        if (!this._maxBtn) return;
        const name = this.getAttribute('taskbar-label') || this.id;
        this._maxBtn.innerHTML = on ? GLYPHS.restore : GLYPHS.max;
        this._maxBtn.setAttribute('aria-label', on ? `Restore ${name} size` : `Maximize ${name}`);
    }

    toggleMaximize() {
        const persistKey = this.getAttribute('persist-key');
        const on = this.toggleAttribute('maximized');
        this._syncMaxBtn(on);
        if (persistKey) {
            if (on) persist(`${persistKey}-max`, '1');
            else unpersist(`${persistKey}-max`);
        }
        topZ += 1;
        this.style.zIndex = String(topZ);
    }

    _wireSizePersistence(persistKey) {
        const sizeKey = `${persistKey}-size`;
        // Clamp to viewport so the resize handle never lands off-screen.
        const clamp = (w, h) => ({
            width: Math.min(w, window.innerWidth - 40),
            height: Math.min(h, window.innerHeight - 40),
        });
        try {
            const saved = localStorage.getItem(sizeKey);
            if (saved) {
                const { width, height } = JSON.parse(saved);
                const c = clamp(width || 0, height || 0);
                if (width) this.style.width = `${c.width}px`;
                if (height) this.style.height = `${c.height}px`;
            }
        } catch (e) { /* corrupt — ignore */ }

        // ResizeObserver doesn't fire for display:none, so closed widgets won't write.
        const observer = new ResizeObserver(entries => {
            for (const entry of entries) {
                // Viewport-fill is not a size choice — don't overwrite the saved size
                if (this.hasAttribute('maximized')) continue;
                // Border-box, NOT contentRect: the saved size is re-applied as
                // style.width/height, which under the global border-box sizing
                // sets the border box — persisting the (padding-excluded)
                // contentRect shrank every window by its padding per cycle
                // until content overflowed the glass.
                const box = entry.borderBoxSize?.[0];
                const w = Math.round(box ? box.inlineSize : entry.target.getBoundingClientRect().width);
                const h = Math.round(box ? box.blockSize : entry.target.getBoundingClientRect().height);
                if (w === 0 || h === 0) continue;
                const c = clamp(w, h);
                persist(sizeKey, JSON.stringify(c));
            }
        });
        observer.observe(this);
    }

    open() {
        const persistKey = this.getAttribute('persist-key');
        let positioned = false;

        // Restore saved position with viewport bounds check
        if (persistKey) {
            try {
                const saved = localStorage.getItem(persistKey);
                if (saved) {
                    const { x, y } = JSON.parse(saved);
                    if (x >= 0 && y >= 0 && x < window.innerWidth - 50 && y < window.innerHeight - 50) {
                        this.style.left = x + 'px';
                        this.style.top = y + 'px';
                        positioned = true;
                    }
                }
            } catch (e) { /* corrupt localStorage — ignore */ }
        }

        // Show the panel (CSS key: ihim-panel[open] { display: flex })
        this.setAttribute('open', '');

        // Center on screen if no valid saved position
        if (!positioned) {
            const rect = this.getBoundingClientRect();
            this.style.left = Math.max(0, (window.innerWidth - rect.width) / 2) + 'px';
            this.style.top = Math.max(0, (window.innerHeight - rect.height) / 2) + 'px';
        }

        this.classList.remove('minimized');
        if (persistKey) {
            persist(`${persistKey}-open`, '1');
            unpersist(`${persistKey}-min`);
        }
        this.dispatchEvent(new CustomEvent('panel:open', { bubbles: true }));
    }

    close() {
        const persistKey = this.getAttribute('persist-key');
        this.removeAttribute('open');
        this.classList.remove('minimized');
        if (persistKey) {
            unpersist(`${persistKey}-open`);
            unpersist(`${persistKey}-min`);
        }
        this.dispatchEvent(new CustomEvent('panel:close', { bubbles: true }));
    }

    toggle() {
        if (this.classList.contains('minimized')) this.restore();
        else if (this.hasAttribute('open')) this.close();
        else this.open();
    }

    minimize() {
        const persistKey = this.getAttribute('persist-key');
        this.classList.add('minimized');
        if (persistKey) persist(`${persistKey}-min`, '1');
        this.dispatchEvent(new CustomEvent('panel:minimize', { bubbles: true }));
    }

    restore() {
        const persistKey = this.getAttribute('persist-key');
        this.classList.remove('minimized');
        if (persistKey) unpersist(`${persistKey}-min`);
        topZ += 1;
        this.style.zIndex = String(topZ);
        this.dispatchEvent(new CustomEvent('panel:restore', { bubbles: true }));
    }
}

customElements.define('ihim-panel', IhimPanel);
