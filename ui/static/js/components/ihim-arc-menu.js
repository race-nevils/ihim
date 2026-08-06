/**
 * <ihim-arc-menu> — bottom-left system menu: screen-level actions that don't
 * deserve a desktop tile live here, behind a start-menu-style button at the
 * left end of the bottom bar. The trigger is a bare three-dot glyph, borderless
 * until hover (2026-08-06 — it replaced a drawn arc-reactor mark, which read as
 * decoration next to the flat bar chips).
 *
 * Light DOM, styled from style.css (.arc-*, .hud-menu*). WAI-ARIA menu-button
 * pattern: aria-expanded on the trigger, role="menu"/"menuitem"; Escape or
 * an outside click closes. The dropdown opens UPWARD (the bar is at the
 * bottom of the screen).
 *
 * Usage: <ihim-arc-menu id="arc-menu"></ihim-arc-menu>
 */

import { restartServer } from '../app.js';

class IhimArcMenu extends HTMLElement {
    abortController = null;

    connectedCallback() {
        if (this._built) return;
        this._built = true;

        this.innerHTML = `
            <button class="arc-btn" aria-label="System menu"
                    aria-haspopup="menu" aria-expanded="false">
                <i data-lucide="ellipsis-vertical"></i>
            </button>
            <div class="hud-menu arc-menu-dropdown" role="menu" hidden>
                <button class="hud-menu-item" role="menuitem" data-action="restart">
                    <i data-lucide="refresh-cw"></i>Restart Server
                </button>
            </div>
        `;
        this._btn = this.querySelector('.arc-btn');
        this._menu = this.querySelector('.arc-menu-dropdown');

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

customElements.define('ihim-arc-menu', IhimArcMenu);
