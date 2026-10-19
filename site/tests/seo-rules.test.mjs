import { describe, it, expect, afterAll } from "vitest";
import fs from "node:fs";
import { auditSite } from "../scripts/lib/rules.mjs";
import { baseSpec, writeSite, ORIGIN } from "./fixture.mjs";

const dirs = [];
const run = (mutate, opts = {}) => {
  const spec = baseSpec();
  mutate?.(spec);
  const dir = writeSite(spec);
  dirs.push(dir);
  return auditSite(dir, { noindexAllowed: ["/404/"], ...opts }).issues;
};
afterAll(() => dirs.forEach((d) => fs.rmSync(d, { recursive: true, force: true })));

const rulesOf = (issues) => [...new Set(issues.map((i) => i.rule))];

describe("the known-good fixture", () => {
  it("passes every rule", () => expect(run()).toEqual([]));
});

// Each case breaks exactly one thing and expects that rule (and names the rule it must raise).
const cases = [
  ["missing title", "title-missing", (s) => (s.pages["/about/"].title = null)],
  ["title over 60 characters", "title-too-long", (s) => (s.pages["/about/"].title = "T".repeat(61))],
  ["duplicate titles", "title-duplicate", (s) => (s.pages["/about/"].title = s.pages["/"].title)],
  ["missing description", "description-missing", (s) => (s.pages["/about/"].desc = null)],
  ["description over 160 characters", "description-too-long", (s) => (s.pages["/about/"].desc = "d".repeat(161))],
  ["description too short", "description-too-short", (s) => (s.pages["/about/"].desc = "short")],
  ["duplicate descriptions", "description-duplicate", (s) => (s.pages["/about/"].desc = s.pages["/"].desc)],
  ["missing canonical", "canonical-missing", (s) => (s.pages["/about/"].noCanonical = true)],
  ["canonical pointing elsewhere", "canonical-mismatch", (s) => (s.pages["/about/"].canonical = ORIGIN + "/other/")],
  ["noindex on a page that should be indexed", "noindex-unexpected", (s) => (s.pages["/about/"].robots = "noindex,follow")],
  ["no h1", "h1-count", (s) => (s.pages["/about/"].h1 = [])],
  ["two h1", "h1-count", (s) => (s.pages["/about/"].h1 = ["A", "B"])],
  ["heading level jump", "heading-order", (s) => (s.pages["/about/"].body = "<h3>Skipped</h3>")],
  ["missing html lang", "html-lang-missing", (s) => (s.pages["/about/"].noLang = true)],
  ["missing viewport", "viewport-missing", (s) => (s.pages["/about/"].noViewport = true)],
  ["image without alt", "img-alt-missing", (s) => (s.pages["/about/"].body = '<img src="/og/x.png" width="10" height="10">')],
  ["image without dimensions", "img-dimensions-missing", (s) => (s.pages["/about/"].body = '<img src="/og/x.png" alt="x">')],
  ["broken internal link", "link-broken", (s) => (s.pages["/about/"].links.push("/nowhere/"))],
  ["internal link without trailing slash", "link-trailing-slash", (s) => (s.pages["/about/"].links.push("/about"))],
  ["broken anchor", "link-anchor-broken", (s) => (s.pages["/about/"].links.push("/#nope"))],
  ["broken image file", "link-broken", (s) => (s.pages["/about/"].body = '<img src="/missing.png" alt="x" width="1" height="1">')],
  ["generic link text", "link-text-generic", (s) => (s.pages["/about/"].body = '<a href="/">read more</a>')],
  ["orphan page", "orphan-page", (s) => { s.pages["/orphan/"] = { lang: "en", title: "Orphan", desc: "An orphan page that nothing links to but is in the sitemap anyway ok.", h1: ["Orphan"], links: ["/"], crumbs: true }; }],
  // The site is English only today; these keep the generic hreflang rules honest for when a language is added (a second language is faked with "fr" on /pricing/).
  ["hreflang missing its reciprocal", "hreflang-not-reciprocal", (s) => { s.pages["/about/"].alts = { en: "/about/", fr: "/pricing/" }; s.pages["/pricing/"].lang = "fr"; }],
  ["hreflang target that does not exist", "hreflang-target-missing", (s) => (s.pages["/about/"].alts = { en: "/about/", fr: "/missing/" })],
  ["hreflang without the page itself", "hreflang-self-missing", (s) => (s.pages["/about/"].alts = { en: "/", fr: "/pricing/" })],
  ["JSON-LD that does not parse", "jsonld-invalid", (s) => (s.pages["/about/"].ld = "{not json")],
  ["JSON-LD without any block", "jsonld-missing", (s) => (s.pages["/about/"].ld = null)],
  ["JSON-LD with a fabricated rating", "jsonld-fabricated", (s) => (s.pages["/about/"].ld = JSON.stringify({ "@context": "https://schema.org", "@graph": [{ "@type": "Organization", name: "Z" }, { "@type": "SoftwareApplication", applicationCategory: "BusinessApplication", aggregateRating: { ratingValue: 5 } }, { "@type": "BreadcrumbList" }] }))],
  ["JSON-LD with a price", "jsonld-fabricated", (s) => (s.pages["/about/"].ld = JSON.stringify({ "@context": "https://schema.org", "@graph": [{ "@type": "Organization", name: "Z" }, { "@type": "SoftwareApplication", applicationCategory: "BusinessApplication", offers: { price: "1" } }, { "@type": "BreadcrumbList" }] }))],
  ["JSON-LD with a search action but no search", "jsonld-invalid", (s) => (s.pages["/about/"].ld = JSON.stringify({ "@context": "https://schema.org", "@graph": [{ "@type": "Organization", name: "Z" }, { "@type": "WebSite", potentialAction: {} }, { "@type": "BreadcrumbList" }] }))],
  ["FAQ shown without FAQPage markup", "jsonld-faq-mismatch", (s) => (s.pages["/about/"].body = '<div class="faq"><details><summary>q</summary>a</details></div>')],
  ["sitemap missing a page", "sitemap-missing-page", (s) => { s.sitemapOverride = `<urlset><url><loc>${ORIGIN}/</loc><lastmod>2026-10-15</lastmod></url></urlset>`; }],
  ["sitemap without lastmod", "sitemap-lastmod", (s) => { s.sitemapOverride = `<urlset><url><loc>${ORIGIN}/</loc></url></urlset>`; }],
  ["sitemap URL that is not a page", "sitemap-dead-url", (s) => { s.sitemapOverride = `<urlset><url><loc>${ORIGIN}/ghost/</loc><lastmod>2026-10-15</lastmod></url></urlset>`; }],
  ["no sitemap", "sitemap-missing", (s) => s.omitFiles.push("sitemap.xml")],
  ["robots.txt without a sitemap line", "robots-sitemap", (s) => (s.robotsOverride = "User-agent: *\nAllow: /\n")],
  ["robots.txt blocking everything", "robots-blocks-all", (s) => (s.robotsOverride = `User-agent: *\nDisallow: /\nSitemap: ${ORIGIN}/sitemap.xml\n`)],
  ["no robots.txt", "robots-missing", (s) => s.omitFiles.push("robots.txt")],
  ["no llms.txt", "file-missing", (s) => s.omitFiles.push("llms.txt")],
  ["no assistant knowledge file", "file-missing", (s) => s.omitFiles.push("assistant-knowledge.json")],
  ["a knowledge chunk that is too long", "assistant-knowledge", (s) => (s.files["assistant-knowledge.json"] = JSON.stringify(Array.from({ length: 10 }, (_, i) => ({ id: `c${i}`, title: "t", url: "/", text: "word ".repeat(i ? 10 : 301) }))))],
  ["a knowledge chunk with an invented claim", "assistant-knowledge", (s) => (s.files["assistant-knowledge.json"] = JSON.stringify(Array.from({ length: 10 }, (_, i) => ({ id: `c${i}`, title: "t", url: "/", text: i ? "Plain words." : "Trusted by shops." }))))],
  ["a knowledge chunk pointing at a page that does not exist", "assistant-knowledge", (s) => (s.files["assistant-knowledge.json"] = JSON.stringify(Array.from({ length: 10 }, (_, i) => ({ id: `c${i}`, title: "t", url: i ? "/" : "/nowhere/", text: "Plain words." }))))],
  ["HTML over budget", "budget-html", (s) => (s.pages["/about/"].body = "<p>" + "x".repeat(90_000) + "</p>")],
  ["too much inline CSS", "budget-css", (s) => (s.pages["/about/"].body = "<style>" + "a{}".repeat(25_000) + "</style>")],
  ["a script file over budget", "budget-js", (s) => { s.files["app.js"] = "x".repeat(25_000); s.pages["/about/"].body = '<script src="/app.js"></script>'; }],
  ["an oversized image file", "budget-image", (s) => { s.files["big.png"] = "x".repeat(170_000); s.pages["/about/"].body = '<img src="/big.png" alt="x" width="1" height="1">'; }],
  ["placeholder text left in", "placeholder-text", (s) => (s.pages["/about/"].body = "<p>TODO write this</p>")],
  ["a guide that is too short", "guide-length", (s) => { s.pages["/guides/x/"] = { lang: "en", title: "Guide X", desc: "A guide that is much too short to be useful, used to test the length rule.", h1: ["Guide"], links: ["/"], crumbs: true, body: '<div class="article"><p>few words</p></div>' }; s.pages["/about/"].links.push("/guides/x/"); }],
  ["a catalogue whose total is wrong", "catalogue-count", (s) => (s.pages["/about/"].body = '<div data-catalogue data-total="3"><section data-cat-group="a" data-count="2"><ul><li class="check">a</li><li class="check">b</li></ul></section></div>')],
  ["a group count that is wrong", "catalogue-count", (s) => (s.pages["/about/"].body = '<div data-catalogue data-total="2"><section data-cat-group="a" data-count="5"><ul><li class="check">a</li><li class="check">b</li></ul></section></div>')],
  ["a total stated in a table that is wrong", "catalogue-count", (s) => (s.pages["/about/"].body = '<div data-catalogue data-total="2"><section data-cat-group="a" data-count="2"><ul><li class="check">a</li><li class="check">b</li></ul></section></div><p data-total-checks>9</p>')],
];

