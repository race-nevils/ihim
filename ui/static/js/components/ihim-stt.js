/**
 * <ihim-stt> — STT window (speech-to-text dictation — History, Dictionary
 * tabs; engine subsystem name stays "stt" in paths/APIs).
 * Extends IhimPanel: IS the draggable window; renders its own chrome +
 * content, loads data on its panel:open / panel:close lifecycle.
 * Engine auto-starts on server boot; hotkey-driven workflow (no Start/Stop UI).
 */
import { API, escapeHtml } from '../app.js';
import { IhimPanel } from './ihim-panel.js';
import './ihim-tabs.js';

class IhimSTT extends IhimPanel {
    _statusSource = null;
    _lastDictationId = null;
    _muteOnDictate = true;
    _modelLoaded = false;

    connectedCallback() {
        this.innerHTML = `
            <span class="stt-titlebar-group" data-titlebar-slot>
                <span class="stt-status-badge" id="stt-status-badge" aria-live="polite" role="status">IDLE</span>
                <button type="button" class="stt-mute-toggle" id="stt-mute-toggle" aria-pressed="true"
                    title="Mute system audio while dictating" aria-label="Mute system audio while dictating">
                    <i data-lucide="volume-x" style="width:14px;height:14px;"></i>
                </button>
                <button type="button" class="stt-unload-btn off" id="stt-unload-btn"
                    title="Transcription model not loaded" aria-label="Transcription model not loaded" disabled>
                    <i data-lucide="memory-stick" style="width:14px;height:14px;"></i>
                </button>
            </span>

            <ihim-tabs>
            <!-- Tabs -->
            <div class="stt-tabs" role="tablist" aria-label="STT">
                <button class="stt-tab-btn active" data-tab="history" role="tab" id="stt-tab-history-btn" aria-selected="true" aria-controls="stt-tab-history" tabindex="0">History</button>
                <button class="stt-tab-btn" data-tab="dictionary" role="tab" id="stt-tab-dictionary-btn" aria-selected="false" aria-controls="stt-tab-dictionary" tabindex="-1">Dictionary</button>
            </div>

            <!-- Error display (shared) -->
            <div class="stt-error" id="stt-error" role="alert" aria-live="assertive" style="display: none;"></div>

            <!-- History Tab -->
            <div id="stt-tab-history" class="stt-tab-content active" role="tabpanel" aria-labelledby="stt-tab-history-btn">
                <div class="stt-list-header">
                    <span class="stt-history-count" id="stt-history-count">0 dictations</span>
                    <span class="stt-history-count" id="stt-word-count" style="margin-left:12px;opacity:0.7;">0 words</span>
                </div>
                <div class="stt-body stt-history-scroll" id="stt-history-body">
                    <div class="stt-placeholder">Switch to this tab to load dictation history.</div>
                </div>
            </div>

            <!-- Dictionary Tab -->
            <div id="stt-tab-dictionary" class="stt-tab-content" role="tabpanel" aria-labelledby="stt-tab-dictionary-btn">
                <div class="stt-list-header">
                    <span class="stt-vocab-count" id="stt-vocab-count">0 terms</span>
                </div>
                <div class="stt-vocab-add-row">
                    <label for="stt-vocab-input" class="sr-only">Add vocabulary term</label>
                    <input type="text" id="stt-vocab-input" placeholder="Add a term..." maxlength="100" />
                    <button class="stt-btn" id="stt-vocab-add-btn">Add</button>
                </div>
                <div class="stt-body stt-vocab-scroll" id="stt-vocab-body">
                    <div class="stt-placeholder">Switch to this tab to load vocabulary.</div>
                </div>
            </div>
            </ihim-tabs>
        `;
        this._wireEvents();
        super.connectedCallback();
    }

    disconnectedCallback() {
        this._stopStatusPolling();
    }

    // =====================
    // Status stream (SSE)
    // =====================

    _startStatusPolling() {
        if (this._statusSource) return;
        this._statusSource = new EventSource(`${API}/api/stt/status/stream`);
        this._statusSource.onmessage = (e) => {
            try { this._renderStatus(JSON.parse(e.data)); } catch {}
        };
        // Connection lost (server down, sleep/wake drop) — say so instead of
        // freezing the badge at the last known state. On reconnect the server
        // pushes current status immediately, which overwrites this.
        this._statusSource.onerror = () => {
            this._renderStatus({ status: 'offline' });
        };
    }

