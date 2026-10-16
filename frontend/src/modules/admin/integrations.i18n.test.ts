import { describe, expect, it } from "vitest";

import en from "./i18n/en.integrations.json";
import sw from "./i18n/sw.integrations.json";

const keys = (o: Record<string, unknown>, p = ""): string[] =>
  Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${p}${k}.`) : [`${p}${k}`]));
const holes = (s: string) => (s.match(/{{\w+}}/g) ?? []).sort();

describe("integration translations", () => {
  it("have the same keys and placeholders in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
    const flat = (o: Record<string, unknown>) => Object.fromEntries(keys(o).map((k) => [k, k.split(".").reduce<unknown>((x, p) => (x as Record<string, unknown>)[p], o) as string]));
    const e = flat(en), s = flat(sw);
    for (const k of Object.keys(e)) expect(holes(s[k] ?? ""), k).toEqual(holes(e[k] ?? ""));
  });
});
