import { describe, expect, it } from "vitest";

import { SIDEBAR } from "@/sdk";

import { arrange, orderAreas, PROFILES, profileFor, W } from "./homeProfiles";

const units = (...u: string[]) => new Set(u);

describe("profileFor", () => {
  it("reads the kind from a switched-on industry pack first, then the edition", () => {
    expect(profileFor("services", units("bookings", "pack_salon"))).toBe("salon");
    expect(profileFor("full", units("pack_garage", "jobs"))).toBe("garage");
    expect(profileFor("services", units("pack_fitness"))).toBe("gym");
    expect(profileFor("services", units("pack_education", "bookings"))).toBe("education");
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
  it("gives a pharmacy sales, what expires soon, low stock and things to look at", () => {
    expect(profileFor("retail", units("pos", "pack_pharmacy"))).toBe("pharmacy");
    expect(arrange(PROFILES.pharmacy, everything).stats).toEqual([W.salesToday, W.stockExpiring, W.lowStock, W.things]);
    expect(SIDEBAR.pharmacy.till).toBe(true);
  });
  it("gives a garage its jobs board and the two tiles that fill its row; the insurer's answer and claims lead its lists", () => {
    const plan = arrange(PROFILES.garage, everything);
    expect(plan.stats).toEqual([W.jobs, W.estimatesAwaiting, W.waitingParts]);
    expect(plan.lists.slice(0, 2)).toEqual([W.waitingInsurer, W.claimsWaiting]);
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

describe("the Home boxes of each service business", () => {
  const everything = Object.values(W);
  it("gives a salon who is free, checkouts waiting and its appointments, and the due-again list under them", () => {
    const plan = arrange(PROFILES.salon, everything);
    expect(plan.stats).toEqual([W.appointments, W.freeNow, W.checkoutsWaiting, W.salesToday]);
    expect(plan.lists).toContain(W.dueAgain);
  });
  it("gives a clinic its appointments, who is due again and claims waiting", () => {
    expect(arrange(PROFILES.clinic, everything).stats).toEqual([W.appointments, W.dueAgain, W.claimsWaiting, W.receivables]);
  });
  it("gives a gym check-ins, class fill, expiring memberships and late payments", () => {
    const plan = arrange(PROFILES.gym, everything);
    expect(plan.stats).toEqual([W.checkinsToday, W.classFill, W.expiring, W.paymentsLate]);
    expect(plan.lists).toContain(W.appointments);
  });
  it("gives a professional firm its work to bill and its deadlines first", () => {
    expect(arrange(PROFILES.professional, everything).stats.slice(0, 2)).toEqual([W.work, W.deadlines]);
  });
  it("puts the bank-to-match list in the books' lists", () => {
    expect(arrange(PROFILES.books, everything).lists[0]).toBe(W.bankToMatch);
  });
  it("shows a box only when its unit gave it (a gym without the memberships unit gets its other boxes)", () => {
    const noMemberships = everything.filter((id) => !id.startsWith("memberships:"));
    const plan = arrange(PROFILES.gym, noMemberships);
    expect(plan.stats).toContain(W.classFill);
    expect([...plan.stats, ...plan.lists, ...plan.more].some((id) => id.startsWith("memberships:"))).toBe(false);
  });
  it("names every new box by the label its module registers, so a rename in one place cannot orphan the other", async () => {
    const { default: bookings } = await import("@/modules/bookings/module");
    const { default: jobs } = await import("@/modules/jobs/module");
    const { default: claims } = await import("@/modules/claims/module");
    const { default: memberships } = await import("@/modules/memberships/module");
    const { default: timebilling } = await import("@/modules/timebilling/module");
    const { default: payments } = await import("@/modules/payments/module");
    const registered = [bookings, jobs, claims, memberships, timebilling, payments].flatMap((m) => (m.slots?.["dashboard.widgets"] ?? []).map((w) => w.label));
    for (const id of [W.freeNow, W.checkoutsWaiting, W.dueAgain, W.classFill, W.estimatesAwaiting, W.waitingParts, W.waitingInsurer, W.claimsWaiting, W.checkinsToday, W.expiring, W.paymentsLate, W.deadlines, W.bankToMatch]) expect(registered).toContain(id);
  });
  it("never lists a box twice for a kind, tile or list", () => {
    for (const profile of Object.values(PROFILES)) {
      const plan = arrange(profile, everything);
      const all = [...plan.stats, ...plan.lists, ...plan.more];
      expect(new Set(all).size).toBe(all.length);
    }
  });
});

describe("orderAreas", () => {
  it("puts the kind's areas first and keeps the rest in their order", () => {
    const areas = [{ id: "sell" }, { id: "stock" }, { id: "money" }, { id: "people" }] as const;
    expect(orderAreas(areas, ["money", "people"]).map((a) => a.id)).toEqual(["money", "people", "sell", "stock"]);
  });
});