    _stopStatusPolling() {
        if (this._statusSource) { this._statusSource.close(); this._statusSource = null; }
    }

    _renderStatus(data) {
        const badge = this.querySelector('#stt-status-badge');
        if (!badge) return;

        badge.classList.remove('status-cold', 'status-warm', 'status-recording', 'status-processing', 'status-loading',
            'status-locked', 'status-offline');

        switch (data.status) {
            case 'offline':
                badge.textContent = 'OFFLINE';
                badge.classList.add('status-offline');
                break;
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

        // Server is authoritative for the mute toggle (any client may flip it)
        if (typeof data.mute_on_dictate === 'boolean') {
            this._renderMuteToggle(data.mute_on_dictate);
        }

        if (typeof data.model_loaded === 'boolean') {
            this._renderUnloadBtn(data.model_loaded);
        }

        // Auto-refresh history when a new dictation arrives
        if (data.last_result_id && data.last_result_id !== this._lastDictationId) {
            this._lastDictationId = data.last_result_id;
            this._loadHistory();
        }
    }

    // =====================
    // Dictation mute toggle
    // =====================

    _renderMuteToggle(enabled) {
        this._muteOnDictate = enabled;
        const btn = this.querySelector('#stt-mute-toggle');
        if (!btn) return;
        const label = enabled
            ? 'Dictation mute on — system audio silenced while dictating'
            : 'Dictation mute off — system audio stays audible while dictating';
        btn.setAttribute('aria-pressed', String(enabled));
        btn.classList.toggle('off', !enabled);
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.innerHTML = `<i data-lucide="${enabled ? 'volume-x' : 'volume-2'}" style="width:14px;height:14px;"></i>`;
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    async _toggleMute() {
        const next = !this._muteOnDictate;
        this._renderMuteToggle(next);  // optimistic — revert on failure
        try {
            const res = await fetch(`${API}/api/stt/mute`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: next }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (e) {
            this._renderMuteToggle(!next);
            this._showError(`Failed to toggle dictation mute: ${e.message}`);
        }
    }

    // =====================
    // Model unload button
    // =====================

    _renderUnloadBtn(loaded) {
        this._modelLoaded = loaded;
        const btn = this.querySelector('#stt-unload-btn');
        if (!btn) return;
        const label = loaded
            ? 'Unload transcription model — free VRAM'
            : 'Transcription model not loaded';
        btn.disabled = !loaded;
        btn.classList.toggle('off', !loaded);
        btn.title = label;
        btn.setAttribute('aria-label', label);
    }

    async _unloadModel() {
        if (!this._modelLoaded) return;
        try {
            const res = await fetch(`${API}/api/stt/unload`, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            // Status stream pushes cold + model_loaded=false; nothing to do here
        } catch (e) {
            this._showError(`Failed to unload model: ${e.message}`);
        }
    }

    // =====================
    // History tab
    // =====================

    async _loadHistory() {
        const body = this.querySelector('#stt-history-body');
        if (!body) return;
        body.innerHTML = '<div class="stt-loading">Loading dictations...</div>';

        try {
            const res = await fetch(`${API}/api/stt/history?limit=50`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const dictations = data.dictations || [];

            const countEl = this.querySelector('#stt-history-count');
            if (countEl) countEl.textContent = `${data.total} dictation${data.total !== 1 ? 's' : ''}`;
            const wordEl = this.querySelector('#stt-word-count');
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

    async _copyDictation(id) {
        const el = this.querySelector(`#stt-text-${CSS.escape(id)}`);
        if (!el) return;
        try {
            await navigator.clipboard.writeText(el.textContent);
            el.classList.add('stt-copied');
            setTimeout(() => el.classList.remove('stt-copied'), 1000);
        } catch (e) {
            console.warn('Clipboard write failed:', e);
        }
    }

    async _flagDictation(id) {
        try {
            const res = await fetch(`${API}/api/stt/flag/${encodeURIComponent(id)}`, { method: 'POST' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            this._loadHistory();
        } catch (e) {
            this._showError(`Failed to flag: ${e.message}`);
        }
    }

    _startEditDictation(id) {
        const textEl = this.querySelector(`#stt-text-${CSS.escape(id)}`);
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

        const textarea = this.querySelector(`#stt-edit-${CSS.escape(id)}`);
        if (textarea) {
            textarea.focus();
            textarea.setSelectionRange(textarea.value.length, textarea.value.length);
        }
    }

    async _saveCorrection(id) {
        const textarea = this.querySelector(`#stt-edit-${CSS.escape(id)}`);
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
            this._loadHistory();
        } catch (e) {
            this._showError(`Failed to save correction: ${e.message}`);
        }
    }

    // =====================
    // Dictionary tab
    // =====================

    async _loadVocab() {
        const body = this.querySelector('#stt-vocab-body');
        if (!body) return;
        body.innerHTML = '<div class="stt-loading">Loading vocabulary...</div>';

        try {
            const res = await fetch(`${API}/api/stt/vocab`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const terms = data.terms || [];

            const countEl = this.querySelector('#stt-vocab-count');
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

    async _addVocabTerm() {
        const input = this.querySelector('#stt-vocab-input');
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
            this._loadVocab();
        } catch (e) {
            this._showError(`Failed to add term: ${e.message}`);
        }
    }

    async _removeVocabTerm(term) {
        if (!confirm(`Remove "${term}" from dictionary?`)) return;
        try {
            const res = await fetch(`${API}/api/stt/vocab`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ add: [], remove: [term] }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            this._loadVocab();
        } catch (e) {
            this._showError(`Failed to remove term: ${e.message}`);
        }
    }

    // =====================
    // Error display
    // =====================

    _showError(msg) {
        const el = this.querySelector('#stt-error');
        if (el) { el.textContent = msg; el.style.display = 'block'; }
    }

    // =====================
    // Event delegation + panel lifecycle
    // =====================

    _wireEvents() {
        // Data init on open (manual click + auto-restore on reload).
        this.addEventListener('panel:open', () => {
            if (typeof lucide !== 'undefined') lucide.createIcons();
            this._startStatusPolling();
            this._loadHistory();  // History is the default tab — load immediately
        });

        // Cleanup on close
        this.addEventListener('panel:close', () => {
            this._stopStatusPolling();
        });

        // Tab change — load data on tab switch
        this.querySelector('ihim-tabs')?.addEventListener('tab:change', (e) => {
            const tabName = e.detail.tab?.dataset?.tab;
            if (tabName === 'history') this._loadHistory();
            if (tabName === 'dictionary') this._loadVocab();
        });

        // Event delegation for all clicks within the panel
        this.addEventListener('click', (e) => {
            // Titlebar mute toggle
            if (e.target.closest('#stt-mute-toggle')) { this._toggleMute(); return; }
            if (e.target.closest('#stt-unload-btn')) { this._unloadModel(); return; }

            // History actions
            const copyBtn = e.target.closest('.stt-copy-btn');
            if (copyBtn) { this._copyDictation(copyBtn.dataset.id); return; }

            const flagBtn = e.target.closest('.stt-flag-btn');
            if (flagBtn) { this._flagDictation(flagBtn.dataset.id); return; }

            const editBtn = e.target.closest('.stt-edit-btn');
            if (editBtn) { this._startEditDictation(editBtn.dataset.id); return; }

            const saveBtn = e.target.closest('.stt-save-btn');
            if (saveBtn) { this._saveCorrection(saveBtn.dataset.id); return; }

            const cancelBtn = e.target.closest('.stt-cancel-btn');
            if (cancelBtn) { this._loadHistory(); return; }

            // Vocab actions
            const removeBtn = e.target.closest('.stt-vocab-remove');
            if (removeBtn) { this._removeVocabTerm(removeBtn.dataset.term); return; }

            if (e.target.closest('#stt-vocab-add-btn')) { this._addVocabTerm(); return; }
        });

        // Enter key in vocab input
        this.querySelector('#stt-vocab-input')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); this._addVocabTerm(); }
        });
    }
}

customElements.define('ihim-stt', IhimSTT);
