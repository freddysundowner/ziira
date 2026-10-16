import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "crm",
  routes: [
    { path: "/customers", page: () => import("./pages/CustomersPage"), permission: "customers.view" },
    { path: "/customers/:customerId", page: () => import("./pages/CustomerPage"), permission: "customers.view" },
    { path: "/leads", page: () => import("./pages/LeadsPage"), permission: "leads.manage" },
    { path: "/receivables", page: () => import("./pages/ReceivablesPage"), permission: "receivables.view" },
  ],
  menu: [
    { label: "crm:menu", to: "/customers", permission: "customers.view", order: 10, area: "customers", icon: "customers" },
    { label: "crm:leads", to: "/leads", permission: "leads.manage", order: 20, area: "customers", icon: "spark" },
    { label: "crm:receivables", to: "/receivables", permission: "receivables.view", order: 30, area: "customers", icon: "receipt" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "crm:receivablesWidget", component: () => import("./slots/ReceivablesWidget"), permission: "receivables.view", order: 20 },
    ],
  },
  translations: { en, sw },
});
