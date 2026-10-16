/**
 * The platform's website content, fetched once at BUILD time (docs/platform-admin-content.md in the main repository).
 *
 * The Super Admin keeps the editable facts (company, contact, social, SEO defaults, banner, legal and content pages,
 * pictures) and the plans; a publish there freezes them and exposes them read-only at
 * `GET {PUBLIC_PLATFORM_API_URL}/api/v1/public/site`. This module fetches that, falls back when it cannot, and turns it
 * into plain data the rest of the site uses through `siteConfig.ts`. Nothing is fetched in the visitor's browser.
 *
 * Where the content comes from, in order:
 *   1. `PLATFORM_SNAPSHOT_FILE`: a JSON file (CI and tests).
 *   2. The live API, when `PUBLIC_PLATFORM_API_URL` is set and something has been published. A good answer is kept in
 *      `.cache/platform-site.json` and its pictures are copied to `public/media/`.
 *   3. `.cache/platform-site.json`: the last good live answer (so a build works offline after one online build).
 *   4. `content-snapshot.json`: the committed seed. It is made of PLACEHOLDERS and says so.
 *
 * A production build prints a loud warning (and fails with `SITE_STRICT=1`) when it is not using fresh, real content:
 * the live fetch failed, nothing is published yet, or placeholder text remains.
 */

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

// ---- the published payload ------------------------------------------------------------------------------------------
export interface PlatformAsset {
  /** Where the site serves it: `/media/<file>`. */
  path: string;
  hash: string;
  width: number;
  height: number;
  alt: string;
  content_type?: string;
  /** Where the platform serves it (relative to the platform's address). */
  download?: string;
}

export interface PlatformPage {
  slug: string;
  locale: string;
  kind: "legal" | "content";
  title: string;
  /** Safe HTML made by the platform from the Markdown. */
  html: string;
  markdown: string;
  seo: { title: string | null; description: string | null };
  updated_at: string;
  version?: number;
}

export interface PlatformPrice {
  currency: string;
  interval: string;
  amount: string;
  tax_inclusive?: boolean;
}

export interface PlatformPlan {
  code?: string;
  name: string;
  description?: string;
  highlights?: string[];
  limits?: Record<string, unknown>;
  trial_days?: number;
  prices?: PlatformPrice[];
  /** Custom / enterprise plans: no public price, "contact us". */
  contact_only?: boolean;
  custom?: boolean;
}

type Localised = Record<string, string>;
interface Social { handle: string; url: string }

export interface PlatformSettings {
  company?: { legal_name?: string | null; trading_name?: string | null; tagline?: Localised; registration_number?: string | null; tax_id?: string | null; postal_address?: string | null };
  contact?: { support_email?: string | null; sales_email?: string | null; phones?: string[]; whatsapp?: { number: string; link: string } | null; form_target?: string | null };
  social?: Record<string, Social>;
  seo?: { title_template?: Localised; description?: Localised; og_image?: PlatformAsset | null };
  branding?: { logo?: PlatformAsset | null; favicon?: PlatformAsset | null };
  analytics?: { id: string } | null;
  cookie_notice?: Localised;
  links?: { app_url?: string | null; status_page_url?: string | null };
  banner?: { text: Localised; link?: string | null; starts_at?: string | null; ends_at?: string | null } | null;
  locales?: string[];
  default_locale?: string;
}

export interface PlatformPayload {
  published: boolean;
  settings: PlatformSettings;
  pages: PlatformPage[];
  plans: PlatformPlan[];
  addons: unknown[];
  assets: PlatformAsset[];
  published_at: string | null;
  version_hash: string | null;
  /** Set only in the committed seed: every value in it is a stand-in. */
  _placeholder?: boolean;
}

const asObject = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const asArray = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

/** Whatever the API (or a file) holds, as a complete payload: missing parts become empty, never undefined. */
export function normalise(raw: unknown): PlatformPayload {
  const r = asObject(raw);
  return {
    published: r.published === true,
    settings: asObject(r.settings) as PlatformSettings,
    pages: asArray<PlatformPage>(r.pages).filter((p) => p && typeof p.slug === "string" && typeof p.locale === "string" && typeof p.html === "string"),
    plans: asArray<PlatformPlan>(r.plans).filter((p) => p && typeof p.name === "string"),
    addons: asArray(r.addons),
    assets: asArray<PlatformAsset>(r.assets),
    published_at: typeof r.published_at === "string" ? r.published_at : null,
    version_hash: typeof r.version_hash === "string" ? r.version_hash : null,
    ...(r._placeholder === true ? { _placeholder: true } : {}),
  };
}

// ---- placeholders ---------------------------------------------------------------------------------------------------
/** The same words the platform's publish check refuses (kernel/site_markdown.py); content that passed it has none. */
export const PLACEHOLDER = /\bTODO\b|\bTBD\b|\bFIXME\b|lorem ipsum|\bCHANGE ?ME\b|REPLACE[ _-]?ME|\bXXX+\b|\[\[|\]\]|review with your lawyer|example\.invalid|@example\.(?:com|org|net)\b|\bexample\.(?:com|org|net)\b|your[- ]company[- ]name/i;

