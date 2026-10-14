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
}

export interface MenuItem {
  /** Translation key, e.g. "products:menu". */
  label: string;
  to: string;
  permission?: string;
  /** Lower numbers come first. */
  order?: number;
  /** Menu section: where it sits in the sidebar. */
  group?: MenuGroup;
  /** Icon name from the SDK's icon set (see sdk/icons.tsx). */
  icon?: string;
}

/** Sidebar sections, in the order they appear. Their titles are in the shell's translations ("nav.sell"). */
export const MENU_GROUPS = ["sell", "stock", "buy", "money", "people", "admin"] as const;
export type MenuGroup = (typeof MENU_GROUPS)[number];

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

