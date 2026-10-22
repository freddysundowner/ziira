import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

const LOG = "time.log";
const VIEW = "time.view";

export default defineModule({
  unit: "timebilling",
  requires: ["crm"],
  routes: [
    { path: "/time", page: () => import("./pages/MyWeekPage"), permission: LOG },
    { path: "/time/approvals", page: () => import("./pages/ApprovalsPage"), permission: "time.approve" },
    { path: "/projects", page: () => import("./pages/ProjectsPage"), permission: VIEW },
    { path: "/projects/:projectId", page: () => import("./pages/ProjectPage"), permission: VIEW },
    { path: "/time/work", page: () => import("./pages/WorkPage"), permission: VIEW },
    { path: "/time/clients", page: () => import("./pages/ClientsPage"), permission: VIEW },
    { path: "/time/unbilled", page: () => import("./pages/UnbilledPage"), permission: "time.bill" },
    { path: "/time/reviews/:reviewId", page: () => import("./pages/ReviewPage"), permission: "time.bill", tab: "/time/unbilled" },
    { path: "/time/overview", page: () => import("./pages/OverviewPage"), permission: VIEW },
    { path: "/time/rates", page: () => import("./pages/RatesPage"), permission: "rates.manage" },
    { path: "/time/settings", page: () => import("./pages/SettingsPage"), permission: "time.settings" },
  ],
  menu: [
    { label: "timebilling:myWeek.title", to: "/time", permission: LOG, order: 40, area: "services", icon: "calendar", keywords: "timebilling:keywords.myWeek" },
    { label: "timebilling:approvals.title", to: "/time/approvals", under: "/time", permission: "time.approve", order: 41, area: "services", icon: "security", keywords: "timebilling:keywords.approvals" },
    { label: "timebilling:projects.title", to: "/projects", permission: VIEW, order: 42, area: "services", icon: "boxes", keywords: "timebilling:keywords.projects" },
    { label: "timebilling:clients.title", to: "/time/clients", under: "/projects", permission: VIEW, order: 43, area: "services", icon: "customers", keywords: "timebilling:keywords.clients" },
    { label: "timebilling:work.title", to: "/time/work", under: "/projects", permission: VIEW, order: 44, area: "services", icon: "calendar", keywords: "timebilling:keywords.work" },
    { label: "timebilling:unbilled.title", to: "/time/unbilled", permission: "time.bill", order: 44, area: "services", icon: "receipt", keywords: "timebilling:keywords.unbilled" },
    { label: "timebilling:overview.title", to: "/time/overview", under: "/time/unbilled", permission: VIEW, order: 45, area: "services", icon: "reports", keywords: "timebilling:keywords.overview" },
    { label: "timebilling:rates.title", to: "/time/rates", permission: "rates.manage", order: 80, area: "services", icon: "cash", setup: true, keywords: "timebilling:keywords.rates" },
    { label: "timebilling:settings.title", to: "/time/settings", under: "/time/rates", permission: "time.settings", order: 81, area: "services", icon: "settings", setup: true, keywords: "timebilling:keywords.settings" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "timebilling:widget.title", component: () => import("./slots/WorkWidget"), permission: VIEW, order: 35 },
      { label: "timebilling:widget.deadlinesTitle", component: () => import("./slots/DeadlinesWidget"), permission: VIEW, order: 35.1 },
    ],
  },
  translations: { en, sw },
});
