// The Help centre's data layer: guides and journeys as page definitions for the registry, and lookups for the page templates.
// Pure data, no imports from registry.ts (registry.ts imports this).
import type { PageDef } from "../content/types";
import type { HelpGuide, HelpJourney } from "../content/help/types";
import { journeys } from "../content/help/journeys";
import { allGuides } from "../content/help";

export const helpJourneys: HelpJourney[] = journeys;
export const helpGuides: HelpGuide[] = allGuides;

export const helpGuideId = (slug: string) => `help-${slug}`;
export const helpJourneyId = (id: string) => `helpj-${id}`;
export const HELP_INDEX_ID = "help";
export const HELP_AZ_ID = "help-a-z";
export const HELP_DATE = "2026-10-15";

const bySlug = new Map(helpGuides.map((g) => [g.slug, g]));
const byId = new Map(helpGuides.map((g) => [helpGuideId(g.slug), g]));
const journeyById = new Map(helpJourneys.map((j) => [j.id, j]));

for (const g of helpGuides) {
  if (!journeyById.has(g.journey)) throw new Error(`Help guide ${g.slug}: unknown journey ${g.journey}`);
  if (g.title.length > 60) throw new Error(`Help guide ${g.slug}: title is ${g.title.length} characters (max 60)`);
  if (g.description.length < 50 || g.description.length > 160) throw new Error(`Help guide ${g.slug}: description is ${g.description.length} characters (50 to 160)`);
  for (const n of g.next) if (!n.startsWith("@") && !bySlug.has(n)) throw new Error(`Help guide ${g.slug}: unknown next guide ${n}`);
}
if (bySlug.size !== helpGuides.length) throw new Error("Help guides: duplicate slug");

export const guideBySlug = (slug: string) => bySlug.get(slug);
export const guideForId = (id: string) => byId.get(id);
export const journeyForId = (id: string) => (id.startsWith("helpj-") ? journeyById.get(id.slice(6)) : undefined);
export const guidesIn = (journey: string) => helpGuides.filter((g) => g.journey === journey);
export const guidePath = (g: HelpGuide) => `help/${g.journey}/${g.slug}`;
export const journeyOf = (g: HelpGuide) => journeyById.get(g.journey)!;
export const isHelpId = (id: string) => id === HELP_INDEX_ID || id === HELP_AZ_ID || id.startsWith("help-") || id.startsWith("helpj-");

/** Reading order across the whole centre: journey by journey, guide by guide. Used for the Previous / Next links. */
export const helpOrder: HelpGuide[] = helpJourneys.flatMap((j) => guidesIn(j.id));

/** The registry's page definitions for the Help centre. */
export function helpDefs(): PageDef[] {
  const defs: PageDef[] = [
    {
      id: HELP_INDEX_ID, slug: "help", kind: "help", cta: "general", short: "Help",
      title: "Help centre: How to Use Ziira, Step by Step",
      description: "Step-by-step guides for running a shop with Ziira: set up, sell, stock, buy, customers, money, people and daily checks. Start here if you are new.",
      h1: "How to use Ziira, step by step", eyebrow: "Help centre",
      lead: "Short, numbered instructions with pictures of the real screens. Pick the job you want to do.", blocks: [],
    },
    {
      id: HELP_AZ_ID, slug: "help/a-z", parent: HELP_INDEX_ID, kind: "help", cta: "general", short: "All guides A to Z",
      title: "All Help Guides A to Z: Find a Ziira How-to",
      description: "Every Ziira help guide in one alphabetical list, with the time each takes. Use it to find a guide when you know what you want to do.",
      h1: "All guides, A to Z", eyebrow: "Help centre", lead: "Every guide in one list.", blocks: [],
    },
  ];
  for (const j of helpJourneys) {
    defs.push({
      id: helpJourneyId(j.id), slug: `help/${j.id}`, parent: HELP_INDEX_ID, kind: "help", cta: "general", short: j.title,
      title: `${j.title}: Ziira Help Guides`.slice(0, 60), description: j.description, h1: j.title, eyebrow: `Help centre · Part ${j.n}`, lead: j.blurb, blocks: [],
    });
  }
  for (const g of helpGuides) {
    defs.push({
      id: helpGuideId(g.slug), slug: guidePath(g), parent: helpJourneyId(g.journey), kind: "help", cta: "general", short: g.h1,
      title: g.title, description: g.description, h1: g.h1, eyebrow: `Help · ${journeyOf(g).title}`, lead: "", blocks: [],
    });
  }
  return defs;
}
