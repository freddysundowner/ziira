import { describe, it, expect } from "vitest";
import { coreEn } from "../src/content/pages/core.en";
import { intelEn } from "../src/content/pages/intel.en";
import { sourcesEn } from "../src/content/pages/sources.en";
import { miscEn } from "../src/content/pages/misc.en";
import { aiEn, solutionsFirst, solutionsMore } from "../src/content/pages/ai.en";
import { home } from "../src/content/home";
import { glossary } from "../src/content/glossary";

const en = [...coreEn, ...aiEn, ...intelEn, ...sourcesEn, ...solutionsFirst, ...miscEn, ...solutionsMore];

describe("content", () => {
  it("ids and slugs are unique within a language", () => {
    for (const list of [en]) {
      expect(new Set(list.map((p) => p.id)).size).toBe(list.length);
      expect(new Set(list.map((p) => p.slug)).size).toBe(list.length);
    }
  });
  it("titles stay within 60 characters and descriptions within 160", () => {
    for (const p of [...en, { id: "home-en", ...home.en }]) {
      expect(p.title.length, `${p.id} title`).toBeLessThanOrEqual(60);
      expect(p.description.length, `${p.id} description`).toBeLessThanOrEqual(160);
    }
  });
  it("the site names one product: no 'Ziira Core' anywhere", () => {
    expect(JSON.stringify([en, home, glossary])).not.toContain("Ziira Core");
  });
  it("tiles and links point at pages that exist", () => {
    const ids = new Set(en.map((p) => p.id));
    for (const p of en) for (const t of p.tiles ?? []) expect(ids.has(t.page), `${p.id} -> ${t.page}`).toBe(true);
  });
  it("every page tells the truth about status: no price, rating or certification words slipped in", () => {
    const text = JSON.stringify([en, home]).toLowerCase();
    for (const bad of ["iso 27001 certified", "soc 2 certified", "5-star", "trusted by", "award-winning"]) expect(text).not.toContain(bad);
  });
});
