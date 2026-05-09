/**
 * flight-path.js — System topology / health viewer
 */
import { API, escapeHtml } from './app.js';

export const flightPath = {
    components: [],
    selectedId: null,
    expandedGroups: new Set(['workspace-root', 'ihim-root']),
    healthPollInterval: null,

    init() {
        this.loadHealth();
        this.startHealthPolling();
    },

    startHealthPolling() {
        if (this.healthPollInterval) clearInterval(this.healthPollInterval);
        this.healthPollInterval = setInterval(() => this.loadHealth(), 5000);
    },

    stopHealthPolling() {
        if (this.healthPollInterval) { clearInterval(this.healthPollInterval); this.healthPollInterval = null; }
    },

    cleanupEventListeners() { /* No canvas listeners in v2 */ },

    async loadHealth() {
        try {
            // Fetch system health + server process health in parallel
            const [healthRes, serverRes] = await Promise.all([
                fetch(`${API}/api/system/health`).catch(() => null),
                fetch(`${API}/api/health`).catch(() => null),
            ]);

            if (healthRes && healthRes.ok) {
                const data = await healthRes.json();
                if (data.success && data.components) {
                    this.components = data.components;

                    // Inject server process health as a component
                    if (serverRes && serverRes.ok) {
                        const server = await serverRes.json();
                        const uptimeMin = server.uptime_seconds ? Math.floor(server.uptime_seconds / 60) : 0;
                        this.components.push({
                            id: 'server-process',
                            name: `Server (PID ${server.pid || '?'})`,
                            status: 'healthy',
                            message: `Up ${uptimeMin}m | ${server.memory_mb || '?'}MB RAM | ${server.active_transcription_workers || 0} workers`,
                        });
                    }

                    this.render();
                    this.updateTrafficLight(data);
                }
            }
        } catch (err) { console.error('Failed to load health:', err); }
    },

    refresh() { this.loadHealth(); },

    updateTrafficLight(data) {
        const counts = { healthy: 0, degraded: 0, error: 0 };
        data.components.forEach(c => { if (counts.hasOwnProperty(c.status)) counts[c.status]++; });
        document.getElementById('fp-count-healthy').textContent = counts.healthy;
        document.getElementById('fp-count-degraded').textContent = counts.degraded;
        document.getElementById('fp-count-error').textContent = counts.error;
        const overall = data.overall_status || 'unknown';
        const label = overall === 'healthy' ? 'All Systems Healthy' :
            overall === 'degraded' ? 'Some Issues' :
            overall === 'error' ? 'Errors Detected' : 'Unknown';
        document.getElementById('fp-overall-status').textContent = label;
    },

    render() {
        const listEl = document.getElementById('fp-system-list');
        if (!listEl) return;
        const hierarchy = this.buildHierarchy();
        listEl.innerHTML = this.renderGroup(hierarchy);
    },

    buildHierarchy() {
        const groups = {
            'workspace-root': { name: 'workspace', children: [] },
            'memory-system': { name: 'Memory', parent: 'workspace-root', children: [] },
            'skills-system': { name: 'Skills', parent: 'workspace-root', children: [] },
            'commands-system': { name: 'Commands', parent: 'workspace-root', children: [] },
            'guardrails-system': { name: 'Guardrails', parent: 'workspace-root', children: [] },
            'projects-system': { name: 'Projects', parent: 'workspace-root', children: [] },
            'learning-system': { name: 'Learning', parent: 'workspace-root', children: [] },
            'ihim-root': { name: 'iHIM', parent: 'workspace-root', children: [] },
            'api-server': { name: 'API', parent: 'ihim-root', children: [] },
            'team-system': { name: 'Team', parent: 'ihim-root', children: [] },
            'feedback-system': { name: 'Feedback', parent: 'ihim-root', children: [] },
            'data-stores': { name: 'Data', parent: 'ihim-root', children: [] },
            'ui-assets': { name: 'UI', parent: 'ihim-root', children: [] }
        };
        const componentToGroup = {
            'memory-claude': 'memory-system', 'memory-owner': 'memory-system',
            'memory-archive': 'memory-system', 'project-edgeflow': 'projects-system',
            'project-legal': 'projects-system', 'debrief-engine': 'learning-system',
            'heuristics-bank': 'learning-system', 'debriefs-log': 'learning-system',
            'actions-registry': 'api-server', 'slash-commands': 'api-server',
            'team-spawner': 'team-system', 'team-router': 'team-system',
            'team-state': 'team-system', 'blackboard': 'team-system',
            'feedback-processor': 'feedback-system', 'feedback-aggregator': 'feedback-system',
            'feedback-optimizer': 'feedback-system', 'feedback-metrics': 'feedback-system',
            'data-tasks': 'data-stores', 'data-notes': 'data-stores',
            'data-slash-commands': 'data-stores', 'data-team-state': 'data-stores',
            'sanity-check': 'ihim-root', 'server-process': 'api-server',
            'ui-dashboard': 'ui-assets', 'ui-styles': 'ui-assets'
        };
        this.components.forEach(comp => {
            const groupId = componentToGroup[comp.id];
            if (groupId && groups[groupId]) groups[groupId].children.push(comp);
            else if (groups[comp.id]) groups[comp.id].component = comp;
        });
        return groups;
    },

    renderGroup(groups) {
        let html = '';
        const workspace = groups['workspace-root'];
        const workspaceComp = workspace.component || this.components.find(c => c.id === 'workspace-root');
        const workspaceExpanded = this.expandedGroups.has('workspace-root');

        html += `<div class="fp-list-group">
            <div class="fp-list-header ${this.selectedId === 'workspace-root' ? 'selected' : ''}"
                 data-id="workspace-root">
                <span class="fp-list-expand ${workspaceExpanded ? 'expanded' : ''}">▶</span>
                <span class="fp-list-status ${workspaceComp?.status || 'inactive'}">●</span>
                <span class="fp-list-name">workspace</span>
            </div>
            <div class="fp-list-children ${workspaceExpanded ? 'expanded' : ''}">`;

        const workspaceChildren = ['memory-system', 'skills-system', 'commands-system',
            'guardrails-system', 'projects-system', 'learning-system', 'ihim-root'];

        workspaceChildren.forEach(groupId => {
            const group = groups[groupId];
            if (!group) return;
            const comp = group.component || this.components.find(c => c.id === groupId);
            const hasChildren = group.children.length > 0;
            const isExpanded = this.expandedGroups.has(groupId);

            html += `<div class="fp-list-group">
                <div class="fp-list-header ${this.selectedId === groupId ? 'selected' : ''}"
                     data-id="${groupId}">
                    <span class="fp-list-expand ${hasChildren ? (isExpanded ? 'expanded' : '') : 'no-children'}">▶</span>
                    <span class="fp-list-status ${comp?.status || 'inactive'}">●</span>
                    <span class="fp-list-name">${group.name}</span>
                </div>`;

            if (hasChildren) {
                html += `<div class="fp-list-children ${isExpanded ? 'expanded' : ''}">`;
                if (groupId === 'ihim-root') {
                    const ihimChildren = ['api-server', 'team-system', 'feedback-system',
                        'data-stores', 'ui-assets', 'sanity-check'];
                    ihimChildren.forEach(subId => {
                        const subGroup = groups[subId];
                        const subComp = subGroup?.component || this.components.find(c => c.id === subId);
                        if (!subGroup && !subComp) return;
                        const subHasChildren = subGroup?.children?.length > 0;
                        const subExpanded = this.expandedGroups.has(subId);

                        html += `<div class="fp-list-group">
                            <div class="fp-list-header ${this.selectedId === subId ? 'selected' : ''}"
                                 data-id="${subId}">
                                <span class="fp-list-expand ${subHasChildren ? (subExpanded ? 'expanded' : '') : 'no-children'}">▶</span>
                                <span class="fp-list-status ${subComp?.status || 'inactive'}">●</span>
                                <span class="fp-list-name">${subGroup?.name || subId}</span>
                            </div>`;
                        if (subHasChildren) {
                            html += `<div class="fp-list-children ${subExpanded ? 'expanded' : ''}">`;
                            subGroup.children.forEach(child => { html += this.renderItem(child); });
                            html += `</div>`;
                        }
                        html += `</div>`;
                    });
                } else {
                    group.children.forEach(child => { html += this.renderItem(child); });
                }
                html += `</div>`;
            }
            html += `</div>`;
        });

        html += `</div></div>`;
        return html;
    },

    renderItem(comp) {
        const name = comp.id.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        return `<div class="fp-list-item ${this.selectedId === comp.id ? 'selected' : ''}"
                     data-id="${comp.id}">
                    <span class="fp-list-status ${comp.status}">●</span>
                    <span class="fp-list-name">${escapeHtml(name)}</span>
                </div>`;
    },

    toggleGroup(groupId) {
        if (this.expandedGroups.has(groupId)) this.expandedGroups.delete(groupId);
        else this.expandedGroups.add(groupId);
        this.selectItem(groupId);
    },

    selectItem(id) {
        this.selectedId = id;
        this.render();
        this.showDetail(id);
    },

    showDetail(id) {
        const detailEl = document.getElementById('fp-detail-panel');
        const comp = this.components.find(c => c.id === id);
        if (!comp) {
            detailEl.innerHTML = '<div class="fp-detail-placeholder">Select a system to see details</div>';
            return;
        }
        const name = comp.id.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        const statusDot = comp.status === 'healthy' ? '●' : comp.status === 'degraded' ? '●' : comp.status === 'error' ? '●' : '○';

        let metricsHtml = '';
        if (comp.metrics && Object.keys(comp.metrics).length > 0) {
            metricsHtml = `<div class="fp-detail-section">
                <div class="fp-detail-section-title">Metrics</div>
                <div class="fp-detail-metrics">
                    ${Object.entries(comp.metrics).map(([key, value]) => {
                        let displayValue = value;
                        if (Array.isArray(value)) displayValue = value.length > 3 ? value.slice(0, 3).join(', ') + '...' : value.join(', ');
                        else if (typeof value === 'boolean') displayValue = value ? '✓' : '✗';
                        else if (typeof value === 'number' && key.includes('size'))
                            displayValue = value > 1024 ? (value / 1024).toFixed(1) + ' KB' : value + ' B';
                        const label = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                        return `<div class="fp-metric">
                            <div class="fp-metric-key">${escapeHtml(label)}</div>
                            <div class="fp-metric-val">${escapeHtml(String(displayValue))}</div>
                        </div>`;
                    }).join('')}
                </div>
            </div>`;
        }

        detailEl.innerHTML = `
            <div class="fp-detail-header">
                <span class="fp-detail-status ${comp.status}">${statusDot}</span>
                <div class="fp-detail-title">
                    <div class="fp-detail-name">${escapeHtml(name)}</div>
                    <div class="fp-detail-id">${escapeHtml(comp.id)}</div>
                </div>
            </div>
            <div class="fp-detail-section">
                <div class="fp-detail-section-title">Status</div>
                <div class="fp-detail-row"><span class="fp-detail-label">Health</span><span class="fp-detail-value">${escapeHtml(comp.status)}</span></div>
                <div class="fp-detail-row"><span class="fp-detail-label">Message</span><span class="fp-detail-value">${escapeHtml(comp.message || 'N/A')}</span></div>
                ${comp.last_check ? `<div class="fp-detail-row"><span class="fp-detail-label">Last Check</span><span class="fp-detail-value">${new Date(comp.last_check).toLocaleTimeString()}</span></div>` : ''}
            </div>
            ${metricsHtml}`;
    }
};

export function openFlightPathWindow() {
    document.getElementById('flightpath-window')?.open();
}

export function closeFlightPathWindow() {
    document.getElementById('flightpath-window')?.close();
}

export function initFlightPathEvents() {
    const win = document.getElementById('flightpath-window');
    if (!win) return;
    // 50ms delay preserves the original timing — gives layout a tick to settle.
    win.addEventListener('panel:open', () => setTimeout(() => flightPath.init(), 50));
    win.addEventListener('panel:close', () => {
        flightPath.stopHealthPolling();
        flightPath.cleanupEventListeners();
    });
}
