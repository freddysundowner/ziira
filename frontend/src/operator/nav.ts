import { Activity, Boxes, Globe, KeyRound, LayoutDashboard, type LucideIcon, Receipt, ShieldCheck, Tag, Users } from "lucide-react";

/**
 * The console's menu. Each item names the permission that shows it (every role has `platform.view`; the server refuses
 * the rest anyway). To add an area: add an item to a group here and a route in OperatorApp.tsx.
 */
export interface NavItem {
  to: string;
  /** Translation key under "operator". */
  key: string;
  icon: LucideIcon;
  permission: string;
  /** Hidden when this deployment does not have the feature (the Website area in a self-hosted copy). */
  feature?: string;
}

export interface NavGroup {
  key: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  { key: "nav.groups.overview", items: [{ to: "/operator/dashboard", key: "nav.dashboard", icon: LayoutDashboard, permission: "platform.view" }] },
  {
    key: "nav.groups.customers",
    items: [
      { to: "/operator/subscribers", key: "nav.subscribers", icon: Users, permission: "platform.view" },
      { to: "/operator/licences", key: "nav.licences", icon: KeyRound, permission: "platform.view" },
    ],
  },
  {
    key: "nav.groups.sell",
    items: [
      { to: "/operator/plans", key: "nav.plans", icon: Tag, permission: "platform.view" },
      { to: "/operator/billing", key: "nav.billing", icon: Receipt, permission: "platform.view" },
    ],
  },
  {
    key: "nav.groups.platform",
    items: [
      { to: "/operator/units", key: "nav.units", icon: Boxes, permission: "platform.view" },
      { to: "/operator/website", key: "nav.website", icon: Globe, permission: "platform.content", feature: "website" },
      { to: "/operator/health", key: "nav.health", icon: Activity, permission: "platform.view" },
      { to: "/operator/operators", key: "nav.operators", icon: ShieldCheck, permission: "platform.operators" },
    ],
  },
];

/** The groups with only the items this operator may open; empty groups disappear. */
export function visibleNav(groups: NavGroup[], permissions: readonly string[], missingFeatures: readonly string[] = []): NavGroup[] {
  return groups
    .map((g) => ({ ...g, items: g.items.filter((i) => permissions.includes(i.permission) && !(i.feature && missingFeatures.includes(i.feature))) }))
    .filter((g) => g.items.length > 0);
}
