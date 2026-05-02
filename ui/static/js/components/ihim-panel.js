/**
 * <ihim-panel> — Draggable window Web Component
 * Thin delegation layer over Phase 3 utilities:
 *   - draggable.js: pointer drag, keyboard move, viewport clamping, position persistence
 *   - a11y.js: global Escape-key close via window registry
 *
 * Usage:
 *   <ihim-panel id="my-window" class="my-window" persist-key="myWindowPosition">
 *     <div data-drag-handle class="my-header">Title <button data-close-btn>&times;</button></div>
 *     <div>Content</div>
 *   </ihim-panel>
 *
 * Visibility controlled by [open] attribute (like <dialog>/<details>).
 * Public API: open(), close(), toggle(), minimize()
 * Events: panel:open, panel:close (bubble)
 */

import { makeDraggable } from '../draggable.js';
import { initWindowEscapeClose } from '../a11y.js';

// Click-to-focus: monotonic counter shared across all ihim-panels.
// Pointerdown anywhere in a panel raises it above its siblings.
let topZ = 100;

class IhimPanel extends HTMLElement {
    connectedCallback() {
        // Defer to ensure light-DOM children are parsed
        queueMicrotask(() => this._setup());
    }

    _setup() {
        if (this._initialized) return;
        this._initialized = true;

        const persistKey = this.getAttribute('persist-key');

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

        // Open-state persistence: re-open panels that were open last session.
        // localStorage[`${persistKey}-open`] = "1" while open, removed on close.
        if (persistKey && localStorage.getItem(`${persistKey}-open`) === '1') {
            this.open();
        }
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
                const w = Math.round(entry.contentRect.width);
                const h = Math.round(entry.contentRect.height);
                if (w === 0 || h === 0) continue;
                const c = clamp(w, h);
                localStorage.setItem(sizeKey, JSON.stringify(c));
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
        if (persistKey) localStorage.setItem(`${persistKey}-open`, '1');
        this.dispatchEvent(new CustomEvent('panel:open', { bubbles: true }));
    }

    close() {
        const persistKey = this.getAttribute('persist-key');
        this.removeAttribute('open');
        if (persistKey) localStorage.removeItem(`${persistKey}-open`);
        this.dispatchEvent(new CustomEvent('panel:close', { bubbles: true }));
    }

    toggle() {
        if (this.hasAttribute('open')) this.close();
        else this.open();
    }

    minimize() {
        this.classList.add('minimized');
    }
}

customElements.define('ihim-panel', IhimPanel);
