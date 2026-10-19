import { describe, expect, it } from "vitest";

import { allModules } from "@/modules";

import { areaEntryPath, AREA_DEFINITIONS, areaPages, buildNavigation, isSingle, placeOf, type NavArea } from "./areas";
import { orderedGroups } from "./edition";
import { defineModule, type MenuItem } from "./module";
import { activeModules, visibleRoutes } from "./registry";

const page = () => Promise.resolve({ default: () => null });
const item = (to: string, extra: Partial<MenuItem> = {}): MenuItem => ({ label: to, to, ...extra });
const access = (permissions: string[] | "all") => ({ enabledUnits: new Set<string>(), can: (p: string) => permissions === "all" || permissions.includes(p) });
const groups = orderedGroups({ menu_groups: ["sell", "stock", "buy", "money", "people", "admin"] });

const sales = defineModule({
  unit: "pos",
  routes: [
    { path: "/pos/terminal", page, permission: "sales.sell" },
    { path: "/pos/sales", page, permission: "till.review" },
    { path: "/pos/sales/:saleId", page, permission: "till.review" },
    { path: "/pos/tills", page, permission: "till.review" },
  ],
  menu: [
    item("/pos/terminal", { permission: "sales.sell", area: "sell", primary: true }),
    item("/pos/devices", { permission: "devices.manage", area: "sell", setup: true, order: 5 }),
    item("/pos/sales", { permission: "till.review", area: "sell", order: 10 }),
    item("/pos/returns", { permission: "till.review", area: "sell", under: "/pos/sales", order: 11 }),
    item("/pos/invoices", { permission: "receivables.view", area: "sell", order: 20 }),
  ],
});
const stock = defineModule({ unit: "inventory", menu: [item("/stock", { permission: "stock.view", area: "stock", order: 1 })] });
const people = defineModule({ unit: "people", menu: [item("/employees", { permission: "employees.view", area: "people" })] });
const kernel = defineModule({
  unit: "kernel",
  menu: [
    item("/admin/users", { permission: "users.manage", area: "settings", section: "access", order: 1 }),
    item("/admin/organisation", { permission: "organisation.manage", area: "settings", section: "business", order: 1 }),
    item("/admin/apps", { permission: "units.manage", area: "settings", section: "platform", order: 1 }),
    item("/admin/approvals", { permission: "approvals.decide", area: "command", order: 9 }),
    item("/admin/account", { hidden: true }),
    item("/plugin-page", { group: "money" }),
  ],
});
const all = [kernel, sales, stock, people];
const nav = (permissions: string[] | "all", modules = all) => buildNavigation(modules, access(permissions), groups);
const ids = (n: ReturnType<typeof nav>) => n.entries.map((e) => (e.kind === "area" ? e.area.id : e.item.to));
const area = (n: ReturnType<typeof nav>, id: string): NavArea => n.areas.find((a) => a.id === id)!;

describe("buildNavigation", () => {
  it("makes one sidebar entry per area, Settings last, with entries that name no area before it", () => {
    expect(ids(nav("all"))).toEqual(["command", "sell", "stock", "people", "/plugin-page", "settings"]);
  });
  it("hides an area when no page of it is allowed, and a page the person lacks the permission for", () => {
    expect(ids(nav(["stock.view"]))).toEqual(["stock", "/plugin-page"]);
    expect(area(nav(["till.review"]), "sell").items.map((t) => t.to)).toEqual(["/pos/sales"]);
    // a page whose entry the person cannot open gets an entry of its own
    const refunds = defineModule({ unit: "pos", menu: [item("/a", { area: "sell", order: 1 }), item("/b", { area: "sell", under: "/gone", order: 2 })] });
    expect(area(nav("all", [refunds]), "sell").items.map((t) => t.to)).toEqual(["/a", "/b"]);
    expect(nav(["till.review"]).areas.map((a) => a.id)).toEqual(["sell"]);
  });
  it("leaves out pages of a module that is not active", () => {
    const modules = activeModules(all, new Set(["pos"]));
    expect(ids(nav("all", modules))).toEqual(["command", "sell", "/plugin-page", "settings"]);
  });
  it("never lists a hidden entry in the sidebar", () => {
    expect(JSON.stringify(nav("all").entries)).not.toContain("/admin/account");
  });
  it("lists entries by order, pages that share an entry in its family, rarely used ones last", () => {
    const sell = area(nav("all"), "sell");
    expect(sell.items.map((t) => t.to)).toEqual(["/pos/sales", "/pos/invoices"]);
    expect(sell.families["/pos/sales"].map((t) => t.to)).toEqual(["/pos/sales", "/pos/returns"]);
    expect(sell.families["/pos/invoices"]).toBeUndefined();
    expect(sell.setup.map((t) => t.to)).toEqual(["/pos/devices"]);
    expect(areaPages(sell).map((t) => t.to)).toEqual(["/pos/terminal", "/pos/sales", "/pos/invoices", "/pos/devices"]);
  });
  it("keeps the till button apart from the pages and lets a till-only person see the area as a plain link", () => {
    const n = nav(["sales.sell"]);
    expect(area(n, "sell").items).toEqual([]);
    expect(isSingle(area(n, "sell"))).toBe(true);
    expect(area(n, "sell").primary.map((t) => t.to)).toEqual(["/pos/terminal"]);
    expect(areaEntryPath(area(n, "sell"))).toBe("/pos/terminal");
  });
  it("follows the edition's order of groups", () => {
    const n = buildNavigation(all, access("all"), orderedGroups({ menu_groups: ["people", "stock"] }));
    expect(ids(n)).toEqual(["command", "people", "stock", "sell", "/plugin-page", "settings"]);
  });
  it("calls the area an inbox when Intelligence and its daily summary are not on", () => {
    expect(area(nav("all"), "command").titleKey).toBe("nav.areas.inbox");
    const intel = defineModule({ unit: "command", menu: [item("/command", { area: "command" })] });
    expect(area(nav("all", [...all, intel]), "command").titleKey).toBe("nav.areas.command");
  });
});

