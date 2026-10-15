import { describe, expect, it } from "vitest";

import { OPENING_STEPS, stepStates } from "./checklist";

describe("the opening balances checklist", () => {
  it("lists accounts, customers and suppliers before the balances, and the trial balance last", () => {
    const kinds = OPENING_STEPS.map((s) => s.kind).filter(Boolean);
    expect(kinds.indexOf("customers")).toBeLessThan(kinds.indexOf("customer_balances"));
    expect(kinds.indexOf("suppliers")).toBeLessThan(kinds.indexOf("supplier_balances"));
    expect(kinds.indexOf("opening_stock")).toBeLessThan(kinds.indexOf("opening_trial_balance"));
    expect(kinds.at(-1)).toBe("opening_trial_balance");
  });
  it("marks a step done only for a finished import, and unavailable when the kind is not offered", () => {
    const states = stepStates(["customers", "customer_balances"], [
      { kind: "customers", status: "done" }, { kind: "customer_balances", status: "reverted" }, { kind: "products", status: "uploaded" },
    ]);
    expect(states.customers).toBe("done");
    expect(states.customer_balances).toBe("ready");          // reversed: do it again
    expect(states.products).toBe("unavailable");
    expect(states.setup).toBe("ready");
  });
});
