import { describe, expect, it } from "vitest";

import { firstOwed, payBody, payerComplete, payPhase, returnParams, secondsLeft, type Invoice } from "./lib";

const inv = (over: Partial<Invoice>): Invoice => ({ id: "i", number: "N", status: "issued", kind: "renewal", currency: "KES", total: "10", amount_paid: "0", balance: "10", issue_date: null, due_date: "2030-01-10", period_start: null, period_end: null, lines: [], tax_lines: [], tax_total: "0", discount_total: "0", subtotal: "10", ...over });

describe("secondsLeft", () => {
  it("counts down from two minutes and stops at zero", () => {
    expect(secondsLeft(0, 0)).toBe(120);
    expect(secondsLeft(0, 30_000)).toBe(90);
    expect(secondsLeft(0, 119_100)).toBe(1);
    expect(secondsLeft(0, 500_000)).toBe(0);
  });
});

describe("payPhase", () => {
  it("only a prompt times out; a provider page keeps waiting", () => {
    expect(payPhase({ status: "pending", flow: "prompt" }, 5)).toBe("waiting");
    expect(payPhase({ status: "pending", flow: "prompt" }, 0)).toBe("timeout");
    expect(payPhase({ status: "pending", flow: "redirect" }, 0)).toBe("waiting");
  });
  it("maps the settled states", () => {
    expect(payPhase({ status: "completed", flow: "prompt" }, 0)).toBe("paid");
    expect(payPhase({ status: "failed", flow: "prompt" }, 50)).toBe("failed");
    expect(payPhase({ status: "mismatch", flow: "redirect" }, 50)).toBe("mismatch");
    expect(payPhase({ status: "expired", flow: "redirect" }, 50)).toBe("expired");
  });
});

describe("what is sent", () => {
  const option = { provider: "x", payer_fields: [{ name: "phone", label: "", kind: "tel", help: "", required: true }, { name: "email", label: "", kind: "email", help: "", required: false }] };
  it("keeps only filled fields, trimmed", () => {
    expect(payBody("i1", option, { phone: " 0712 ", email: " " })).toEqual({ invoice_id: "i1", provider: "x", payer: { phone: "0712" } });
  });
  it("needs every required field", () => {
    expect(payerComplete(option, { phone: "" })).toBe(false);
    expect(payerComplete(option, { phone: "0712" })).toBe(true);
  });
});

describe("returnParams and firstOwed", () => {
  it("reads where a provider sends the owner back", () => {
    expect(returnParams("?attempt=abc&payment=success")).toEqual({ attempt: "abc", payment: "success" });
    expect(returnParams("?attempt=abc&payment=weird")).toEqual({ attempt: "abc", payment: null });
    expect(returnParams("?x=1")).toBeNull();
  });
  it("picks the oldest unpaid invoice", () => {
    const list = [inv({ id: "paid", status: "paid", balance: "0" }), inv({ id: "late", due_date: "2030-02-01" }), inv({ id: "early", due_date: "2030-01-01" })];
    expect(firstOwed(list)?.id).toBe("early");
    expect(firstOwed([inv({ status: "paid", balance: "0" })])).toBeNull();
    expect(firstOwed(undefined)).toBeNull();
  });
});
