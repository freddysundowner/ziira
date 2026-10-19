import { describe, expect, it } from "vitest";

import {
  barWidth, busiest, daysAgo, heatGrid, initials, intensity, kioskReasonKey, kioskView, lateDays, looksLikeIdentifier, newWindow, parseReport, readWindows, retentionIntensity,
  share, splitCodes, toggleDay, viewFromRoster, viewFromServer, windowsProblem, type CheckinResult,
} from "./gymLogic";

const base: CheckinResult = {
  outcome: "allow", allowed: true, code: "ok", message: "Welcome", reasons: [], duplicate: false, overridden: false, can_override: false,
  checkin_id: "k1", occurred_at: "2026-03-01T08:00:00Z", entitlement: "Monthly", credits_left: null, classes_today: [],
  person: {
    customer_id: "c1", profile_id: "p1", number: "M-0001", name: "Jane Wanjiru", phone: "0712", photo_file_id: null, photo_link: "/api/v1/files/x",
    lifecycle: "member", plan_name: "Monthly", membership_status: "active", next_renewal_date: null, owed: "0.00",
  },
};

describe("viewFromServer", () => {
  it("shows an allowed person with their plan and photo", () => {
    const v = viewFromServer(base);
    expect(v).toMatchObject({ outcome: "allow", name: "Jane Wanjiru", number: "M-0001", plan: "Monthly", photoUrl: "/api/v1/files/x", owed: 0 });
  });
  it("marks a refused person who needs the terms, and one who may be let in anyway", () => {
    const v = viewFromServer({ ...base, outcome: "deny", allowed: false, code: "waiver_missing", can_override: true,
      reasons: [{ code: "waiver_missing", message: "The current terms have not been accepted", level: "deny" }] });
    expect(v).toMatchObject({ outcome: "deny", needsTerms: true, canOverride: true });
  });
  it("keeps warn for a warned person and notes someone already in", () => {
    const v = viewFromServer({ ...base, outcome: "warn", reasons: [{ code: "payment_late", message: "Payment is 3 days late", level: "warn" }], duplicate: true });
    expect(v.outcome).toBe("warn");
    expect(v.duplicate).toBe(true);
  });
  it("treats an unknown number as not found", () => {
    const v = viewFromServer({ ...base, outcome: "deny", allowed: false, code: "not_found", person: null, message: "Nobody has this number or card" });
    expect(v.notFound).toBe(true);
    expect(v.name).toBeNull();
  });
  it("counts an override as allowed", () => {
    expect(viewFromServer({ ...base, outcome: "deny", allowed: true, overridden: true }).outcome).toBe("allow");
  });
});

describe("viewFromRoster", () => {
  it("carries the time the list was saved", () => {
    const v = viewFromRoster({ number: "M-1", card_number: null, outcome: "deny", code: "ended", message: "Membership ended", plan: null, name: "A B" }, 123);
    expect(v).toMatchObject({ outcome: "deny", offlineSavedAt: 123, canOverride: false });
  });
});

describe("text helpers", () => {
  it("tells identifiers from names", () => {
    expect(looksLikeIdentifier("M-0042")).toBe(true);
    expect(looksLikeIdentifier("0712345678")).toBe(true);
    expect(looksLikeIdentifier("Jane Wanjiru")).toBe(false);
    expect(looksLikeIdentifier("Jane")).toBe(false);
    expect(looksLikeIdentifier("  ")).toBe(false);
  });
  it("makes initials", () => {
    expect(initials("Jane Wanjiru")).toBe("JW");
    expect(initials("Cher")).toBe("C");
    expect(initials(null)).toBe("?");
  });
  it("splits codes and removes repeats", () => {
    expect(splitCodes("L1, L2\nL3 L2;;")).toEqual(["L1", "L2", "L3"]);
  });
});

describe("kiosk", () => {
  it("never carries more than the first name and a plain reason", () => {
    const v = kioskView({ ...base, outcome: "deny", allowed: false, code: "payment_overdue", reasons: [{ code: "payment_overdue", message: "Payment is 40 days late (5,000.00 owed)", level: "deny" }] });
    expect(v).toEqual({ outcome: "deny", firstName: "Jane", reasonKey: "payment_overdue", needsTerms: false, customerId: "c1" });
  });
  it("welcomes with no reason and falls back for codes it does not know", () => {
    expect(kioskView(base)).toMatchObject({ outcome: "allow", reasonKey: null });
    expect(kioskReasonKey("something_new")).toBe("generic");
  });
  it("asks for the terms when they are missing", () => {
    const v = kioskView({ ...base, outcome: "deny", allowed: false, code: "waiver_missing", reasons: [{ code: "waiver_missing", message: "x", level: "deny" }] });
    expect(v.needsTerms).toBe(true);
  });
});

