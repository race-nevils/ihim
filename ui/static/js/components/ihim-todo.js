/**
 * <ihim-todo> — To-Do window: quick-capture list grouped by category.
 * Extends IhimPanel: IS the draggable window; renders its own chrome +
 * content, loads data on its panel:open lifecycle.
 *
 * Backed by /api/todos (data/local/todos.json). The server is the single
 * source of truth — every mutation POSTs then re-fetches, so all clients
 * (browser tabs, desktop app) see the same list.
 */
import { API, escapeHtml } from '../app.js';
import { IhimPanel } from './ihim-panel.js';

class IhimTodo extends IhimPanel {
    _categories = [];
    _focusCategoryId = null;   // restore quick-add focus across re-renders

    connectedCallback() {
        this.innerHTML = `
            <div class="todo-new-category-row">
                <input type="text" id="todo-new-category" placeholder="New category (e.g. desktop app, Tomorrow)" maxlength="80" />
                <button class="todo-add-btn" id="todo-add-category-btn" aria-label="Add category">+</button>
            </div>
            <div class="todo-body" id="todo-body">
                <div class="todo-loading">Loading...</div>
            </div>
        `;
        this._wireEvents();
        super.connectedCallback();
    }

    _el(id) { return this.querySelector(`#${id}`); }

    // =====================
    // Data
    // =====================

    async _load() {
        try {
            const res = await fetch(`${API}/api/todos`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this._categories = data.categories || [];
            this._renderBody();
        } catch (e) {
            this._el('todo-body').innerHTML =
                `<div class="todo-error">Failed to load to-dos: ${escapeHtml(e.message)}</div>`;
        }
    }

    async _mutate(path, options) {
        try {
            const res = await fetch(`${API}/api/todos${path}`, options);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || err.title || `HTTP ${res.status}`);
            }
            await this._load();
        } catch (e) {
            console.warn('To-do update failed:', e);
        }
    }

    _addCategory() {
        const input = this._el('todo-new-category');
        const name = input.value.trim();
        if (!name) return;
        input.value = '';
        this._mutate('/categories', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
    }

    _addItem(categoryId, input) {
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        this._focusCategoryId = categoryId;
        this._mutate('/items', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category_id: categoryId, text }),
        });
    }

    // =====================
    // Render
    // =====================

    _renderBody() {
        const body = this._el('todo-body');
        if (this._categories.length === 0) {
            body.innerHTML = '<div class="todo-empty">No categories yet. Add one above to start capturing to-dos.</div>';
            return;
        }
        body.innerHTML = this._categories.map(cat => {
            const items = cat.items || [];
            const openCount = items.filter(i => !i.done).length;
            return `
            <section class="todo-category" data-category-id="${escapeHtml(cat.id)}">
                <div class="todo-category-header">
                    <span class="todo-category-name">${escapeHtml(cat.name)}</span>
                    <span class="todo-category-count">${openCount}</span>
                    <button class="todo-category-delete" title="Delete category" aria-label="Delete category ${escapeHtml(cat.name)}">&times;</button>
                </div>
                ${items.map(item => `
                <div class="todo-item${item.done ? ' done' : ''}" data-item-id="${escapeHtml(item.id)}">
                    <input type="checkbox" ${item.done ? 'checked' : ''} aria-label="${escapeHtml(item.text)}" />
                    <span class="todo-item-text">${escapeHtml(item.text)}</span>
                    <button class="todo-item-delete" title="Delete" aria-label="Delete ${escapeHtml(item.text)}">&times;</button>
                </div>`).join('')}
                <input type="text" class="todo-quick-add" placeholder="Add to ${escapeHtml(cat.name)}..." maxlength="500" />
            </section>`;
        }).join('');

        // Quick-add keeps focus through the re-render so capture stays rapid
        if (this._focusCategoryId) {
            const section = body.querySelector(`[data-category-id="${CSS.escape(this._focusCategoryId)}"]`);
            section?.querySelector('.todo-quick-add')?.focus();
            this._focusCategoryId = null;
        }
    }

    // =====================
    // Events
    // =====================

    _wireEvents() {
        this.addEventListener('panel:open', () => {
            if (typeof lucide !== 'undefined') lucide.createIcons();
            this._load();
        });

        this.addEventListener('click', (e) => {
            if (e.target.closest('#todo-add-category-btn')) { this._addCategory(); return; }

            const deleteCatBtn = e.target.closest('.todo-category-delete');
            if (deleteCatBtn) {
                const section = deleteCatBtn.closest('.todo-category');
                const catId = section?.dataset.categoryId;
                const cat = this._categories.find(c => c.id === catId);
                if (!cat) return;
                const count = (cat.items || []).length;
                if (count > 0 && !confirm(`Delete "${cat.name}" and its ${count} to-do${count !== 1 ? 's' : ''}?`)) return;
                this._mutate(`/categories/${encodeURIComponent(catId)}`, { method: 'DELETE' });
                return;
            }

            const deleteItemBtn = e.target.closest('.todo-item-delete');
            if (deleteItemBtn) {
                const itemId = deleteItemBtn.closest('.todo-item')?.dataset.itemId;
                if (itemId) this._mutate(`/items/${encodeURIComponent(itemId)}`, { method: 'DELETE' });
                return;
            }
        });

        this.addEventListener('change', (e) => {
            if (e.target.matches('.todo-item input[type="checkbox"]')) {
                const itemId = e.target.closest('.todo-item')?.dataset.itemId;
                if (itemId) this._mutate(`/items/${encodeURIComponent(itemId)}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ done: e.target.checked }),
                });
            }
        });

        this.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            if (e.target.id === 'todo-new-category') { this._addCategory(); return; }
            if (e.target.matches('.todo-quick-add')) {
                const catId = e.target.closest('.todo-category')?.dataset.categoryId;
                if (catId) this._addItem(catId, e.target);
            }
        });
    }
}

customElements.define('ihim-todo', IhimTodo);
