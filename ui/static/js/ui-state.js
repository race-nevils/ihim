/**
 * ui-state.js — server-mirrored UI state.
 *
 * The whole desktop layout (window positions / sizes / open flags, icon
 * layout, stopwatches) lives in localStorage for synchronous reads, and is
 * mirrored to the server preferences store under "ui_state" so every client
 * — browser tabs and the Electron desktop app — shares ONE desktop.
 *
 * hydrateUiState() runs before any component registers (main.js awaits it
 * before importing components): server values are copied into localStorage,
 * so components keep reading localStorage synchronously with no async
 * plumbing. Writes go through persist()/unpersist(), which update
 * localStorage immediately and batch a deep-merge PUT /api/preferences
 * (null tombstones a removed key). If the server is unreachable the page
 * degrades to a plain localStorage session — the dashboard never blocks.
 */

// Keys that count as UI state: component STORAGE_KEYs (ihim_*) and every
// persist-key family (<name>WindowPosition, -size, -open).
const UI_KEY_RE = /^ihim_|WindowPosition/;

let pending = {};
let timer = null;

export async function hydrateUiState() {
    let server;
    try {
        const r = await fetch('/api/preferences', { cache: 'no-store' });
        if (!r.ok) return;
        server = (await r.json()).ui_state;
    } catch { return; /* unreachable — localStorage-only session, don't seed */ }

    const known = (server && typeof server === 'object') ? server : {};
    for (const [key, value] of Object.entries(known)) {
        if (value === null) localStorage.removeItem(key);
        else localStorage.setItem(key, String(value));
    }

    // Gap-fill: local UI keys the server doesn't know yet (first run after
    // the localStorage-only era) are pushed up — added, never overwriting.
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && UI_KEY_RE.test(key) && !(key in known)) {
            queue(key, localStorage.getItem(key));
        }
    }
}

export function persist(key, value) {
    localStorage.setItem(key, value);
    queue(key, value);
}

export function unpersist(key) {
    localStorage.removeItem(key);
    queue(key, null);
}

function queue(key, value) {
    pending[key] = value;
    clearTimeout(timer);
    timer = setTimeout(flush, 400);
}

function flush() {
    clearTimeout(timer);
    timer = null;
    if (!Object.keys(pending).length) return;
    const body = JSON.stringify({ ui_state: pending });
    pending = {};
    // keepalive lets the final flush survive tab close
    fetch('/api/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true,
    }).catch(() => { /* best-effort mirror — localStorage already has it */ });
}

// Debounce window may still be open when the tab closes — flush what's left.
window.addEventListener('pagehide', flush);
