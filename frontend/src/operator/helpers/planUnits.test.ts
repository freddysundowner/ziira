import { describe, expect, it } from "vitest";

import { changedSales, emptySale, explicitUnits, groupOf, isOffered, neededBy, offerAll, planCounts, saleCurrencies, saleProblem, saleProblems, salesToForm, searchUnits, sellableUnits, stopSellingAll, toggleUnit, toSaleIn, type UnitInfo, withRequired } from "./planUnits";

const u = (name: string, requires: string[] = [], kind = "module", title = name.toUpperCase()): UnitInfo => ({ name, title, description: `${name} does things`, kind, requires });
const UNITS = [u("kernel", [], "kernel"), u("products", ["kernel"]), u("inventory", ["products"]), u("jobs", ["inventory"], "module", "Jobs"), u("pack_x", [], "plugin")];

describe("units a plan includes", () => {
  it("never lists the kernel and groups modules apart from plugins", () => {
    expect(sellableUnits(UNITS).map((x) => x.name)).toEqual(["products", "inventory", "jobs", "pack_x"]);
    expect(groupOf(UNITS[1])).toBe("module");
    expect(groupOf(UNITS[4])).toBe("plugin");
  });
  it("adds what a ticked unit requires, again and again, without the kernel", () => {
    expect(withRequired(["jobs"], UNITS)).toEqual(["inventory", "jobs", "products"]);
    expect(withRequired([], UNITS)).toEqual([]);
    expect(withRequired(["jobs"], sellableUnits(UNITS))).toEqual(["inventory", "jobs", "products"]);   // the list the editor holds has no kernel in it
  });
  it("names the ticked units that need a unit", () => {
    expect(neededBy("inventory", ["jobs", "inventory", "products"], UNITS)).toEqual(["Jobs"]);
    expect(neededBy("jobs", ["jobs", "inventory", "products"], UNITS)).toEqual([]);
    expect(neededBy("inventory", ["inventory", "products"], UNITS)).toEqual([]);
  });
  it("starts from the units nobody else needs, so required ones can be unticked later", () => {
    expect(explicitUnits(["inventory", "jobs", "products", "pack_x"], UNITS).sort()).toEqual(["jobs", "pack_x"]);
  });
  it("ticks freely and unticks the unit itself", () => {
    expect(toggleUnit(["jobs"], "pack_x")).toEqual(["jobs", "pack_x"]);
    expect(toggleUnit(["jobs", "pack_x"], "pack_x")).toEqual(["jobs"]);
  });
  it("finds units by title, name or description", () => {
    expect(searchUnits(UNITS, "JOBS").map((x) => x.name)).toEqual(["jobs"]);
    expect(searchUnits(UNITS, "pack things").map((x) => x.name)).toEqual(["pack_x"]);
    expect(searchUnits(UNITS, "").length).toBe(UNITS.length);
  });
});

describe("selling an unticked unit", () => {
  const sale = (offered: boolean, prices: Record<string, string>) => ({ ...emptySale(), offered, prices });
  it("counts included and for-sale units", () => {
    const sales = { jobs: sale(true, { KES: "3000" }), pack_x: sale(true, {}), inventory: sale(true, { KES: "5" }) };
    expect(planCounts(["products", "inventory"], sales, sellableUnits(UNITS))).toEqual({ included: 2, forSale: 1 });
  });
  it("is offered only when switched on and priced", () => {
    expect(isOffered(sale(true, { KES: "10" }))).toBe(true);
    expect(isOffered(sale(true, { KES: " " }))).toBe(false);
    expect(isOffered(sale(false, { KES: "10" }))).toBe(false);
    expect(isOffered(undefined)).toBe(false);
  });
  it("wants a price when offered and positive amounts with at most two decimals", () => {
    expect(saleProblem(sale(true, {}))).toBe("needsPrice");
    expect(saleProblem(sale(true, { KES: "0" }))).toBe("price");
    expect(saleProblem(sale(false, { KES: "-1" }))).toBe("price");
    expect(saleProblem(sale(true, { KES: "12.345" }))).toBe("price");
    expect(saleProblem(sale(true, { KES: "3000", USD: "" }))).toBeNull();
    expect(saleProblem(sale(false, {}))).toBeNull();
  });
  it("ignores ticked units when it looks for problems", () => {
    const sales = { jobs: sale(true, {}), pack_x: sale(true, { KES: "x" }) };
    expect(saleProblems(sales, ["jobs"])).toEqual({ pack_x: "price" });
  });
  it("sees only real changes", () => {
    const before = salesToForm([{ unit: "jobs", offered: true, prices: { KES: "3000.00" }, tax_inclusive: false }]);
    expect(changedSales({ jobs: sale(true, { KES: "3000" }) }, before)).toEqual([]);
    expect(changedSales({ jobs: sale(true, { KES: "3500" }) }, before)).toEqual(["jobs"]);
    expect(changedSales({ jobs: sale(false, { KES: "3000" }) }, before)).toEqual(["jobs"]);
    expect(changedSales({ jobs: sale(true, { KES: "3000" }), pack_x: sale(true, { KES: "5" }) }, before)).toEqual(["pack_x"]);
  });
  it("sends emptied currencies as withdrawn", () => {
    const before = sale(true, { KES: "3000", USD: "20" });
    expect(toSaleIn(sale(true, { KES: " 3500 ", USD: "" }), before)).toEqual({ offered: true, prices: { KES: "3500", USD: null }, tax_inclusive: false });
  });
  it("offers the platform's currencies, those already priced and added ones", () => {
    expect(saleCurrencies(["KES"], { a: sale(true, { USD: "1" }) }, ["EUR"])).toEqual(["EUR", "KES", "USD"]);
  });
  it("stops selling everything in one go, keeping prices", () => {
    const units = [{ name: "a", title: "A", description: "", kind: "module", requires: [] }, { name: "b", title: "B", description: "", kind: "plugin", requires: [] }, { name: "c", title: "C", description: "", kind: "plugin", requires: [] }];
    const sales = { a: sale(true, { KES: "10" }), b: sale(true, { KES: "20" }), c: sale(false, {}) };
    const out = stopSellingAll(sales, ["b"], units);          // b is in the plan: not counted
    expect(out.count).toBe(1);
    expect(out.sales.a).toEqual(sale(false, { KES: "10" }));
    expect(out.sales.b.offered).toBe(true);
  });
  it("offers every unticked, unoffered unit at one price and leaves the rest", () => {
    const units = [{ name: "a", title: "A", description: "", kind: "module", requires: [] }, { name: "b", title: "B", description: "", kind: "plugin", requires: [] }, { name: "c", title: "C", description: "", kind: "plugin", requires: [] }];
    const sales = { a: sale(true, { KES: "10" }), b: sale(false, { KES: "5" }) };
    const out = offerAll(sales, ["c"], units, { KES: " 99 ", USD: "" });
    expect(out.count).toBe(1);
    expect(out.sales.b).toEqual(sale(true, { KES: "99" }));
    expect(out.sales.a).toEqual(sale(true, { KES: "10" }));
    expect(out.sales.c).toBeUndefined();
    expect(offerAll(sales, [], units, { KES: "" }).count).toBe(0);
  });
});
