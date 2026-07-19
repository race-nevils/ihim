/**
 * <ihim-recorder> — Meeting Recorder window (record, playback, transcripts).
 * Extends IhimPanel: IS the draggable window; renders its own chrome +
 * content, loads data on its panel:open / panel:close lifecycle.
 */
import { API, escapeHtml } from '../app.js';
import { IhimPanel } from './ihim-panel.js';
import './ihim-tabs.js';

// Transcription stage display names
const STAGE_LABELS = {
    queued: 'Queued...',
    loading_model: 'Loading Whisper model...',
    transcribing_mic: 'Transcribing mic channel...',
    transcribing_sys: 'Transcribing system audio...',
    merging: 'Merging channels...',
};

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function formatSegmentTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
}

class IhimRecorder extends IhimPanel {
    _devicesData = null;
    _selectedRecordingId = null;
    _pollInterval = null;
    _elapsedTimer = null;
    _recordingStartedAt = null;
    _previousStatus = null;
    _transcriptionPollInterval = null;

    connectedCallback() {
        this.innerHTML = `
            <ihim-tabs>
            <!-- Tabs -->
            <div class="recorder-tabs" id="recorder-tablist" role="tablist" aria-label="Meeting Recorder">
                <button class="recorder-tab-btn active" data-tab="record" role="tab" id="recorder-tab-record-btn" aria-selected="true" aria-controls="recorder-tab-record" tabindex="0">Record</button>
                <button class="recorder-tab-btn" data-tab="history" role="tab" id="recorder-tab-history-btn" aria-selected="false" aria-controls="recorder-tab-history" tabindex="-1">History</button>
            </div>

            <!-- Record Tab -->
            <div id="recorder-tab-record" class="recorder-tab-content active" role="tabpanel" aria-labelledby="recorder-tab-record-btn">
                <div class="recorder-body" id="recorder-record-body">
                    <div class="recorder-device-row">
                        <label for="recorder-mic-select">Microphone</label>
                        <select id="recorder-mic-select"><option value="">Loading devices...</option></select>
                    </div>
                    <div class="recorder-device-row">
                        <label for="recorder-sys-select">System Audio</label>
                        <select id="recorder-sys-select"><option value="">Loading devices...</option></select>
                    </div>
                    <div class="recorder-device-row">
                        <label for="recorder-label-input">Label</label>
                        <input type="text" id="recorder-label-input" placeholder="e.g. Weekly standup" maxlength="120" />
                    </div>
                    <div class="recorder-device-row">
                        <label for="recorder-participant-input">Participant</label>
                        <input type="text" id="recorder-participant-input" placeholder="e.g. Sarah" maxlength="120" />
                    </div>

                    <div class="recorder-live-status" id="recorder-live-status" style="display: none;">
                        <div class="recorder-elapsed" id="recorder-elapsed">00:00</div>
                    </div>

                    <div class="recorder-controls">
                        <button class="recorder-btn recorder-start-btn" id="recorder-start-btn">Start Recording</button>
                        <button class="recorder-btn recorder-stop-btn" id="recorder-stop-btn" disabled>Stop</button>
                        <button class="recorder-btn recorder-reset-btn" id="recorder-reset-btn" style="display: none;">Reset</button>
                    </div>

                    <div class="recorder-error" id="recorder-error" role="alert" aria-live="assertive" style="display: none;"></div>
                </div>
            </div>

            <!-- History Tab — master-detail -->
            <div id="recorder-tab-history" class="recorder-tab-content" role="tabpanel" aria-labelledby="recorder-tab-history-btn">
                <!-- LIST VIEW (default) -->
                <div id="recorder-history-list">
                    <div class="recorder-list-header">
                        <span class="recorder-list-count" id="recorder-list-count">0 recordings</span>
                        <button class="recorder-btn recorder-refresh-btn" id="recorder-refresh-btn">Refresh</button>
                    </div>
                    <div class="recorder-body recorder-list-body" id="recorder-recordings-body">
                        <div class="recorder-loading">Loading recordings...</div>
                    </div>
                </div>
                <!-- DETAIL VIEW (hidden until recording clicked) -->
                <div id="recorder-history-detail" style="display: none;">
                    <div class="recorder-transcript-toolbar" id="recorder-transcript-toolbar">
                        <button class="recorder-btn recorder-back-btn" id="recorder-back-btn">&larr; Back</button>
                        <span class="recorder-transcript-meta" id="recorder-transcript-meta"></span>
                        <button class="recorder-btn recorder-transcribe-btn" id="recorder-transcribe-btn" style="display: none;">Transcribe</button>
                        <button class="recorder-btn recorder-delete-btn" id="recorder-delete-btn">Delete</button>
                    </div>
                    <div class="recorder-body recorder-transcript-body" id="recorder-transcript-body"></div>
                </div>
            </div>
            </ihim-tabs>
        `;
        this._wireEvents();
        super.connectedCallback();
    }

