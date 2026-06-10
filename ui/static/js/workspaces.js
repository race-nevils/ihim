/**
 * workspaces.js — Git branch/branch monitor widget.
 * Split out of the old vault-dashboard.js in the 2026-06 refactor.
 */

export const workspacesManager = {
    async loadWorkspaces() {
        const body = document.getElementById('workspaces-body');
        if (!body) return;
        body.innerHTML = '<div class="workspaces-loading">Loading workspaces...</div>';
        try {
            const res = await fetch('/api/workspaces');
            const data = await res.json();
            if (!data.success) throw new Error('Failed to load workspaces');
            if (data.workspaces.length === 0) {
                body.innerHTML = `<div class="workspaces-empty"><p>No active workspaces</p><p class="workspaces-hint">Create a branch in the agent harness to see it here</p></div>`;
                return;
            }

            let html = '';

            if (data.summary) {
                const s = data.summary;
                html += `<div class="workspaces-summary">
                    <span class="ws-stat">${s.total} branch${s.total !== 1 ? 'es' : ''}</span>
                    <span class="ws-stat">${s.branches} branch${s.branches !== 1 ? 's' : ''}</span>
                    ${s.merged ? `<span class="ws-stat ws-stat-merged">${s.merged} merged</span>` : ''}
                    ${s.dirty ? `<span class="ws-stat ws-stat-dirty">${s.dirty} dirty</span>` : ''}
                </div>`;
            }

            html += '<div class="workspaces-list">';
            data.workspaces.forEach(ws => {
                const statusClass = this.statusClass(ws.status);
                const statusLabel = ws.status === 'branch-only' ? 'branch only' : ws.status;

                let syncHtml = '';
                if (ws.ahead_count > 0 || ws.behind_count > 0) {
                    const parts = [];
                    if (ws.ahead_count > 0) parts.push(`<span class="ws-ahead">↑${ws.ahead_count}</span>`);
                    if (ws.behind_count > 0) parts.push(`<span class="ws-behind">↓${ws.behind_count}</span>`);
                    syncHtml = `<span class="ws-sync">${parts.join(' ')}</span>`;
                }

                // Dirty breakdown — untracked vs modified vs staged readable at a glance
                const dirtyParts = [];
                if (ws.conflicted_count > 0) dirtyParts.push(`<span class="ws-conflicted">⚠ ${ws.conflicted_count} conflicted</span>`);
                if (ws.staged_count > 0) dirtyParts.push(`<span class="ws-staged">✓ ${ws.staged_count} staged</span>`);
                if (ws.modified_count > 0) dirtyParts.push(`<span class="ws-modified">● ${ws.modified_count} modified</span>`);
                if (ws.untracked_count > 0) dirtyParts.push(`<span class="ws-untracked">◌ ${ws.untracked_count} untracked</span>`);
                const dirtyHtml = dirtyParts.join(' ');

                const remoteHtml = !ws.has_remote ? '<span class="ws-local-only">local only</span>' : '';
                const commitHtml = ws.last_commit_message
                    ? `<div class="workspace-commit">${this.escapeHtml(ws.last_commit_message)}</div>`
                    : '';

                html += `<div class="workspace-item ${statusClass}">
                    <div class="workspace-header">
                        <span class="workspace-name">${this.escapeHtml(ws.name)}</span>
                        <span class="workspace-header-right">
                            ${syncHtml}${dirtyHtml}${remoteHtml}
                            <span class="workspace-status-badge ${statusClass}">${statusLabel}</span>
                        </span>
                    </div>
                    <div class="workspace-details">
                        <div class="workspace-branch">Branch: <code>${this.escapeHtml(ws.branch)}</code></div>
                        ${commitHtml}
                        ${ws.purpose ? `<div class="workspace-purpose">${this.escapeHtml(ws.purpose)}</div>` : ''}
                        ${ws.last_activity_relative ? `<div class="workspace-activity">Last active: ${ws.last_activity_relative}</div>` : ''}
                    </div>
                </div>`;
            });
            html += '</div>';
            body.innerHTML = html;
        } catch (e) {
            console.error('Failed to load workspaces:', e);
            body.innerHTML = '<div class="workspaces-error">Failed to load workspaces</div>';
        }
    },

    statusClass(status) {
        const map = {
            'active': 'status-active',
            'branch-only': 'status-branch-only',
            'merged': 'status-merged',
            'stale': 'status-stale',
            'diverged': 'status-diverged',
        };
        return map[status] || 'status-closed';
    },

    async refresh() {
        const btn = document.getElementById('workspaces-refresh-btn');
        if (!btn || btn.classList.contains('is-refreshing')) return;
        btn.classList.add('is-refreshing');
        btn.disabled = true;
        try {
            await this.loadWorkspaces();
            if (window.lucide) lucide.createIcons();
        } finally {
            btn.classList.remove('is-refreshing');
            btn.disabled = false;
        }
    },

    escapeHtml(unsafe) {
        return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }
};

export function toggleWorkspacesWindow() {
    const win = document.getElementById('workspaces-window');
    if (!win) return;
    if (win.hasAttribute('open')) win.close();
    else win.open();
}

export function initWorkspacesEvents() {
    const wsWin = document.getElementById('workspaces-window');
    if (!wsWin) return;
    document.getElementById('workspaces-refresh-btn')
        ?.addEventListener('click', () => workspacesManager.refresh());
    // Data init on panel:open — covers manual open AND auto-restore on reload.
    wsWin.addEventListener('panel:open', () => {
        workspacesManager.loadWorkspaces();
        if (window.lucide) lucide.createIcons();
    });
}
