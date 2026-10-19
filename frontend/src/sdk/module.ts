/**
 * The frontend module manifest: what a module adds to the app.
 *
 * Every frontend module mirrors a backend unit (same name in `unit`). The shell shows a module only
 * when the business has that unit enabled, and each page, menu item and slot contribution only to
 * users holding its permission.
 */
import type { ComponentType } from "react";

/** Props every slot contribution receives: whatever the slot's owner passes (e.g. { productId }). */
export type SlotProps = Record<string, unknown>;

type Lazy<P> = () => Promise<{ default: ComponentType<P> }>;

export interface PageRoute {
  /** URL path, e.g. "/products" or "/products/:productId". */
  path: string;
  /** The page, loaded only when first opened. */
  page: Lazy<object>;
  /** Permission needed to open it (anywhere in the user's scope). */
  permission?: string;
  /** Set instead of a permission for a page every signed-in user may open (e.g. their own account). */
  anySignedIn?: boolean;
  /**
   * The menu entry (its `to`) this page belongs to, for pages that sit under no entry by their path alone
   * (e.g. "/payslips/:id" belongs to "/payroll", which keeps that section open). Without it the longest entry whose path is a prefix of this page's path is used.
   */
  tab?: string;
}

export interface MenuItem {
  /** Translation key, e.g. "products:menu". */
  label: string;
  to: string;
  permission?: string;
  /** Lower numbers come first. */
  order?: number;
  /** Where an entry without an `area` sits in the order of the edition's groups. */
  group?: MenuGroup;
  /** Icon name from the SDK's icon set (see sdk/icons.tsx). */
  icon?: string;
  /**
   * The sidebar area that owns this entry. An entry with an area is listed under that area's expandable section in the sidebar (or is a row of the Settings list). Without an area (and not `hidden`) the entry is a sidebar item of its own.
   */
  area?: AreaId;
  /** Settings only: the heading this page is listed under (ids are listed per area in sdk/areas.ts). */
  section?: string;
  /** The `to` of the sidebar entry this page shares: the entry covers both pages and each shows a small tab bar to switch (use only for pages that are the same kind of list, e.g. Quotations and Sales orders). */
  under?: string;
  /** Name (translation key) in the sidebar or the Settings list when it differs from `label` (which search and the tab bar use): the name of a family of pages, or a shorter name. */
  tab?: string;
  /** A rarely used page (setup, devices): listed last in its section. */
  setup?: boolean;
  /** A prominent button at the top of the area's section (e.g. "Point of sale" in Sell). */
  primary?: boolean;
  /** Translation key of extra words search matches (other names people know the page by: "apps plugins add-ons"). */
  keywords?: string;
  /** Not in the sidebar, only found by search (e.g. "My account", opened from the account menu). */
  hidden?: boolean;
  /** Listed only while this navigation flag is on (see sdk/navFlags.ts: a module switches a flag from a `shell.background` slot component). */
  when?: string;
}

/** The edition's ordering groups (an edition lists them in the order its areas appear). */
export const MENU_GROUPS = ["sell", "services", "stock", "buy", "money", "people", "admin"] as const;
export type MenuGroup = (typeof MENU_GROUPS)[number];

/** Sidebar areas (one sidebar entry each; the area's pages are listed under it). Their titles are in the shell's translations ("nav.areas.sell"). */
export const AREA_IDS = ["waiting", "command", "sell", "services", "customers", "stock", "buy", "money", "people", "connect", "addons", "settings"] as const;
export type AreaId = (typeof AREA_IDS)[number];

export interface SlotContribution {
  /** Translation key for a title (tabs and widgets show it). */
  label?: string;
  component: Lazy<SlotProps>;
  permission?: string;
  order?: number;
}

export interface ModuleDefinition {
  /** Name of the backend unit, e.g. "inventory". The kernel's own screens use "kernel". */
  unit: string;
  /** Other frontend modules this one needs (mirrors the backend manifest). */
  requires?: string[];
  routes?: PageRoute[];
  menu?: MenuItem[];
  /** Contributions to slots offered by the shell or other modules, by slot name. */
  slots?: Record<string, SlotContribution[]>;
  /** Translations, merged under the namespace `unit`: t("inventory:menu"). */
  translations?: { en: Record<string, unknown>; sw: Record<string, unknown> };
}

/** Declare a module. Only a type check: keeps every module.ts in the same shape. */
export function defineModule(definition: ModuleDefinition): ModuleDefinition {
  return definition;
}

