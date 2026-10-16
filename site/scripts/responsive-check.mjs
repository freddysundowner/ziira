// npm run responsive: layout checks on the built site at phone, tablet and desktop widths with touch emulation.
// Fails on horizontal page overflow, elements that stick out of the viewport (clipped or overlapping text), and tap targets under 44px.
// Uses Playwright from ../e2e/node_modules (run `make e2e-setup` once). Needs `npm run build` first. RESP_PAGES / RESP_WIDTHS override the lists.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { serve } from "./lib/static-server.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
let chromium;
try { chromium = createRequire(path.resolve(here, "../../e2e/package.json"))("playwright").chromium; } catch { console.log("responsive: Playwright not installed (run `make e2e-setup`); skipped"); process.exit(0); }

const dist = path.resolve(here, "../dist");
const helpGuide = fs.existsSync(path.join(dist, "help")) ? fs.readdirSync(path.join(dist, "help")).find((d) => fs.existsSync(path.join(dist, "help", d, "index.html")) && !["a-z"].includes(d)) : null;
const PAGES = (process.env.RESP_PAGES ?? ["/", "/product/", "/product/pos-and-till/", "/intelligence/how-it-works/", "/intelligence/complete-guide/", "/solutions/", "/integrations/", "/pricing/", "/get-started/", "/guides/", "/guides/cashier-voids-discount-abuse/", "/glossary/", "/privacy-policy/", "/security-and-privacy/", "/help/", helpGuide ? `/help/${helpGuide}/` : "", "/404.html"].join(",")).split(",").filter(Boolean);
const WIDTHS = (process.env.RESP_WIDTHS ?? "320,360,375,390,414,600,768,1024").split(",").map(Number);
const MIN_TAP = 44;

const TAP = ".btn, .btn-link, .nav-button, .nav-link, .menu-item, .menu-foot, .acc-btn, .site-footer li a, .app, .pick, .card-link, .int-card, summary, input:not([type=hidden]):not(.nav-toggle):not(.acc), textarea, select, button, .help-side a, .help-toc a, .help-card, .help-start-list a, .help-pager a, .more-link, .toc-inline a, .toc-inline summary, .g-pager a, .g-go a";

