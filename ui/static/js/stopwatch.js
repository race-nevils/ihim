/**
 * stopwatch.js — Timer widget manager with drag-and-drop positioning
 */

export const stopwatchManager = {
    stopwatches: [],
    nextId: 1,
    STORAGE_KEY: 'ihim_stopwatches',

    formatTime(ms) {
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        const centiseconds = Math.floor((ms % 1000) / 10);
        return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(centiseconds).padStart(2, '0')}`;
    },

    spawn() {
        const id = this.nextId++;
        const stopwatch = {
            id, elapsed: 0, running: false, startTime: null, intervalId: null
        };
        this.stopwatches.push(stopwatch);
        this.renderStopwatch(stopwatch);
        this.saveState();
    },

    renderStopwatch(stopwatch) {
        const list = document.getElementById('stopwatch-list');
        const div = document.createElement('div');
        div.className = 'stopwatch-item';
        div.id = `stopwatch-${stopwatch.id}`;
        div.dataset.id = stopwatch.id;

        if (stopwatch.x !== undefined && stopwatch.y !== undefined) {
            div.style.position = 'fixed';
            div.style.left = stopwatch.x + 'px';
            div.style.top = stopwatch.y + 'px';
        }

        div.innerHTML = `
            <div class="stopwatch-header stopwatch-drag-handle">
                <span class="stopwatch-label">Timer ${parseInt(stopwatch.id)}</span>
                <button class="stopwatch-close" data-action="remove" title="Remove">&times;</button>
            </div>
            <div class="stopwatch-display" id="stopwatch-display-${parseInt(stopwatch.id)}">
                ${this.formatTime(stopwatch.elapsed)}
            </div>
            <div class="stopwatch-controls">
                <button class="stopwatch-btn start" id="stopwatch-toggle-${parseInt(stopwatch.id)}" data-action="toggle">
                    Start
                </button>
                <button class="stopwatch-btn reset" data-action="reset">
                    Reset
                </button>
            </div>
        `;

        list.appendChild(div);

        // Drag handling
        const header = div.querySelector('.stopwatch-drag-handle');
        let isDragging = false;
        let mouseDownTime = 0;
        let startX, startY, offsetX, offsetY;
        header.style.cursor = 'move';

        header.addEventListener('mousedown', (e) => {
            if (e.target.classList.contains('stopwatch-close')) return;
            mouseDownTime = Date.now();
            isDragging = false;
            const rect = div.getBoundingClientRect();
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
                    div.style.position = 'fixed';
                    div.style.opacity = '0.8';
                    div.style.zIndex = '1000';
                }
                if (isDragging) {
                    div.style.left = (e.clientX - offsetX) + 'px';
                    div.style.top = (e.clientY - offsetY) + 'px';
                }
            };

            const onMouseUp = () => {
                if (isDragging) {
                    stopwatch.x = parseInt(div.style.left);
                    stopwatch.y = parseInt(div.style.top);
                    this.saveState();
                    div.style.opacity = '1';
                    div.style.zIndex = '';
                }
                isDragging = false;
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            };

            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });

        // Event delegation for controls
        div.addEventListener('click', (e) => {
            const button = e.target.closest('button[data-action]');
            if (!button) return;
            const action = button.dataset.action;
            const id = parseInt(stopwatch.id);
            switch (action) {
                case 'remove': this.remove(id); break;
                case 'toggle': this.toggle(id); break;
                case 'reset': this.reset(id); break;
            }
        });

        if (stopwatch.running) this.startTimer(stopwatch);
    },

    toggle(id) {
        const sw = this.stopwatches.find(s => s.id === id);
        if (!sw) return;
        sw.running ? this.stop(id) : this.start(id);
    },

    start(id) {
        const sw = this.stopwatches.find(s => s.id === id);
        if (!sw || sw.running) return;
        sw.running = true;
        sw.startTime = Date.now() - sw.elapsed;
        this.startTimer(sw);
        this.updateUI(sw);
        this.saveState();
    },

    startTimer(stopwatch) {
        const item = document.getElementById(`stopwatch-${stopwatch.id}`);
        if (item) item.classList.add('running');
        stopwatch.intervalId = setInterval(() => {
            stopwatch.elapsed = Date.now() - stopwatch.startTime;
            const display = document.getElementById(`stopwatch-display-${stopwatch.id}`);
            if (display) display.textContent = this.formatTime(stopwatch.elapsed);
        }, 10);
    },

    stop(id) {
        const sw = this.stopwatches.find(s => s.id === id);
        if (!sw || !sw.running) return;
        sw.running = false;
        sw.elapsed = Date.now() - sw.startTime;
        if (sw.intervalId) { clearInterval(sw.intervalId); sw.intervalId = null; }
        const item = document.getElementById(`stopwatch-${sw.id}`);
        if (item) item.classList.remove('running');
        this.updateUI(sw);
        this.saveState();
    },

    reset(id) {
        const sw = this.stopwatches.find(s => s.id === id);
        if (!sw) return;
        if (sw.running) {
            if (sw.intervalId) { clearInterval(sw.intervalId); sw.intervalId = null; }
            sw.running = false;
            const item = document.getElementById(`stopwatch-${sw.id}`);
            if (item) item.classList.remove('running');
        }
        sw.elapsed = 0;
        sw.startTime = null;
        const display = document.getElementById(`stopwatch-display-${sw.id}`);
        if (display) display.textContent = this.formatTime(0);
        this.updateUI(sw);
        this.saveState();
    },

    remove(id) {
        const sw = this.stopwatches.find(s => s.id === id);
        if (!sw) return;
        if (sw.intervalId) clearInterval(sw.intervalId);
        const item = document.getElementById(`stopwatch-${id}`);
        if (item) {
            item.classList.add('removing');
            setTimeout(() => item.remove(), 250);
        }
        this.stopwatches = this.stopwatches.filter(s => s.id !== id);
        this.saveState();
    },

    updateUI(stopwatch) {
        const toggleBtn = document.getElementById(`stopwatch-toggle-${stopwatch.id}`);
        if (toggleBtn) {
            if (stopwatch.running) {
                toggleBtn.textContent = 'Stop';
                toggleBtn.classList.remove('start');
                toggleBtn.classList.add('stop');
            } else {
                toggleBtn.textContent = 'Start';
                toggleBtn.classList.remove('stop');
                toggleBtn.classList.add('start');
            }
        }
    },

    saveState() {
        const state = {
            nextId: this.nextId,
            stopwatches: this.stopwatches.map(s => ({
                id: s.id,
                elapsed: s.running ? Date.now() - s.startTime : s.elapsed,
                running: s.running,
                x: s.x, y: s.y
            }))
        };
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state));
    },

    restoreState() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            if (!stored) return;
            const state = JSON.parse(stored);
            this.nextId = parseInt(state.nextId) || 1;
            const list = document.getElementById('stopwatch-list');
            list.innerHTML = '';
            this.stopwatches = [];
            for (const sw of state.stopwatches || []) {
                const id = parseInt(sw.id);
                if (!Number.isInteger(id) || id < 1) continue;
                const stopwatch = {
                    id, elapsed: parseInt(sw.elapsed) || 0,
                    running: Boolean(sw.running),
                    startTime: sw.running ? Date.now() - (parseInt(sw.elapsed) || 0) : null,
                    intervalId: null, x: sw.x, y: sw.y
                };
                this.stopwatches.push(stopwatch);
                this.renderStopwatch(stopwatch);
            }
        } catch (err) { console.error('Failed to restore stopwatch state:', err); }
    },

    stopAll() {
        this.stopwatches.forEach(sw => {
            if (sw.intervalId) { clearInterval(sw.intervalId); sw.intervalId = null; }
        });
    },

    init() { this.restoreState(); }
};
