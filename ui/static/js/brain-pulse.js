/**
 * brain-pulse.js — Brain stats at-a-glance widget
 *
 * Fetches /api/brain/stats and renders a compact card showing
 * total entries, embedding coverage, and top categories.
 * No polling — snapshot on open.
 */
import { API } from './app.js';

export const brainPulse = {
    loaded: false,

    init() {
        if (!this.loaded) this.load();
    },

    async load() {
        try {
            const res = await fetch(`${API}/api/brain/stats`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.loaded = true;
            this.render(data);
        } catch (err) {
            console.error('Brain pulse fetch failed:', err);
            this.renderError();
        }
    },

    render(data) {
        const statusEl = document.getElementById('bp-status');
        const totalEl = document.getElementById('bp-total');
        const coverageEl = document.getElementById('bp-coverage');
        const listEl = document.getElementById('bp-category-list');

        if (!statusEl) return;

        // Status indicator
        const ok = data.total_entries > 0;
        statusEl.className = `bp-status ${ok ? 'bp-pass' : 'bp-warn'}`;
        statusEl.innerHTML = `<span class="bp-light"></span><span>${ok ? 'Healthy' : 'Empty'}</span>`;

        // Metrics
        if (totalEl) totalEl.textContent = data.total_entries ?? '--';
        if (coverageEl) coverageEl.textContent = data.embedding_coverage ?? '--';

        // Top categories (sorted by count, top 5)
        if (listEl && data.categories) {
            const sorted = Object.entries(data.categories)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 5);

            listEl.innerHTML = sorted.map(([name, count]) =>
                `<div class="bp-category-row">
                    <span class="bp-cat-name">${name}</span>
                    <span class="bp-cat-count">${count}</span>
                </div>`
            ).join('');
        }
    },

    renderError() {
        const statusEl = document.getElementById('bp-status');
        if (statusEl) {
            statusEl.className = 'bp-status bp-fail';
            statusEl.innerHTML = '<span class="bp-light"></span><span>Offline</span>';
        }
    },
};

export function openBrainPulse() {
    const win = document.getElementById('brain-pulse-window');
    if (win) { win.open(); brainPulse.init(); }
}

export function closeBrainPulse() {
    const win = document.getElementById('brain-pulse-window');
    if (win) win.close();
}
