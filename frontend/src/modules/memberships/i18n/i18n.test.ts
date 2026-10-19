import { describe, expect, it } from "vitest";

import en from "./en.json";
import enGym from "./en.gym.json";
import sw from "./sw.json";
import swGym from "./sw.gym.json";

const keys = (o: Record<string, unknown>, p = ""): string[] =>
  Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${p}${k}.`) : [`${p}${k}`]));

describe("memberships translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });

  it("has the same keys in the gym screens' English and Swahili", () => {
    expect(keys(swGym).sort()).toEqual(keys(enGym).sort());
  });

  it("does not reuse a top-level key of the main files", () => {
    const main = new Set(Object.keys(en));
    expect(Object.keys(enGym).filter((k) => main.has(k))).toEqual([]);
  });

  it("leaves no text empty", () => {
    const empty = (o: Record<string, unknown>): string[] => keys(o).filter((k) => k.split(".").reduce<unknown>((a, p) => (a as Record<string, unknown>)[p], o) === "");
    expect(empty(enGym)).toEqual([]);
    expect(empty(swGym)).toEqual([]);
  });
});
