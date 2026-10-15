import { describe, expect, it } from "vitest";

import type { CartLine } from "../cart";
import { newLeg } from "../cart";
import { buildOfflineSale, type Labels, type OfflineSaleInput, taxInside, toCents } from "./localSale";

const labels: Labels = { title: "Receipt", provisional: "TO BE CONFIRMED", date: "Date", servedBy: "Served by", customer: "Customer", subtotal: "Subtotal", discount: "Discount", total: "TOTAL" };
const line = (over: Partial<CartLine> = {}): CartLine => ({
  key: "k", productId: "p1", sku: "CEM", name: "Cement 50kg", listPrice: "116.00", price: "116.00", quantity: "1", discount: "0", reasonId: "", stock: "10", vatRate: "16", ...over,
});
const input = (over: Partial<OfflineSaleInput> = {}): OfflineSaleInput => ({
  localId: "11111111-1111-4111-8111-111111111111", tillId: "till-1", branchId: "b1", userId: "u1", number: "OFFLINE-D1-0001", madeAt: Date.UTC(2026, 0, 5, 10, 30), offsetMs: 2_000,
  currency: "KES", lines: [line()], legs: [newLeg("cash", 116)], customerId: "", customerName: "", cashierName: "Amina", header: ["Hardware Ltd", "Main branch"], footer: ["Thank you"], labels, ...over,
});

describe("tax inside a price", () => {
  it("is gross x rate / (100 + rate), rounded half up", () => {
    expect(taxInside(11600, "16")).toBe(1600);            // 116.00 at 16%: 16.00
    expect(taxInside(10000, "16")).toBe(1379);            // 100.00 at 16%: 13.793... -> 13.79
    expect(taxInside(105, "5")).toBe(5);                  // 1.05 at 5%: 0.05
    expect(taxInside(1, "50")).toBe(0);                   // 0.0033 -> 0
    expect(taxInside(3, "50")).toBe(1);                   // 0.01 exactly
    expect(taxInside(15, "100")).toBe(8);                 // 0.075 -> half up -> 0.08
  });
  it("is nothing at 0% or for nothing", () => {
    expect(taxInside(11600, "0")).toBe(0);
    expect(taxInside(0, "16")).toBe(0);
  });
  it("reads amounts as whole cents", () => {
    expect(toCents("116.00")).toBe(11600);
    expect(toCents("0.1") + toCents("0.2")).toBe(30);
    expect(toCents("1.005")).toBe(101);
  });
});

describe("the request for a sale made offline", () => {
  const { op } = buildOfflineSale(input());
  it("carries the client-made id (what makes it happen once) and the till", () => {
    expect(op.type).toBe("sale");
    expect(op.local_id).toBe("11111111-1111-4111-8111-111111111111");
    expect(op.till_session_id).toBe("till-1");
  });
  it("records the moment on the device clock plus the last known server offset", () => {
    expect(op.at).toBe("2026-01-05T10:30:02.000Z");
    expect(buildOfflineSale(input({ offsetMs: 0 })).op.at).toBe("2026-01-05T10:30:00.000Z");
  });
  it("always names the price the customer was charged, because the list may change before the sale is sent", () => {
    expect(op.lines).toEqual([{ product_id: "p1", quantity: "1", unit_price: "116.00", discount: "0" }]);
  });
  it("keeps reasons, codes, accounts and customer", () => {
    const sale = buildOfflineSale(input({
      lines: [line({ price: "100", discount: "10", reasonId: "r1" })],
      legs: [{ ...newLeg("mobile_money", 90), ref: "QWE123", accountId: "acc1" }], customerId: "c1",
    })).op;
    expect(sale.lines[0]).toMatchObject({ unit_price: "100", discount: "10", reason_code_id: "r1" });
    expect(sale.payments).toEqual([{ method: "mobile_money", amount: "90", external_ref: "QWE123", payment_account_id: "acc1" }]);
    expect(sale.customer_id).toBe("c1");
  });
  it("leaves out payments of nothing", () => {
    const sale = buildOfflineSale(input({ legs: [newLeg("cash", 116), newLeg("card", 0)] })).op;
    expect(sale.payments).toHaveLength(1);
  });
});

describe("the receipt printed from local data", () => {
  it("shows the lines, totals, tax and payments the way the server's does, marked to be confirmed", () => {
    const built = buildOfflineSale(input({
      lines: [line({ quantity: "2" }), line({ productId: "p2", name: "Delivery", price: "58", vatRate: "0", listPrice: "58" })],
      legs: [newLeg("cash", 300)], customerName: "Mama Mboga",
    }));
    const r = built.receipt;
    expect(r.number).toBe("OFFLINE-D1-0001");
    expect(r.header).toEqual(["Hardware Ltd", "Main branch"]);
    expect(r.notes).toEqual(["TO BE CONFIRMED"]);
    expect(r.lines.map((l) => [l.description, l.quantity, l.unit_price, l.amount])).toEqual([["Cement 50kg", "2", "116.00", "232.00"], ["Delivery", "1", "58", "58.00"]]);
    expect(r.totals).toEqual([{ label: "Subtotal", amount: "290.00" }, { label: "TOTAL", amount: "290.00" }]);
    expect(r.vat).toEqual([{ rate: "16", net: "200.00", tax: "32.00" }]);
    expect(r.payments).toEqual([{ label: "CASH", amount: "290.00" }]);
    expect(r.meta).toEqual([["Date", "2026-01-05 " + r.meta[0]![1]!.slice(11)], ["Served by", "Amina"], ["Customer", "Mama Mboga"]]);
    expect(built.total).toBe("290.00");
    expect(built.change).toBe("10.00");
    expect(r.footer).toEqual(["Thank you"]);
  });
  it("takes a discount off the line and shows it", () => {
    const r = buildOfflineSale(input({ lines: [line({ discount: "16", reasonId: "r" })], legs: [newLeg("cash", 100)] })).receipt;
    expect(r.totals).toEqual([{ label: "Subtotal", amount: "116.00" }, { label: "Discount", amount: "-16.00" }, { label: "TOTAL", amount: "100.00" }]);
    expect(r.vat).toEqual([{ rate: "16", net: "86.21", tax: "13.79" }]);
  });
  it("splits payments: only cash can be more than is due, the rest is change", () => {
    const built = buildOfflineSale(input({ lines: [line({ quantity: "3" })], legs: [newLeg("card", 100), newLeg("cash", 300)] }));
    expect(built.total).toBe("348.00");
    expect(built.receipt.payments).toEqual([{ label: "CASH", amount: "248.00" }, { label: "CARD", amount: "100.00" }]);
    expect(built.change).toBe("52.00");
  });
  it("lists what is in the queue: sku, name, quantity, amount", () => {
    expect(buildOfflineSale(input()).lines).toEqual([{ sku: "CEM", name: "Cement 50kg", quantity: "1", amount: "116.00" }]);
  });
});
