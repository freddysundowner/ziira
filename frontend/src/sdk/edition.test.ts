import { describe, expect, it } from "vitest";

import { landingTarget, orderedGroups, progress, visibleSteps, type EditionStep } from "./edition";

const step = (id: string, unit = ""): EditionStep => ({ id, title: id, hint: "", to: `/${id}`, unit });

describe("orderedGroups", () => {
  it("puts the edition's sections first and the rest after in the usual order", () => {
    expect(orderedGroups({ menu_groups: ["money", "buy"] })).toEqual(["money", "buy", "sell", "stock", "people", "admin"]);
  });
  it("is the usual order with no edition, and ignores sections it does not know", () => {
    expect(orderedGroups(undefined)).toEqual(["sell", "stock", "buy", "money", "people", "admin"]);
    expect(orderedGroups({ menu_groups: ["nonsense", "stock"] })[0]).toBe("stock");
  });
});

describe("first steps", () => {
  const edition = { checklist: [step("a", "products"), step("b", "pos"), step("c")] };
  it("shows only steps whose unit is on", () => {
    expect(visibleSteps(edition, new Set(["products"])).map((s) => s.id)).toEqual(["a", "c"]);
  });
  it("counts what is done and knows when all are", () => {
    const steps = visibleSteps(edition, new Set(["products", "pos"]));
    expect(progress(steps, ["a"])).toEqual({ done: 1, total: 3, complete: false });
    expect(progress(steps, ["a", "b", "c", "zzz"])).toEqual({ done: 3, total: 3, complete: true });
    expect(progress([], []).complete).toBe(false);
  });
});

describe("landingTarget", () => {
  const open = new Set(["/pos/terminal"]);
  it("goes to the landing page once, when the person may open it", () => {
    expect(landingTarget("/pos/terminal", open, false)).toBe("/pos/terminal");
    expect(landingTarget("/pos/terminal", open, true)).toBeNull();
    expect(landingTarget("/finance/reports", open, false)).toBeNull();
    expect(landingTarget("", open, false)).toBeNull();
    expect(landingTarget(undefined, open, false)).toBeNull();
  });
});
