#!/usr/bin/env node
// Automatic responsive audit: visits every route a signed-in person can reach at phone/tablet/desktop widths and records
// layout defects (page scroll sideways, children sticking out of cards, clipped figures, overlapping text, small tap
// targets, fixed elements covering content). Writes docs/plans/responsive-audit.md + e2e/results/responsive/audit.json
// and screenshots (offenders outlined in red). Exit code 1 when defects (other than tap targets) exist.
//
//   make responsive-audit                       # against the running local stack (web :5173, API :8000)
//   node e2e/responsive-audit.mjs --only /jobs --widths 320,390 --max-routes 40
//   E2E_SERVE=1 bash e2e/run.sh   then   node e2e/responsive-audit.mjs --web http://localhost:4175 --account owner@x.test:password
//
// Options: --web URL  --widths 320,360,390,768,1280  --account email:password[:label] (repeatable; default the local demo
// owners demo-hardware and demo-gym)  --no-operator  --only SUBSTRING  --max-routes N (per account)  --concurrency N  --reuse (skip the crawl, use the last route list)
// Operator account: read from .dev-operator.local (gitignored); the password is never printed or written anywhere.
import { chromium } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const OUT = join(HERE, "results", "responsive");

// ---------- options ----------
const argv = process.argv.slice(2);
const opt = (name, fallback) => { const i = argv.indexOf(`--${name}`); return i >= 0 ? argv[i + 1] : fallback; };
const opts = (name) => argv.flatMap((a, i) => (a === `--${name}` ? [argv[i + 1]] : []));
const WEB = (opt("web", process.env.E2E_BASE_URL ?? "http://localhost:5173")).replace(/\/$/, "");
const WIDTHS = opt("widths", "320,360,390,768,1280").split(",").map(Number);
const ONLY = opt("only", "");
const MAX_ROUTES = Number(opt("max-routes", "400"));
const CONCURRENCY = Number(opt("concurrency", "4"));
const REUSE = argv.includes("--reuse");   // reuse the routes found by the last run (skips the crawl)
const DEMO_PASSWORD = process.env.ZIIRA_DEMO_PASSWORD ?? "demo-pass-123";   // documented in CLAUDE.md (demo data only)
let accounts = opts("account").map((a) => { const [email, password, label] = a.split(":"); return { email, password, label: label ?? email.split("@")[1] ?? email, kind: "business" }; });
if (!accounts.length) accounts = ["demo-hardware", "demo-gym"].map((code) => ({ email: `owner@${code}.test`, password: DEMO_PASSWORD, label: code, kind: "business" }));
if (!argv.includes("--no-operator") && existsSync(join(ROOT, ".dev-operator.local"))) {
  const text = readFileSync(join(ROOT, ".dev-operator.local"), "utf8");
  const get = (k) => text.match(new RegExp(`^${k}:\\s*(.+)$`, "m"))?.[1]?.trim();
  if (get("login") && get("password")) accounts.push({ email: get("login"), password: get("password"), label: "operator", kind: "operator" });
}
const PUBLIC_ROUTES = ["/register", "/forgot-password", "/reset-password?token=x", "/register/verify?token=x", "/confirm-email?token=x"];
const SKIP_HREF = /logout|sign-out|signout|\/api\/|^mailto:|^tel:|\.csv|\.pdf|download|\/print/i;

