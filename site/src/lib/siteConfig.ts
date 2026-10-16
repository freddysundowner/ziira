/**
 * THE ONE PLACE for every editable fact about the business behind the site: names, origin, contact details, social links,
 * SEO defaults, announcement banner, plans (prices) and legal text. Nothing else in the site may hard-code these.
 *
 * The values come from the platform's Super Admin (Website > Publish) through `lib/platform.ts`, which fetches
 * `GET /api/v1/public/site` at build time and falls back to a cached copy or the committed placeholder snapshot.
 * Build-time environment variables (site/.env.example) fill whatever the platform does not supply.
 */
import { bannerOf, loaded, type Loaded, type PlatformAsset, type PlatformPage, type PlatformPlan, type PlatformPayload } from "./platform";

export interface Plan {
  id: string;
  name: string;
  /** Free text exactly as the platform publishes it, e.g. "From 20 per branch per month". Never invented here. */
  priceText: string;
  description?: string;
  features: string[];
  highlighted?: boolean;
  ctaLabel?: string;
}

export interface SiteConfig {
  /** Product / brand name shown everywhere. */
  orgName: string;
  /** Registered company name; empty until supplied. Never invented. */
  legalName: string;
  /** Canonical origin of this site, no trailing slash. */
  siteUrl: string;
  /** Origin of the product web app (sign in / register links). */
  appUrl: string;
  contact: { formUrl: string; email: string; phone: string; address: string; salesEmail: string; phones: string[]; whatsappUrl: string };
  /** Profile URLs for Organization.sameAs; empty until real profiles exist. */
  social: string[];
  seo: { titleSuffix: string; defaultOgImage: string; twitterHandle: string; titleTemplate: Record<string, string>; description: Record<string, string> };
  /** A one-line banner above the header; null hides it. Per language. */
  announcement: null | { en: string; href?: string; from?: string; until?: string; showNow?: boolean };
  /** Plans for the pricing page. Empty array renders the "Get in touch" state. */
  plans: Plan[];
  /** Legal pages: Markdown bodies (or null = show the built-in template) and whether a lawyer has reviewed them. */
  legal: { privacyMd: string | null; termsMd: string | null; reviewed: boolean; effectiveDate: string };
  /** Date used as lastmod for pages without their own date (ISO). */
  contentDate: string;
  /** From the platform: the registration and tax numbers to show, the logo and favicon (served from /media), the plans as published. */
  company: { registrationNumber: string; taxId: string; logo: PlatformAsset | null; favicon: PlatformAsset | null };
  /** Pages the platform publishes (legal and content), and the plans exactly as published. */
  cmsPages: PlatformPage[];
  pricing: PlatformPlan[];
  /** Where this content came from: live, cache, seed or file. */
  source: Loaded["source"];
}

export const PLACEHOLDER_SITE_URL = "https://example.invalid";

type Env = Record<string, string | undefined>;
const env = import.meta.env as Env;

const trimUrl = (u: string) => u.replace(/\/+$/, "");
const isUrl = (v: string | null | undefined): v is string => !!v && /^https?:\/\//.test(v);
const day = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : "");

/** Plans in the shape older code expects (name, a price line, features): the pricing page itself reads `pricing`. */
function legacyPlans(plans: PlatformPlan[]): Plan[] {
  return plans.map((p) => {
    const first = (p.prices ?? [])[0];
    return { id: p.code ?? p.name, name: p.name, priceText: first ? `${first.currency} ${first.amount} / ${first.interval}` : "", description: p.description, features: p.highlights ?? [] };
  });
}

export function loadSiteConfig(e: Env = env, payload: PlatformPayload = loaded.payload, source: Loaded["source"] = loaded.source, now = new Date()): SiteConfig {
  const s = payload.settings;
  const handleX = s.social?.x?.handle ?? "";
  const privacy = payload.pages.find((p) => p.slug === "privacy" && p.locale === "en");
  const terms = payload.pages.find((p) => p.slug === "terms" && p.locale === "en");
  const target = s.contact?.form_target ?? "";
  const phones = s.contact?.phones ?? [];
  return {
    orgName: s.company?.trading_name || e.PUBLIC_ORG_NAME || "Ziira",
    legalName: s.company?.legal_name || e.PUBLIC_ORG_LEGAL_NAME || "",
    siteUrl: trimUrl(e.PUBLIC_SITE_URL || PLACEHOLDER_SITE_URL),
    appUrl: trimUrl(s.links?.app_url || e.PUBLIC_APP_URL || "http://localhost:5173"),
    contact: {
      formUrl: isUrl(target) ? target : e.PUBLIC_CONTACT_URL || "",
      email: s.contact?.support_email || (target.includes("@") && !isUrl(target) ? target : "") || e.PUBLIC_CONTACT_EMAIL || "",
      phone: phones[0] ?? "",
      address: s.company?.postal_address ?? "",
      salesEmail: s.contact?.sales_email ?? "",
      phones,
      whatsappUrl: s.contact?.whatsapp?.link ?? "",
    },
    social: Object.values(s.social ?? {}).map((x) => x.url).concat((e.PUBLIC_SOCIAL_URLS || "").split(",").map((u) => u.trim()).filter(Boolean)),
    seo: {
      titleSuffix: "",
      defaultOgImage: s.seo?.og_image?.path ?? "",
      twitterHandle: /^@[A-Za-z0-9_]{1,15}$/.test(handleX) ? handleX : "",
      titleTemplate: s.seo?.title_template ?? {},
      description: s.seo?.description ?? {},
    },
    announcement: bannerOf(s, now),
    plans: legacyPlans(payload.plans),
    legal: {
      privacyMd: privacy?.markdown ?? null,
      termsMd: terms?.markdown ?? null,
      reviewed: (privacy !== undefined && terms !== undefined) || e.PUBLIC_LEGAL_REVIEWED === "true",
      effectiveDate: day(privacy?.updated_at),
    },
    contentDate: day(payload.published_at) || "2026-10-15",
    company: { registrationNumber: s.company?.registration_number ?? "", taxId: s.company?.tax_id ?? "", logo: s.branding?.logo ?? null, favicon: s.branding?.favicon ?? null },
    cmsPages: payload.pages,
    pricing: payload.plans,
    source,
  };
}

export const siteConfig: SiteConfig = loadSiteConfig();

export const isPlaceholderOrigin = siteConfig.siteUrl === PLACEHOLDER_SITE_URL;

/** Links into the product web app. */
export const appLinks = {
  signIn: `${siteConfig.appUrl}/`,
  register: `${siteConfig.appUrl}/register`,
};

/** Absolute URL on this site for a path that starts with "/". */
export function absUrl(path: string): string {
  return siteConfig.siteUrl + path;
}
