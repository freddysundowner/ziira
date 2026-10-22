import { describe, expect, it } from "vitest";

import { findByCode, searchLocal, withReserved } from "./catalogSearch";
import type { CatalogItem } from "./types";

const item = (over: Partial<CatalogItem>): CatalogItem => ({
  product_id: "p", sku: "X", name: "X", product_type: "stock", vat_rate: "16", is_batch_tracked: false, uom_id: "u", price: "10.00", stock: "5", barcodes: [], reference_prompt: "off", ...over,
});
const items = [
  item({ product_id: "1", sku: "CEM", name: "Cement 50kg", barcodes: ["6001234567890", "CEM-ALT"] }),
  item({ product_id: "2", sku: "PAINT", name: "Paint white 4L", barcodes: ["5000000000011"] }),
  item({ product_id: "3", sku: "NAIL-2", name: "Nails 2in" }),
  item({ product_id: "4", sku: "DELIVERY", name: "Delivery", product_type: "service", stock: null }),
];

describe("finding a scanned code on this device", () => {
  it("finds the product by any of its barcodes", () => {
    expect(findByCode(items, "6001234567890")?.sku).toBe("CEM");
    expect(findByCode(items, " CEM-ALT ")?.sku).toBe("CEM");
    expect(findByCode(items, "5000000000011")?.sku).toBe("PAINT");
  });
  it("barcodes are case sensitive; SKUs are not", () => {
    expect(findByCode(items, "cem-alt")).toBeUndefined();
    expect(findByCode(items, "nail-2")?.sku).toBe("NAIL-2");
  });
  it("finds nothing for an unknown or empty code", () => {
    expect(findByCode(items, "0000")).toBeUndefined();
    expect(findByCode(items, "  ")).toBeUndefined();
  });
  it("does not guess when two products have the code", () => {
    expect(findByCode([...items, item({ product_id: "9", sku: "DUP", name: "Dup", barcodes: ["CEM-ALT"] })], "CEM-ALT")).toBeUndefined();
  });
});

describe("searching the list on this device", () => {
  it("matches name or SKU, ignoring case, by name", () => {
    expect(searchLocal(items, "ce", 10).map((i) => i.sku)).toEqual(["CEM"]);
    expect(searchLocal(items, "NAIL", 10).map((i) => i.sku)).toEqual(["NAIL-2"]);
    expect(searchLocal(items, "paint", 10).map((i) => i.sku)).toEqual(["PAINT"]);
  });
  it("finds a product by its exact barcode", () => {
    expect(searchLocal(items, "5000000000011", 10).map((i) => i.sku)).toEqual(["PAINT"]);
    expect(searchLocal(items, "50000000000", 10)).toEqual([]);
  });
  it("lists everything by name when the box is empty, up to the limit", () => {
    expect(searchLocal(items, "", 10).map((i) => i.sku)).toEqual(["CEM", "DELIVERY", "NAIL-2", "PAINT"]);
    expect(searchLocal(items, "", 2)).toHaveLength(2);
  });
});

describe("stock not yet at the server", () => {
  it("takes the quantity of waiting sales off the stock", () => {
    const shown = withReserved(items, new Map([["1", 2], ["4", 9]]));
    expect(shown.find((i) => i.product_id === "1")?.stock).toBe("3");
    expect(shown.find((i) => i.product_id === "4")?.stock).toBeNull();
    expect(shown.find((i) => i.product_id === "2")?.stock).toBe("5");
  });
  it("can go below zero: the till shows it is sold out", () => {
    expect(withReserved(items, new Map([["1", 7]])).find((i) => i.product_id === "1")?.stock).toBe("-2");
  });
});
