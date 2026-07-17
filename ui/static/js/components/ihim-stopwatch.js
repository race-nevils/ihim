/**
 * Stopwatch Web Components — one feature, two elements:
 *
 *   <ihim-stopwatch-dock> — fixed top-right dock: spawn button + list.
 *     Owns persistence (localStorage 'ihim_stopwatches') and timer ids.
 *     Public API: spawn()
 *
 *   <ihim-stopwatch> — a single timer. Owns its interval, drag, and controls.
 *     Set .state = { id, elapsed, running, x, y } before appending.
 *     Events (bubble): stopwatch:change (any state mutation), stopwatch:remove
 */

import { persist } from '../ui-state.js';

function formatTime(ms) {
    const totalSeconds = Math.floor(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    const centiseconds = Math.floor((ms % 1000) / 10);
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(centiseconds).padStart(2, '0')}`;
}

// ---------------------------------------------------------------------------
// <ihim-stopwatch>
// ---------------------------------------------------------------------------

class IhimStopwatch extends HTMLElement {
    state = { id: 0, elapsed: 0, running: false, x: undefined, y: undefined };
    _intervalId = null;
    _startTime = null;

    connectedCallback() {
        const sw = this.state;
        this.classList.add('stopwatch-item');
        this.dataset.id = sw.id;

        if (sw.x !== undefined && sw.y !== undefined) {
            this.style.position = 'fixed';
            this.style.left = sw.x + 'px';
            this.style.top = sw.y + 'px';
        }

        this.innerHTML = `
            <div class="stopwatch-header stopwatch-drag-handle">
                <span class="stopwatch-label">Timer ${parseInt(sw.id)}</span>
                <button class="stopwatch-close" data-action="remove" title="Remove">&times;</button>
            </div>
            <div class="stopwatch-display">${formatTime(sw.elapsed)}</div>
            <div class="stopwatch-controls">
                <button class="stopwatch-btn start" data-action="toggle">Start</button>
                <button class="stopwatch-btn reset" data-action="reset">Reset</button>
            </div>
        `;

        this._wireDrag();

        // Event delegation for controls
        this.addEventListener('click', (e) => {
            const button = e.target.closest('button[data-action]');
            if (!button) return;
            switch (button.dataset.action) {
                case 'remove': this.remove(); break;
                case 'toggle': this.toggle(); break;
                case 'reset': this.reset(); break;
            }
        });

        if (sw.running) {
            this._startTime = Date.now() - sw.elapsed;
            this._startTimer();
            this._updateToggleBtn();
        }
    }

    disconnectedCallback() {
        if (this._intervalId) { clearInterval(this._intervalId); this._intervalId = null; }
    }

    /** Current persistable state (elapsed computed live while running). */
    get snapshot() {
        const sw = this.state;
        return {
            id: sw.id,
            elapsed: sw.running ? Date.now() - this._startTime : sw.elapsed,
            running: sw.running,
            x: sw.x, y: sw.y,
        };
    }

    toggle() { this.state.running ? this.stop() : this.start(); }

    start() {
        const sw = this.state;
        if (sw.running) return;
        sw.running = true;
        this._startTime = Date.now() - sw.elapsed;
        this._startTimer();
        this._updateToggleBtn();
        this._changed();
    }

    stop() {
        const sw = this.state;
        if (!sw.running) return;
        sw.running = false;
        sw.elapsed = Date.now() - this._startTime;
        this._clearTimer();
        this._updateToggleBtn();
        this._changed();
    }

    reset() {
        const sw = this.state;
        if (sw.running) { this._clearTimer(); sw.running = false; }
        sw.elapsed = 0;
        this._startTime = null;
        this.querySelector('.stopwatch-display').textContent = formatTime(0);
        this._updateToggleBtn();
        this._changed();
    }

    remove() {
        this._clearTimer();
        this.dispatchEvent(new CustomEvent('stopwatch:remove', { bubbles: true }));
        this.classList.add('removing');
        setTimeout(() => super.remove(), 250);
    }

    _startTimer() {
        this.classList.add('running');
        this._intervalId = setInterval(() => {
            this.state.elapsed = Date.now() - this._startTime;
            this.querySelector('.stopwatch-display').textContent = formatTime(this.state.elapsed);
        }, 10);
    }

    _clearTimer() {
        if (this._intervalId) { clearInterval(this._intervalId); this._intervalId = null; }
        this.classList.remove('running');
    }

    _updateToggleBtn() {
        const btn = this.querySelector('[data-action="toggle"]');
        if (!btn) return;
        btn.textContent = this.state.running ? 'Stop' : 'Start';
        btn.classList.toggle('stop', this.state.running);
        btn.classList.toggle('start', !this.state.running);
    }

    _changed() {
        this.dispatchEvent(new CustomEvent('stopwatch:change', { bubbles: true }));
    }

    _wireDrag() {
        const header = this.querySelector('.stopwatch-drag-handle');
        let isDragging = false;
        let mouseDownTime = 0;
        let startX, startY, offsetX, offsetY;
        header.style.cursor = 'move';

        header.addEventListener('mousedown', (e) => {
            if (e.target.classList.contains('stopwatch-close')) return;
            mouseDownTime = Date.now();
            isDragging = false;
            const rect = this.getBoundingClientRect();
            offsetX = e.clientX - rect.left;
            offsetY = e.clientY - rect.top;
            startX = e.clientX;
            startY = e.clientY;

            const onMouseMove = (e) => {
                const dx = Math.abs(e.clientX - startX);
                const dy = Math.abs(e.clientY - startY);
                const elapsed = Date.now() - mouseDownTime;
                if ((dx > 5 || dy > 5 || elapsed > 150) && !isDragging) {
                    isDragging = true;
                    this.style.position = 'fixed';
                    this.style.opacity = '0.8';
                    this.style.zIndex = '1000';
                }
                if (isDragging) {
                    this.style.left = (e.clientX - offsetX) + 'px';
                    this.style.top = (e.clientY - offsetY) + 'px';
                }
            };

            const onMouseUp = () => {
                if (isDragging) {
                    this.state.x = parseInt(this.style.left);
                    this.state.y = parseInt(this.style.top);
                    this._changed();
                    this.style.opacity = '1';
                    this.style.zIndex = '';
                }
                isDragging = false;
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            };

            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }
}

customElements.define('ihim-stopwatch', IhimStopwatch);

// ---------------------------------------------------------------------------
// <ihim-stopwatch-dock>
// ---------------------------------------------------------------------------

class IhimStopwatchDock extends HTMLElement {
    nextId = 1;
    STORAGE_KEY = 'ihim_stopwatches';

    connectedCallback() {
        this.innerHTML = `
            <button class="stopwatch-spawn-btn" title="Add Stopwatch" aria-label="Add Stopwatch">
                <i data-lucide="timer" class="stopwatch-icon"></i>
                <i data-lucide="plus" class="stopwatch-plus"></i>
            </button>
            <div class="stopwatch-list"></div>
        `;
        this._list = this.querySelector('.stopwatch-list');

        this.querySelector('.stopwatch-spawn-btn').addEventListener('click', () => this.spawn());
        this.addEventListener('stopwatch:change', () => this._saveState());
        this.addEventListener('stopwatch:remove', (e) => {
            // Exclude the departing element — it's still in the DOM until its exit animation ends.
            this._saveState(e.target);
        });

        this._restoreState();
    }

    spawn() {
        this._add({ id: this.nextId++, elapsed: 0, running: false });
        this._saveState();
    }

    _add(state) {
        const el = document.createElement('ihim-stopwatch');
        el.state = state;
        this._list.appendChild(el);
    }

    _watches(excludeEl = null) {
        return [...this._list.querySelectorAll('ihim-stopwatch')].filter(el => el !== excludeEl);
    }

    _saveState(excludeEl = null) {
        const state = {
            nextId: this.nextId,
            stopwatches: this._watches(excludeEl).map(el => el.snapshot),
        };
        persist(this.STORAGE_KEY, JSON.stringify(state));
    }

    _restoreState() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            if (!stored) return;
            const state = JSON.parse(stored);
            this.nextId = parseInt(state.nextId) || 1;
            for (const sw of state.stopwatches || []) {
                const id = parseInt(sw.id);
                if (!Number.isInteger(id) || id < 1) continue;
                this._add({
                    id,
                    elapsed: parseInt(sw.elapsed) || 0,
                    running: Boolean(sw.running),
                    x: sw.x, y: sw.y,
                });
            }
        } catch (err) { console.error('Failed to restore stopwatch state:', err); }
    }
}

customElements.define('ihim-stopwatch-dock', IhimStopwatchDock);
