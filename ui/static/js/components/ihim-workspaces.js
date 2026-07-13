/**
 * <ihim-workspaces> — Git branch/branch monitor window.
 * Extends IhimPanel: IS the draggable window; renders its own chrome +
 * content, loads data on its panel:open lifecycle.
 */
import { API, escapeHtml } from '../app.js';
import { IhimPanel } from './ihim-panel.js';

class IhimWorkspaces extends IhimPanel {
    connectedCallback() {
        this.innerHTML = `
            <div class="workspaces-header workspaces-drag-handle" data-drag-handle>
                <span class="workspaces-label"><i data-lucide="git-branch" style="width:16px;height:16px;display:inline;vertical-align:middle;margin-right:6px;"></i>Workspaces</span>
                <span class="workspaces-header-actions">
                    <button class="workspaces-refresh" id="workspaces-refresh-btn" type="button" aria-label="Refresh workspaces"><i data-lucide="refresh-cw" style="width:14px;height:14px;"></i></button>
                    <button class="workspaces-close" data-close-btn aria-label="Close Workspaces">&times;</button>
                </span>
            </div>

            <div class="workspaces-body" id="workspaces-body">
                <div class="workspaces-loading">Loading workspaces...</div>
            </div>
        `;

        this.querySelector('#workspaces-refresh-btn').addEventListener('click', () => this._refresh());

        // Data init on open — covers manual open AND auto-restore on reload.
        this.addEventListener('panel:open', () => {
            this._loadWorkspaces();
            if (window.lucide) lucide.createIcons();
        });

        super.connectedCallback();
    }

    async _loadWorkspaces() {
        const body = this.querySelector('#workspaces-body');
        if (!body) return;
        body.innerHTML = '<div class="workspaces-loading">Loading workspaces...</div>';
        try {
            const res = await fetch(`${API}/api/workspaces`);
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
                const statusClass = this._statusClass(ws.status);
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
                    ? `<div class="workspace-commit">${escapeHtml(ws.last_commit_message)}</div>`
                    : '';

                html += `<div class="workspace-item ${statusClass}">
                    <div class="workspace-header">
                        <span class="workspace-name">${escapeHtml(ws.name)}</span>
                        <span class="workspace-header-right">
                            ${syncHtml}${dirtyHtml}${remoteHtml}
                            <span class="workspace-status-badge ${statusClass}">${statusLabel}</span>
                        </span>
                    </div>
                    <div class="workspace-details">
                        <div class="workspace-branch">Branch: <code>${escapeHtml(ws.branch)}</code></div>
                        ${commitHtml}
                        ${ws.purpose ? `<div class="workspace-purpose">${escapeHtml(ws.purpose)}</div>` : ''}
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
    }

    _statusClass(status) {
        const map = {
            'active': 'status-active',
            'branch-only': 'status-branch-only',
            'merged': 'status-merged',
            'stale': 'status-stale',
            'diverged': 'status-diverged',
        };
        return map[status] || 'status-closed';
    }

    async _refresh() {
        const btn = this.querySelector('#workspaces-refresh-btn');
        if (!btn || btn.classList.contains('is-refreshing')) return;
        btn.classList.add('is-refreshing');
        btn.disabled = true;
        try {
            await this._loadWorkspaces();
            if (window.lucide) lucide.createIcons();
        } finally {
            btn.classList.remove('is-refreshing');
            btn.disabled = false;
        }
    }
}

customElements.define('ihim-workspaces', IhimWorkspaces);
