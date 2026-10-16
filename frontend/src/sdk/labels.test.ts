import { describe, expect, it } from "vitest";

import { allModules } from "@/modules";
import en from "@/i18n/en.json";
import sw from "@/i18n/sw.json";

import { AREA_DEFINITIONS } from "./areas";
import { AREA_IDS } from "./module";

type Tree = Record<string, unknown>;
const lookup = (tree: Tree, path: string): unknown => path.split(".").reduce<unknown>((o, p) => (o && typeof o === "object" ? (o as Tree)[p] : undefined), tree);
const isText = (v: unknown) => typeof v === "string" && v.length > 0;

describe("every label the navigation shows has real text in English and Swahili", () => {
  it("area names (and the fallback name) and Settings headings are in the shell translations", () => {
    const missing: string[] = [];
    for (const id of AREA_IDS) {
      for (const name of [id, AREA_DEFINITIONS[id].fallbackTitle].filter(Boolean)) {
        for (const [lang, tree] of [["en", en], ["sw", sw]] as const) if (!isText(lookup(tree, `nav.areas.${name}`))) missing.push(`${lang}: nav.areas.${name}`);
      }
      for (const s of AREA_DEFINITIONS[id].sections) {
        for (const [lang, tree] of [["en", en], ["sw", sw]] as const) if (!isText(lookup(tree, `nav.sections.${s}`))) missing.push(`${lang}: nav.sections.${s}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("every menu label, short name and search-word key resolves in both languages", () => {
    const missing: string[] = [];
    for (const m of allModules) {
      for (const item of m.menu ?? []) {
        for (const key of [item.label, item.tab, item.keywords]) {
          if (!key) continue;
          const [ns, path] = key.includes(":") ? key.split(":") : [undefined, key];
          for (const lang of ["en", "sw"] as const) {
            const tree = ns ? m.translations?.[lang] ?? {} : lang === "en" ? en : sw;
            const owner = ns && ns !== m.unit && ns !== "kernel" ? allModules.find((x) => x.unit === ns)?.translations?.[lang] ?? {} : tree;
            if (!isText(lookup(owner as Tree, path))) missing.push(`${lang}: ${key}`);
          }
        }
      }
    }
    expect(missing).toEqual([]);
  });
});
