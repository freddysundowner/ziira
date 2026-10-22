// The Help centre's content: every guide has what the audit expects, links resolve, and every screenshot has a capture spec with the right number of marks.
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { allGuides } from "../src/content/help/index";
import { journeys } from "../src/content/help/journeys";
// @ts-expect-error plain JS module
import { shots } from "../scripts/help-screens.shots.mjs";

const keys = allGuides.flatMap((g) => g.steps.flatMap((s) => (s.shot ? [{ g: g.slug, shot: s.shot }] : [])));
const specByKey = new Map<string, { marks: unknown[] }>(shots.map((s: { key: string; marks: unknown[] }) => [s.key, s]));

describe("help guides", () => {
  it("has the sixteen journeys, each with guides", () => {
    expect(journeys.map((j) => j.id)).toEqual(["get-started", "first-week", "sell", "stock", "buy", "customers", "money", "people", "bookings", "jobs", "time-projects", "memberships", "files", "intelligence", "settings", "support"]);
    for (const j of journeys) expect(allGuides.filter((g) => g.journey === j.id).length, j.id).toBeGreaterThan(0);
  });
  it("has unique slugs, titles and descriptions of the right length", () => {
    expect(new Set(allGuides.map((g) => g.slug)).size).toBe(allGuides.length);
    expect(new Set(allGuides.map((g) => g.title)).size).toBe(allGuides.length);
    expect(new Set(allGuides.map((g) => g.description)).size).toBe(allGuides.length);
    for (const g of allGuides) {
      expect(g.title.length, g.slug).toBeLessThanOrEqual(60);
      expect(g.description.length, g.slug).toBeGreaterThanOrEqual(50);
      expect(g.description.length, g.slug).toBeLessThanOrEqual(160);
    }
  });
  it("keeps every guide short: numbered steps, one short intro sentence, 1 to 3 problems, 1 to 2 next links, at most 2 links to other guides", () => {
    for (const g of allGuides) {
      expect(g.steps.length, g.slug).toBeGreaterThanOrEqual(3);
      expect(g.problems.length, g.slug).toBeGreaterThanOrEqual(1);
      expect(g.problems.length, g.slug).toBeLessThanOrEqual(3);
      expect(g.next.length, g.slug).toBeGreaterThanOrEqual(1);
      expect(g.next.length, g.slug).toBeLessThanOrEqual(2);
      expect(g.who && g.time, g.slug).toBeTruthy();
      expect(g.minutes, g.slug).toBeGreaterThan(0);
      expect((g.intro ?? "").split(/\s+/).filter(Boolean).length, `${g.slug}: intro is one short sentence`).toBeLessThanOrEqual(30);
      expect(g.tips.length, `${g.slug}: tips were removed`).toBe(0);
      const inGuide = JSON.stringify({ ...g, next: [] }).match(/\]\(@helpj?-/g) ?? [];
      expect(inGuide.length, `${g.slug}: links to other guides in the text`).toBeLessThanOrEqual(2);
    }
  });
  it("points next steps at guides or site pages that exist", () => {
    const slugs = new Set(allGuides.map((g) => g.slug));
    for (const g of allGuides) for (const n of g.next) if (!n.startsWith("@")) expect(slugs.has(n), `${g.slug} -> ${n}`).toBe(true);
  });
  it("links to existing guides in its text", () => {
    const slugs = new Set(allGuides.map((g) => g.slug));
    const text = JSON.stringify(allGuides);
    for (const m of text.matchAll(/\]\(@help-([a-z0-9-]+)\)/g)) expect(slugs.has(m[1]), `link to help-${m[1]}`).toBe(true);
    for (const m of text.matchAll(/\]\(@helpj-([a-z0-9-]+)\)/g)) expect(journeys.some((j) => j.id === m[1]), `link to helpj-${m[1]}`).toBe(true);
  });
  it("uses plain text only: no stray single asterisks or HTML", () => {
    const strip = (t: string) => t.replace(/\*\*[^*]+\*\*/g, "");
    for (const g of allGuides) for (const t of [g.intro ?? "", ...g.need, ...g.steps.flatMap((s) => [s.do, s.result ?? "", s.note ?? ""]), ...g.problems.flatMap((p) => [p.p, p.fix]), ...g.tips]) {
      expect(strip(t), `${g.slug}: ${t.slice(0, 40)}`).not.toMatch(/\*|<[a-z]/i);
    }
  });
  it("has no country in the guides' logic words: M-Pesa appears only as an example of mobile money", () => {
    for (const g of allGuides) for (const s of g.steps) expect(`${s.do} ${s.result ?? ""}`).not.toMatch(/\bM-Pesa\b|\bKRA\b|\beTIMS\b/);
  });
  it("has a capture spec with one mark per legend item for every screenshot", () => {
    const seen = new Set<string>();
    for (const { g, shot } of keys) {
      expect(seen.has(shot.key), `duplicate screenshot key ${shot.key}`).toBe(false);
      seen.add(shot.key);
      const spec = specByKey.get(shot.key);
      expect(spec, `${g}: no capture spec for ${shot.key}`).toBeTruthy();
      expect(spec!.marks.length, `${shot.key}: marks vs legend`).toBe(shot.legend?.length ?? 0);
      expect(shot.alt.length, shot.key).toBeGreaterThan(20);
    }
    for (const k of specByKey.keys()) expect(seen.has(k), `spec ${k} is not used by any guide`).toBe(true);
  });
  it("has the screenshot files (run npm run help:screens)", () => {
    const dir = path.resolve(__dirname, "../src/assets/help");
    for (const { shot } of keys) expect(fs.existsSync(path.join(dir, `${shot.key}.png`)), shot.key).toBe(true);
  });
});
