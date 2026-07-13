/**
 * <ihim-vault> — Vault window: Tasks / Projects / Documents browser over the
 * brain index. Extends IhimPanel: IS the draggable window; renders its own
 * chrome + content, loads data on its panel:open lifecycle.
 */
import { API } from '../app.js';
import { IhimPanel } from './ihim-panel.js';
import './ihim-tabs.js';

class IhimVault extends IhimPanel {
    _docsPage = 0;
    _docsLimit = 30;
    _expandedDoc = null;
    _expandedItem = null;

    connectedCallback() {
        this.innerHTML = `
            <div class="vault-header vault-drag-handle" data-drag-handle>
                <span class="vault-label"><i data-lucide="archive" style="width:16px;height:16px;display:inline;vertical-align:middle;margin-right:6px;"></i>Vault</span>
                <button class="vault-close" data-close-btn aria-label="Close Vault">&times;</button>
            </div>

            <ihim-tabs>
            <!-- Tabs -->
            <div class="vault-tabs" id="vault-tablist" role="tablist" aria-label="Vault">
                <button class="vault-tab-btn active" data-tab="tasks" role="tab" id="vault-tab-tasks-btn" aria-selected="true" aria-controls="vault-tab-tasks" tabindex="0">Tasks</button>
                <button class="vault-tab-btn" data-tab="projects" role="tab" id="vault-tab-projects-btn" aria-selected="false" aria-controls="vault-tab-projects" tabindex="-1">Projects</button>
                <button class="vault-tab-btn" data-tab="documents" role="tab" id="vault-tab-documents-btn" aria-selected="false" aria-controls="vault-tab-documents" tabindex="-1">Documents</button>
            </div>

            <!-- Tasks Tab -->
            <div id="vault-tab-tasks" class="vault-tab-content active" role="tabpanel" aria-labelledby="vault-tab-tasks-btn">
                <div class="vault-body" id="vault-tasks-body">
                    <div class="vault-loading">Loading tasks...</div>
                </div>
            </div>

            <!-- Projects Tab -->
            <div id="vault-tab-projects" class="vault-tab-content" role="tabpanel" aria-labelledby="vault-tab-projects-btn" style="display: none;">
                <div class="vault-body" id="vault-projects-body">
                    <div class="vault-loading">Loading projects...</div>
                </div>
            </div>

            <!-- Documents Tab -->
            <div id="vault-tab-documents" class="vault-tab-content" role="tabpanel" aria-labelledby="vault-tab-documents-btn" style="display: none;">
                <div class="vault-doc-controls">
                    <label for="vault-doc-category" class="sr-only">Filter by category</label>
                    <select id="vault-doc-category">
                        <option value="">All Categories</option>
                    </select>
                    <label for="vault-doc-sort" class="sr-only">Sort order</label>
                    <select id="vault-doc-sort">
                        <option value="created_at">Newest</option>
                        <option value="updated_at">Recently Updated</option>
                        <option value="title">Title A-Z</option>
                    </select>
                </div>
                <div class="vault-body" id="vault-docs-body">
                    <div class="vault-loading">Loading documents...</div>
                </div>
            </div>
            </ihim-tabs>
        `;

        // Data init on open (manual click + auto-restore on reload)
        this.addEventListener('panel:open', () => {
            this._loadTasks();
            this._loadCategories();
            if (window.lucide) lucide.createIcons();
        });

        this.querySelector('ihim-tabs').addEventListener('tab:change', (e) => {
            const tabName = e.detail.tab?.dataset?.tab;
            if (tabName === 'tasks') this._loadTasks();
            else if (tabName === 'projects') this._loadProjects();
            else if (tabName === 'documents') { this._docsPage = 0; this._loadDocuments(); }
        });

        this.addEventListener('click', (e) => {
            const toggle = e.target.closest('[data-vault-toggle]');
            if (toggle) { this._toggleTask(toggle.dataset.vaultToggle); return; }
            const item = e.target.closest('[data-vault-item]');
            if (item) { this._toggleItemExpand(item.dataset.vaultItem); return; }
            const doc = e.target.closest('[data-vault-doc]');
            if (doc) { this._toggleDocExpand(doc.dataset.vaultDoc); return; }
            const page = e.target.closest('[data-vault-page]');
            if (page) {
                if (page.dataset.vaultPage === 'prev') this._docsPage--;
                else this._docsPage++;
                this._loadDocuments();
            }
        });
        this.addEventListener('change', (e) => {
            if (e.target.id === 'vault-doc-category' || e.target.id === 'vault-doc-sort') {
                this._loadDocuments();
            }
        });

        super.connectedCallback();
    }

    _el(id) { return this.querySelector(`#${id}`); }

    async _loadTasks() {
        const body = this._el('vault-tasks-body');
        if (!body) return;
        body.innerHTML = '<div class="vault-loading">Loading tasks...</div>';
        try {
            const res = await fetch(`${API}/api/vault/tasks`);
            const data = await res.json();
            if (!data.success) throw new Error(data.detail || 'Failed');
            this._renderChecklist(body, data.tasks, 'task');
        } catch (e) { body.innerHTML = '<div class="vault-loading">Failed to load tasks.</div>'; }
    }

