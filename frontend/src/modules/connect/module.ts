import { COMMAND_PANELS } from "@/modules/command/public";
import { FINDINGS_BANNER } from "@/modules/intel/public";
import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import enMove from "./i18n/en.move.json";
import sw from "./i18n/sw.json";
import swMove from "./i18n/sw.move.json";

export default defineModule({
  unit: "connect",
  routes: [
    { path: "/connect", page: () => import("./pages/ConnectionsPage"), permission: "connect.view" },
    { path: "/connect/new", page: () => import("./pages/AddConnectionPage"), permission: "connect.manage" },
    { path: "/connect/connections/:connectionId", page: () => import("./pages/ConnectionPage"), permission: "connect.view" },
    { path: "/connect/connections/:connectionId/move", page: () => import("./pages/MovePage"), permission: "connect.manage" },
  ],
  menu: [{ label: "connect:menu", to: "/connect", permission: "connect.view", order: 20, area: "connect", icon: "spark" }],
  slots: {
    "dashboard.widgets": [{ label: "connect:widgetTitle", component: () => import("./slots/ConnectWidget"), permission: "connect.view", order: 0 }],
    [COMMAND_PANELS]: [
      { label: "connect:overlap.title", component: () => import("./slots/OverlapSlot"), permission: "connect.view", order: 5 },
      { label: "connect:coverage.title", component: () => import("./slots/CoverageSlot"), permission: "connect.view", order: 15 },
    ],
    "admin.apps.notices": [{ label: "connect:move.suggest.title", component: () => import("./slots/MoveNotice"), permission: "connect.manage", order: 0 }],
    [FINDINGS_BANNER]: [{ label: "connect:overlap.title", component: () => import("./slots/OverlapSlot"), permission: "connect.view", order: 0 }],
  },
  translations: { en: { ...en, ...enMove }, sw: { ...sw, ...swMove } },
});
