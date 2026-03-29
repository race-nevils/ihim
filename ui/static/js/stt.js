/**
 * stt.js — Dictation panel (History, Dictionary tabs)
 * Uses <ihim-panel> for window lifecycle and <ihim-tabs> for tab management.
 * Engine auto-starts on server boot; hotkey-driven workflow (no Start/Stop UI).
 */
import { API, escapeHtml } from './app.js';

let statusPollInterval = null;
let lastDictationId = null;

// =====================
// Window lifecycle
// =====================

export async function openSTTWindow() {
    const win = document.getElementById('stt-window');
    if (!win) return;
    win.open();
    if (typeof lucide !== 'undefined') lucide.createIcons();
    startStatusPolling();
    loadHistory();  // History is the default tab — load immediately
}

export function closeSTTWindow() {
    const win = document.getElementById('stt-window');
    if (win) win.close();
    stopStatusPolling();
}

export function toggleSTTWindow() {
    const win = document.getElementById('stt-window');
    if (!win) return;
    if (win.hasAttribute('open')) closeSTTWindow();
    else openSTTWindow();
}

// =====================
// Status polling
// =====================

function startStatusPolling() {
    if (statusPollInterval) return;
    pollStatus();
    statusPollInterval = setInterval(pollStatus, 2000);
}

function stopStatusPolling() {
    if (statusPollInterval) { clearInterval(statusPollInterval); statusPollInterval = null; }
}

async function pollStatus() {
    try {
        const res = await fetch(`${API}/api/stt/status`);
        if (!res.ok) return;
        const data = await res.json();
        renderStatus(data);
    } catch (e) { /* silent — polling resilience */ }
}

function renderStatus(data) {
    const badge = document.getElementById('stt-status-badge');
    if (!badge) return;

    badge.classList.remove('status-cold', 'status-warm', 'status-recording', 'status-processing', 'status-loading',
        'status-locked', 'status-warning');

    switch (data.status) {
        case 'warm':
            badge.textContent = 'WARM';
            badge.classList.add('status-warm');
            break;
        case 'recording':
            badge.textContent = 'REC';
            badge.classList.add('status-recording');
            break;
        case 'locked':
            badge.textContent = 'LOCKED';
            badge.classList.add('status-locked');
            break;
        case 'warning':
            badge.textContent = 'REC';
            badge.classList.add('status-warning');
            break;
        case 'processing':
            badge.textContent = 'PROCESSING';
            badge.classList.add('status-processing');
            break;
        case 'loading':
            badge.textContent = 'LOADING';
            badge.classList.add('status-loading');
            break;
        default:
            badge.textContent = 'COLD';
            badge.classList.add('status-cold');
            break;
    }

    // Auto-refresh history when a new dictation arrives
    if (data.last_result_id && data.last_result_id !== lastDictationId) {
        lastDictationId = data.last_result_id;
        loadHistory();
    }
}

// =====================
// History tab
// =====================

