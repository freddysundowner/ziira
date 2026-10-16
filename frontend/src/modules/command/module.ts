import { TODAY_PANELS } from "@/modules/intel/public";
import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "command",
  routes: [
    { path: "/intelligence/summary", page: () => import("./pages/BriefsPage"), permission: "command.view" },
    // Earlier addresses of the Command Center: old links and bookmarks still arrive.
    { path: "/command", page: () => import("./pages/Redirects").then((m) => ({ default: m.ToToday })), permission: "command.view", tab: "/intelligence/summary" },
    { path: "/command/briefs", page: () => import("./pages/Redirects").then((m) => ({ default: m.ToSummary })), permission: "command.view", tab: "/intelligence/summary" },
  ],
  menu: [
    { label: "command:briefsTitle", to: "/intelligence/summary", permission: "command.view", order: 30, area: "command", icon: "document", keywords: "command:keywords" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "command:todayWidget", component: () => import("./slots/TodayWidget"), permission: "command.view", order: 1 },
    ],
    [TODAY_PANELS]: [
      { label: "command:figuresTitle", component: () => import("./slots/TodayFigures"), permission: "command.view", order: 50 },
    ],
  },
  translations: { en, sw },
});
