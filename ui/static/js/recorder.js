/**
 * recorder.js — Meeting recorder dashboard (record, playback, transcripts)
 */
import { API, escapeHtml } from './app.js';
import { makeDraggable } from './draggable.js';
import { initAccessibleTabs } from './a11y.js';

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

    let posRestored = false;
    try {
        const saved = localStorage.getItem('recorderWindowPosition');
        if (saved) {
            const { x, y } = JSON.parse(saved);
            if (x >= 0 && y >= 0 && x < window.innerWidth - 50 && y < window.innerHeight - 50) {
                win.style.left = x + 'px'; win.style.top = y + 'px'; posRestored = true;
            }
        }
    } catch (e) { console.warn('Failed to restore recorder position:', e); }
    if (!posRestored) {
        win.style.left = Math.max(0, (window.innerWidth - 680) / 2) + 'px';
        win.style.top = Math.max(0, (window.innerHeight - 550) / 2) + 'px';
    }

    win.style.display = 'flex';
    if (!win.dataset.dragInitialized) {
        makeDraggable('recorder-window', '.recorder-drag-handle', 'recorderWindowPosition');
        win.dataset.dragInitialized = 'true';
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
    if (!devicesData) await loadDevices();
    startStatusPolling();
}

export function closeRecorderWindow() {
    const win = document.getElementById('recorder-window');
    if (win) win.style.display = 'none';
    stopStatusPolling();
    clearElapsedTimer();
}

// =====================
// Tabs
// =====================

export function switchRecorderTab(tab) {
    document.querySelectorAll('.recorder-tab-btn').forEach(btn => {
        const isTarget = btn.dataset.tab === tab;
        btn.classList.toggle('active', isTarget);
        btn.setAttribute('aria-selected', isTarget ? 'true' : 'false');
        btn.setAttribute('tabindex', isTarget ? '0' : '-1');
    });
    document.querySelectorAll('.recorder-tab-content').forEach(content => {
        content.style.display = content.id === `recorder-tab-${tab}` ? 'block' : 'none';
    });
    if (tab === 'recordings') loadRecordings();
}

// =====================
// Devices
// =====================

async function loadDevices() {
    const micSelect = document.getElementById('recorder-mic-select');
    const sysSelect = document.getElementById('recorder-sys-select');
    try {
        const res = await fetch(`${API}/api/recorder/devices`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        devicesData = data;

        micSelect.innerHTML = data.mic_devices.map(d =>
            `<option value="${d.index}">${escapeHtml(d.name)}</option>`
        ).join('') || '<option value="">No microphones found</option>';

        sysSelect.innerHTML = data.system_devices.map(d =>
            `<option value="${d.index}">${escapeHtml(d.name)}</option>`
        ).join('') || '<option value="">No system audio found</option>';
    } catch (e) {
        micSelect.innerHTML = '<option value="">Failed to load</option>';
        sysSelect.innerHTML = '<option value="">Failed to load</option>';
        showRecorderError(`Failed to load devices: ${e.message}`);
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

    const body = {};
    if (label) body.label = label;
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
        // Poll will pick up state change and auto-switch to recordings tab
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
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
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

        // Auto-switch to recordings tab when transcription completes
        if (previousStatus === 'transcribing' && data.status === 'idle') {
            switchRecorderTab('recordings');
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
                recordingStartedAt = new Date(data.started_at);
                startElapsedTimer();
            }
            break;
        case 'transcribing':
            badge.textContent = 'PROCESSING';
            badge.classList.add('status-transcribing');
            startBtn.disabled = true;
            stopBtn.disabled = true;
            stopBtn.textContent = 'Stopping...';
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

function startElapsedTimer() {
    clearElapsedTimer();
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
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
// Transcript view
// =====================

async function loadTranscript(id) {
    selectedRecordingId = id;
    switchRecorderTab('transcript');
    const body = document.getElementById('recorder-transcript-body');
    const toolbar = document.getElementById('recorder-transcript-toolbar');
    const meta = document.getElementById('recorder-transcript-meta');
    body.innerHTML = '<div class="recorder-loading">Loading transcript...</div>';
    toolbar.style.display = 'flex';

    try {
        const res = await fetch(`${API}/api/recorder/recordings/${encodeURIComponent(id)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const label = data.label ? escapeHtml(data.label) : 'Untitled';
        const duration = data.duration_seconds ? formatDuration(data.duration_seconds) : '';
        meta.textContent = `${label}${duration ? ` (${duration})` : ''}`;

        if (!data.segments || data.segments.length === 0) {
            body.innerHTML = '<div class="recorder-placeholder">No transcript segments available.</div>';
            return;
        }

        const speakerMap = data.speakers || {};
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
// Delete recording
// =====================

async function deleteRecording(id) {
    if (!confirm('Delete this recording? This removes the audio files, transcript, and brain entry.')) return;
    try {
        const res = await fetch(`${API}/api/recorder/recordings/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        selectedRecordingId = null;
        document.getElementById('recorder-transcript-toolbar').style.display = 'none';
        document.getElementById('recorder-transcript-body').innerHTML =
            '<div class="recorder-placeholder">Select a recording to view its transcript.</div>';
        switchRecorderTab('recordings');
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

    const tablist = document.getElementById('recorder-tablist');
    if (tablist) {
        initAccessibleTabs(tablist, {
            tabSelector: '[role="tab"]',
            onActivate(tab) { switchRecorderTab(tab.dataset.tab); }
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
        if (e.target.closest('#recorder-back-btn')) { switchRecorderTab('recordings'); return; }
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
