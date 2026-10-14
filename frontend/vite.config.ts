/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs on :8000 (make run / scripts/run_local.sh); the dev server forwards /api to it.
// ZIIRA_API_URL points both the dev server and `vite preview` elsewhere (the end-to-end tests do).
const apiUrl = process.env.ZIIRA_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
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