// ---------- the in-page audit ----------
/* eslint-disable */
function auditInPage() {
  const W = innerWidth, H = innerHeight;
  const defects = [];
  const cs = (el) => getComputedStyle(el);
  const visible = (el) => {
    try { if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false; } catch { /* old engine */ }
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const snippet = (el) => (el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title") || "").replace(/\s+/g, " ").trim().slice(0, 70);
  const path = (el) => {
    const parts = [];
    for (let n = el, d = 0; n && n.nodeType === 1 && n !== document.body && d < 5; n = n.parentElement, d++) {
      let s = n.tagName.toLowerCase();
      if (n.id) { parts.unshift(`${s}#${n.id}`); break; }
      const tid = n.getAttribute("data-testid");
      if (tid) { parts.unshift(`${s}[data-testid=${tid}]`); break; }
      const raw = [...n.classList].slice(0, 4).filter((c) => /^[\w\-.:/\[\]%]+$/.test(c));
      s += raw.map((c) => "." + c.replace(/[^\w-]/g, "\\$&")).join("");
      parts.unshift(s);
    }
    return parts.join(" > ");
  };
  const add = (kind, el, detail, extra = {}) => {
    el.setAttribute("data-ra-hit", "1");
    const r = el.getBoundingClientRect();
    defects.push({ kind, selector: path(el), text: snippet(el), rect: [Math.round(r.left), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)], detail, ...extra });
  };
  const all = [...document.body.querySelectorAll("*")].filter((el) => !el.closest("svg") || el.tagName.toLowerCase() === "svg");
  const vis = new Map();
  const isVis = (el) => { if (!vis.has(el)) vis.set(el, visible(el)); return vis.get(el); };
  const styleCache = new Map();
  const st = (el) => { let s = styleCache.get(el); if (!s) { s = cs(el); styleCache.set(el, s); } return s; };
  const isScrollX = (el) => /auto|scroll/.test(st(el).overflowX);
  const clips = (el) => /hidden|clip|auto|scroll/.test(st(el).overflowX) || /hidden|clip|auto|scroll/.test(st(el).overflowY);
  const fixedRoot = (el) => { for (let n = el; n && n !== document.body; n = n.parentElement) { if (st(n).position === "fixed") return n; } return null; };

  // (a) horizontal page scroll
  const docW = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  if (docW > W + 1) {
    const sticking = all.filter((el) => isVis(el) && !fixedRoot(el)).filter((el) => { const r = el.getBoundingClientRect(); return r.right > W + 1 || r.left < -1; })
      .filter((el) => { for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) if (isScrollX(n) || /hidden|clip/.test(st(n).overflowX)) return false; return true; });
    const set = new Set(sticking);
    const deepest = sticking.filter((el) => ![...el.children].some((c) => set.has(c)));
    deepest.sort((x, y) => y.getBoundingClientRect().right - x.getBoundingClientRect().right);
    defects.push({ kind: "page-scroll", selector: "html", text: "", rect: [0, 0, docW, 0], detail: `document is ${docW}px wide in a ${W}px window` });
    for (const el of deepest.slice(0, 6)) add("page-scroll", el, `reaches x=${Math.round(el.getBoundingClientRect().right)} (window ${W})`);
  }

  // (b) child sticks out of its card / panel
  const isContainer = (el) => {
    const s = st(el);
    const bw = parseFloat(s.borderTopWidth) + parseFloat(s.borderBottomWidth) + parseFloat(s.borderLeftWidth) + parseFloat(s.borderRightWidth);
    const rad = parseFloat(s.borderTopLeftRadius) > 0;
    const bg = s.backgroundColor && !/rgba\(0, 0, 0, 0\)|transparent/.test(s.backgroundColor);
    return bw > 0 || (rad && bg) || (s.boxShadow && s.boxShadow !== "none" && bg);
  };
  const containerOf = new Map();
  const container = (el) => {
    if (containerOf.has(el)) return containerOf.get(el);
    const p = el.parentElement; let c = null;
    if (p && p !== document.body && p !== document.documentElement) c = isContainer(p) ? p : container(p);
    containerOf.set(el, c); return c;
  };
  const sticks = new Map();
  for (const el of all) {
    if (!isVis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const c = container(el);
    if (!c) continue;
    let skip = false;
    for (let n = el; n && n !== c.parentElement; n = n.parentElement) {
      const s = st(n);
      if (s.position === "absolute" || s.position === "fixed" || s.position === "sticky") { skip = true; break; }
      if (isScrollX(n)) { skip = true; break; }
    }
    if (skip) continue;
    const cr = c.getBoundingClientRect();
    if (r.right > cr.right + 2 || r.left < cr.left - 2) sticks.set(el, { c, over: Math.round(Math.max(r.right - cr.right, cr.left - r.left)) });
  }
  for (const [el, { c, over }] of sticks) {
    const p = el.parentElement;
    if (p && p !== c && sticks.get(p)?.c === c) continue;   // report the outermost only
    const clipped = (() => { for (let n = el.parentElement; n && n !== c.parentElement; n = n.parentElement) if (/hidden|clip/.test(st(n).overflowX)) return true; return false; })();
    add("sticks-out", el, `${over}px outside its card ${path(c).split(" > ").slice(-1)[0]}${clipped ? " (clipped)" : ""}`, { container: path(c) });
  }

  // (c) text overflow / clipped figures
  const figureLike = (t) => { const s = t.replace(/\s/g, ""); return s.length > 0 && (s.replace(/\D/g, "").length / s.length) >= 0.35; };
  for (const el of all) {
    if (!isVis(el)) continue;
    const s = st(el);
    if (s.display === "inline" || s.display === "contents") continue;
    if (/auto|scroll/.test(s.overflowX)) continue;
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    if (el.clientWidth < 1 || el.scrollWidth <= el.clientWidth + 1) continue;
    if (el.matches("input,textarea,select")) continue;
    const text = snippet(el);
    const ellipsis = s.textOverflow === "ellipsis" && /hidden|clip/.test(s.overflowX);
    if (ellipsis && !figureLike(text)) continue;   // an ellipsis on a name is by design
    add("text-overflow", el, `${ellipsis ? "figure cut by ellipsis" : /hidden|clip/.test(s.overflowX) ? "clipped" : "spills out of its box"}: content ${el.scrollWidth}px in ${el.clientWidth}px`);
  }

  // (d) overlapping text
  const lines = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement;
    if (!el || /^(script|style|noscript|option)$/i.test(el.tagName) || !isVis(el) || el.closest("[aria-hidden=true],[hidden],.sr-only")) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    const rects = [...range.getClientRects()].filter((r) => r.width > 1 && r.height > 1);
    for (const r0 of rects) {
      let r = { left: r0.left, right: r0.right, top: r0.top, bottom: r0.bottom };
      for (let a = el; a && a !== document.body && r; a = a.parentElement) {
        if (!clips(a)) continue;
        const ar = a.getBoundingClientRect();
        r = { left: Math.max(r.left, ar.left), right: Math.min(r.right, ar.right), top: Math.max(r.top, ar.top), bottom: Math.min(r.bottom, ar.bottom) };
        if (r.right - r.left < 1 || r.bottom - r.top < 1) r = null;
      }
      if (r) lines.push({ el, node: n, ...r, root: fixedRoot(el), text: n.textContent.trim().slice(0, 40) });
    }
  }
  lines.sort((x, y) => x.top - y.top);
  const seen = new Set();
  let overlaps = 0;
  for (let i = 0; i < lines.length && overlaps < 40; i++) {
    const a = lines[i];
    for (let j = i + 1; j < lines.length && lines[j].top < a.bottom - 1; j++) {
      const b = lines[j];
      if (a.node === b.node || a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el) || a.root !== b.root) continue;
      const ix = Math.min(a.right, b.right) - Math.max(a.left, b.left), iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (ix < 4 || iy < 4 || iy < 0.5 * Math.min(a.bottom - a.top, b.bottom - b.top)) continue;
      const key = path(a.el) + "|" + path(b.el);
      if (seen.has(key)) continue; seen.add(key); overlaps++;
      a.el.setAttribute("data-ra-hit", "1"); b.el.setAttribute("data-ra-hit", "1");
      defects.push({ kind: "text-overlap", selector: path(a.el), text: a.text, rect: [Math.round(a.left), Math.round(a.top + scrollY), Math.round(a.right - a.left), Math.round(a.bottom - a.top)],
        detail: `overlaps "${b.text}" (${path(b.el)}) by ${Math.round(ix)}x${Math.round(iy)}px`, other: path(b.el) });
    }
  }

  // (e) small tap targets (phones, report only)
  if (W <= 430) {
    const sel = "a[href],button,[role=button],[role=tab],[role=menuitem],[role=option],summary,select,input:not([type=hidden]):not([type=checkbox]):not([type=radio])";
    let n = 0;
    for (const el of document.body.querySelectorAll(sel)) {
      if (!isVis(el) || el.disabled) continue;
      const r = el.getBoundingClientRect();
      if (st(el).display === "inline" && el.tagName === "A") continue;   // links inside a sentence
      if (r.height >= 36 || r.width < 2 || el.closest(".sr-only")) continue;
      if (n++ < 25) add("tap-target", el, `${Math.round(r.width)}x${Math.round(r.height)}px`, { reportOnly: true });
    }
  }

  // (f) fixed elements: covering content, or covering each other
  const fixedTop = all.filter((el) => st(el).position === "fixed" && isVis(el)).filter((el) => !el.parentElement || !fixedRoot(el.parentElement));
  // a click-through layer (pointer-events: none) is judged by the clickable things inside it
  const fixed = fixedTop.flatMap((f) => st(f).pointerEvents !== "none" ? [f] : [...f.querySelectorAll("*")].filter((c) => isVis(c) && st(c).pointerEvents !== "none" && (st(c.parentElement).pointerEvents === "none" || c.parentElement === f)));
  const interesting = [...document.body.querySelectorAll("a[href],button,input,select,textarea,[role=tab]")].filter(isVis);
  const fixedInfo = [];
  for (const f of fixed) {
    const fr = f.getBoundingClientRect();
    if (fr.top <= 2 && fr.width >= 0.5 * W) continue;                     // a top bar: content starts below it
    if (fr.width * fr.height >= 0.8 * W * H) continue;                   // a full-screen layer (menu backdrop)
    if (f.matches("[role=dialog]") || f.querySelector("[role=dialog]")) continue;
    if (fr.left <= 0 && fr.height >= 0.8 * H && W >= 768) continue;     // the sidebar (content has its margin)
    const covered = new Set();
    const test = (el, r) => {
      if (f.contains(el) || fixedRoot(el)) return;
      const x1 = Math.max(fr.left, r.left), x2 = Math.min(fr.right, r.right), y1 = Math.max(fr.top, r.top), y2 = Math.min(fr.bottom, r.bottom);
      if (x2 - x1 < 4 || y2 - y1 < 4 || y2 <= 0 || y1 >= H) return;
      const hit = document.elementFromPoint((x1 + x2) / 2, Math.min(H - 1, (y1 + y2) / 2));
      if (hit && f.contains(hit)) covered.add(el);
    };
    for (const el of interesting) { const r = el.getBoundingClientRect(); if (r.top < H && r.bottom > 0) test(el, r); }
    for (const l of lines) if (l.top < H && l.bottom > 0) test(l.el, l);
    const rect = f.getBoundingClientRect();
    fixedInfo.push({ selector: path(f), text: snippet(f), rect: [rect.left, rect.top, rect.right, rect.bottom], n: covered.size, covered: [...covered].slice(0, 4).map((e) => ({ selector: path(e), text: snippet(e) })) });
  }
  return { defects, fixedInfo, docW, W, H, scrollMax: Math.max(0, document.documentElement.scrollHeight - H) };
}
/* eslint-enable */

