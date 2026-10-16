import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { cmsDefs, descriptionFor, titleFor } from "../src/lib/cmsPages";
import {
  bannerOf, formatPrice, isContactOnly, loadPlatform, normalise, offered, placeholderIssues, plainText, priceFor, reportWarnings, truncate, warningBanner, type PlatformPage, type PlatformPayload,
} from "../src/lib/platform";
import { loadSiteConfig } from "../src/lib/siteConfig";

const real = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "platform-real.json"), "utf8"));
const seedFile = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "content-snapshot.json"), "utf8"));

/** A site folder with the given files, so each way of loading can be tried without touching the real one. */
function folder(files: Record<string, unknown> = {}): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "site-platform-"));
  for (const [name, value] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    fs.writeFileSync(path.join(root, name), JSON.stringify(value));
  }
  return root;
}
const answer = (body: unknown, status = 200): typeof fetch => (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
const PROD = { NODE_ENV: "production", PUBLIC_PLATFORM_API_URL: "https://platform.test" };

describe("reading the payload", () => {
  it("fills in what is missing instead of failing", () => {
    const p = normalise({});
    expect(p).toMatchObject({ published: false, pages: [], plans: [], assets: [], settings: {} });
    expect(normalise(null).pages).toEqual([]);
    expect(normalise({ pages: [{ nonsense: 1 }, { slug: "a", locale: "en", html: "<p>x</p>" }] }).pages).toHaveLength(1);
  });

  it("flags the seed, an unpublished platform and placeholder words, and passes real content", () => {
    expect(placeholderIssues(normalise(seedFile)).join(" ")).toMatch(/committed seed/);
    expect(placeholderIssues(normalise({ published: false }))).toEqual(["nothing has been published in the Super Admin yet"]);
    expect(placeholderIssues(normalise(real))).toEqual([]);
    const dirty = normalise({ ...real, settings: { ...real.settings, company: { legal_name: "TODO company name" } } });
    expect(placeholderIssues(dirty).join(" ")).toMatch(/setting still holds placeholder text/);
    const page = { ...real.pages[0], markdown: "Lorem ipsum dolor" };
    expect(placeholderIssues(normalise({ ...real, pages: [page] })).join(" ")).toMatch(/page en\/privacy still holds placeholder/i);
    expect(placeholderIssues(normalise({ ...real, settings: { links: { app_url: "https://example.invalid" } } })).length).toBe(1);
  });
});

describe("where the content comes from", () => {
  it("uses the live platform when it has published, and remembers the answer", async () => {
    const root = folder({ "content-snapshot.json": seedFile });
    const loaded = await loadPlatform({ env: PROD, root, fetchImpl: answer(real), persist: true });
    expect(loaded.source).toBe("live");
    expect(loaded.warnings).toEqual([]);
    expect(loaded.payload.settings.company?.legal_name).toBe("Acme Systems Ltd");
    expect(JSON.parse(fs.readFileSync(path.join(root, ".cache", "platform-site.json"), "utf8")).version_hash).toBe("fixture0001");
  });

  it("falls back to the last good copy when the platform cannot be reached, with a warning that does not show the address path", async () => {
    const root = folder({ ".cache/platform-site.json": real, "content-snapshot.json": seedFile });
    const failing = (async () => { throw new Error("connect ECONNREFUSED"); }) as unknown as typeof fetch;
    const loaded = await loadPlatform({ env: PROD, root, fetchImpl: failing });
    expect(loaded.source).toBe("cache");
    expect(loaded.warnings.join("\n")).toMatch(/platform.test could not be read \(connect ECONNREFUSED\)/);
    expect(loaded.warnings.join("\n")).toMatch(/last good copy/);
  });

  it("falls back to the placeholder seed with no cache, and says so loudly in a production build only", async () => {
    const root = folder({ "content-snapshot.json": seedFile });
    const failing = answer({}, 503);
    const production = await loadPlatform({ env: PROD, root, fetchImpl: failing });
    expect(production.source).toBe("seed");
    expect(production.warnings.join("\n")).toMatch(/HTTP 503/);
    expect(production.warnings.join("\n")).toMatch(/placeholder snapshot/);
    expect(warningBanner(production)).toMatch(/DO NOT DEPLOY/);
    const development = await loadPlatform({ env: { ...PROD, NODE_ENV: "development" }, root, fetchImpl: failing });
    expect(development.warnings).toEqual([]);
    expect(warningBanner(development)).toBeNull();
  });

  it("treats a platform that has published nothing as not ready", async () => {
    const root = folder({ "content-snapshot.json": seedFile });
    const loaded = await loadPlatform({ env: PROD, root, fetchImpl: answer({ published: false, settings: {}, pages: [], plans: [] }) });
    expect(loaded.source).toBe("seed");
    expect(loaded.warnings.join("\n")).toMatch(/nothing has been published/);
  });

  it("builds offline with no address at all, using the seed", async () => {
    const root = folder({ "content-snapshot.json": seedFile });
    const loaded = await loadPlatform({ env: { NODE_ENV: "production" }, root });
    expect(loaded.source).toBe("seed");
    expect(loaded.warnings.join("\n")).toMatch(/PUBLIC_PLATFORM_API_URL is not set/);
  });

  it("reads a fixture file for CI and refuses an unreadable one", async () => {
    const root = folder({ "snap.json": real });
    const loaded = await loadPlatform({ env: { NODE_ENV: "production", PLATFORM_SNAPSHOT_FILE: "snap.json" }, root });
    expect(loaded.source).toBe("file");
    expect(loaded.warnings).toEqual([]);
    await expect(loadPlatform({ env: { PLATFORM_SNAPSHOT_FILE: "missing.json" }, root })).rejects.toThrow(/cannot be read/);
  });

  it("stops a strict production build that is not on real content", async () => {
    const root = folder({ "content-snapshot.json": seedFile });
    const loaded = await loadPlatform({ env: { NODE_ENV: "production" }, root });
    expect(() => reportWarnings(loaded, { SITE_STRICT: "1" })).toThrow(/DO NOT DEPLOY/);
    const clean = await loadPlatform({ env: { NODE_ENV: "production", PLATFORM_SNAPSHOT_FILE: "snap.json" }, root: folder({ "snap.json": real }) });
    expect(() => reportWarnings(clean, { SITE_STRICT: "1" })).not.toThrow();
  });

  it("copies the live pictures by hash and refuses one that does not match", async () => {
    const bytes = Buffer.from("not really a png");
    const hash = (await import("node:crypto")).createHash("sha256").update(bytes).digest("hex");
    const asset = { path: "/media/abc.png", hash, width: 1, height: 1, alt: "x", download: "/api/v1/public/site/assets/abc.png" };
    const fetchBoth = (async (url: string) => (String(url).endsWith("/abc.png") ? new Response(bytes) : new Response(JSON.stringify({ ...real, assets: [asset] })))) as unknown as typeof fetch;
    const root = folder({ "content-snapshot.json": seedFile });
    await loadPlatform({ env: PROD, root, fetchImpl: fetchBoth, persist: true });
    expect(fs.readFileSync(path.join(root, "public", "media", "abc.png"))).toEqual(bytes);
    const wrong = (async (url: string) => (String(url).endsWith("/abc.png") ? new Response("tampered") : new Response(JSON.stringify({ ...real, assets: [asset] })))) as unknown as typeof fetch;
    const loaded = await loadPlatform({ env: PROD, root: folder({ "content-snapshot.json": seedFile }), fetchImpl: wrong, persist: true });
    expect(loaded.source).toBe("seed");                                             // the whole fetch is distrusted
    expect(loaded.warnings.join("\n")).toMatch(/does not match its hash/);
  });
});

describe("the site's facts", () => {
  const config = () => loadSiteConfig({ PUBLIC_SITE_URL: "https://ziira.test" }, normalise(real), "file", new Date("2026-10-15T00:00:00Z"));

  it("come from the platform, with the environment filling only the gaps", () => {
    const c = config();
    expect(c.orgName).toBe("Ziira");
    expect(c.legalName).toBe("Acme Systems Ltd");
    expect(c.appUrl).toBe("https://app.acme-systems.test");
    expect(c.contact).toMatchObject({ email: "help@acme-systems.test", salesEmail: "sales@acme-systems.test", formUrl: "https://forms.acme-systems.test/contact", whatsappUrl: "https://wa.me/442079460958" });
    expect(c.social).toEqual(["https://x.com/ziira_hq", "https://www.linkedin.com/company/ziira"]);
    expect(c.seo.twitterHandle).toBe("@ziira_hq");
    expect(c.legal.reviewed).toBe(true);
    expect(c.contentDate).toBe("2026-10-12");
    const empty = loadSiteConfig({ PUBLIC_ORG_LEGAL_NAME: "Env Co", PUBLIC_CONTACT_EMAIL: "env@x.test" }, normalise(seedFile), "seed");
    expect(empty.legalName).toBe("Env Co");
    expect(empty.contact.email).toBe("env@x.test");
    expect(empty.legal.reviewed).toBe(false);
    expect(empty.pricing).toEqual([]);
  });

  it("show the banner only inside its dates, and keep the dates for the browser", () => {
    const settings = (b: object) => ({ banner: { text: { en: "Hello" }, ...b } });
    const now = new Date("2026-10-15T12:00:00Z");
    expect(bannerOf(settings({}), now)).toMatchObject({ en: "Hello", showNow: true });
    expect(bannerOf(settings({ ends_at: "2026-10-01T00:00:00Z" }), now)).toBeNull();
    expect(bannerOf(settings({ starts_at: "2026-11-01T00:00:00Z" }), now)).toMatchObject({ showNow: false, from: "2026-11-01T00:00:00.000Z" });
    expect(bannerOf({ banner: null }, now)).toBeNull();
    expect(bannerOf({ banner: { text: {} } }, now)).toBeNull();
  });
});

describe("pricing", () => {
  const plans = normalise(real).plans;

  it("offers a period or currency choice only when prices exist for it", () => {
    expect(offered(plans)).toEqual({ currencies: ["EUR", "USD"], intervals: ["month", "year"] });
    expect(offered([plans[0]])).toEqual({ currencies: ["EUR", "USD"], intervals: ["month", "year"] });
    expect(offered([plans[2]])).toEqual({ currencies: [], intervals: [] });
  });

  it("never invents a price: a missing combination or a custom plan is 'contact us'", () => {
    const [growth, scale, enterprise] = plans;
    expect(priceFor(growth, "USD", "year")?.amount).toBe("300.00");
    expect(priceFor(growth, "EUR", "year")).toBeUndefined();
    expect(priceFor(scale, "EUR", "month")).toBeUndefined();
    expect(isContactOnly(enterprise)).toBe(true);
    expect(isContactOnly(growth)).toBe(false);
    expect(isContactOnly({ name: "Custom", custom: true, prices: [{ currency: "USD", interval: "month", amount: "1.00" }] })).toBe(true);
  });

  it("shows amounts as published, in the visitor's language", () => {
    expect(formatPrice({ currency: "USD", interval: "month", amount: "30.00" }, "en")).toBe("$30.00");
    expect(formatPrice({ currency: "USD", interval: "month", amount: "1234.50" }, "en")).toBe("$1,234.50");
    expect(formatPrice({ currency: "??", interval: "month", amount: "5.00" }, "en")).toBe("?? 5.00");
  });
});

describe("published pages", () => {
  const pages = normalise(real).pages;
  const config = { seo: { titleTemplate: { en: "{title} | Ziira" }, description: { en: "Business software for shops and distributors." }, defaultOgImage: "", twitterHandle: "", titleSuffix: "", }, orgName: "Ziira", contentDate: "2026-10-01" };
  const existing = { en: [{ id: "privacy", slug: "privacy-policy", kind: "legal", title: "x", description: "x", h1: "x", lead: "", blocks: [] }, { id: "about", slug: "about", kind: "page", title: "x", description: "x", h1: "x", lead: "", blocks: [] }], sw: [] } as never;
  const paths = (lang: string, slug: string) => `/${slug}/`;

  it("keep the address of a built-in legal page, add the others, and never take over a marketing page", () => {
    const warnings: string[] = [];
    const extra: PlatformPage[] = [...pages, { ...pages[0], slug: "about", kind: "content", title: "About us" }, { ...pages[0], locale: "fr" }];
    const defs = cmsDefs(extra, existing, paths, config, (m) => warnings.push(m));
    const privacy = defs.filter((d) => d.def.id === "privacy").map((d) => [d.lang, d.def.slug]);
    expect(privacy).toEqual([["en", "privacy-policy"]]);
    expect(defs.find((d) => d.def.id === "cookies" && d.lang === "en")?.def.slug).toBe("cookies");
    expect(defs.some((d) => d.def.id === "about")).toBe(false);
    expect(warnings.join("\n")).toMatch(/same id as a built-in page/);
    expect(warnings.join("\n")).toMatch(/language the site does not render/);
    expect(defs.every((d) => d.def.cmsHtml !== undefined && d.def.kind === "legal")).toBe(true);
  });

  it("get search text within the audit's limits", () => {
    for (const p of pages) {
      const t = titleFor(p, config), d = descriptionFor(p, config);
      expect(t.length).toBeLessThanOrEqual(60);
      expect(d.length).toBeGreaterThanOrEqual(50);
      expect(d.length).toBeLessThanOrEqual(160);
    }
    const partners = pages.find((p) => p.slug === "partners" && p.locale === "en") as PlatformPage;
    expect(titleFor(partners, config)).toBe("Partner with Ziira");
    expect(titleFor({ ...pages[0], title: "A".repeat(80) }, config)).toHaveLength(60);
    expect(descriptionFor({ ...pages[0], html: "<h2>T</h2><p>Short.</p>" }, config).length).toBeGreaterThanOrEqual(50);
    expect(descriptionFor(pages[0], config)).not.toContain("<");
  });
});

describe("small helpers", () => {
  it("turn HTML into plain words and cut text at a word", () => {
    expect(plainText("<p>A &amp; B</p><ul><li>c</li></ul>")).toBe("A & B c");
    expect(truncate("one two three four five", 12)).toBe("one two…");
    expect(truncate("short", 12)).toBe("short");
  });
  it("keep the payload type honest", () => {
    const p: PlatformPayload = normalise(real);
    expect(p.pages.length).toBe(14);
  });
});
