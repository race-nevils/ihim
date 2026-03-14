/**
 * pipeline-observer.js — Pipeline health dashboard widget
 *
 * Standards:
 *   - draft-inadarei-api-health-check-06 (response format)
 *   - WAI-ARIA Graphics Module 1.0 (sparkline SVGs)
 *   - WCAG 1.1.1, 1.4.1, 2.3.3 (accessibility)
 *   - HTML <time> element (semantic timestamps)
 */
import { API, formatTimestamp } from './app.js';

const POLL_INTERVAL = 30_000; // 30s

export const pipelineObserver = {
    pollTimer: null,
    lastData: null,

    init() {
        this.load();
        this.startPolling();
    },

    startPolling() {
        this.stopPolling();
        this.pollTimer = setInterval(() => this.load(), POLL_INTERVAL);
    },

    stopPolling() {
        if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
    },

    async load() {
        try {
            const res = await fetch(`${API}/api/pipeline/status`);
            if (!res.ok && res.status !== 503) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.lastData = data;
            this.render(data);
        } catch (err) {
            console.error('Pipeline status fetch failed:', err);
            this.renderError();
        }
    },

    render(data) {
        this._renderStatus(data.status);
        this._renderMetrics(data.checks);
        this._renderTrends(data._trends, data.status);
        this._renderDetails(data.checks);
        this._renderErrors(data._errors || []);
    },

    renderError() {
        const statusEl = document.getElementById('pipeline-status');
        if (statusEl) {
            statusEl.className = 'pipeline-status pipeline-fail';
            statusEl.innerHTML = `
                <span class="pipeline-light"></span>
                <i data-lucide="x-circle" class="pipeline-status-icon"></i>
                <span>Unreachable</span>
            `;
            _refreshIcons();
        }
    },

    // --- Status indicator (WCAG 1.4.1: text + icon alongside color) ---
    _renderStatus(status) {
        const el = document.getElementById('pipeline-status');
        if (!el) return;

        const config = {
            pass:  { label: 'Healthy',  icon: 'check-circle', cls: 'pipeline-pass' },
            warn:  { label: 'Warning',  icon: 'alert-triangle', cls: 'pipeline-warn' },
            fail:  { label: 'Critical', icon: 'x-circle', cls: 'pipeline-fail' },
        };
        const c = config[status] || config.fail;

        el.className = `pipeline-status ${c.cls}`;
        el.innerHTML = `
            <span class="pipeline-light"></span>
            <i data-lucide="${c.icon}" class="pipeline-status-icon"></i>
            <span>${c.label}</span>
        `;
        _refreshIcons();
    },

    // --- Metric cards ---
    _renderMetrics(checks) {
        const metrics = [
            { id: 'pipeline-metric-entries',    key: 'graph:entries',       label: 'Entries',    unit: '' },
            { id: 'pipeline-metric-relations',  key: 'graph:relations',    label: 'Relations',  unit: '' },
            { id: 'pipeline-metric-orphans',    key: 'graph:orphanRate',   label: 'Orphan Rate',unit: '' },
            { id: 'pipeline-metric-embeddings', key: 'embeddings:coverage',label: 'Embeddings', unit: '%' },
        ];

        for (const m of metrics) {
            const el = document.getElementById(m.id);
            if (!el) continue;

            const check = checks[m.key]?.[0];
            if (!check) { el.querySelector('.pipeline-metric-value').textContent = '--'; continue; }

            const val = check.observedValue;
            let display;
            if (m.key === 'graph:orphanRate') {
                display = val != null ? `${(val * 100).toFixed(1)}%` : '--';
            } else if (m.unit === '%') {
                display = val != null ? `${val}%` : '--';
            } else {
                display = val != null ? val.toLocaleString() : '--';
            }

            el.querySelector('.pipeline-metric-value').textContent = display;
            el.className = `pipeline-metric pipeline-metric-${check.status || 'pass'}`;
        }
    },

    // --- Sparkline bar charts (WAI-ARIA Graphics Module 1.0) ---
    _renderTrends(trends, overallStatus) {
        if (!trends) return;

        const entryEl = document.getElementById('pipeline-trend-entries');
        if (entryEl && trends.entries?.length > 0) {
            entryEl.innerHTML = _buildSparkline(
                trends.entries,
                'Entry count trend',
                `Last ${trends.entries.length} rebuilds: ${trends.entries.join(', ')}`,
                overallStatus
            );
        }
    },

    // --- Detail rows: rebuild, watcher ---
    _renderDetails(checks) {
        // Last rebuild
        const rebuildEl = document.getElementById('pipeline-detail-rebuild');
        if (rebuildEl) {
            const rb = checks['rebuild:lastRun']?.[0];
            if (rb) {
                const ts = rb.observedValue;
                rebuildEl.innerHTML = ts
                    ? `<span class="pipeline-detail-label">Last Rebuild</span>${_timeTag(ts)} — ${_esc(rb.output || '')}`
                    : `<span class="pipeline-detail-label">Last Rebuild</span><span>${_esc(rb.output || 'Unknown')}</span>`;
            }
        }

        // Watcher
        const watcherEl = document.getElementById('pipeline-detail-watcher');
        if (watcherEl) {
            const w = checks['watcher:heartbeat']?.[0];
            if (w) {
                const badge = w.status === 'pass' ? 'pipeline-badge-pass'
                    : w.status === 'warn' ? 'pipeline-badge-warn' : 'pipeline-badge-fail';
                const label = w.observedValue ? 'Running' : 'Stopped';
                watcherEl.innerHTML = `
                    <span class="pipeline-detail-label">Watcher</span>
                    <span class="pipeline-badge ${badge}">${label}</span>
                    <span class="pipeline-detail-text">${_esc(w.output || '')}</span>
                `;
            }
        }
    },

    // --- Error list (hidden when empty) ---
    _renderErrors(errors) {
        const container = document.getElementById('pipeline-errors');
        if (!container) return;

        if (!errors.length) {
            container.style.display = 'none';
            return;
        }

        container.style.display = '';
        const list = container.querySelector('.pipeline-error-list');
        if (!list) return;

        list.innerHTML = errors.map(err => {
            const ts = err.timestamp || err.time || '';
            const phase = err.phase || '';
            const msg = err.error || err.message || JSON.stringify(err);
            return `<div class="pipeline-error-item">
                ${ts ? _timeTag(ts) : ''}
                ${phase ? `<span class="pipeline-error-phase">${_esc(phase)}</span>` : ''}
                <span class="pipeline-error-msg">${_esc(msg)}</span>
            </div>`;
        }).join('');
    },
};


