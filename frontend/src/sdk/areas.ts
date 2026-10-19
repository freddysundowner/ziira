/**
 * The sidebar's areas. A menu entry that names an `area` is a page listed under that area's section in the sidebar (or a row of the
 * Settings list), so the sidebar holds one expandable entry per area instead of one flat list of every page. Pure functions (no React):
 * which areas a person sees, in what order, and which area a URL belongs to. The shell draws them (shell/Sidebar.tsx, shell/AreaFrame.tsx).
 */
import { matchPath } from "react-router-dom";

import { AREA_IDS, type AreaId, type MenuGroup, type MenuItem, type ModuleDefinition, type PageRoute } from "./module";
import { TILL_PAGES, type SidebarPlan } from "./kindProfile";
import { type Access, type NavItem, visibleMenu } from "./registry";

export interface AreaDefinition {
  icon: string;
  /** The edition's menu group that orders this area among the others (none: right after Home). */
  group?: MenuGroup;
  /** "list": a section of the sidebar that expands to its pages. "side": one sidebar entry, its pages listed on the left of the page (Settings). */
  variant: "list" | "side";
  /** Settings headings in display order (entries may use others; they follow). */
  sections: readonly string[];
  /** When none of these units contributes a page, the area is called "nav.areas.<fallback>" instead (the Command Center without Intelligence is an inbox). */
  coreUnits?: readonly string[];
  fallbackTitle?: string;
}

export const AREA_DEFINITIONS: Record<AreaId, AreaDefinition> = {
  waiting: { icon: "bell", variant: "list", sections: [] },
  command: { icon: "dashboard", variant: "list", sections: [], coreUnits: ["command", "intel"], fallbackTitle: "inbox" },
  sell: { icon: "sales", group: "sell", variant: "list", sections: [] },
  services: { icon: "calendar", group: "services", variant: "list", sections: [] },
  customers: { icon: "customers", group: "sell", variant: "list", sections: [] },
  stock: { icon: "stock", group: "stock", variant: "list", sections: [] },
  buy: { icon: "suppliers", group: "buy", variant: "list", sections: [] },
  money: { icon: "finance", group: "money", variant: "list", sections: [] },
  people: { icon: "people", group: "people", variant: "list", sections: [] },
  connect: { icon: "spark", group: "admin", variant: "list", sections: [] },
  addons: { icon: "boxes", group: "admin", variant: "list", sections: [] },
  settings: { icon: "settings", group: "admin", variant: "side", sections: ["business", "access", "channels", "intelligence", "data", "platform"] },
};

export interface NavArea {
  id: AreaId;
  icon: string;
  /** Translation key of the sidebar name. */
  titleKey: string;
  variant: "list" | "side";
  /** The pages the person may open, in display order (Settings: grouped by heading). */
  items: NavItem[];
  /** Rarely used pages, listed last in the section. */
  setup: NavItem[];
  /** Pages that share one sidebar entry: the entry's own page first, then its other pages (a small tab bar on each switches between them). Only entries with two or more. */
  families: Record<string, NavItem[]>;
  /** A prominent button above the pages (e.g. "Point of sale" in Sell). */
  primary: NavItem[];
  /** Settings: headings that have at least one page, in display order ("" holds pages without one). */
  sections: string[];
}

/** One sidebar entry: an area, or a menu entry that names no area (third-party modules). */
export type SidebarEntry = { kind: "area"; area: NavArea } | { kind: "item"; item: NavItem };

export interface Navigation {
  entries: SidebarEntry[];
  areas: NavArea[];
}

const orderOf = (i: MenuItem) => i.order ?? 100;
const byOrder = (list: NavItem[]) => list.map((item, n) => ({ item, n })).sort((a, b) => orderOf(a.item) - orderOf(b.item) || a.n - b.n).map((x) => x.item);

function buildArea(id: AreaId, items: NavItem[]): NavArea | null {
  const def = AREA_DEFINITIONS[id];
  const mine = items.filter((i) => i.area === id);
  if (mine.length === 0) return null;
  const listed = byOrder(mine.filter((i) => !i.primary));
  const side = def.variant === "side";
  // A page whose entry is not available to this person gets an entry of its own, so it stays reachable.
  const entries = listed.filter((i) => side || !i.under || !listed.some((h) => h.to === i.under));
  const families: Record<string, NavItem[]> = {};
  for (const head of entries) {
    const rest = listed.filter((i) => i.under === head.to && !entries.includes(i));
    if (rest.length) families[head.to] = [head, ...rest];
  }
  const rank = (i: NavItem) => (def.sections.includes(i.section ?? "") ? def.sections.indexOf(i.section ?? "") : def.sections.length);
  const regular = entries.filter((i) => side || !i.setup);
  const ordered = side ? regular.map((item, n) => ({ item, n })).sort((a, b) => rank(a.item) - rank(b.item) || a.n - b.n).map((x) => x.item) : regular;
  const ownsCore = !def.coreUnits || mine.some((i) => def.coreUnits?.includes(i.unit));
  return {
    id, icon: def.icon, variant: def.variant, items: ordered, setup: side ? [] : entries.filter((i) => i.setup), families, primary: mine.filter((i) => i.primary),
    sections: side ? [...new Set(ordered.map((i) => i.section ?? ""))] : [],
    titleKey: `nav.areas.${ownsCore || !def.fallbackTitle ? id : def.fallbackTitle}`,
  };
}