// ---------- helpers ----------
const slug = (s) => s.replace(/^\//, "").replace(/[^\w]+/g, "-").replace(/^-|-$/g, "") || "home";
const normal = (p) => p.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, ":id").replace(/\/\d{3,}(?=\/|$)/g, "/:id");
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => undefined);
  await page.waitForFunction(() => !document.querySelector('[class*="animate-pulse"]'), null, { timeout: 4000 }).catch(() => undefined);
  await pause(350);
}

async function signIn(page, acct) {
  const url = acct.kind === "operator" ? `${WEB}/operator` : `${WEB}/`;
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("input[type=password]", { timeout: 15000 });
  if (acct.kind === "operator") {
    await page.locator("input[type=email]").fill(acct.email);
    await page.locator("input[type=password]").fill(acct.password);
  } else {
    await page.locator("input[name=login]").fill(acct.email);
    await page.locator("input[name=password]").fill(acct.password);
  }
  await page.locator("button[type=submit]").click();
  await page.waitForSelector(acct.kind === "operator" ? "nav, main" : 'nav[aria-label="Main"]', { timeout: 20000 });
  await settle(page);
}

/** Open every collapsed menu section, then return every internal link on the page. */
async function links(page) {
  for (let i = 0; i < 4; i++) {
    const n = await page.evaluate(() => { const b = [...document.querySelectorAll('nav button[aria-expanded="false"], aside button[aria-expanded="false"]')]; b.forEach((x) => x.click()); return b.length; });
    if (!n) break;
    await pause(150);
  }
  return page.evaluate(() => [...document.querySelectorAll("a[href]")].filter((a) => !a.hasAttribute("download") && a.target !== "_blank")
    .map((a) => { try { const u = new URL(a.getAttribute("href"), location.href); return u.origin === location.origin ? u.pathname + u.search : null; } catch { return null; } }).filter(Boolean));
}

