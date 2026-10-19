import { describe, it, expect } from "vitest";
import { navGroups } from "../src/content/nav";
import { coreEn } from "../src/content/pages/core.en";
import { intelEn } from "../src/content/pages/intel.en";
import { sourcesEn } from "../src/content/pages/sources.en";
import { miscEn } from "../src/content/pages/misc.en";
import { aiEn, solutionsFirst, solutionsMore } from "../src/content/pages/ai.en";
import { home } from "../src/content/home";

const ids = new Set(["home", ...[...coreEn, ...aiEn, ...intelEn, ...sourcesEn, ...solutionsFirst, ...miscEn, ...solutionsMore].map((p) => p.id)]);
// Pages another package adds (the Help centre) may be absent when this file is tested alone; the header drops links to pages that do not exist.
const OPTIONAL = new Set(["help"]);

describe("navigation", () => {
  const links = navGroups.flatMap((g) => [{ id: g.to.id, href: g.to.href, label: g.label }, ...g.columns.flatMap((c) => c.links), ...(g.foot ? [g.foot] : [])]);
  it("every link points at a page that exists (or an anchor)", () => {
    for (const l of links) {
      if (l.href) { expect(l.href.startsWith("/"), l.label).toBe(true); continue; }
      expect(ids.has(l.id!) || OPTIONAL.has(l.id!), `${l.label} -> ${l.id}`).toBe(true);
    }
  });
  it("labels are plain: short, no jargon", () => {
    for (const g of navGroups) {
      expect(g.label.length).toBeLessThanOrEqual(24);
      for (const c of g.columns) for (const l of c.links) expect(l.label.length, l.label).toBeLessThanOrEqual(44);
    }
    const text = links.map((l) => `${l.label} ${(l as { desc?: string }).desc ?? ""}`).join(" ").toLowerCase();
    for (const bad of ["free trial", "synergy", "leverage", "solutions", "intelligence"]) expect(text, bad).not.toContain(bad);
  });
  it("the top level uses the owner's words", () => {
    expect(navGroups.map((g) => g.label)).toEqual(["What Ziira does", "Ziira AI", "Who it is for", "How it works", "Pricing", "Help"]);
  });
  it("the home page names who it is for and shows only true trust statements", () => {
    const h = home.en;
    expect(h.h1.includes(h.h1Em) && h.h1.includes(h.h1Und)).toBe(true);
    expect(h.annotation).toBe("ask it anything, in plain words");
    expect(h.trustLine).toEqual(["One system instead of a pile of separate tools", "AI that shows its proof and never moves money", "Shops, salons, garages, clinics, gyms, agencies and more"]);
  });
});
