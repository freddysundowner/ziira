import { describe, expect, it } from "vitest";

import { mustGoToBilling, noticeFor, type BillingBanner } from "./noticeRules";

const banner = (over: Partial<BillingBanner>): BillingBanner => ({ level: "blocked", message: "m", status: "suspended", kind: "suspended", date: null, days_left: null, ...over });
const fmt = (v: string) => `<${v.slice(0, 10)}>`;

describe("mustGoToBilling", () => {
  it("sends a suspended owner to Plan & billing from any other page", () => {
    expect(mustGoToBilling(banner({}), "/")).toBe(true);
    expect(mustGoToBilling(banner({}), "/pos/sales")).toBe(true);
  });
  it("leaves them on billing and their account", () => {
    expect(mustGoToBilling(banner({}), "/admin/billing")).toBe(false);
    expect(mustGoToBilling(banner({}), "/admin/account")).toBe(false);
  });
  it("does nothing for businesses that are not suspended, or no banner", () => {
    expect(mustGoToBilling(banner({ status: "past_due", level: "warning" }), "/")).toBe(false);
    expect(mustGoToBilling(banner({ status: "expired" }), "/")).toBe(false);
    expect(mustGoToBilling(null, "/")).toBe(false);
  });
});

describe("noticeFor", () => {
  it("words an ended trial with its date", () => {
    expect(noticeFor(banner({ kind: "trial_ended", date: "2030-02-01T00:00:00Z" }), fmt)).toEqual({ tone: "bad", key: "billing.notice.trialEnded", params: { date: "<2030-02-01>" } });
  });
  it("speaks about a running trial only in its last week", () => {
    const trial = (days: number) => banner({ kind: "trial", status: "trialing", level: "info", days_left: days });
    expect(noticeFor(trial(20), fmt)).toBeNull();
    expect(noticeFor(trial(7), fmt)).toMatchObject({ tone: "info", key: "billing.notice.trialEnding", params: { count: 7 } });
    expect(noticeFor(trial(3), fmt)).toMatchObject({ tone: "warn" });
    expect(noticeFor(trial(1), fmt)).toMatchObject({ tone: "warn", params: { count: 1 } });
    expect(noticeFor(trial(0), fmt)).toMatchObject({ key: "billing.notice.trialToday" });
  });
  it("warns about an overdue payment and falls back to the server's words", () => {
    expect(noticeFor(banner({ kind: "grace", level: "warning", status: "grace" }), fmt)).toMatchObject({ tone: "warn", key: "billing.notice.overdue" });
    expect(noticeFor(banner({ kind: "other", status: "expired", message: "Read only" }), fmt)).toMatchObject({ tone: "bad", text: "Read only" });
    expect(noticeFor(null, fmt)).toBeNull();
  });
});
