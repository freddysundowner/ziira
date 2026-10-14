import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";
import { terminalMenu, terminalRoutes, terminalTranslations } from "./terminal";

export default defineModule({
  unit: "pos",
  routes: [
    ...terminalRoutes,
    { path: "/pos/sales", page: () => import("./pages/SalesPage"), permission: "till.review" },
    { path: "/pos/sales/:saleId", page: () => import("./pages/SalePage"), permission: "till.review" },
    { path: "/pos/returns", page: () => import("./pages/ReturnsPage"), permission: "till.review" },
    { path: "/pos/tills", page: () => import("./pages/TillsPage"), permission: "till.review" },
    { path: "/pos/tills/:tillId", page: () => import("./pages/TillPage"), permission: "till.review" },
    { path: "/pos/devices", page: () => import("./pages/DevicesPage"), permission: "devices.manage" },
    { path: "/pos/settings", page: () => import("./pages/SettingsPage"), permission: "settings.manage" },
  ],
  menu: [
    ...terminalMenu,
    { label: "pos:sales", to: "/pos/sales", permission: "till.review", order: 21, group: "sell", icon: "sales" },
    { label: "pos:returns", to: "/pos/returns", permission: "till.review", order: 22, group: "sell", icon: "receipt" },
    { label: "pos:tills", to: "/pos/tills", permission: "till.review", order: 23, group: "sell", icon: "cash" },
    { label: "pos:devices", to: "/pos/devices", permission: "devices.manage", order: 24, group: "sell", icon: "payments" },
    { label: "pos:settingsMenu", to: "/pos/settings", permission: "settings.manage", order: 25, group: "sell", icon: "settings" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "pos:todaySales", component: () => import("./slots/TodaySalesWidget"), permission: "till.review", order: 10 },
      { label: "pos:openTills", component: () => import("./slots/OpenTillsWidget"), permission: "till.review", order: 11 },
    ],
  },
  translations: { en: { ...en, terminal: terminalTranslations.en }, sw: { ...sw, terminal: terminalTranslations.sw } },
});
