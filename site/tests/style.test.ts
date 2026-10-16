// Plain-language style for guides, Help centre and the Intelligence step-by-step page (docs/marketing-site.md "Writing style").
// Hard fail: banned jargon. Warnings (printed, never failing): sentences over 25 words, paragraphs over 4 lines, more than 2 internal links
// in a paragraph, and the reading grade (Flesch-Kincaid, target about 7) with the worst pages listed.
import { describe, it, expect } from "vitest";
import { collect, check, grade, syllables } from "./lib/style";

const report = check(collect());

describe("plain-language style", () => {
  it("uses none of the banned jargon", () => { expect(report.banned).toEqual([]); });
  it("reports warnings (never fails)", () => {
    const show = (title: string, rows: string[]) => { if (rows.length) console.warn(`STYLE WARNING: ${title}: ${rows.length}\n  ` + rows.slice(0, 15).join("\n  ")); };
    show("sentences over 25 words", report.longSentences);
    show("paragraphs over about 4 lines (60 words)", report.longParagraphs);
    show("paragraphs with more than 2 internal links", report.linkHeavy);
    show("reading grade above 8 (worst first)", report.hard.slice(0, 15).map((h) => `${h.where}: grade ${h.grade}`));
    expect(true).toBe(true);
  });
  it("measures reading grade sensibly", () => {
    expect(syllables("cat")).toBe(1);
    expect(syllables("because")).toBe(2);
    expect(grade("Click Save. The sale is done. You can print it now. It takes a second.")).toBeLessThan(3);
    expect(grade("Reconciliation of consolidated intercompany receivables necessitates comprehensive documentation.")).toBeGreaterThan(14);
  });
  it("catches banned words (self-test)", () => {
    const r = check([{ source: "x", where: "y", text: "The webhook endpoint uses a tenant baseline. We found three findings." }]);
    expect(r.banned.length).toBeGreaterThanOrEqual(5);
    expect(check([{ source: "x", where: "y", text: "The old name for this was Findings." }]).banned).toEqual([]);
  });
});
