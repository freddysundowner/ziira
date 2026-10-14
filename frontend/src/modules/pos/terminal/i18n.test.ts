import { describe, expect, it } from "vitest";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

function keys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe("terminal translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
});
