/**
 * <ihim-yt> — YT Transcriber window: paste a URL, watch it transcribe live.
 * Extends IhimPanel: IS the draggable window; renders its own content,
 * loads jobs on panel:open, streams the active job over SSE.
 *
 * Backed by /api/yt (worker subprocess on the server does yt-dlp + GPU
 * whisper; dictation always preempts the GPU — the widget just shows the
 * "paused for dictation" state when that happens). Segments arrive as SSE
 * `segment` events and append to the log pane in real time, terminal-style.
 * Final transcripts land in workspace/yt-transcriptions/ as .txt.
 */
import { API, escapeHtml } from '../app.js';
import { IhimPanel } from './ihim-panel.js';

const STATUS_LABELS = {
    queued: 'Queued',
    starting: 'Starting…',
    fetching_metadata: 'Fetching video info…',
    downloading: 'Downloading audio…',
    waiting_for_gpu: 'Waiting for dictation to finish…',
    transcribing: 'Transcribing',
    paused_for_dictation: 'Paused — dictation in progress',
    complete: 'Complete',
    duplicate: 'Already transcribed',
    failed: 'Failed',
};
const TERMINAL = new Set(['complete', 'duplicate', 'failed']);
const ACTIVE = new Set([
    'starting', 'fetching_metadata', 'downloading',
    'waiting_for_gpu', 'transcribing', 'paused_for_dictation',
]);

const fmtTs = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

class IhimYt extends IhimPanel {
    _jobs = [];
    _es = null;          // EventSource for the streaming job
    _streamJobId = null;
    _logJobId = null;    // which job the log pane currently shows