    async _loadProjects() {
        const body = this._el('vault-projects-body');
        if (!body) return;
        body.innerHTML = '<div class="vault-loading">Loading projects...</div>';
        try {
            const res = await fetch(`${API}/api/vault/projects`);
            const data = await res.json();
            if (!data.success) throw new Error(data.detail || 'Failed');
            this._renderChecklist(body, data.projects, 'project');
        } catch (e) { body.innerHTML = '<div class="vault-loading">Failed to load projects.</div>'; }
    }

    _renderChecklist(container, items, type) {
        if (!items || items.length === 0) { container.innerHTML = `<div class="vault-empty">No ${type}s found.</div>`; return; }
        const pending = items.filter(i => !i.is_completed);
        const completed = items.filter(i => i.is_completed);
        let html = '';
        pending.forEach(item => {
            const meta = type === 'task'
                ? (item.event_date || '') + (item.event_start_time ? ' ' + item.event_start_time : '')
                : this._formatDate(item.created_at);
            html += this._itemHTML(item, meta, false);
            if (this._expandedItem === item.id) html += this._itemExpandHTML(item);
        });
        if (completed.length > 0) {
            html += `<div class="vault-divider"><span class="vault-divider-line"></span><span class="vault-divider-label">Completed (${completed.length})</span><span class="vault-divider-line"></span></div>`;
            completed.forEach(item => {
                const meta = item.completed_at ? 'Done ' + this._formatDate(item.completed_at) : '';
                html += this._itemHTML(item, meta, true);
                if (this._expandedItem === item.id) html += this._itemExpandHTML(item);
            });
        }
        html += `<div class="vault-count">${pending.length} open, ${completed.length} done</div>`;
        container.innerHTML = html;
    }

    _itemHTML(item, meta, isCompleted) {
        const cls = isCompleted ? 'vault-item completed' : 'vault-item';
        const checked = isCompleted ? 'checked' : '';
        return `<div class="${cls}">
            <input type="checkbox" ${checked} data-vault-toggle="${item.id}">
            <div class="vault-item-info" data-vault-item="${item.id}">
                <div class="vault-item-title">${this._esc(item.title)}</div>
                <div class="vault-item-meta">${this._esc(meta)}</div>
            </div>
        </div>`;
    }

    _itemExpandHTML(item) {
        const content = item.content || item.summary || 'No content available.';
        return `<div class="vault-item-expand">${this._esc(content)}</div>`;
    }

    _onTasksTab() {
        const tasksTab = this._el('vault-tab-tasks');
        return tasksTab && tasksTab.style.display !== 'none';
    }

    _toggleItemExpand(entryId) {
        this._expandedItem = this._expandedItem === entryId ? null : entryId;
        if (this._onTasksTab()) this._loadTasks();
        else this._loadProjects();
    }

    async _toggleTask(entryId) {
        try {
            await fetch(`${API}/api/vault/tasks/${entryId}/toggle`, { method: 'PATCH' });
            if (this._onTasksTab()) this._loadTasks();
            else this._loadProjects();
        } catch (e) { console.error('Toggle failed:', e); }
    }

    async _loadDocuments() {
        const body = this._el('vault-docs-body');
        if (!body) return;
        body.innerHTML = '<div class="vault-loading">Loading documents...</div>';
        const cat = this._el('vault-doc-category')?.value || '';
        const sort = this._el('vault-doc-sort')?.value || 'created_at';
        const offset = this._docsPage * this._docsLimit;
        try {
            let url = `${API}/api/vault/entries?limit=${this._docsLimit}&offset=${offset}&sort=${sort}`;
            if (cat) url += `&category=${encodeURIComponent(cat)}`;
            const res = await fetch(url);
            const data = await res.json();
            if (!data.success) throw new Error(data.detail || 'Failed');
            this._renderDocuments(body, data);
        } catch (e) { body.innerHTML = '<div class="vault-loading">Failed to load documents.</div>'; }
    }

    _renderDocuments(container, data) {
        const { entries, total, offset, limit } = data;
        if (!entries || entries.length === 0) { container.innerHTML = '<div class="vault-empty">No documents found.</div>'; return; }
        let html = '';
        entries.forEach(entry => {
            const isExpanded = this._expandedDoc === entry.id;
            html += `<div class="vault-doc-item" data-vault-doc="${entry.id}">
                <span class="vault-doc-badge">${this._esc(entry.category)}</span>
                <div class="vault-item-info">
                    <div class="vault-item-title">${this._esc(entry.title)}</div>
                    <div class="vault-item-meta">${this._formatDate(entry.created_at)}</div>
                </div>
            </div>`;
            if (isExpanded) {
                const content = entry.content || entry.summary || 'No content available.';
                html += `<div class="vault-doc-expand">${this._esc(content)}</div>`;
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
    }

    _toggleDocExpand(entryId) {
        this._expandedDoc = this._expandedDoc === entryId ? null : entryId;
        this._loadDocuments();
    }

    async _loadCategories() {
        try {
            const res = await fetch(`${API}/api/vault/categories`);
            const data = await res.json();
            if (!data.success) return;
            const select = this._el('vault-doc-category');
            if (!select) return;
            select.innerHTML = '<option value="">All Categories</option>';
            for (const [cat, count] of Object.entries(data.categories)) {
                select.innerHTML += `<option value="${this._esc(cat)}">${this._esc(cat)} (${count})</option>`;
            }
        } catch (e) { /* silent */ }
    }

    _formatDate(dateStr) {
        if (!dateStr) return '';
        try { return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
        catch { return dateStr; }
    }

    _esc(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

customElements.define('ihim-vault', IhimVault);
