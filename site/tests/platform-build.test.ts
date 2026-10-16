// Builds the whole site three ways (about 25 seconds each) into temporary folders and checks what comes out:
//   1. from a real, published payload: the footer, legal pages, pricing and JSON-LD render from it, and the SEO audit passes;
//   2. from the committed placeholder seed in production mode: a loud warning, and the build still finishes;
//   3. the same with SITE_STRICT=1: the build fails.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { load } from "cheerio";
import { beforeAll, describe, expect, it } from "vitest";

// @ts-expect-error plain JavaScript module
import { auditSite } from "../scripts/lib/rules.mjs";

const site = path.resolve(__dirname, "..");
const noindex = JSON.parse(fs.readFileSync(path.join(site, "scripts", "noindex-allowlist.json"), "utf8")).paths;

function build(env: Record<string, string>) {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "site-build-"));
  const run = spawnSync("npx", ["astro", "build", "--outDir", out], {
    cwd: site, encoding: "utf8", timeout: 240_000,
    env: { ...process.env, NODE_ENV: "production", PUBLIC_SITE_URL: "https://ziira.test", PUBLIC_PLATFORM_API_URL: "", PLATFORM_SNAPSHOT_FILE: "", SITE_STRICT: "", ...env },
  });
  return { out, status: run.status, output: `${run.stdout}\n${run.stderr}` };
}
const page = (out: string, p: string) => load(fs.readFileSync(path.join(out, p, "index.html"), "utf8"));

describe("a build from real published content", () => {
  let out = "";
  let output = "";
  beforeAll(() => {
    const r = build({ PLATFORM_SNAPSHOT_FILE: "tests/fixtures/platform-real.json" });
    expect(r.status, r.output.slice(-1500)).toBe(0);
    out = r.out;
    output = r.output;
  }, 300_000);

  it("is quiet: no warning when nothing is a placeholder", () => {
    expect(output).not.toMatch(/DO NOT DEPLOY/);
  });

  it("writes the footer from the platform's facts", () => {
    const $ = page(out, "");
    const footer = $("footer").text();
    expect(footer).toContain("help@acme-systems.test");
    expect(footer).toContain("sales@acme-systems.test");
    expect(footer).toContain("+44 20 7946 0958");
    expect(footer).toContain("1 High Street");
    expect(footer).toContain("Acme Systems Ltd");
    expect(footer).toContain("REG 12345");
    expect($('footer a[href="https://wa.me/442079460958"]').length).toBe(1);
    expect($('footer a[href="https://x.com/ziira_hq"]').length).toBe(1);
    expect($('footer a[href="/cookies/"]').length).toBe(1);                       // published legal pages are linked
    expect($('footer a[href="/refunds/"]').length + $('footer a[href="/acceptable-use/"]').length + $('footer a[href="/data-processing/"]').length).toBe(3);
  });

  it("shows the announcement banner", () => {
    expect(page(out, "")(".announce").text()).toContain("New: daily owner brief");
  });

  it("renders the published legal text in both languages, as indexable pages with alternates", () => {
    const en = page(out, "cookies");
    expect(en("h1").text()).toBe("Cookie policy");
    expect(en("article, .prose").text()).toContain("We collect only what we need");
    expect(en("title").text()).toBe("Cookie policy | Ziira");
    expect(en('meta[name="robots"]').attr("content")).toMatch(/^index/);
    expect(en('link[rel="alternate"][hreflang]').length).toBe(0);                      // English only: no hreflang
    expect(page(out, "privacy-policy")("h1").text()).toBe("Privacy policy");
    expect(page(out, "privacy-policy")(".callout.warn").length).toBe(0);              // no "template" banner on real text
    expect(page(out, "partners")("title").text()).toBe("Partner with Ziira");
  });

  it("renders the plans with a period and currency choice, and 'contact us' where there is no price", () => {
    const $ = page(out, "pricing");
    expect($(".plan h3").map((_, e) => $(e).text()).get()).toEqual(["Growth", "Scale", "Enterprise"]);
    expect($('input[name="iv"]').length).toBe(2);
    expect($('input[name="cu"]').length).toBe(2);
    const growth = $(".plan").first();
    expect(growth.find('.price-line[data-cu="USD"][data-iv="year"]').text()).toContain("$300.00");
    expect(growth.find('.price-line[data-cu="EUR"][data-iv="year"]').text()).toContain("Contact us");
    expect($(".plan").last().find(".price").text()).toContain("Custom pricing");
    expect($(".plan").last().find("a.btn").attr("href")).toMatch(/get-started/);
    expect($("style").text()).toContain(':has(#iv-year:checked)');
    expect($.html()).not.toMatch(/\$\s*0\.00/);
  });

  it("puts the organisation in the structured data", () => {
    const graph = JSON.parse(page(out, "")('script[type="application/ld+json"]').text())["@graph"];
    const org = graph.find((n: { "@type": string }) => n["@type"] === "Organization");
    expect(org.legalName).toBe("Acme Systems Ltd");
    expect(org.sameAs).toEqual(["https://x.com/ziira_hq", "https://www.linkedin.com/company/ziira"]);
    expect(org.contactPoint.map((c: { email?: string; telephone?: string }) => c.email ?? c.telephone)).toEqual(["help@acme-systems.test", "sales@acme-systems.test", "+44 20 7946 0958"]);
    expect(org.address.streetAddress).toBe("1 High Street, Somewhere");
  });

  it("shows the contact details on the contact page and posts the form to the platform's target", () => {
    const $ = page(out, "get-started");
    expect($("form").attr("action")).toBe("https://forms.acme-systems.test/contact");
    expect($("main .contact-details").text()).toContain("sales@acme-systems.test");
    expect($('main .contact-details a[href="tel:+442079460958"]').length).toBe(1);
  });

  it("dates the sitemap from the pages' own update times", () => {
    const xml = fs.readFileSync(path.join(out, "sitemap.xml"), "utf8");
    expect(xml).toMatch(/<loc>https:\/\/ziira.test\/cookies\/<\/loc>\s*<lastmod>2026-10-10<\/lastmod>/);
    expect(xml).toMatch(/<loc>https:\/\/ziira.test\/partners\/<\/loc>\s*<lastmod>2026-10-11<\/lastmod>/);
  });

  it("passes the SEO audit in production mode", () => {
    const { issues } = auditSite(out, { production: true, noindexAllowed: noindex });
    expect(issues, JSON.stringify(issues.slice(0, 5))).toEqual([]);
  });
});

describe("a production build from the placeholder seed", () => {
  it("warns loudly and still builds", () => {
    const r = build({});
    expect(r.status, r.output.slice(-1500)).toBe(0);
    expect(r.output).toMatch(/DO NOT DEPLOY/);
    expect(r.output).toMatch(/PUBLIC_PLATFORM_API_URL is not set/);
    expect(r.output).toMatch(/committed (seed|placeholder)/);
    expect(page(r.out, "privacy-policy")(".callout.warn").length).toBe(1);               // the built-in template stays marked
    const { issues } = auditSite(r.out, { production: true, noindexAllowed: noindex });  // the seed does not change the site's SEO health
    expect(issues, JSON.stringify(issues.slice(0, 5))).toEqual([]);
  }, 300_000);

  it("fails when SITE_STRICT=1", () => {
    const r = build({ SITE_STRICT: "1" });
    expect(r.status).not.toBe(0);
    expect(r.output).toMatch(/DO NOT DEPLOY/);
  }, 300_000);
});