function strings(value: unknown, out: string[] = []): string[] {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((v) => strings(v, out));
  else if (value && typeof value === "object") Object.values(value).forEach((v) => strings(v, out));
  return out;
}

/** Why this payload is not real content yet (empty list: it is). */
export function placeholderIssues(payload: PlatformPayload): string[] {
  const issues: string[] = [];
  if (payload._placeholder) issues.push("the committed seed snapshot is in use: every value in it is a placeholder");
  if (!payload.published) issues.push("nothing has been published in the Super Admin yet");
  const hit = strings(payload.settings).find((s) => PLACEHOLDER.test(s));
  if (hit) issues.push(`a setting still holds placeholder text ("${hit.slice(0, 40)}")`);
  for (const p of payload.pages) {
    const found = PLACEHOLDER.exec(`${p.title} ${p.markdown}`);
    if (found) issues.push(`page ${p.locale}/${p.slug} still holds placeholder text ("${found[0]}")`);
  }
  return issues;
}

// ---- loading --------------------------------------------------------------------------------------------------------
export type Source = "file" | "live" | "cache" | "seed";
export interface Loaded {
  payload: PlatformPayload;
  source: Source;
  /** Problems worth a loud warning in a production build. */
  warnings: string[];
  /** The platform's address, when one is configured (for pictures). */
  apiBase: string;
}

type Env = Record<string, string | undefined>;
export interface LoadOptions {
  env: Env;
  root: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  /** Write the live answer to the cache and copy its pictures (a real build); false in unit tests. */
  persist?: boolean;
}

const readJson = (file: string): unknown | null => {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
};

const SEED = "content-snapshot.json";
const CACHE = path.join(".cache", "platform-site.json");

export async function loadPlatform(options: LoadOptions): Promise<Loaded> {
  const { env, root } = options;
  const apiBase = (env.PUBLIC_PLATFORM_API_URL ?? "").trim().replace(/\/+$/, "");
  const production = env.NODE_ENV === "production" || env.MODE === "production" || env.ZIIRA_SITE_ENV === "production";
  const problems: string[] = [];
  const seed = () => normalise(readJson(path.join(root, SEED)) ?? { _placeholder: true });

  let result: { payload: PlatformPayload; source: Source } | null = null;
  const filePath = env.PLATFORM_SNAPSHOT_FILE?.trim();
  if (filePath) {
    const raw = readJson(path.resolve(root, filePath));
    if (raw === null) throw new Error(`PLATFORM_SNAPSHOT_FILE ${filePath} cannot be read as JSON`);
    result = { payload: normalise(raw), source: "file" };
  } else if (apiBase) {
    try {
      const live = await fetchLive(apiBase, options.fetchImpl ?? fetch, options.timeoutMs ?? 10_000);
      if (live.published) {
        if (options.persist) await persistLive(live, apiBase, root, options.fetchImpl ?? fetch);
        result = { payload: live, source: "live" };
      } else problems.push("the platform answered, but nothing has been published there yet");
    } catch (error) {
      problems.push(`the platform at ${new URL(apiBase).host} could not be read (${(error as Error).message})`);
    }
  } else {
    problems.push("PUBLIC_PLATFORM_API_URL is not set, so the platform's content was not fetched");
  }

  if (!result) {
    const cached = readJson(path.join(root, CACHE));
    if (cached) {
      result = { payload: normalise(cached), source: "cache" };
      problems.push("using the last good copy of the platform's content (.cache/platform-site.json)");
    } else {
      result = { payload: seed(), source: "seed" };
      problems.push("using the committed placeholder snapshot (content-snapshot.json)");
    }
  }

  problems.push(...placeholderIssues(result.payload));
  return { payload: result.payload, source: result.source, warnings: production ? [...new Set(problems)] : [], apiBase };
}

async function fetchLive(base: string, fetchImpl: typeof fetch, timeoutMs: number): Promise<PlatformPayload> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${base}/api/v1/public/site`, { headers: { Accept: "application/json" }, signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return normalise(await response.json());
  } finally {
    clearTimeout(timer);
  }
}

/** Keep the good answer for offline builds, and copy the pictures it names into `public/media/` (named by hash, so a stale copy is impossible). */
async function persistLive(payload: PlatformPayload, base: string, root: string, fetchImpl: typeof fetch): Promise<void> {
  const dir = path.join(root, "public", "media");
  fs.mkdirSync(dir, { recursive: true });
  for (const asset of payload.assets) {
    const target = path.join(dir, path.basename(asset.path));
    if (fs.existsSync(target) && sha(fs.readFileSync(target)) === asset.hash) continue;
    const url = asset.download ? `${base}${asset.download}` : null;
    if (!url) continue;
    const response = await fetchImpl(url);
    if (!response.ok) throw new Error(`picture ${asset.path} answered HTTP ${response.status}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    if (sha(bytes) !== asset.hash) throw new Error(`picture ${asset.path} does not match its hash`);
    fs.writeFileSync(target, bytes);
  }
  fs.mkdirSync(path.join(root, ".cache"), { recursive: true });                 // only a payload whose pictures all arrived
  fs.writeFileSync(path.join(root, CACHE), JSON.stringify(payload));
}

