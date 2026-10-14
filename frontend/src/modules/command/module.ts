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
    { label: "command:menu", to: "/command", permission: "command.view", order: 1, icon: "dashboard" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "command:todayWidget", component: () => import("./slots/TodayWidget"), permission: "command.view", order: 1 },
    ],
  },
  translations: { en, sw },
});
