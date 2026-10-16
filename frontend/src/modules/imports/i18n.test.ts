import { describe, expect, it } from "vitest";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";
import { OPENING_STEPS } from "./lib/checklist";

const keys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));

describe("imports translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("name the guide link and every guide step (the page never shows a raw key)", () => {
    for (const lang of [en, sw]) {
      const all = new Set(keys(lang));
      for (const k of ["guide.link", "guide.title", "guide.hint", "guide.before", "guide.beforeHint", "guide.done", "guide.unavailable", "guide.import", "guide.open"]) expect(all.has(k), k).toBe(true);
      for (const step of OPENING_STEPS) {
        expect(all.has(`guide.steps.${step.id}.title`), step.id).toBe(true);
        expect(all.has(`guide.steps.${step.id}.text`), step.id).toBe(true);
      }
    }
  });
});
