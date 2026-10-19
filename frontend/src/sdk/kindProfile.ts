/**
 * The kind of business, and how the sidebar is arranged for it. One resolver shared by Home (shell/homeProfiles.ts) and the sidebar.
 * Data, not code: no country, no business names. The kind is read from what the business already has: an industry pack that is
 * switched on wins, else the edition it registered for (the sign-up's business type only ever chooses one of these).
 */
import type { AreaId } from "./module";

export type ProfileId =
  | "retail" | "distribution" | "books" | "intelligence"
  | "salon" | "garage" | "clinic" | "gym" | "professional" | "education" | "services" | "full";

/** Installed industry packs and the kind of business each one means (a pack is a unit, so it is in the enabled set). */
const PACKS: ReadonlyArray<readonly [string, ProfileId]> = [
  ["pack_clinic", "clinic"], ["pack_garage", "garage"], ["pack_fitness", "gym"],
  ["pack_salon", "salon"], ["pack_professional", "professional"], ["pack_education", "education"],
];
const EDITIONS: Readonly<Record<string, ProfileId>> = {
  retail: "retail", distribution: "distribution", books: "books", intelligence: "intelligence", services: "services",
};

/** The kind of business: a switched-on industry pack, else the edition; anything unknown is the all-round "full". */
export function profileFor(editionId: string | undefined, enabledUnits: ReadonlySet<string>): ProfileId {
  for (const [unit, id] of PACKS) if (enabledUnits.has(unit)) return id;
  return (editionId && EDITIONS[editionId]) || "full";
}

export interface SidebarPlan {
  /** Areas that follow Intelligence, in this order; the others follow in the edition's order. Empty: the edition's order alone. */
  order: readonly AreaId[];
  /** Sections that start open (Intelligence always does, and so does the one you are in). A choice made by hand wins. */
  open: readonly AreaId[];
  /** Whether this kind of business sells over a counter: only then are the till and "Tills and devices" listed. */
  till: boolean;
}

const SERVICE: SidebarPlan = { order: ["services", "customers", "sell", "money", "stock", "buy", "people"], open: ["services", "customers"], till: false };

export const SIDEBAR: Record<ProfileId, SidebarPlan> = {
  retail: { order: ["sell", "stock", "customers", "money", "buy", "people"], open: ["sell", "stock"], till: true },
  distribution: { order: ["sell", "buy", "stock", "customers", "money", "people"], open: ["sell", "buy", "stock"], till: true },
  books: { order: ["money", "buy", "customers", "people"], open: ["money", "buy"], till: false },
  intelligence: { order: ["connect", "money"], open: ["connect"], till: false },
  salon: SERVICE,
  clinic: SERVICE,
  gym: SERVICE,
  education: SERVICE,
  services: SERVICE,
  garage: { order: ["services", "sell", "customers", "stock", "buy", "money", "people"], open: ["services", "sell"], till: false },
  professional: { order: ["services", "customers", "money", "sell", "people"], open: ["services", "customers"], till: false },
  full: { order: [], open: [], till: true },
};

/** Menu entries that exist only for a till (hidden from the menu, never from the router, when the kind has none). */
export const TILL_PAGES: readonly string[] = ["/pos/tills", "/pos/devices"];
