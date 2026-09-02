// Trovee service worker.
// Only caches the static app shell (CSS/JS/icons/manifest) so the app can
// install and open quickly offline. It deliberately NEVER caches anything
// under /api/ — balances, prices, and messages must always come from the
// network so nobody is ever shown stale financial data.

const CACHE_VERSION = "trovee-shell-v1";
const PRECACHE_URLS = [
  "/static/css/trovee.css",
  "/static/js/trovee.js",
  "/static/img/logo.png",
  "/static/img/favicon.ico",
  "/static/img/icon-192.png",
  "/static/img/icon-512.png",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(PRECACHE_URLS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== "GET" || url.origin !== self.location.origin) return;

  // Never cache API calls — always hit the network for live data.
  if (url.pathname.startsWith("/api/")) return;

  // Page navigations: network-first, so users get fresh content when
  // online, with a soft offline fallback when they don't have a connection.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() =>
        caches.match(req).then(
          (cached) =>
            cached ||
            new Response(
              "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Trovee — Offline</title>" +
                "<style>body{background:#06080D;color:#F5F7FA;font-family:sans-serif;" +
                "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;padding:24px;}" +
                "</style></head><body><div><h2>You're offline</h2>" +
                "<p>Reconnect to the internet to keep using Trovee.</p></div></body></html>",
              { headers: { "Content-Type": "text/html" } }
            )
        )
      )
    );
    return;
  }

  // Static assets: cache-first, refreshing the cache in the background.
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
