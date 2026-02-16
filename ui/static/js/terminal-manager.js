/**
 * terminal-manager.js — Mission Control: xterm.js terminals + Agent Workshop
 */
import { API, escapeHtml, showStatus } from './app.js';
import { makeDraggable } from './draggable.js';

// =====================
// Terminal Manager
// =====================

export const terminalManager = {
    tabs: [],
    activeTabId: null,
    tabCounter: 0,
    wsConnections: new Map(),

    init() { this.renderTabs(); this.updateFooterInfo(); },

    createTab(name = null) {
        this.tabCounter++;
        const tabId = `term-${this.tabCounter}`;
        const tabName = name || `Terminal ${this.tabCounter}`;
        const tab = { id: tabId, name: tabName, terminal: null, fitAddon: null, webLinksAddon: null, connected: false, resizeHandler: null };
        this.tabs.push(tab);
        this.renderTabs();
        this.activateTab(tabId);
        this.connectTerminal(tabId);
        return tabId;
    },

    closeTab(tabId) {
        const index = this.tabs.findIndex(t => t.id === tabId);
        if (index === -1) return;
        const ws = this.wsConnections.get(tabId);
        if (ws) { ws.close(); this.wsConnections.delete(tabId); }
        const tab = this.tabs[index];
        if (tab.terminal) tab.terminal.dispose();
        if (tab.resizeHandler) window.removeEventListener('resize', tab.resizeHandler);
        this.tabs.splice(index, 1);
        if (this.activeTabId === tabId) {
            if (this.tabs.length > 0) this.activateTab(this.tabs[Math.max(0, index - 1)].id);
            else this.activeTabId = null;
        }
        this.renderTabs();
        this.updateFooterInfo();
    },

    activateTab(tabId) {
        const tab = this.tabs.find(t => t.id === tabId);
        if (!tab) return;
        this.activeTabId = tabId;
        this.renderTabs();
        this.updateFooterInfo();
        setTimeout(() => {
            if (tab.terminal && tab.fitAddon) { tab.fitAddon.fit(); tab.terminal.focus(); }
        }, 50);
    },

    renderTabs() {
        const tabsContainer = document.getElementById('terminal-tabs');
        const panesContainer = document.getElementById('terminal-panes');
        if (!tabsContainer || !panesContainer) return;

        if (this.tabs.length === 0) {
            tabsContainer.innerHTML = '';
            panesContainer.innerHTML = `<div class="terminal-empty"><div class="terminal-empty-icon">⌘</div><div class="terminal-empty-text">No terminals open</div><div class="terminal-empty-hint">Click + to create a new terminal</div></div>`;
            return;
        }

        tabsContainer.innerHTML = this.tabs.map(tab => `
            <div class="terminal-tab ${tab.id === this.activeTabId ? 'active' : ''}" data-tab-id="${tab.id}">
                <span class="terminal-tab-icon">❯</span>
                <span class="terminal-tab-name">${escapeHtml(tab.name)}</span>
                <button class="terminal-tab-close" data-close-tab="${tab.id}">×</button>
            </div>
        `).join('');

        panesContainer.innerHTML = this.tabs.map(tab => `
            <div class="terminal-pane ${tab.id === this.activeTabId ? 'active' : ''}" id="pane-${tab.id}"></div>
        `).join('');

        this.tabs.forEach(tab => { if (!tab.terminal) this.initTerminalInstance(tab); });
    },

    initTerminalInstance(tab) {
        const pane = document.getElementById(`pane-${tab.id}`);
        if (!pane) return;
        const terminal = new Terminal({
            cursorBlink: true, fontSize: 14,
            fontFamily: "'SF Mono', 'Monaco', 'Consolas', 'Liberation Mono', monospace",
            theme: {
                background: '#0a0a0a', foreground: '#e5e5e5', cursor: '#3d6f9a', cursorAccent: '#0a0a0a',
                selection: 'rgba(61, 111, 154, 0.3)', black: '#1a1a1a', red: '#f87171', green: '#4ade80',
                yellow: '#fbbf24', blue: '#3d6f9a', magenta: '#a78bfa', cyan: '#22d3ee', white: '#e5e5e5',
                brightBlack: '#555555', brightRed: '#ef4444', brightGreen: '#22c55e', brightYellow: '#f59e0b',
                brightBlue: '#4a8ac2', brightMagenta: '#8b5cf6', brightCyan: '#06b6d4', brightWhite: '#ffffff'
            },
            scrollback: 5000, allowTransparency: true
        });
        const fitAddon = new FitAddon.FitAddon();
        const webLinksAddon = new WebLinksAddon.WebLinksAddon();
        terminal.loadAddon(fitAddon); terminal.loadAddon(webLinksAddon);
        terminal.open(pane); fitAddon.fit();
        tab.terminal = terminal; tab.fitAddon = fitAddon; tab.webLinksAddon = webLinksAddon;

        terminal.writeln('\x1b[38;5;67m┌─────────────────────────────────────────┐\x1b[0m');
        terminal.writeln('\x1b[38;5;67m│\x1b[0m  \x1b[1;37miHIM Mission Control\x1b[0m                   \x1b[38;5;67m│\x1b[0m');
        terminal.writeln('\x1b[38;5;67m│\x1b[0m  \x1b[38;5;246mConnecting to PTY backend...\x1b[0m           \x1b[38;5;67m│\x1b[0m');
        terminal.writeln('\x1b[38;5;67m└─────────────────────────────────────────┘\x1b[0m');
        terminal.writeln('');

        const resizeHandler = () => { if (tab.fitAddon && tab.id === this.activeTabId) tab.fitAddon.fit(); };
        window.addEventListener('resize', resizeHandler);
        tab.resizeHandler = resizeHandler;
    },

    connectTerminal(tabId) {
        const tab = this.tabs.find(t => t.id === tabId);
        if (!tab || !tab.terminal) return;
        this.updateConnectionStatus('connecting');
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/api/terminal/ws/${tabId}`;
        try {
            const ws = new WebSocket(wsUrl);
            this.wsConnections.set(tabId, ws);
            ws.onopen = () => {
                tab.connected = true; this.updateConnectionStatus('connected');
                tab.terminal.writeln('\x1b[32m✓ Connected to terminal\x1b[0m'); tab.terminal.writeln('');
                ws.send(JSON.stringify({ type: 'resize', cols: tab.terminal.cols, rows: tab.terminal.rows }));
            };
            ws.onmessage = (event) => {
                if (typeof event.data === 'string') {
                    try {
                        const msg = JSON.parse(event.data);
                        if (msg.type === 'output') tab.terminal.write(msg.data);
                        else if (msg.type === 'exit') { tab.terminal.writeln(''); tab.terminal.writeln(`\x1b[33m[Process exited with code ${msg.code}]\x1b[0m`); }
                    } catch { tab.terminal.write(event.data); }
                }
            };
            ws.onclose = () => {
                tab.connected = false;
                if (this.activeTabId === tabId) this.updateConnectionStatus('disconnected');
                tab.terminal.writeln(''); tab.terminal.writeln('\x1b[31m✕ Disconnected from terminal\x1b[0m');
            };
            ws.onerror = (error) => {
                console.error('Terminal WebSocket error:', error);
                tab.terminal.writeln('\x1b[31m✕ Connection error\x1b[0m');
                this.updateConnectionStatus('disconnected');
            };
            tab.terminal.onData((data) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data })); });
            tab.terminal.onResize(({ cols, rows }) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols, rows })); });
        } catch (error) {
            console.error('Failed to connect terminal:', error);
            tab.terminal.writeln('\x1b[31m✕ Failed to connect to terminal backend\x1b[0m');
            this.updateConnectionStatus('disconnected');
        }
    },

    updateConnectionStatus(status) {
        const statusEl = document.getElementById('terminal-connection-status');
        if (!statusEl) return;
        statusEl.className = `terminal-connection-status ${status}`;
        const statusText = statusEl.querySelector('.status-text');
        if (statusText) statusText.textContent = { connected: 'Connected', connecting: 'Connecting...', disconnected: 'Disconnected' }[status] || 'Unknown';
    },

    updateFooterInfo() {
        const countEl = document.getElementById('terminal-tab-count');
        const infoEl = document.getElementById('terminal-active-info');
        if (countEl) countEl.textContent = `${this.tabs.length} terminal${this.tabs.length !== 1 ? 's' : ''}`;
        const activeTab = this.tabs.find(t => t.id === this.activeTabId);
        if (infoEl) infoEl.textContent = activeTab ? activeTab.name : '--';
    },

    clearActiveTerminal() {
        const tab = this.tabs.find(t => t.id === this.activeTabId);
        if (tab?.terminal) tab.terminal.clear();
    },

    reconnect() {
        const tab = this.tabs.find(t => t.id === this.activeTabId);
        if (!tab) return;
        const ws = this.wsConnections.get(tab.id);
        if (ws) { ws.close(); this.wsConnections.delete(tab.id); }
        tab.terminal.writeln(''); tab.terminal.writeln('\x1b[33m↻ Reconnecting...\x1b[0m');
        setTimeout(() => this.connectTerminal(tab.id), 500);
    }
};

// =====================
// Mission Control Window
// =====================

export function openMCWindow() {
    const mcWindow = document.getElementById('mc-window');
    mcWindow.style.display = 'flex';
    let posRestored = false;
    try {
        const savedPos = localStorage.getItem('mcWindowPosition');
        if (savedPos) {
            const { x, y } = JSON.parse(savedPos);
            if (x >= 0 && y >= 0 && x < window.innerWidth - 50 && y < window.innerHeight - 50) {
                mcWindow.style.left = x + 'px'; mcWindow.style.top = y + 'px'; posRestored = true;
            }
        }
    } catch (e) { console.warn('Failed to restore MC position:', e); }
    if (!posRestored) {
        const rect = mcWindow.getBoundingClientRect();
        mcWindow.style.left = Math.max(20, (window.innerWidth - rect.width) / 2) + 'px';
        mcWindow.style.top = Math.max(20, (window.innerHeight - rect.height) / 2) + 'px';
    }
    if (!mcWindow.dataset.dragInitialized) {
        makeDraggable('mc-window', '.mc-drag-handle', 'mcWindowPosition');
        mcWindow.dataset.dragInitialized = 'true';
    }
    if (terminalManager.tabs.length === 0) { terminalManager.init(); terminalManager.createTab(); }
    else {
        const activeTab = terminalManager.tabs.find(t => t.id === terminalManager.activeTabId);
        if (activeTab?.fitAddon) setTimeout(() => { activeTab.fitAddon.fit(); activeTab.terminal.focus(); }, 50);
    }
}

export function closeMCWindow() { document.getElementById('mc-window').style.display = 'none'; }

// =====================
// Agent Workshop
// =====================

let savedAgents = [];
let editingAgentId = null;

export function switchMCSection(section) {
    document.querySelectorAll('.mc-tab-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.section === section));
    document.querySelectorAll('.mc-section-panel').forEach(panel => panel.classList.toggle('active', panel.id === `mc-section-${section}`));
}

function newAgent() { editingAgentId = null; clearAgentForm(); }

function clearAgentForm() {
    document.getElementById('agent-name').value = '';
    document.getElementById('agent-tier').value = 'haiku';
    document.getElementById('agent-description').value = '';
    document.getElementById('agent-skills').value = '';
    document.getElementById('skill-preview').innerHTML = '';
    editingAgentId = null;
    updateTierIndicator();
}

function updateTierIndicator() {
    const tier = document.getElementById('agent-tier').value;
    const indicator = document.getElementById('tier-indicator');
    indicator.className = `tier-indicator tier-${tier}`;
    const configs = {
        haiku: { icon: '👁', label: 'Scout', badge: 'READ-ONLY', badgeClass: 'read-only' },
        sonnet: { icon: '🔧', label: 'Operator', badge: 'READ/WRITE', badgeClass: 'read-write' },
        opus: { icon: '🏛', label: 'Architect', badge: 'FULL ACCESS', badgeClass: 'full' }
    };
    const config = configs[tier];
    indicator.innerHTML = `<span class="tier-icon">${config.icon}</span><span class="tier-label">${config.label}</span><span class="tier-badge ${config.badgeClass}">${config.badge}</span>`;
}

function updateSkillPreviews() {
    const skillsInput = document.getElementById('agent-skills').value.trim();
    const previewContainer = document.getElementById('skill-preview');
    if (!skillsInput) { previewContainer.innerHTML = ''; return; }
    const skills = skillsInput.split(',').map(s => s.trim()).filter(Boolean);
    previewContainer.innerHTML = skills.map(skill => `<span class="skill-pill">${skill}</span>`).join('');
}

async function saveAgent() {
    const name = document.getElementById('agent-name').value.trim();
    const tier = document.getElementById('agent-tier').value;
    const description = document.getElementById('agent-description').value.trim();
    const skillsRaw = document.getElementById('agent-skills').value.trim();
    if (!name) { showMCStatus('Agent name is required', 'error'); return; }
    if (!description) { showMCStatus('Description/prompt is required', 'error'); return; }
    const skills = skillsRaw ? skillsRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
    const agent = { id: editingAgentId || name.toLowerCase().replace(/\s+/g, '-'), name, tier, description, skills };
    try {
        const res = await fetch(`${API}/api/agents`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(agent) });
        const data = await res.json();
        if (data.success) { showMCStatus(`Agent "${name}" saved`, 'success'); clearAgentForm(); loadAgents(); }
        else showMCStatus(data.message || 'Failed to save agent', 'error');
    } catch (err) { console.error('Save error:', err); showMCStatus('Network error - check if server is running', 'error'); }
}

async function loadAgents() {
    const listEl = document.getElementById('agent-list');
    listEl.innerHTML = '<div style="color:#666;padding:10px;">Loading...</div>';
    try {
        const res = await fetch(`${API}/api/agents`);
        const data = await res.json();
        savedAgents = data.agents || [];
        if (savedAgents.length === 0) { listEl.innerHTML = '<div style="color:#666;padding:10px;">No saved agents yet. Create one!</div>'; return; }
        const tierIcons = { haiku: '👁', sonnet: '🔧', opus: '🏛' };
        listEl.innerHTML = savedAgents.map(agent => {
            const skillsHtml = agent.skills?.length > 0 ? `<div class="mc-agent-card-skills">${agent.skills.map(skill => `<span class="mc-agent-card-skill-pill">${skill}</span>`).join('')}</div>` : '';
            return `<div class="mc-agent-card tier-${agent.tier}" data-agent-id="${agent.id}">
                <div class="mc-agent-card-header"><span class="mc-agent-card-tier-icon">${tierIcons[agent.tier] || '⚙'}</span><div class="mc-agent-card-name">${agent.name}</div></div>
                <div class="mc-agent-card-tier ${agent.tier}">${agent.tier}</div>${skillsHtml}
            </div>`;
        }).join('');
    } catch (err) { console.error('Load agents error:', err); listEl.innerHTML = '<div style="color:#f66;padding:10px;">Failed to load agents</div>'; }
}

function loadAgentToForm(agentId) {
    const agent = savedAgents.find(a => a.id === agentId);
    if (!agent) return;
    editingAgentId = agent.id;
    document.getElementById('agent-name').value = agent.name;
    document.getElementById('agent-tier').value = agent.tier;
    document.getElementById('agent-description').value = agent.description;
    document.getElementById('agent-skills').value = (agent.skills || []).join(', ');
    updateTierIndicator(); updateSkillPreviews();
    showMCStatus(`Editing "${agent.name}"`, 'success');
}

function newTeam() { showMCStatus('Team composer coming soon', 'success'); }
function newWorkflow() { showMCStatus('Workflow planner coming soon', 'success'); }

function showMCStatus(message, type) {
    const status = document.getElementById('mc-status');
    status.textContent = message;
    status.className = `mc-status mc-status-${type}`;
    status.style.display = 'block';
    setTimeout(() => { status.style.display = 'none'; }, 5000);
}

// =====================
// MC Event Initialization
// =====================

export function initMCEvents() {
    const mcWindow = document.getElementById('mc-window');
    if (!mcWindow) return;

    // Terminal tab and pane event delegation
    mcWindow.addEventListener('click', (e) => {
        // Tab activation
        const tab = e.target.closest('[data-tab-id]');
        if (tab && !e.target.closest('[data-close-tab]')) { terminalManager.activateTab(tab.dataset.tabId); return; }
        // Tab close
        const closeBtn = e.target.closest('[data-close-tab]');
        if (closeBtn) { e.stopPropagation(); terminalManager.closeTab(closeBtn.dataset.closeTab); return; }
        // MC section tabs
        const sectionBtn = e.target.closest('.mc-tab-btn');
        if (sectionBtn?.dataset.section) { switchMCSection(sectionBtn.dataset.section); return; }
        // Agent cards
        const agentCard = e.target.closest('[data-agent-id]');
        if (agentCard) { loadAgentToForm(agentCard.dataset.agentId); return; }
        // New buttons
        if (e.target.closest('.mc-btn-small')) {
            const text = e.target.textContent.trim();
            if (text === '+ New') {
                const panel = e.target.closest('.mc-section-panel');
                if (panel?.id === 'mc-section-agents') newAgent();
                else if (panel?.id === 'mc-section-teams') newTeam();
                else if (panel?.id === 'mc-section-workflows') newWorkflow();
            }
        }
        // Save/Clear agent
        if (e.target.classList.contains('mc-btn-primary')) saveAgent();
        if (e.target.classList.contains('mc-btn-secondary')) clearAgentForm();
    });

    // Footer buttons
    mcWindow.querySelector('.mc-footer-right')?.addEventListener('click', (e) => {
        const btn = e.target.closest('.mc-footer-btn');
        if (!btn) return;
        if (btn.title === 'Clear') terminalManager.clearActiveTerminal();
        else if (btn.title === 'Reconnect') terminalManager.reconnect();
    });

    // Agent tier change
    document.getElementById('agent-tier')?.addEventListener('change', updateTierIndicator);
    // Agent skills input
    document.getElementById('agent-skills')?.addEventListener('input', updateSkillPreviews);
}
