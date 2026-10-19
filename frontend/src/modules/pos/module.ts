import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";
import { salesDocsMenu, salesDocsRoutes, salesDocsTranslations } from "./salesdocs";
import { terminalMenu, terminalRoutes, terminalTranslations } from "./terminal";

export default defineModule({
  unit: "pos",
  routes: [
    ...terminalRoutes,
    ...salesDocsRoutes,
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
    { label: "pos:sales", to: "/pos/sales", permission: "till.review", order: 10, area: "sell", icon: "sales" },
    { label: "pos:returns", to: "/pos/returns", permission: "till.review", order: 50, area: "sell", icon: "receipt" },
    { label: "pos:tills", tab: "pos:tillsDevices", to: "/pos/tills", permission: "till.review", order: 80, area: "sell", icon: "cash" },
    { label: "pos:devices", to: "/pos/devices", permission: "devices.manage", order: 81, area: "sell", under: "/pos/tills", icon: "payments" },
    { label: "pos:settingsMenu", to: "/pos/settings", permission: "settings.manage", order: 12, area: "settings", section: "business", under: "/admin/organisation", icon: "settings" },
    ...salesDocsMenu,
  ],
  slots: {
    "dashboard.widgets": [
      { label: "pos:todaySales", component: () => import("./slots/TodaySalesWidget"), permission: "till.review", order: 10 },
      { label: "pos:openTills", component: () => import("./slots/OpenTillsWidget"), permission: "till.review", order: 11 },
    ],
  },
  translations: { en: { ...en, terminal: terminalTranslations.en, docs: salesDocsTranslations.en }, sw: { ...sw, terminal: terminalTranslations.sw, docs: salesDocsTranslations.sw } },
});
