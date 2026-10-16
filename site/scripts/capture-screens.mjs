// Captures the marketing screenshots from the running Ziira web app (demo business) into src/assets/screens/*.webp
// and writes src/assets/screens/manifest.json (page route, capture date, git commit of the app) for every picture.
//
//   make site-screens                       # all of them (needs the app on :5173, the API on :8000 and the demo business)
//   node scripts/capture-screens.mjs --only command,till --out /tmp/scratch   # a few, optionally somewhere else
//
// Framing is fixed so pictures stay comparable: desktop 1440x1000 CSS px and phone 390x844, both at device scale factor 2 / 3,
// light mode, no scrollbars, no text cursor, no toasts. Emails and phone numbers on screen are replaced by obvious examples.
// Uses Playwright from ../e2e/node_modules (run `make e2e-setup` once). The demo login comes from CLAUDE.md (a development business).
// After a capture, `npm run build` optimises the pictures (AVIF/WebP via astro:assets). See docs/marketing-site.md.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "../..");
const require = createRequire(path.resolve(repo, "e2e/package.json"));
const { chromium } = require("playwright");

const APP = process.env.APP_URL ?? "http://localhost:5173";
const EMAIL = process.env.DEMO_EMAIL ?? "owner@demo-hardware.test";
const PASSWORD = process.env.DEMO_PASSWORD ?? "demo-pass-123";
const arg = (name) => (process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : null);
const only = arg("--only")?.split(",") ?? null;
const out = path.resolve(arg("--out") ?? path.resolve(here, "../src/assets/screens"));
fs.mkdirSync(out, { recursive: true });

const DESKTOP = { width: 1440, height: 1000, scale: 2 };
const PHONE = { width: 390, height: 844, scale: 3 };

// ---------------------------------------------------------------- helpers
/** Wait for the page to go quiet, but never longer than 10 s (the app keeps polling in places). */
const settle = (p) => p.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
/** Open a till on the first device that has none (a device can only have one open till), then put two items in the cart. */
async function sellScreen(p) {
  const search = p.locator("input[placeholder^='Search or scan']");
  await search.or(p.getByLabel("Branch")).first().waitFor({ timeout: 30000 });
  if (!(await search.count())) {
    for (const branch of ["Juja", "Ruiru", "Thika"]) {
      await p.getByLabel("Branch").selectOption({ label: branch });
      for (const device of await p.getByLabel("Till (device)").locator("option").allTextContents()) {
        await p.getByLabel("Till (device)").selectOption({ label: device });
        await p.getByLabel("Opening float").fill("5000");
        await p.getByRole("button", { name: /Open till|Try again/ }).click();
        await p.waitForTimeout(1500);
        if (await search.count()) break;
      }
      if (await search.count()) break;
    }
  }
  if (!(await search.count())) throw new Error("could not open a till on any device: close one in the app (Sell > Tills and devices)");
  const clear = p.getByRole("button", { name: "Clear", exact: true });
  if (await clear.count()) { await clear.first().click().catch(() => {}); await p.waitForTimeout(300); }
  for (const name of [/Cement 50kg/, /Claw hammer/, /Gloss enamel paint/]) {
    const b = p.getByRole("button", { name }).first();
    if (await b.count()) { await b.click(); await p.waitForTimeout(300); }
  }
  await p.waitForTimeout(500);
}
const clickTab = (name) => async (p) => {
  const tab = p.getByRole("tab", { name }).or(p.getByRole("link", { name, exact: true })).or(p.getByRole("button", { name, exact: true })).or(p.getByText(name, { exact: true })).first();
  await tab.waitFor({ timeout: 60000 }); await tab.click(); await p.waitForTimeout(1500);
};
const openFirstFinding = async (p) => {
  await p.locator('a[href^="/findings/"]:not([href="/findings/actions"]):not([href="/findings/checks"])').first().click();
  await settle(p); await p.waitForTimeout(1500);
};

