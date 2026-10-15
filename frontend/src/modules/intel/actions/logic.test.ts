import { describe, expect, it } from "vitest";

import { isWaiting, needsAutomationRight, type Proposal, recordLink, ruleState, splitProposals } from "./logic";

const p = (id: string, status: string, proposed_at: string) => ({ id, status, proposed_at }) as Proposal;

describe("splitProposals", () => {
  it("puts open and failed first, each newest first", () => {
    const { waiting, earlier } = splitProposals([p("a", "executed", "2026-01-01"), p("b", "proposed", "2026-01-02"), p("c", "failed", "2026-01-03"), p("d", "rejected", "2026-01-04")]);
    expect(waiting.map((x) => x.id)).toEqual(["c", "b"]);
    expect(earlier.map((x) => x.id)).toEqual(["d", "a"]);
  });
  it("knows what is waiting", () => {
    expect(isWaiting(p("a", "failed", ""))).toBe(true);
    expect(isWaiting(p("a", "expired", ""))).toBe(false);
  });
});

describe("recordLink", () => {
  it("links the records that have a screen", () => {
    expect(recordLink({ type: "purchasing.purchase_request", id: "x1" })).toBe("/requests/x1");
    expect(recordLink({ type: "crm.customer", id: "c1" })).toBe("/customers/c1");
  });
  it("gives no link for unknown types or missing ids", () => {
    expect(recordLink({ type: "pos.sales_invoice", id: "x" })).toBeNull();
    expect(recordLink({ type: "products.product", id: null })).toBeNull();
  });
});

describe("levels and rules", () => {
  it("needs the automation right from level 3", () => {
    expect([1, 2, 3, 4].map(needsAutomationRight)).toEqual([false, false, true, true]);
  });
  it("tells a rule's state", () => {
    expect(ruleState({ enabled: true, paused: false })).toBe("active");
    expect(ruleState({ enabled: true, paused: true })).toBe("paused");
    expect(ruleState({ enabled: false, paused: true })).toBe("off");
  });
});
