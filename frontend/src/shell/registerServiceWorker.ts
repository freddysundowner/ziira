/**
 * Registers the service worker (production build only), which keeps the app shell so the till terminal opens without a
 * connection. The worker file is written by the build (vite.config.ts) from service-worker.js.
 */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);      // without it the app still works online
  });
}
