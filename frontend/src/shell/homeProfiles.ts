/**
 * What Home shows for each kind of business. Data, not code: a table from "kind of business" to the Home boxes that matter to it.
 *
 * The kind is read from what the business already has, never from a name or a country: an industry pack that is switched on
 * (a salon, a garage ...) wins, else the edition the business registered for. A box is named by its slot label
 * (`widgetId`), the same key the owning module registers in "dashboard.widgets". A box that is not in the business's
 * permitted set (unit off, no permission) is simply skipped. See docs/plans/home-by-industry.md.
 */
import type { AreaId, ProfileId } from "@/sdk";

export { profileFor, type ProfileId } from "@/sdk";

export interface HomeProfile {
  /** Boxes shown first, as compact number tiles (the first four that exist). */
  stats: readonly string[];
  /** Boxes shown next as lists, in this order. */
  lists: readonly string[];
  /** Areas whose shortcuts come first. */
  areas: readonly AreaId[];
}

/** The ids of the Home boxes (their `dashboard.widgets` labels). */
export const W = {
  salesToday: "pos:todaySales",
  openTills: "pos:openTills",
  lowStock: "inventory:lowStockTitle",
  things: "intel:findingsWidget",
  figure: "command:todayWidget",
  approvals: "kernel:widgetApprovalsTitle",
  exceptions: "kernel:widgetExceptionsTitle",
  receivables: "crm:receivablesWidget",
  billsDue: "purchasing:billsDue",
  money: "finance:widget.title",
  received: "payments:todayWidget",
  people: "people:widget.title",
  appointments: "bookings:widget.today",
  jobs: "jobs:widget.title",
  work: "timebilling:widget.title",
  connect: "connect:widgetTitle",
  products: "catalog_stats:widgetTitle",
} as const;

/** Tiles that hold several figures side by side: given two columns until the row is wide enough. */
export const WIDE: ReadonlySet<string> = new Set([W.jobs, W.money]);

export const PROFILES: Record<ProfileId, HomeProfile> = {
  retail: {
    stats: [W.salesToday, W.openTills, W.lowStock, W.things],
    lists: [W.approvals, W.exceptions, W.received, W.figure],
    areas: ["sell", "stock", "customers", "money"],
  },
  distribution: {
    stats: [W.salesToday, W.receivables, W.lowStock, W.billsDue],
    lists: [W.things, W.approvals, W.exceptions, W.received],
    areas: ["sell", "stock", "buy", "customers", "money"],
  },
  books: {
    stats: [W.money, W.receivables, W.billsDue, W.received],
    lists: [W.things, W.approvals, W.exceptions],
    areas: ["money", "customers", "buy"],
  },
  intelligence: {
    stats: [W.things, W.figure, W.connect],
    lists: [W.approvals, W.exceptions],
    areas: ["command", "connect"],
  },
  salon: {
    stats: [W.appointments, W.salesToday, W.received, W.things],
    lists: [W.approvals, W.exceptions, W.people],
    areas: ["services", "sell", "customers", "people"],
  },
  garage: {
    stats: [W.jobs, W.salesToday, W.receivables, W.things],
    lists: [W.approvals, W.exceptions, W.lowStock, W.billsDue],
    areas: ["services", "sell", "customers", "stock"],
  },
  clinic: {
    stats: [W.appointments, W.received, W.receivables, W.things],
    lists: [W.approvals, W.exceptions, W.people],
    areas: ["services", "customers", "money"],
  },
  gym: {
    stats: [W.appointments, W.received, W.receivables, W.things],
    lists: [W.approvals, W.exceptions, W.people],
    areas: ["services", "customers", "sell"],
  },
  professional: {
    stats: [W.work, W.approvals, W.receivables, W.appointments],
    lists: [W.things, W.exceptions, W.people],
    areas: ["services", "customers", "money", "people"],
  },
  education: {
    stats: [W.appointments, W.received, W.receivables, W.things],
    lists: [W.approvals, W.exceptions, W.people],
    areas: ["services", "customers", "money"],
  },
  services: {
    stats: [W.appointments, W.jobs, W.work, W.received],
    lists: [W.things, W.approvals, W.exceptions, W.people],
    areas: ["services", "sell", "customers"],
  },
  full: {
    stats: [W.salesToday, W.things, W.lowStock, W.receivables],
    lists: [W.approvals, W.exceptions, W.billsDue, W.received, W.figure],
    areas: ["sell", "customers", "stock", "money"],
  },
};

/** Tops a row of number tiles up when the business has fewer than this many. */
export const MIN_STATS = 3;
export const MAX_STATS = 4;
const TOP_UP = [W.things, W.salesToday, W.received, W.receivables, W.figure, W.approvals];

export interface Arranged {
  stats: string[];
  lists: string[];
  more: string[];
}

/** Sorts the boxes this person may see: number tiles first, then lists, the rest behind "More". Boxes that do not exist are skipped. */
export function arrange(profile: HomeProfile, available: readonly string[]): Arranged {
  const have = new Set(available);
  const stats = profile.stats.filter((id) => have.has(id));
  for (const id of TOP_UP) if (stats.length < MIN_STATS && have.has(id) && !stats.includes(id)) stats.push(id);
  const tiles = stats.slice(0, MAX_STATS);
  const lists = profile.lists.filter((id) => have.has(id) && !tiles.includes(id));
  const more = available.filter((id) => !tiles.includes(id) && !lists.includes(id));
  return { stats: tiles, lists, more };
}

/** Shortcut order: the areas this kind of business uses most first, the others after in their usual order. */
export function orderAreas<T extends { id: AreaId }>(areas: readonly T[], preferred: readonly AreaId[]): T[] {
  const rank = (id: AreaId) => { const i = preferred.indexOf(id); return i === -1 ? preferred.length : i; };
  return [...areas].sort((a, b) => rank(a.id) - rank(b.id));
}
