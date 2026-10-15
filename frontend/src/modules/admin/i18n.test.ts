import { describe, expect, it } from "vitest";

import en from "./i18n/en.admin.json";
import sw from "./i18n/sw.admin.json";
import enAi from "./i18n/en.ai.json";
import enOrg from "./i18n/en.org.json";
import swAi from "./i18n/sw.ai.json";
import enApps from "./i18n/en.apps.json";
import swApps from "./i18n/sw.apps.json";
import swOrg from "./i18n/sw.org.json";

const keys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));
const flat = (o: Record<string, unknown>): Record<string, string> =>
  Object.fromEntries(keys(o).map((k) => [k, k.split(".").reduce<unknown>((x, p) => (x as Record<string, unknown>)[p], o) as string]));

describe("admin translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("keep the same placeholders in both languages", () => {
    const e = flat(en), s = flat(sw);
    const holes = (text: string) => (text.match(/{{\w+}}/g) ?? []).sort();
    for (const k of Object.keys(e)) expect(holes(s[k] ?? ""), k).toEqual(holes(e[k] ?? ""));
  });
  it("has the organisation screens in both languages with the same keys and placeholders", () => {
    expect(keys(swOrg).sort()).toEqual(keys(enOrg).sort());
    const e = flat(enOrg), w = flat(swOrg);
    const holes = (text: string) => (text.match(/{{\w+}}/g) ?? []).sort();
    for (const k of Object.keys(e)) expect(holes(w[k] ?? ""), k).toEqual(holes(e[k] ?? ""));
  });
  it("has the AI assistant screen in both languages with the same keys and placeholders", () => {
    expect(keys(swAi).sort()).toEqual(keys(enAi).sort());
    const e = flat(enAi), w = flat(swAi);
    const holes = (text: string) => (text.match(/{{\w+}}/g) ?? []).sort();
    for (const k of Object.keys(e)) expect(holes(w[k] ?? ""), k).toEqual(holes(e[k] ?? ""));
  });
  it("has the Apps & plugins screen in both languages with the same keys and placeholders", () => {
    expect(keys(swApps).sort()).toEqual(keys(enApps).sort());
    const e = flat(enApps), w = flat(swApps);
    const holes = (text: string) => (text.match(/{{\w+}}/g) ?? []).sort();
    for (const k of Object.keys(e)) expect(holes(w[k] ?? ""), k).toEqual(holes(e[k] ?? ""));
  });
});
