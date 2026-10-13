import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "products",
  routes: [
    { path: "/products", page: () => import("./pages/ProductsPage"), permission: "products.view" },
    { path: "/products/:productId", page: () => import("./pages/ProductPage"), permission: "products.view" },
  ],
  menu: [{ label: "products:menu", to: "/products", permission: "products.view", order: 10 }],
  translations: { en, sw },
});
