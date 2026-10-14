import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "intel",
  routes: [
    { path: "/findings", page: () => import("./pages/FindingsPage"), permission: "findings.view" },
    { path: "/findings/checks", page: () => import("./pages/ChecksPage"), permission: "findings.manage" },
    { path: "/findings/:findingId", page: () => import("./pages/FindingPage"), permission: "findings.view" },
  ],
  menu: [
    { label: "intel:menu", to: "/findings", permission: "findings.view", order: 2, icon: "spark" },
    { label: "intel:checksMenu", to: "/findings/checks", permission: "findings.manage", order: 3, group: "admin", icon: "settings" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "intel:findingsWidget", component: () => import("./slots/FindingsWidget"), permission: "findings.view", order: 2 },
    ],
  },
  translations: { en, sw },
});