async function discover(page, acct, seeds) {   // always crawls everything; --only filters afterwards
  const found = new Map();
  const queue = [...seeds];
  const patterns = new Set();
  const add = (p, kind = "link") => {
    if (SKIP_HREF.test(p) || /^\/(book|job-approval|claim-response|confirm-email|register|forgot-password|reset-password)/.test(p)) return;
    if (acct.kind === "operator" ? !p.startsWith("/operator") : p.startsWith("/operator")) return;
    const pat = normal(p);
    if (patterns.has(pat)) return;
    patterns.add(pat);
    found.set(p, { path: p, kind });
    queue.push(p);
  };
  for (const s of seeds) { patterns.add(normal(s)); found.set(s, { path: s, kind: "link" }); }
  const visited = new Set();
  while (queue.length && found.size < MAX_ROUTES) {
    const p = queue.shift();
    if (visited.has(p)) continue; visited.add(p);
    try {
      await page.goto(`${WEB}${p}`, { waitUntil: "domcontentloaded" });
      await settle(page);
      for (const h of await links(page)) add(h);
      const row = page.locator("tbody tr[class*=cursor-pointer]").first();
      if (await row.count()) {
        const before = page.url();
        await row.click({ timeout: 3000 }).catch(() => undefined);
        await pause(600);
        if (page.url() !== before) { const u = new URL(page.url()); add(u.pathname + u.search, "detail"); }
      }
    } catch (e) { console.error(`  discovery failed at ${p}: ${String(e).split("\n")[0]}`); }
  }
  return [...found.values()].slice(0, MAX_ROUTES);
}

