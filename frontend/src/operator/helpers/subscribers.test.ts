import { describe, expect, it } from "vitest";

import { availableActions, filtersFromParams, filtersToParams, hasFilters, NO_FILTERS, subscriberQuery } from "./subscribers";

const everything = () => true;

describe("subscriber filters", () => {
  it("round-trip through the address, dropping empty ones", () => {
    const params = new URLSearchParams("flag=past_due&plan=pro&search=%20shop%20");
    const filters = filtersFromParams(params);
    expect(filters).toMatchObject({ flag: "past_due", plan: "pro", search: " shop " });
    expect(filtersToParams(filters).toString()).toBe("search=shop&plan=pro&flag=past_due");
    expect(hasFilters(NO_FILTERS)).toBe(false);
    expect(hasFilters(filters)).toBe(true);
  });

  it("builds the page query with only the set filters and a capital country", () => {
    expect(subscriberQuery({ ...NO_FILTERS, status: "active", country: "ke" }, 2, 25)).toEqual({ status: "active", country: "KE", limit: 25, offset: 50 });
    expect(subscriberQuery(NO_FILTERS, 0, 25)).toEqual({ limit: 25, offset: 0 });
  });
});

describe("availableActions", () => {
  it("offers a business without a subscription only to start one", () => {
    expect(availableActions({ status: "unmanaged", cancel_at_period_end: false }, everything)).toEqual(["start", "export", "delete"]);
  });
  it("offers a trial an extension and cancellation", () => {
    const list = availableActions({ status: "trialing", cancel_at_period_end: false }, everything);
    expect(list).toContain("extendTrial");
    expect(list).toContain("cancel");
    expect(list).not.toContain("uncancel");
  });
  it("offers to undo a cancellation that is waiting for the period end", () => {
    const list = availableActions({ status: "active", cancel_at_period_end: true }, everything);
    expect(list).toContain("uncancel");
    expect(list).not.toContain("cancel");
  });
  it("offers a suspended business to be reactivated, not suspended again", () => {
    const list = availableActions({ status: "suspended", cancel_at_period_end: false }, everything);
    expect(list).toContain("reactivate");
    expect(list).not.toContain("suspend");
  });
  it("hides what the role cannot do", () => {
    const supportOnly = (p: string) => p === "platform.subscribers";
    const list = availableActions({ status: "active", cancel_at_period_end: false }, supportOnly);
    expect(list).toEqual(["suspend", "cancel", "export", "delete"]);
    expect(availableActions({ status: "active", cancel_at_period_end: false }, () => false)).toEqual([]);
  });
});
