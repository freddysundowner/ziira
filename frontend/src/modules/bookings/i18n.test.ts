import { describe, expect, it } from "vitest";

import enDesk from "./i18n/en.desk.json";
import enOps from "./i18n/en.ops.json";
import en0 from "./i18n/en.json";
import swDesk from "./i18n/sw.desk.json";
import swOps from "./i18n/sw.ops.json";
import sw0 from "./i18n/sw.json";

const en = { ...en0, ...enDesk, ...enOps } as Record<string, unknown>;
const sw = { ...sw0, ...swDesk, ...swOps } as Record<string, unknown>;

const keys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));

describe("bookings translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("keep the same placeholders in both languages", () => {
    const flat = (o: Record<string, unknown>): Record<string, string> => Object.fromEntries(keys(o).map((k) => [k, k.split(".").reduce<unknown>((x, p) => (x as Record<string, unknown>)[p], o) as string]));
    const e = flat(en), s = flat(sw);
    const holes = (text: string) => (text.match(/{{\w+}}/g) ?? []).sort();
    for (const k of Object.keys(e)) expect(holes(s[k] ?? ""), k).toEqual(holes(e[k] ?? ""));
  });
});
