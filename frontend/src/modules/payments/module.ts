import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "payments",
  routes: [
    { path: "/payments", page: () => import("./pages/PaymentsPage"), permission: "payments.view" },
    { path: "/payments/requests", page: () => import("./pages/RequestsPage"), permission: "payments.view" },
    { path: "/payments/reconciliation", page: () => import("./pages/ReconciliationPage"), permission: "payments.view" },
    { path: "/payments/closes", page: () => import("./pages/ClosesPage"), permission: "payments.view" },
    { path: "/payments/accounts", page: () => import("./pages/AccountsPage"), permission: "payments.view" },
  ],
  menu: [
    { label: "payments:menu", to: "/payments", permission: "payments.view", order: 30, group: "money", icon: "payments" },
    { label: "payments:requests", to: "/payments/requests", permission: "payments.view", order: 31, group: "money", icon: "cash" },
    { label: "payments:reconciliation", to: "/payments/reconciliation", permission: "payments.view", order: 32, group: "money", icon: "ledger" },
    { label: "payments:closes", to: "/payments/closes", permission: "payments.view", order: 33, group: "money", icon: "document" },
    { label: "payments:accounts", to: "/payments/accounts", permission: "payments.view", order: 34, group: "money", icon: "settings" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "payments:todayWidget", component: () => import("./slots/PaymentsTodayWidget"), permission: "payments.view", order: 30 },
    ],
  },
  translations: { en, sw },
});
