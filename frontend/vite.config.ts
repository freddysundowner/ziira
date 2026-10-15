/// <reference types="vitest" />
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// The API runs on :8000 (make run / scripts/run_local.sh); the dev server forwards /api to it.
// ZIIRA_API_URL points both the dev server and `vite preview` elsewhere (the end-to-end tests do).
const apiUrl = process.env.ZIIRA_API_URL ?? "http://localhost:8000";

/**
 * Production build only: writes `sw.js` (the file service-worker.js with the build's file list filled in), the service
 * worker that lets the till terminal load without a connection. See docs/offline-pos.md.
 */
function serviceWorker(): Plugin {
  return {
    name: "ziira-service-worker",
    apply: "build",
    generateBundle(_options, bundle) {
      const files = Object.keys(bundle).filter((name) => /\.(js|css|html)$/.test(name));
      const urls = ["/", ...files.map((name) => `/${name}`)];
      const version = createHash("sha256").update(files.sort().join("\n")).digest("hex").slice(0, 12);
      const source = readFileSync(new URL("./service-worker.js", import.meta.url), "utf8")
        .replace("__VERSION__", version)
        .replace("__PRECACHE__", JSON.stringify(urls));      // the first occurrence of each: the constants in the file
      this.emitFile({ type: "asset", fileName: "sw.js", source });
    },
  };
}

export default defineConfig({
  plugins: [react(), serviceWorker()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: { port: 5173, proxy: { "/api": apiUrl } },
  preview: { proxy: { "/api": apiUrl } },
  build: {
    rollupOptions: {
      // Libraries change rarely: their own files keep the browser cache warm across releases.
      output: { manualChunks: { react: ["react", "react-dom", "react-router-dom"], data: ["@tanstack/react-query", "i18next", "react-i18next", "openapi-fetch"], icons: ["lucide-react"] } },
    },
  },
  test: { environment: "jsdom", globals: false },
});