// module of a route, from the web modules' own route tables
function routeIndex() {
  const dir = join(ROOT, "frontend", "src", "modules");
  const out = [];
  for (const m of readdirSync(dir, { withFileTypes: true })) {
    if (!m.isDirectory()) continue;
    const f = join(dir, m.name, "module.ts");
    if (!existsSync(f)) continue;
    const text = readFileSync(f, "utf8");
    for (const g of text.matchAll(/path:\s*"([^"]+)",\s*page:\s*\(\)\s*=>\s*import\("([^"]+)"\)/g)) {
      const re = new RegExp("^" + g[1].replace(/:[\w]+/g, "[^/]+").replace(/\//g, "\\/") + "$");
      out.push({ re, module: m.name, file: `frontend/src/modules/${m.name}/${g[2].replace(/^\.\//, "")}.tsx` });
    }
  }
  return out;
}
const INDEX = routeIndex();
function whereIs(p, kind) {
  const pathname = p.split("?")[0].split("#")[0];
  if (kind === "operator") return { module: "operator", file: `frontend/src/operator/pages (${pathname})` };
  if (kind === "public") return { module: "auth / sign-up", file: "frontend/src/shell (SignIn, Register, register/*)" };
  if (pathname === "/") return { module: "shell/home", file: "frontend/src/shell/Home.tsx" };
  const hit = INDEX.find((r) => r.re.test(pathname));
  return hit ? { module: hit.module, file: hit.file } : { module: "shell", file: "frontend/src/shell" };
}

// ---------- audit one route at one width ----------
async function auditRoute(page, route, width, acct, results, log) {
  const full = route.path;
  await page.setViewportSize({ width, height: width >= 768 ? 900 : 800 });
  try {
    await page.goto(`${WEB}${full}`, { waitUntil: "domcontentloaded" });
  } catch (e) { log(`  goto failed ${full} @${width}: ${String(e).split("\n")[0]}`); return; }
  await settle(page);
  let variants = [{ label: "", run: async () => undefined }];
  if (route.openMenu) {
    if (width >= 768) return;
    variants = [{ label: "#menu", run: async () => { await page.locator('button[aria-label="Menu"]').first().click({ timeout: 3000 }).catch(() => undefined); await pause(400); } }];
  } else {
    const tabs = await page.locator("[role=tab]:not([aria-selected=true])").evaluateAll((els) => els.slice(0, 6).map((e) => e.textContent.trim().slice(0, 40)));
    for (const t of tabs) variants.push({ label: `#tab:${t}`, run: async () => { await page.locator("[role=tab]", { hasText: t }).first().click({ timeout: 3000 }).catch(() => undefined); await settle(page); } });
  }
  for (const v of variants) {
    await v.run();
    let data;
    try { data = await page.evaluate(auditInPage); } catch (e) { log(`  audit failed ${full}${v.label} @${width}: ${String(e).split("\n")[0]}`); continue; }
    const defects = [...data.defects];
    const fixedCover = (f, at) => ({ kind: "fixed-cover", selector: f.selector, text: f.text, rect: [], detail: `${at}: covers ${f.n} element(s): ${f.covered.map((c) => `"${c.text}" (${c.selector.split(" > ").slice(-1)[0]})`).slice(0, 3).join(", ")}` });
    if (data.scrollMax <= 0) for (const f of data.fixedInfo) if (f.n) defects.push(fixedCover(f, "page too short to scroll it away"));
    if (data.scrollMax > 0 && data.fixedInfo.length) {   // a floating button must not hide the last rows
      await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight)); await pause(200);
      const end = await page.evaluate(auditInPage);
      for (const f of end.fixedInfo) if (f.n) defects.push(fixedCover(f, "end of page"));
      await page.evaluate(() => scrollTo(0, 0));
    }
    const fe = data.fixedInfo;
    for (let i = 0; i < fe.length; i++) for (let j = i + 1; j < fe.length; j++) {
      const a = fe[i].rect, b = fe[j].rect;
      const ix = Math.min(a[2], b[2]) - Math.max(a[0], b[0]), iy = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
      if (ix > 6 && iy > 6) defects.push({ kind: "fixed-cover", selector: fe[i].selector, text: fe[i].text, rect: [], detail: `overlaps another fixed element "${fe[j].text}" (${fe[j].selector}) by ${Math.round(ix)}x${Math.round(iy)}px` });
    }
    const real = defects.filter((d) => !d.reportOnly);
    let shot = "";
    if (defects.length) {
      shot = `${acct.label}__${slug(full)}${v.label ? "__" + slug(v.label) : ""}__${width}.png`;
      await page.addStyleTag({ content: "[data-ra-hit]{outline:2px solid #ff1744 !important;outline-offset:-2px}" }).catch(() => undefined);
      await page.screenshot({ path: join(OUT, shot), fullPage: true }).catch(() => { shot = ""; });
    }
    results.push({ account: acct.label, route: full + v.label, width, kind: route.kind, ...whereIs(full, acct.kind === "operator" ? "operator" : route.kind), count: real.length, tapCount: defects.length - real.length, shot, defects });
    await page.evaluate(() => document.querySelectorAll("[data-ra-hit]").forEach((e) => e.removeAttribute("data-ra-hit")));
  }
}

