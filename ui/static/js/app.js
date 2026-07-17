/**
 * app.js — Shared constants and utilities.
 * Pure exports only — no component imports (avoids circular deps).
 * The CPU/RAM system monitor lives in components/ihim-system-monitor.js.
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
    'mic': 'mic', 'git-branch': 'git-branch',
    'heart-pulse': 'heart-pulse', 'list-todo': 'list-todo', 'timer': 'timer',
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