/** Runs in the page: returns the problems found. */
function audit({ tap, min, openMenu }) {
  const out = [];
  const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > vw + 1) out.push(`page scrolls horizontally (${document.documentElement.scrollWidth} > ${vw})`);
  const visible = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none"; };
  const inScroller = (el) => { for (let p = el.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if ((o === "auto" || o === "scroll") && p !== document.documentElement && p !== document.body) return true; if (getComputedStyle(p).position === "fixed" && p.classList.contains("help-shot")) return true; } return false; };
  const clippedByAncestor = (el) => { for (let p = el.parentElement; p; p = p.parentElement) { const cs = getComputedStyle(p); if (cs.overflowX === "hidden" || cs.overflow === "clip" || cs.overflowX === "clip") { const r = p.getBoundingClientRect(); if (r.right <= vw + 1) return true; } } return false; };
  for (const el of document.querySelectorAll("body *")) {
    if (!visible(el) || el.closest(".sr-only, svg, .hp, .skip")) continue;
    const r = el.getBoundingClientRect();
    if ((r.right > vw + 1 || r.left < -1) && !inScroller(el)) {
      const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (hasText || el.matches("img, picture, button, a, input")) out.push(`sticks out of the screen: <${el.tagName.toLowerCase()} class="${el.className}"> ${(el.textContent || "").trim().slice(0, 40)}`);
    }
    // text that does not fit its own box
    if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflowX === "visible" && el.children.length === 0 && el.clientWidth > 0 && !inScroller(el)) {
      const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (hasText) out.push(`text overflows its box: <${el.tagName.toLowerCase()} class="${el.className}"> ${(el.textContent || "").trim().slice(0, 40)}`);
    }
  }
  for (const el of document.querySelectorAll(tap)) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (el.matches(".acc-btn") && r.width < min) out.push(`tap target too small: acc-btn ${Math.round(r.width)}x${Math.round(r.height)}`);
    else if (r.height < min - 0.5 || (r.width < min - 0.5 && el.matches(".btn, .nav-button, button, input, textarea"))) out.push(`tap target too small: <${el.tagName.toLowerCase()} class="${el.className}"> "${(el.textContent || "").trim().slice(0, 30)}" ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  return out;
}

const srv = await serve(dist);
const browser = await chromium.launch();
let problems = 0, runs = 0;
const report = (label, list) => { const seen = new Set(); for (const m of list) { if (seen.has(m)) continue; seen.add(m); problems++; console.error(`[${label}] ${m}`); } };

const contexts = [
  ...WIDTHS.map((w) => ({ name: `${w}px`, opts: { viewport: { width: w, height: w >= 768 ? 900 : 780 }, isMobile: w < 1024, hasTouch: w < 1024, deviceScaleFactor: 2 }, phone: w < 1100 })),
  { name: "landscape 812x375", opts: { viewport: { width: 812, height: 375 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }, phone: true },
  { name: "landscape 667x375", opts: { viewport: { width: 667, height: 375 }, isMobile: true, hasTouch: true }, phone: true },
];
for (const c of contexts) {
  const ctx = await browser.newContext(c.opts);
  for (const p of PAGES) {
    const page = await ctx.newPage();
    await page.goto(`http://127.0.0.1:${srv.port}${p}`, { waitUntil: "networkidle" });
    report(`${c.name} ${p}`, await page.evaluate(audit, { tap: TAP, min: MIN_TAP }));
    runs++;
    if (c.phone && p === "/") {
      // the open phone menu, with the first accordion expanded
      if (await page.locator("label.nav-button").isVisible()) {
        await page.click("label.nav-button");
        await page.check(".acc >> nth=0", { force: true });
        report(`${c.name} ${p} (menu open)`, await page.evaluate(audit, { tap: TAP, min: MIN_TAP }));
        const first = page.locator(".nav .menu-item").first();
        const h = await page.evaluate(() => document.querySelector(".nav").scrollWidth > document.querySelector(".nav").clientWidth + 1);
        if (h) report(`${c.name} (menu open)`, ["menu panel scrolls horizontally"]);
        await first.click();
        await page.waitForLoadState("networkidle");
        if (await page.evaluate(() => document.getElementById("nav-toggle")?.checked)) report(`${c.name} (menu)`, ["menu stays open after following a link"]);
        runs++;
      }
    }
    await page.close();
  }
  await ctx.close();
}
// Desktop dropdowns: no overflow, readable rows, keyboard access
for (const w of [1180, 1280, 1600]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: 800 } });
  const page = await ctx.newPage();
  await page.goto(`http://127.0.0.1:${srv.port}/`, { waitUntil: "networkidle" });
  const n = await page.locator(".nav-item:has(.menu)").count();
  for (let i = 0; i < n; i++) {
    const item = page.locator(".nav-item:has(.menu)").nth(i);
    await item.locator(".nav-link").hover();
    await page.waitForTimeout(350);
    const res = await item.evaluate((li) => {
      const m = li.querySelector(".menu"); const r = m.getBoundingClientRect(); const vw = document.documentElement.clientWidth; const out = [];
      if (getComputedStyle(m).visibility !== "visible") out.push("panel does not open on hover");
      if (r.left < 0 || r.right > vw) out.push(`panel leaves the screen (${Math.round(r.left)}..${Math.round(r.right)} of ${vw})`);
      if (r.bottom > innerHeight + 1 && getComputedStyle(m).overflowY === "visible") out.push("panel taller than the screen without scrolling");
      for (const b of m.querySelectorAll(".menu-item b")) { const lh = parseFloat(getComputedStyle(b).lineHeight) || 20; if (b.getBoundingClientRect().height > lh * 2 + 2) out.push(`title wraps to more than 2 lines: ${b.textContent}`); if (b.getBoundingClientRect().width < 100) out.push(`title column too narrow: ${b.textContent}`); }
      return out;
    });
    report(`${w}px dropdown ${i}`, res);
    runs++;
  }
  // keyboard: focus a top link, the panel opens, Tab reaches its first row, Escape closes
  await page.mouse.move(5, 500);
  await page.locator(".nav-item:has(.menu) .nav-link").first().focus();
  await page.waitForTimeout(300);
  await page.keyboard.press("Tab");
  await page.waitForTimeout(300);
  const opened = await page.evaluate(() => { const a = document.activeElement; const m = a.closest(".nav-item")?.querySelector(".menu"); return !!(m && getComputedStyle(m).visibility === "visible" && a.classList.contains("menu-item")); });
  if (!opened) report(`${w}px keyboard`, ["Tab from a top-level link does not reach the open panel"]);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  const closed = await page.evaluate(() => [...document.querySelectorAll(".menu")].every((m) => getComputedStyle(m).visibility === "hidden"));
  if (!closed) report(`${w}px keyboard`, ["Escape does not close the panel"]);
  await ctx.close();
}
await browser.close();
srv.close();
console.log(`responsive: ${PAGES.length} pages x ${contexts.length} sizes (${runs} runs), ${problems} problem(s)`);
process.exit(problems ? 1 : 0);