const sha = (bytes: Buffer): string => createHash("sha256").update(bytes).digest("hex");

/** The loud message for a production build, or null when all is well. */
export function warningBanner(loaded: Loaded): string | null {
  if (loaded.warnings.length === 0) return null;
  const bar = "=".repeat(78);
  const lines = loaded.warnings.map((w) => ` - ${w}`).join("\n");
  return `\n${bar}\n WARNING: the website is not built from real, published platform content (source: ${loaded.source}).\n${lines}\n DO NOT DEPLOY THIS BUILD. Publish the content in the Super Admin (Website > Publish), set\n PUBLIC_PLATFORM_API_URL, and rebuild. Set SITE_STRICT=1 to make this a failure.\n${bar}\n`;
}

/** Print the banner; with SITE_STRICT=1 in a production build, stop the build. */
export function reportWarnings(loaded: Loaded, env: Env): void {
  const banner = warningBanner(loaded);
  if (!banner) return;
  if (env.SITE_STRICT) throw new Error(banner);
  const once = globalThis as { __ziiraPlatformWarned?: boolean };
  if (once.__ziiraPlatformWarned) return;                      // a build loads this module in more than one place
  once.__ziiraPlatformWarned = true;
  console.warn(banner);
}

/** The site's folder. The build bundles this file somewhere else, so its own location says nothing: the build runs from the site folder. */
export function defaultRoot(): string {
  return process.cwd();
}

// ---- reading the content --------------------------------------------------------------------------------------------
/** The best text for a language: its own, else the default language's, else the first one given. */
export function pick(text: Localised | undefined, lang: string, fallback = "en"): string {
  if (!text) return "";
  const own = text[lang] ?? text[fallback] ?? Object.values(text)[0];
  return own ?? "";
}

/** The banner as the site shows it, or null. `from`/`until` are kept so a visitor's browser can apply the dates between rebuilds. */
export function bannerOf(settings: PlatformSettings, now: Date): null | { en: string; href?: string; from?: string; until?: string; showNow: boolean } {
  const b = settings.banner;
  if (!b || !b.text || Object.keys(b.text).length === 0) return null;
  const from = b.starts_at ? new Date(b.starts_at) : null;
  const until = b.ends_at ? new Date(b.ends_at) : null;
  if (until && until <= now) return null;
  const showNow = !from || from <= now;
  return {
    en: pick(b.text, "en"), ...(b.link ? { href: b.link } : {}),
    ...(from ? { from: from.toISOString() } : {}), ...(until ? { until: until.toISOString() } : {}), showNow,
  };
}

/** Prices offered across the public plans: which currencies and billing intervals the toggles need. */
export function offered(plans: PlatformPlan[]): { currencies: string[]; intervals: string[] } {
  const order = ["month", "year", "one_time"];
  const currencies = [...new Set(plans.flatMap((p) => (p.prices ?? []).map((x) => x.currency)))].sort();
  const intervals = [...new Set(plans.flatMap((p) => (p.prices ?? []).map((x) => x.interval)))].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return { currencies, intervals };
}

export const isContactOnly = (plan: PlatformPlan): boolean => plan.contact_only === true || plan.custom === true || (plan.prices ?? []).length === 0;

/** The price of a plan for a choice of currency and interval; undefined when it has none (the card then says "contact us"). */
export function priceFor(plan: PlatformPlan, currency: string, interval: string): PlatformPrice | undefined {
  return (plan.prices ?? []).find((p) => p.currency === currency && p.interval === interval);
}

/** A display amount in the visitor's language. The amount is shown, never calculated with. */
export function formatPrice(price: PlatformPrice, lang: string): string {
  try {
    return new Intl.NumberFormat("en", { style: "currency", currency: price.currency }).format(price.amount as unknown as number);
  } catch {
    return `${price.currency} ${price.amount}`;
  }
}

/** The text of a page with its markup removed (for descriptions). */
export function plainText(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\s+/g, " ").trim();
}

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${space > max / 2 ? cut.slice(0, space) : cut}…`;
}

// ---- the one load for the whole build -------------------------------------------------------------------------------
const env = (typeof process !== "undefined" ? { ...process.env, ...(import.meta as unknown as { env?: Env }).env } : {}) as Env;

/** Loaded once per build (top-level await); every module reads it through `siteConfig`. */
export const loaded: Loaded = await loadPlatform({ env, root: defaultRoot(), persist: env.PLATFORM_SNAPSHOT_FILE ? false : true });
reportWarnings(loaded, env);
