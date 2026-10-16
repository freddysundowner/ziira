import { describe, expect, it } from "vitest";

import { addDays, allocateOldestFirst, amountDue, dayToTimestamp, isOpenBill, isOverdue, previewSubtotal, receiveLocationId, remaining, stillToReceive, sumAmounts } from "./lib";

describe("bill amounts", () => {
  it("works out what is still owed and never goes below zero", () => {
    expect(amountDue({ total: "1160.00", amount_paid: "500.00", credited: "60.00" })).toBe("600.00");
    expect(amountDue({ total: "100.00", amount_paid: "100.00", credited: "20.00" })).toBe("0.00");
  });
  it("knows which bills are still open and which are overdue", () => {
    expect(isOpenBill("posted")).toBe(true);
    expect(isOpenBill("paid")).toBe(false);
    expect(isOverdue({ status: "part_paid", due_date: "2025-01-01" }, "2025-01-02")).toBe(true);
    expect(isOverdue({ status: "paid", due_date: "2025-01-01" }, "2025-01-02")).toBe(false);
    expect(isOverdue({ status: "posted", due_date: "2025-01-02" }, "2025-01-02")).toBe(false);
  });
});

describe("line previews", () => {
  it("adds up quantity times cost without float drift", () => {
    expect(previewSubtotal([{ quantity: "3", unit_cost: "0.1" }, { quantity: "2.5", unit_cost: "10.10" }])).toBe("25.55");
  });
  it("ignores half-typed numbers", () => {
    expect(previewSubtotal([{ quantity: "", unit_cost: "5" }, { quantity: "2.", unit_cost: "1.5" }])).toBe("3.00");
  });
  it("tells what is left to receive or credit", () => {
    expect(stillToReceive({ quantity: "10", qty_received: "4" })).toBe("6");
    expect(remaining("2", "3")).toBe("0");
    expect(remaining("1.5", "0.25")).toBe("1.25");
  });
});

describe("spreading a payment", () => {
  const bills = [
    { id: "b", due_date: "2025-02-10", due: "300.00" },
    { id: "a", due_date: "2025-01-10", due: "200.00" },
    { id: "c", due_date: "2025-03-10", due: "100.00" },
  ];
  it("pays the oldest bill first and stops when the money runs out", () => {
    expect(allocateOldestFirst("350", bills)).toEqual({ a: "200.00", b: "150.00" });
  });
  it("never pays a bill more than it owes", () => {
    expect(allocateOldestFirst("1000", bills)).toEqual({ a: "200.00", b: "300.00", c: "100.00" });
  });
  it("sums amounts in cents", () => {
    expect(sumAmounts(["0.1", "0.2", ""])).toBe("0.30");
  });
});

describe("dates", () => {
  it("adds days across month ends", () => {
    expect(addDays("2025-01-30", 7)).toBe("2025-02-06");
  });
  it("sends a timestamp only for a day other than today", () => {
    expect(dayToTimestamp("2025-01-05", "2025-01-05")).toBeUndefined();
    expect(dayToTimestamp("2025-01-04", "2025-01-05")).toMatch(/^2025-01-04T/);
  });
});

describe("receiveLocationId", () => {
  const loc = (id: string, kind = "store", is_active = true) => ({ id, kind, is_active });
  it("prefers the order's own location, else the first active store", () => {
    expect(receiveLocationId([loc("a"), loc("b")], "b")).toBe("b");
    expect(receiveLocationId([loc("w", "warehouse"), loc("s")], null)).toBe("s");
  });
  it("ignores an inactive preferred location and is empty with none", () => {
    expect(receiveLocationId([loc("a"), loc("b", "store", false)], "b")).toBe("a");
    expect(receiveLocationId([], null)).toBe("");
  });
});
