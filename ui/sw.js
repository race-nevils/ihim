/**
 * iHIM Service Worker — resilient app shell.
 *
 * Strategy:
 *   - App shell (HTML, CSS, JS): network-first, fall back to cache
 *   - API requests: network-only (never cache data)
 *   - On server restart/crash, cached shell loads instantly
 *
 * W3C Service Workers spec compliant.
 */

const CACHE_NAME = 'ihim-shell-v1';

// App shell files to pre-cache on install
const SHELL_FILES = [
    '/',
    '/static/style.css',
];

// Install — pre-cache shell
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(SHELL_FILES))
            .then(() => self.skipWaiting())
    );
});

// Activate — clean old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

// Fetch — network-first for shell, network-only for API
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Never cache API requests or WebSocket upgrades
    if (url.pathname.startsWith('/api/') || event.request.headers.get('upgrade') === 'websocket') {
        return;
    }

    // Network-first for app shell
    event.respondWith(
        fetch(event.request)
            .then(response => {
                // Cache successful responses
                if (response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() => {
                // Network failed — try cache
                return caches.match(event.request).then(cached => {
                    if (cached) return cached;
                    // Fallback: return cached root for navigation requests
                    if (event.request.mode === 'navigate') {
                        return caches.match('/');
                    }
                    return new Response('Offline', { status: 503 });
                });
            })
    );
});