    disconnectedCallback() {
        this._stopStatusPolling();
        this._clearElapsedTimer();
        this._stopTranscriptionPolling();
    }

    _el(id) { return this.querySelector(`#${id}`); }

    // =====================
    // Devices
    // =====================

    async _loadDevices() {
        const micSelect = this._el('recorder-mic-select');
        const sysSelect = this._el('recorder-sys-select');
        try {
            const res = await fetch(`${API}/api/recorder/devices`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            this._devicesData = data;

            micSelect.innerHTML = data.mic_devices.map(d =>
                `<option value="${d.index}">${escapeHtml(d.name)}</option>`
            ).join('') || '<option value="">No microphones found</option>';

            sysSelect.innerHTML = data.system_devices.map(d =>
                `<option value="${d.index}">${escapeHtml(d.name)}</option>`
            ).join('') || '<option value="">No system audio found</option>';

            // Restore saved device preferences (server-side, survives cache clear)
            await this._restoreDevicePreferences(data);

            // Persist on change
            micSelect.addEventListener('change', () => this._saveDevicePreferences());
            sysSelect.addEventListener('change', () => this._saveDevicePreferences());
            this._el('recorder-participant-input').addEventListener('change', () => this._saveDevicePreferences());
        } catch (e) {
            micSelect.innerHTML = '<option value="">Failed to load</option>';
            sysSelect.innerHTML = '<option value="">Failed to load</option>';
            this._showError(`Failed to load devices: ${e.message}`);
        }
    }

    async _restoreDevicePreferences(devices) {
        try {
            const res = await fetch(`${API}/api/preferences`);
            if (!res.ok) return;
            const prefs = await res.json();
            const saved = prefs.recorder || {};

            if (saved.mic_device) {
                const match = devices.mic_devices.find(d => d.name === saved.mic_device);
                if (match) this._el('recorder-mic-select').value = String(match.index);
            }
            if (saved.sys_device) {
                const match = devices.system_devices.find(d => d.name === saved.sys_device);
                if (match) this._el('recorder-sys-select').value = String(match.index);
            }
            if (saved.participant_name) {
                this._el('recorder-participant-input').value = saved.participant_name;
            }
            // Fallback: auto-select first system audio device if nothing selected
            const sysSelect = this._el('recorder-sys-select');
            if (!sysSelect.value && devices.system_devices.length > 0) {
                sysSelect.value = String(devices.system_devices[0].index);
            }
        } catch (e) {
            console.warn('Failed to restore device preferences:', e);
        }
    }

    async _saveDevicePreferences() {
        if (!this._devicesData) return;
        const micIdx = parseInt(this._el('recorder-mic-select').value, 10);
        const sysIdx = parseInt(this._el('recorder-sys-select').value, 10);

        const micDev = this._devicesData.mic_devices.find(d => d.index === micIdx);
        const sysDev = this._devicesData.system_devices.find(d => d.index === sysIdx);

        try {
            await fetch(`${API}/api/preferences`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    recorder: {
                        mic_device: micDev ? micDev.name : null,
                        sys_device: sysDev ? sysDev.name : null,
                        participant_name: this._el('recorder-participant-input').value.trim() || null
                    }
                })
            });
        } catch (e) {
            console.warn('Failed to save device preferences:', e);
        }
    }

    // =====================
    // Recording controls
    // =====================

    async _startRecording() {
        const startBtn = this._el('recorder-start-btn');
        const stopBtn = this._el('recorder-stop-btn');
        const label = this._el('recorder-label-input').value.trim();
        const micIdx = this._el('recorder-mic-select').value;
        const sysIdx = this._el('recorder-sys-select').value;

        startBtn.disabled = true;
        this._hideError();

        const participant = this._el('recorder-participant-input').value.trim();

        const body = {};
        if (label) body.label = label;
        if (participant) body.participant_name = participant;
        if (micIdx !== '') body.mic_device_index = parseInt(micIdx, 10);
        if (sysIdx !== '') body.sys_device_index = parseInt(sysIdx, 10);

        try {
            const res = await fetch(`${API}/api/recorder/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || err.title || `HTTP ${res.status}`);
            }
            stopBtn.disabled = false;
            this._pollStatus(); // Immediate status poll — timer appears without waiting for next interval
        } catch (e) {
            startBtn.disabled = false;
            this._showError(`Failed to start: ${e.message}`);
        }
    }

    async _stopRecording() {
        const stopBtn = this._el('recorder-stop-btn');
        stopBtn.disabled = true;
        stopBtn.textContent = 'Stopping...';
        this._hideError();

        try {
            const res = await fetch(`${API}/api/recorder/stop`, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || err.title || `HTTP ${res.status}`);
            }
            // Poll will pick up state change and auto-switch to history tab
        } catch (e) {
            stopBtn.disabled = false;
            stopBtn.textContent = 'Stop';
            this._showError(`Failed to stop: ${e.message}`);
        }
    }

    async _resetRecorder() {
        this._hideError();
        try {
            const res = await fetch(`${API}/api/recorder/reset`, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            this._el('recorder-reset-btn').style.display = 'none';
        } catch (e) {
            this._showError(`Failed to reset: ${e.message}`);
        }
    }

    // =====================
    // Status polling
    // =====================

    _startStatusPolling() {
        if (this._pollInterval) return;
        this._pollStatus(); // immediate first call
        this._pollInterval = setInterval(() => this._pollStatus(), 2000);
    }

    _stopStatusPolling() {
        if (this._pollInterval) { clearInterval(this._pollInterval); this._pollInterval = null; }
    }

    async _pollStatus() {
        try {
            const res = await fetch(`${API}/api/recorder/status`);
            if (!res.ok) return;
            const data = await res.json();
            this._renderStatus(data);

            // Auto-switch to history tab when stop completes (recording → idle)
            if (this._previousStatus === 'recording' && data.status === 'idle') {
                const tabs = this.querySelector('ihim-tabs');
                if (tabs) {
                    tabs.activate('history');
                    this._showHistoryList();
                    this._loadRecordings();
                }
            }
            this._previousStatus = data.status;
        } catch (e) { /* silent — polling resilience */ }
    }

    _renderStatus(data) {
        const startBtn = this._el('recorder-start-btn');
        const stopBtn = this._el('recorder-stop-btn');
        const resetBtn = this._el('recorder-reset-btn');
        const liveStatus = this._el('recorder-live-status');

        // Recording indicator lives on the taskbar chip (red outline), driven
        // by this attribute; panel:state tells the taskbar to re-render.
        const isRecording = data.status === 'recording';
        if (isRecording !== this.hasAttribute('recording')) {
            this.toggleAttribute('recording', isRecording);
            this.dispatchEvent(new CustomEvent('panel:state', { bubbles: true }));
        }

        switch (data.status) {
            case 'recording':
                startBtn.disabled = true;
                stopBtn.disabled = false;
                stopBtn.textContent = 'Stop';
                resetBtn.style.display = 'none';
                liveStatus.style.display = 'flex';
                // Start elapsed timer from server's started_at
                if (data.started_at && !this._elapsedTimer) {
                    this._startElapsedTimer(new Date(data.started_at));
                }
                break;
            case 'transcribing':
                startBtn.disabled = true;
                stopBtn.disabled = true;
                stopBtn.textContent = 'Transcribing...';
                resetBtn.style.display = 'none';
                liveStatus.style.display = 'flex';
                this._clearElapsedTimer();
                break;
            case 'error':
                startBtn.disabled = false;
                stopBtn.disabled = true;
                stopBtn.textContent = 'Stop';
                resetBtn.style.display = 'inline-flex';
                liveStatus.style.display = 'none';
                this._clearElapsedTimer();
                if (data.error) this._showError(data.error);
                break;
            default: // idle
                startBtn.disabled = false;
                stopBtn.disabled = true;
                stopBtn.textContent = 'Stop';
                resetBtn.style.display = 'none';
                liveStatus.style.display = 'none';
                this._clearElapsedTimer();
                break;
        }
    }

    // =====================
    // Elapsed timer
    // =====================

    _startElapsedTimer(startedAt) {
        if (this._elapsedTimer) { clearInterval(this._elapsedTimer); this._elapsedTimer = null; }
        this._recordingStartedAt = startedAt;
        this._updateElapsed();
        this._elapsedTimer = setInterval(() => this._updateElapsed(), 1000);
    }

    _clearElapsedTimer() {
        if (this._elapsedTimer) { clearInterval(this._elapsedTimer); this._elapsedTimer = null; }
        this._recordingStartedAt = null;
    }

    _updateElapsed() {
        if (!this._recordingStartedAt) return;
        const diff = Math.floor((Date.now() - this._recordingStartedAt.getTime()) / 1000);
        const mins = String(Math.floor(diff / 60)).padStart(2, '0');
        const secs = String(diff % 60).padStart(2, '0');
        const el = this._el('recorder-elapsed');
        if (el) el.textContent = `${mins}:${secs}`;
    }

    // =====================
    // Recordings list
    // =====================

    async _loadRecordings() {
        const body = this._el('recorder-recordings-body');
        const countEl = this._el('recorder-list-count');
        body.innerHTML = '<div class="recorder-loading">Loading recordings...</div>';
        try {
            const res = await fetch(`${API}/api/recorder/recordings`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            const recordings = data.recordings || [];
            countEl.textContent = `${recordings.length} recording${recordings.length !== 1 ? 's' : ''}`;

            if (recordings.length === 0) {
                body.innerHTML = '<div class="recorder-placeholder">No recordings yet. Start your first recording above.</div>';
                return;
            }

            body.innerHTML = recordings.map(r => {
                const date = new Date(r.started_at);
                const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                const timeStr = date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
                const duration = r.duration_seconds ? formatDuration(r.duration_seconds) : '--:--';
                const label = r.label ? escapeHtml(r.label) : 'Untitled';
                return `<div class="recorder-list-item" data-recording-id="${escapeHtml(r.recording_id)}">
                    <div class="recorder-list-item-main">
                        <span class="recorder-list-item-label">${label}</span>
                        <span class="recorder-list-item-actions">
                            <button class="recorder-list-rename-btn" title="Rename" aria-label="Rename recording">&#9998;</button>
                            <span class="recorder-list-item-duration">${duration}</span>
                        </span>
                    </div>
                    <div class="recorder-list-item-meta">${dateStr} at ${timeStr}</div>
                </div>`;
            }).join('');
        } catch (e) {
            body.innerHTML = `<div class="recorder-error-inline">Failed to load recordings: ${escapeHtml(e.message)}</div>`;
        }
    }

    // =====================
    // History master-detail toggle
    // =====================

    _showHistoryList() {
        this._el('recorder-history-list').style.display = '';
        this._el('recorder-history-detail').style.display = 'none';
        const transcribeBtn = this._el('recorder-transcribe-btn');
        if (transcribeBtn) transcribeBtn.style.display = 'none';
        this._selectedRecordingId = null;
        // Stop transcription progress polling when leaving detail view
        this._stopTranscriptionPolling();
    }

    _showHistoryDetail() {
        this._el('recorder-history-list').style.display = 'none';
        this._el('recorder-history-detail').style.display = '';
    }

    // =====================
    // Transcript view
    // =====================

    async _loadTranscript(id) {
        this._selectedRecordingId = id;
        this._showHistoryDetail();
        const body = this._el('recorder-transcript-body');
        const meta = this._el('recorder-transcript-meta');
        body.innerHTML = '<div class="recorder-loading">Loading transcript...</div>';

        try {
            const res = await fetch(`${API}/api/recorder/recordings/${encodeURIComponent(id)}`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();

            const label = data.label ? escapeHtml(data.label) : 'Untitled';
            const duration = data.duration_seconds ? formatDuration(data.duration_seconds) : '';
            meta.textContent = `${label}${duration ? ` (${duration})` : ''}`;

            const transcribeBtn = this._el('recorder-transcribe-btn');

            // Handle transcription status
            if (data.status === 'pending_transcription') {
                transcribeBtn.style.display = '';
                transcribeBtn.textContent = 'Transcribe';
                transcribeBtn.disabled = false;
                body.innerHTML = '<div class="recorder-placeholder">Recording saved. Click <strong>Transcribe</strong> to process.</div>';
                return;
            }
            if (data.status === 'transcribing') {
                transcribeBtn.style.display = '';
                transcribeBtn.textContent = 'Transcribing...';
                transcribeBtn.disabled = true;
                const stage = data.transcription_stage || 'processing';
                const stageLabel = STAGE_LABELS[stage] || `Processing (${stage})...`;
                body.innerHTML = `<div class="recorder-loading">${escapeHtml(stageLabel)}</div>`;
                // Start polling if not already
                if (!this._transcriptionPollInterval) this._startTranscriptionPolling(id);
                return;
            }
            if (data.status === 'transcription_failed') {
                transcribeBtn.style.display = '';
                transcribeBtn.textContent = 'Retry';
                transcribeBtn.disabled = false;
                const errMsg = data.transcription_error ? escapeHtml(data.transcription_error) : 'Unknown error';
                body.innerHTML = `<div class="recorder-error-inline">Transcription failed: ${errMsg}</div>
                    <div class="recorder-placeholder">Click <strong>Retry</strong> to try again.</div>`;
                return;
            }

            // Complete or other — hide transcribe button, show segments
            transcribeBtn.style.display = 'none';

            if (!data.segments || data.segments.length === 0) {
                body.innerHTML = '<div class="recorder-placeholder">No transcript segments available.</div>';
                return;
            }

            body.innerHTML = data.segments.map(seg => {
                const speaker = escapeHtml(seg.speaker || 'Unknown');
                const speakerClass = speaker.toLowerCase() === 'owner' ? 'speaker-mic' :
                                     speaker.toLowerCase() === 'other' ? 'speaker-other' : 'speaker-default';
                const start = formatSegmentTime(seg.start);
                const end = formatSegmentTime(seg.end);
                return `<div class="recorder-segment">
                    <div class="recorder-segment-header">
                        <span class="recorder-speaker ${speakerClass}">${speaker}</span>
                        <span class="recorder-segment-time">${start} - ${end}</span>
                    </div>
                    <div class="recorder-segment-text">${escapeHtml(seg.text)}</div>
                </div>`;
            }).join('');
        } catch (e) {
            body.innerHTML = `<div class="recorder-error-inline">Failed to load transcript: ${escapeHtml(e.message)}</div>`;
        }
    }

    // =====================
    // Manual transcription
    // =====================

    async _transcribeRecording(id) {
        const transcribeBtn = this._el('recorder-transcribe-btn');
        const body = this._el('recorder-transcript-body');
        transcribeBtn.disabled = true;
        transcribeBtn.textContent = 'Transcribing...';
        body.innerHTML = '<div class="recorder-loading">Starting transcription...</div>';

        try {
            const res = await fetch(`${API}/api/recorder/transcribe/${encodeURIComponent(id)}`, { method: 'POST' });
            if (!res.ok && res.status !== 202) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || err.title || `HTTP ${res.status}`);
            }
            // Start polling for transcription progress
            this._startTranscriptionPolling(id);
        } catch (e) {
            transcribeBtn.disabled = false;
            transcribeBtn.textContent = 'Retry';
            body.innerHTML = `<div class="recorder-error-inline">Transcription failed: ${escapeHtml(e.message)}</div>
                <div class="recorder-placeholder">Click <strong>Retry</strong> to try again.</div>`;
        }
    }

    _startTranscriptionPolling(id) {
        this._stopTranscriptionPolling();
        const startTime = Date.now();

        this._transcriptionPollInterval = setInterval(async () => {
            try {
                const res = await fetch(`${API}/api/recorder/recordings/${encodeURIComponent(id)}`);
                if (!res.ok) return;
                const data = await res.json();

                const body = this._el('recorder-transcript-body');
                const elapsed = Math.floor((Date.now() - startTime) / 1000);
                const elapsedStr = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;

                if (data.status === 'transcribing') {
                    const stage = data.transcription_stage || 'processing';
                    const stageLabel = STAGE_LABELS[stage] || `Processing (${stage})...`;
                    body.innerHTML = `<div class="recorder-loading">
                        <div>${escapeHtml(stageLabel)}</div>
                        <div class="recorder-elapsed-hint">Elapsed: ${elapsedStr}</div>
                    </div>`;
                } else if (data.status === 'complete' || data.status === 'no_transcript') {
                    // Done — reload full transcript view
                    this._stopTranscriptionPolling();
                    await this._loadTranscript(id);
                } else if (data.status === 'transcription_failed') {
                    this._stopTranscriptionPolling();
                    const transcribeBtn = this._el('recorder-transcribe-btn');
                    transcribeBtn.disabled = false;
                    transcribeBtn.textContent = 'Retry';
                    transcribeBtn.style.display = '';
                    const errMsg = data.transcription_error ? escapeHtml(data.transcription_error) : 'Unknown error';
                    body.innerHTML = `<div class="recorder-error-inline">Transcription failed: ${errMsg}</div>
                        <div class="recorder-placeholder">Click <strong>Retry</strong> to try again.</div>`;
                }
            } catch (e) { /* polling resilience */ }
        }, 2000);
    }

    _stopTranscriptionPolling() {
        if (this._transcriptionPollInterval) {
            clearInterval(this._transcriptionPollInterval);
            this._transcriptionPollInterval = null;
        }
    }

    // =====================
    // Rename recording
    // =====================

    _startInlineRename(item) {
        const labelEl = item.querySelector('.recorder-list-item-label');
        if (!labelEl || item.querySelector('.recorder-rename-input')) return;
        const id = item.dataset.recordingId;
        const current = labelEl.textContent === 'Untitled' ? '' : labelEl.textContent;

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'recorder-rename-input';
        input.maxLength = 120;
        input.value = current;
        input.placeholder = 'Untitled';
        labelEl.replaceWith(input);
        input.focus();
        input.select();

        let done = false;
        const finish = async (save) => {
            if (done) return;
            done = true;
            const value = input.value.trim();
            if (save && value !== current) {
                try {
                    const res = await fetch(`${API}/api/recorder/recordings/${encodeURIComponent(id)}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ label: value || null })
                    });
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    labelEl.textContent = value || 'Untitled';
                } catch (e) {
                    console.warn('Rename failed:', e);
                }
            }
            input.replaceWith(labelEl);
        };
        input.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter') finish(true);
            else if (ev.key === 'Escape') finish(false);
        });
        input.addEventListener('blur', () => finish(true));
    }

    // =====================
    // Delete recording
    // =====================

    async _deleteRecording(id) {
        if (!confirm('Delete this recording? This removes the audio files, transcript, and brain entry.')) return;
        try {
            const res = await fetch(`${API}/api/recorder/recordings/${encodeURIComponent(id)}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            this._showHistoryList();
            this._loadRecordings();
        } catch (e) {
            this._showError(`Failed to delete: ${e.message}`);
        }
    }

    // =====================
    // Error display
    // =====================

    _showError(msg) {
        const el = this._el('recorder-error');
        if (el) { el.textContent = msg; el.style.display = 'block'; }
    }

    _hideError() {
        const el = this._el('recorder-error');
        if (el) el.style.display = 'none';
    }

    // =====================
    // Event delegation + panel lifecycle
    // =====================

    _wireEvents() {
        // Data init on open (manual click + auto-restore on reload).
        this.addEventListener('panel:open', async () => {
            if (typeof lucide !== 'undefined') lucide.createIcons();
            if (!this._devicesData) await this._loadDevices();
            this._startStatusPolling();
        });

        // Cleanup on close (Escape key, close button)
        this.addEventListener('panel:close', () => {
            this._stopStatusPolling();
            this._clearElapsedTimer();
        });

        // Tab change — load recordings when switching to that tab
        this.querySelector('ihim-tabs')?.addEventListener('tab:change', (e) => {
            const tabName = e.detail.tab?.dataset?.tab;
            if (tabName === 'history') {
                this._showHistoryList();
                this._loadRecordings();
            }
        });

        this.addEventListener('click', (e) => {
            // Start button
            if (e.target.closest('#recorder-start-btn')) { this._startRecording(); return; }
            // Stop button
            if (e.target.closest('#recorder-stop-btn')) { this._stopRecording(); return; }
            // Reset button
            if (e.target.closest('#recorder-reset-btn')) { this._resetRecorder(); return; }
            // Refresh recordings
            if (e.target.closest('#recorder-refresh-btn')) { this._loadRecordings(); return; }
            // Back from transcript
            if (e.target.closest('#recorder-back-btn')) {
                this._showHistoryList();
                this._loadRecordings();
                return;
            }
            // Transcribe recording
            if (e.target.closest('#recorder-transcribe-btn') && this._selectedRecordingId) {
                this._transcribeRecording(this._selectedRecordingId); return;
            }
            // Delete recording
            if (e.target.closest('#recorder-delete-btn') && this._selectedRecordingId) {
                this._deleteRecording(this._selectedRecordingId); return;
            }
            // Rename button — inline edit, never opens the transcript
            const renameBtn = e.target.closest('.recorder-list-rename-btn');
            if (renameBtn) {
                const item = renameBtn.closest('.recorder-list-item');
                if (item) this._startInlineRename(item);
                return;
            }
            // Clicks inside an active rename input stay in the input
            if (e.target.closest('.recorder-rename-input')) return;
            // Recording list item click
            const listItem = e.target.closest('.recorder-list-item');
            if (listItem) {
                const id = listItem.dataset.recordingId;
                if (id) this._loadTranscript(id);
            }
        });
    }
}

customElements.define('ihim-recorder', IhimRecorder);
