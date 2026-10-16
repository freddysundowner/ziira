import { describe, expect, it } from "vitest";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

const keys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));

describe("connect translations", () => {
  it("have the same keys in English and Swahili", () => {
    expect(keys(sw).sort()).toEqual(keys(en).sort());
  });
  it("say 'outside system' on Home and in the coverage panel, so the two never seem to disagree", () => {
    for (const text of [en.widget.connected_one, en.widget.connected_other, en.coverage.nothing, en.first.title]) expect(text).toMatch(/outside system/);
    for (const text of [sw.widget.connected_one, sw.widget.connected_other, sw.coverage.nothing]) expect(text).toMatch(/wa nje|ya nje/);
  });
});
