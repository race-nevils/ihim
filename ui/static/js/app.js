/**
 * app.js — Shared constants, utilities, and system monitors.
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

// Lucide icon mapping
const LUCIDE_ICONS = {
    'cli': 'terminal', 'rocket': 'rocket', 'terminal': 'monitor-dot',
    'folder': 'folder-open', 'play': 'play', 'code': 'code-2',
    'team': 'users-round', 'users': 'users-round', 'x': 'x-circle',
    'checklist': 'list-checks', 'note': 'sticky-note', 'flightpath': 'map',
    'map': 'map', 'slash': 'command', 'restart': 'refresh-cw',
    'timer': 'timer', 'verified': 'badge-check', 'shield': 'shield-check',
    'lightbulb': 'lightbulb', 'calendar': 'calendar-days',
    'git-branch': 'git-branch', 'archive': 'archive', 'mic': 'mic', 'default': 'zap'
};

export function getIcon(icon) {
    const iconName = LUCIDE_ICONS[icon] || LUCIDE_ICONS['default'];
    return `<i data-lucide="${iconName}"></i>`;
}

export function createRipple(event) {
    const button = event.currentTarget;
    const rect = button.getBoundingClientRect();
    const existingRipple = button.querySelector('.ripple');
    if (existingRipple) existingRipple.remove();

    const ripple = document.createElement('span');
    ripple.className = 'ripple';
    const size = Math.max(rect.width, rect.height) * 2;
    ripple.style.width = ripple.style.height = size + 'px';
    ripple.style.left = (event.clientX - rect.left - size / 2) + 'px';
    ripple.style.top = (event.clientY - rect.top - size / 2) + 'px';
    button.appendChild(ripple);
    ripple.addEventListener('animationend', () => ripple.remove());
}

// =====================
// Server Restart
// =====================

export async function restartServer() {
    if (!confirm('Restart the iHIM server? The page will reconnect automatically.')) return;

    showStatus('Restarting server...', 'pending');
    document.body.style.opacity = '0.5';

    try { await fetch(`${API}/api/server/restart`, { method: 'POST' }); }
    catch (err) { /* Expected - server dies before responding */ }

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
                    try {
                        const pageRes = await fetch(`${API}/`, { cache: 'no-store' });
                        if (pageRes.ok) {
                            document.body.style.opacity = '1';
                            showStatus('Server back online!', 'success');
                            setTimeout(() => location.reload(), 500);
                            return;
                        }
                    } catch (e) { /* fall through */ }
                    document.body.style.opacity = '1';
                    showStatus('Server up but loading... retrying', 'pending');
                    setTimeout(() => location.reload(), 2000);
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
// System Monitors
// =====================

let systemMonitorInterval = null;

export async function updateSystemMonitor() {
    try {
        const res = await fetch(`${API}/api/system/stats`);
        const data = await res.json();
        const cpuEl = document.getElementById('cpu-value');
        const ramEl = document.getElementById('ram-value');
        if (cpuEl) cpuEl.textContent = data.cpu?.percent || '--';
        if (ramEl) ramEl.textContent = data.memory?.percent || '--';
    } catch (err) { /* Silently fail */ }
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

export async function updateWatcherStatus() {
    const dot = document.getElementById('watcher-dot');
    const val = document.getElementById('watcher-value');
    const widget = document.getElementById('watcher-widget');
    if (!dot || !val) return;

    try {
        const res = await fetch(`${API}/api/system/watcher`);
        const data = await res.json();
        dot.className = 'status-dot';

        if (data.status === 'healthy') {
            dot.classList.add('active');
            if (data.tracked_count > 0) {
                const processing = data.tracked_files?.some(f => f.state === 'PROCESSING');
                if (processing) { val.textContent = 'Processing...'; }
                else {
                    const s = data.settling_count > 0 ? `/${data.settling_count}s` : '';
                    val.textContent = `${data.tracked_count}f${s}`;
                }
            } else { val.textContent = 'Idle'; }
        } else if (data.status === 'degraded') { dot.classList.add('warning'); val.textContent = 'Slow'; }
        else if (data.status === 'error') { dot.classList.add('error'); val.textContent = 'Down'; }
        else { dot.classList.add('inactive'); val.textContent = 'OFF'; }

        const parts = [];
        if (data.uptime_seconds > 0) {
            const h = Math.floor(data.uptime_seconds / 3600);
            const m = Math.floor((data.uptime_seconds % 3600) / 60);
            parts.push(`Uptime: ${h}h ${m}m`);
        }
        if (data.tracked_files?.length > 0) {
            parts.push(`Files: ${data.tracked_files.map(f => `${f.name} (${f.state})`).join(', ')}`);
        }
        if (data.recent_activity?.length > 0) {
            const last = data.recent_activity[data.recent_activity.length - 1];
            parts.push(`Last: ${last.file} → ${last.action}`);
        }
        widget.title = parts.length > 0 ? parts.join('\n') : 'Inbox Watcher';
    } catch (err) {
        dot.className = 'status-dot inactive';
        val.textContent = 'OFF';
        widget.title = 'Inbox Watcher (unreachable)';
    }
}
