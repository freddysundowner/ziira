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
