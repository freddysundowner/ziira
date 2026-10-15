import { describe, expect, it } from "vitest";

import { actionsFor, ageInDays, atDefaults, type Check, draftChanges, groupChecks, paramKind, resetChanges, statusesFor } from "./logic";

const check = (over: Partial<Check>): Check => ({ code: "x.y", title: "T", area: "stock", description: "", severity: "low", enabled: true, auto_resolves: true, defaults: {}, params: {}, ...over });

describe("statusesFor", () => {
  it("leaves open to the server and expands the groups", () => {
    expect(statusesFor("open")).toBeUndefined();
    expect(statusesFor("closed")).toEqual(["resolved", "dismissed"]);
    expect(statusesFor("all")).toHaveLength(6);
    expect(statusesFor("explained")).toEqual(["explained"]);
  });
});

describe("actionsFor", () => {
  const f = (status: string, owner: string | null = null) => ({ status, owner_user_id: owner });
  it("gives managers everything on an open finding, less where it is already done", () => {
    expect(actionsFor(f("new"), { manage: true, respond: false }, "u1")).toEqual({ acknowledge: true, explain: true, resolve: true, dismiss: true, assign: true, ask: true });
    expect(actionsFor(f("acknowledged"), { manage: true, respond: false }, "u1").acknowledge).toBe(false);
    expect(actionsFor(f("explained"), { manage: true, respond: false }, "u1").explain).toBe(false);
  });
  it("lets a responder answer only what is assigned to them", () => {
    expect(actionsFor(f("sent", "u1"), { manage: false, respond: true }, "u1")).toMatchObject({ explain: true, acknowledge: true, resolve: false, dismiss: false, assign: false, ask: false });
    expect(actionsFor(f("sent", "u2"), { manage: false, respond: true }, "u1").explain).toBe(false);
    expect(actionsFor(f("sent", null), { manage: false, respond: false }, "u1").explain).toBe(false);
  });
  it("offers nothing once closed", () => {
    expect(Object.values(actionsFor(f("resolved", "u1"), { manage: true, respond: true }, "u1")).some(Boolean)).toBe(false);
  });
});

describe("ageInDays", () => {
  it("counts whole days and never goes negative", () => {
    const now = new Date("2026-10-14T12:00:00Z");
    expect(ageInDays("2026-10-11T13:00:00Z", now)).toBe(2);
    expect(ageInDays("2026-10-20T00:00:00Z", now)).toBe(0);
  });
});

describe("check limits", () => {
  const c = check({ defaults: { limit: 5, ratio: "0.5", name: "a", strict: false }, params: { limit: 8, ratio: "0.5", name: "a", strict: false } });
  it("tells number, boolean and text apart", () => {
    expect(paramKind(5)).toBe("number");
    expect(paramKind("0.5")).toBe("number");
    expect(paramKind(true)).toBe("boolean");
    expect(paramKind("abc")).toBe("text");
  });
  it("sends only changed limits", () => {
    expect(draftChanges(c, { limit: "8", ratio: "0.7", name: "a", strict: "true" })).toEqual({ ratio: "0.7", strict: true });
    expect(draftChanges(c, { limit: "8", ratio: "0.5", name: "a", strict: "false" })).toEqual({});
  });
  it("knows when limits are at their defaults and how to reset them", () => {
    expect(atDefaults(c)).toBe(false);
    expect(resetChanges(c)).toEqual({ limit: 5 });
    expect(atDefaults(check({ defaults: { a: 1 }, params: { a: 1 } }))).toBe(true);
  });
});

describe("groupChecks", () => {
  it("orders known areas first and unknown ones last", () => {
    const groups = groupChecks([check({ code: "a", area: "people" }), check({ code: "b", area: "zzz" }), check({ code: "c", area: "cash_sales" }), check({ code: "d", area: "people" })]);
    expect(groups.map((g) => g.area)).toEqual(["cash_sales", "people", "zzz"]);
    expect(groups[1].checks).toHaveLength(2);
  });
});

describe("the AI assistant", () => {
  it("maps reasons to translation keys, with a generic one for unknown reasons", async () => {
    const { reasonKey, fixableInSettings } = await import("./logic");
    expect(reasonKey("budget")).toBe("budget");
    expect(reasonKey("something_new")).toBe("default");
    expect(reasonKey(null)).toBe("default");
    expect(fixableInSettings("no_consent")).toBe(true);
    expect(fixableInSettings("not_configured")).toBe(false);
    expect(fixableInSettings(undefined)).toBe(false);
  });

  it("shows a source's columns in order, without ids, and no more than six", async () => {
    const { sourceColumns, cellText } = await import("./logic");
    expect(sourceColumns([{ branch: "HQ", branch_id: "x", id: "y", total: "1" }, { branch: "J", note: "n" }])).toEqual(["branch", "total", "note"]);
    expect(sourceColumns([{ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7 }])).toEqual(["a", "b", "c", "d", "e", "f"]);
    expect(sourceColumns([])).toEqual([]);
    expect([cellText(null), cellText(5), cellText(false), cellText("x"), cellText({ a: 1 })]).toEqual(["", "5", "false", "x", '{"a":1}']);
  });

  it("lines numbers up to the right", async () => {
    const { isNumeric } = await import("./logic");
    expect([isNumeric(5), isNumeric("1250.00"), isNumeric("-3"), isNumeric("HQ"), isNumeric("12 units"), isNumeric(null)]).toEqual([true, true, true, false, false, false]);
  });

  it("names the period of a source", async () => {
    const { sourcePeriod } = await import("./logic");
    expect(sourcePeriod({ params: { date_from: "2026-10-01", date_to: "2026-10-07" } })).toBe("2026-10-01 – 2026-10-07");
    expect(sourcePeriod({ params: { date_from: "2026-10-01", date_to: "2026-10-01" } })).toBe("2026-10-01");
    expect(sourcePeriod({ params: { limit: 5 } })).toBeNull();
  });
});
