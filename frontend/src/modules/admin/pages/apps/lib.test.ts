import { describe, expect, it } from "vitest";

import { countryName, isIndustryPack, recommendedForEdition, recommendedPlugins, removeConfirmed, titlesOf, unitState, visibleCards, wouldSwitchOn, type UnitCard } from "./lib";

const card = (over: Partial<UnitCard>): UnitCard => ({
  name: "x", title: "X", description: "", category: "", countries: [], kind: "module", version: "1.0.0", requires: [], optional: [], dependants: [], installed: true, enabled: false,
  has_data: false, in_plan: true, will_also_enable: [], can_enable: true, can_disable: false, why_not_disable: null, can_remove: false, why_not_remove: null, ...over,
});

describe("unitState", () => {
  it("is on when enabled, off when only offered, unavailable when the platform lacks it", () => {
    expect(unitState({ installed: true, enabled: true })).toBe("on");
    expect(unitState({ installed: true, enabled: false })).toBe("off");
    expect(unitState({ installed: false, enabled: false })).toBe("unavailable");
  });
});

describe("visibleCards", () => {
  const cards = [card({ name: "b", title: "Beta", enabled: true }), card({ name: "a", title: "Alpha" }), card({ name: "z", title: "Zed", installed: false }),
    card({ name: "c", title: "Cash", enabled: true, description: "Takes payments" }), card({ name: "d", title: "Delta" })];
  it("lists switched on first, then available, then not available yet, alphabetical inside each", () => {
    expect(visibleCards(cards, "", "all").map((c) => c.name)).toEqual(["b", "c", "a", "d", "z"]);
  });
  it("filters by status (off includes those not offered yet) and by words in the title, name or description", () => {
    expect(visibleCards(cards, "", "on").map((c) => c.name)).toEqual(["b", "c"]);
    expect(visibleCards(cards, "", "off").map((c) => c.name)).toEqual(["a", "d", "z"]);
    expect(visibleCards(cards, "  PAYMENTS take", "all").map((c) => c.name)).toEqual(["c"]);
    expect(visibleCards(cards, "nothing like this", "all")).toEqual([]);
  });
});

describe("recommendedPlugins", () => {
  const plugins = [
    card({ name: "world", kind: "plugin", category: "payments" }),
    card({ name: "ke", kind: "plugin", category: "payments", countries: ["KE"] }),
    card({ name: "on", kind: "plugin", category: "payments", enabled: true }),
    card({ name: "later", kind: "plugin", category: "payments", installed: false }),
    card({ name: "other", kind: "plugin", category: "ai" }),
    card({ name: "mod", category: "payments" }),
  ];
  it("suggests worldwide plugins and those for the business's country, in the edition's categories", () => {
    expect(recommendedPlugins(plugins, { plugin_categories: ["payments"] }, "ke").map((c) => c.name)).toEqual(["world", "ke"]);
    expect(recommendedPlugins(plugins, { plugin_categories: ["payments"] }, "GB").map((c) => c.name)).toEqual(["world"]);
    expect(recommendedPlugins(plugins, { plugin_categories: ["payments"] }, null).map((c) => c.name)).toEqual(["world"]);
    expect(recommendedPlugins(plugins, undefined, "KE")).toEqual([]);
  });

  it("suggests the country pack that names the business's country, whatever the edition, and never the worldwide pack", () => {
    const packs = [card({ name: "pack_ke", kind: "plugin", category: "country", countries: ["KE"] }), card({ name: "pack_international", kind: "plugin", category: "country" }),
      card({ name: "pack_done", kind: "plugin", category: "country", countries: ["KE"], enabled: true })];
    expect(recommendedPlugins(packs, undefined, "ke").map((c) => c.name)).toEqual(["pack_ke"]);
    expect(recommendedPlugins(packs, { plugin_categories: [] }, "GB")).toEqual([]);
    expect(recommendedPlugins(packs, undefined, null)).toEqual([]);
  });
});

describe("countryName", () => {
  it("names a country in the reader's language and falls back to the code", () => {
    expect(countryName("ke", "en")).toBe("Kenya");
    expect(countryName(null, "en")).toBe("");
    expect(countryName("zz", "en")).toBeTruthy();
  });
});

describe("wouldSwitchOn", () => {
  const cards = [card({ name: "pos", requires: ["products", "inventory"] }), card({ name: "products" }), card({ name: "inventory", requires: ["products"] }),
    card({ name: "crm", enabled: true }), card({ name: "finance" })];
  it("lists the edition's units that are off, with what they need, once each", () => {
    expect(wouldSwitchOn(cards, { units: ["pos", "crm", "finance", "ghost"] }).sort()).toEqual(["finance", "inventory", "pos", "products"]);
    expect(wouldSwitchOn(cards, { units: ["crm"] })).toEqual([]);
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

describe("industry packs", () => {
  const pack = (over: Partial<UnitCard> = {}) => card({ name: "pack_salon", category: "industry", kind: "plugin", editions: ["services"], ...over });
  it("are recognised by their category", () => {
    expect(isIndustryPack(pack())).toBe(true);
    expect(isIndustryPack(card({ category: "stock" }))).toBe(false);
  });
  it("are recommended for the editions they name, until they are on", () => {
    expect(recommendedForEdition(pack(), "services")).toBe(true);
    expect(recommendedForEdition(pack(), "retail")).toBe(false);
    expect(recommendedForEdition(pack({ enabled: true }), "services")).toBe(false);
    expect(recommendedForEdition(pack(), undefined)).toBe(false);
    expect(recommendedForEdition(card({ editions: ["services"] }), "services")).toBe(false);          // not a pack
  });
  it("are not suggested through the edition's plugin categories (they name their editions instead)", () => {
    expect(recommendedPlugins([pack()], { plugin_categories: ["industry"] }, "KE")).toEqual([]);
  });
});
