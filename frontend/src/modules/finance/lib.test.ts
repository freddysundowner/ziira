import { describe, expect, it } from "vitest";

import { isSignedAmount, isZero, orderAccounts, previewJournal } from "./lib";

describe("previewJournal", () => {
  it("balances two opposite lines", () => {
    const p = previewJournal([{ account_id: "a", debit: "10.10", credit: "" }, { account_id: "b", debit: "", credit: "10.10" }]);
    expect(p).toMatchObject({ debit: "10.10", credit: "10.10", difference: "0.00", balanced: true, ready: true, problems: [] });
  });
  it("adds cents without float noise", () => {
    const p = previewJournal([
      { account_id: "a", debit: "0.10", credit: "" }, { account_id: "a", debit: "0.20", credit: "" }, { account_id: "b", debit: "", credit: "0.30" },
    ]);
    expect(p.difference).toBe("0.00");
    expect(p.ready).toBe(true);
  });
  it("shows the difference and blocks saving", () => {
    const p = previewJournal([{ account_id: "a", debit: "5", credit: "" }, { account_id: "b", debit: "", credit: "4" }]);
    expect(p.difference).toBe("1.00");
    expect(p.ready).toBe(false);
  });
  it("flags missing account, both sides, no amount and too few lines", () => {
    expect(previewJournal([{ account_id: "", debit: "5", credit: "" }]).problems).toEqual(expect.arrayContaining(["noAccount", "fewLines"]));
    expect(previewJournal([{ account_id: "a", debit: "5", credit: "5" }, { account_id: "b", debit: "", credit: "" }]).problems).toEqual(expect.arrayContaining(["bothSides", "noAmount"]));
  });
  it("ignores blank lines", () => {
    expect(previewJournal([{ account_id: "", debit: "", credit: "" }]).problems).toEqual(["fewLines"]);
  });
});

describe("orderAccounts", () => {
  it("puts children under their parent with depth", () => {
    const rows = orderAccounts([
      { id: "3", code: "1110", parent_id: "1" }, { id: "2", code: "2000", parent_id: null }, { id: "1", code: "1100", parent_id: null },
    ]);
    expect(rows.map((r) => [r.account.id, r.depth])).toEqual([["1", 0], ["3", 1], ["2", 0]]);
  });
  it("treats a parent that is not in the list as a root", () => {
    expect(orderAccounts([{ id: "1", code: "1", parent_id: "gone" }])[0].depth).toBe(0);
  });
});

describe("amount helpers", () => {
  it("recognises zero", () => {
    expect(isZero("0.00")).toBe(true);
    expect(isZero("0.01")).toBe(false);
  });
  it("accepts negative statement balances", () => {
    expect(isSignedAmount("-120.50")).toBe(true);
    expect(isSignedAmount("12.345")).toBe(false);
    expect(isSignedAmount("abc")).toBe(false);
  });
});
