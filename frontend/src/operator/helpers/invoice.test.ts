import { describe, expect, it } from "vitest";

import { type InvoiceDraft, invoiceProblems, lineAmount, previewSubtotal, toInvoiceIn } from "./invoice";

const draft = (over: Partial<InvoiceDraft> = {}): InvoiceDraft => ({
  tenant_code: "shop-a", licence_id: "", currency: "", lines: [{ description: "Setup", quantity: "2", unit_amount: "10.50" }],
  tax_inclusive: false, notes: "", due_date: "", issue: false, ...over,
});

describe("lineAmount", () => {
  it("multiplies exactly and rounds half up to two decimals", () => {
    expect(lineAmount("2", "10.50")).toBe("21.00");
    expect(lineAmount("0.333", "10")).toBe("3.33");
    expect(lineAmount("1.5", "0.01")).toBe("0.02");
    expect(lineAmount("3", "0.1")).toBe("0.30");
  });
  it("keeps discounts negative", () => {
    expect(lineAmount("1", "-5")).toBe("-5.00");
    expect(lineAmount("1.5", "-0.01")).toBe("-0.02");
  });
  it("is null for anything that is not a number or has too many decimals", () => {
    expect(lineAmount("", "5")).toBeNull();
    expect(lineAmount("1", "abc")).toBeNull();
    expect(lineAmount("1", "1.234")).toBeNull();
    expect(lineAmount("1.2345", "1")).toBeNull();
  });
});

describe("previewSubtotal", () => {
  it("adds the valid lines and ignores blank or half-typed ones", () => {
    const lines = [
      { description: "A", quantity: "1", unit_amount: "100.10" },
      { description: "Discount", quantity: "1", unit_amount: "-20" },
      { description: "", quantity: "1", unit_amount: "50" },
      { description: "B", quantity: "1", unit_amount: "x" },
    ];
    expect(previewSubtotal(lines)).toBe("80.10");
  });
});

describe("invoice form", () => {
  it("is fine with a subscriber and one good line", () => {
    expect(invoiceProblems(draft())).toEqual([]);
  });
  it("names what is missing", () => {
    expect(invoiceProblems(draft({ tenant_code: "" }))).toEqual(["target"]);
    expect(invoiceProblems(draft({ lines: [{ description: "", quantity: "1", unit_amount: "" }] }))).toEqual(["noLines"]);
    expect(invoiceProblems(draft({ lines: [{ description: "X", quantity: "0", unit_amount: "5" }] }))).toEqual(["badLine"]);
    expect(invoiceProblems(draft({ currency: "KESH" }))).toEqual(["currency"]);
  });
  it("sends a subscriber or a licence, never both, with a capital currency and no blank lines", () => {
    const body = toInvoiceIn(draft({ licence_id: "abc", currency: "usd", lines: [...draft().lines, { description: "", quantity: "1", unit_amount: "" }] }));
    expect(body.tenant_code).toBe("shop-a");
    expect(body.licence_id).toBeNull();
    expect(body.currency).toBe("USD");
    expect(body.lines).toHaveLength(1);
    expect(toInvoiceIn(draft({ tenant_code: "", licence_id: "abc" })).licence_id).toBe("abc");
  });
});
