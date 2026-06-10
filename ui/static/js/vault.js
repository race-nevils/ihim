/**
 * vault.js — Tasks / Projects / Documents browser over the brain index.
 * Split out of the old vault-dashboard.js; backend renamed /api/dashboard
 * -> /api/vault in the 2026-06 refactor.
 */

export const vaultManager = {
    docsPage: 0,
    docsLimit: 30,
    expandedDoc: null,
    expandedItem: null,
    _items: {},

    async loadTasks() {
        const body = document.getElementById('vault-tasks-body');
        if (!body) return;
        body.innerHTML = '<div class="vault-loading">Loading tasks...</div>';
        try {
            const res = await fetch('/api/vault/tasks');
            const data = await res.json();
            if (!data.success) throw new Error(data.detail || 'Failed');
            this.renderChecklist(body, data.tasks, 'task');
        } catch (e) { body.innerHTML = '<div class="vault-loading">Failed to load tasks.</div>'; }
    },

    async loadProjects() {
        const body = document.getElementById('vault-projects-body');
        if (!body) return;
        body.innerHTML = '<div class="vault-loading">Loading projects...</div>';
        try {
            const res = await fetch('/api/vault/projects');
            const data = await res.json();
            if (!data.success) throw new Error(data.detail || 'Failed');
            this.renderChecklist(body, data.projects, 'project');
        } catch (e) { body.innerHTML = '<div class="vault-loading">Failed to load projects.</div>'; }
    },

    renderChecklist(container, items, type) {
        if (!items || items.length === 0) { container.innerHTML = `<div class="vault-empty">No ${type}s found.</div>`; return; }
        items.forEach(item => { this._items[item.id] = item; });
        const pending = items.filter(i => !i.is_completed);
        const completed = items.filter(i => i.is_completed);
        let html = '';
        pending.forEach(item => {
            const meta = type === 'task'
                ? (item.event_date || '') + (item.event_start_time ? ' ' + item.event_start_time : '')
                : this.formatDate(item.created_at);
            html += this.itemHTML(item, meta, false);
            if (this.expandedItem === item.id) html += this.itemExpandHTML(item);
        });
        if (completed.length > 0) {
            html += `<div class="vault-divider"><span class="vault-divider-line"></span><span class="vault-divider-label">Completed (${completed.length})</span><span class="vault-divider-line"></span></div>`;
            completed.forEach(item => {
                const meta = item.completed_at ? 'Done ' + this.formatDate(item.completed_at) : '';
                html += this.itemHTML(item, meta, true);
                if (this.expandedItem === item.id) html += this.itemExpandHTML(item);
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
            <div class="vault-item-info" data-vault-item="${item.id}">
                <div class="vault-item-title">${this.esc(item.title)}</div>
                <div class="vault-item-meta">${this.esc(meta)}</div>
            </div>
        </div>`;
    },

    itemExpandHTML(item) {
        const content = item.content || item.summary || 'No content available.';
        return `<div class="vault-item-expand">${this.esc(content)}</div>`;
    },

    toggleItemExpand(entryId) {
        this.expandedItem = this.expandedItem === entryId ? null : entryId;
        const tasksTab = document.getElementById('vault-tab-tasks');
        if (tasksTab && tasksTab.style.display !== 'none') this.loadTasks();
        else this.loadProjects();
    },

    async toggle(entryId) {
        try {
            await fetch(`/api/vault/tasks/${entryId}/toggle`, { method: 'PATCH' });
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
            let url = `/api/vault/entries?limit=${this.docsLimit}&offset=${offset}&sort=${sort}`;
            if (cat) url += `&category=${encodeURIComponent(cat)}`;
            const res = await fetch(url);
            const data = await res.json();
            if (!data.success) throw new Error(data.detail || 'Failed');
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
            const res = await fetch('/api/vault/categories');
            const data = await res.json();
            if (!data.success) return;
            const select = document.getElementById('vault-doc-category');
            if (!select) return;
            select.innerHTML = '<option value="">All Categories</option>';
            for (const [cat, count] of Object.entries(data.categories)) {
                select.innerHTML += `<option value="${this.esc(cat)}">${this.esc(cat)} (${count})</option>`;
            }
        } catch (e) { /* silent */ }
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

export function toggleVaultWindow() {
    const win = document.getElementById('vault-window');
    if (!win) return;
    if (win.hasAttribute('open')) win.close();
    else win.open();
}

export function initVaultEvents() {
    const vaultWin = document.getElementById('vault-window');
    if (!vaultWin) return;

    // Data init on panel:open (manual click + auto-restore on reload)
    vaultWin.addEventListener('panel:open', () => {
        vaultManager.loadTasks();
        vaultManager.loadCategories();
        if (window.lucide) lucide.createIcons();
    });

    const tabs = vaultWin.querySelector('ihim-tabs');
    if (tabs) {
        tabs.addEventListener('tab:change', (e) => {
            const tabName = e.detail.tab?.dataset?.tab;
            if (tabName === 'tasks') vaultManager.loadTasks();
            else if (tabName === 'projects') vaultManager.loadProjects();
            else if (tabName === 'documents') { vaultManager.docsPage = 0; vaultManager.loadDocuments(); }
        });
    }

    vaultWin.addEventListener('click', (e) => {
        const toggle = e.target.closest('[data-vault-toggle]');
        if (toggle) { vaultManager.toggle(toggle.dataset.vaultToggle); return; }
        const item = e.target.closest('[data-vault-item]');
        if (item) { vaultManager.toggleItemExpand(item.dataset.vaultItem); return; }
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
