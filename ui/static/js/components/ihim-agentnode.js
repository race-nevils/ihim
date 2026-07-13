/**
 * <ihim-agentnode> — agent node Agent Node window: status polling, system metrics,
 * agent task queue, model info, and power controls. Talks to the iHIM backend
 * which proxies to agent node over the private link.
 * Extends IhimPanel: IS the draggable window; polls while open, stops on close.
 */
import { API, escapeHtml, formatTimestamp } from '../app.js';
import { IhimPanel } from './ihim-panel.js';

const POLL_INTERVAL = 15_000; // 15s — agent node status is latency-sensitive

class IhimAgentNode extends IhimPanel {
    _pollTimer = null;

    connectedCallback() {
        this.innerHTML = `
            <div class="k8-header" data-drag-handle>
                <span class="k8-label">agent node</span>
                <div class="k8-header-actions">
                    <button class="k8-refresh-btn" aria-label="Refresh agent node Status" title="Refresh">
                        <i data-lucide="refresh-cw" style="width:14px;height:14px;"></i>
                    </button>
                    <button class="k8-close" data-close-btn aria-label="Close agent node Panel">&times;</button>
                </div>
            </div>
            <div class="k8-body">
                <!-- Connection Status -->
                <div id="k8-connection-status" class="k8-connection-status k8-status-offline" role="status" aria-live="polite" aria-atomic="true">
                    <span class="k8-status-light"></span>
                    <i data-lucide="wifi-off" class="k8-status-icon"></i>
                    <span>Checking...</span>
                </div>

                <!-- System Metrics Grid (2x2) -->
                <div id="k8-metrics-grid" class="k8-metrics-grid">
                    <div id="k8-metric-cpu" class="k8-metric">
                        <span class="k8-metric-label">CPU</span>
                        <span class="k8-metric-value">--</span>
                    </div>
                    <div id="k8-metric-ram" class="k8-metric">
                        <span class="k8-metric-label">RAM</span>
                        <span class="k8-metric-value">--</span>
                    </div>
                    <div id="k8-metric-temp" class="k8-metric">
                        <span class="k8-metric-label">Temp</span>
                        <span class="k8-metric-value">--</span>
                    </div>
                    <div id="k8-metric-uptime" class="k8-metric">
                        <span class="k8-metric-label">Uptime</span>
                        <span class="k8-metric-value">--</span>
                    </div>
                </div>

                <!-- Agent Status -->
                <div class="k8-section">
                    <span class="k8-section-label">Agent</span>
                    <div id="k8-agent-status" class="k8-agent-status">
                        <span class="k8-agent-idle">No data</span>
                    </div>
                </div>

                <!-- Model Status -->
                <div class="k8-section">
                    <span class="k8-section-label">Model</span>
                    <div id="k8-model-status" class="k8-model-status">
                        <span class="k8-model-none">No data</span>
                    </div>
                </div>

                <!-- Task Input -->
                <div class="k8-task-section">
                    <span class="k8-section-label">Send Task</span>
                    <div class="k8-task-input-row">
                        <input type="text" id="k8-task-input" class="k8-task-input" placeholder="Describe task for agent..." autocomplete="off">
                        <button class="k8-task-submit" aria-label="Submit Task">
                            <i data-lucide="send" style="width:14px;height:14px;"></i>
                        </button>
                    </div>
                </div>

                <!-- Power Controls -->
                <div class="k8-power-section">
                    <span class="k8-section-label">Power</span>
                    <div class="k8-power-buttons">
                        <button class="k8-power-btn k8-power-wol" title="Wake on LAN">
                            <i data-lucide="power" style="width:14px;height:14px;"></i> Wake
                        </button>
                        <button class="k8-power-btn k8-power-reboot hidden" title="Reboot">
                            <i data-lucide="rotate-ccw" style="width:14px;height:14px;"></i> Reboot
                        </button>
                        <button class="k8-power-btn k8-power-shutdown hidden" title="Shutdown">
                            <i data-lucide="power-off" style="width:14px;height:14px;"></i> Shutdown
                        </button>
                    </div>
                    <span id="k8-power-feedback" class="k8-power-feedback"></span>
                </div>
            </div>
            <div class="k8-footer">
                <span id="k8-last-update">Polls every 15s</span>
                <span class="k8-host-label">192.168.20.2</span>
            </div>
        `;
        this._wireEvents();
        super.connectedCallback();
    }

