/**
 * chat-manager.js — Brain Chat (WebSocket RAG), Team Modal, and Agent Team Builder Modal
 */
import { API, escapeHtml, showStatus } from './app.js';
import { openWithFocusRestore, closeWithFocusRestore } from './a11y.js';

// =====================
// Brain Chat Manager
// =====================

export const chatManager = {
    ws: null,
    sessionId: null,
    isGenerating: false,
    currentAssistantEl: null,
    currentSources: null,
    reconnectTimer: null,
    reconnectAttempts: 0,

    init() {
        this.sessionId = 'chat-' + Date.now().toString(36);
        this.connect();
    },

    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/api/chat/ws/${this.sessionId}`;
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            this.reconnectAttempts = 0;
            if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
        };

        this.ws.onmessage = (e) => {
            try { this.handleMessage(JSON.parse(e.data)); }
            catch (err) { console.error('Chat WS parse error:', err); }
        };

        this.ws.onclose = () => {
            this.updateStatus('disconnected');
            if (this.reconnectAttempts < 10) {
                const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
                this.reconnectAttempts++;
                this.reconnectTimer = setTimeout(() => this.connect(), delay);
            }
        };

        this.ws.onerror = () => { this.updateStatus('disconnected'); };
    },

    handleMessage(data) {
        switch (data.type) {
            case 'connected': this.updateStatus('connected'); break;
            case 'retrieval_start':
                document.getElementById('chat-retrieval-indicator').classList.add('active'); break;
            case 'retrieval_result':
                document.getElementById('chat-retrieval-indicator').classList.remove('active');
                this.currentSources = data.entries || []; break;
            case 'generation_start':
                this.isGenerating = true;
                this.currentAssistantEl = this.addMessageBubble('assistant', '');
                document.getElementById('chat-send-btn').disabled = true; break;
            case 'token':
                if (this.currentAssistantEl) {
                    const textNode = this.currentAssistantEl.querySelector('.chat-msg-text');
                    if (textNode) textNode.textContent += data.content;
                    this.scrollToBottom();
                } break;
            case 'generation_end':
                this.isGenerating = false;
                document.getElementById('chat-send-btn').disabled = false;
                if (this.currentAssistantEl && this.currentSources?.length > 0)
                    this.addSourceChips(this.currentAssistantEl, this.currentSources);
                this.currentAssistantEl = null;
                this.currentSources = null;
                this.scrollToBottom(); break;
            case 'cleared':
                document.getElementById('chat-messages').innerHTML =
                    '<div class="chat-welcome"><strong>Brain Chat</strong>History cleared. Ask a new question.</div>'; break;
            case 'error':
                this.addMessageBubble('system', 'Error: ' + data.message);
                this.isGenerating = false;
                document.getElementById('chat-send-btn').disabled = false; break;
            case 'pong': break;
        }
    },

    send() {
        const input = document.getElementById('chat-input');
        const text = input.value.trim();
        if (!text || this.isGenerating) return;
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.addMessageBubble('system', 'Not connected. Reconnecting...');
            this.connect(); return;
        }
        this.addMessageBubble('user', text);
        this.ws.send(JSON.stringify({ type: 'message', content: text }));
        input.value = '';
        this.autoResize(input);
        this.scrollToBottom();
    },

    handleKeydown(event) {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.send(); }
    },

    clearHistory() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN)
            this.ws.send(JSON.stringify({ type: 'clear' }));
    },

    addMessageBubble(role, text) {
        const msgs = document.getElementById('chat-messages');
        const welcome = msgs.querySelector('.chat-welcome');
        if (welcome) welcome.remove();
        const bubble = document.createElement('div');
        bubble.className = `chat-msg ${role}`;
        const textSpan = document.createElement('span');
        textSpan.className = 'chat-msg-text';
        textSpan.textContent = text;
        bubble.appendChild(textSpan);
        msgs.appendChild(bubble);
        this.scrollToBottom();
        return bubble;
    },

    addSourceChips(el, sources) {
        if (!sources || sources.length === 0) return;
        const container = document.createElement('div');
        container.className = 'chat-source-chips';
        sources.forEach(s => {
            const chip = document.createElement('span');
            chip.className = 'chat-source-chip';
            chip.textContent = `${s.category}: ${s.title}`;
            chip.title = `Score: ${s.score}`;
            container.appendChild(chip);
        });
        el.appendChild(container);
    },

    scrollToBottom() {
        const msgs = document.getElementById('chat-messages');
        msgs.scrollTop = msgs.scrollHeight;
    },

    autoResize(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 100) + 'px';
    },

    updateStatus(state) {
        const dot = document.getElementById('chat-status-dot');
        if (!dot) return;
        dot.className = 'chat-status-dot ' + state;
    },

    destroy() {
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        if (this.ws) { this.ws.onclose = null; this.ws.close(); }
    }
};

// =====================
// Chat Window Functions
// =====================

export function openChatWindow() {
    const win = document.getElementById('chat-window');
    if (!win) return;
    win.open();
    if (!chatManager.ws || chatManager.ws.readyState !== WebSocket.OPEN) chatManager.init();
    document.getElementById('chat-input').focus();
}

export function closeChatWindow() {
    const win = document.getElementById('chat-window');
    if (win) win.close();
}

export function toggleChatWindow() {
    const win = document.getElementById('chat-window');
    if (!win) return;
    if (win.hasAttribute('open')) closeChatWindow();
    else openChatWindow();
}

export function toggleChatMinimize() {
    const win = document.getElementById('chat-window');
    if (win) win.classList.toggle('minimized');
}

// =====================
// Team Modal (Feature Builder)
// =====================

export function openTeamModal() {
    const dialog = document.getElementById('team-modal');
    if (!dialog) return;
    openWithFocusRestore(dialog, document.activeElement);
    setTimeout(() => document.getElementById('team-prompt')?.focus(), 100);
}

export function closeTeamModal() {
    const dialog = document.getElementById('team-modal');
    if (!dialog) return;
    document.getElementById('team-prompt').value = '';
    closeWithFocusRestore(dialog);
}

export async function spawnTeam() {
    const prompt = document.getElementById('team-prompt').value.trim();
    if (!prompt) { showStatus('Please enter a task description', 'error'); return; }
    showStatus('Spawning team...', 'pending');
    closeTeamModal();
    try {
        const res = await fetch(`${API}/api/team/spawn`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, project: 'workspace' })
        });
        const data = await res.json();
        showStatus(data.message, data.success ? 'success' : 'error');
    } catch (err) { showStatus('Failed to spawn team', 'error'); }
}

// =====================
// Agent Team Builder Modal
// =====================

let selectedTeamType = 'auto';
const teamConfigs = {
    auto: { name: 'Auto-detect', agents: [
        { icon: '🎯', name: 'Lead', role: 'Coordinates team' },
        { icon: '🔍', name: 'Analyst', role: 'Research & planning' },
        { icon: '⚡', name: 'Executor', role: 'Implementation' }
    ]},
    project: { name: 'Project Team', agents: [
        { icon: '📋', name: 'PM', role: 'Project management' },
        { icon: '🎨', name: 'Designer', role: 'UI/UX design' },
        { icon: '💻', name: 'Developer', role: 'Implementation' },
        { icon: '🧪', name: 'QA', role: 'Testing & quality' },
        { icon: '🚀', name: 'DevOps', role: 'Deployment' }
    ]},
    research: { name: 'Research Team', agents: [
        { icon: '🔬', name: 'Researcher', role: 'Deep investigation' },
        { icon: '📊', name: 'Analyst', role: 'Data analysis' },
        { icon: '📝', name: 'Writer', role: 'Documentation' }
    ]},
    custom: { name: 'Custom', agents: [
        { icon: '🎯', name: 'Agent 1', role: 'Custom role' },
        { icon: '🎯', name: 'Agent 2', role: 'Custom role' },
        { icon: '🎯', name: 'Agent 3', role: 'Custom role' }
    ]}
};

export function openAgentTeamModal() {
    const dialog = document.getElementById('agent-team-modal');
    if (!dialog) return;
    openWithFocusRestore(dialog, document.activeElement);
    setTimeout(() => document.getElementById('agent-team-prompt')?.focus(), 100);
    updateAgentPreview();
}

export function closeAgentTeamModal() {
    const dialog = document.getElementById('agent-team-modal');
    if (!dialog) return;
    document.getElementById('agent-team-prompt').value = '';
    selectedTeamType = 'auto';
    document.getElementById('team-size-slider').value = 3;
    updateTeamSizeDisplay();
    document.querySelectorAll('#agent-team-modal .team-type-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.type === 'auto') btn.classList.add('active');
    });
    closeWithFocusRestore(dialog);
}

export function selectTeamType(type) {
    selectedTeamType = type;
    document.querySelectorAll('#agent-team-modal .team-type-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.type === type) btn.classList.add('active');
    });
    updateAgentPreview();
}

export function updateTeamSizeDisplay() {
    const slider = document.getElementById('team-size-slider');
    const display = document.getElementById('team-size-display');
    if (!slider || !display) return;
    display.textContent = `${slider.value} agents`;
    updateAgentPreview();
}

function updateAgentPreview() {
    const slider = document.getElementById('team-size-slider');
    const previewList = document.getElementById('agent-preview-list');
    if (!slider || !previewList) return;
    const size = parseInt(slider.value);
    const config = teamConfigs[selectedTeamType];
    let agents = [...config.agents];
    if (selectedTeamType === 'auto' || selectedTeamType === 'custom') {
        while (agents.length < size) agents.push({ icon: '⚡', name: `Agent ${agents.length + 1}`, role: 'Specialist' });
        agents = agents.slice(0, size);
    } else if (selectedTeamType === 'project') {
        agents = config.agents.slice(0, size);
    } else if (selectedTeamType === 'research') {
        agents = config.agents.slice(0, Math.min(size, config.agents.length));
        while (agents.length < size) agents.push({ icon: '📚', name: `Expert ${agents.length + 1}`, role: 'Domain specialist' });
    }
    previewList.innerHTML = agents.map(agent => `
        <div class="agent-preview-item">
            <span class="agent-preview-icon">${agent.icon}</span>
            <span class="agent-preview-name">${agent.name}</span>
            <span class="agent-preview-role">${agent.role}</span>
        </div>
    `).join('');
}

export async function spawnAgentTeam() {
    const prompt = document.getElementById('agent-team-prompt').value.trim();
    if (!prompt) { showStatus('Please describe what you want to accomplish', 'error'); return; }
    const size = parseInt(document.getElementById('team-size-slider').value);
    const useFeedback = document.getElementById('config-feedback').checked;
    const allowParallel = document.getElementById('config-parallel').checked;
    showStatus(`Spawning ${size}-agent team...`, 'pending');
    closeAgentTeamModal();
    try {
        const res = await fetch(`${API}/api/team/spawn-custom`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt, team_type: selectedTeamType, team_size: size, project: 'workspace',
                options: { use_blackboard: false, use_feedback: useFeedback, allow_parallel: allowParallel }
            })
        });
        const data = await res.json();
        showStatus(data.message || (data.success ? `Team of ${size} agents spawned!` : 'Failed to spawn team'),
            data.success ? 'success' : 'error');
    } catch (err) {
        console.error('Failed to spawn agent team:', err);
        showStatus('Failed to spawn team - API error', 'error');
    }
}

// =====================
// Chat Event Initialization
// =====================

export function initChatEvents() {
    // Chat input handlers
    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
        chatInput.addEventListener('keydown', (e) => chatManager.handleKeydown(e));
        chatInput.addEventListener('input', () => chatManager.autoResize(chatInput));
    }

    // Chat window buttons
    const chatHeader = document.getElementById('chat-window')?.querySelector('.chat-header-actions');
    if (chatHeader) {
        const [clearBtn, minBtn, closeBtn] = chatHeader.querySelectorAll('button');
        if (clearBtn) clearBtn.addEventListener('click', () => chatManager.clearHistory());
        if (minBtn) minBtn.addEventListener('click', toggleChatMinimize);
        if (closeBtn) closeBtn.addEventListener('click', closeChatWindow);
    }

    // Send button
    document.getElementById('chat-send-btn')?.addEventListener('click', () => chatManager.send());

    // Team modal: backdrop click + ESC cleanup
    const teamDialog = document.getElementById('team-modal');
    teamDialog?.addEventListener('click', (e) => {
        if (e.target === teamDialog) closeTeamModal();
    });
    teamDialog?.addEventListener('close', () => {
        document.getElementById('team-prompt').value = '';
    });

    // Agent team modal: backdrop click + ESC cleanup
    const agentDialog = document.getElementById('agent-team-modal');
    agentDialog?.addEventListener('click', (e) => {
        if (e.target === agentDialog) closeAgentTeamModal();
    });
    agentDialog?.addEventListener('close', () => {
        document.getElementById('agent-team-prompt').value = '';
        selectedTeamType = 'auto';
        document.getElementById('team-size-slider').value = 3;
        updateTeamSizeDisplay();
        document.querySelectorAll('#agent-team-modal .team-type-btn').forEach(btn => {
            btn.classList.remove('active');
            if (btn.dataset.type === 'auto') btn.classList.add('active');
        });
    });
    document.getElementById('agent-team-prompt')?.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') spawnAgentTeam();
    });

    // Team size slider
    document.getElementById('team-size-slider')?.addEventListener('input', updateTeamSizeDisplay);

    // Team type buttons (via event delegation)
    document.getElementById('agent-team-modal')?.addEventListener('click', (e) => {
        const btn = e.target.closest('.team-type-btn');
        if (btn?.dataset.type) selectTeamType(btn.dataset.type);
    });
}
