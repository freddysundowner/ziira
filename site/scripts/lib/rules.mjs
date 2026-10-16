// The SEO audit: pure functions over a built folder (dist/). Every rule has a unit test with a deliberately broken fixture (tests/seo-rules.test.mjs).
import fs from "node:fs";
import path from "node:path";
import { load } from "cheerio";

export const LIMITS = { title: 60, descriptionMax: 160, descriptionMin: 50, htmlBytes: 80_000, longformHtmlBytes: 300_000, longformCssBytes: 80_000, jsBytes: 10_000, cssBytes: 66_000, imageFileBytes: 160_000, pageImageBytes: 700_000, guideMinWords: 900, guideMaxWords: 1800, helpMinSteps: 3, helpMinProblems: 1, helpMaxProblems: 3, helpMaxNext: 2 };
export const PLACEHOLDER_ORIGIN = /example\.(invalid|com|org|net)|localhost|127\.0\.0\.1/;

/** @typedef {{rule: string, page: string, message: string}} Issue */

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out); else out.push(p);
  }
  return out;
}

export function urlPathOf(dist, file) {
  const rel = "/" + path.relative(dist, file).split(path.sep).join("/");
  if (rel === "/404.html") return "/404/";
  return rel.replace(/index\.html$/, "");
}

/** Resolve an href found on `fromPath` to a clean site path, or null for external/non-navigational targets. */
export function resolveInternal(href, fromPath, siteOrigin) {
  if (!href || /^(mailto:|tel:|javascript:|data:)/.test(href)) return null;
  let u;
  try { u = new URL(href, "https://site.local" + fromPath); } catch { return { bad: true, href }; }
  const abs = /^https?:\/\//.test(href);
  if (abs) {
    if (!siteOrigin || u.origin !== new URL(siteOrigin).origin) return null;
  } else if (u.origin !== "https://site.local") return null;
  return { path: u.pathname, hash: u.hash.replace(/^#/, ""), search: u.search };
}

export function auditSite(dist, opts = {}) {
  /** @type {Issue[]} */
  const issues = [];
  const add = (rule, page, message) => issues.push({ rule, page, message });
  const only = opts.only ?? null; // optional set of rule names (e.g. links-only)
  const files = walk(dist);
  const htmlFiles = files.filter((f) => f.endsWith(".html") && !f.includes(`${path.sep}og${path.sep}`));
  const noindexAllowed = new Set(opts.noindexAllowed ?? []);
  const pages = new Map(); // urlPath -> { $, file, bytes, noindex }
  for (const f of htmlFiles) {
    const html = fs.readFileSync(f, "utf8");
    pages.set(urlPathOf(dist, f), { $: load(html), file: f, bytes: Buffer.byteLength(html), html });
  }
  const exists = (p) => fs.existsSync(path.join(dist, p));

  // site origin: option, else the home page canonical
  const homeCanon = pages.get("/")?.$('link[rel="canonical"]').attr("href");
  const siteOrigin = opts.siteUrl ?? (homeCanon ? new URL(homeCanon).origin : "");

  // ---- production guard
  if (opts.production && (!siteOrigin || PLACEHOLDER_ORIGIN.test(siteOrigin))) add("site-url", "(site)", `PUBLIC_SITE_URL is unset or a placeholder (${siteOrigin || "none"}) in production mode`);

  const titles = new Map(), descs = new Map();
  const inbound = new Map();
  for (const p of pages.keys()) inbound.set(p, new Set());
  const sitemapXml = exists("sitemap.xml") ? fs.readFileSync(path.join(dist, "sitemap.xml"), "utf8") : null;
  const sitemapUrls = new Map();
  if (sitemapXml) {
    for (const m of sitemapXml.matchAll(/<url>([\s\S]*?)<\/url>/g)) {
      const loc = /<loc>([^<]+)<\/loc>/.exec(m[1])?.[1];
      if (loc) sitemapUrls.set(loc, { lastmod: /<lastmod>([^<]+)<\/lastmod>/.exec(m[1])?.[1], alts: [...m[1].matchAll(/hreflang="([^"]+)" href="([^"]+)"/g)].map((a) => ({ lang: a[1], href: a[2] })) });
    }
  }
  const externalLinks = new Set();

  for (const [p, page] of pages) {
    const $ = page.$;
    const is404 = p === "/404/";
    const robots = ($('meta[name="robots"]').attr("content") ?? "").toLowerCase();
    const noindex = robots.includes("noindex");
    page.noindex = noindex;

    // ---- head basics
    const title = $("title").first().text().trim();
    const desc = ($('meta[name="description"]').attr("content") ?? "").trim();
    if (!title) add("title-missing", p, "no <title>");
    else {
      if (title.length > LIMITS.title) add("title-too-long", p, `title is ${title.length} chars (max ${LIMITS.title}): ${title}`);
      (titles.get(title) ?? titles.set(title, []).get(title)).push(p);
    }
    if (!desc) add("description-missing", p, "no meta description");
    else {
      if (desc.length > LIMITS.descriptionMax) add("description-too-long", p, `description is ${desc.length} chars (max ${LIMITS.descriptionMax})`);
      if (desc.length < LIMITS.descriptionMin) add("description-too-short", p, `description is ${desc.length} chars (min ${LIMITS.descriptionMin})`);
      (descs.get(desc) ?? descs.set(desc, []).get(desc)).push(p);
    }
    const canon = $('link[rel="canonical"]').attr("href");
    if (!canon) add("canonical-missing", p, "no canonical link");
    else if (siteOrigin && !is404 && canon !== siteOrigin + p) add("canonical-mismatch", p, `canonical ${canon} is not ${siteOrigin + p}`);
    if (noindex && !noindexAllowed.has(p)) add("noindex-unexpected", p, "page is noindex but is not in the allow-list");
    if (!$("html").attr("lang")) add("html-lang-missing", p, "<html> has no lang");
    if (!$('meta[name="viewport"]').length) add("viewport-missing", p, "no viewport meta");
    for (const prop of ["og:title", "og:description", "og:image", "og:url"]) if (!$(`meta[property="${prop}"]`).attr("content")) add("og-missing", p, `missing ${prop}`);
    if (!$('meta[name="twitter:card"]').attr("content")) add("og-missing", p, "missing twitter:card");
    const ogImage = $('meta[property="og:image"]').attr("content");
    if (ogImage && siteOrigin) {
      const op = ogImage.replace(siteOrigin, "");
      if (!exists(op)) add("og-image-missing", p, `og:image file not found: ${op}`);
    }

    // ---- headings
    const h1s = $("h1");
    if (h1s.length !== 1) add("h1-count", p, `${h1s.length} <h1> elements (need exactly 1)`);
    let prev = 0;
    $("h1,h2,h3,h4,h5,h6").each((_, el) => {
      const lvl = Number(el.tagName[1]);
      if (prev && lvl > prev + 1) add("heading-order", p, `heading level jumps from h${prev} to h${lvl}: ${$(el).text().trim().slice(0, 50)}`);
      prev = lvl;
    });
    const ids = new Set(); $("[id]").each((_, el) => { const id = $(el).attr("id"); if (ids.has(id)) add("duplicate-id", p, `duplicate id "${id}"`); ids.add(id); });
    page.ids = ids;
    if (!$("main").length) add("landmark-missing", p, "no <main>");
    if (!$("header").length || !$("footer").length) add("landmark-missing", p, "no <header>/<footer>");
    if (!$('a[href="#main"]').length) add("skip-link-missing", p, "no skip link");

    // ---- images
    let imgBytes = 0;
    $("img").each((_, el) => {
      const $el = $(el);
      if ($el.attr("alt") === undefined) add("img-alt-missing", p, `<img src="${$el.attr("src")}"> has no alt attribute`);
      if (!$el.attr("width") || !$el.attr("height")) add("img-dimensions-missing", p, `<img src="${$el.attr("src")}"> has no width/height`);
      const src = $el.attr("src");
      if (src && !/^https?:/.test(src) && !src.startsWith("data:")) {
        const sp = src.split("?")[0];
        if (exists(sp)) { const sz = fs.statSync(path.join(dist, sp)).size; imgBytes += sz; if (sz > LIMITS.imageFileBytes) add("budget-image", p, `${sp} is ${sz} bytes (max ${LIMITS.imageFileBytes})`); }
      }
    });
    if (imgBytes > LIMITS.pageImageBytes) add("budget-page-images", p, `images on the page weigh up to ${imgBytes} bytes (max ${LIMITS.pageImageBytes})`);

    // ---- weight
    // A page marked data-longform (the complete guide, which lists every check) may be larger; it is served compressed and has no heavy script.
    const htmlMax = $("[data-longform]").length ? LIMITS.longformHtmlBytes : LIMITS.htmlBytes;
    if (page.bytes > htmlMax) add("budget-html", p, `HTML is ${page.bytes} bytes (max ${htmlMax})`);
    let jsBytes = 0, cssBytes = 0;
    $("script[src]").each((_, el) => { const s = $(el).attr("src"); if (s && exists(s)) jsBytes += fs.statSync(path.join(dist, s)).size; });
    $('link[rel="stylesheet"]').each((_, el) => { const s = $(el).attr("href"); if (s && exists(s)) cssBytes += fs.statSync(path.join(dist, s)).size; });
    $("style").each((_, el) => { cssBytes += Buffer.byteLength($(el).text()); });
    if (jsBytes > LIMITS.jsBytes) add("budget-js", p, `JavaScript is ${jsBytes} bytes (max ${LIMITS.jsBytes})`);
    const cssMax = $("[data-longform]").length ? LIMITS.longformCssBytes : LIMITS.cssBytes; // the guide's own stylesheet is loaded on that page only
    if (cssBytes > cssMax) add("budget-css", p, `CSS is ${cssBytes} bytes (max ${cssMax})`);

    // ---- links
    const checkTarget = (href, kind) => {
      const r = resolveInternal(href, p, siteOrigin);
      if (r === null) { if (/^https?:\/\//.test(href ?? "")) externalLinks.add(href); return; }
      if (r.bad) return add("link-broken", p, `unparseable ${kind} ${href}`);
      let tp = r.path;
      const isAsset = path.extname(tp) !== "";
      if (kind === "a" && !isAsset && !tp.endsWith("/")) add("link-trailing-slash", p, `internal link ${href} lacks the trailing slash`);
      if (isAsset) { if (!exists(tp)) add("link-broken", p, `${kind} ${href} -> missing file ${tp}`); return; }
      const target = pages.get(tp.endsWith("/") ? tp : tp + "/");
      if (!target) return add("link-broken", p, `${kind} ${href} -> no page at ${tp}`);
      if (kind === "a") {
        if (target !== page) inbound.get(tp.endsWith("/") ? tp : tp + "/")?.add(p);
        if (r.hash && !(target === page ? ids : target.ids ?? ids).has(r.hash) && !load(target.html)(`[id="${r.hash}"], a[name="${r.hash}"]`).length) add("link-anchor-broken", p, `${href} -> no #${r.hash} on ${tp}`);
      }
    };
    $("a[href]").each((_, el) => { const h = $(el).attr("href"); if (h.startsWith("#")) { if (h.length > 1 && !$(`[id="${h.slice(1)}"]`).length) add("link-anchor-broken", p, `${h} not found on the page`); } else checkTarget(h, "a"); });
    $("img[src], script[src], source[srcset], link[href]").each((_, el) => {
      const $el = $(el);
      if (el.tagName === "source") { for (const part of ($el.attr("srcset") ?? "").split(",")) { const u = part.trim().split(/\s+/)[0]; if (u) checkTarget(u, "srcset"); } return; }
      const u = $el.attr("src") ?? $el.attr("href");
      if (el.tagName === "link" && ["canonical", "alternate"].includes($el.attr("rel"))) return;
      if (u) checkTarget(u, el.tagName);
    });
    $("a[href]").each((_, el) => { const t = $(el).text().trim(); const label = $(el).attr("aria-label"); if (!t && !label && !$(el).find("img,svg").length) add("link-text-empty", p, `link ${$(el).attr("href")} has no text`); if (/^(click here|read more|here|more)$/i.test(t)) add("link-text-generic", p, `generic anchor text "${t}" -> ${$(el).attr("href")}`); });

    // ---- JSON-LD
    const ld = $('script[type="application/ld+json"]');
    if (!is404 && !ld.length) add("jsonld-missing", p, "no JSON-LD");
    ld.each((_, el) => {
      let data;
      try { data = JSON.parse($(el).text()); } catch (e) { return add("jsonld-invalid", p, `JSON-LD does not parse: ${e.message}`); }
      if (data["@context"] !== "https://schema.org") add("jsonld-invalid", p, "JSON-LD @context is not https://schema.org");
      const nodes = data["@graph"] ?? [data];
      const types = nodes.map((n) => n["@type"]);
      for (const n of nodes) {
        if (!n["@type"]) add("jsonld-invalid", p, "a JSON-LD node has no @type");
        for (const bad of ["aggregateRating", "review", "offers", "reviewRating"]) if (n[bad] !== undefined) add("jsonld-fabricated", p, `JSON-LD ${n["@type"]} carries "${bad}": ratings, reviews and prices must not be invented`);
        if (n["@type"] === "WebSite" && n.potentialAction) add("jsonld-invalid", p, "WebSite has a SearchAction but the site has no search");
        if (n["@type"] === "SoftwareApplication" && n.applicationCategory !== "BusinessApplication") add("jsonld-invalid", p, "SoftwareApplication.applicationCategory must be BusinessApplication");
      }
      if (!is404 && !types.includes("Organization")) add("jsonld-invalid", p, "no Organization node");
      if (p !== "/" && !is404 && !types.includes("BreadcrumbList")) add("jsonld-invalid", p, "no BreadcrumbList on an inner page");
      if (types.includes("FAQPage")) { const q = nodes.find((n) => n["@type"] === "FAQPage").mainEntity?.length ?? 0; if (q !== $(".faq details").length) add("jsonld-faq-mismatch", p, `FAQPage lists ${q} questions but the page shows ${$(".faq details").length}`); }
      else if ($(".faq details").length) add("jsonld-faq-mismatch", p, "page shows an FAQ but has no FAQPage JSON-LD");
      if (/^\/guides\/[^/]+\/$/.test(p)) {
        const art = nodes.find((n) => n["@type"] === "BlogPosting");
        if (!art) add("jsonld-invalid", p, "guide has no BlogPosting");
        else for (const k of ["headline", "datePublished", "dateModified", "author", "image"]) if (!art[k]) add("jsonld-invalid", p, `BlogPosting lacks ${k}`);
      }
    });

    // ---- help guides (step-by-step how-to pages under /help/<journey>/<guide>/): numbered steps, pictures with alt, problems, next steps, HowTo data
    if ($("article[data-help-guide]").length) {
      const steps = $("article[data-help-guide] ol.help-steps > li");
      if (steps.length < LIMITS.helpMinSteps) add("help-steps-missing", p, `help guide has ${steps.length} numbered steps (need at least ${LIMITS.helpMinSteps})`);
      if ($("article[data-help-guide] .problem").length < LIMITS.helpMinProblems) add("help-problems-missing", p, `help guide lists ${$("article[data-help-guide] .problem").length} problems under "If something goes wrong" (need ${LIMITS.helpMinProblems} to ${LIMITS.helpMaxProblems})`);
      if ($("article[data-help-guide] .problem").length > LIMITS.helpMaxProblems) add("help-problems-missing", p, `help guide lists more than ${LIMITS.helpMaxProblems} problems`);
      if ($("article[data-help-guide] .help-next a[href]").length > LIMITS.helpMaxNext) add("help-next-missing", p, `help guide has more than ${LIMITS.helpMaxNext} "Next steps" links`);
      if (!$("article[data-help-guide] .help-next a[href]").length) add("help-next-missing", p, 'help guide has no "Next steps" link');
      let how = null;
      $('script[type="application/ld+json"]').each((_, el) => { try { const d = JSON.parse($(el).text()); for (const n of d["@graph"] ?? [d]) if (n["@type"] === "HowTo") how = n; } catch { /* reported by jsonld-invalid */ } });
      if (!how) add("help-howto-missing", p, "help guide has no HowTo JSON-LD");
      else {
        const hs = how.step ?? [];
        if (hs.length !== steps.length) add("help-howto-mismatch", p, `HowTo lists ${hs.length} steps but the page shows ${steps.length}`);
        if (hs.some((x) => x["@type"] !== "HowToStep" || !x.text || !x.name)) add("help-howto-mismatch", p, "a HowToStep lacks @type, name or text");
        if (!how.name || !how.totalTime) add("help-howto-mismatch", p, "HowTo lacks a name or totalTime");
      }
    }

    // ---- the complete guide's catalogue: every count on the page must equal the number of items actually listed
    const cat = $("[data-catalogue]");
    if (cat.length) {
      const listed = cat.find(".check").length;
      if (Number(cat.attr("data-total")) !== listed) add("catalogue-count", p, `the catalogue says ${cat.attr("data-total")} checks but lists ${listed}`);
      cat.find("[data-cat-group]").each((_, el) => { const n = $(el).find(".check").length; if (Number($(el).attr("data-count")) !== n) add("catalogue-count", p, `group ${$(el).attr("data-cat-group")} says ${$(el).attr("data-count")} but lists ${n}`); });
      $("[data-total-checks]").each((_, el) => { if (Number($(el).text().trim()) !== listed) add("catalogue-count", p, `the page states ${$(el).text().trim()} checks in total but lists ${listed}`); });
      const acts = $("[data-actions]"); if (acts.length && Number(acts.attr("data-actions")) !== acts.find(".action").length) add("catalogue-count", p, "the actions count differs from the actions listed");
    }

    // ---- guide length
    if (/^\/guides\/[^/]+\/$/.test(p)) {
      const words = $(".article").text().split(/\s+/).filter(Boolean).length;
      if (words < LIMITS.guideMinWords || words > LIMITS.guideMaxWords) add("guide-length", p, `guide has ${words} words (expected ${LIMITS.guideMinWords}-${LIMITS.guideMaxWords})`);
    }
    if (/lorem ipsum|TODO|FIXME|undefined|\[object Object\]/.test($("main").text())) add("placeholder-text", p, "visible text contains a placeholder (lorem/TODO/undefined/[object Object])");
  }

  for (const [t, list] of titles) if (list.length > 1) add("title-duplicate", list.join(" , "), `same title on ${list.length} pages: ${t}`);
  for (const [d, list] of descs) if (list.length > 1) add("description-duplicate", list.join(" , "), `same description on ${list.length} pages: ${d.slice(0, 60)}...`);

  // ---- orphans
  for (const [p, set] of inbound) if (p !== "/" && p !== "/404/" && set.size === 0) add("orphan-page", p, "no other page links to it");

  // ---- hreflang
  for (const [p, page] of pages) {
    const $ = page.$;
    const alts = $('link[rel="alternate"][hreflang]').map((_, el) => ({ lang: $(el).attr("hreflang"), href: $(el).attr("href") })).get();
    if (!alts.length) continue;
    const self = alts.find((a) => a.href === siteOrigin + p);
    if (!self) add("hreflang-self-missing", p, "hreflang set does not include the page itself");
    else if (self.lang !== $("html").attr("lang")) add("hreflang-lang-mismatch", p, `html lang ${$("html").attr("lang")} differs from its hreflang ${self.lang}`);
    if (!alts.some((a) => a.lang === "x-default")) add("hreflang-xdefault-missing", p, "no x-default");
    for (const a of alts) {
      const ap = siteOrigin ? a.href.replace(siteOrigin, "") : new URL(a.href).pathname;
      const target = pages.get(ap);
      if (!target) { add("hreflang-target-missing", p, `${a.lang} -> ${a.href} is not a page of the site`); continue; }
      if (a.lang === "x-default") continue;
      const back = target.$('link[rel="alternate"][hreflang]').map((_, el) => target.$(el).attr("href")).get();
      if (!back.includes(siteOrigin + p)) add("hreflang-not-reciprocal", p, `${a.href} does not list ${siteOrigin + p} back`);
    }
  }

  // ---- sitemap, robots and friends
  if (!sitemapXml) add("sitemap-missing", "/sitemap.xml", "no sitemap.xml");
  else {
    for (const [p, page] of pages) {
      const url = siteOrigin + p;
      if (p === "/404/") continue;
      if (!page.noindex && !sitemapUrls.has(url)) add("sitemap-missing-page", p, "indexable page is not listed in sitemap.xml");
      if (page.noindex && sitemapUrls.has(url)) add("sitemap-noindex-page", p, "noindex page is listed in sitemap.xml");
    }
    for (const [url, info] of sitemapUrls) {
      const p = siteOrigin ? url.replace(siteOrigin, "") : new URL(url).pathname;
      if (!pages.has(p)) add("sitemap-dead-url", url, "sitemap lists a URL that is not a built page");
      if (!info.lastmod || !/^\d{4}-\d{2}-\d{2}/.test(info.lastmod)) add("sitemap-lastmod", url, "missing or malformed <lastmod>");
      for (const a of info.alts) if (!sitemapUrls.has(a.href)) add("sitemap-hreflang", url, `alternate ${a.href} is not itself in the sitemap`);
      const page = pages.get(p);
      if (page) { const htmlAlts = page.$('link[rel="alternate"][hreflang]').length; if ((htmlAlts > 0) !== (info.alts.length > 0)) add("sitemap-hreflang", url, "sitemap hreflang annotations differ from the page's"); }
    }
  }
  const robotsTxt = exists("robots.txt") ? fs.readFileSync(path.join(dist, "robots.txt"), "utf8") : null;
  if (!robotsTxt) add("robots-missing", "/robots.txt", "no robots.txt");
  else {
    if (!/^Sitemap:\s*\S+/im.test(robotsTxt)) add("robots-sitemap", "/robots.txt", "robots.txt has no Sitemap line");
    if (/^Disallow:\s*\/\s*$/im.test(robotsTxt)) add("robots-blocks-all", "/robots.txt", "robots.txt disallows everything");
  }
  for (const f of ["llms.txt", "site.webmanifest", "guides/feed.xml", "404.html", "_headers", "favicon.svg"]) if (!exists(f)) add("file-missing", "/" + f, `${f} is missing from the build`);

  const filtered = only ? issues.filter((i) => only.has(i.rule)) : issues;
  return { issues: filtered, stats: { pages: pages.size, sitemapUrls: sitemapUrls.size, externalLinks: [...externalLinks].sort(), siteOrigin } };
}

export const LINK_RULES = new Set(["link-broken", "link-anchor-broken", "link-trailing-slash", "orphan-page", "link-text-empty", "link-text-generic"]);
