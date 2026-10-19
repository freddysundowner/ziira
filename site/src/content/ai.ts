/**
 * What the Ziira AI page and the home strip say, in one place. Short on purpose: the live proof is the floating "Ask Ziira" assistant.
 *
 * Truth rules (docs/marketing-site.md): numbers about the product come from the generated catalogue (src/content/checks.catalog.json via
 * lib/catalog), never typed here; every rule stated below is a real rule of the product (docs/ai.md, docs/intelligence.md).
 */
import type { Faq } from "./types";
import { catalog, totals } from "../lib/catalog";

export const counts = {
  checks: totals.checks,
  areas: catalog.groups.length,
  onZiira: totals.ziira,
  onConnected: totals.connected,
  actions: totals.actions,
  automatic: totals.automatic_actions,
  askTools: totals.ask_tools,
};

/** The slim strip on the home page. The button opens the floating assistant (components/Assistant.astro); without it, it opens /ai/. */
export const strip = {
  text: "Questions about Ziira? Ask it, and get an answer from the real pages.",
  button: "Ask Ziira anything",
  more: "How Ziira AI works",
};

/** What Ziira AI does, in plain lines (the /ai page). */
export const does = {
  h2: "What Ziira AI does",
  lines: [
    `**It checks every day.** ${counts.checks} checks run on your records, ${counts.onZiira} on Ziira's own data and ${counts.onConnected} on a system you already use, in ${counts.areas} areas.`,
    "**It tells you in plain words.** A short daily note and alerts by message, with the records behind each line.",
    "**It answers questions.** Ask about sales, stock, customers or money and see how it knows.",
    `**It prepares the next step.** ${counts.actions} kinds of step are ready, such as a purchase request or a payment reminder. You approve with one tap.`,
    `**It looks things up for you.** ${counts.askTools} different lookups sit behind Ask Ziira, each limited to what the person asking may see.`,
  ],
};

/** The safety rules, one short list. Real rules of the product. */
export const safety = {
  h2: "The rules it follows",
  items: [
    "It never moves money.",
    "It is off until an Owner accepts a written consent, and can be switched off at any time.",
    "Every figure comes from your own records, and the proof is beside each answer.",
    "It sees only what the person asking is allowed to see.",
    "Prices, credit limits and stock change only when a person approves.",
    "Names are replaced by labels and contact and bank details are removed before anything goes to an AI provider. Each business has a monthly usage limit.",
  ],
  note: "Read the [security and privacy summary](@security).",
};

export const aiCta = { button: "Ask Ziira anything", text: "Ask the assistant about prices, what fits your business, or how a check works." };

export const pageFaq: Faq[] = [
  { q: "Does the AI make up numbers?", a: "It cannot supply them. Every figure is calculated from your records. A written explanation whose numbers are not in the facts is discarded, and an answer containing a number that cannot be traced carries a note that some figures could not be checked against your data." },
  { q: "Is the AI switched on for my business automatically?", a: "No. It is off for every business until an Owner accepts a written consent. The consent is recorded, and switching it off stops every later use." },
  { q: "Can the AI move money or change my prices?", a: "No. Ziira never moves money. Prices, credit limits and stock change only when a person approves, and what they approve runs with their own permissions. The only things that can run by themselves, under rules the owner writes, are routine reminders and nudges." },
  { q: "Which AI providers does Ziira support?", a: "Anthropic, Google Gemini and OpenAI. The platform owner chooses which one is used and sets the spend cap." },
  { q: "What is sent to the AI provider?", a: "The question and the bounded results of the lookups it needed, such as totals, counts and product names. Names of people become labels, and phone numbers, emails, tax numbers, bank details and pay are not sent." },
  { q: "Can I use Ziira AI without moving to Ziira?", a: "The daily check, alerts and the daily note can run on the system you already use, which Ziira only reads. Asking questions works on the records Ziira holds." },
];

export const pageHero = {
  title: "Ziira AI: Ask Your Business and Get Answers You Can Check",
  description: "AI built into every part of the business: ask in plain words, get answers with proof, daily checks and suggestions you approve. It never moves money.",
  h1: "Ziira AI: it watches, answers and prepares",
  lead: "One AI across sales, stock, buying, money, people, bookings, jobs and claims. Ask it anything below, or read what it does.",
  glance: [`${counts.checks} checks every day`, "Answers with the proof beside them", "Suggestions you approve", "Never moves money"],
};
