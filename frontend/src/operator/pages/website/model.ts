/** Pure helpers for the Website area: turning the server's setting values into form text and back, and the same quick checks the server makes. */

export type Raw = Record<string, unknown>;
export type FormValue = string | boolean | Record<string, string>;
export type Form = Record<string, FormValue>;

export const DEFAULT_LOCALES = ["en", "sw"];

/** Which settings each tab edits, and in what shape (the server's list says the same: it is the truth, this is the form). */
export const LOCALISED = new Set(["tagline", "seo_title_template", "seo_description", "cookie_notice_text", "banner_text"]);
export const BOOLEANS = new Set(["analytics_enabled", "banner_active"]);
export const LISTS = new Set(["phones", "locales"]);

export const TAB_KEYS = {
  company: ["company_legal_name", "company_trading_name", "tagline", "registration_number", "tax_id", "postal_address", "support_email", "sales_email", "phones", "whatsapp_number", "contact_form_target", "app_url", "status_page_url", "locales"],
  social: ["social_x", "social_linkedin", "social_facebook", "social_instagram", "social_youtube", "social_tiktok", "social_github"],
  seo: ["seo_title_template", "seo_description", "og_image", "logo", "favicon", "analytics_enabled", "analytics_id", "cookie_notice_text"],
  banner: ["banner_active", "banner_text", "banner_link", "banner_starts_at", "banner_ends_at"],
} as const;

export type SettingsTab = keyof typeof TAB_KEYS;

export function localesOf(values: Raw | undefined): string[] {
  const list = values?.locales;
  return Array.isArray(list) && list.length > 0 ? (list as string[]) : DEFAULT_LOCALES;
}

/** The server's value as text for a form control. */
export function toFormValue(key: string, value: unknown, locales: string[]): FormValue {
  if (BOOLEANS.has(key)) return value === true;
  if (LOCALISED.has(key)) {
    const given = (value && typeof value === "object" ? value : {}) as Record<string, string>;
    return Object.fromEntries(locales.map((l) => [l, given[l] ?? ""]));
  }
  if (LISTS.has(key)) return Array.isArray(value) ? value.join(key === "phones" ? "\n" : ", ") : "";
  if (key.endsWith("_at")) return typeof value === "string" ? toLocalInput(value) : "";
  return typeof value === "string" ? value : "";
}

export function toForm(keys: readonly string[], values: Raw | undefined): Form {
  const locales = localesOf(values);
  return Object.fromEntries(keys.map((k) => [k, toFormValue(k, values?.[k], locales)]));
}

/** Text from the form as the server expects it: empty means "not set" (null). */
export function toRaw(key: string, value: FormValue): unknown {
  if (typeof value === "boolean") return value ? true : null;
  if (typeof value === "object") {
    const filled = Object.fromEntries(Object.entries(value).map(([l, v]) => [l, v.trim()]).filter(([, v]) => v));
    return Object.keys(filled).length ? filled : null;
  }
  const text = value.trim();
  if (!text) return null;
  if (key === "phones") return text.split(/\n|,/).map((p) => p.trim()).filter(Boolean);
  if (key === "locales") return text.split(/[,\s]+/).filter(Boolean);
  if (key.endsWith("_at")) return fromLocalInput(text);
  return text;
}

/** Only the settings whose value differs from what the server has. */
export function changes(keys: readonly string[], form: Form, original: Raw | undefined): Raw {
  const out: Raw = {};
  for (const key of keys) {
    const now = toRaw(key, form[key] ?? "");
    const before = original?.[key] ?? null;
    if (JSON.stringify(normalise(now)) !== JSON.stringify(normalise(before))) out[key] = now;
  }
  return out;
}

function normalise(value: unknown): unknown {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.fromEntries(Object.entries(value as Raw).sort(([a], [b]) => a.localeCompare(b)));
  }
  return value ?? null;
}

