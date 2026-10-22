import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

const VIEW = "claims.view";

export default defineModule({
  unit: "claims",
  requires: [],
  routes: [
    { path: "/claims", page: () => import("./pages/ClaimsPage"), permission: VIEW },
    { path: "/claims/payers", page: () => import("./pages/PayersPage"), permission: VIEW },
    { path: "/claims/ageing", page: () => import("./pages/AgeingPage"), permission: VIEW },
    { path: "/claims/:claimId", page: () => import("./pages/ClaimPage"), permission: VIEW },
  ],
  menu: [
    { label: "claims:menu.claims", to: "/claims", permission: VIEW, order: 40, area: "services", icon: "purchases", keywords: "claims:keywords.claims" },
    { label: "claims:menu.payers", to: "/claims/payers", under: "/claims", permission: VIEW, order: 41, area: "services", icon: "customers", keywords: "claims:keywords.payers" },
    { label: "claims:menu.ageing", to: "/claims/ageing", under: "/claims", permission: VIEW, order: 42, area: "services", icon: "finance", keywords: "claims:keywords.ageing" },
  ],
  slots: {
    "dashboard.widgets": [{ label: "claims:widget.title", component: () => import("./slots/ClaimsWaitingWidget"), permission: VIEW, order: 32 }],
  },
  translations: { en, sw },
});
