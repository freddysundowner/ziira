import { describe, expect, it } from "vitest";

import { defineModule } from "./module";
import { activeModules, slotContributions, visibleMenu, visibleRoutes } from "./registry";

const page = () => Promise.resolve({ default: () => null });
const kernel = defineModule({ unit: "kernel", menu: [{ label: "users", to: "/users", permission: "users.manage", order: 90 }] });
const products = defineModule({
  unit: "products",
  routes: [{ path: "/products", page, permission: "products.view" }],
  menu: [{ label: "products", to: "/products", permission: "products.view", order: 10 }],
});
const stats = defineModule({
  unit: "catalog_stats",
  requires: ["products"],
  slots: {
    "dashboard.widgets": [{ component: page, permission: "catalog_stats.view" }],
    "products.product.tabs": [{ component: page, order: 2 }, { component: page, order: 1, label: "first" }],
  },
});
const all = [kernel, products, stats];
const access = (units: string[], permissions: string[]) => ({
  enabledUnits: new Set(units),
  can: (p: string) => permissions.includes(p),
});

describe("activeModules", () => {
  it("keeps the kernel's screens and modules whose unit is enabled", () => {
    expect(activeModules(all, new Set(["products"])).map((m) => m.unit)).toEqual(["kernel", "products"]);
  });
  it("drops a module whose required module is not enabled", () => {
    expect(activeModules(all, new Set(["catalog_stats"])).map((m) => m.unit)).toEqual(["kernel"]);
  });
  it("keeps a module once its requirements are enabled", () => {
    expect(activeModules(all, new Set(["products", "catalog_stats"])).map((m) => m.unit)).toContain("catalog_stats");
  });
});

describe("permissions", () => {
  const modules = activeModules(all, new Set(["products", "catalog_stats"]));
  it("shows pages and menu items only with the permission", () => {
    expect(visibleRoutes(modules, access([], [])).length).toBe(0);
    expect(visibleRoutes(modules, access([], ["products.view"])).map((r) => r.path)).toEqual(["/products"]);
  });
  it("orders the menu", () => {
    const menu = visibleMenu(modules, access([], ["products.view", "users.manage"]));
    expect(menu.map((m) => m.to)).toEqual(["/products", "/users"]);
  });
});

describe("slotContributions", () => {
  const modules = activeModules(all, new Set(["products", "catalog_stats"]));
  it("collects contributions from active modules, filtered and ordered", () => {
    expect(slotContributions(modules, "dashboard.widgets", access([], []))).toEqual([]);
    expect(slotContributions(modules, "dashboard.widgets", access([], ["catalog_stats.view"]))).toHaveLength(1);
    const tabs = slotContributions(modules, "products.product.tabs", access([], []));
    expect(tabs.map((t) => t.label)).toEqual(["first", undefined]);
    expect(tabs.every((t) => t.unit === "catalog_stats")).toBe(true);
  });
  it("is empty when the contributing module is not active", () => {
    const productsOnly = activeModules(all, new Set(["products"]));
    expect(slotContributions(productsOnly, "products.product.tabs", access([], []))).toEqual([]);
  });
});