// ---- date and time: the server keeps an exact moment; the form edits it in the browser's own time zone
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInput(value: string): string | null {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

// ---- the quick checks (the server checks again and is the truth)
const EMAIL = /^[^@\s<>]{1,64}@[^@\s<>]+\.[^@\s<>]{2,}$/;
const PHONE = /^\+[0-9][0-9 ()\-.]{5,28}$/;
const HANDLE = /^@?[A-Za-z0-9._-]{1,60}(\/[A-Za-z0-9._-]{1,60})?$/;

export type Problem = "email" | "phone" | "url" | "handle" | "locales" | "token" | "tooLong" | null;

export function isHttpUrl(text: string): boolean {
  try {
    const u = new URL(text);
    return (u.protocol === "https:" || u.protocol === "http:") && !!u.hostname && !u.username && !/\s/.test(text);
  } catch {
    return false;
  }
}

export function quickProblem(key: string, value: FormValue, max = 200): Problem {
  if (typeof value === "boolean") return null;
  if (typeof value === "object") {
    const texts = Object.values(value).map((v) => v.trim());
    if (texts.some((v) => v.length > max)) return "tooLong";
    if (key === "seo_title_template") return texts.some((v) => v && !v.includes("{title}")) ? "token" : null;
    return null;
  }
  const text = value.trim();
  if (!text) return null;
  if (text.length > max && key !== "phones" && key !== "locales") return "tooLong";
  switch (key) {
    case "support_email":
    case "sales_email":
      return EMAIL.test(text) ? null : "email";
    case "phones":
      return text.split(/\n|,/).map((p) => p.trim()).filter(Boolean).every((p) => PHONE.test(p) && digits(p) >= 7 && digits(p) <= 15) ? null : "phone";
    case "whatsapp_number":
      return PHONE.test(text) && digits(text) >= 7 && digits(text) <= 15 ? null : "phone";
    case "app_url":
    case "status_page_url":
      return isHttpUrl(text) ? null : "url";
    case "banner_link":
      return isHttpUrl(text) || (text.startsWith("/") && !text.startsWith("//")) ? null : "url";
    case "contact_form_target":
      return EMAIL.test(text) || isHttpUrl(text) ? null : "url";
    case "locales":
      return text.split(/[,\s]+/).filter(Boolean).every((l) => /^[a-z]{2,3}(-[A-Z]{2})?$/.test(l)) ? null : "locales";
    default:
      if (key.startsWith("social_")) return HANDLE.test(text) || isHttpUrl(text) ? null : "handle";
      return null;
  }
}

const digits = (text: string) => text.replace(/\D/g, "").length;

/** First problem among the form's fields, keyed by setting (so the form can mark them and block saving). */
export function quickProblems(keys: readonly string[], form: Form): Record<string, Exclude<Problem, null>> {
  const out: Record<string, Exclude<Problem, null>> = {};
  for (const key of keys) {
    const problem = quickProblem(key, form[key] ?? "");
    if (problem) out[key] = problem;
  }
  return out;
}

/** The address a handle stands for, as the public site will show it (the server builds the real one). */
export const SOCIAL_BASE: Record<string, string> = {
  social_x: "https://x.com/", social_linkedin: "https://www.linkedin.com/company/", social_facebook: "https://www.facebook.com/",
  social_instagram: "https://www.instagram.com/", social_youtube: "https://www.youtube.com/@", social_tiktok: "https://www.tiktok.com/@", social_github: "https://github.com/",
};

export function socialUrl(key: string, value: string): string | null {
  const text = value.trim();
  if (!text) return null;
  if (isHttpUrl(text)) return text;
  return HANDLE.test(text) ? `${SOCIAL_BASE[key] ?? ""}${text.replace(/^@/, "")}` : null;
}

export function whatsappLink(number: string): string | null {
  return PHONE.test(number.trim()) ? `https://wa.me/${number.replace(/\D/g, "")}` : null;
}

// ---- pages
export const PAGE_STATE_TONE: Record<string, "ok" | "warn" | "neutral" | "info"> = { live: "ok", changed: "warn", new: "info", draft: "neutral", unpublish_pending: "warn" };

/** Search-result length guides (characters), used for the counters under the SEO fields. */
export const SEO_LIMITS = { title: 60, description: 160 } as const;

export function countTone(length: number, limit: number): "muted" | "warn" {
  return length > limit ? "warn" : "muted";
}

/** A web-address part from a title: lower case letters and digits, single dashes. */
export function slugFrom(title: string): string {
  return title.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
}

export const LEGAL_SLUGS = ["privacy", "terms", "cookies", "refunds", "acceptable-use", "data-processing"];

/** Legal pages missing for a language (the publish check wants all of them). */
export function missingLegal(pages: { slug: string; locale: string; kind: string }[], locale: string): string[] {
  const have = new Set(pages.filter((p) => p.locale === locale).map((p) => p.slug));
  return LEGAL_SLUGS.filter((s) => !have.has(s));
}

/** The Markdown line that puts a library picture in a page. */
export const imageSnippet = (assetId: string, alt: string): string => `![${alt.replace(/[[\]]/g, "")}](asset:${assetId})`;

export function groupIssues<T extends { code: string }>(issues: T[]): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const issue of issues) groups.set(issue.code, [...(groups.get(issue.code) ?? []), issue]);
  return [...groups.entries()];
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
