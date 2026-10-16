/**
 * Which modules, pages, menu items and slot contributions are active for the signed-in user.
 *
 * Pure functions (no React, no network) so the rules are easy to test:
 * - a module is active when its backend unit is enabled for the business, and so are the modules
 *   it requires;
 * - a page, menu item or slot contribution is visible when the user holds its permission.
 */
import type { MenuItem, ModuleDefinition, PageRoute, SlotContribution } from "./module";

export interface Access {
  /** Backend units enabled for this business (from GET /api/v1/units). */
  enabledUnits: ReadonlySet<string>;
  /** Permission check (from GET /api/v1/auth/me). */
  can: (permission: string) => boolean;
  /** Navigation flags that are on (menu entries with `when` are listed only while theirs is). */
  flags?: ReadonlySet<string>;
}

export function activeModules(all: readonly ModuleDefinition[], enabledUnits: ReadonlySet<string>) {
  const byUnit = new Map(all.map((m) => [m.unit, m]));
  const isActive = (m: ModuleDefinition, seen = new Set<string>()): boolean => {
    if (seen.has(m.unit)) return false; // circular requirement: refuse
    seen.add(m.unit);
    if (m.unit !== "kernel" && !enabledUnits.has(m.unit)) return false;
    return (m.requires ?? []).every((r) => {
      const dep = byUnit.get(r);
      return dep !== undefined && isActive(dep, new Set(seen));
    });
  };
  return all.filter((m) => isActive(m));
}

const allowed = (access: Access, permission?: string) => !permission || access.can(permission);

export function visibleRoutes(modules: readonly ModuleDefinition[], access: Access): PageRoute[] {
  return modules.flatMap((m) => m.routes ?? []).filter((r) => allowed(access, r.permission));
}

/** A menu entry together with the unit whose module declared it. */
export interface NavItem extends MenuItem {
  unit: string;
}

export function visibleMenu(modules: readonly ModuleDefinition[], access: Access): NavItem[] {
  return modules
    .flatMap((m) => (m.menu ?? []).map((i) => ({ ...i, unit: m.unit })))
    .filter((i) => allowed(access, i.permission) && (!i.when || access.flags?.has(i.when)))
    .sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
}

export interface ActiveContribution extends SlotContribution {
  /** The module that contributed it. */
  unit: string;
}

export function slotContributions(
  modules: readonly ModuleDefinition[],
  slot: string,
  access: Access,
): ActiveContribution[] {
  return modules
    .flatMap((m) => (m.slots?.[slot] ?? []).map((c) => ({ ...c, unit: m.unit })))
    .filter((c) => allowed(access, c.permission))
    .sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
}
