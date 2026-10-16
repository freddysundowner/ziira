import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { allModules } from "./index";

/**
 * A page's heading says what the sidebar says. Each menu entry is named by its `tab` (the family or short name) or else its `label`;
 * the page it opens must head itself with that name. A page that is only a tab of a family (`under`) may instead use its own label.
 * Headings that are not a plain `t("key")` (a record's number, a person's name) are skipped.
 */
const lookup = (tree: unknown, key: string): string | null => {
  let at: unknown = tree;
  for (const part of key.split(".")) {
    if (!at || typeof at !== "object" || !(part in at)) return null;
    at = (at as Record<string, unknown>)[part];
  }
  return typeof at === "string" ? at : null;
};

/** The heading texts a page file can show: every string key in its PageHeader title expression, resolved in the module's English. */
function headings(source: string, en: unknown): string[] | null {
  const header = /<PageHeader[^>]*?\btitle=\{([\s\S]*?)\}\s*(?:description|actions|back|\/>|>)/.exec(source)?.[1];
  if (!header || !header.includes("t(")) return null;
  const keys = [...header.matchAll(/"([\w.]+)"/g)].map((m) => m[1]);
  const found = keys.map((k) => lookup(en, k)).filter((v): v is string => v !== null);
  return found.length > 0 ? found : null;
}

describe("page headings match the sidebar", () => {
  for (const mod of allModules) {
    const en = mod.translations?.en;
    const name = (key: string | undefined): string | null => {
      if (!key || !key.includes(":")) return null;
      return lookup(en, key.split(":")[1] ?? "");
    };
    for (const entry of mod.menu ?? []) {
      if (!entry.area) continue;
      const route = mod.routes?.find((r) => r.path === entry.to);
      const imported = /\("([^"]+\.tsx)"\)/.exec(String(route?.page))?.[1];     // the dev transform writes the page's path
      const path = imported ? join(process.cwd(), imported) : undefined;
      if (!path) continue;
      const shown = headings(readFileSync(path, "utf8"), en);
      const sidebar = name(entry.tab) ?? name(entry.label);
      const own = name(entry.label);
      if (!shown || !sidebar) continue;
      it(`${mod.unit} ${entry.to}: "${shown.join(" / ")}" is "${sidebar}"`, () => {
        const allowed = entry.under ? [sidebar, own] : [sidebar];
        expect(shown.some((s) => allowed.includes(s))).toBe(true);
      });
    }
  }
  it("checks at least the main families", () => {
    expect(allModules.length).toBeGreaterThan(10);
  });
});
