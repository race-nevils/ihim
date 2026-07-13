/**
 * <ihim-calendar> — Google Calendar window.
 * Extends IhimPanel: IS the draggable window; renders its own chrome +
 * content, loads data on its panel:open lifecycle.
 */
import { API } from '../app.js';
import { IhimPanel } from './ihim-panel.js';

class IhimCalendar extends IhimPanel {
    connectedCallback() {
        this.innerHTML = `
            <div class="calendar-header calendar-drag-handle" data-drag-handle>
                <span class="calendar-label"><i data-lucide="calendar-days" style="width:16px;height:16px;display:inline;vertical-align:middle;margin-right:6px;"></i>Google Calendar</span>
                <div class="calendar-header-actions">
                    <button class="calendar-refresh-btn" title="Refresh from Google" aria-label="Refresh from Google Calendar">
                        <i data-lucide="refresh-cw" style="width:14px;height:14px;"></i>
                    </button>
                    <button class="calendar-close" data-close-btn aria-label="Close Calendar">&times;</button>
                </div>
            </div>
            <div class="calendar-status" id="calendar-status"></div>
            <div class="calendar-body" id="calendar-body">
                <div class="calendar-empty">Loading...</div>
            </div>
            <div class="calendar-footer">
                <button class="calendar-add-btn">+ New Event</button>
                <span id="calendar-sync-time" class="calendar-sync-info"></span>
            </div>
            <div id="calendar-add-form" class="calendar-add-form" style="display: none;">
                <label for="cal-new-summary" class="sr-only">Event title</label>
                <input type="text" id="cal-new-summary" placeholder="Event title..." class="cal-input">
                <div class="cal-datetime-row">
                    <label for="cal-new-start" class="sr-only">Start date and time</label>
                    <input type="datetime-local" id="cal-new-start" class="cal-input">
                    <span class="cal-arrow" aria-hidden="true">→</span>
                    <label for="cal-new-end" class="sr-only">End date and time</label>
                    <input type="datetime-local" id="cal-new-end" class="cal-input">
                </div>
                <label for="cal-new-description" class="sr-only">Description</label>
                <input type="text" id="cal-new-description" placeholder="Description (optional)" class="cal-input">
                <div class="calendar-form-actions">
                    <button class="cal-create-btn">Create on GCal</button>
                    <button class="cal-cancel-btn">Cancel</button>
                </div>
            </div>
        `;

        this.addEventListener('panel:open', () => {
            if (typeof lucide !== 'undefined') lucide.createIcons();
            this._loadEvents();
        });

        this.querySelector('.calendar-refresh-btn').addEventListener('click', () => this._sync());
        this.querySelector('.calendar-add-btn').addEventListener('click', () => this._toggleAddForm());
        this.querySelector('.cal-create-btn').addEventListener('click', () => this._pushNewEvent());
        this.querySelector('.cal-cancel-btn').addEventListener('click', () => this._toggleAddForm());

        // Event delegation for opening calendar links
        this.querySelector('#calendar-body').addEventListener('click', (e) => {
            const card = e.target.closest('.cal-event-card');
            if (card?.dataset.link) window.open(card.dataset.link, '_blank');
        });

        super.connectedCallback();
    }

    _el(id) { return this.querySelector(`#${id}`); }

    async _loadEvents() {
        const statusEl = this._el('calendar-status');
        const bodyEl = this._el('calendar-body');
        const syncTimeEl = this._el('calendar-sync-time');

        try {
            const statusRes = await fetch(`${API}/api/calendar/status`);
            const status = await statusRes.json();

            if (!status.credentials_file_exists) {
                statusEl.innerHTML = '<span class="cal-status-warn">credentials.json not found in IHIM/data/</span>';
                bodyEl.innerHTML = '<div class="calendar-empty">Place your Google OAuth2 credentials.json in IHIM/data/ to get started.</div>';
                return;
            }

            if (!status.authenticated) {
                statusEl.innerHTML = '<span class="cal-status-warn">Not connected</span>';
                bodyEl.innerHTML = `
                    <div class="calendar-auth-prompt">
                        <p>Connect your Google Calendar to see events here.</p>
                        <button class="cal-auth-btn" id="cal-auth-btn">Connect Google Calendar</button>
                    </div>`;
                this._el('cal-auth-btn')?.addEventListener('click', () => this._startAuth());
                return;
            }

            statusEl.innerHTML = '<span class="cal-status-ok">Connected</span>';

            const res = await fetch(`${API}/api/calendar/events?days_ahead=365`);
            const data = await res.json();

            if (data.cached_at) {
                const age = Date.now() - new Date(data.cached_at).getTime();
                const mins = Math.round(age / 60000);
                syncTimeEl.textContent = mins < 1 ? 'Just synced' : `${mins}m ago`;
                if (age > 5 * 60 * 1000) { this._sync(); return; }
            } else {
                syncTimeEl.textContent = 'Never synced';
                this._sync();
                return;
            }

            this._renderEvents(data.events || []);
        } catch (e) {
            statusEl.innerHTML = `<span class="cal-status-err">Error: ${e.message}</span>`;
            bodyEl.innerHTML = '<div class="calendar-empty">Failed to load calendar data.</div>';
        }
    }

