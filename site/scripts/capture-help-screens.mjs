// Captures the annotated screenshots used by the Help guides (src/assets/help/*.png) from the running web app.
// Usage: APP_URL=http://localhost:5173 node scripts/capture-help-screens.mjs [--only key,key] [--list]
//   DEMO_EMAIL / DEMO_PASSWORD         the demo business (CLAUDE.md), used for list and report screens
//   HELP_SHOP_EMAIL / HELP_SHOP_PASSWORD   a scratch business that is walked through setting up and selling (see site/README.md)
// Every picture is demo data. Numbered circles are drawn into the picture at the places the guide's "legend" names, in order.
// Uses Playwright from ../e2e/node_modules (run `make e2e-setup` once) and sharp from this folder.
import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { shots } from "./help-screens.shots.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.resolve(here, "../../e2e/package.json"));
const { chromium } = require("playwright");

const APP = process.env.APP_URL ?? "http://localhost:5173";
const TENANTS = {
  demo: { email: process.env.DEMO_EMAIL ?? "owner@demo-hardware.test", password: process.env.DEMO_PASSWORD ?? "demo-pass-123" },
  shop: { email: process.env.HELP_SHOP_EMAIL ?? "owner@helpdoc-shop.test", password: process.env.HELP_SHOP_PASSWORD ?? "helpdoc-pass-123" },
};
const out = path.resolve(here, "../src/assets/help");
fs.mkdirSync(out, { recursive: true });
const arg = (n) => (process.argv.includes(n) ? process.argv[process.argv.indexOf(n) + 1] : null);
const only = arg("--only")?.split(",") ?? null;

if (process.argv.includes("--list")) { for (const s of shots) console.log(s.key, s.ten ?? "demo", s.url ?? "(signed out)"); process.exit(0); }

const VIEW = { width: 1280, height: 800 };
const SCALE = 2;

async function signIn(page, who) {
  await page.goto(APP + "/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="email"], input[autocomplete="username"]').first().fill(TENANTS[who].email);
  await page.locator('input[type="password"]').first().fill(TENANTS[who].password);
  await page.getByRole("button", { name: /sign in/i }).first().click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);
}

/** Draw numbered circles and a soft outline at each target; returns the union box (CSS pixels) of everything marked. */
async function annotate(page, targets) {
  const boxes = [];
  for (const t of targets) {
    await t.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
  }
  await page.waitForTimeout(250);
  for (const [i, t] of targets.entries()) {
    const b = await t.boundingBox({ timeout: 3000 }).catch(() => null);
    if (!b) throw new Error(`mark ${i + 1} not found`);
    boxes.push(b);
  }
  await page.evaluate((bs) => {
    const layer = document.createElement("div");
    layer.id = "help-marks";
    layer.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483647";
    bs.forEach((b, i) => {
      const box = document.createElement("div");
      box.style.cssText = `position:fixed;left:${b.x - 3}px;top:${b.y - 3}px;width:${b.width + 6}px;height:${b.height + 6}px;border:2px solid #d97706;border-radius:8px;box-shadow:0 0 0 3px rgba(217,119,6,.18)`;
      const dot = document.createElement("div");
      dot.textContent = String(i + 1);
      dot.style.cssText = `position:fixed;left:${Math.max(4, b.x - 16)}px;top:${Math.max(4, b.y - 16)}px;width:26px;height:26px;border-radius:50%;background:#d97706;color:#fff;font:700 14px/26px system-ui,sans-serif;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.4)`;
      layer.append(box, dot);
    });
    document.body.append(layer);
  }, boxes);
  const x0 = Math.min(...boxes.map((b) => b.x)), y0 = Math.min(...boxes.map((b) => b.y));
  const x1 = Math.max(...boxes.map((b) => b.x + b.width)), y1 = Math.max(...boxes.map((b) => b.y + b.height));
  return { x0, y0, x1, y1 };
}

const browser = await chromium.launch();
let failed = 0, done = 0;
const sessions = new Map(); // tenant -> {ctx,page}

async function pageFor(who) {
  if (who === "out") {
    const ctx = await browser.newContext({ viewport: VIEW, deviceScaleFactor: SCALE, colorScheme: "light", locale: "en-GB" });
    const pg = await ctx.newPage(); pg.setDefaultTimeout(8000); return { ctx, page: pg, temp: true };
  }
  if (!sessions.has(who)) {
    const ctx = await browser.newContext({ viewport: VIEW, deviceScaleFactor: SCALE, colorScheme: "light", locale: "en-GB" });
    const page = await ctx.newPage();
    page.setDefaultTimeout(8000);
    await signIn(page, who);
    sessions.set(who, { ctx, page });
  }
  return sessions.get(who);
}

for (const s of shots) {
  if (only && !only.includes(s.key)) continue;
  const who = s.ten ?? "demo";
  const { page, ctx, temp } = await pageFor(who);
  try {
    await page.goto(APP + (s.url ?? "/register"));
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(s.wait ?? 1400);
    if (s.pre) await s.pre(page);
    await page.waitForTimeout(500);
    const targets = s.marks.map((m) => m(page));
    const u = await annotate(page, targets);
    // crop: the marked region with room around it, never smaller than a readable block
    const pad = s.pad ?? 70;
    let w = Math.max(u.x1 - u.x0 + pad * 2, s.minW ?? 760), h = Math.max(u.y1 - u.y0 + pad * 2, s.minH ?? 380);
    w = Math.min(w, VIEW.width); h = Math.min(h, VIEW.height);
    let x = Math.max(0, Math.min(u.x0 - pad, VIEW.width - w)), y = Math.max(0, Math.min(u.y0 - pad, VIEW.height - h));
    if (s.clip) ({ x, y, width: w, height: h } = s.clip);
    const buf = await page.screenshot({ clip: { x, y, width: w, height: h } });
    const file = path.join(out, `${s.key}.png`);
    await sharp(buf).resize({ width: Math.min(1100, Math.round(w * SCALE)), withoutEnlargement: true }).png({ palette: true, quality: 82, effort: 8 }).toFile(file);
    await page.evaluate(() => document.getElementById("help-marks")?.remove());
    if (s.after) await s.after(page);
    console.log("captured", s.key, `${Math.round(w)}x${Math.round(h)}`, `${Math.round(fs.statSync(file).size / 1024)} KB`);
    done++;
  } catch (e) {
    failed++;
    console.error("FAILED", s.key, String(e.message).split("\n")[0].slice(0, 160));
    await page.screenshot({ path: path.join(here, `../.cache-help-fail-${s.key}.png`) }).catch(() => {});
  } finally {
    if (temp) await ctx.close();
  }
}
await browser.close();
console.log(`${done} captured, ${failed} failed`);
process.exit(failed ? 1 : 0);
