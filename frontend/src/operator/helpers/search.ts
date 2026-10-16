import type { LucideIcon } from "lucide-react";

import { EXTRA_PAGES, type NavGroup, visibleNav } from "../nav";

/** One line in the search box: something to jump to. */
export interface Hit {
  /** "page" for a screen of the console, otherwise what the server found. */
  kind: "page" | "subscriber" | "invoice" | "plan" | "licence" | "operator";
  id: string;
  title: string;
  subtitle: string;
  to: string;
  icon?: LucideIcon;
}

export const MIN_QUERY = 2;

/** The screens the operator may open, as search lines. `label` turns a nav id into words in the current language. */
export function pageHits(groups: NavGroup[], permissions: readonly string[], missingFeatures: readonly string[], label: (id: string) => string, groupLabel: (key: string) => string): (Hit & { words: string })[] {
  const nav = visibleNav(groups, permissions, missingFeatures).flatMap((g) =>
    g.items.map((i) => ({ kind: "page" as const, id: i.id, title: label(i.id), subtitle: groupLabel(g.key), to: i.to, icon: i.icon, words: `${label(i.id)} ${i.keywords ?? ""}` })));
  const extra = EXTRA_PAGES.filter((p) => permissions.includes(p.permission)).map((p) => ({
    kind: "page" as const, id: p.id, title: label(p.id), subtitle: "", to: p.to, icon: p.icon, words: `${label(p.id)} ${p.keywords ?? ""}`,
  }));
  return [...nav, ...extra];
}

/** Screens whose name or keywords contain every word typed (any order, any case). Fewer than two characters finds none. */
export function matchPages<T extends { words: string }>(pages: T[], query: string, limit = 6): T[] {
  const q = query.trim().toLowerCase();
  if (q.length < MIN_QUERY) return [];
  const needles = q.split(/\s+/);
  return pages.filter((p) => needles.every((n) => p.words.toLowerCase().includes(n))).slice(0, limit);
}

/** Group hits by kind in a fixed order, keeping each kind's own order. */
export function groupHits<T extends { kind: string }>(hits: T[], order: readonly string[]): { kind: string; hits: T[] }[] {
  return order.map((kind) => ({ kind, hits: hits.filter((h) => h.kind === kind) })).filter((g) => g.hits.length > 0);
}

/** Arrow keys move the highlighted line and wrap around. */
export function moveIndex(current: number, delta: 1 | -1, count: number): number {
  if (count === 0) return 0;
  return (current + delta + count) % count;
}
