import { describe, expect, it } from "vitest";

import { batchTone, canUndo, defaultKinds, hasCoreUnits, percentDone, ready, totals } from "./moveLogic";

describe("defaultKinds", () => {
  const kinds = [
    { kind: "products", available: true, allowed: true }, { kind: "customers", available: false, allowed: true },
    { kind: "suppliers", available: true, allowed: false }, { kind: "opening_stock", available: true, allowed: true },
  ] as const;
  it("ticks what can be brought and has something to bring", () => {
    expect(defaultKinds(kinds, { products: 4, customers: 3, suppliers: 2, stock_movements: 0 })).toEqual(["products"]);
    expect(defaultKinds(kinds, { products: 4, stock_movements: 7 })).toEqual(["products", "opening_stock"]);
  });
});

describe("ready", () => {
  it("needs a unit and a tax class only when products are brought", () => {
    expect(ready(["products"], "", "VAT", "2026-06-30")).toBe(false);
    expect(ready(["products"], "PCS", "VAT", "2026-06-30")).toBe(true);
    expect(ready(["customers"], "", "", "2026-06-30")).toBe(true);
    expect(ready([], "PCS", "VAT", "2026-06-30")).toBe(false);
    expect(ready(["customers"], "", "", "")).toBe(false);
  });
});

describe("totals", () => {
  it("adds up only the chosen kinds", () => {
    const k = [{ create: 2, exists: 1, skipped: 1, selected: true }, { create: 5, exists: 0, skipped: 0, selected: false }, { create: 3, exists: 2, skipped: 0, selected: true }];
    expect(totals(k)).toEqual({ create: 5, exists: 3, skipped: 1 });
  });
});

describe("progress", () => {
  const b = (status: string, failed = 0, reversible = false) => ({ status, counts: { failed }, reversible });
  it("counts finished batches", () => {
    expect(percentDone([])).toBe(0);
    expect(percentDone([b("done"), b("nothing_new"), b("committing"), b("waiting")])).toBe(50);
  });
  it("tones failures as bad and finished as ok", () => {
    expect(batchTone(b("done", 1))).toBe("bad");
    expect(batchTone(b("done"))).toBe("ok");
    expect(batchTone(b("nothing_new"))).toBe("neutral");
    expect(batchTone(b("committing"))).toBe("info");
  });
  it("offers undo only when a reversible batch is done", () => {
    expect(canUndo([b("done"), b("done", 0, true)])).toBe(true);
    expect(canUndo([b("reverted", 0, true), b("done")])).toBe(false);
  });
});

describe("hasCoreUnits", () => {
  it("is true once a unit that holds the data is on", () => {
    expect(hasCoreUnits(new Set(["connect", "intel", "command", "imports"]))).toBe(false);
    expect(hasCoreUnits(new Set(["connect", "crm"]))).toBe(true);
  });
});
