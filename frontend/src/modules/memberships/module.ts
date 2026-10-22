import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import enGym from "./i18n/en.gym.json";
import sw from "./i18n/sw.json";
import swGym from "./i18n/sw.gym.json";

export default defineModule({
  unit: "memberships",
  requires: ["crm"],
  routes: [
    { path: "/memberships", page: () => import("./pages/MembersPage"), permission: "memberships.view" },
    { path: "/memberships/plans", page: () => import("./pages/CataloguePage"), permission: "memberships.view" },
    { path: "/memberships/recurring", page: () => import("./pages/RecurringPage"), permission: "memberships.view" },
    { path: "/memberships/checkin", page: () => import("./pages/CheckinPage"), permission: "memberships.checkin" },
    { path: "/memberships/kiosk", page: () => import("./pages/KioskPage"), permission: "memberships.checkin", tab: "/memberships/checkin" },
    { path: "/memberships/arrears", page: () => import("./pages/ArrearsPage"), permission: "memberships.view" },
    { path: "/memberships/reports", page: () => import("./pages/ReportsPage"), permission: "memberships.reports" },
    { path: "/memberships/extras", page: () => import("./pages/ExtrasPage"), permission: "memberships.view" },
    { path: "/memberships/people/:customerId", page: () => import("./pages/PersonPage"), permission: "memberships.view", tab: "/memberships" },
    { path: "/memberships/:memberId", page: () => import("./pages/MemberPage"), permission: "memberships.view", tab: "/memberships" },
  ],
  menu: [
    { label: "memberships:menu", to: "/memberships", permission: "memberships.view", order: 50, area: "services", icon: "customers", keywords: "memberships:keywords" },
    { label: "memberships:catalogueMenu", to: "/memberships/plans", under: "/memberships", permission: "memberships.view", order: 52, area: "services", icon: "boxes", keywords: "memberships:catalogueKeywords" },
    { label: "memberships:recurringMenu", to: "/memberships/recurring", under: "/memberships", permission: "memberships.view", order: 54, area: "services", icon: "receipt", keywords: "memberships:recurringKeywords" },
    { label: "memberships:checkinMenu", to: "/memberships/checkin", under: "/memberships", permission: "memberships.checkin", order: 51, area: "services", icon: "customers", keywords: "memberships:checkinKeywords" },
    { label: "memberships:arrearsMenu", to: "/memberships/arrears", under: "/memberships", permission: "memberships.view", order: 53, area: "services", icon: "cash", keywords: "memberships:arrearsKeywords" },
    { label: "memberships:reportsMenu", to: "/memberships/reports", under: "/memberships", permission: "memberships.reports", order: 55, area: "services", icon: "reports", keywords: "memberships:reportsKeywords" },
    { label: "memberships:extrasMenu", to: "/memberships/extras", under: "/memberships", permission: "memberships.view", order: 56, area: "services", icon: "boxes", keywords: "memberships:extrasKeywords" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "memberships:widget.checkinsTitle", component: () => import("./slots/CheckinsTodayWidget"), permission: "memberships.view", order: 36 },
      { label: "memberships:widget.expiringTitle", component: () => import("./slots/ExpiringWidget"), permission: "memberships.view", order: 36.1 },
      { label: "memberships:widget.lateTitle", component: () => import("./slots/PaymentsLateWidget"), permission: "memberships.view", order: 36.2 },
    ],
    "crm.customer.tabs": [
      { label: "memberships:customerTab", component: () => import("./slots/CustomerMembership"), permission: "memberships.view", order: 40 },
    ],
  },
  translations: { en: { ...en, ...enGym }, sw: { ...sw, ...swGym } },
});
