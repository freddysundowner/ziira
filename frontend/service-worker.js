/*
 * The app's service worker (production build only). It exists so the till terminal still loads when the page is opened
 * with no connection: after one visit online, the app shell (index.html and every script and style of the build) is
 * kept in the browser. It never touches /api: data and sales are handled by the app itself (IndexedDB).
 *
 * The build (vite.config.ts) fills in the file list and a version hash of it below, so every release gets its own
 * cache and the previous one is deleted when the new worker takes over.
 */
const VERSION = "__VERSION__";
const PRECACHE = __PRECACHE__;
const CACHE = `ziira-shell-${VERSION}`;
const SHELL = "/";
const NAVIGATION_TIMEOUT_MS = 4000;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE.map((url) => new Request(url, { cache: "reload" }))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n.startsWith("ziira-shell-") && n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

/** Page loads: the network when it answers (fresh index.html), else the saved shell. */
function navigate(request) {
  return new Promise((resolve) => {
    const fallback = () => caches.match(SHELL).then((saved) => resolve(saved || Response.error()));
    const timer = setTimeout(fallback, NAVIGATION_TIMEOUT_MS);
    fetch(request).then(
      (response) => { clearTimeout(timer); resolve(response); },
      () => { clearTimeout(timer); fallback(); },
    );
  });
}

/** Built files carry a hash in their name, so a saved copy is always right. */
function asset(request) {
  return caches.match(request).then((saved) => saved || fetch(request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request, copy));
    }
    return response;
  }));
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (request.mode === "navigate") {
    event.respondWith(navigate(request));
  } else if (url.pathname.startsWith("/assets/")) {
    event.respondWith(asset(request));
  }
});
