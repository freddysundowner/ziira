// Plain-language rules for guide and help content. Banned words fail the test; length and reading-grade problems are warnings.
import fs from "node:fs";
import path from "node:path";
import { allGuides } from "../../src/content/help/index";
import { sections, faq as completeFaq, intro as completeIntro, faqSection } from "../../src/content/completeGuide";
import { intelEn } from "../../src/content/pages/intel.en";

/** Internal-status language that must never appear on customer-facing pages (the site is for customers, not a status report). */
export const BANNED_PHRASES: RegExp[] = [/\bnot tested\b/i, /\buntested\b/i, /\bstand-ins?\b/i, /\bpilot test/i, /\bnot yet run\b/i, /\bnot live\b/i, /\bwork in progress\b/i, /\bwe have not\b/i, /\bno certifications?\b/i, /\bnot built\b/i, /\bunverified\b/i, /\bnot yet (been )?tested\b/i, /\bbuilt, pilot\b/i];

export interface Piece { source: string; where: string; text: string }

/** Words guide and help writers must not use. Each entry: [label, pattern]. */
export const BANNED: [string, RegExp][] = [
  ["baseline", /\bbaselines?\b/i],
  ["connector", /\bconnectors?\b/i],
  ["endpoint", /\bendpoints?\b/i],
  ["OAuth", /\boauth\b/i],
  ["webhook", /\bwebhooks?\b/i],
  ["extension point", /\bextension points?\b/i],
  ["plugin", /\bplug-?ins?\b/i],
  ["tenant", /\btenants?\b/i],
  ["provider", /\bproviders?\b/i],
  ["idempotent", /\bidempoten/i],
  ["RLS", /\bRLS\b/],
  ["cursor", /\bcursors?\b/i],
  ["schema", /\bschemas?\b/i],
  ["coverage matrix", /\bcoverage matrix\b/i],
  ["entity", /\bentity\b|\bentities\b/i],
  ["out of the box", /\bout[- ]of[- ]the[- ]box\b/i],
  ["leverage", /\bleverag(e|es|ed|ing)\b/i],
  ["robust", /\brobust\b/i],
  ["seamless", /\bseamless(ly)?\b/i],
  ["end to end", /\bend[- ]to[- ]end\b/i],
  ["read-only key", /\bread-only keys?\b/i],
  ["synergy", /\bsynerg/i],
  ["utilise", /\butili[sz]e\b/i],
];
/** "finding(s)" is allowed only in a sentence that says it is the app's older word. */
export const FINDING = /\bfindings?\b/i;
export const FINDING_OK = /\b(old|older|still|used to|also called|called|labelled|labeled|formerly)\b/i;

const plainText = (s: string): string =>
  s.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/\*\*([^*]+)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1").replace(/&nbsp;/g, " ");

const SKIP_KEYS = new Set(["t", "id", "key", "tone", "name", "kind", "x", "y", "icon", "slug", "journey", "next", "keywords", "shot", "date", "updated", "related", "topic", "type"]);
function strings(v: unknown, out: string[] = [], key = ""): string[] {
  if (typeof v === "string") { if (!SKIP_KEYS.has(key) && v.length > 2) out.push(v); }
  else if (Array.isArray(v)) v.forEach((x) => strings(x, out, key));
  else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) strings(x, out, k);
  return out;
}

export function collect(): Piece[] {
  const out: Piece[] = [];
  // Articles
  const dir = path.resolve(__dirname, "../../src/content/guides");
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith(".md"))) {
    const raw = fs.readFileSync(path.join(dir, f), "utf8");
    const m = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
    const front = m?.[1] ?? "";
    const body = m?.[2] ?? raw;
    for (const para of body.split(/\n\s*\n/)) out.push({ source: "article", where: f, text: para.trim() });
    for (const line of front.split("\n")) if (/^\s*(a|q|title|description|h1):/.test(line)) out.push({ source: "article", where: `${f} (front matter)`, text: line.replace(/^\s*\w+:\s*/, "").replace(/^"|"$/g, "") });
  }
  // Help guides
  for (const g of allGuides) for (const t of strings({ ...g, steps: g.steps.map((s) => ({ do: s.do, result: s.result, note: s.note, alt: s.shot?.alt })) })) out.push({ source: "help", where: g.slug, text: t });
  // Complete guide, its FAQ and the how-it-works page
  for (const s of sections) for (const t of strings(s)) out.push({ source: "complete-guide", where: s.id, text: t });
  for (const t of strings([completeIntro, faqSection, completeFaq])) out.push({ source: "complete-guide", where: "intro/faq", text: t });
  const how = intelEn.find((p) => p.id === "intelligence-how");
  if (how) for (const t of strings({ lead: how.lead, blocks: how.blocks, faq: how.faq })) out.push({ source: "page", where: "intelligence-how", text: t });
  return out;
}

export const sentences = (text: string): string[] => plainText(text).split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);
export const words = (s: string): string[] => s.split(/\s+/).filter((w) => /[a-z0-9]/i.test(w));

export function syllables(word: string): number {
  const w = word.toLowerCase().replace(/[^a-z]/g, "");
  if (!w) return 0;
  if (w.length <= 3) return 1;
  const m = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, "").replace(/^y/, "").match(/[aeiouy]{1,2}/g);
  return Math.max(1, m ? m.length : 1);
}
/** Flesch-Kincaid grade level of a text (lower is easier). */
export function grade(text: string): number {
  const ss = sentences(text);
  const ws = ss.flatMap((s) => words(s));
  if (!ss.length || ws.length < 6) return 0;
  const syl = ws.reduce((a, w) => a + syllables(w), 0);
  return 0.39 * (ws.length / ss.length) + 11.8 * (syl / ws.length) - 15.59;
}

export interface Report { banned: string[]; longSentences: string[]; longParagraphs: string[]; linkHeavy: string[]; hard: { where: string; grade: number }[] }
export function check(pieces: Piece[]): Report {
  const r: Report = { banned: [], longSentences: [], longParagraphs: [], linkHeavy: [], hard: [] };
  const byWhere = new Map<string, string[]>();
  for (const p of pieces) {
    const t = plainText(p.text);
    for (const [label, re] of BANNED) if (re.test(t)) r.banned.push(`${p.source}/${p.where}: "${label}" in: ${t.slice(0, 90)}`);
    for (const s of sentences(p.text)) {
      if (FINDING.test(s) && !FINDING_OK.test(s)) r.banned.push(`${p.source}/${p.where}: "finding" in: ${s.slice(0, 90)}`);
      const n = words(s).length;
      if (n > 25 && !s.includes("|")) r.longSentences.push(`${p.source}/${p.where} (${n} words): ${s.slice(0, 80)}`);
    }
    if (words(t).length > 60 && p.source !== "help") r.longParagraphs.push(`${p.source}/${p.where} (${words(t).length} words): ${t.slice(0, 60)}`);
    const links = (p.text.match(/\]\(@/g) ?? []).length;
    if (links > 2) r.linkHeavy.push(`${p.source}/${p.where} (${links} links): ${t.slice(0, 60)}`);
    const k = `${p.source}/${p.where}`;
    byWhere.set(k, [...(byWhere.get(k) ?? []), t]);
  }
  for (const [where, ts] of byWhere) { const g = grade(ts.join(" ")); if (g > 8) r.hard.push({ where, grade: Math.round(g * 10) / 10 }); }
  r.hard.sort((a, b) => b.grade - a.grade);
  return r;
}
