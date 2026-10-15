import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "imports",
  routes: [
    { path: "/imports", page: () => import("./pages/ImportsPage"), permission: "imports.manage" },
    { path: "/imports/opening-balances", page: () => import("./pages/OpeningBalancesPage"), permission: "imports.manage" },
    { path: "/imports/new", page: () => import("./pages/ImportWizardPage"), permission: "imports.manage" },
    { path: "/imports/:batchId", page: () => import("./pages/ImportWizardPage"), permission: "imports.manage" },
  ],
  menu: [
    { label: "imports:menu", to: "/imports", permission: "imports.manage", order: 96, group: "admin", icon: "document" },
  ],
  translations: { en, sw },
});
