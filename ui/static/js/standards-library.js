/**
 * standards-library.js — Compliance standards library viewer
 */
import { API, escapeHtml, showStatus } from './app.js';
import { makeDraggable } from './draggable.js';
import { initAccessibleTabs } from './a11y.js';

let standardsLibraryModules = [];
let selectedModuleId = null;
let referencesData = null;

export async function openStandardsLibraryWindow() {
    const win = document.getElementById('standards-library-window');
    let posRestored = false;
    try {
        const saved = localStorage.getItem('standardsLibraryWindowPosition');
        if (saved) {
            const { x, y } = JSON.parse(saved);
            if (x >= 0 && y >= 0 && x < window.innerWidth - 50 && y < window.innerHeight - 50) {
                win.style.left = x + 'px'; win.style.top = y + 'px'; posRestored = true;
            }
        }
    } catch (e) { console.warn('Failed to restore standards library position:', e); }
    if (!posRestored) {
        const rect = win.getBoundingClientRect();
        win.style.left = (window.innerWidth - rect.width) / 2 + 'px';
        win.style.top = (window.innerHeight - rect.height) / 2 + 'px';
    }
    win.style.display = 'block';
    await loadStandardsLibraryModules();
    if (!win.dataset.dragInitialized) {
        makeDraggable('standards-library-window', '.standards-library-drag-handle', 'standardsLibraryWindowPosition');
        win.dataset.dragInitialized = 'true';
    }
}

export function closeStandardsLibraryWindow() {
    document.getElementById('standards-library-window').style.display = 'none';
}

async function loadStandardsLibraryModules() {
    try {
        const res = await fetch(`${API}/api/compliance/modules`);
        const data = await res.json();
        standardsLibraryModules = (data.modules || []).map(m => ({
            id: m.module_id, name: m.name, version: m.version, category: m.category,
            status: m.enabled ? 'active' : 'inactive', priority: m.priority,
            controls_count: m.controls_count, description: m.description
        }));
        renderStandardsLibraryModuleList();
        updateStandardsLibraryCount();
    } catch (err) {
        console.error('Failed to load standards library modules:', err);
        standardsLibraryModules = [];
    }
}

function renderStandardsLibraryModuleList() {
    const listEl = document.getElementById('standards-library-modules-list');
    const searchTerm = document.getElementById('standards-library-search-input')?.value.toLowerCase() || '';
    const filtered = standardsLibraryModules.filter(m =>
        m.name.toLowerCase().includes(searchTerm) || m.description?.toLowerCase().includes(searchTerm)
    );
    if (filtered.length === 0) {
        listEl.innerHTML = '<div class="standards-library-empty-state"><p>No modules found</p></div>';
        return;
    }
    listEl.innerHTML = filtered.map(module => `
        <div class="standards-library-module-item ${selectedModuleId === module.id ? 'selected' : ''} ${module.status === 'active' ? 'active' : ''}"
             data-module-id="${module.id}">
            <div class="standards-library-module-header">
                <span class="standards-library-module-name">${module.name}</span>
                <span class="standards-library-module-status ${module.status === 'active' ? 'status-active' : 'status-inactive'}">
                    ${module.status === 'active' ? '●' : '○'}
                </span>
            </div>
            <div class="standards-library-module-meta">
                <span class="standards-library-module-version">v${module.version || '1.0.0'}</span>
                ${module.priority ? `<span class="standards-library-module-priority">P${module.priority}</span>` : ''}
            </div>
        </div>
    `).join('');
}

async function selectStandardsLibraryModule(moduleId) {
    selectedModuleId = moduleId;
    renderStandardsLibraryModuleList();
    await renderStandardsLibraryModuleDetail();
}

async function renderStandardsLibraryModuleDetail() {
    const detailEl = document.getElementById('standards-library-module-detail');
    const module = standardsLibraryModules.find(m => m.id === selectedModuleId);
    if (!module) {
        detailEl.innerHTML = '<div class="standards-library-empty-state"><p>Select a module to view details</p></div>';
        return;
    }
    let fullModule = module;
    try {
        const res = await fetch(`${API}/api/compliance/modules/${module.id}`);
        const data = await res.json();
        if (data.success && data.module) fullModule = { ...module, controls: data.module.controls || [] };
    } catch (err) { console.error('Failed to fetch module details:', err); }

    const isActive = fullModule.status === 'active';
    const controlsCount = fullModule.controls?.length || 0;

    detailEl.innerHTML = `
        <div class="standards-library-detail-header">
            <h3>${fullModule.name}</h3>
            <span class="standards-library-detail-version">v${fullModule.version || '1.0.0'}</span>
        </div>
        <div class="standards-library-detail-description">${fullModule.description || 'No description available'}</div>
        <div class="standards-library-detail-stats">
            <div class="stat-item"><span class="stat-label">Priority</span><span class="stat-value">${fullModule.priority || 'N/A'}</span></div>
            <div class="stat-item"><span class="stat-label">Controls</span><span class="stat-value">${controlsCount}</span></div>
            <div class="stat-item"><span class="stat-label">Status</span><span class="stat-value ${isActive ? 'status-active' : 'status-inactive'}">${isActive ? 'Active' : 'Inactive'}</span></div>
        </div>
        ${fullModule.controls && fullModule.controls.length > 0 ? `
            <div class="standards-library-detail-controls">
                <h4>Controls (${controlsCount})</h4>
                <div class="controls-list">
                    ${fullModule.controls.map(control => `
                        <div class="control-item">
                            <div class="control-name">${control.name || control.id}</div>
                            <div class="control-level">${control.level || 'AUDIT'}</div>
                        </div>
                    `).join('')}
                </div>
            </div>
        ` : ''}
        <div class="standards-library-detail-actions">
            ${isActive ?
                `<button class="deactivate-module-btn" data-module-action="deactivate" data-module-id="${fullModule.id}">Deactivate</button>` :
                `<button class="activate-module-btn" data-module-action="activate" data-module-id="${fullModule.id}">Activate</button>`
            }
        </div>`;
}

