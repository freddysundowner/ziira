import { describe, expect, it } from "vitest";

import commandEn from "../command/i18n/en.json";
import commandSw from "../command/i18n/sw.json";
import banned from "./bannedTerms.json";
import en from "./i18n/en.json";
import enPlain from "./i18n/en.plain.json";
import sw from "./i18n/sw.json";
import swPlain from "./i18n/sw.plain.json";

type Tree = { [key: string]: string | Tree };

/** Every string in a tree, with its dotted key; `tech` subtrees (the Expert layer) and `keywords` (search aliases) are left out. */
function strings(tree: Tree, prefix = ""): [string, string][] {
  return Object.entries(tree).flatMap(([k, v]) => {
    if (k === "tech" || k === "keywords") return [];
    return typeof v === "string" ? [[`${prefix}${k}`, v] as [string, string]] : strings(v, `${prefix}${k}.`);
  });
}
const keys = (tree: Tree, prefix = ""): string[] => Object.entries(tree).flatMap(([k, v]) => (typeof v === "string" ? [`${prefix}${k}`] : keys(v, `${prefix}${k}.`)));
const found = (text: string, list: readonly string[]) => list.filter((w) => new RegExp(`(?<![\\w])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w])`, "i").test(text));

const english: Tree = { ...(en as Tree), ...(enPlain as Tree) };
const swahili: Tree = { ...(sw as Tree), ...(swPlain as Tree) };

describe("Intelligence speaks plain words", () => {
  it("has the same keys in English and Swahili", () => {
    expect(keys(swahili).sort()).toEqual(keys(english).sort());
    expect(keys(commandSw as Tree).sort()).toEqual(keys(commandEn as Tree).sort());
  });
  it("uses no technical word in the English text a business person reads", () => {
    const bad = [...strings(english), ...strings(commandEn as Tree)].filter(([, text]) => found(text, banned.words).length > 0);
    expect(bad.map(([k, text]) => `${k}: ${text}`)).toEqual([]);
  });
  it("uses no technical word in the Swahili text either", () => {
    const bad = [...strings(swahili), ...strings(commandSw as Tree)].filter(([, text]) => found(text, banned.swahili).length > 0);
    expect(bad.map(([k, text]) => `${k}: ${text}`)).toEqual([]);
  });
  it("names the new places the way a business does", () => {
    expect(english.today).toMatchObject({ menu: "Today" });
    expect((english.things as Tree).menu).toBe("Things to look at");
    expect((english.watch as Tree).menu).toBe("What Ziira watches");
    expect((english.how as Tree).menu).toBe("How much Ziira does for you");
    expect((english.alerts as Tree).menu).toBe("Where you hear from Ziira");
    expect(Object.values((english.how as Tree).mode as Tree).map((m) => (m as Tree).name)).toEqual(["Watch", "Ask", "Prepare", "Act for me"]);
    expect([english.band as Tree].map((b) => [b.urgent, b.soon, b.look])[0]).toEqual(["Urgent", "Soon", "Worth a look"]);
  });
});
