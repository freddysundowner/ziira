// Builds a minimal, valid static site in a temp folder, so each SEO rule can be tested by breaking exactly one thing.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const ORIGIN = "https://ziira.test";

const pageSpecs = () => ({
  "/": { lang: "en", title: "Ziira Home Page", desc: "A description of the Ziira home page that is long enough to pass the minimum length.", h1: ["Home"], links: ["/about/", "/pricing/"] },
  "/about/": { lang: "en", title: "About Ziira", desc: "A description of the about page that is long enough to pass the minimum length rule.", h1: ["About"], links: ["/", "/pricing/"], crumbs: true },
  "/pricing/": { lang: "en", title: "Ziira Plans", desc: "A description of the pricing page that is long enough to pass the minimum length rule.", h1: ["Plans"], links: ["/", "/about/"], crumbs: true },
  "/404/": { lang: "en", title: "Not Found", desc: "That page does not exist, so use the links to find what you were looking for here.", h1: ["Not found"], links: ["/"], robots: "noindex,follow", is404: true },
});

export function baseSpec() {
  return { pages: pageSpecs(), files: {}, omitFiles: [], sitemapOverride: null, robotsOverride: null };
}

function renderPage(p, spec) {
  const canonical = spec.canonical ?? ORIGIN + p;
  const alts = spec.alts
    ? Object.entries(spec.alts).map(([l, href]) => `<link rel="alternate" hreflang="${l}" href="${ORIGIN + href}">`).join("") + `<link rel="alternate" hreflang="x-default" href="${ORIGIN + spec.alts.en}">`
    : "";
  const org = { "@type": "Organization", "@id": ORIGIN + "/#organization", name: "Ziira", url: ORIGIN + "/" };
  const graph = [org, { "@type": "WebPage", "@id": ORIGIN + p + "#webpage", url: ORIGIN + p, name: spec.title }];
  if (spec.crumbs) graph.push({ "@type": "BreadcrumbList", itemListElement: [{ "@type": "ListItem", position: 1, name: "Home", item: ORIGIN + "/" }] });
  const ld = spec.ld !== undefined ? spec.ld : JSON.stringify({ "@context": "https://schema.org", "@graph": graph });
  const h1 = (spec.h1 ?? []).map((t) => `<h1>${t}</h1>`).join("");
  const links = (spec.links ?? []).map((l) => `<a href="${l}">link to ${l}</a>`).join(" ");
  return `<!doctype html><html${spec.noLang ? "" : ` lang="${spec.lang}"`}><head><meta charset="utf-8">${spec.noViewport ? "" : '<meta name="viewport" content="width=device-width, initial-scale=1">'}
${spec.title === null ? "" : `<title>${spec.title}</title>`}${spec.desc === null ? "" : `<meta name="description" content="${spec.desc}">`}
<meta name="robots" content="${spec.robots ?? "index,follow"}">${spec.noCanonical ? "" : `<link rel="canonical" href="${canonical}">`}${alts}
<meta property="og:title" content="t"><meta property="og:description" content="d"><meta property="og:url" content="${canonical}"><meta property="og:image" content="${ORIGIN}/og/x.png"><meta name="twitter:card" content="summary_large_image">
${ld === null ? "" : `<script type="application/ld+json">${ld}</script>`}</head><body><a href="#main">skip</a><header>h</header><main id="main">${h1}${spec.body ?? ""}<p>${links}</p></main><footer>f</footer></body></html>`;
}

export function writeSite(spec) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "seo-fixture-"));
  const put = (rel, content) => { const f = path.join(dir, rel); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, content); };
  for (const [p, s] of Object.entries(spec.pages)) put(s.is404 ? "404.html" : path.join(p, "index.html"), renderPage(p, s));
  put("og/x.png", "png");
  put("llms.txt", "x"); put("site.webmanifest", "{}"); put("guides/feed.xml", "<feed/>"); put("_headers", "x"); put("favicon.svg", "<svg/>");
  put("assistant.js", "x"); put("assistant-chat.js", "x"); put("assistant.css", "x");
  put("assistant-knowledge.json", JSON.stringify(Array.from({ length: 10 }, (_, i) => ({ id: `c${i}`, title: "t", url: "/", text: "Plain words about the product." }))));
  const indexable = Object.entries(spec.pages).filter(([, s]) => !s.is404 && !(s.robots ?? "").includes("noindex"));
  const sitemap = spec.sitemapOverride ?? `<?xml version="1.0"?><urlset>${indexable.map(([p, s]) => `<url><loc>${ORIGIN + p}</loc><lastmod>2026-10-15</lastmod>${s.alts ? Object.entries(s.alts).map(([l, h]) => `<xhtml:link rel="alternate" hreflang="${l}" href="${ORIGIN + h}"/>`).join("") + `<xhtml:link rel="alternate" hreflang="x-default" href="${ORIGIN + s.alts.en}"/>` : ""}</url>`).join("")}</urlset>`;
  put("sitemap.xml", sitemap);
  put("robots.txt", spec.robotsOverride ?? `User-agent: *\nAllow: /\nSitemap: ${ORIGIN}/sitemap.xml\n`);
  for (const [rel, c] of Object.entries(spec.files)) put(rel, c);
  for (const rel of spec.omitFiles) fs.rmSync(path.join(dir, rel), { force: true });
  return dir;
}
