import { describe, expect, it } from "vitest";

import { changedCounts, differs, duplicateProducts, fetchAll, lowStockRows, newLine, signedQty } from "./logic";

const product = (id: string, level: string | null, extra: object = {}) => ({
  id, sku: id, name: id, product_type: "stock", reorder_level: level, is_active: true, ...extra,
});

describe("lowStockRows", () => {
  it("totals a product across locations and sorts the most short first", () => {
    const rows = lowStockRows(
      [product("a", "10"), product("b", "5"), product("c", "5")],
      [{ product_id: "a", quantity: "4" }, { product_id: "a", quantity: "3" }, { product_id: "b", quantity: "0" }, { product_id: "c", quantity: "50" }],
    );
    expect(rows.map((r) => r.product.id)).toEqual(["b", "a"]);
    expect(rows[1]).toMatchObject({ onHand: "7", short: "3" });
  });
  it("treats a product with no balance as zero and skips inactive, non-stock and no-level products", () => {
    const rows = lowStockRows(
      [product("a", "2"), product("b", null), product("c", "2", { is_active: false }), product("d", "2", { product_type: "service" })], []);
    expect(rows.map((r) => r.product.id)).toEqual(["a"]);
  });
  it("includes a product exactly at its level", () => {
    expect(lowStockRows([product("a", "5")], [{ product_id: "a", quantity: "5" }])).toHaveLength(1);
  });
});

describe("lines", () => {
  it("signs the quantity", () => {
    expect(signedQty({ ...newLine(), qty: "3" })).toBe("3");
    expect(signedQty({ ...newLine(), qty: "3", remove: true })).toBe("-3");
  });
  it("finds a product picked twice", () => {
    const l = (p: string) => ({ ...newLine(), productId: p, qty: "1" });
    expect(duplicateProducts([l("a"), l("b"), l("a")])).toEqual(["a"]);
  });
});

describe("counts and receipts", () => {
  it("sends only changed count entries", () => {
    const lines = [{ id: "1", counted_qty: "5" }, { id: "2", counted_qty: null }, { id: "3", counted_qty: "2" }];
    const out = changedCounts(lines, { "1": "5.0", "2": "0", "3": "4", "4": "9" });
    expect(out.map((o) => [o.line.id, o.value])).toEqual([["2", "0"], ["3", "4"]]);
  });
  it("spots a received quantity that differs", () => {
    expect(differs("10", "10.00")).toBe(false);
    expect(differs("10", "9")).toBe(true);
    expect(differs("10", "")).toBe(false);
  });
});

describe("fetchAll", () => {
  it("keeps asking until a short page", async () => {
    const calls: number[] = [];
    const rows = await fetchAll(async (limit, offset) => { calls.push(offset); return offset < 4 ? Array(limit).fill(1) : [1]; }, 2);
    expect(calls).toEqual([0, 2, 4]);
    expect(rows).toHaveLength(5);
  });
});
