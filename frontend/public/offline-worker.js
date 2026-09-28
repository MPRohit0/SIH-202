// Hand-written service worker (no build plugin — see frontend/CLAUDE.md's "no
// new UI libraries" rule and the fact this repo has no vite-plugin-pwa dep).
// Two jobs:
//   1. Runtime-cache the app shell (HTML/JS/CSS, same-origin) as it's
//      fetched, so the SPA itself can load offline after at least one
//      online visit.
//   2. On any failed/offline GET request, fall back to whatever was
//      explicitly cached by "Save for offline"
//      (src/offline/cache-store.ts, cache 'terraflow-offline-data-v1') or
//      by this worker's own runtime shell cache — whichever has it.
// It never intercepts non-GET requests: POST actions (new simulation, GEE
// refresh, Add a dam) must reach the real server or fail outright, matching
// the UI's own offline-disabling of those actions.

const SHELL_CACHE = 'terraflow-shell-v1';

// The page that registers this worker isn't itself under its control (a
// worker only controls pages from their *next* navigation onward), so the
// app shell HTML and its content-hashed JS/CSS bundle would otherwise never
// get cached until a second visit. Fetch '/' once during install, cache it,
// and pull its own <script src>/<link href> asset paths out of the markup
// (no build manifest exists to read instead) so the shell is fully
// offline-navigable after just one online visit.
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(SHELL_CACHE);
      const response = await fetch('/');
      const html = await response.clone().text();
      const assetUrls = Array.from(html.matchAll(/(?:src|href)="(\/[^"]+\.(?:js|css))"/g)).map(m => m[1]);
      await cache.put('/', response);
      await Promise.all(assetUrls.map(url => cache.add(url).catch(() => {})));
    } catch {
      // Best effort; runtime caching below still covers subsequent visits.
    }
  })());
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', event => {
  const {request} = event;
  if (request.method !== 'GET') return;

  event.respondWith((async () => {
    try {
      const response = await fetch(request);
      if (response && response.ok && request.url.startsWith(self.location.origin)) {
        const shell = await caches.open(SHELL_CACHE);
        shell.put(request, response.clone()).catch(() => {});
      }
      return response;
    } catch {
      const cached = await caches.match(request, {ignoreVary: true});
      if (cached) return cached;
      if (request.mode === 'navigate') {
        const shellFallback = await caches.match('/');
        if (shellFallback) return shellFallback;
      }
      throw new Error(`offline and no cached response for ${request.url}`);
    }
  })());
});
