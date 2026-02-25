/**
 * vault-dashboard.js — Vault (tasks, projects, documents) + Workspaces viewer
 */
import { initAccessibleTabs } from './a11y.js';

// =====================
// Vault Manager
// =====================

export const vaultManager = {
    initialized: false,
    docsPage: 0,
    docsLimit: 30,
    expandedDoc: null,

    async loadTasks() {
        const body = document.getElementById('vault-tasks-body');
        if (!body) return;
        body.innerHTML = '<div class="vault-loading">Loading tasks...</div>';
        try {
            const res = await fetch('/api/dashboard/tasks');
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed');
            this.renderChecklist(body, data.tasks, 'task');
        } catch (e) { body.innerHTML = '<div class="vault-loading">Failed to load tasks.</div>'; }
    },

    async loadProjects() {
        const body = document.getElementById('vault-projects-body');
        if (!body) return;
        body.innerHTML = '<div class="vault-loading">Loading projects...</div>';
        try {
            const res = await fetch('/api/dashboard/projects');
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed');
            this.renderChecklist(body, data.projects, 'project');
        } catch (e) { body.innerHTML = '<div class="vault-loading">Failed to load projects.</div>'; }
    },

    renderChecklist(container, items, type) {
        if (!items || items.length === 0) { container.innerHTML = `<div class="vault-empty">No ${type}s found.</div>`; return; }
        const pending = items.filter(i => !i.is_completed);
        const completed = items.filter(i => i.is_completed);
        let html = '';
        pending.forEach(item => {
            const meta = type === 'task'
                ? (item.event_date || '') + (item.event_start_time ? ' ' + item.event_start_time : '')
                : this.formatDate(item.created_at);
            html += this.itemHTML(item, meta, false);
        });
        if (completed.length > 0) {
            html += `<div class="vault-divider"><span class="vault-divider-line"></span><span class="vault-divider-label">Completed (${completed.length})</span><span class="vault-divider-line"></span></div>`;
            completed.forEach(item => {
                const meta = item.completed_at ? 'Done ' + this.formatDate(item.completed_at) : '';
                html += this.itemHTML(item, meta, true);
            });
        }
        html += `<div class="vault-count">${pending.length} open, ${completed.length} done</div>`;
        container.innerHTML = html;
    },

    itemHTML(item, meta, isCompleted) {
        const cls = isCompleted ? 'vault-item completed' : 'vault-item';
        const checked = isCompleted ? 'checked' : '';
        return `<div class="${cls}">
            <input type="checkbox" ${checked} data-vault-toggle="${item.id}">
            <div class="vault-item-info">
                <div class="vault-item-title">${this.esc(item.title)}</div>
                <div class="vault-item-meta">${this.esc(meta)}</div>
            </div>
        </div>`;
    },

    async toggle(entryId) {
        try {
            await fetch(`/api/dashboard/tasks/${entryId}/toggle`, { method: 'PATCH' });
            const tasksTab = document.getElementById('vault-tab-tasks');
            if (tasksTab && tasksTab.style.display !== 'none') this.loadTasks();
            else this.loadProjects();
        } catch (e) { console.error('Toggle failed:', e); }
    },

    async loadDocuments() {
        const body = document.getElementById('vault-docs-body');
        if (!body) return;
        body.innerHTML = '<div class="vault-loading">Loading documents...</div>';
        const cat = document.getElementById('vault-doc-category')?.value || '';
        const sort = document.getElementById('vault-doc-sort')?.value || 'created_at';
        const offset = this.docsPage * this.docsLimit;
        try {
            let url = `/api/dashboard/entries?limit=${this.docsLimit}&offset=${offset}&sort=${sort}`;
            if (cat) url += `&category=${encodeURIComponent(cat)}`;
            const res = await fetch(url);
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed');
            this.renderDocuments(body, data);
        } catch (e) { body.innerHTML = '<div class="vault-loading">Failed to load documents.</div>'; }
    },

    renderDocuments(container, data) {
        const { entries, total, offset, limit } = data;
        if (!entries || entries.length === 0) { container.innerHTML = '<div class="vault-empty">No documents found.</div>'; return; }
        let html = '';
        entries.forEach(entry => {
            const isExpanded = this.expandedDoc === entry.id;
            html += `<div class="vault-doc-item" data-vault-doc="${entry.id}">
                <span class="vault-doc-badge">${this.esc(entry.category)}</span>
                <div class="vault-item-info">
                    <div class="vault-item-title">${this.esc(entry.title)}</div>
                    <div class="vault-item-meta">${this.formatDate(entry.created_at)}</div>
                </div>
            </div>`;
            if (isExpanded) {
                const content = entry.content || entry.summary || 'No content available.';
                html += `<div class="vault-doc-expand">${this.esc(content)}</div>`;
            }
        });
        const totalPages = Math.ceil(total / limit);
        const currentPage = Math.floor(offset / limit) + 1;
        html += `<div class="vault-pagination">
            <button ${currentPage <= 1 ? 'disabled' : ''} data-vault-page="prev">Prev</button>
            <span>${currentPage} / ${totalPages}</span>
            <button ${currentPage >= totalPages ? 'disabled' : ''} data-vault-page="next">Next</button>
        </div>`;
        container.innerHTML = html;
    },

    toggleExpand(entryId) {
        this.expandedDoc = this.expandedDoc === entryId ? null : entryId;
        this.loadDocuments();
    },

    async loadCategories() {
        try {
            const res = await fetch('/api/dashboard/categories');
            const data = await res.json();
            if (!data.success) return;
            const select = document.getElementById('vault-doc-category');
            if (!select) return;
            select.innerHTML = '<option value="">All Categories</option>';
            for (const [cat, count] of Object.entries(data.categories)) {
                select.innerHTML += `<option value="${this.esc(cat)}">${this.esc(cat)} (${count})</option>`;
            }
        } catch (e) { /* Silent fail */ }
    },

    formatDate(dateStr) {
        if (!dateStr) return '';
        try { return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
        catch { return dateStr; }
    },

    esc(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// =====================
// Workspaces Manager
// =====================

export const workspacesManager = {
    initialized: false,

    async loadWorkspaces() {
        const body = document.getElementById('workspaces-body');
        if (!body) return;
        body.innerHTML = '<div class="workspaces-loading">Loading workspaces...</div>';
        try {
            const res = await fetch('/api/workspaces');
            const data = await res.json();
            if (!data.success) throw new Error('Failed to load workspaces');
            if (data.workspaces.length === 0) {
                body.innerHTML = `<div class="workspaces-empty"><p>No active workspaces</p><p class="workspaces-hint">Use <code>/workspace create &lt;name&gt;</code> in the agent harness to create a workspace</p></div>`;
                return;
            }

            let html = '';

            // Summary bar
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

                // Ahead/behind indicator
                let syncHtml = '';
                if (ws.ahead_count > 0 || ws.behind_count > 0) {
                    const parts = [];
                    if (ws.ahead_count > 0) parts.push(`<span class="ws-ahead">\u2191${ws.ahead_count}</span>`);
                    if (ws.behind_count > 0) parts.push(`<span class="ws-behind">\u2193${ws.behind_count}</span>`);
                    syncHtml = `<span class="ws-sync">${parts.join(' ')}</span>`;
                }

                // Dirty indicator
                const dirtyHtml = ws.is_dirty
                    ? `<span class="ws-dirty">\u25cf ${ws.dirty_files_count} uncommitted</span>`
                    : '';

                // Remote indicator
                const remoteHtml = !ws.has_remote
                    ? '<span class="ws-local-only">local only</span>'
                    : '';

                // Last commit message
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

    escapeHtml(unsafe) {
        return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }
};

// =====================
// Window management
// =====================

export async function openVaultWindow() {
    const win = document.getElementById('vault-window');
    if (!win) return;
    win.open();
    if (!vaultManager.initialized) vaultManager.initialized = true;
    vaultManager.loadTasks();
    vaultManager.loadCategories();
    if (window.lucide) lucide.createIcons();
}

export function closeVaultWindow() {
    const win = document.getElementById('vault-window');
    if (win) win.close();
}

export function toggleVaultWindow() {
    const win = document.getElementById('vault-window');
    if (!win) return;
    if (win.hasAttribute('open')) closeVaultWindow();
    else openVaultWindow();
}

export function switchVaultTab(tab) {
    document.querySelectorAll('.vault-tab-btn').forEach(btn => {
        const isTarget = btn.dataset.tab === tab;
        btn.classList.toggle('active', isTarget);
        btn.setAttribute('aria-selected', isTarget ? 'true' : 'false');
        btn.setAttribute('tabindex', isTarget ? '0' : '-1');
    });
    document.querySelectorAll('.vault-tab-content').forEach(content => {
        content.style.display = content.id === `vault-tab-${tab}` ? 'block' : 'none';
    });
    if (tab === 'tasks') vaultManager.loadTasks();
    else if (tab === 'projects') vaultManager.loadProjects();
    else if (tab === 'documents') { vaultManager.docsPage = 0; vaultManager.loadDocuments(); }
}

export async function openWorkspacesWindow() {
    const win = document.getElementById('workspaces-window');
    if (!win) return;
    win.open();
    if (!workspacesManager.initialized) workspacesManager.initialized = true;
    await workspacesManager.loadWorkspaces();
    if (window.lucide) lucide.createIcons();
}

export function closeWorkspacesWindow() {
    const win = document.getElementById('workspaces-window');
    if (win) win.close();
}

export function toggleWorkspacesWindow() {
    const win = document.getElementById('workspaces-window');
    if (!win) return;
    if (win.hasAttribute('open')) closeWorkspacesWindow();
    else openWorkspacesWindow();
}

// Event delegation for vault interactions
export function initVaultEvents() {
    const tablist = document.getElementById('vault-tablist');
    if (tablist) {
        initAccessibleTabs(tablist, {
            tabSelector: '[role="tab"]',
            onActivate(tab) { switchVaultTab(tab.dataset.tab); }
        });
    }

    const vaultWin = document.getElementById('vault-window');
    if (vaultWin) {
        vaultWin.addEventListener('click', (e) => {
            const toggle = e.target.closest('[data-vault-toggle]');
            if (toggle) { vaultManager.toggle(toggle.dataset.vaultToggle); return; }
            const doc = e.target.closest('[data-vault-doc]');
            if (doc) { vaultManager.toggleExpand(doc.dataset.vaultDoc); return; }
            const page = e.target.closest('[data-vault-page]');
            if (page) {
                if (page.dataset.vaultPage === 'prev') vaultManager.docsPage--;
                else vaultManager.docsPage++;
                vaultManager.loadDocuments();
            }
        });
        vaultWin.addEventListener('change', (e) => {
            if (e.target.id === 'vault-doc-category' || e.target.id === 'vault-doc-sort') {
                vaultManager.loadDocuments();
            }
        });
    }
}
