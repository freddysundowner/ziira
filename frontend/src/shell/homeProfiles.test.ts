import { describe, expect, it } from "vitest";

import { arrange, orderAreas, PROFILES, profileFor, W } from "./homeProfiles";

const units = (...u: string[]) => new Set(u);

describe("profileFor", () => {
  it("reads the kind from a switched-on industry pack first, then the edition", () => {
    expect(profileFor("services", units("bookings", "pack_salon"))).toBe("salon");
    expect(profileFor("full", units("pack_garage", "jobs"))).toBe("garage");
    expect(profileFor("services", units("pack_fitness"))).toBe("gym");
    expect(profileFor("retail", units("pos"))).toBe("retail");
    expect(profileFor("distribution", units())).toBe("distribution");
    expect(profileFor("books", units())).toBe("books");
    expect(profileFor("services", units())).toBe("services");
  });
  it("falls back to the all-round Home for the full edition, an unknown edition or none yet", () => {
    expect(profileFor("full", units())).toBe("full");
    expect(profileFor("something-new", units())).toBe("full");
    expect(profileFor(undefined, units())).toBe("full");
  });
});

describe("arrange", () => {
  const everything = Object.values(W);
  it("gives a shop its sales, tills, low stock and things to look at, in that order", () => {
    expect(arrange(PROFILES.retail, everything).stats).toEqual([W.salesToday, W.openTills, W.lowStock, W.things]);
  });
  it("gives a distributor orders, receivables, stock and suppliers to pay", () => {
    expect(arrange(PROFILES.distribution, everything).stats).toEqual([W.salesToday, W.receivables, W.lowStock, W.billsDue]);
  });
  it("gives a garage its jobs board first and a salon its appointments", () => {
    expect(arrange(PROFILES.garage, everything).stats[0]).toBe(W.jobs);
    expect(arrange(PROFILES.salon, everything).stats[0]).toBe(W.appointments);
  });
  it("shows nothing for a unit that is off, and never invents a box", () => {
    const shop = arrange(PROFILES.retail, [W.salesToday, W.things]);
    expect(shop.stats).toEqual([W.salesToday, W.things]);
    expect([...shop.stats, ...shop.lists, ...shop.more]).not.toContain(W.lowStock);
  });
  it("tops a thin row up so it is never empty when other boxes exist", () => {
    const plan = arrange(PROFILES.salon, [W.things, W.salesToday, W.received]);
    expect(plan.stats.length).toBe(3);
  });
  it("moves the boxes that do not apply behind More, each exactly once", () => {
    const plan = arrange(PROFILES.books, everything);
    expect(plan.more).toContain(W.openTills);
    expect(plan.stats).not.toContain(W.openTills);
    const all = [...plan.stats, ...plan.lists, ...plan.more];
    expect(new Set(all).size).toBe(all.length);
    expect(all.length).toBe(everything.length);
  });
});

describe("orderAreas", () => {
  it("puts the kind's areas first and keeps the rest in their order", () => {
    const areas = [{ id: "sell" }, { id: "stock" }, { id: "money" }, { id: "people" }] as const;
    expect(orderAreas(areas, ["money", "people"]).map((a) => a.id)).toEqual(["money", "people", "sell", "stock"]);
  });
});
