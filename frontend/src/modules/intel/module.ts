import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import enPlain from "./i18n/en.plain.json";
import sw from "./i18n/sw.json";
import swPlain from "./i18n/sw.plain.json";

export default defineModule({
  unit: "intel",
  routes: [
    { path: "/intelligence", page: () => import("./pages/TodayPage"), permission: "findings.view" },
    { path: "/intelligence/things", page: () => import("./pages/ThingsPage"), permission: "findings.view" },
    { path: "/intelligence/things/:findingId", page: () => import("./pages/ThingPage"), permission: "findings.view" },
    { path: "/intelligence/suggestions", page: () => import("./pages/ActionsPage"), permission: "findings.view" },
    { path: "/intelligence/setup", page: () => import("./pages/QuickStartPage"), permission: "findings.manage", tab: "/intelligence/watching" },
    { path: "/intelligence/watching", page: () => import("./pages/WatchingPage"), permission: "findings.manage" },
    { path: "/intelligence/how-much", page: () => import("./pages/HowMuchPage"), permission: "findings.view" },
    { path: "/intelligence/alerts", page: () => import("./pages/AlertsPage"), permission: "findings.view" },
    // Earlier addresses: old links and bookmarks still arrive.
    { path: "/findings", page: () => import("./pages/Redirects").then((m) => ({ default: m.ToThings })), permission: "findings.view" },
    { path: "/findings/actions", page: () => import("./pages/Redirects").then((m) => ({ default: m.ToSuggestions })), permission: "findings.view" },
    { path: "/findings/checks", page: () => import("./pages/Redirects").then((m) => ({ default: m.ToWatching })), permission: "findings.manage" },
    { path: "/findings/:findingId", page: () => import("./pages/Redirects").then((m) => ({ default: m.ToThing })), permission: "findings.view" },
  ],
  menu: [
    { label: "intel:today.menu", to: "/intelligence", permission: "findings.view", order: 1, area: "command", icon: "dashboard", keywords: "intel:keywords.today" },
    { label: "intel:things.menu", to: "/intelligence/things", permission: "findings.view", order: 10, area: "command", icon: "spark", keywords: "intel:keywords.things" },
    { label: "intel:suggestions.menu", to: "/intelligence/suggestions", permission: "findings.view", order: 20, area: "command", icon: "document", when: "intel.suggestions", keywords: "intel:keywords.suggestions" },
    { label: "intel:watch.menu", to: "/intelligence/watching", permission: "findings.manage", order: 30, area: "settings", section: "intelligence", icon: "settings", keywords: "intel:keywords.watching" },
    { label: "intel:how.menu", to: "/intelligence/how-much", permission: "findings.view", order: 31, area: "settings", section: "intelligence", icon: "settings", keywords: "intel:keywords.how" },
    { label: "intel:alerts.menu", to: "/intelligence/alerts", permission: "findings.view", order: 32, area: "settings", section: "intelligence", icon: "settings", keywords: "intel:keywords.alerts" },
    { label: "intel:quick.menu", to: "/intelligence/setup", permission: "findings.manage", order: 33, hidden: true, icon: "spark", keywords: "intel:keywords.setup" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "intel:findingsWidget", component: () => import("./slots/FindingsWidget"), permission: "findings.view", order: 2 },
    ],
    "shell.background": [
      { component: () => import("./slots/NavFlags"), permission: "findings.view" },
    ],
  },
  translations: { en: { ...en, ...enPlain }, sw: { ...sw, ...swPlain } },
});
