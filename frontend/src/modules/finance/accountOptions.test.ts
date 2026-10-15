import { describe, expect, it } from "vitest";

import { type Account, accountOptions, MONEY_SUBTYPES, SYSTEM_EXPENSE_SUBTYPES } from "./api";

const account = (code: string, type: string, subtype: string | null, extra: Partial<Account> = {}): Account => ({
  id: code, company_id: "c", code, name: `Account ${code}`, type, subtype, parent_id: null, is_control: false, is_active: true, ...extra,
});

const chart = [
  account("1010", "asset", "cash"), account("1020", "asset", "bank"), account("1030", "asset", "mobile_money_clearing", { is_control: true }),
  account("1100", "asset", "receivable", { is_control: true }), account("1200", "asset", "inventory", { is_control: true }),
  account("5000", "expense", "cogs"), account("5100", "expense", "shrinkage"), account("6000", "expense", "rent"), account("6200", "expense", "utilities"),
  account("6900", "expense", null), account("1025", "asset", "bank", { is_active: false }),
];
const codes = (options: { value: string }[]) => options.map((o) => o.value);

describe("account pickers", () => {
  it("offer only places money is kept when checking a statement", () => {
    expect(codes(accountOptions(chart, { types: ["asset"], subtypes: MONEY_SUBTYPES }))).toEqual(["1010", "1020", "1030"]);
  });
  it("leave out the expense accounts the system posts by itself", () => {
    expect(codes(accountOptions(chart, { types: ["expense"], postable: true, exceptSubtypes: SYSTEM_EXPENSE_SUBTYPES }))).toEqual(["6000", "6200", "6900"]);
  });
  it("keep every active account when no filter is given", () => {
    expect(accountOptions(chart)).toHaveLength(chart.length - 1);
  });
});