// ---------- report ----------
function writeReport(results, startedAt) {
  const KINDS = { "page-scroll": "page scrolls sideways", "sticks-out": "sticks out of its card", "text-overflow": "text/figure overflow", "text-overlap": "overlapping text", "fixed-cover": "fixed element covers content" };
  const real = results.flatMap((r) => r.defects.filter((d) => !d.reportOnly).map((d) => ({ ...d, r })));
  const taps = results.flatMap((r) => r.defects.filter((d) => d.reportOnly).map((d) => ({ ...d, r })));
  const byModule = new Map();
  for (const d of real) { const k = `${d.r.account} / ${d.r.module}`; (byModule.get(k) ?? byModule.set(k, []).get(k)).push(d); }
  const tapByModule = new Map();
  for (const d of taps) tapByModule.set(d.r.module, (tapByModule.get(d.r.module) ?? 0) + 1);
  const L = [];
  L.push("# Responsive audit", "", `Generated by \`make responsive-audit\` (\`e2e/responsive-audit.mjs\`) on ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC, ${Math.round((Date.now() - startedAt) / 1000)} s.`,
    `Widths: ${WIDTHS.join(", ")} px. Pages audited: ${new Set(results.map((r) => `${r.account}${r.route}`)).size} (${results.length} page-width visits). Screenshots (offenders outlined red): \`e2e/results/responsive/\`. Full details: \`e2e/results/responsive/audit.json\`.`, "");
  L.push(`**Defects: ${real.length}** (${Object.keys(KINDS).map((k) => `${KINDS[k]}: ${real.filter((d) => d.kind === k).length}`).join("; ")}). Small tap targets (report only): ${taps.length}.`, "");
  L.push("## How to read", "", "- *sticks out*: a child's box is wider than the nearest bordered/rounded container (not inside an `overflow-x:auto` wrapper). *text-overflow*: an element's content is wider than the element (clipped, spilling, or a figure cut with an ellipsis). *overlapping text*: two unrelated text boxes intersect. *fixed cover*: a fixed element (floating button, banner) sits over text or a control, or over another fixed element.",
    "- Selectors are short paths (tag.class chain, up to 5 levels). The file is a guess from the route table (`module.ts`); shared-kit components are in `frontend/src/sdk/ui/` and `frontend/src/shell/`.", "");
  const sel = new Map();
  for (const d of real) { const k = `${d.kind} | ${d.selector.split(" > ").slice(-2).join(" > ")}`; const e = sel.get(k) ?? { n: 0, pages: new Set(), sample: d }; e.n++; e.pages.add(d.r.account + d.r.route); sel.set(k, e); }
  const topSel = [...sel.entries()].sort((a, b) => b[1].pages.size - a[1].pages.size || b[1].n - a[1].n).slice(0, 25);
  L.push("## Most repeated offenders (shared parts first)", "", "| Pages | Visits | Kind | Selector | Text | Example |", "|---|---|---|---|---|---|");
  for (const [k, e] of topSel) L.push(`| ${e.pages.size} | ${e.n} | ${k.split(" | ")[0]} | \`${k.split(" | ")[1].replace(/\|/g, "/")}\` | ${e.sample.text.replace(/\|/g, "/").slice(0, 40)} | ${e.sample.r.shot} |`);
  L.push("", "## Summary by module (worst first)", "", "| Account / module | Defects | Pages affected | Worst width |", "|---|---|---|---|");
  const rows = [...byModule.entries()].sort((a, b) => b[1].length - a[1].length);
  for (const [k, ds] of rows) {
    const byW = new Map(); for (const d of ds) byW.set(d.r.width, (byW.get(d.r.width) ?? 0) + 1);
    const worst = [...byW.entries()].sort((a, b) => b[1] - a[1])[0];
    L.push(`| ${k} | ${ds.length} | ${new Set(ds.map((d) => d.r.route)).size} | ${worst[0]} px (${worst[1]}) |`);
  }
  L.push("");
  for (const [k, ds] of rows) {
    L.push(`## ${k}`, "", `Files (guess): ${[...new Set(ds.map((d) => d.r.file))].slice(0, 6).map((f) => `\`${f}\``).join(", ")}`, "");
    const pages = new Map();
    for (const d of ds) (pages.get(d.r.route) ?? pages.set(d.r.route, []).get(d.r.route)).push(d);
    for (const [route, pd] of [...pages.entries()].sort((a, b) => b[1].length - a[1].length)) {
      L.push(`### \`${route}\` (${pd.length})`, "");
      const seen = new Set();
      const norm = (d) => `${d.kind}|${d.selector}|${d.detail.replace(/\d+/g, "#")}`;
      for (const d of pd.sort((a, b) => a.r.width - b.r.width)) {
        if (seen.has(norm(d))) continue; seen.add(norm(d));
        const widths = [...new Set(pd.filter((x) => norm(x) === norm(d)).map((x) => x.r.width))].sort((a, b) => a - b);
        L.push(`- **${d.kind}** @${widths.join("/")}px: \`${d.selector}\`${d.text ? ` "${d.text}"` : ""} - ${d.detail} [${d.r.shot}]`);
      }
      L.push("");
    }
  }
  if (taps.length) {
    L.push("## Small tap targets (under 36 px high, phone widths; report only)", "", "| Module | Count |", "|---|---|");
    for (const [m, n] of [...tapByModule.entries()].sort((a, b) => b[1] - a[1])) L.push(`| ${m} | ${n} |`);
    L.push("", "Examples:", "");
    const seen = new Set();
    for (const d of taps) { const key = d.selector.split(" > ").slice(-2).join(" > "); if (seen.has(key) || seen.size >= 15) continue; seen.add(key); L.push(`- \`${d.selector}\` "${d.text}" ${d.detail} on \`${d.r.route}\` @${d.r.width}px`); }
    L.push("");
  }
  return L.join("\n");
}

