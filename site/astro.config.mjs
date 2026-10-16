import { defineConfig } from "astro/config";
import { loadEnv } from "vite";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const env = { ...loadEnv(process.env.NODE_ENV ?? "production", process.cwd(), ""), ...process.env };
const PLACEHOLDER = "https://example.invalid";
const siteUrl = (env.PUBLIC_SITE_URL || PLACEHOLDER).replace(/\/+$/, "");

/** Warn loudly (or fail with SITE_STRICT=1) when the canonical origin is not set: every canonical, sitemap and Open Graph URL depends on it. */
function siteUrlGuard() {
  return {
    name: "ziira-site-url-guard",
    hooks: {
      "astro:build:start": ({ logger }) => {
        if (siteUrl === PLACEHOLDER || /example\.(invalid|com|org)|localhost/.test(siteUrl)) {
          const bar = "=".repeat(78);
          const msg = `\n${bar}\n WARNING: PUBLIC_SITE_URL is ${env.PUBLIC_SITE_URL ? "a placeholder" : "not set"} (${siteUrl}).\n Canonical links, the sitemap, hreflang and social cards will point at it.\n DO NOT DEPLOY THIS BUILD. Set PUBLIC_SITE_URL to the real origin and rebuild.\n${bar}\n`;
          if (env.SITE_STRICT) throw new Error(msg);
          logger.warn(msg);
        }
      },
    },
  };
}

/** Writes dist/_redirects from redirects.json (301 map for future moves). */
function redirectsFile() {
  return {
    name: "ziira-redirects",
    hooks: {
      "astro:build:done": ({ dir, logger }) => {
        const data = JSON.parse(fs.readFileSync(new URL("./redirects.json", import.meta.url), "utf8"));
        const rows = data.redirects ?? [];
        for (const r of rows) {
          if (!r.from?.startsWith("/") || !r.to?.startsWith("/") || r.from === r.to) throw new Error(`redirects.json: bad row ${JSON.stringify(r)}`);
        }
        const body = rows.map((r) => `${r.from} ${r.to} 301`).join("\n") + (rows.length ? "\n" : "");
        fs.writeFileSync(path.join(fileURLToPath(dir), "_redirects"), `# generated from redirects.json\n${body}`);
        logger.info(`wrote _redirects (${rows.length} rows)`);
      },
    },
  };
}

export default defineConfig({
  site: siteUrl,
  output: "static",
  trailingSlash: "always",
  build: { format: "directory", inlineStylesheets: "auto" },
  compressHTML: true,
  prefetch: false,
  devToolbar: { enabled: false },
  integrations: [siteUrlGuard(), redirectsFile()],
});