// =============================================================================
// Public API
// =============================================================================

export function openPipelineObserver() {
    const panel = document.getElementById('pipeline-observer-window');
    if (!panel) return;
    panel.open();
    pipelineObserver.init();
}

export function closePipelineObserver() {
    pipelineObserver.stopPolling();
    const panel = document.getElementById('pipeline-observer-window');
    if (panel) panel.close();
}


// =============================================================================
// Helpers
// =============================================================================

/** Build accessible SVG sparkline bar chart (WAI-ARIA Graphics Module 1.0). */
function _buildSparkline(values, title, description, status) {
    if (!values.length) return '';

    const w = 200, h = 40, gap = 2;
    const barWidth = Math.max(2, (w - gap * (values.length - 1)) / values.length);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;

    const color = status === 'fail' ? 'var(--status-error)'
        : status === 'warn' ? 'var(--status-warning)'
        : 'var(--status-success)';

    const titleId = `spark-title-${Date.now()}`;
    const descId = `spark-desc-${Date.now()}`;

    const bars = values.map((v, i) => {
        const barH = Math.max(2, ((v - min) / range) * (h - 4));
        const x = i * (barWidth + gap);
        const y = h - barH;
        return `<rect role="graphics-object" aria-label="Rebuild ${i + 1}: ${v}"
            x="${x}" y="${y}" width="${barWidth}" height="${barH}"
            fill="${color}" rx="1" opacity="${0.5 + (i / values.length) * 0.5}"/>`;
    }).join('');

    return `<svg role="graphics-document" aria-roledescription="bar chart"
        aria-labelledby="${titleId} ${descId}"
        viewBox="0 0 ${w} ${h}" width="100%" height="${h}"
        preserveAspectRatio="xMidYMid meet">
        <title id="${titleId}">${_esc(title)}</title>
        <desc id="${descId}">${_esc(description)}</desc>
        <g role="graphics-object" aria-label="data series">${bars}</g>
    </svg>`;
}

/** HTML <time> element with ISO datetime + human-friendly display. */
function _timeTag(isoString) {
    if (!isoString) return '';
    const display = formatTimestamp(isoString);
    return `<time datetime="${_esc(isoString)}" title="${_esc(isoString)}">${display}</time>`;
}

function _esc(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

function _refreshIcons() {
    requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
}
