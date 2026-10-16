import type { Lang } from "../content/types";
import { absUrl, siteConfig } from "./siteConfig";
import { type Entry } from "./registry";

export const ogPath = (e: Entry): string => `/og/${e.lang}/${e.id}.png`;
export const OG_LOCALE: Record<Lang, string> = { en: "en_US" };

export interface HeadMeta {
  lang: Lang;
  title: string;
  description: string;
  canonical: string;
  robots: string;
  ogImage: string;
  ogType: "website" | "article";
  published?: string;
  modified?: string;
}

export function headFor(e: Entry): HeadMeta {
  return {
    lang: e.lang,
    title: e.def.title,
    description: e.def.description,
    canonical: absUrl(e.path),
    robots: e.indexable ? "index,follow,max-image-preview:large" : "noindex,follow",
    ogImage: absUrl(e.def.cmsHtml !== undefined && siteConfig.seo.defaultOgImage ? siteConfig.seo.defaultOgImage : ogPath(e)),
    ogType: e.guideSlug ? "article" : "website",
  };
}

export const siteName = () => siteConfig.orgName;
