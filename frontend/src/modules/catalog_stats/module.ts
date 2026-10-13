/**
 * Example plugin: shows how a unit adds to screens it does not own, through slots.
 * - a box on the home page ("dashboard.widgets", offered by the shell)
 * - a tab on every product page ("products.product.tabs", offered by Products)
 * Products does not import this plugin; it appears only for businesses that enabled it.
 */
import { defineModule } from "@/sdk";
import { PRODUCT_TABS } from "@/modules/products/public";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "catalog_stats",
  requires: ["products"],
  slots: {
    "dashboard.widgets": [
      { label: "catalog_stats:widgetTitle", component: () => import("./slots/ProductCountWidget"), permission: "catalog_stats.view" },
    ],
    [PRODUCT_TABS]: [
      { label: "catalog_stats:tabTitle", component: () => import("./slots/CatalogTab"), permission: "catalog_stats.view", order: 50 },
    ],
  },
  translations: { en, sw },
});
