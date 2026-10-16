import {
  Activity, Boxes, Brain, Building2, CreditCard, DatabaseBackup, FileText, Globe, Image, Inbox, KeyRound, LayoutDashboard, type LucideIcon, Mail, MailOpen,
  Receipt, ScrollText, Settings, ShieldCheck, SlidersHorizontal, Tag, Ticket, UploadCloud, Users, Wallet,
} from "lucide-react";

/**
 * The Super Admin's sidebar. Each item names the permission that shows it (every role has `platform.view`; the server
 * refuses the rest anyway). To add a screen: add an item to a group here, a route in OperatorApp.tsx and its words
 * under "nav.i.<id>" in i18n/*.shell.json. `match` decides when the item is the open one (default: the address starts
 * with `to`); items that share one page through `?tab=` list the tabs they stand for.
 */
export interface NavItem {
  id: string;
  to: string;
  icon: LucideIcon;
  permission: string;
  /** Hidden when this deployment does not have the feature (the Website area in a self-hosted copy). */
  feature?: string;
  match?: (pathname: string, params: URLSearchParams) => boolean;
  /** Extra words the search box finds this screen by (English; the screen's own name is always searched). */
  keywords?: string;
}

export interface NavGroup {
  key: string;
  items: NavItem[];
}

const OP = "/operator";
const startsWith = (prefix: string) => (pathname: string) => pathname === prefix || pathname.startsWith(`${prefix}/`);
const websiteTab = (...tabs: string[]) => (pathname: string, params: URLSearchParams) =>
  pathname === `${OP}/website` && tabs.includes(params.get("tab") ?? "company");

export const NAV_GROUPS: NavGroup[] = [
  { key: "nav.groups.overview", items: [{ id: "dashboard", to: `${OP}/dashboard`, icon: LayoutDashboard, permission: "platform.view", keywords: "home overview kpi" }] },
  {
    key: "nav.groups.customers",
    items: [
      { id: "subscribers", to: `${OP}/subscribers`, icon: Users, permission: "platform.view", match: (p) => startsWith(`${OP}/subscribers`)(p) || startsWith(`${OP}/businesses`)(p), keywords: "businesses customers" },
      { id: "licences", to: `${OP}/licences`, icon: KeyRound, permission: "platform.view", keywords: "licence key self-hosted" },
      { id: "requests", to: `${OP}/billing/requests`, icon: Inbox, permission: "platform.view", keywords: "plan change upgrade downgrade" },
    ],
  },
  {
    key: "nav.groups.revenue",
    items: [
      { id: "plans", to: `${OP}/plans`, icon: Tag, permission: "platform.view", match: (p) => p === `${OP}/plans` || (startsWith(`${OP}/plans`)(p) && !p.startsWith(`${OP}/plans/coupons`)), keywords: "pricing prices add-ons addons" },
      { id: "coupons", to: `${OP}/plans/coupons`, icon: Ticket, permission: "platform.view", match: startsWith(`${OP}/plans/coupons`), keywords: "discount promo code" },
      { id: "invoices", to: `${OP}/billing/invoices`, icon: Receipt, permission: "platform.view", match: (p) => p === `${OP}/billing` || startsWith(`${OP}/billing/invoices`)(p), keywords: "billing payments dunning" },
      { id: "methods", to: `${OP}/payment-methods`, icon: CreditCard, permission: "platform.view", keywords: "gateway mobile money card bank provider" },
      { id: "billingSettings", to: `${OP}/billing/settings`, icon: SlidersHorizontal, permission: "platform.view", keywords: "tax vendor dunning proration invoice details" },
    ],
  },
  {
    key: "nav.groups.website",
    items: [
      { id: "siteCompany", to: `${OP}/website`, icon: Building2, permission: "platform.content", feature: "website", match: websiteTab("company", "social", "seo"), keywords: "contact social seo marketing site" },
      { id: "sitePages", to: `${OP}/website?tab=pages`, icon: FileText, permission: "platform.content", feature: "website", match: websiteTab("pages", "banner", "pricing"), keywords: "terms privacy legal banner" },
      { id: "siteMedia", to: `${OP}/website?tab=media`, icon: Image, permission: "platform.content", feature: "website", match: websiteTab("media"), keywords: "logo pictures images" },
      { id: "sitePublish", to: `${OP}/website?tab=publish`, icon: UploadCloud, permission: "platform.content", feature: "website", match: websiteTab("publish"), keywords: "go live publish" },
    ],
  },
  {
    key: "nav.groups.platform",
    items: [
      { id: "units", to: `${OP}/units`, icon: Boxes, permission: "platform.view", keywords: "modules plugins install upgrade" },
      { id: "ai", to: `${OP}/ai`, icon: Brain, permission: "platform.ai", keywords: "api keys models spend cap provider" },
      { id: "email", to: `${OP}/email`, icon: Mail, permission: "platform.settings", keywords: "smtp sender test message" },
      { id: "settings", to: `${OP}/settings`, icon: Settings, permission: "platform.settings", keywords: "registration mode invite open closed addresses links" },
      { id: "operators", to: `${OP}/operators`, icon: ShieldCheck, permission: "platform.operators", keywords: "staff roles second factor" },
    ],
  },
  {
    key: "nav.groups.system",
    items: [
      { id: "health", to: `${OP}/health`, icon: Activity, permission: "platform.view", keywords: "queues jobs worker status ready" },
      { id: "backups", to: `${OP}/backups`, icon: DatabaseBackup, permission: "platform.view", keywords: "migrations behind upgrade all restore" },
      { id: "audit", to: `${OP}/audit`, icon: ScrollText, permission: "platform.operators", keywords: "operator actions log history who did" },
      { id: "mailLog", to: `${OP}/mail-log`, icon: MailOpen, permission: "platform.settings", keywords: "sent emails failed" },
      { id: "attempts", to: `${OP}/payment-attempts`, icon: Wallet, permission: "platform.view", keywords: "payments failed mismatch stuck" },
    ],
  },
];

