/**
 * calendar.js — Google Calendar integration module
 */
import { API, showStatus } from './app.js';

let calendarCache = null;

export function openCalendarWindow() {
    document.getElementById('calendar-window')?.open();
}

export function closeCalendarWindow() {
    document.getElementById('calendar-window')?.close();
}

export function initCalendarEvents() {
    const win = document.getElementById('calendar-window');
    if (!win) return;
    win.addEventListener('panel:open', () => {
        if (typeof lucide !== 'undefined') lucide.createIcons();
        loadCalendarEvents();
    });
}

async function loadCalendarEvents() {
    const statusEl = document.getElementById('calendar-status');
    const bodyEl = document.getElementById('calendar-body');
    const syncTimeEl = document.getElementById('calendar-sync-time');

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
            document.getElementById('cal-auth-btn')?.addEventListener('click', startCalendarAuth);
            return;
        }

        statusEl.innerHTML = '<span class="cal-status-ok">Connected</span>';

        const res = await fetch(`${API}/api/calendar/events?days_ahead=365`);
        const data = await res.json();
        calendarCache = data;

        if (data.cached_at) {
            const age = Date.now() - new Date(data.cached_at).getTime();
            const mins = Math.round(age / 60000);
            syncTimeEl.textContent = mins < 1 ? 'Just synced' : `${mins}m ago`;
            if (age > 5 * 60 * 1000) { syncCalendar(); return; }
        } else {
            syncTimeEl.textContent = 'Never synced';
            syncCalendar();
            return;
        }

        renderCalendarEvents(data.events || []);
    } catch (e) {
        statusEl.innerHTML = `<span class="cal-status-err">Error: ${e.message}</span>`;
        bodyEl.innerHTML = '<div class="calendar-empty">Failed to load calendar data.</div>';
    }
}

function renderCalendarEvents(events) {
    const bodyEl = document.getElementById('calendar-body');
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

    // Event delegation for opening calendar links
    bodyEl.addEventListener('click', (e) => {
        const card = e.target.closest('.cal-event-card');
        if (card?.dataset.link) window.open(card.dataset.link, '_blank');
    });
}

export async function syncCalendar() {
    const syncTimeEl = document.getElementById('calendar-sync-time');
    const refreshBtn = document.querySelector('.calendar-refresh-btn');
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
            calendarCache = data;
            renderCalendarEvents(data.events || []);
            syncTimeEl.textContent = 'Just synced';
        } else { syncTimeEl.textContent = 'Sync failed'; }
    } catch (e) { syncTimeEl.textContent = 'Sync error'; }
    finally { if (refreshBtn) refreshBtn.classList.remove('spinning'); }
}

async function startCalendarAuth() {
    const statusEl = document.getElementById('calendar-status');
    statusEl.innerHTML = '<span class="cal-status-pending">Opening Google sign-in...</span>';
    try {
        const res = await fetch(`${API}/api/calendar/auth/start`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            statusEl.innerHTML = '<span class="cal-status-ok">Connected!</span>';
            await loadCalendarEvents();
        } else {
            statusEl.innerHTML = `<span class="cal-status-err">${data.message || 'Auth failed'}</span>`;
        }
    } catch (e) {
        statusEl.innerHTML = `<span class="cal-status-err">Auth error: ${e.message}</span>`;
    }
}

export function toggleCalendarAddForm() {
    const form = document.getElementById('calendar-add-form');
    const isVisible = form.style.display !== 'none';
    form.style.display = isVisible ? 'none' : 'block';
    if (!isVisible) {
        document.getElementById('cal-new-summary').focus();
        const now = new Date();
        now.setMinutes(0, 0, 0);
        now.setHours(now.getHours() + 1);
        const end = new Date(now.getTime() + 3600000);
        document.getElementById('cal-new-start').value = toLocalISO(now);
        document.getElementById('cal-new-end').value = toLocalISO(end);
    }
}

function toLocalISO(date) {
    const pad = n => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export async function pushNewCalendarEvent() {
    const summary = document.getElementById('cal-new-summary').value.trim();
    const start = document.getElementById('cal-new-start').value;
    const end = document.getElementById('cal-new-end').value;
    const description = document.getElementById('cal-new-description').value.trim();

    if (!summary) { alert('Event title is required'); return; }
    if (!start || !end) { alert('Start and end times are required'); return; }

    const btn = document.querySelector('.cal-create-btn');
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
            toggleCalendarAddForm();
            document.getElementById('cal-new-summary').value = '';
            document.getElementById('cal-new-description').value = '';
            await loadCalendarEvents();
        } else {
            alert('Failed to create event: ' + (data.detail || data.error || 'Unknown error'));
        }
    } catch (e) { alert('Error creating event: ' + e.message); }
    finally { btn.disabled = false; btn.textContent = 'Create on GCal'; }
}
