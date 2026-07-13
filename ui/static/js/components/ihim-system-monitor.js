/**
 * <ihim-system-monitor> — CPU/RAM bottom-bar widget Web Component
 * Renders its own markup and owns the 2s polling interval
 * (starts on connect, stops on disconnect).
 *
 * Usage:
 *   <ihim-system-monitor class="bar-widget"></ihim-system-monitor>
 */

import { API } from '../app.js';

const POLL_INTERVAL = 2_000;

class IhimSystemMonitor extends HTMLElement {
    connectedCallback() {
        this.innerHTML = `
            <span class="bar-label">CPU</span>
            <span class="bar-value" data-cpu>--</span>
            <span class="bar-sep">|</span>
            <span class="bar-label">RAM</span>
            <span class="bar-value" data-ram>--</span>
        `;
        this._update();
        this._timer = setInterval(() => this._update(), POLL_INTERVAL);
    }

    disconnectedCallback() {
        if (this._timer) { clearInterval(this._timer); this._timer = null; }
    }

    async _update() {
        try {
            const res = await fetch(`${API}/api/system/stats`);
            const data = await res.json();
            this.querySelector('[data-cpu]').textContent = data.cpu?.percent ?? '--';
            this.querySelector('[data-ram]').textContent = data.memory?.percent ?? '--';
        } catch (err) { /* silent — bar shows last value */ }
    }
}

customElements.define('ihim-system-monitor', IhimSystemMonitor);
