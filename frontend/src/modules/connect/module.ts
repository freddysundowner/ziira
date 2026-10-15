import { COMMAND_PANELS } from "@/modules/command/public";
import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "connect",
  routes: [
    { path: "/connect", page: () => import("./pages/ConnectionsPage"), permission: "connect.view" },
    { path: "/connect/new", page: () => import("./pages/AddConnectionPage"), permission: "connect.manage" },
    { path: "/connect/connections/:connectionId", page: () => import("./pages/ConnectionPage"), permission: "connect.view" },
  ],
  menu: [{ label: "connect:menu", to: "/connect", permission: "connect.view", order: 20, group: "admin", icon: "dashboard" }],
  slots: {
    "dashboard.widgets": [{ label: "connect:widgetTitle", component: () => import("./slots/ConnectWidget"), permission: "connect.view", order: 0 }],
    [COMMAND_PANELS]: [{ label: "connect:coverage.title", component: () => import("./slots/CoverageSlot"), permission: "connect.view", order: 15 }],
  },
  translations: { en, sw },
});
