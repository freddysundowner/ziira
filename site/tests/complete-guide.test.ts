import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { catalog, totals, checkByCode } from "../src/lib/catalog";
import { sections, faq, faqSection, guideWords } from "../src/content/completeGuide";
import { intelEn } from "../src/content/pages/intel.en";
import { inline } from "../src/lib/md";

const read = (rel: string) => fs.readFileSync(path.join(__dirname, "..", rel), "utf8");
const plain = JSON.parse(read("src/content/checks.plain.json")) as Record<string, unknown>;
const actionsPlain = JSON.parse(read("src/content/actions.plain.json")) as Record<string, unknown>;
const real = (o: Record<string, unknown>) => Object.keys(o).filter((k) => !k.startsWith("_")).sort();

describe("the generated catalogue", () => {
  it("is non-empty and its totals agree with the lists", () => {
    expect(totals.checks).toBeGreaterThan(0);
    expect(catalog.checks.length).toBe(totals.checks);
    expect(totals.ziira + totals.connected).toBe(totals.checks);
    expect(catalog.actions.length).toBe(totals.actions);
    expect(catalog.actions.filter((a) => a.automatic).length).toBe(totals.automatic_actions);
    expect(catalog.ask_tools.length).toBe(totals.ask_tools);
    expect(Object.values(totals.by_area).reduce((a, b) => a + b, 0)).toBe(totals.checks);
  });
  it("counts per area add up to the total, and per source", () => {
    expect(catalog.groups.reduce((a, g) => a + g.count, 0)).toBe(totals.checks);
    for (const g of catalog.groups) {
      expect(catalog.checks.filter((c) => c.group === g.key).length).toBe(g.count);
      expect(g.ziira + g.connected).toBe(g.count);
    }
  });
  it("has plain text for every check and no text for a check that does not exist", () => {
    expect(real(plain)).toEqual(catalog.checks.map((c) => c.code).sort());
    for (const c of catalog.checks) { expect(c.plain.length, c.code).toBeGreaterThan(20); expect(c.example, c.code).toBeTruthy(); for (const l of c.limits) expect(l.label, `${c.code}.${l.name}`).toBeTruthy(); }
  });
  it("has plain text for every action and ask tool", () => {
    expect(real(actionsPlain)).toEqual(catalog.actions.map((a) => a.type).sort());
    for (const t of catalog.ask_tools) expect(t.plain, t.name).toBeTruthy();
    for (const a of catalog.actions) expect(a.who_approves, a.type).toBeTruthy();
  });
});

describe("the complete guide's content", () => {
  it("never types a count by hand: counts come from the catalogue", () => {
    for (const f of ["src/content/completeGuide.ts", "src/content/pages/intel.en.ts", "src/components/GuideBlock.astro", "src/components/CompleteGuide.astro"]) {
      const src = read(f);
      expect(src.match(/\b\d+\s+(checks?|actions?|lookups?)\b/gi), `${f} has a hand-typed count`).toBeNull();
    }
  });
  it("links to checks that exist, to pages that exist, and to anchors that exist", () => {
    const ids = new Set([...sections.map((s) => s.id), faqSection.id, "next", "catalogue"]);
    const resolve = (id: string) => `/${id}/`;
    const all = JSON.stringify(sections);
    for (const m of all.matchAll(/\]\(#([a-z0-9-]+)\)/g)) {
      const id = m[1];
      if (id.startsWith("check-")) expect(catalog.checks.some((c) => `check-${c.code.replace(/[^a-z0-9]+/gi, "-")}` === id), id).toBe(true);
      else expect(ids.has(id), `anchor #${id}`).toBe(true);
    }
    expect(() => checkByCode("nope")).toThrow();
    for (const s of sections) JSON.stringify(s.blocks).replace(/\]\(@([a-z0-9-]+)\)/g, (_m, id: string) => { resolve(id); return ""; });
    expect(inline("[x](#ask) and [y](@home)", "en", (id) => `/${id}/`)).toContain('href="#ask"');
  });
  it("has unique section ids, an FAQ of 8 to 15 questions and a matching FAQ in the page definition", () => {
    const ids = [...sections.map((s) => s.id), faqSection.id, "next"];
    expect(new Set(ids).size).toBe(ids.length);
    expect(faq.length).toBeGreaterThanOrEqual(8);
    expect(faq.length).toBeLessThanOrEqual(15);
    const def = intelEn.find((p) => p.id === "intelligence-complete")!;
    expect(def.faq).toBe(faq);
    expect(def.kind).toBe("complete");
    expect(def.title.length).toBeLessThanOrEqual(60);
    expect(def.description.length).toBeGreaterThanOrEqual(50);
    expect(def.description.length).toBeLessThanOrEqual(160);
    expect(def.h1).toContain("complete guide");
  });
  it("is a short reference: at most twelve sections plus the FAQ", () => {
    expect(sections.length).toBeLessThanOrEqual(12);
    expect(guideWords()).toBeGreaterThan(guideWords(true));
  });
  it("stays true: says Ziira never moves money, claims no certification and never uses the old product name", () => {
    const text = JSON.stringify([sections, faq]).toLowerCase();
    expect(text).toContain("never moves money");
    expect(text).not.toMatch(/\b(iso 27001|soc 2|certified)\b/);
    expect(text).not.toContain("ziira core");
  });
});
