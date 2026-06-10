/**
 * app.js — Shared constants, utilities, and the system monitor.
 * Pure exports only — no feature module imports (avoids circular deps).
 */

// API base URL (empty = same origin)
export const API = '';

// =====================
// Utilities
// =====================

export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

export function showStatus(message, type) {
    const status = document.getElementById('status');
    if (!status) return;
    status.textContent = message;
    status.className = `status ${type}`;
    setTimeout(() => { status.className = 'status'; }, 3000);
}

export function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (date.getFullYear() === now.getFullYear()) {
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

// Lucide icon names for desktop tiles
const LUCIDE_ICONS = {
    'mic': 'mic', 'git-branch': 'git-branch', 'calendar': 'calendar-days',
    'heart-pulse': 'heart-pulse', 'archive': 'archive', 'timer': 'timer',
    'restart': 'refresh-cw', 'default': 'zap',
};

export function getIcon(icon) {
    return `<i data-lucide="${LUCIDE_ICONS[icon] || LUCIDE_ICONS['default']}"></i>`;
}

// =====================
// Server Restart
// =====================

export async function restartServer() {
    if (!confirm('Restart the iHIM server? The page will reconnect automatically.')) return;

    showStatus('Restarting server...', 'pending');
    document.body.style.opacity = '0.5';

    try { await fetch(`${API}/api/server/restart`, { method: 'POST' }); }
    catch (err) { /* expected — server goes down before responding */ }

    await new Promise(r => setTimeout(r, 3000));

    let attempts = 0;
    const maxAttempts = 30;
    let consecutiveOk = 0;
    const pollInterval = setInterval(async () => {
        attempts++;
        try {
            const res = await fetch(`${API}/api/health`, { cache: 'no-store' });
            if (res.ok) {
                consecutiveOk++;
                if (consecutiveOk >= 2) {
                    clearInterval(pollInterval);
                    document.body.style.opacity = '1';
                    showStatus('Server back online!', 'success');
                    setTimeout(() => location.reload(), 500);
                }
            } else { consecutiveOk = 0; }
        } catch (err) {
            consecutiveOk = 0;
            if (attempts >= maxAttempts) {
                clearInterval(pollInterval);
                document.body.style.opacity = '1';
                showStatus('Server not responding. Refresh manually.', 'error');
            }
        }
    }, 1500);
}

// =====================
// System Monitor (CPU/RAM bottom-bar widget)
// =====================

let systemMonitorInterval = null;

export async function updateSystemMonitor() {
    try {
        const res = await fetch(`${API}/api/system/stats`);
        const data = await res.json();
        const cpuEl = document.getElementById('cpu-value');
        const ramEl = document.getElementById('ram-value');
        if (cpuEl) cpuEl.textContent = data.cpu?.percent ?? '--';
        if (ramEl) ramEl.textContent = data.memory?.percent ?? '--';
    } catch (err) { /* silent — bar shows last value */ }
}

export function startSystemMonitor() {
    if (systemMonitorInterval) return;
    systemMonitorInterval = setInterval(updateSystemMonitor, 2000);
}

export function stopSystemMonitor() {
    if (systemMonitorInterval) {
        clearInterval(systemMonitorInterval);
        systemMonitorInterval = null;
    }
}
