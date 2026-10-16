import type { Lang } from "../content/types";
import { navGroups, type NavGroup, type NavLink } from "../content/nav";
import { urlFor } from "./registry";

export interface ResolvedLink extends Omit<NavLink, "id" | "href"> { href: string }
export interface ResolvedGroup { key: string; label: string; href: string; mega?: boolean; right?: boolean; columns: { title?: string; links: ResolvedLink[] }[]; foot?: ResolvedLink }

/** A link to a page that does not exist (yet) is dropped, so optional pages can come and go. */
function resolveLink(l: NavLink, lang: Lang): ResolvedLink | null {
  if (l.href) return { ...l, href: l.href };
  try { return { ...l, href: urlFor(l.id!, lang) }; } catch { return null; }
}

export function resolveNav(lang: Lang): ResolvedGroup[] {
  const out: ResolvedGroup[] = [];
  for (const g of navGroups as NavGroup[]) {
    const columns = g.columns
      .map((c) => ({ title: c.title, links: c.links.map((l) => resolveLink(l, lang)).filter((x): x is ResolvedLink => !!x) }))
      .filter((c) => c.links.length > 0);
    const top = resolveLink({ ...g.to, label: g.label }, lang) ?? columns[0]?.links[0];
    if (!top) continue;
    const foot = g.foot ? resolveLink(g.foot, lang) ?? undefined : undefined;
    out.push({ key: g.key, label: g.label, href: top.href, mega: g.mega, right: g.right, columns, foot });
  }
  return out;
}