// ---------- main ----------
async function main() {
  const startedAt = Date.now();
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const results = [];
  const log = (m) => console.log(m);
  const work = async (acct, routes, ctx) => {
    const pages = await Promise.all(Array.from({ length: CONCURRENCY }, () => ctx.newPage()));
    const tasks = routes.flatMap((r) => WIDTHS.map((w) => ({ r, w })));
    let i = 0;
    await Promise.all(pages.map(async (page) => {
      while (i < tasks.length) { const t = tasks[i++]; await auditRoute(page, t.r, t.w, acct, results, log); }
    }));
    await Promise.all(pages.map((p) => p.close()));
  };
  {   // signed-out screens (sign-in, sign-up, password reset)
    const ctx = await browser.newContext();
    const routes = [{ path: "/", kind: "public" }, ...PUBLIC_ROUTES.map((p) => ({ path: p, kind: "public" }))].filter((r) => !ONLY || r.path.includes(ONLY));
    log(`public: ${routes.length} screens`);
    await work({ label: "public", kind: "public" }, routes, ctx);
    await ctx.close();
  }
  for (const acct of accounts) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    try { await signIn(page, acct); } catch (e) { log(`!! cannot sign in ${acct.label}: ${String(e).split("\n")[0]} (skipped)`); await ctx.close(); continue; }
    const cache = join(HERE, "results", `routes-${acct.label}.json`);
    let routes;
    if (REUSE && existsSync(cache)) routes = JSON.parse(readFileSync(cache, "utf8")).filter((r) => !ONLY || r.path.includes(ONLY));
    else { routes = await discover(page, acct, [acct.kind === "operator" ? "/operator" : "/"]); mkdirSync(dirname(cache), { recursive: true }); writeFileSync(cache, JSON.stringify(routes)); routes = routes.filter((r) => !ONLY || r.path.includes(ONLY)); }
    await page.close();
    log(`${acct.label}: ${routes.length} routes (${routes.filter((r) => r.kind === "detail").length} detail pages)`);
    if (acct.kind !== "operator") routes.push({ path: "/", kind: "link", openMenu: true });   // the open phone menu is part of the shell
    await work(acct, routes, ctx);
    await ctx.close();
  }
  await browser.close();
  results.sort((a, b) => b.count - a.count);
  writeFileSync(join(OUT, "audit.json"), JSON.stringify({ generatedAt: new Date().toISOString(), web: WEB, widths: WIDTHS, results }, null, 1));
  mkdirSync(join(ROOT, "docs", "plans"), { recursive: true });
  writeFileSync(join(ROOT, "docs", "plans", "responsive-audit.md"), writeReport(results, startedAt));
  const kinds = {};
  for (const r of results) for (const d of r.defects) if (!d.reportOnly) kinds[d.kind] = (kinds[d.kind] ?? 0) + 1;
  const total = Object.values(kinds).reduce((a, b) => a + b, 0);
  console.log(`\n${results.length} page-width visits, ${total} defects`, kinds, "report: docs/plans/responsive-audit.md");
  process.exit(total > 0 ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