describe("the complete guide's long-form allowances", () => {
  it("a consistent catalogue passes, and a data-longform page may exceed the normal HTML size", () => {
    const issues = run((s) => { s.pages["/about/"].body = '<div data-longform><div data-catalogue data-total="2"><section data-cat-group="a" data-count="2"><ul><li class="check">a</li><li class="check">b</li></ul></section></div><p data-total-checks>2</p><p>' + "x".repeat(120_000) + "</p></div>"; });
    expect(issues).toEqual([]);
  });
});

describe("each rule fails on a deliberately broken page", () => {
  for (const [name, rule, mutate] of cases) {
    it(`${name} -> ${rule}`, () => {
      const issues = run(mutate);
      expect(rulesOf(issues), JSON.stringify(issues.slice(0, 3))).toContain(rule);
    });
  }
});

describe("sitemap and noindex", () => {
  it("a noindex page listed in the sitemap -> sitemap-noindex-page", () => {
    const issues = run((s) => { s.pages["/about/"].robots = "noindex,follow"; s.sitemapOverride = `<urlset><url><loc>${ORIGIN}/about/</loc><lastmod>2026-10-15</lastmod></url></urlset>`; }, { noindexAllowed: ["/404/", "/about/"] });
    expect(rulesOf(issues)).toContain("sitemap-noindex-page");
  });
});

describe("production mode", () => {
  it("fails when the site URL is a placeholder", () => {
    const spec = baseSpec();
    const dir = writeSite(spec); dirs.push(dir);
    const issues = auditSite(dir, { production: true, siteUrl: "https://example.invalid", noindexAllowed: ["/404/"] }).issues;
    expect(rulesOf(issues)).toContain("site-url");
  });
  it("does not fail outside production mode", () => {
    const issues = run(null, { siteUrl: "https://example.invalid" });
    expect(rulesOf(issues)).not.toContain("site-url");
  });
  it("passes with a real origin", () => {
    expect(rulesOf(run(null, { production: true }))).not.toContain("site-url");
  });
});
