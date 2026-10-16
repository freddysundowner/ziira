/**
 * Pages published in the platform's Super Admin (legal pages and simple content pages), as page definitions the
 * registry can add. A legal page that the site already has by id (privacy, terms) keeps its address and gets the
 * platform's text; any other published page becomes a new page at `/<slug>/`. A page may not take over
 * a built-in marketing page or an address that is already in use: it is skipped and said so.
 */
import { LANGS, type Lang, type PageDef } from "../content/types";
import { pick, plainText, truncate, type PlatformPage } from "./platform";
import type { SiteConfig } from "./siteConfig";

export interface CmsDef {
  lang: Lang;
  def: PageDef;
  lastmod: string;
}

const MIN_DESCRIPTION = 50;

/** `{title}` filled into the platform's title template; the page's own search title wins; at most 60 characters. */
export function titleFor(page: PlatformPage, config: Pick<SiteConfig, "seo" | "orgName">): string {
  const template = pick(config.seo.titleTemplate, page.locale);
  const full = page.seo.title || (template ? template.replace("{title}", page.title) : `${page.title} | ${config.orgName}`);
  return full.length <= 60 ? full : page.title.length <= 60 ? page.title : truncate(page.title, 60);
}

/** The page's own search description, else its title and the start of its text, else the site default; 50 to 160 characters. */
export function descriptionFor(page: PlatformPage, config: Pick<SiteConfig, "seo" | "orgName">): string {
  const firstParagraph = /<p>([\s\S]*?)<\/p>/.exec(page.html)?.[1] ?? page.html;
  let text = page.seo.description || truncate(`${page.title}: ${plainText(firstParagraph)}`, 155);   // the title keeps pages' descriptions apart
  if (text.length < MIN_DESCRIPTION) text = `${text} ${pick(config.seo.description, page.locale) || config.orgName}`.trim();
  if (text.length < MIN_DESCRIPTION) text = `${page.title}. ${text}`.trim();
  return truncate(text, 160);
}

export function cmsDefs(
  pages: PlatformPage[],
  existing: Record<Lang, PageDef[]>,
  paths: (lang: Lang, slug: string) => string,
  config: Pick<SiteConfig, "seo" | "orgName" | "contentDate">,
  warn: (message: string) => void = console.warn,
): CmsDef[] {
  const out: CmsDef[] = [];
  const takenPaths = new Set(LANGS.flatMap((lang) => existing[lang].map((d) => paths(lang, d.slug))));
  for (const page of pages) {
    const lang = page.locale as Lang;
    if (!LANGS.includes(lang)) { warn(`Published page ${page.locale}/${page.slug} is in a language the site does not render; skipped.`); continue; }
    const builtIn = existing.en.find((d) => d.id === page.slug) ?? existing[lang].find((d) => d.id === page.slug);
    if (builtIn && builtIn.kind !== "legal") { warn(`Published page ${page.locale}/${page.slug} has the same id as a built-in page; skipped.`); continue; }
    const slug = builtIn ? builtIn.slug : page.slug;
    const own = existing[lang].find((d) => d.id === page.slug);
    if (!builtIn && takenPaths.has(paths(lang, slug))) { warn(`Published page ${page.locale}/${page.slug} would take an address that is already used; skipped.`); continue; }
    const def: PageDef = {
      id: page.slug, slug, kind: "legal", title: titleFor(page, config), description: descriptionFor(page, config), h1: page.title,
      lead: "", blocks: [], short: page.title, cta: "general", cmsHtml: page.html, ...(own?.parent ? { parent: own.parent } : {}),
    };
    out.push({ lang, def, lastmod: page.updated_at.slice(0, 10) || config.contentDate });
  }
  return out;
}
