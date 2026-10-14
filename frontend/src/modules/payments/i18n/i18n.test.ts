import { describe, expect, it } from "vitest";

import en from "./en.json";
import sw from "./sw.json";

const keys = (o: Record<string, unknown>, p = ""): string[] =>
  Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${p}${k}.`) : [`${p}${k}`]));

describe("payments translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
});
