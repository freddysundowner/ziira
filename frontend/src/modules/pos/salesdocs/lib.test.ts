import { describe, expect, it } from "vitest";

import {
  returnMethods, blankLine, deliveryLines, estimateTotal, invoiceActions, invoiceDisplayStatus, lineBody, linesValid, orderActions, outstanding, overDelivered,
  quotationActions, readRejectedSale, receiptActions, rejectedSaleTotal, remainingToDeliver, statusTone, toEditLines,
} from "./lib";

const line = (patch: Partial<ReturnType<typeof blankLine>>) => ({ ...blankLine(), product_id: "p1", ...patch });

describe("quotation and order actions", () => {
  it("lets a draft quotation be changed, sent, accepted or cancelled", () => {
    expect(quotationActions("draft")).toMatchObject({ edit: true, send: true, accept: true, cancel: true });
  });
  it("lets a sent quotation only be accepted or cancelled", () => {
    expect(quotationActions("sent")).toMatchObject({ edit: false, send: false, accept: true, cancel: true });
  });
  it("offers nothing on a finished quotation", () => {
    for (const s of ["confirmed", "cancelled", "expired"]) expect(Object.values(quotationActions(s)).some(Boolean)).toBe(false);
  });
  it("lets a draft order be submitted, a confirmed one be delivered", () => {
    expect(orderActions({ status: "draft", lines: [] })).toMatchObject({ edit: true, submit: true, deliver: false });
    expect(orderActions({ status: "confirmed", lines: [{ qty_delivered: "0" }] })).toMatchObject({ deliver: true, cancel: true });
  });
  it("stops cancelling an order once goods have left", () => {
    expect(orderActions({ status: "confirmed", lines: [{ qty_delivered: "2" }] })).toMatchObject({ deliver: true, cancel: false });
  });
  it("offers nothing on a fulfilled order, and only cancel while it waits for approval", () => {
    expect(Object.values(orderActions({ status: "fulfilled", lines: [] })).some(Boolean)).toBe(false);
    expect(orderActions({ status: "pending_approval", lines: [] })).toMatchObject({ cancel: true, submit: false, deliver: false });
  });
});

describe("delivery quantities", () => {
  it("is what is left on the line", () => {
    expect(remainingToDeliver({ quantity: "10", qty_delivered: "3.5" })).toBe("6.5");
    expect(remainingToDeliver({ quantity: "2", qty_delivered: "2" })).toBe("0");
  });
  it("sends only lines with a quantity", () => {
    expect(deliveryLines({ a: "2", b: "0", c: "" })).toEqual([{ order_line_id: "a", quantity: "2" }]);
  });
  it("flags more than is left", () => {
    expect(overDelivered({ a: "5", b: "1" }, { a: "4", b: "1" })).toEqual(["a"]);
  });
});

describe("line editor", () => {
  it("needs at least one product and quantities above zero", () => {
    expect(linesValid([blankLine()])).toBe(false);
    expect(linesValid([line({ quantity: "0" })])).toBe(false);
    expect(linesValid([line({ quantity: "2" }), blankLine()])).toBe(true);
  });
  it("sends a blank price as null and a reason only with a price change", () => {
    const body = lineBody([line({ quantity: "2" }), line({ product_id: "p2", unit_price: "9.50", discount: "1" })], "r1");
    expect(body[0]).toEqual({ product_id: "p1", quantity: "2", unit_price: null, discount: "0", reason_code_id: null });
    expect(body[1]).toMatchObject({ unit_price: "9.50", discount: "1", reason_code_id: "r1" });
  });
  it("estimates only when every line has a price, without float noise", () => {
    expect(estimateTotal([line({ quantity: "3", unit_price: "0.10" }), line({ quantity: "1", unit_price: "0.20" })])).toBe("0.50");
    expect(estimateTotal([line({ unit_price: "10", discount: "2.50" })])).toBe("7.50");
    expect(estimateTotal([line({ unit_price: "" })])).toBeNull();
    expect(estimateTotal([blankLine()])).toBeNull();
  });
  it("turns saved lines back into rows", () => {
    const rows = toEditLines([{ id: "l1", product_id: "p", quantity: "2.0000", unit_price: "5.00", discount_amount: "0.00" }]);
    expect(rows[0]).toMatchObject({ key: "l1", quantity: "2", unit_price: "5.00", discount: "" });
  });
});

