/** Pure helpers for the assistant knowledge base (no site registry, so they are unit-tested on their own: tests/knowledge.test.ts). */
import { plain } from "./md";

export const MIN_WORDS = 150;
export const MAX_WORDS = 300;
/** Words and phrases that must never reach the assistant: invented proof, and any country or country-specific service (rule 15). */
export const BANNED = /\b(trusted by|award|ranked|number one|best-in-class|uptime|customers worldwide|live-tested|certified|benchmark|million users|kenya|kenyan|m-pesa|mpesa|etims|nairobi|safaricom|ksh|kes)\b|99\.9|% more accurate|#1/i;

export const words = (s: string) => s.split(/\s+/).filter(Boolean).length;
export const clean = (s: string) => plain(s).replace(/\s+/g, " ").trim();
export const sentences = (s: string) => s.match(/[^.!?]+[.!?]+(\s|$)|[^.!?]+$/g)?.map((x) => x.trim()).filter(Boolean) ?? [];
/** Sentences that say something the assistant must not repeat are dropped, never rewritten. */
export const safe = (s: string) => sentences(s).filter((x) => !BANNED.test(x)).join(" ");

/** Pack paragraphs of text into chunks of MIN_WORDS to MAX_WORDS (a lone short piece stays short; an over-long one is cut at sentence ends). */
export function pack(pieces: string[]): string[] {
  const out: string[] = [];
  let cur = "";
  const push = () => { if (cur.trim()) out.push(cur.trim()); cur = ""; };
  const flatten = pieces.flatMap((p) => (words(p) > MAX_WORDS ? split(p) : [p])).filter(Boolean);
  for (const p of flatten) {
    if (cur && words(cur) + words(p) > MAX_WORDS) push();
    cur = cur ? `${cur} ${p}` : p;
    if (words(cur) >= MIN_WORDS) push();
  }
  push();
  // a short tail joins the previous chunk when it still fits
  if (out.length > 1 && words(out[out.length - 1]) < MIN_WORDS / 2 && words(out[out.length - 2]) + words(out[out.length - 1]) <= MAX_WORDS) {
    const tail = out.pop()!; out[out.length - 1] += ` ${tail}`;
  }
  return out;
}
function split(p: string): string[] {
  const out: string[] = []; let cur = "";
  const cut = (x: string): string[] => { const w = x.split(/\s+/); if (w.length <= MAX_WORDS) return [x]; const o: string[] = []; for (let k = 0; k < w.length; k += MAX_WORDS) o.push(w.slice(k, k + MAX_WORDS).join(" ")); return o; };
  for (const s of sentences(p).flatMap(cut)) { if (cur && words(cur) + words(s) > MAX_WORDS) { out.push(cur); cur = ""; } cur = cur ? `${cur} ${s}` : s; }
  if (cur) out.push(cur);
  return out;
}