    _renderEvents(events) {
        const bodyEl = this._el('calendar-body');
        if (!events || events.length === 0) {
            bodyEl.innerHTML = '<div class="calendar-empty">No upcoming events</div>';
            return;
        }

        const grouped = {};
        events.forEach(ev => {
            const start = ev.start?.dateTime || ev.start?.date || '';
            const dateKey = start.slice(0, 10);
            if (!grouped[dateKey]) grouped[dateKey] = [];
            grouped[dateKey].push(ev);
        });

        const today = new Date().toISOString().slice(0, 10);
        const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);

        let html = '';
        Object.keys(grouped).sort().forEach(dateKey => {
            let label = dateKey;
            if (dateKey === today) label = 'Today';
            else if (dateKey === tomorrow) label = 'Tomorrow';
            else {
                const d = new Date(dateKey + 'T00:00:00');
                label = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
            }

            html += `<div class="cal-day-group"><div class="cal-day-label">${label}</div>`;
            grouped[dateKey].forEach(ev => {
                const startTime = ev.start?.dateTime
                    ? new Date(ev.start.dateTime).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
                    : 'All day';
                const endTime = ev.end?.dateTime
                    ? new Date(ev.end.dateTime).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
                    : '';
                const timeStr = endTime ? `${startTime} – ${endTime}` : startTime;
                const link = ev.htmlLink || '#';
                const loc = ev.location ? `<span class="cal-event-loc">${ev.location}</span>` : '';

                html += `<div class="cal-event-card" data-link="${link}">
                    <div class="cal-event-time">${timeStr}</div>
                    <div class="cal-event-info">
                        <div class="cal-event-title">${ev.summary || 'Untitled'}</div>
                        ${loc}
                    </div>
                </div>`;
            });
            html += '</div>';
        });

        bodyEl.innerHTML = html;
    }

    async _sync() {
        const syncTimeEl = this._el('calendar-sync-time');
        const refreshBtn = this.querySelector('.calendar-refresh-btn');
        if (refreshBtn) refreshBtn.classList.add('spinning');
        syncTimeEl.textContent = 'Syncing...';

        try {
            const res = await fetch(`${API}/api/calendar/sync`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days_ahead: 365, days_behind: 7 })
            });
            const data = await res.json();
            if (data.success) {
                this._renderEvents(data.events || []);
                syncTimeEl.textContent = 'Just synced';
            } else { syncTimeEl.textContent = 'Sync failed'; }
        } catch (e) { syncTimeEl.textContent = 'Sync error'; }
        finally { if (refreshBtn) refreshBtn.classList.remove('spinning'); }
    }

    async _startAuth() {
        const statusEl = this._el('calendar-status');
        statusEl.innerHTML = '<span class="cal-status-pending">Opening Google sign-in...</span>';
        try {
            const res = await fetch(`${API}/api/calendar/auth/start`, { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                statusEl.innerHTML = '<span class="cal-status-ok">Connected!</span>';
                await this._loadEvents();
            } else {
                statusEl.innerHTML = `<span class="cal-status-err">${data.message || 'Auth failed'}</span>`;
            }
        } catch (e) {
            statusEl.innerHTML = `<span class="cal-status-err">Auth error: ${e.message}</span>`;
        }
    }

    _toggleAddForm() {
        const form = this._el('calendar-add-form');
        const isVisible = form.style.display !== 'none';
        form.style.display = isVisible ? 'none' : 'block';
        if (!isVisible) {
            this._el('cal-new-summary').focus();
            const now = new Date();
            now.setMinutes(0, 0, 0);
            now.setHours(now.getHours() + 1);
            const end = new Date(now.getTime() + 3600000);
            this._el('cal-new-start').value = this._toLocalISO(now);
            this._el('cal-new-end').value = this._toLocalISO(end);
        }
    }

    _toLocalISO(date) {
        const pad = n => String(n).padStart(2, '0');
        return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    async _pushNewEvent() {
        const summary = this._el('cal-new-summary').value.trim();
        const start = this._el('cal-new-start').value;
        const end = this._el('cal-new-end').value;
        const description = this._el('cal-new-description').value.trim();

        if (!summary) { alert('Event title is required'); return; }
        if (!start || !end) { alert('Start and end times are required'); return; }

        const btn = this.querySelector('.cal-create-btn');
        btn.disabled = true;
        btn.textContent = 'Creating...';

        try {
            const res = await fetch(`${API}/api/calendar/events`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ summary, start, end, description })
            });
            const data = await res.json();
            if (data.success) {
                this._toggleAddForm();
                this._el('cal-new-summary').value = '';
                this._el('cal-new-description').value = '';
                await this._loadEvents();
            } else {
                alert('Failed to create event: ' + (data.detail || data.error || 'Unknown error'));
            }
        } catch (e) { alert('Error creating event: ' + e.message); }
        finally { btn.disabled = false; btn.textContent = 'Create on GCal'; }
    }
}

customElements.define('ihim-calendar', IhimCalendar);
