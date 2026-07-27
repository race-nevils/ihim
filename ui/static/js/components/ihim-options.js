/**
 * <ihim-options> — top-right ⋮ system menu: screen-level actions that don't
 * deserve a desktop tile.
 *
 * Light DOM, styled from style.css (.options-*). WAI-ARIA menu-button
 * pattern: aria-expanded on the trigger, role="menu"/"menuitem"; Escape or
 * an outside click closes.
 *
 * Usage: <ihim-options id="options-menu"></ihim-options>
 */

import { restartServer } from '../app.js';

class IhimOptions extends HTMLElement {
    abortController = null;

    connectedCallback() {
        if (this._built) return;
        this._built = true;

        this.innerHTML = `
            <button class="options-btn" aria-label="System options"
                    aria-haspopup="menu" aria-expanded="false">
                <i data-lucide="ellipsis-vertical"></i>
            </button>
            <div class="options-dropdown" role="menu" hidden>
                <button class="options-item" role="menuitem" data-action="restart">
                    <i data-lucide="refresh-cw"></i>Restart Server
                </button>
            </div>
        `;
        this._btn = this.querySelector('.options-btn');
        this._menu = this.querySelector('.options-dropdown');

        this.abortController = new AbortController();
        const signal = this.abortController.signal;

        this._btn.addEventListener('click', () => this.toggle(), { signal });
        this.querySelector('[data-action="restart"]').addEventListener('click', () => {
            this.close();
            restartServer();
        }, { signal });
        document.addEventListener('click', (e) => {
            if (!this._menu.hidden && !this.contains(e.target)) this.close();
        }, { signal });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !this._menu.hidden) { this.close(); this._btn.focus(); }
        }, { signal });

        requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
    }

    disconnectedCallback() {
        if (this.abortController) { this.abortController.abort(); this.abortController = null; }
    }

    toggle() { this._menu.hidden ? this.open() : this.close(); }

    open() {
        this._menu.hidden = false;
        this._btn.setAttribute('aria-expanded', 'true');
    }

    close() {
        this._menu.hidden = true;
        this._btn.setAttribute('aria-expanded', 'false');
    }
}

customElements.define('ihim-options', IhimOptions);
