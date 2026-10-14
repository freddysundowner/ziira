import { defineModule } from "@/sdk";
import { PRODUCT_TABS } from "@/modules/products/public";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "inventory",
  requires: ["products"],
  routes: [
    { path: "/stock", page: () => import("./pages/StockPage"), permission: "stock.view" },
    { path: "/stock/movements", page: () => import("./pages/MovementsPage"), permission: "stock.view" },
    { path: "/stock/opening", page: () => import("./pages/OpeningStockPage"), permission: "stock.adjust" },
    { path: "/stock/adjustments", page: () => import("./pages/AdjustmentsPage"), permission: "stock.view" },
    { path: "/stock/adjustments/:adjustmentId", page: () => import("./pages/AdjustmentPage"), permission: "stock.view" },
    { path: "/stock/transfers", page: () => import("./pages/TransfersPage"), permission: "stock.view" },
    { path: "/stock/transfers/:transferId", page: () => import("./pages/TransferPage"), permission: "stock.view" },
    { path: "/stock/counts", page: () => import("./pages/CountsPage"), permission: "stock.view" },
    { path: "/stock/counts/:countId", page: () => import("./pages/CountPage"), permission: "stock.view" },
    { path: "/stock/locations", page: () => import("./pages/LocationsPage"), permission: "stock.view" },
  ],
  menu: [
    { label: "inventory:stock", to: "/stock", permission: "stock.view", order: 20, group: "stock", icon: "stock" },
    { label: "inventory:movements", to: "/stock/movements", permission: "stock.view", order: 21, group: "stock", icon: "ledger" },
    { label: "inventory:adjustments", to: "/stock/adjustments", permission: "stock.view", order: 22, group: "stock", icon: "document" },
    { label: "inventory:transfers", to: "/stock/transfers", permission: "stock.view", order: 23, group: "stock", icon: "suppliers" },
    { label: "inventory:counts", to: "/stock/counts", permission: "stock.view", order: 24, group: "stock", icon: "purchases" },
    { label: "inventory:locations", to: "/stock/locations", permission: "stock.view", order: 25, group: "stock", icon: "company" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "inventory:lowStockTitle", component: () => import("./slots/LowStockWidget"), permission: "stock.view", order: 20 },
    ],
    [PRODUCT_TABS]: [
      { label: "inventory:stock", component: () => import("./slots/StockTab"), permission: "stock.view", order: 10 },
    ],
  },
  translations: { en, sw },
});