describe("invoice actions", () => {
  const base = { kind: "invoice", status: "issued", total: "100.00", amount_paid: "0.00", credited: "0.00", due_date: "2026-01-10" };
  it("works out what is still owed", () => {
    expect(outstanding({ ...base, amount_paid: "30.00", credited: "20.00" })).toBe("50.00");
    expect(outstanding({ ...base, status: "cancelled" })).toBe("0.00");
    expect(outstanding({ ...base, amount_paid: "100.00", status: "paid" })).toBe("0.00");
  });
  it("shows an unpaid invoice past its due date as overdue", () => {
    expect(invoiceDisplayStatus(base, "2026-01-11")).toBe("overdue");
    expect(invoiceDisplayStatus(base, "2026-01-10")).toBe("issued");
    expect(invoiceDisplayStatus({ ...base, status: "paid", amount_paid: "100.00" }, "2026-03-01")).toBe("paid");
  });
  it("cancels only an untouched invoice for goods", () => {
    expect(invoiceActions(base).cancel).toBe(true);
    expect(invoiceActions({ ...base, status: "part_paid", amount_paid: "10.00" }).cancel).toBe(false);
    expect(invoiceActions({ ...base, credited: "5.00" }).cancel).toBe(false);
    expect(invoiceActions({ ...base, kind: "credit_sale" })).toMatchObject({ cancel: false, giveBack: false, receive: true });
    expect(invoiceActions({ ...base, kind: "opening_balance" }).giveBack).toBe(false);
  });
  it("takes payment only while something is owed", () => {
    expect(invoiceActions({ ...base, status: "paid", amount_paid: "100.00" }).receive).toBe(false);
    expect(invoiceActions({ ...base, status: "cancelled" })).toMatchObject({ receive: false, giveBack: false });
  });
});

describe("receipt actions", () => {
  it("reverses a payment until part of it is refunded", () => {
    expect(receiptActions({ status: "posted", unallocated: "0.00", refunded: "0.00" }).reverse).toBe(true);
    expect(receiptActions({ status: "posted", unallocated: "5.00", refunded: "5.00" }).reverse).toBe(false);
    expect(receiptActions({ status: "reversed", unallocated: "0.00", refunded: "0.00" }).reverse).toBe(false);
  });
  it("refunds or applies only money held on account", () => {
    expect(receiptActions({ status: "posted", unallocated: "20.00", refunded: "0.00" })).toMatchObject({ refund: true, applyCredit: true });
    expect(receiptActions({ status: "posted", unallocated: "0.00", refunded: "0.00" })).toMatchObject({ refund: false, applyCredit: false });
  });
});

describe("rejected sales", () => {
  const payload = { type: "sale", number: "POS-A-1-L000007", at: "2026-02-01T10:00:00Z", customer_id: "c1",
    lines: [{ product_id: "p1", quantity: "2", unit_price: "10.00", discount: "1.00" }, { product_id: "p2", quantity: "1", unit_price: "0.50" }],
    payments: [{ method: "cash", amount: "20.00" }, { method: "mobile_money", amount: "5", external_ref: "ABC" }] };
  it("reads the parts and ignores what is missing", () => {
    const sale = readRejectedSale(payload);
    expect(sale.number).toBe("POS-A-1-L000007");
    expect(sale.lines).toHaveLength(2);
    expect(sale.payments[1]).toEqual({ method: "mobile_money", amount: "5", reference: "ABC" });
    expect(readRejectedSale({}).lines).toEqual([]);
  });
  it("totals the lines when each has its price", () => {
    expect(rejectedSaleTotal(readRejectedSale(payload))).toBe("19.50");
    expect(rejectedSaleTotal(readRejectedSale({ lines: [{ product_id: "p", quantity: "1" }] }))).toBeNull();
  });
});

describe("status tones", () => {
  it("colours known codes and leaves others neutral", () => {
    expect(statusTone("fulfilled")).toBe("ok");
    expect(statusTone("cancelled")).toBe("bad");
    expect(statusTone("mystery")).toBe("neutral");
  });
});

describe("dayBefore", () => {
  it("steps back over month and year ends", async () => {
    const { dayBefore } = await import("./lib");
    expect(dayBefore("2026-03-01")).toBe("2026-02-28");
    expect(dayBefore("2026-01-01")).toBe("2025-12-31");
    expect(dayBefore("2028-03-01")).toBe("2028-02-29");
  });
});

describe("returnMethods", () => {
  const inv = { status: "issued", total: "100.00", amount_paid: "0.00", credited: "0.00" };
  it("offers a credit note while the invoice is owed and money back once it is paid", () => {
    expect(returnMethods(inv)).toEqual(["credit_note", "exchange"]);
    expect(returnMethods({ ...inv, status: "part_paid", amount_paid: "60.00" })).toEqual(["credit_note", "exchange"]);
    expect(returnMethods({ ...inv, status: "paid", amount_paid: "100.00" })).toEqual(["cash", "mobile_money", "exchange"]);
  });
});
