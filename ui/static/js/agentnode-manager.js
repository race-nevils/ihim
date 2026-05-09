/**
 * agentnode-manager.js — agent node Agent Node dashboard panel
 *
 * Manages the agent node panel: status polling, system metrics, agent
 * task queue, model info, and power controls. Talks to iHIM backend
 * which proxies to agent node over the private link.
 */
import { API, escapeHtml, formatTimestamp } from './app.js';

const POLL_INTERVAL = 15_000; // 15s — agent node status is latency-sensitive

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let pollTimer = null;
let lastStatus = null;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function openAgentNodeWindow() {
    document.getElementById('agentnode-window')?.open();
}

export function closeAgentNodeWindow() {
    document.getElementById('agentnode-window')?.close();
}

export function initAgentNodeEvents() {
    const win = document.getElementById('agentnode-window');
    if (!win) return;

    // Refresh button
    win.querySelector('.k8-refresh-btn')?.addEventListener('click', refreshStatus);

    // Power controls
    win.querySelector('.k8-power-shutdown')?.addEventListener('click', () => powerAction('shutdown'));
    win.querySelector('.k8-power-reboot')?.addEventListener('click', () => powerAction('reboot'));
    win.querySelector('.k8-power-wol')?.addEventListener('click', () => powerAction('wol'));

    // Task submit
    win.querySelector('.k8-task-submit')?.addEventListener('click', submitTask);
    win.querySelector('#k8-task-input')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitTask(); }
    });

    // Data init on panel open (manual click + auto-restore on reload).
    win.addEventListener('panel:open', () => {
        refreshStatus();
        startPolling();
    });

    // Stop polling when panel closes
    win.addEventListener('panel:close', () => stopPolling());
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

function startPolling() {
    stopPolling();
    pollTimer = setInterval(refreshStatus, POLL_INTERVAL);
}

function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

// ---------------------------------------------------------------------------
// Status fetch + render
// ---------------------------------------------------------------------------

async function refreshStatus() {
    try {
        const res = await fetch(`${API}/api/agentnode/status`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        lastStatus = data;
        render(data);
    } catch (err) {
        console.error('agent node status fetch failed:', err);
        renderOffline();
    }
}

function render(data) {
    renderConnectionStatus(data.status);
    renderSystemMetrics(data.system);
    renderAgentStatus(data.agent);
    renderModelStatus(data.model);
    renderTimestamp(data.timestamp);
    _refreshIcons();
}

function renderOffline() {
    renderConnectionStatus('offline');
    renderSystemMetrics(null);
    renderAgentStatus(null);
    renderModelStatus(null);
    _refreshIcons();
}

// ---------------------------------------------------------------------------
// Connection status indicator
// ---------------------------------------------------------------------------

function renderConnectionStatus(status) {
    const el = document.getElementById('k8-connection-status');
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
    const shutdownBtn = document.querySelector('.k8-power-shutdown');
    const rebootBtn = document.querySelector('.k8-power-reboot');
    const wolBtn = document.querySelector('.k8-power-wol');
    const taskSection = document.querySelector('.k8-task-section');

    if (status === 'offline') {
        shutdownBtn?.classList.add('hidden');
        rebootBtn?.classList.add('hidden');
        wolBtn?.classList.remove('hidden');
        taskSection?.classList.add('hidden');
    } else {
        shutdownBtn?.classList.remove('hidden');
        rebootBtn?.classList.remove('hidden');
        wolBtn?.classList.add('hidden');
        taskSection?.classList.remove('hidden');
    }
}

// ---------------------------------------------------------------------------
// System metrics (CPU, RAM, temp, uptime)
// ---------------------------------------------------------------------------

function renderSystemMetrics(system) {
    const grid = document.getElementById('k8-metrics-grid');
    if (!grid) return;

    if (!system) {
        grid.querySelectorAll('.k8-metric-value').forEach(el => el.textContent = '--');
        return;
    }

    _setMetric('k8-metric-cpu', system.cpu_percent, '%');
    _setMetric('k8-metric-ram', system.ram_percent, '%', system.ram_used_gb ? `${system.ram_used_gb}GB` : null);
    _setMetric('k8-metric-temp', system.cpu_temp, '\u00B0C');
    _setMetric('k8-metric-uptime', null, '', system.uptime || '--');
}

function _setMetric(id, value, unit, displayOverride) {
    const el = document.getElementById(id);
    if (!el) return;
    const valEl = el.querySelector('.k8-metric-value');
    if (!valEl) return;
    valEl.textContent = displayOverride || (value != null ? `${value}${unit}` : '--');
}

// ---------------------------------------------------------------------------
// Agent status
// ---------------------------------------------------------------------------

function renderAgentStatus(agent) {
    const el = document.getElementById('k8-agent-status');
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

// ---------------------------------------------------------------------------
// Model status
// ---------------------------------------------------------------------------

function renderModelStatus(model) {
    const el = document.getElementById('k8-model-status');
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

// ---------------------------------------------------------------------------
// Timestamp
// ---------------------------------------------------------------------------

function renderTimestamp(ts) {
    const el = document.getElementById('k8-last-update');
    if (!el || !ts) return;
    el.textContent = `Updated ${formatTimestamp(ts)}`;
}

// ---------------------------------------------------------------------------
// Power actions
// ---------------------------------------------------------------------------

async function powerAction(action) {
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

        const statusEl = document.getElementById('k8-power-feedback');
        if (statusEl) {
            statusEl.textContent = `${label} ${action === 'wol' ? 'packet sent' : 'initiated'}`;
            statusEl.className = 'k8-power-feedback k8-power-success';
            setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'k8-power-feedback'; }, 5000);
        }

        // If shutdown/reboot, refresh status after delay
        if (action !== 'wol') {
            setTimeout(refreshStatus, 3000);
        } else {
            // WoL — poll for agent node to come online
            setTimeout(refreshStatus, 10000);
        }
    } catch (err) {
        alert(`${label} failed: ${err.message}`);
    }
}

// ---------------------------------------------------------------------------
// Task submission
// ---------------------------------------------------------------------------

async function submitTask() {
    const input = document.getElementById('k8-task-input');
    if (!input) return;

    const prompt = input.value.trim();
    if (!prompt) return;

    const submitBtn = document.querySelector('.k8-task-submit');
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
        refreshStatus(); // Refresh to show new task
    } catch (err) {
        alert(`Task submission failed: ${err.message}`);
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _refreshIcons() {
    requestAnimationFrame(() => { if (window.lucide) lucide.createIcons(); });
}
