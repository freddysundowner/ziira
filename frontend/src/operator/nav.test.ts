import { describe, expect, it } from "vitest";

import { crumbParts, findCurrent, isActive, NAV_GROUPS, visibleNav } from "./nav";

const ROLES: Record<string, string[]> = {
  superadmin: ["platform.view", "platform.subscribers", "platform.plans", "platform.billing", "platform.licences", "platform.units", "platform.content", "platform.ai", "platform.settings", "platform.operators"],
  billing: ["platform.view", "platform.subscribers", "platform.plans", "platform.billing", "platform.licences"],
  support: ["platform.view", "platform.subscribers"],
  content: ["platform.view", "platform.content"],
  readonly: ["platform.view"],
};
const ids = (permissions: string[], missing: string[] = []) => visibleNav(NAV_GROUPS, permissions, missing).flatMap((g) => g.items.map((i) => i.id));
const READ_ONLY_SET = ["dashboard", "subscribers", "licences", "requests", "plans", "coupons", "invoices", "methods", "billingSettings", "units", "health", "backups", "attempts"];

describe("the sidebar for each role", () => {
  it("shows a read-only operator every screen that only needs to look", () => {
    expect(ids(ROLES.readonly!)).toEqual(READ_ONLY_SET);
  });
  it("adds the website screens for content staff and nothing else", () => {
    expect(ids(ROLES.content!)).toEqual(["dashboard", "subscribers", "licences", "requests", "plans", "coupons", "invoices", "methods", "billingSettings",
      "siteCompany", "sitePages", "siteMedia", "sitePublish", "units", "health", "backups", "attempts"]);
  });
  it("gives billing and support the same screens as read only (their extra rights are buttons inside)", () => {
    expect(ids(ROLES.billing!)).toEqual(READ_ONLY_SET);
    expect(ids(ROLES.support!)).toEqual(READ_ONLY_SET);
  });
  it("gives a super admin everything, in the section order of the brief", () => {
    const groups = visibleNav(NAV_GROUPS, ROLES.superadmin!);
    expect(groups.map((g) => g.key.replace("nav.groups.", ""))).toEqual(["overview", "customers", "revenue", "website", "platform", "system"]);
    expect(groups.flatMap((g) => g.items.map((i) => i.id))).toEqual([
      "dashboard", "subscribers", "licences", "requests", "plans", "coupons", "invoices", "methods", "billingSettings", "siteCompany", "sitePages", "siteMedia", "sitePublish",
      "units", "ai", "email", "settings", "operators", "health", "backups", "audit", "mailLog", "attempts"]);
  });
  it("hides the website when the deployment has none, and drops sections that become empty", () => {
    expect(ids(ROLES.superadmin!, ["website"])).not.toContain("siteCompany");
    const groups = visibleNav(NAV_GROUPS, ROLES.content!, ["website"]).map((g) => g.key);
    expect(groups).not.toContain("nav.groups.website");
  });
  it("never lists an item twice and points each at a console address", () => {
    const all = NAV_GROUPS.flatMap((g) => g.items);
    expect(new Set(all.map((i) => i.id)).size).toBe(all.length);
    expect(all.every((i) => i.to.startsWith("/operator/"))).toBe(true);
  });
});

describe("which item is open", () => {
  const open = (path: string, search = "") => findCurrent(NAV_GROUPS, path, search)?.item.id;
  it("marks one item for ordinary addresses", () => {
    expect(open("/operator/dashboard")).toBe("dashboard");
    expect(open("/operator/subscribers/shop-a")).toBe("subscribers");
    expect(open("/operator/businesses/shop-a")).toBe("subscribers");
    expect(open("/operator/billing")).toBe("invoices");
    expect(open("/operator/billing/requests")).toBe("requests");
    expect(open("/operator/billing/settings")).toBe("billingSettings");
    expect(open("/operator/payment-methods")).toBe("methods");
    expect(open("/operator/payment-attempts")).toBe("attempts");
  });
  it("keeps Plans and Coupons apart although they share a page", () => {
    expect(open("/operator/plans")).toBe("plans");
    expect(open("/operator/plans/addons")).toBe("plans");
    expect(open("/operator/plans/edit/pro")).toBe("plans");
    expect(open("/operator/plans/coupons")).toBe("coupons");
  });
  it("tells the website sections apart by the tab in the address", () => {
    expect(open("/operator/website")).toBe("siteCompany");
    expect(open("/operator/website", "?tab=seo")).toBe("siteCompany");
    expect(open("/operator/website", "?tab=pages")).toBe("sitePages");
    expect(open("/operator/website", "?tab=banner")).toBe("sitePages");
    expect(open("/operator/website", "?tab=media")).toBe("siteMedia");
    expect(open("/operator/website", "?tab=publish")).toBe("sitePublish");
  });
  it("knows nothing about an address that is not in the menu", () => {
    expect(open("/operator/account")).toBeUndefined();
    const item = NAV_GROUPS[0]!.items[0]!;
    expect(isActive(item, "/operator/dashboardx", "")).toBe(false);
  });
  it("builds breadcrumb parts, with the record on a detail page", () => {
    expect(crumbParts(NAV_GROUPS, "/operator/subscribers/shop-a", "")).toMatchObject({ groupKey: "nav.groups.customers", itemId: "subscribers", rest: "shop-a" });
    expect(crumbParts(NAV_GROUPS, "/operator/plans/edit/pro", "")).toMatchObject({ itemId: "plans", rest: "pro" });
    expect(crumbParts(NAV_GROUPS, "/operator/health", "")).toMatchObject({ groupKey: "nav.groups.system", itemId: "health", rest: null });
    expect(crumbParts(NAV_GROUPS, "/operator/nowhere", "").groupKey).toBeNull();
  });
});