async function activateStandardsLibraryModule(moduleId) {
    try {
        const res = await fetch(`${API}/api/compliance/activate/${moduleId}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            const module = standardsLibraryModules.find(m => m.id === moduleId);
            if (module) module.status = 'active';
            renderStandardsLibraryModuleList();
            renderStandardsLibraryModuleDetail();
            showStatus(`${module?.name || 'Module'} activated`, 'success');
        }
    } catch (err) { console.error('Failed to activate module:', err); showStatus('Failed to activate module', 'error'); }
}

async function deactivateStandardsLibraryModule(moduleId) {
    try {
        const res = await fetch(`${API}/api/compliance/deactivate/${moduleId}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            const module = standardsLibraryModules.find(m => m.id === moduleId);
            if (module) module.status = 'inactive';
            renderStandardsLibraryModuleList();
            renderStandardsLibraryModuleDetail();
            showStatus(`${module?.name || 'Module'} deactivated`, 'success');
        }
    } catch (err) { console.error('Failed to deactivate module:', err); showStatus('Failed to deactivate module', 'error'); }
}

export function filterStandardsLibraryModules() {
    renderStandardsLibraryModuleList();
}

function updateStandardsLibraryCount() {
    const countEl = document.getElementById('standards-library-count');
    const activeCount = standardsLibraryModules.filter(m => m.status === 'active').length;
    if (countEl) countEl.textContent = `${standardsLibraryModules.length} modules (${activeCount} active)`;
}

export function switchStandardsLibraryTab(tab) {
    document.querySelectorAll('.sl-tab-btn').forEach(btn => {
        const isTarget = btn.dataset.tab === tab;
        btn.classList.toggle('active', isTarget);
        btn.setAttribute('aria-selected', isTarget ? 'true' : 'false');
        btn.setAttribute('tabindex', isTarget ? '0' : '-1');
    });
    document.querySelectorAll('.sl-tab-panel').forEach(panel => panel.style.display = 'none');
    document.getElementById(`sl-${tab}-panel`).style.display = 'block';
    if (tab === 'references' && !referencesData) loadStandardsReferences();
}

async function loadStandardsReferences() {
    try {
        const res = await fetch(`${API}/api/standards/references`);
        referencesData = await res.json();
        renderStandardsReferences();
    } catch (e) {
        console.error('Failed to load references:', e);
        document.getElementById('standards-references-list').innerHTML = '<div class="standards-library-empty-state"><p>Failed to load references</p></div>';
    }
}

function renderStandardsReferences() {
    const listEl = document.getElementById('standards-references-list');
    if (!referencesData?.standards || referencesData.standards.length === 0) {
        listEl.innerHTML = '<div class="standards-library-empty-state"><p>No references found</p></div>';
        return;
    }
    listEl.innerHTML = referencesData.standards.map(std => `
        <div class="reference-standard-item">
            <div class="reference-standard-header" data-ref-id="${std.id}">
                <span class="expand-icon" id="expand-${std.id}">▶</span>
                <span class="reference-standard-name">${std.name}</span>
                <span class="reference-count">${std.references.length} refs</span>
            </div>
            <div class="reference-links-list" id="refs-${std.id}" style="display: none;">
                ${std.references.map(ref => `
                    <a href="${ref.url}" target="_blank" class="reference-link-item">
                        <span class="ref-type ref-type-${ref.type}">${ref.type}</span>
                        <span class="ref-title">${ref.title}</span>
                    </a>
                `).join('')}
            </div>
        </div>
    `).join('');
}

function toggleReferenceExpand(stdId) {
    const list = document.getElementById(`refs-${stdId}`);
    const icon = document.getElementById(`expand-${stdId}`);
    if (list.style.display === 'none') { list.style.display = 'block'; icon.textContent = '▼'; }
    else { list.style.display = 'none'; icon.textContent = '▶'; }
}

// Event delegation for standards library interactions
export function initStandardsLibraryEvents() {
    const win = document.getElementById('standards-library-window');
    if (!win) return;

    // Accessible tabs — keyboard nav + ARIA state sync
    const tablist = document.getElementById('sl-tablist');
    if (tablist) {
        initAccessibleTabs(tablist, {
            tabSelector: '[role="tab"]',
            onActivate(tab) { switchStandardsLibraryTab(tab.dataset.tab); }
        });
    }

    win.addEventListener('click', (e) => {
        // Module selection
        const moduleItem = e.target.closest('[data-module-id]');
        if (moduleItem && moduleItem.classList.contains('standards-library-module-item')) {
            selectStandardsLibraryModule(moduleItem.dataset.moduleId);
            return;
        }
        // Activate/deactivate buttons
        const actionBtn = e.target.closest('[data-module-action]');
        if (actionBtn) {
            const action = actionBtn.dataset.moduleAction;
            const id = actionBtn.dataset.moduleId;
            if (action === 'activate') activateStandardsLibraryModule(id);
            else if (action === 'deactivate') deactivateStandardsLibraryModule(id);
            return;
        }
        // Reference expand
        const refHeader = e.target.closest('[data-ref-id]');
        if (refHeader) { toggleReferenceExpand(refHeader.dataset.refId); return; }
    });
}
