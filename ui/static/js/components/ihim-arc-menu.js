/**
 * <ihim-arc-menu> — bottom-left arc-reactor system menu (2026-08-06, replaced
 * the top-right <ihim-options> ⋮): screen-level actions that don't deserve a
 * desktop tile live here, behind a start-menu-style button at the left end of
 * the bottom bar. The button is the reactor itself — an inline SVG Mark-I
 * mark in the HUD palette (gunmetal housing, dark-copper coil segments,
 * crimson core), drawn from the design tokens' hex values (SVG attributes
 * can't read CSS custom properties in all paint contexts, so the colors are
 * inlined).
 *
 * Light DOM, styled from style.css (.arc-*, .hud-menu*). WAI-ARIA menu-button
 * pattern: aria-expanded on the trigger, role="menu"/"menuitem"; Escape or
 * an outside click closes. The dropdown opens UPWARD (the bar is at the
 * bottom of the screen).
 *
 * Usage: <ihim-arc-menu id="arc-menu"></ihim-arc-menu>
 */

import { restartServer } from '../app.js';

// Mark-I reactor, viewBox 64: housing ring → 10 copper coil segments (stroke
// dasharray = circumference/10 minus the gap) → crimson tick ring → radial
// core → Y-strut + hub. Coils are dark copper (#8E4F2E / #B87333 edge) — the
// winding the current runs through, muted so it sits INTO the dark HUD rather
// than popping off it; #4A5568 gunmetal, #DC143C crimson, #0b0b0d surface.
const REACTOR_SVG = `
<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <defs>
        <radialGradient id="ihim-arc-core">
            <stop offset="0%" stop-color="#ffe0e6"/>
            <stop offset="35%" stop-color="#ff5d78"/>
            <stop offset="75%" stop-color="#DC143C"/>
            <stop offset="100%" stop-color="rgba(220, 20, 60, 0)"/>
        </radialGradient>
    </defs>
    <circle cx="32" cy="32" r="30" fill="#0b0b0d" stroke="#4A5568" stroke-width="2.5"/>
    <circle cx="32" cy="32" r="26.5" fill="none" stroke="rgba(74, 85, 104, 0.55)" stroke-width="1"/>
    <g class="arc-coils">
        <circle cx="32" cy="32" r="21.5" fill="none" stroke="#8E4F2E" stroke-width="7"
                stroke-dasharray="9.8 3.709"/>
        <circle cx="32" cy="32" r="24.2" fill="none" stroke="#B87333" stroke-width="1.2"
                stroke-dasharray="11.03 4.175" opacity="0.55"/>
    </g>
    <circle cx="32" cy="32" r="15" fill="none" stroke="#DC143C" stroke-width="1.6"
            stroke-dasharray="2.2 3.036" opacity="0.85"/>
    <circle cx="32" cy="32" r="12" fill="url(#ihim-arc-core)"/>
    <path d="M32 32 L32 21 M32 32 L22.47 37.5 M32 32 L41.53 37.5"
          stroke="#14161c" stroke-width="1.8" stroke-linecap="round" fill="none"/>
    <circle cx="32" cy="32" r="2.2" fill="#1a1d24" stroke="#4A5568" stroke-width="0.8"/>
</svg>`;

class IhimArcMenu extends HTMLElement {
    abortController = null;

    connectedCallback() {
        if (this._built) return;
        this._built = true;

        this.innerHTML = `
            <button class="arc-btn" aria-label="System menu"
                    aria-haspopup="menu" aria-expanded="false">${REACTOR_SVG}</button>
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
