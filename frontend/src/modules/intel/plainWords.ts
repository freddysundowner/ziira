/**
 * Plain-words rules for the Simple layer of Intelligence: how urgent a thing is in everyday words, how a fact is shown,
 * how a check's limits read as a sentence, what the Today page says about the day, and which topics suit an edition.
 * Pure functions (tested); no technical word is produced here.
 */
import { formatDate, money, percent, quantity, type Schemas } from "@/sdk";

export type Band = "urgent" | "soon" | "look";
export type PlainCheck = Schemas["PlainCheckOut"];
export type FigureMeta = Schemas["FigureMetaOut"];
export type TopicKey = Schemas["TopicStateOut"]["key"];

/** Urgent (critical, high), Soon (medium) or Worth a look (low, info). */
export function bandOf(severity: string): Band {
  if (severity === "critical" || severity === "high") return "urgent";
  return severity === "medium" ? "soon" : "look";
}

export const TOPIC_KEYS = ["cash", "stock", "customers", "suppliers", "staff", "books"] as const;

/** A number written as text, with thousands commas allowed ("12,345.50"); null for anything else (a currency word, a sentence). */
export function numericText(value: string): number | null {
  const cleaned = value.trim().replace(/,/g, "");
  return /^-?\d+(\.\d+)?$/.test(cleaned) ? Number(cleaned) : null;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-/i;
const KIND_RANK: Record<string, number> = { money: 0, days: 1, count: 1, percent: 2, number: 3, date: 4, yesno: 5, text: 6 };

export interface Fact {
  key: string;
  label: string;
  kind: string;
  value: string;
}

/** Show a fact the way its kind says: money in the company's currency, counts whole, dates like "13 Oct 2026". Anything unexpected is shown as written. */
export function formatFact(value: string, kind: string, currency: string | undefined, words: { yes: string; no: string }): string {
  const n = numericText(value);
  switch (kind) {
    case "money": return n === null ? value : money(n, currency);
    case "count":
    case "days": return n === null ? value : quantity(n, Number.isInteger(n) ? 0 : 1);
    case "percent": return n === null ? value : percent(n, 1);
    case "number": return n === null ? value : quantity(n, 2);
    case "date": return /^\d{4}-\d{2}-\d{2}/.test(value) ? formatDate(value.slice(0, 10)) : value;
    case "yesno": return /^(yes|true)$/i.test(value) ? words.yes : /^(no|false)$/i.test(value) ? words.no : value;
    default: return value;
  }
}

/**
 * A finding's figures as labelled facts, the most telling first (money, then counts and days). Empty values, ids and the
 * currency code are left out; a figure no one has written a label for is skipped rather than shown by its code name.
 */
export function factsOf(figures: Record<string, string>, meta: Record<string, FigureMeta>, max = 6): Fact[] {
  const facts: Fact[] = [];
  for (const [key, value] of Object.entries(figures)) {
    const m = meta[key];
    if (!m || key === "currency" || value === "" || value === null || UUID.test(value)) continue;
    facts.push({ key, label: m.label, kind: m.kind, value });
  }
  return facts
    .map((f, i) => ({ f, i }))
    .sort((a, b) => (KIND_RANK[a.f.kind] ?? 9) - (KIND_RANK[b.f.kind] ?? 9) || a.i - b.i)
    .map((x) => x.f)
    .slice(0, max);
}

export type Segment = { kind: "text"; text: string } | { kind: "param"; name: string };

/** A sentence such as "Tell me when a customer is more than {min_days_overdue} days late." as pieces: words and the limits to edit. */
export function splitSentence(sentence: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of sentence.matchAll(/\{([a-z_0-9]+)\}/g)) {
    if (m.index > last) out.push({ kind: "text", text: sentence.slice(last, m.index) });
    out.push({ kind: "param", name: m[1] });
    last = m.index + m[0].length;
  }
  if (last < sentence.length) out.push({ kind: "text", text: sentence.slice(last) });
  return out;
}

/** The limits a sentence does not name: they are listed under "More settings". */
export function limitsOutsideSentence(sentence: string | null | undefined, names: readonly string[]): string[] {
  const named = new Set(splitSentence(sentence ?? "").flatMap((s) => (s.kind === "param" ? [s.name] : [])));
  return names.filter((n) => !named.has(n));
}

export interface DaySummary {
  /** How many things need the person today. */
  need: number;
  /** How many of those are urgent. */
  urgent: number;
  /** Which sentence to say: nothing needs you, some do, or all of them are urgent. */
  tone: "none" | "some" | "all";
}

export function daySummary(need: number, urgent: number): DaySummary {
  if (need <= 0) return { need: 0, urgent: 0, tone: "none" };
  const u = Math.min(urgent, need);
  return { need, urgent: u, tone: u === need ? "all" : "some" };
}

/** The topics worth switching on first for an edition (everything is the safe default; an unknown or missing edition gets everything). */
export function presetFor(edition: string | undefined): TopicKey[] {
  switch (edition) {
    case "retail": return ["cash", "stock", "customers", "staff"];
    case "distribution": return ["cash", "stock", "customers", "suppliers"];
    case "books": return ["cash", "customers", "suppliers", "books"];
    default: return [...TOPIC_KEYS];
  }
}

export const SNOOZE_CHOICES = [{ id: "three", days: 3 }, { id: "week", days: 7 }] as const;

/** Where "this is normal" applies, as the choices offered: the branch and the person or thing, when the finding is about one. */
export function ignoreScopes(options: { branch: { name: string } | null; subject: { label: string } | null }): ("branch" | "person" | "everywhere")[] {
  return [...(options.branch ? ["branch" as const] : []), ...(options.subject ? ["person" as const] : []), "everywhere"];
}

/** The routes of records a finding points at that have their own page (others are shown as text). */
const RECORD_ROUTES: Record<string, string> = {
  "pos.sale": "/pos/sales/",
  "crm.customer": "/customers/",
  "products.product": "/products/",
  "purchasing.purchase_order": "/orders/",
  "purchasing.supplier": "/suppliers/",
  "purchasing.supplier_bill": "/bills/",
  "people.employee": "/employees/",
  "people.payroll_run": "/payroll/",
  "inventory.stock_count": "/stock/counts/",
};

export function recordPath(record: { type: string; id: string | null }): string | null {
  const base = RECORD_ROUTES[record.type];
  return base && record.id ? `${base}${record.id}` : null;
}