/** Other places that are reachable but are not in the sidebar. */
export const EXTRA_PAGES: { id: string; to: string; icon: LucideIcon; permission: string; keywords?: string }[] = [
  { id: "setup", to: `${OP}/setup`, icon: Globe, permission: "platform.view", keywords: "where do i find checklist first run getting started" },
];

/** The groups with only the items this operator may open; empty groups disappear. */
export function visibleNav(groups: NavGroup[], permissions: readonly string[], missingFeatures: readonly string[] = []): NavGroup[] {
  return groups
    .map((g) => ({ ...g, items: g.items.filter((i) => permissions.includes(i.permission) && !(i.feature && missingFeatures.includes(i.feature))) }))
    .filter((g) => g.items.length > 0);
}

const pathOf = (to: string) => to.split("?")[0] as string;

/** Whether an item is the open screen at this address. */
export function isActive(item: NavItem, pathname: string, search: string): boolean {
  const params = new URLSearchParams(search);
  return item.match ? item.match(pathname, params) : startsWith(pathOf(item.to))(pathname);
}

/** The group and item that the address belongs to, if any (the first item that matches, most specific path first). */
export function findCurrent(groups: NavGroup[], pathname: string, search: string): { group: NavGroup; item: NavItem } | null {
  const hits = groups.flatMap((group) => group.items.filter((item) => isActive(item, pathname, search)).map((item) => ({ group, item })));
  hits.sort((a, b) => pathOf(b.item.to).length - pathOf(a.item.to).length);
  return hits[0] ?? null;
}

/** Breadcrumb parts for an address: the group, the screen, and a last part when the address goes deeper (a subscriber's code, "new"). */
export function crumbParts(groups: NavGroup[], pathname: string, search: string): { groupKey: string | null; itemId: string | null; itemTo: string | null; rest: string | null } {
  const current = findCurrent(groups, pathname, search);
  if (!current) return { groupKey: null, itemId: null, itemTo: null, rest: null };
  const base = pathOf(current.item.to);
  const tail = pathname.startsWith(`${base}/`) ? pathname.slice(base.length + 1) : "";
  const rest = tail ? decodeURIComponent(tail.split("/").filter(Boolean).pop() ?? "") : null;
  return { groupKey: current.group.key, itemId: current.item.id, itemTo: current.item.to, rest: rest || null };
}
