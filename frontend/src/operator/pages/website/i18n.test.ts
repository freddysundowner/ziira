import { describe, expect, it } from "vitest";

import en from "../../i18n/en.website.json";
import sw from "../../i18n/sw.website.json";

function keys(value: unknown, prefix = ""): string[] {
  if (value && typeof value === "object") return Object.entries(value).flatMap(([k, v]) => keys(v, `${prefix}${k}.`));
  return [prefix.slice(0, -1)];
}
function texts(value: unknown): string[] {
  if (value && typeof value === "object") return Object.values(value).flatMap(texts);
  return [String(value)];
}
const placeholders = (s: string) => (s.match(/\{\{\w+\}\}/g) ?? []).sort().join();

describe("website area translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("leave no empty text and keep the same placeholders", () => {
    const e = texts(en), s = texts(sw);
    expect(e.every((t) => t.trim() !== "")).toBe(true);
    expect(s.every((t) => t.trim() !== "")).toBe(true);
    expect(s.map(placeholders)).toEqual(e.map(placeholders));
  });
});
