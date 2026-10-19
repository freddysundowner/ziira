import { describe, expect, it } from "vitest";

import en from "./i18n/en.json";
import enGarage from "./i18n/en.garage.json";
import sw from "./i18n/sw.json";
import swGarage from "./i18n/sw.garage.json";

const keys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));

describe("jobs translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("have the same garage keys in English and Swahili", () => {
    expect(keys(swGarage).sort()).toEqual(keys(enGarage).sort());
  });
  it("keep the same placeholders in the garage texts", () => {
    const flat = (o: Record<string, unknown>): Record<string, string> => Object.fromEntries(keys(o).map((k) => [k, k.split(".").reduce<unknown>((x, p) => (x as Record<string, unknown>)[p], o) as string]));
    const e = flat(enGarage), s = flat(swGarage);
    const holes = (text: string) => (text.match(/{{\w+}}/g) ?? []).sort();
    for (const k of Object.keys(e)) expect(holes(s[k] ?? ""), k).toEqual(holes(e[k] ?? ""));
  });
  it("keep the same placeholders in both languages", () => {
    const flat = (o: Record<string, unknown>): Record<string, string> => Object.fromEntries(keys(o).map((k) => [k, k.split(".").reduce<unknown>((x, p) => (x as Record<string, unknown>)[p], o) as string]));
    const e = flat(en), s = flat(sw);
    const holes = (text: string) => (text.match(/{{\w+}}/g) ?? []).sort();
    for (const k of Object.keys(e)) expect(holes(s[k] ?? ""), k).toEqual(holes(e[k] ?? ""));
  });
});
