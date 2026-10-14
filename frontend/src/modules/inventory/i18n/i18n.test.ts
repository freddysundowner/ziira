import { describe, expect, it } from "vitest";

import en from "./en.json";
import sw from "./sw.json";

const keys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));

describe("inventory translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("leave no string empty", () => {
    expect([...keys(en), ...keys(sw)].length).toBeGreaterThan(0);
    for (const value of [en, sw]) expect(JSON.stringify(value)).not.toContain('""');
  });
});