describe("access windows", () => {
  it("reads what the plan stores", () => {
    expect(readWindows([{ days: [0, 4, 9], from: "06:00", to: "10:00" }, { from: 5 }])).toEqual([
      { days: [0, 4], from: "06:00", to: "10:00" }, { days: [], from: "06:00", to: "22:00" }]);
    expect(readWindows(null)).toEqual([]);
  });
  it("finds a window with no day or with times the wrong way round", () => {
    expect(windowsProblem([newWindow()])).toBeNull();
    expect(windowsProblem([{ days: [], from: "06:00", to: "10:00" }])).toBe("days");
    expect(windowsProblem([{ days: [1], from: "10:00", to: "09:00" }])).toBe("times");
    expect(windowsProblem([{ days: [1], from: "10:00", to: "24:00" }])).toBeNull();
  });
  it("toggles a day and keeps the days in order", () => {
    expect(toggleDay([0, 2], 1)).toEqual([0, 1, 2]);
    expect(toggleDay([0, 1, 2], 1)).toEqual([0, 2]);
  });
});

describe("heat map", () => {
  const cells = [{ weekday: 0, hour: 7, visits: 10 }, { weekday: 0, hour: 18, visits: 40 }, { weekday: 6, hour: 23, visits: 2 }];
  it("builds a grid over the hours that have visits", () => {
    const g = heatGrid(cells);
    expect(g.hours[0]).toBe(6);
    expect(g.hours[g.hours.length - 1]).toBe(23);
    expect(g.max).toBe(40);
    expect(g.total).toBe(52);
    expect(g.rows[0]?.[18 - 6]).toBe(40);
    expect(g.rows).toHaveLength(7);
  });
  it("shades in steps and leaves empty cells unshaded", () => {
    expect(intensity(0, 40)).toBe(0);
    expect(intensity(40, 40)).toBe(1);
    expect(intensity(1, 40)).toBe(0.2);
  });
  it("finds the busiest hour", () => {
    expect(busiest(cells)).toEqual({ weekday: 0, hour: 18, visits: 40 });
    expect(busiest([])).toBeNull();
  });
  it("shades retention but not what is not known yet", () => {
    expect(retentionIntensity(null)).toBe(0);
    expect(retentionIntensity(100)).toBe(1);
    expect(retentionIntensity(3)).toBeGreaterThan(0);
  });
});

describe("dates and shares", () => {
  it("counts late days and goes back in time", () => {
    expect(lateDays("2026-03-01", "2026-03-11")).toBe(10);
    expect(lateDays(null, "2026-03-11")).toBe(0);
    expect(daysAgo("2026-03-01", 1)).toBe("2026-02-28");
  });
  it("gives a whole-number share", () => {
    expect(share(1, 3)).toBe(33);
    expect(share(1, 0)).toBe(0);
  });
});

describe("parseReport", () => {
  it("turns the loose lists into typed rows and tolerates what is missing", () => {
    const r = parseReport({
      company_id: "c", start: "2026-01-01", end: "2026-03-01", branch_id: null, members: { active: 10, inactive_4_weeks: 2 }, mrr: "100.00", revenue_at_risk: "10.00",
      revenue_at_risk_percent: 10, by_plan: [{ plan: "Gold", members: 4, mrr: "80.00" }], flow: [{ month: "2026-01-01", new: 3, ended: 1, net: 2 }],
      retention: [{ month: "2026-01-01", joined: 5, still_member_percent: [100, 80, null] }], attendance: [{ weekday: 1, hour: 7, visits: 9 }], visits: 9, visitors: 5,
      arrears: { owed: "50.00", people: 2 }, freezes: { holds: 1, days: 10, fees: "0", running: 0 }, trials: { started: 4, converted: 1 },
      leaving: [{ reason: "Moved", members: 2 }], class_fill: [{ class: "Spin", sessions: 4, booked: 30, places: 40, fill_percent: 75 }], trainers: [{ trainer: "Ann", sessions: 3, earned: "30.00" }],
    });
    expect(r.members).toMatchObject({ active: 10, paused: 0, inactive: 2 });
    expect(r.retention[0]?.percent).toEqual([100, 80, null]);
    expect(r.owed).toMatchObject({ owed: "50.00", people: 2, d7: "0" });
    expect(r.classes[0]).toMatchObject({ name: "Spin", fill: 75 });
    expect(r.trainers[0]?.trainer).toBe("Ann");
  });
});

describe("barWidth", () => {
  it("scales to the biggest and keeps a small value visible", () => {
    expect(barWidth(50, 100)).toBe(50);
    expect(barWidth(1, 1000)).toBe(3);
    expect(barWidth(0, 10)).toBe(0);
    expect(barWidth(5, 0)).toBe(0);
  });
});
