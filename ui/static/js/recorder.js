/**
 * recorder.js — Meeting recorder dashboard (record, playback, transcripts)
 * Uses <ihim-panel> for window lifecycle and <ihim-tabs> for tab management.
 */
import { API, escapeHtml } from './app.js';

let devicesData = null;
let selectedRecordingId = null;
let pollInterval = null;
let elapsedTimer = null;
let recordingStartedAt = null;

// =====================
// Window lifecycle
// =====================

export async function openRecorderWindow() {
    const win = document.getElementById('recorder-window');
    if (!win) return;
    win.open();
    if (typeof lucide !== 'undefined') lucide.createIcons();
    if (!devicesData) await loadDevices();
    startStatusPolling();
}

export function closeRecorderWindow() {
    const win = document.getElementById('recorder-window');
    if (win) win.close();
    stopStatusPolling();
    clearElapsedTimer();
}

export function toggleRecorderWindow() {
    const win = document.getElementById('recorder-window');
    if (!win) return;
    if (win.hasAttribute('open')) closeRecorderWindow();
    else openRecorderWindow();
}

// =====================
// Devices
// =====================

async function loadDevices() {
    const micSelect = document.getElementById('recorder-mic-select');
    const sysSelect = document.getElementById('recorder-sys-select');
    try {
        const res = await fetch(`${API}/api/recorder/devices`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        devicesData = data;

        micSelect.innerHTML = data.mic_devices.map(d =>
            `<option value="${d.index}">${escapeHtml(d.name)}</option>`
        ).join('') || '<option value="">No microphones found</option>';

        sysSelect.innerHTML = data.system_devices.map(d =>
            `<option value="${d.index}">${escapeHtml(d.name)}</option>`
        ).join('') || '<option value="">No system audio found</option>';

        // Restore saved device preferences (server-side, survives cache clear)
        await restoreDevicePreferences(data);

        // Persist on change
        micSelect.addEventListener('change', saveDevicePreferences);
        sysSelect.addEventListener('change', saveDevicePreferences);
        document.getElementById('recorder-participant-input').addEventListener('change', saveDevicePreferences);
    } catch (e) {
        micSelect.innerHTML = '<option value="">Failed to load</option>';
        sysSelect.innerHTML = '<option value="">Failed to load</option>';
        showRecorderError(`Failed to load devices: ${e.message}`);
    }
}

async function restoreDevicePreferences(devices) {
    try {
        const res = await fetch(`${API}/api/preferences`);
        if (!res.ok) return;
        const prefs = await res.json();
        const saved = prefs.recorder || {};

        if (saved.mic_device) {
            const match = devices.mic_devices.find(d => d.name === saved.mic_device);
            if (match) document.getElementById('recorder-mic-select').value = String(match.index);
        }
        if (saved.sys_device) {
            const match = devices.system_devices.find(d => d.name === saved.sys_device);
            if (match) document.getElementById('recorder-sys-select').value = String(match.index);
        }
        if (saved.participant_name) {
            document.getElementById('recorder-participant-input').value = saved.participant_name;
        }
        // Fallback: auto-select first system audio device if nothing selected
        const sysSelect = document.getElementById('recorder-sys-select');
        if (!sysSelect.value && devices.system_devices.length > 0) {
            sysSelect.value = String(devices.system_devices[0].index);
        }
    } catch (e) {
        console.warn('Failed to restore device preferences:', e);
    }
}

async function saveDevicePreferences() {
    if (!devicesData) return;
    const micSelect = document.getElementById('recorder-mic-select');
    const sysSelect = document.getElementById('recorder-sys-select');
    const micIdx = parseInt(micSelect.value, 10);
    const sysIdx = parseInt(sysSelect.value, 10);

    const micDev = devicesData.mic_devices.find(d => d.index === micIdx);
    const sysDev = devicesData.system_devices.find(d => d.index === sysIdx);

    try {
        await fetch(`${API}/api/preferences`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                recorder: {
                    mic_device: micDev ? micDev.name : null,
                    sys_device: sysDev ? sysDev.name : null,
                    participant_name: document.getElementById('recorder-participant-input').value.trim() || null
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

async function startRecording() {
    const startBtn = document.getElementById('recorder-start-btn');
    const stopBtn = document.getElementById('recorder-stop-btn');
    const label = document.getElementById('recorder-label-input').value.trim();
    const micIdx = document.getElementById('recorder-mic-select').value;
    const sysIdx = document.getElementById('recorder-sys-select').value;

    startBtn.disabled = true;
    hideRecorderError();

    const participant = document.getElementById('recorder-participant-input').value.trim();

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
        pollStatus(); // Immediate status poll — timer appears without waiting for next interval
    } catch (e) {
        startBtn.disabled = false;
        showRecorderError(`Failed to start: ${e.message}`);
    }
}

async function stopRecording() {
    const stopBtn = document.getElementById('recorder-stop-btn');
    stopBtn.disabled = true;
    stopBtn.textContent = 'Stopping...';
    hideRecorderError();

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
        showRecorderError(`Failed to stop: ${e.message}`);
    }
}

async function resetRecorder() {
    hideRecorderError();
    try {
        const res = await fetch(`${API}/api/recorder/reset`, { method: 'POST' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        document.getElementById('recorder-reset-btn').style.display = 'none';
    } catch (e) {
        showRecorderError(`Failed to reset: ${e.message}`);
    }
}

// =====================
// Status polling
// =====================

function startStatusPolling() {
    if (pollInterval) return;
    pollStatus(); // immediate first call
    pollInterval = setInterval(pollStatus, 2000);
}

function stopStatusPolling() {
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

let previousStatus = null;

async function pollStatus() {
    try {
        const res = await fetch(`${API}/api/recorder/status`);
        if (!res.ok) return;
        const data = await res.json();
        renderStatus(data);

        // Auto-switch to history tab when stop completes (recording → idle)
        if (previousStatus === 'recording' && data.status === 'idle') {
            const tabs = document.querySelector('#recorder-window ihim-tabs');
            if (tabs) {
                tabs.activate('history');
                showHistoryList();
                loadRecordings();
            }
        }
        previousStatus = data.status;
    } catch (e) { /* silent — polling resilience */ }
}

function renderStatus(data) {
    const badge = document.getElementById('recorder-status-badge');
    const startBtn = document.getElementById('recorder-start-btn');
    const stopBtn = document.getElementById('recorder-stop-btn');
    const resetBtn = document.getElementById('recorder-reset-btn');
    const liveStatus = document.getElementById('recorder-live-status');
    const liveDevices = document.getElementById('recorder-live-devices');

    // Badge
    badge.classList.remove('status-idle', 'status-recording', 'status-transcribing', 'status-error');
    switch (data.status) {
        case 'recording':
            badge.textContent = 'REC';
            badge.classList.add('status-recording');
            startBtn.disabled = true;
            stopBtn.disabled = false;
            stopBtn.textContent = 'Stop';
            resetBtn.style.display = 'none';
            liveStatus.style.display = 'flex';
            if (data.mic_device || data.sys_device) {
                const parts = [];
                if (data.mic_device) parts.push(`Mic: ${escapeHtml(data.mic_device)}`);
                if (data.sys_device) parts.push(`Sys: ${escapeHtml(data.sys_device)}`);
                liveDevices.innerHTML = parts.join(' &middot; ');
            }
            // Start elapsed timer from server's started_at
            if (data.started_at && !elapsedTimer) {
                startElapsedTimer(new Date(data.started_at));
            }
            break;
        case 'transcribing':
            badge.textContent = 'PROCESSING';
            badge.classList.add('status-transcribing');
            startBtn.disabled = true;
            stopBtn.disabled = true;
            stopBtn.textContent = 'Transcribing...';
            resetBtn.style.display = 'none';
            liveStatus.style.display = 'flex';
            clearElapsedTimer();
            break;
        case 'error':
            badge.textContent = 'ERROR';
            badge.classList.add('status-error');
            startBtn.disabled = false;
            stopBtn.disabled = true;
            stopBtn.textContent = 'Stop';
            resetBtn.style.display = 'inline-flex';
            liveStatus.style.display = 'none';
            clearElapsedTimer();
            if (data.error) showRecorderError(data.error);
            break;
        default: // idle
            badge.textContent = 'IDLE';
            badge.classList.add('status-idle');
            startBtn.disabled = false;
            stopBtn.disabled = true;
            stopBtn.textContent = 'Stop';
            resetBtn.style.display = 'none';
            liveStatus.style.display = 'none';
            clearElapsedTimer();
            break;
    }
}

// =====================
// Elapsed timer
// =====================

function startElapsedTimer(startedAt) {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
    recordingStartedAt = startedAt;
    updateElapsed();
    elapsedTimer = setInterval(updateElapsed, 1000);
}

function clearElapsedTimer() {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
    recordingStartedAt = null;
}

function updateElapsed() {
    if (!recordingStartedAt) return;
    const diff = Math.floor((Date.now() - recordingStartedAt.getTime()) / 1000);
    const mins = String(Math.floor(diff / 60)).padStart(2, '0');
    const secs = String(diff % 60).padStart(2, '0');
    const el = document.getElementById('recorder-elapsed');
    if (el) el.textContent = `${mins}:${secs}`;
}

// =====================
// Recordings list
// =====================

async function loadRecordings() {
    const body = document.getElementById('recorder-recordings-body');
    const countEl = document.getElementById('recorder-list-count');
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
                    <span class="recorder-list-item-duration">${duration}</span>
                </div>
                <div class="recorder-list-item-meta">${dateStr} at ${timeStr}</div>
            </div>`;
        }).join('');
    } catch (e) {
        body.innerHTML = `<div class="recorder-error-inline">Failed to load recordings: ${escapeHtml(e.message)}</div>`;
    }
}

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// =====================
// History master-detail toggle
// =====================

function showHistoryList() {
    document.getElementById('recorder-history-list').style.display = '';
    document.getElementById('recorder-history-detail').style.display = 'none';
    const transcribeBtn = document.getElementById('recorder-transcribe-btn');
    if (transcribeBtn) transcribeBtn.style.display = 'none';
    selectedRecordingId = null;
}

function showHistoryDetail() {
    document.getElementById('recorder-history-list').style.display = 'none';
    document.getElementById('recorder-history-detail').style.display = '';
}

// =====================
// Transcript view
// =====================

async function loadTranscript(id) {
    selectedRecordingId = id;
    showHistoryDetail();
    const body = document.getElementById('recorder-transcript-body');
    const meta = document.getElementById('recorder-transcript-meta');
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

        const transcribeBtn = document.getElementById('recorder-transcribe-btn');

        // Handle transcription status
        if (data.status === 'pending_transcription') {
            transcribeBtn.style.display = '';
            transcribeBtn.textContent = 'Transcribe';
            transcribeBtn.disabled = false;
            body.innerHTML = '<div class="recorder-placeholder">Recording saved. Click <strong>Transcribe</strong> to process.</div>';
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
            const start = formatTimestamp(seg.start);
            const end = formatTimestamp(seg.end);
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

function formatTimestamp(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
}

// =====================
// Manual transcription
// =====================

async function transcribeRecording(id) {
    const transcribeBtn = document.getElementById('recorder-transcribe-btn');
    const body = document.getElementById('recorder-transcript-body');
    transcribeBtn.disabled = true;
    transcribeBtn.textContent = 'Transcribing...';
    body.innerHTML = '<div class="recorder-loading">Transcribing... This may take a minute or two.</div>';

    try {
        const res = await fetch(`${API}/api/recorder/transcribe/${encodeURIComponent(id)}`, { method: 'POST' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.title || `HTTP ${res.status}`);
        }
        // Reload the full detail view to show segments
        await loadTranscript(id);
    } catch (e) {
        transcribeBtn.disabled = false;
        transcribeBtn.textContent = 'Retry';
        body.innerHTML = `<div class="recorder-error-inline">Transcription failed: ${escapeHtml(e.message)}</div>
            <div class="recorder-placeholder">Click <strong>Retry</strong> to try again.</div>`;
    }
}

// =====================
// Delete recording
// =====================

async function deleteRecording(id) {
    if (!confirm('Delete this recording? This removes the audio files, transcript, and brain entry.')) return;
    try {
        const res = await fetch(`${API}/api/recorder/recordings/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        showHistoryList();
        loadRecordings();
    } catch (e) {
        showRecorderError(`Failed to delete: ${e.message}`);
    }
}

// =====================
// Error display
// =====================

function showRecorderError(msg) {
    const el = document.getElementById('recorder-error');
    if (el) { el.textContent = msg; el.style.display = 'block'; }
}

function hideRecorderError() {
    const el = document.getElementById('recorder-error');
    if (el) el.style.display = 'none';
}

// =====================
// Event delegation + init
// =====================

export function initRecorderEvents() {
    const win = document.getElementById('recorder-window');
    if (!win) return;

    // Cleanup on panel close (Escape key, close button)
    win.addEventListener('panel:close', () => {
        stopStatusPolling();
        clearElapsedTimer();
    });

    // Tab change — load recordings when switching to that tab
    const tabs = win.querySelector('ihim-tabs');
    if (tabs) {
        tabs.addEventListener('tab:change', (e) => {
            const tabName = e.detail.tab?.dataset?.tab;
            if (tabName === 'history') {
                showHistoryList();
                loadRecordings();
            }
        });
    }

    win.addEventListener('click', (e) => {
        // Start button
        if (e.target.closest('#recorder-start-btn')) { startRecording(); return; }
        // Stop button
        if (e.target.closest('#recorder-stop-btn')) { stopRecording(); return; }
        // Reset button
        if (e.target.closest('#recorder-reset-btn')) { resetRecorder(); return; }
        // Refresh recordings
        if (e.target.closest('#recorder-refresh-btn')) { loadRecordings(); return; }
        // Back from transcript
        if (e.target.closest('#recorder-back-btn')) {
            showHistoryList();
            loadRecordings();
            return;
        }
        // Transcribe recording
        if (e.target.closest('#recorder-transcribe-btn') && selectedRecordingId) {
            transcribeRecording(selectedRecordingId); return;
        }
        // Delete recording
        if (e.target.closest('#recorder-delete-btn') && selectedRecordingId) {
            deleteRecording(selectedRecordingId); return;
        }
        // Recording list item click
        const listItem = e.target.closest('.recorder-list-item');
        if (listItem) {
            const id = listItem.dataset.recordingId;
            if (id) loadTranscript(id);
        }
    });
}
