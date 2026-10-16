/** The site is English only. To add a language later: widen Lang and LANGS, add content files per language, a LANG_PREFIX and the language switch (see docs/marketing-site.md). */
export type Lang = "en";
export const LANGS: Lang[] = ["en"];

/** One per file in src/assets/screens/ (made by `make site-screens`; keys and routes in scripts/capture-screens.mjs). */
export type ScreenKey =
  | "home" | "command" | "findings" | "finding" | "sales" | "till" | "stock" | "orders" | "owing" | "books" | "payroll"
  | "connect" | "connect-add" | "addons" | "intel-actions" | "brief" | "till-phone" | "command-phone";

export interface Block {
  h2: string;
  id?: string;
  /** Paragraphs. Inline markup: **bold**, [text](@page-id), [text](https://external). */
  p?: string[];
  ul?: string[];
  ol?: string[];
  table?: { caption?: string; head: string[]; rows: string[][] };
  callout?: { tone: "info" | "warn" | "ok"; title?: string; text: string };
  img?: { key: ScreenKey; alt: string; caption?: string };
  /** A second paragraph group after the list/table. */
  after?: string[];
  /** Render the page's child pages as cards here (hub pages). */
  cards?: boolean;
}

export interface Tile { icon: import("./integrations").IconName; title: string; text: string; page: string; hash?: string; name?: string }

export interface Faq { q: string; a: string }

/** One numbered step of a "steps" page (kind "steps"): a one-line title, 2-4 short sentences, the concrete result and optionally a real screenshot. */
export interface HowStep { title: string; text: string[]; result: string; img?: { key: ScreenKey; alt: string; caption?: string } }

export type PageKind = "page" | "home" | "contact" | "pricing" | "legal" | "glossary" | "guides" | "sources" | "integrations" | "hub" | "help" | "complete" | "steps";

/** The opening story on a steps page: a picture the reader recognises, an example note, and the question that leads into the steps. */
export interface HowStory { title: string; paragraphs: string[]; noteTitle: string; note: string[]; noteCaption: string; after: string[]; teaser: string }

export interface PageDef {
  id: string;
  /** URL path below the language root, no slashes at the ends ("" = the language home). Localised per language. */
  slug: string;
  parent?: string;
  kind?: PageKind;
  title: string;
  description: string;
  h1: string;
  lead: string;
  eyebrow?: string;
  blocks: Block[];
  faq?: Faq[];
  /** Page ids shown in "Keep reading". */
  related?: string[];
  /** Child pages listed as cards (hubs). */
  children?: boolean;
  schema?: "core" | "intelligence";
  cta?: "core" | "intelligence" | "general";
  /** Label used in OG image and breadcrumbs when shorter than the title. */
  short?: string;
  hero?: ScreenKey;
  /** Hero area: short, concrete bullets for 'What you get on this page'. Falls back to the page's own section headings. */
  glance?: string[];
  glanceTitle?: string;
  /** Hub pages: a full-width grid of benefit cards, each linking to a page. */
  tiles?: Tile[];
  /** Hub pages: how many blocks appear as full-width cards after the tiles (all by default). */
  /** Capabilities this page is about that depend on an outside service (src/content/availability.ts): while any is "soon" the page shows a Coming soon banner with a Get notified link. */
  avail?: import("./availability").AvailKey[];
  /** kind "steps": the numbered steps (also published as HowTo structured data), the minutes it takes to read, and a "what it checks" list drawn from the generated catalogue. */
  how?: { steps: HowStep[]; minutes: number; checksH2?: string; story?: HowStory };
  /** Pages the platform publishes: its safe HTML replaces the built-in body (see lib/cmsPages.ts). */
  cmsHtml?: string;
}