async function loadHistory() {
    const body = document.getElementById('stt-history-body');
    if (!body) return;
    body.innerHTML = '<div class="stt-loading">Loading dictations...</div>';

    try {
        const res = await fetch(`${API}/api/stt/history?limit=50`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const dictations = data.dictations || [];

        const countEl = document.getElementById('stt-history-count');
        if (countEl) countEl.textContent = `${data.total} dictation${data.total !== 1 ? 's' : ''}`;
        const wordEl = document.getElementById('stt-word-count');
        if (wordEl) wordEl.textContent = `${(data.total_words || 0).toLocaleString()} words`;

        if (dictations.length === 0) {
            body.innerHTML = '<div class="stt-placeholder">No dictations yet. Start listening and speak!</div>';
            return;
        }

        body.innerHTML = dictations.map(d => {
            const date = new Date(d.timestamp);
            const timeStr = date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
            const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            const text = d.correction ? d.correction.text : d.cleaned_text;
            const hasCorrection = !!d.correction;
            const flagged = d.flagged;

            return `<div class="stt-history-item${flagged ? ' flagged' : ''}" data-id="${escapeHtml(d.id)}">
                <div class="stt-history-meta">
                    <span class="stt-history-time">${dateStr} ${timeStr}</span>
                    <span class="stt-history-latency">${d.latency_ms}ms</span>
                    ${hasCorrection ? '<span class="stt-history-corrected" title="Corrected">&#10003;</span>' : ''}
                </div>
                <div class="stt-history-text" id="stt-text-${escapeHtml(d.id)}">${escapeHtml(text)}</div>
                <div class="stt-history-actions">
                    <button class="stt-action-btn stt-copy-btn" data-id="${escapeHtml(d.id)}" title="Copy to clipboard" aria-label="Copy dictation">
                        <i data-lucide="copy" style="width:14px;height:14px;"></i>
                    </button>
                    <button class="stt-action-btn stt-flag-btn${flagged ? ' active' : ''}" data-id="${escapeHtml(d.id)}" title="Flag for review" aria-label="Flag dictation">
                        <i data-lucide="flag" style="width:14px;height:14px;"></i>
                    </button>
                    <button class="stt-action-btn stt-edit-btn" data-id="${escapeHtml(d.id)}" title="Edit / Correct" aria-label="Edit dictation">
                        <i data-lucide="pencil" style="width:14px;height:14px;"></i>
                    </button>
                </div>
            </div>`;
        }).join('');

        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        body.innerHTML = `<div class="stt-error-inline">Failed to load history: ${escapeHtml(e.message)}</div>`;
    }
}

async function copyDictation(id) {
    const el = document.getElementById(`stt-text-${id}`);
    if (!el) return;
    try {
        await navigator.clipboard.writeText(el.textContent);
        el.classList.add('stt-copied');
        setTimeout(() => el.classList.remove('stt-copied'), 1000);
    } catch (e) {
        console.warn('Clipboard write failed:', e);
    }
}

async function flagDictation(id) {
    try {
        const res = await fetch(`${API}/api/stt/flag/${encodeURIComponent(id)}`, { method: 'POST' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        loadHistory();
    } catch (e) {
        showSTTError(`Failed to flag: ${e.message}`);
    }
}

function startEditDictation(id) {
    const textEl = document.getElementById(`stt-text-${id}`);
    if (!textEl) return;

    const originalText = textEl.textContent;
    const item = textEl.closest('.stt-history-item');
    if (!item) return;

    // Replace text with input field
    textEl.innerHTML = `<textarea class="stt-edit-textarea" id="stt-edit-${escapeHtml(id)}" rows="3">${escapeHtml(originalText)}</textarea>
        <div class="stt-edit-actions">
            <button class="stt-btn stt-save-btn" data-id="${escapeHtml(id)}">Save</button>
            <button class="stt-btn stt-cancel-btn" data-id="${escapeHtml(id)}">Cancel</button>
        </div>`;

    const textarea = document.getElementById(`stt-edit-${id}`);
    if (textarea) {
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }
}

async function saveCorrection(id) {
    const textarea = document.getElementById(`stt-edit-${id}`);
    if (!textarea) return;

    const correctedText = textarea.value.trim();
    if (!correctedText) return;

    try {
        const res = await fetch(`${API}/api/stt/correct/${encodeURIComponent(id)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ corrected_text: correctedText }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        loadHistory();
    } catch (e) {
        showSTTError(`Failed to save correction: ${e.message}`);
    }
}

function cancelEdit(id) {
    loadHistory(); // Simplest: just reload the list
}

// =====================
// Dictionary tab
// =====================

async function loadVocab() {
    const body = document.getElementById('stt-vocab-body');
    if (!body) return;
    body.innerHTML = '<div class="stt-loading">Loading vocabulary...</div>';

    try {
        const res = await fetch(`${API}/api/stt/vocab`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const terms = data.terms || [];

        const countEl = document.getElementById('stt-vocab-count');
        if (countEl) countEl.textContent = `${terms.length} term${terms.length !== 1 ? 's' : ''}`;

        if (terms.length === 0) {
            body.innerHTML = '<div class="stt-placeholder">No vocabulary terms. Add terms to improve recognition.</div>';
            return;
        }

        body.innerHTML = terms.map(t =>
            `<div class="stt-vocab-item">
                <span class="stt-vocab-term">${escapeHtml(t)}</span>
                <button class="stt-action-btn stt-vocab-remove" data-term="${escapeHtml(t)}" title="Remove term" aria-label="Remove ${escapeHtml(t)}">
                    <i data-lucide="x" style="width:14px;height:14px;"></i>
                </button>
            </div>`
        ).join('');

        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        body.innerHTML = `<div class="stt-error-inline">Failed to load vocabulary: ${escapeHtml(e.message)}</div>`;
    }
}

async function addVocabTerm() {
    const input = document.getElementById('stt-vocab-input');
    if (!input) return;
    const term = input.value.trim();
    if (!term) return;

    try {
        const res = await fetch(`${API}/api/stt/vocab`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ add: [term], remove: [] }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        input.value = '';
        loadVocab();
    } catch (e) {
        showSTTError(`Failed to add term: ${e.message}`);
    }
}

async function removeVocabTerm(term) {
    if (!confirm(`Remove "${term}" from dictionary?`)) return;
    try {
        const res = await fetch(`${API}/api/stt/vocab`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ add: [], remove: [term] }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        loadVocab();
    } catch (e) {
        showSTTError(`Failed to remove term: ${e.message}`);
    }
}

// =====================
// Error display
// =====================

function showSTTError(msg) {
    const el = document.getElementById('stt-error');
    if (el) { el.textContent = msg; el.style.display = 'block'; }
}

function hideSTTError() {
    const el = document.getElementById('stt-error');
    if (el) el.style.display = 'none';
}

// =====================
// Event delegation + init
// =====================

export function initSTTEvents() {
    const win = document.getElementById('stt-window');
    if (!win) return;

    // Cleanup on panel close
    win.addEventListener('panel:close', () => {
        stopStatusPolling();
    });

    // Tab change — load data on tab switch
    const tabs = win.querySelector('ihim-tabs');
    if (tabs) {
        tabs.addEventListener('tab:change', (e) => {
            const tabName = e.detail.tab?.dataset?.tab;
            if (tabName === 'history') loadHistory();
            if (tabName === 'dictionary') loadVocab();
        });
    }

    // Event delegation for all clicks within the panel
    win.addEventListener('click', (e) => {
        // History actions
        const copyBtn = e.target.closest('.stt-copy-btn');
        if (copyBtn) { copyDictation(copyBtn.dataset.id); return; }

        const flagBtn = e.target.closest('.stt-flag-btn');
        if (flagBtn) { flagDictation(flagBtn.dataset.id); return; }

        const editBtn = e.target.closest('.stt-edit-btn');
        if (editBtn) { startEditDictation(editBtn.dataset.id); return; }

        const saveBtn = e.target.closest('.stt-save-btn');
        if (saveBtn) { saveCorrection(saveBtn.dataset.id); return; }

        const cancelBtn = e.target.closest('.stt-cancel-btn');
        if (cancelBtn) { cancelEdit(cancelBtn.dataset.id); return; }

        // Vocab actions
        const removeBtn = e.target.closest('.stt-vocab-remove');
        if (removeBtn) { removeVocabTerm(removeBtn.dataset.term); return; }

        if (e.target.closest('#stt-vocab-add-btn')) { addVocabTerm(); return; }
    });

    // Enter key in vocab input
    const vocabInput = document.getElementById('stt-vocab-input');
    if (vocabInput) {
        vocabInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addVocabTerm(); }
        });
    }
}
