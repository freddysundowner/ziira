import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "command",
  routes: [
    { path: "/command", page: () => import("./pages/CommandPage"), permission: "command.view" },
    { path: "/command/briefs", page: () => import("./pages/BriefsPage"), permission: "command.view" },
  ],
  menu: [
    { label: "command:menu", tab: "nav.tabs.overview", to: "/command", permission: "command.view", order: 1, area: "command", icon: "dashboard" },
    { label: "command:briefsTitle", to: "/command/briefs", permission: "command.view", order: 30, area: "command", icon: "document" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "command:todayWidget", component: () => import("./slots/TodayWidget"), permission: "command.view", order: 1 },
    ],
  },
  translations: { en, sw },
});