    connectedCallback() {
        this.innerHTML = `
            <div class="yt-submit-row">
                <input type="text" id="yt-url" placeholder="Paste a YouTube URL…"
                       maxlength="2000" aria-label="Video URL" />
                <button type="button" id="yt-submit-btn">Transcribe</button>
            </div>
            <div class="yt-status-row" id="yt-status-row" hidden>
                <span class="yt-status-label" id="yt-status-label"></span>
                <span class="yt-progress" id="yt-progress"></span>
                <button type="button" class="yt-cancel-btn" id="yt-cancel-btn"
                        aria-label="Cancel transcription">Cancel</button>
            </div>
            <div class="yt-log" id="yt-log" aria-live="polite"></div>
            <div class="yt-history" id="yt-history"></div>
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
            const res = await fetch(`${API}/api/yt/jobs`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this._jobs = data.jobs || [];
            this._renderHistory();
            const active = this._jobs.find(j => ACTIVE.has(j.status) || j.status === 'queued');
            this._syncBusy(!!active);
            const running = this._jobs.find(j => ACTIVE.has(j.status));
            if (running) this._openStream(running.job_id);
            else this._renderStatus(active || null);
        } catch (e) {
            this._el('yt-history').innerHTML =
                `<div class="yt-error">Failed to load jobs: ${escapeHtml(e.message)}</div>`;
        }
    }

    async _submit() {
        const input = this._el('yt-url');
        const url = input.value.trim();
        if (!url) return;
        const btn = this._el('yt-submit-btn');
        btn.disabled = true;
        try {
            const res = await fetch(`${API}/api/yt/jobs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || err.title || `HTTP ${res.status}`);
            }
            const job = await res.json();
            input.value = '';
            this._clearLog();
            await this._load();
            if (!ACTIVE.has(job.status)) this._renderStatus(job); // queued
        } catch (e) {
            this._renderStatus({ status: 'failed', error: e.message });
        } finally {
            btn.disabled = false;
        }
    }

    // =====================
    // Live stream
    // =====================

    _openStream(jobId) {
        if (this._streamJobId === jobId && this._es) return;
        this._closeStream();
        if (this._logJobId !== jobId) this._clearLog();
        this._streamJobId = jobId;
        this._logJobId = jobId;
        this._es = new EventSource(`${API}/api/yt/jobs/${jobId}/stream`);
        this._es.addEventListener('status', (e) => {
            const job = JSON.parse(e.data);
            this._renderStatus(job);
            if (TERMINAL.has(job.status)) {
                this._closeStream();
                this._load();
            }
        });
        this._es.addEventListener('segment', (e) => {
            const seg = JSON.parse(e.data);
            this._appendSegment(seg);
        });
        this._es.onerror = () => {
            // Server restart / network blip: drop and let the next open reload.
            this._closeStream();
        };
    }

    _closeStream() {
        if (this._es) { this._es.close(); this._es = null; }
        this._streamJobId = null;
    }

    // =====================
    // Render
    // =====================

    _renderStatus(job) {
        const row = this._el('yt-status-row');
        if (!job) { row.hidden = true; return; }
        row.hidden = false;
        const name = job.title || job.url || '';
        const label = STATUS_LABELS[job.status] || job.status;
        const err = job.status === 'failed' && job.error ? ` — ${job.error}` : '';
        this._el('yt-status-label').innerHTML =
            `<span class="yt-status-chip ${escapeHtml(job.status)}">${escapeHtml(label)}</span>` +
            `<span class="yt-status-title">${escapeHtml(name)}${escapeHtml(err)}</span>`;
        const pct = job.progress != null ? Math.round(job.progress * 100) : null;
        this._el('yt-progress').textContent =
            pct != null && !TERMINAL.has(job.status) ? `${pct}%` : '';
        this._el('yt-cancel-btn').hidden =
            !(ACTIVE.has(job.status) || job.status === 'queued');
        this._el('yt-cancel-btn').dataset.jobId = job.job_id || '';
        this._syncBusy(ACTIVE.has(job.status) || job.status === 'queued');
    }

    _appendSegment(seg) {
        const log = this._el('yt-log');
        const pinned = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
        const div = document.createElement('div');
        div.className = 'yt-seg';
        div.innerHTML =
            `<span class="yt-ts">[${fmtTs(seg.start)}]</span> ${escapeHtml(seg.text)}`;
        log.appendChild(div);
        if (pinned) log.scrollTop = log.scrollHeight;
    }

    _clearLog() {
        this._el('yt-log').textContent = '';
        this._logJobId = null;
    }

    _renderHistory() {
        const box = this._el('yt-history');
        const jobs = this._jobs.filter(j => !ACTIVE.has(j.status));
        if (!jobs.length) { box.innerHTML = ''; return; }
        box.innerHTML = jobs.map(j => {
            const name = j.title || j.url;
            const date = j.created_at ? j.created_at.slice(0, 10) : '';
            const dur = j.duration_seconds ? fmtTs(j.duration_seconds) : '';
            const noSpeech = j.status === 'complete' && j.segments_count === 0
                ? 'no speech' : '';
            // Completed rows carry no status dot —
            // done is the normal state; dots mark everything else.
            return `
            <div class="yt-history-row" data-job-id="${escapeHtml(j.job_id)}">
                ${j.status !== 'complete' ? `
                    <span class="yt-status-chip ${escapeHtml(j.status)}"
                          title="${escapeHtml(j.status === 'failed' ? (j.error || 'failed') : j.status)}"></span>` : ''}
                <span class="yt-history-title" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
                <span class="yt-history-meta">${escapeHtml([date, dur, noSpeech].filter(Boolean).join(' · '))}</span>
                ${j.status === 'queued' ? `
                    <button type="button" class="yt-row-btn" data-act="start"
                            aria-label="Start ${escapeHtml(name)}">Start</button>` : ''}
                ${j.txt_file ? `
                    <button type="button" class="yt-row-btn" data-act="view"
                            aria-label="View transcript of ${escapeHtml(name)}">View</button>
                    <button type="button" class="yt-row-btn" data-act="copy"
                            aria-label="Copy file path of ${escapeHtml(name)}">Copy</button>` : ''}
                <button type="button" class="yt-row-btn yt-row-delete" data-act="delete"
                        aria-label="Delete ${escapeHtml(name)} and its transcript file">&times;</button>
            </div>`;
        }).join('');
    }

    _syncBusy(busy) {
        // Taskbar live-state: red-outlined chip while a job is queued/running.
        const had = this.hasAttribute('recording');
        if (busy === had) return;
        this.toggleAttribute('recording', busy);
        this.dispatchEvent(new CustomEvent('panel:state', { bubbles: true }));
    }

    // =====================
    // History actions
    // =====================

    async _fetchText(jobId) {
        const res = await fetch(`${API}/api/yt/jobs/${jobId}/text`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    async _viewJob(jobId) {
        try {
            const data = await this._fetchText(jobId);
            this._clearLog();
            this._logJobId = jobId;
            const log = this._el('yt-log');
            for (const line of data.text.split('\n')) {
                if (!line.trim()) continue;
                const div = document.createElement('div');
                div.className = 'yt-seg';
                div.textContent = line;
                log.appendChild(div);
            }
            const job = this._jobs.find(j => j.job_id === jobId);
            if (job) this._renderStatus(job);
        } catch (e) {
            this._renderStatus({ status: 'failed', error: `View failed: ${e.message}` });
        }
    }

    async _copyJob(jobId, btn) {
        // Copies the transcript's absolute file path — pasteable straight
        // into an agent session.
        try {
            const data = await this._fetchText(jobId);
            await navigator.clipboard.writeText(data.txt_path);
            const old = btn.textContent;
            btn.textContent = '✓';
            setTimeout(() => { btn.textContent = old; }, 1200);
        } catch (e) {
            console.warn('Copy failed:', e);
        }
    }

    // =====================
    // Events
    // =====================

    _wireEvents() {
        this.addEventListener('panel:open', () => this._load());
        this.addEventListener('panel:close', () => this._closeStream());

        this.addEventListener('click', async (e) => {
            if (e.target.closest('#yt-submit-btn')) { this._submit(); return; }

            const cancel = e.target.closest('#yt-cancel-btn');
            if (cancel && cancel.dataset.jobId) {
                await fetch(`${API}/api/yt/jobs/${cancel.dataset.jobId}/cancel`,
                    { method: 'POST' }).catch(() => {});
                this._closeStream();
                this._load();
                return;
            }

            const rowBtn = e.target.closest('.yt-row-btn');
            if (rowBtn) {
                const jobId = rowBtn.closest('.yt-history-row')?.dataset.jobId;
                if (!jobId) return;
                const act = rowBtn.dataset.act;
                if (act === 'view') this._viewJob(jobId);
                else if (act === 'copy') this._copyJob(jobId, rowBtn);
                else if (act === 'start') {
                    await fetch(`${API}/api/yt/jobs/${jobId}/start`,
                        { method: 'POST' }).catch(() => {});
                    this._load();
                } else if (act === 'delete') {
                    // Real delete-off-disk (record + transcript .txt), so it
                    // confirms first.
                    const job = this._jobs.find(j => j.job_id === jobId);
                    const name = job?.title || job?.url || jobId;
                    const what = job?.txt_file
                        ? 'and its transcript file will be deleted from disk'
                        : 'will be removed';
                    if (!confirm(`"${name}" ${what}. Continue?`)) return;
                    await fetch(`${API}/api/yt/jobs/${jobId}`,
                        { method: 'DELETE' }).catch(() => {});
                    if (this._logJobId === jobId) this._clearLog();
                    this._load();
                }
            }
        });

        this.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.target.id === 'yt-url') this._submit();
        });
    }
}

customElements.define('ihim-yt', IhimYt);
