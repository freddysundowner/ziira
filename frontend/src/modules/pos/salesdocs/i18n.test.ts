import { describe, expect, it } from "vitest";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

function keys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe("sales documents translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("keep the same {{placeholders}} in both languages", () => {
    const flat = (o: unknown, p = ""): Record<string, string> =>
      typeof o === "string" ? { [p]: o } : Object.entries(o as object).reduce((a, [k, v]) => ({ ...a, ...flat(v, p ? `${p}.${k}` : k) }), {});
    const marks = (s: string) => (s.match(/{{\s*\w+\s*}}/g) ?? []).sort().join();
    const e = flat(en), w = flat(sw);
    for (const k of Object.keys(e)) expect(marks(w[k] ?? ""), k).toBe(marks(e[k]));
  });
});