describe("Settings grouping", () => {
  it("lists settings pages by group in the defined group order", () => {
    const settings = area(nav("all"), "settings");
    expect(AREA_DEFINITIONS.settings.variant).toBe("side");
    expect(settings.sections).toEqual(["business", "access", "platform"]);
    expect(isSingle(settings)).toBe(true);        // one entry in the sidebar, not expandable
    expect(settings.items.map((t) => t.to)).toEqual(["/admin/organisation", "/admin/users", "/admin/apps"]);
  });
});

describe("areaEntryPath and isSingle", () => {
  it("opens the first page; an area with several pages expands", () => {
    expect(areaEntryPath(area(nav("all"), "sell"))).toBe("/pos/sales");
    expect(isSingle(area(nav("all"), "sell"))).toBe(false);
    expect(isSingle(area(nav("all"), "people"))).toBe(true);
  });
});

describe("placeOf", () => {
  const n = nav("all");
  const routes = visibleRoutes(all, access("all"));
  it("finds the entry for its own page, for a page under it and by the page's declaration", () => {
    expect(placeOf(n.areas, routes, "/pos/devices")?.item.to).toBe("/pos/devices");
    expect(placeOf(n.areas, routes, "/pos/sales/abc")?.item.to).toBe("/pos/sales");
    const member = placeOf(n.areas, routes, "/pos/returns");
    expect([member?.item.to, member?.head.to]).toEqual(["/pos/returns", "/pos/sales"]);

    const declared = [{ path: "/payslips/:id", page, tab: "/employees" }];
    expect(placeOf(n.areas, declared, "/payslips/7")?.area.id).toBe("people");
  });
  it("takes the longest matching entry and treats the till as a header button", () => {
    expect(placeOf(n.areas, routes, "/pos/terminal")?.item.primary).toBe(true);
  });
  it("places nothing outside the areas (Home, My account, unknown pages)", () => {
    expect(placeOf(n.areas, routes, "/")).toBeNull();
    expect(placeOf(n.areas, routes, "/admin/account")).toBeNull();
    expect(placeOf(n.areas, routes, "/nowhere")).toBeNull();
  });
});

describe("the real modules", () => {
  const everything = activeModules(allModules, new Set(allModules.map((m) => m.unit)));
  const unlimited = access("all");
  const n = buildNavigation(everything, unlimited, groups);
  const routes = visibleRoutes(everything, unlimited);

  it("keeps sections to about seven entries (Services, which four modules fill, may hold twelve)", () => {
    const limit = (id: string) => (id === "services" ? 12 : 8);
    expect(n.areas.filter((a) => a.variant === "list").map((a) => [a.id, areaPages(a).length] as const).filter(([id, c]) => c > limit(id))).toEqual([]);
  });
  it("gives a full business thirteen or fewer sidebar entries including Home and Waiting for you", () => {
    expect(n.entries.length + 1).toBeLessThanOrEqual(13);
    expect(n.entries.every((e) => e.kind === "area")).toBe(true);
  });
  it("puts every page in an area, except the person's own account", () => {
    const outside = routes.map((r) => r.path.replace(/:\w+/g, "x")).filter((p) => !placeOf(n.areas, routes, p) && p !== "/admin/account");
    expect(outside).toEqual([]);
  });
  it("uses only sections an area knows and no address twice", () => {
    const known = new Set(Object.values(AREA_DEFINITIONS).flatMap((d) => d.sections));
    const pages = n.areas.flatMap(areaPages);
    expect(pages.filter((t) => t.section && !known.has(t.section)).map((t) => t.to)).toEqual([]);
    const addresses = everything.flatMap((m) => m.menu ?? []).map((i) => i.to);
    expect(addresses.filter((a, i) => addresses.indexOf(a) !== i)).toEqual([]);
  });
  it("points every declared entry at an existing entry", () => {
    const entries = new Set(everything.flatMap((m) => m.menu ?? []).map((i) => i.to));
    expect(routes.filter((r) => r.tab && !entries.has(r.tab)).map((r) => r.path)).toEqual([]);
  });
});
