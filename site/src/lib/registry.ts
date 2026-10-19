import { LANGS, type Lang, type PageDef } from "../content/types";
import { home } from "../content/home";
import { coreEn } from "../content/pages/core.en";
import { intelEn } from "../content/pages/intel.en";
import { sourcesEn } from "../content/pages/sources.en";
import { miscEn } from "../content/pages/misc.en";
import { cmsDefs } from "./cmsPages";
import { guides } from "./guides";
import { helpDefs, HELP_DATE } from "./help";
import { siteConfig } from "./siteConfig";
import { BUILD_DATE } from "./buildDate";

export interface Entry {
  id: string;
  lang: Lang;
  path: string;
  def: PageDef;
  indexable: boolean;
  lastmod: string;
  /** For guide articles */
  guideSlug?: string;
}

const homeDef = (lang: Lang): PageDef => {
  const h = home[lang];
  return { id: "home", slug: "", kind: "home", title: h.title, description: h.description, h1: h.h1, lead: h.lead, blocks: [], short: "Ziira", cta: "general" };
};

const defs: Record<Lang, PageDef[]> = {
  en: [homeDef("en"), ...coreEn, ...intelEn, ...sourcesEn, ...miscEn],
};

export const LANG_PREFIX: Record<Lang, string> = { en: "" };

export function pathFor(lang: Lang, slug: string): string {
  const base = LANG_PREFIX[lang];
  if (!slug) return base ? `${base}/` : "/";
  return `${base}/${slug}/`;
}

const entries = new Map<string, Entry>(); // key: `${lang}:${id}`
const key = (lang: Lang, id: string) => `${lang}:${id}`;

for (const lang of LANGS) {
  for (const def of defs[lang]) {
    if (entries.has(key(lang, def.id))) throw new Error(`Duplicate page id ${def.id} (${lang})`);
    const legalNoindex = def.kind === "legal" && !siteConfig.legal.reviewed;
    entries.set(key(lang, def.id), { id: def.id, lang, path: pathFor(lang, def.slug), def, indexable: !legalNoindex, lastmod: def.kind === "complete" ? BUILD_DATE : siteConfig.contentDate });
  }
}

// Pages published in the platform's Super Admin: legal text for privacy/terms, and any other legal or content page.
for (const c of cmsDefs(siteConfig.cmsPages, defs, pathFor, siteConfig)) {
  entries.set(key(c.lang, c.def.id), { id: c.def.id, lang: c.lang, path: pathFor(c.lang, c.def.slug), def: c.def, indexable: true, lastmod: c.lastmod });
}

/** Guides: English only for now. Each is its own page. */
const guidesIndexDef = defs.en.find((d) => d.id === "guides")!;
for (const g of guides) {
  const id = `guide-${g.slug}`;
  const def: PageDef = {
    id, slug: `guides/${g.slug}`, parent: "guides", kind: "page", title: g.title, description: g.description, h1: g.h1, lead: "", blocks: [], short: g.title,
    cta: "general", related: g.related,
  };
  entries.set(key("en", id), { id, lang: "en", path: pathFor("en", def.slug), def, indexable: true, lastmod: g.updated, guideSlug: g.slug });
}
void guidesIndexDef;

/** Help centre (step-by-step how-to guides): English only. Built in lib/help.ts, rendered by components/HelpPage.astro. */
for (const def of helpDefs()) {
  entries.set(key("en", def.id), { id: def.id, lang: "en", path: pathFor("en", def.slug), def, indexable: true, lastmod: HELP_DATE });
}

/** Ids of the pages the platform publishes in a language (linked from the footer). */
export const cmsPageIds = (lang: Lang): string[] => entriesFor(lang).filter((e) => e.def.cmsHtml !== undefined).map((e) => e.id);

export const allEntries = (): Entry[] => [...entries.values()];
export const entriesFor = (lang: Lang): Entry[] => allEntries().filter((e) => e.lang === lang);
export const getEntry = (lang: Lang, id: string): Entry | undefined => entries.get(key(lang, id));

/** URL of a page in a language; falls back to the English page when that page has no translation. */
export function urlFor(id: string, lang: Lang): string {
  const e = entries.get(key(lang, id)) ?? entries.get(key("en", id));
  if (!e) throw new Error(`Unknown page id "${id}" (linked from content)`);
  return e.path;
}

export function titleFor(id: string, lang: Lang): string {
  const e = entries.get(key(lang, id)) ?? entries.get(key("en", id));
  if (!e) throw new Error(`Unknown page id "${id}"`);
  return e.def.short ?? e.def.title;
}

/** Language versions that exist for a page id. */
export function alternates(id: string): { lang: Lang; path: string }[] {
  return LANGS.flatMap((lang) => {
    const e = entries.get(key(lang, id));
    return e ? [{ lang, path: e.path }] : [];
  });
}

export function breadcrumbsFor(e: Entry): { name: string; path: string }[] {
  const trail: { name: string; path: string }[] = [];
  let cur: PageDef | undefined = e.def;
  while (cur) {
    const ent = entries.get(key(e.lang, cur.id)) ?? entries.get(key("en", cur.id));
    if (!ent) break;
    trail.unshift({ name: ent.def.short ?? ent.def.title, path: ent.path });
    cur = cur.parent ? (entries.get(key(e.lang, cur.parent))?.def ?? entries.get(key("en", cur.parent))?.def) : undefined;
  }
  return trail;
}

export function childrenOf(id: string, lang: Lang): Entry[] {
  return entriesFor(lang).filter((e) => e.def.parent === id);
}

export function homeOf(lang: Lang): string {
  return pathFor(lang, "");
}
