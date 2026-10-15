import { describe, expect, it } from "vitest";

import { coveragePercent, groupKinds, isStale, type Kind, oauthResult, sortEntities } from "./logic";

const kind = (k: string, group: string, freshness: Kind["freshness"]) => ({ kind: k, group, freshness }) as Kind;

describe("connect logic", () => {
  it("lists ERPs before statements and exports", () => {
    const grouped = groupKinds([kind("bank", "Statements and exports", "on_upload"), kind("odoo", "Your ERP", "daily"), kind("csv", "Statements and exports", "on_upload")]);
    expect(grouped.map((g) => g.group)).toEqual(["Your ERP", "Statements and exports"]);
    expect(grouped[1].kinds.map((k) => k.kind)).toEqual(["bank", "csv"]);
  });
  it("reads the OAuth result from the address", () => {
    expect(oauthResult("?oauth=success")).toEqual({ ok: true, reason: null });
    expect(oauthResult("?oauth=failed&reason=exchange_failed")).toEqual({ ok: false, reason: "exchange_failed" });
    expect(oauthResult("?x=1")).toBeNull();
  });
  it("calls a connection stale after three missed windows, never a file or paused one", () => {
    const base = { freshness: "daily", status: "active" as const, sync_every_minutes: 60, last_success_at: "2026-10-14T00:00:00Z" };
    expect(isStale(base, Date.parse("2026-10-14T02:59:00Z"))).toBe(false);
    expect(isStale(base, Date.parse("2026-10-14T03:01:00Z"))).toBe(true);
    expect(isStale({ ...base, freshness: "on_upload" }, Date.parse("2027-01-01T00:00:00Z"))).toBe(false);
    expect(isStale({ ...base, status: "paused" }, Date.parse("2027-01-01T00:00:00Z"))).toBe(false);
  });
  it("orders entities and computes coverage", () => {
    expect(sortEntities(["invoices", "sales", "weird", "branches"])).toEqual(["branches", "sales", "invoices", "weird"]);
    expect(coveragePercent([{ active: 1, total: 4 }, { active: 3, total: 4 }])).toBe(50);
    expect(coveragePercent([])).toBe(0);
  });
});
