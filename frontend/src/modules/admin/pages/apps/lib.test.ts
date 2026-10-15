import { describe, expect, it } from "vitest";

import { removeConfirmed, splitByKind, titlesOf, unitState, type UnitCard } from "./lib";

const card = (over: Partial<UnitCard>): UnitCard => ({
  name: "x", title: "X", description: "", kind: "module", version: "1.0.0", requires: [], optional: [], dependants: [], installed: true, enabled: false,
  has_data: false, will_also_enable: [], can_enable: true, can_disable: false, why_not_disable: null, can_remove: false, why_not_remove: null, ...over,
});

describe("unitState", () => {
  it("is on when enabled, off when only offered, unavailable when the platform lacks it", () => {
    expect(unitState({ installed: true, enabled: true })).toBe("on");
    expect(unitState({ installed: true, enabled: false })).toBe("off");
    expect(unitState({ installed: false, enabled: false })).toBe("unavailable");
  });
});

describe("splitByKind", () => {
  it("separates modules from plugins and keeps the order", () => {
    const cards = [card({ name: "a" }), card({ name: "p", kind: "plugin" }), card({ name: "b" })];
    const { modules, plugins } = splitByKind(cards);
    expect(modules.map((c) => c.name)).toEqual(["a", "b"]);
    expect(plugins.map((c) => c.name)).toEqual(["p"]);
  });
});

describe("titlesOf", () => {
  it("joins titles and falls back to the name", () => {
    const cards = [card({ name: "products", title: "Products" })];
    expect(titlesOf(cards, ["products", "ghost"])).toBe("Products, ghost");
    expect(titlesOf(cards, [])).toBe("");
  });
});

describe("removeConfirmed", () => {
  it("needs the exact name", () => {
    expect(removeConfirmed({ name: "inventory" }, "inventory")).toBe(true);
    expect(removeConfirmed({ name: "inventory" }, " inventory ")).toBe(true);
    expect(removeConfirmed({ name: "inventory" }, "Inventory")).toBe(false);
    expect(removeConfirmed({ name: "inventory" }, "")).toBe(false);
  });
});
