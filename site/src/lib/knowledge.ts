/**
 * The assistant's knowledge base: plain-text chunks of the real site content, written to dist/assistant-knowledge.json by
 * src/pages/assistant-knowledge.json.ts on every build. The API behind the floating "Ask Ziira" reads that file from the site dist
 * folder (format: docs/marketing-site.md, "Floating Ask Ziira"). Real numbers only: counts come from checks.catalog.json via lib/catalog.
 */
import { entriesFor, type Entry } from "./registry";
import { BANNED, MIN_WORDS, MAX_WORDS, clean, safe, pack } from "./knowledgePack";
export { BANNED, MIN_WORDS, MAX_WORDS };
import { home } from "../content/home";
import { appTiles } from "../content/nav";
import { integrationsPage } from "../content/integrations";
import { presentation } from "../content/availability";
import { does, safety } from "../content/ai";
import { catalog, totals } from "./catalog";
import { helpGuides, helpJourneys } from "./help";
import { siteConfig } from "./siteConfig";
import type { Block, PageDef } from "../content/types";

export interface Chunk { id: string; title: string; url: string; text: string }

function blockText(b: Block): string {
  const parts: string[] = [b.h2 + "."];
  b.p?.forEach((x) => parts.push(clean(x)));
  b.ul?.forEach((x) => parts.push(clean(x).replace(/[.;]?$/, ".")));
  b.ol?.forEach((x, k) => parts.push(`${k + 1}. ${clean(x)}`));
  if (b.table) b.table.rows.forEach((r) => parts.push(r.map(clean).join(": ") + "."));
  if (b.callout) parts.push(`${b.callout.title ? b.callout.title + ": " : ""}${clean(b.callout.text)}`);
  b.after?.forEach((x) => parts.push(clean(x)));
  return safe(parts.join(" "));
}

function addPage(out: Chunk[], id: string, title: string, url: string, pieces: string[]) {
  pack(pieces.map(safe).filter(Boolean)).forEach((text, k, all) => out.push({ id: all.length > 1 ? `${id}-${k + 1}` : id, title, url, text }));
}

const BANNED_PAGES = new Set(["privacy", "terms", "complete", "guides", "glossary", "help"]);

function fromDef(e: Entry): string[] {
  const d: PageDef = e.def;
  const pieces: string[] = [];
  if (d.lead) pieces.push(clean(d.lead));
  if (d.glance?.length) pieces.push(d.glance.map(clean).join(". ") + ".");
  d.blocks.forEach((b) => pieces.push(blockText(b)));
  d.faq?.forEach((f) => pieces.push(`${f.q} ${clean(f.a)}`));
  return pieces;
}

export function buildKnowledge(): Chunk[] {
  const out: Chunk[] = [];
  const en = entriesFor("en").filter((e) => e.indexable);
  const urlOf = (id: string) => en.find((e) => e.id === id)?.path ?? "/";
  const h = home.en;

  // Home: positioning, who it is for, what is in it, how to start, questions.
  addPage(out, "home", "Ziira: the AI-first business system for every kind of business", "/", [
    clean(h.lead), h.trustLine.map(clean).join(". ") + ".", clean(h.heroNote),
    ...h.forItems.map((f) => `${f.t}. ${clean(f.d)}`),
    "What is in Ziira: " + appTiles.map((a) => `${a.label} (${a.desc})`).join("; ") + ".",
    clean(h.onePlace.text), h.onePlace.points.map(clean).join(". ") + ".",
    ...h.startSteps.map((s, k) => `Step ${k + 1}. ${s.t}. ${clean(s.d)}`),
    ...h.faq.map((f) => `${f.q} ${clean(f.a)}`),
  ]);

  // Content pages: product, solutions, AI, intelligence, security, about, contact, pricing.
  for (const e of en) {
    const d = e.def;
    if (e.id === "home" || e.guideSlug || d.cmsHtml !== undefined || BANNED_PAGES.has(d.kind ?? "") || BANNED_PAGES.has(e.id)) continue;
    if (e.id.startsWith("help") || d.kind === "help" || d.kind === "integrations") continue;
    if (e.id === "integrations-mpesa") continue; // a country-specific provider page: the integrations chunk below says "mobile money" generically
    if (e.id === "ai") {
      addPage(out, "ai", d.short ?? d.h1, e.path, [clean(d.lead), ...does.lines.map(clean), "The rules Ziira AI follows. " + safety.items.join(" ")]);
      continue;
    }
    const pieces = fromDef(e);
    if (d.kind === "pricing") {
      for (const p of siteConfig.pricing) {
        const prices = (p.prices ?? []).map((x) => `${x.currency} ${x.amount} per ${x.interval}`).join(", ");
        pieces.push(`Plan ${p.name}. ${p.description ?? ""} ${(p.highlights ?? []).join(". ")} ${prices ? "Published price: " + prices + "." : p.contact_only || p.custom ? "Price on request." : ""}`.replace(/\s+/g, " "));
      }
      if (!siteConfig.pricing.length) pieces.push("No plan prices are published on the site right now. Ask us about your business on the Get started page and we will say what fits.");
    }
    addPage(out, e.id, d.short ?? d.h1, e.path, pieces);
  }

  // Integrations, with their availability exactly as the site shows it.
  const ip = integrationsPage.en;
  const cards = ip.groups.flatMap((g) => g.cards.map((c) => ({ g, c })));
  const lines = cards.filter(({ c }) => !BANNED.test(`${c.name} ${c.title} ${c.text}`)).map(({ c }) => {
    const pr = c.avail ? presentation(c.avail) : null;
    return `${c.name}: ${pr?.soon ? `${pr.chip}. ${pr.note}` : `${clean(c.title)}. ${clean(c.text)} Status: ${c.chip}.`}`;
  });
  lines.push("Mobile money payments: a customer pays from their phone and Ziira matches the payment to the sale. Each country has its own add-on, so ask us about yours.");
  addPage(out, "integrations", "Integrations and connections", urlOf("integrations"), [clean(ip.note), ...lines, ...ip.steps.map((s, k) => `Step ${k + 1}. ${s.t}. ${clean(s.d)}`)]);

  // The checks, in numbers from the generated catalogue only.
  addPage(out, "checks", "The daily checks in numbers", urlOf("intelligence-complete"), [
    `Ziira runs ${totals.checks} checks every day in ${catalog.groups.length} areas: ${totals.ziira} on Ziira's own records and ${totals.connected} on a system you already use. ${totals.actions} kinds of suggested next step are ready for a person to approve, and ${totals.ask_tools} lookups sit behind Ask Ziira.`,
    "Areas: " + catalog.groups.map((g) => `${g.title} (${g.count} checks)`).join("; ") + ".",
  ]);

  // Help centre: the guides' titles and summaries, journey by journey.
  for (const j of helpJourneys) {
    const gs = helpGuides.filter((g) => g.journey === j.id);
    if (!gs.length) continue;
    addPage(out, `help-${j.id}`, `Help: ${j.title}`, `/help/${j.id}/`, [clean(j.blurb), ...gs.map((g) => `${g.h1}. ${clean(g.description)} Takes about ${g.minutes} minutes. See /help/${g.journey}/${g.slug}/.`)]);
  }
  return out;
}
