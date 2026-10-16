// The availability switch (src/content/availability.ts) and the customer-facing language rules.
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { availability, presentation, isAvailable, soonStatus, ifAvailable, soonKeys, type AvailKey } from "../src/content/availability";
import { integrationsPage } from "../src/content/integrations";
import { BANNED_PHRASES } from "./lib/style";

const root = path.resolve(__dirname, "../src");
const walk = (d: string): string[] => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]));

describe("availability switch", () => {
  it("every item is available by default: no Coming soon chip, no status line", () => {
    for (const k of Object.keys(availability) as AvailKey[]) {
      expect(isAvailable(k), k).toBe(true);
      expect(presentation(k).soon, k).toBe(false);
      expect(presentation(k).chip, k).toBe("");
      expect(soonStatus(k), k).toBe("");
    }
    expect(soonKeys()).toEqual([]);
  });
  it("an item set to soon renders a Coming soon chip with its note, and drops the live-only text", () => {
    const k: AvailKey = "whatsapp";
    const before = availability[k].status;
    try {
      availability[k].status = "soon";
      const p = presentation(k);
      expect(p.soon).toBe(true);
      expect(p.chip).toBe("Coming soon");
      expect(p.note).toBe(availability[k].note);
      expect(soonStatus(k)).toBe(`Coming soon: ${availability[k].note}`);
      expect(ifAvailable(k, "works today", "")).toBe("");
      expect(soonKeys()).toContain(k);
    } finally { availability[k].status = before; }
    expect(ifAvailable(k, "works today")).toBe("works today");
  });
  it("every note is one short customer-friendly line, and every integration card names a real item", () => {
    for (const [k, v] of Object.entries(availability)) { expect(v.note.length, k).toBeGreaterThan(20); expect(v.note.length, k).toBeLessThan(120); expect(v.note, k).not.toMatch(/test/i); }
    for (const g of integrationsPage.en.groups) for (const c of g.cards) if (c.avail) expect(availability[c.avail], c.name).toBeTruthy();
  });
});

describe("customer-facing language", () => {
  it("has no internal-status phrases in site content, components or pages", () => {
    const files = [...walk(path.join(root, "content")), ...walk(path.join(root, "components")), ...walk(path.join(root, "pages")), ...walk(path.join(root, "i18n"))]
      .filter((f) => /\.(ts|astro|md)$/.test(f) && !/legal\.ts$|availability\.ts$/.test(f));
    const hits: string[] = [];
    for (const f of files) {
      const text = fs.readFileSync(f, "utf8");
      for (const re of BANNED_PHRASES) { const m = text.match(re); if (m) hits.push(`${path.relative(root, f)}: "${m[0]}"`); }
    }
    expect(hits).toEqual([]);
  });
});