    disconnectedCallback() {
        this._stopPolling();
    }

    _el(id) { return this.querySelector(`#${id}`); }

    _wireEvents() {
        // Refresh button
        this.querySelector('.k8-refresh-btn').addEventListener('click', () => this._refreshStatus());

        // Power controls
        this.querySelector('.k8-power-shutdown').addEventListener('click', () => this._powerAction('shutdown'));
        this.querySelector('.k8-power-reboot').addEventListener('click', () => this._powerAction('reboot'));
        this.querySelector('.k8-power-wol').addEventListener('click', () => this._powerAction('wol'));

        // Task submit
        this.querySelector('.k8-task-submit').addEventListener('click', () => this._submitTask());
        this._el('k8-task-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._submitTask(); }
        });

        // Data init on open (manual click + auto-restore on reload).
        this.addEventListener('panel:open', () => {
            this._refreshStatus();
            this._startPolling();
        });

        // Stop polling when the window closes
        this.addEventListener('panel:close', () => this._stopPolling());
    }

    // -----------------------------------------------------------------------
    // Polling
    // -----------------------------------------------------------------------

    _startPolling() {
        this._stopPolling();
        this._pollTimer = setInterval(() => this._refreshStatus(), POLL_INTERVAL);
    }

    _stopPolling() {
        if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
    }

    // -----------------------------------------------------------------------
    // Status fetch + render
    // -----------------------------------------------------------------------

    async _refreshStatus() {
        try {
            const res = await fetch(`${API}/api/agentnode/status`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this._render(data);
        } catch (err) {
            console.error('agent node status fetch failed:', err);
            this._renderOffline();
        }
    }

    _render(data) {
        this._renderConnectionStatus(data.status);
        this._renderSystemMetrics(data.system);
        this._renderAgentStatus(data.agent);
        this._renderModelStatus(data.model);
        this._renderTimestamp(data.timestamp);
        this._refreshIcons();
    }

    _renderOffline() {
        this._renderConnectionStatus('offline');
        this._renderSystemMetrics(null);
        this._renderAgentStatus(null);
        this._renderModelStatus(null);
        this._refreshIcons();
    }

    _renderConnectionStatus(status) {
        const el = this._el('k8-connection-status');
        if (!el) return;

        const config = {
            online:   { label: 'Online',   icon: 'wifi',     cls: 'k8-status-online' },
            degraded: { label: 'Degraded', icon: 'wifi-off', cls: 'k8-status-degraded' },
            offline:  { label: 'Offline',  icon: 'wifi-off', cls: 'k8-status-offline' },
        };
        const c = config[status] || config.offline;

        el.className = `k8-connection-status ${c.cls}`;
        el.innerHTML = `
            <span class="k8-status-light"></span>
            <i data-lucide="${c.icon}" class="k8-status-icon"></i>
            <span>${c.label}</span>
        `;

        // Toggle power button visibility based on status
        const shutdownBtn = this.querySelector('.k8-power-shutdown');
        const rebootBtn = this.querySelector('.k8-power-reboot');
        const wolBtn = this.querySelector('.k8-power-wol');
        const taskSection = this.querySelector('.k8-task-section');

        if (status === 'offline') {
            shutdownBtn.classList.add('hidden');
            rebootBtn.classList.add('hidden');
            wolBtn.classList.remove('hidden');
            taskSection.classList.add('hidden');
        } else {
            shutdownBtn.classList.remove('hidden');
            rebootBtn.classList.remove('hidden');
            wolBtn.classList.add('hidden');
            taskSection.classList.remove('hidden');
        }
    }

    _renderSystemMetrics(system) {
        const grid = this._el('k8-metrics-grid');
        if (!grid) return;

        if (!system) {
            grid.querySelectorAll('.k8-metric-value').forEach(el => el.textContent = '--');
            return;
        }

        this._setMetric('k8-metric-cpu', system.cpu_percent, '%');
        this._setMetric('k8-metric-ram', system.ram_percent, '%', system.ram_used_gb ? `${system.ram_used_gb}GB` : null);
        this._setMetric('k8-metric-temp', system.cpu_temp, '°C');
        this._setMetric('k8-metric-uptime', null, '', system.uptime || '--');
    }

    _setMetric(id, value, unit, displayOverride) {
        const valEl = this._el(id)?.querySelector('.k8-metric-value');
        if (!valEl) return;
        valEl.textContent = displayOverride || (value != null ? `${value}${unit}` : '--');
    }

    _renderAgentStatus(agent) {
        const el = this._el('k8-agent-status');
        if (!el) return;

        if (!agent) {
            el.innerHTML = '<span class="k8-agent-idle">No data</span>';
            return;
        }

        const statusCls = agent.status === 'busy' ? 'k8-agent-busy' :
                           agent.status === 'error' ? 'k8-agent-error' : 'k8-agent-idle';

        let html = `<span class="${statusCls}">${escapeHtml(agent.status || 'idle')}</span>`;

        if (agent.current_task) {
            html += `<div class="k8-current-task">
                <span class="k8-task-label">Current:</span>
                <span class="k8-task-text">${escapeHtml(agent.current_task)}</span>
            </div>`;
        }

        if (agent.queue_depth != null) {
            html += `<span class="k8-queue-depth">${agent.queue_depth} queued</span>`;
        }

        el.innerHTML = html;
    }

    _renderModelStatus(model) {
        const el = this._el('k8-model-status');
        if (!el) return;

        if (!model) {
            el.innerHTML = '<span class="k8-model-none">No data</span>';
            return;
        }

        let html = `<span class="k8-model-name">${escapeHtml(model.name || model.model || 'Unknown')}</span>`;

        if (model.parameters) {
            html += `<span class="k8-model-params">${escapeHtml(model.parameters)}</span>`;
        }

        if (model.backend) {
            html += `<span class="k8-model-backend">${escapeHtml(model.backend)}</span>`;
        }

        el.innerHTML = html;
    }

    _renderTimestamp(ts) {
        const el = this._el('k8-last-update');
        if (!el || !ts) return;
        el.textContent = `Updated ${formatTimestamp(ts)}`;
    }

    // -----------------------------------------------------------------------
    // Power actions
    // -----------------------------------------------------------------------

    async _powerAction(action) {
        const labels = { shutdown: 'Shut down', reboot: 'Reboot', wol: 'Wake' };
        const label = labels[action] || action;

        if (action !== 'wol' && !confirm(`${label} agent node?`)) return;

        try {
            const res = await fetch(`${API}/api/agentnode/power/${action}`, { method: 'POST' });
            const data = await res.json();

            if (!res.ok) {
                alert(`${label} failed: ${data.detail || data.title || 'Unknown error'}`);
                return;
            }

            const statusEl = this._el('k8-power-feedback');
            if (statusEl) {
                statusEl.textContent = `${label} ${action === 'wol' ? 'packet sent' : 'initiated'}`;
                statusEl.className = 'k8-power-feedback k8-power-success';
                setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'k8-power-feedback'; }, 5000);
            }

            // If shutdown/reboot, refresh status after delay
            if (action !== 'wol') {
                setTimeout(() => this._refreshStatus(), 3000);
            } else {
                // WoL — poll for agent node to come online
                setTimeout(() => this._refreshStatus(), 10000);
            }
        } catch (err) {
            alert(`${label} failed: ${err.message}`);
        }
    }

    // -----------------------------------------------------------------------
    // Task submission
    // -----------------------------------------------------------------------

    async _submitTask() {
        const input = this._el('k8-task-input');
        if (!input) return;

        const prompt = input.value.trim();
        if (!prompt) return;

        const submitBtn = this.querySelector('.k8-task-submit');
        if (submitBtn) submitBtn.disabled = true;

        try {
            const res = await fetch(`${API}/api/agentnode/agent/tasks`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt }),
            });

            if (!res.ok) {
                const err = await res.json();
                alert(`Task failed: ${err.detail || err.title || 'Unknown error'}`);
                return;
            }

            input.value = '';
            this._refreshStatus(); // Refresh to show new task
        } catch (err) {
            alert(`Task submission failed: ${err.message}`);
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    _refreshIcons() {
        requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
    }
}

customElements.define('ihim-agentnode', IhimAgentNode);
