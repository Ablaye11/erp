// Service Worker — École Al-Nour ERP (C4)
const CACHE_NAME = 'al-nour-erp-v1';
const STATIC_ASSETS = [
    '/',
    '/static/css/style.css',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(STATIC_ASSETS).catch((err) => {
                console.warn('SW: Some static assets failed to cache', err);
            });
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => caches.delete(name))
            );
        })
    );
    self.clients.claim();
});

// Network-first strategy: always try network, fallback to cache
self.addEventListener('fetch', (event) => {
    // Only handle GET requests
    if (event.request.method !== 'GET') return;

    // Skip Django admin, API calls, and HTMX panel requests
    const url = new URL(event.request.url);
    if (url.pathname.startsWith('/admin') ||
        url.pathname.startsWith('/api/') ||
        url.pathname.startsWith('/action/') ||
        url.pathname.startsWith('/panel/')) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // Cache static assets
                if (url.pathname.startsWith('/static/')) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() => {
                return caches.match(event.request);
            })
    );
});