/**
 * The sidebar for this person: areas that have at least one page they may open, in the edition's order (Settings always last),
 * then entries that belong to no area. Pages of a unit that is off are absent because only active modules are passed in.
 */
export function buildNavigation(modules: readonly ModuleDefinition[], access: Access, groupOrder: readonly MenuGroup[], plan?: SidebarPlan): Navigation {
  const till = (i: NavItem) => !!i.primary || TILL_PAGES.includes(i.to);
  const items = visibleMenu(modules, access).filter((i) => !i.hidden && (plan?.till !== false || !till(i)));
  const areas = AREA_IDS.map((id) => buildArea(id, items)).filter((a): a is NavArea => a !== null)
    .map((a) => (plan?.till === false && a.id === "sell" ? { ...a, titleKey: "nav.areas.sellNoTill" } : a));   // no counter: Sell is invoices and payments
  const rank = (a: NavArea) => {
    if (a.id === "settings") return Number.MAX_SAFE_INTEGER;
    const group = AREA_DEFINITIONS[a.id].group;
    if (!group) return -1;
    const own = plan ? plan.order.indexOf(a.id) : -1;
    if (own !== -1) return own;
    const at = groupOrder.indexOf(group);
    return (plan?.order.length ?? 0) + (at === -1 ? groupOrder.length : at);
  };
  const sorted = areas
    .map((area, n) => ({ area, n }))
    .sort((a, b) => rank(a.area) - rank(b.area) || a.n - b.n)
    .map((x) => x.area);
  const loose = items.filter((i) => !i.area).map((item): SidebarEntry => ({ kind: "item", item }));
  const entries = sorted.map((area): SidebarEntry => ({ kind: "area", area }));
  const last = entries.at(-1);
  if (last?.kind === "area" && last.area.id === "settings") entries.splice(entries.length - 1, 0, ...loose);
  else entries.push(...loose);
  return { entries, areas };
}

/** The sidebar entries of an area, in order (the till button first). */
export function areaPages(area: NavArea): NavItem[] {
  return [...area.primary, ...area.items, ...area.setup];
}

/** Every page of an area, including the other pages of an entry's family. */
export function areaMembers(area: NavArea): NavItem[] {
  return [...new Set([...areaPages(area), ...Object.values(area.families).flat()])];
}

/** An area with one page (or Settings, whose pages are listed in the page itself) is a plain link in the sidebar, not an expandable section. */
export function isSingle(area: NavArea): boolean {
  return area.variant === "side" || areaPages(area).length <= 1;
}

/** Where an area's sidebar entry leads when it is a link (or collapsed to an icon): its first page. */
export function areaEntryPath(area: NavArea): string {
  return (area.items[0] ?? area.primary[0] ?? area.setup[0]).to;
}

export interface Placement {
  area: NavArea;
  /** The page that is open. */
  item: NavItem;
  /** The sidebar entry it is listed under (the page itself unless it is in a family). */
  head: NavItem;
}

/** Specific routes first: fewer ":params", then longer paths. */
const specificity = (a: PageRoute, b: PageRoute) => a.path.split(":").length - b.path.split(":").length || b.path.length - a.path.length;

/**
 * Which area and page a URL belongs to, or null (Home, My account, pages no entry owns). Order: an entry whose path is this page,
 * then the page's own `tab` declaration, then the entry with the longest path that is a prefix of the URL.
 */
export function placeOf(areas: readonly NavArea[], routes: readonly PageRoute[], pathname: string): Placement | null {
  const all = areas.flatMap((area) => areaMembers(area).map((item) => ({ area, item, head: area.items.concat(area.setup).find((h) => h.to === item.under) ?? item })));
  const exact = all.find(({ item }) => matchPath({ path: item.to, end: true }, pathname));
  if (exact) return exact;
  const declared = routes.filter((r) => r.tab && matchPath({ path: r.path, end: true }, pathname)).sort(specificity)[0];
  const byDeclaration = declared && all.find(({ item }) => item.to === declared.tab);
  if (byDeclaration) return byDeclaration;
  const prefixes = all.filter(({ item }) => item.to !== "/" && pathname.startsWith(`${item.to}/`)).sort((a, b) => b.item.to.length - a.item.to.length);
  return prefixes[0] ?? null;
}

/** Settings pages under one heading, in display order. */
export function itemsOfSection(area: NavArea, section: string): NavItem[] {
  return area.items.filter((t) => (t.section ?? "") === section);
}