// ---------------------------------------------------------------- what to photograph
// key = file name and ScreenKey in src/content/types.ts; route = the page; pre = get the page ready; clip = crop (CSS px); phone = 390x844
export const shots = [
  { key: "home", route: "/", wait: 2500 },
  { key: "command", route: "/command", wait: 3000 },
  { key: "findings", route: "/findings", wait: 2500 },
  { key: "finding", route: "/findings", pre: openFirstFinding },
  { key: "sales", route: "/pos/sales", wait: 2500 },
  { key: "till", route: "/pos/terminal", pre: sellScreen, wait: 1500 },
  { key: "stock", route: "/stock", wait: 2500 },
  { key: "orders", route: "/orders", wait: 2500 },
  { key: "owing", route: "/receivables", wait: 2500 },
  { key: "books", route: "/finance/reports", wait: 2500 },
  { key: "payroll", route: "/payroll", wait: 2500 },
  { key: "connect", route: "/connect", wait: 2500, clip: { x: 272, y: 322, width: 1152, height: 678 } }, // the coverage panel only: the demo business has two stray test connections above it
  { key: "connect-add", route: "/connect/new", wait: 2500 },
  { key: "addons", route: "/addons", wait: 2500 },
  { key: "intel-actions", route: "/admin/settings", pre: clickTab("Intelligence actions") },
  { key: "brief", route: "/command/briefs", pre: async (p) => {
      await p.getByRole("button", { name: "Show preview" }).click(); await p.waitForTimeout(2500);
      await p.getByText("Preview and send", { exact: true }).evaluate((el) => el.closest("div[class*=card], section, div")?.scrollIntoView({ block: "start" })); await p.waitForTimeout(300);
      await p.evaluate(() => { for (let e = document.querySelector("main"); e; e = e.parentElement) if (e.scrollTop > 80) { e.scrollTop -= 80; break; } }); await p.waitForTimeout(300);
    } },
  { key: "till-phone", route: "/pos/terminal", phone: true, wait: 1500, pre: async (p) => { await sellScreen(p); await p.getByRole("button", { name: /^Sale \(/ }).first().click(); await p.waitForTimeout(800); } },
  { key: "command-phone", route: "/command", phone: true, wait: 3000 },
];

// ---------------------------------------------------------------- page cleaning
const CSS = `
  *, *::before, *::after { caret-color: transparent !important; scrollbar-width: none !important; animation-duration: 0s !important; transition: none !important; }
  ::-webkit-scrollbar { display: none !important; }
  [data-sonner-toaster], [role="status"][class*="toast" i], [class*="toast" i] { display: none !important; }
`;
/** Replace anything that looks like a personal email address or phone number with an obvious example. */
const scrub = () => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const emailRe = /[\w.+-]+@[\w-]+(\.[\w-]+)+/g;
  const phoneRe = /(\+\d[\d ()-]{8,}\d|\b0\d{2}[\d ]{6,}\d)/g; // starts with + or 0: ISO dates and amounts are left alone
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.nodeValue ?? "";
    const clean = t.replace(emailRe, "name@example.com").replace(phoneRe, "07•• ••• •••");
    if (clean !== t) n.nodeValue = clean;
  }
  for (const el of document.querySelectorAll("input")) {
    if (/@/.test(el.value) && el.type !== "password") el.value = "name@example.com";
  }
};

// ---------------------------------------------------------------- run
function git(...args) {
  try { return execFileSync("git", args, { cwd: repo, encoding: "utf8" }).trim(); } catch { return ""; }
}
function newestMtime(dir) {
  let newest = 0;
  const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    if (e.name === "node_modules") continue;
    const f = path.join(d, e.name);
    if (e.isDirectory()) walk(f); else newest = Math.max(newest, fs.statSync(f).mtimeMs);
  } };
  walk(dir);
  return new Date(newest).toISOString();
}

const browser = await chromium.launch();
/** Sign in on a fresh page (the session token lives in the page, so every picture signs in itself) and wait for the app shell. */
async function signIn(page) {
  await page.goto(APP + "/");
  await page.locator('input[type="email"], input[name="login"], input[autocomplete="username"]').first().fill(EMAIL, { timeout: 60000 });
  await page.locator('input[type="password"]').first().fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).first().click();
  await page.locator('input[type="password"]').first().waitFor({ state: "detached", timeout: 60000 });
}

const manifestFile = path.join(out, "manifest.json");
const manifest = fs.existsSync(manifestFile) ? JSON.parse(fs.readFileSync(manifestFile, "utf8")) : { app: {}, screens: {} };
const commit = git("rev-parse", "--short", "HEAD");
const dirty = git("status", "--porcelain", "--", "frontend/src") !== "";
let failed = 0;

for (const s of shots) {
  if (only && !only.includes(s.key)) continue;
  const v = s.phone ? PHONE : DESKTOP;
  const ctx = await browser.newContext({ viewport: { width: v.width, height: v.height }, deviceScaleFactor: v.scale, locale: "en-GB", colorScheme: "light", isMobile: !!s.phone, hasTouch: !!s.phone });
  const page = await ctx.newPage();
  try {
    await signIn(page);
    await page.goto(APP + s.route);
    await settle(page);
    await page.waitForTimeout(s.wait ?? 1500);
    await page.addStyleTag({ content: CSS });
    if (s.pre) await s.pre(page);
    await page.addStyleTag({ content: CSS });
    await page.evaluate(scrub);
    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    const png = await page.screenshot({ ...(s.clip ? { clip: s.clip } : {}) });
    const file = path.join(out, `${s.key}.webp`);
    await sharp(png).webp({ quality: 88, effort: 5 }).toFile(file);
    const meta = await sharp(file).metadata();
    manifest.screens[s.key] = {
      route: new URL(page.url()).pathname.replace(/\/[0-9a-f]{8}-[0-9a-f-]{27}/g, "/:id"),
      captured: new Date().toISOString(),
      viewport: `${v.width}x${v.height}@${v.scale}x`,
      size: `${meta.width}x${meta.height}`,
      appCommit: commit + (dirty ? "+uncommitted" : ""),
      frontendSrcNewest: newestMtime(path.join(repo, "frontend/src")),
    };
    console.log("captured", s.key, manifest.screens[s.key].route, manifest.screens[s.key].size);
  } catch (e) {
    failed++;
    console.error("FAILED", s.key, String(e).split("\n")[0]);
  }
  await ctx.close();
}
await browser.close();

manifest.app = { commit, uncommittedFrontend: dirty, appUrl: "(local demo business)" };
fs.writeFileSync(manifestFile, JSON.stringify(manifest, null, 2) + "\n");
if (failed) process.exit(1);
