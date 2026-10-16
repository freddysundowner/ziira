// npm run lhci: runs Lighthouse (npx, not a dependency) against the built site on a local static server, mobile and desktop, and
// fails if any category is below 95 or a Core Web Vital budget is exceeded. Chromium comes from Playwright (../e2e/node_modules).
import { createRequire } from "node:module";
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { serve } from "./lib/static-server.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.resolve(here, "../../e2e/package.json"));
const { chromium } = require("playwright");
const chrome = process.env.CHROME_PATH ?? chromium.executablePath();
const PAGES = (process.env.LH_PAGES ?? "/,/product/,/intelligence/how-it-works/,/guides/cashier-voids-discount-abuse/,/get-started/").split(",");
const out = path.resolve(here, "../.lighthouse");
fs.mkdirSync(out, { recursive: true });
const srv = await serve(path.resolve(here, "../dist"));
let failed = false;
console.log("page".padEnd(52), "form".padEnd(8), "perf  a11y  bp    seo   LCP     CLS    TBT");
for (const preset of ["mobile", "desktop"]) {
  for (const p of PAGES) {
    const file = path.join(out, `${preset}-${p.replace(/[^a-z0-9]+/gi, "_")}.json`);
    const args = ["--yes", "lighthouse@13.5.0", `http://127.0.0.1:${srv.port}${p}`, "--output=json", `--output-path=${file}`, "--quiet", "--chrome-flags=--headless=new --no-sandbox", "--only-categories=performance,accessibility,best-practices,seo"];
    if (preset === "desktop") args.push("--preset=desktop");
    // async on purpose: the static server runs in this process and must keep answering while Lighthouse works
    const r = await new Promise((resolve) => execFile("npx", args, { env: { ...process.env, CHROME_PATH: chrome }, maxBuffer: 64 * 1024 * 1024 }, (err, _o, stderr) => resolve({ err, stderr })));
    if (r.err || !fs.existsSync(file)) { console.error(`Lighthouse failed for ${p}: ${String(r.stderr).slice(-500)}`); failed = true; continue; }
    const j = JSON.parse(fs.readFileSync(file, "utf8"));
    const sc = (k) => Math.round(j.categories[k].score * 100);
    const a = j.audits;
    const row = [sc("performance"), sc("accessibility"), sc("best-practices"), sc("seo")];
    const lcp = a["largest-contentful-paint"].numericValue, cls = a["cumulative-layout-shift"].numericValue, tbt = a["total-blocking-time"].numericValue;
    console.log(p.padEnd(52), preset.padEnd(8), row.map((x) => String(x).padEnd(5)).join(" "), `${(lcp / 1000).toFixed(2)}s `.padEnd(7), cls.toFixed(3).padEnd(6), `${Math.round(tbt)}ms`);
    if (row.some((x) => x < 95) || lcp > 2000 || cls > 0.1) failed = true;
  }
}
srv.close();
process.exit(failed ? 1 : 0);
