import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "finance",
  routes: [
    { path: "/finance/accounts", page: () => import("./pages/AccountsPage"), permission: "reports.view" },
    { path: "/finance/journal", page: () => import("./pages/JournalPage"), permission: "reports.view" },
    { path: "/finance/journal/:entryId", page: () => import("./pages/EntryPage"), permission: "reports.view" },
    { path: "/finance/manual-journals/new", page: () => import("./pages/NewManualJournalPage"), permission: "journal.post_manual" },
    { path: "/finance/manual-journals/:manualId", page: () => import("./pages/ManualJournalPage"), permission: "reports.view" },
    { path: "/finance/reports", page: () => import("./pages/ReportsPage"), permission: "reports.view" },
    { path: "/finance/reports/:report", page: () => import("./pages/ReportsPage"), permission: "reports.view" },
    { path: "/finance/expenses", page: () => import("./pages/ExpensesPage"), permission: "expenses.submit" },
    { path: "/finance/expenses/:expenseId", page: () => import("./pages/ExpensePage"), permission: "expenses.submit" },
    { path: "/finance/bank", page: () => import("./pages/BankPage"), permission: "bank.reconcile" },
    { path: "/finance/bank/:reconId", page: () => import("./pages/ReconciliationPage"), permission: "bank.reconcile" },
    { path: "/finance/setup", page: () => import("./pages/SetupPage"), permission: "reports.view" },
  ],
  menu: [
    { label: "finance:menu.accounts", to: "/finance/accounts", permission: "reports.view", order: 40, group: "money", icon: "finance" },
    { label: "finance:menu.journal", to: "/finance/journal", permission: "reports.view", order: 41, group: "money", icon: "ledger" },
    { label: "finance:menu.reports", to: "/finance/reports", permission: "reports.view", order: 42, group: "money", icon: "reports" },
    { label: "finance:menu.expenses", to: "/finance/expenses", permission: "expenses.submit", order: 43, group: "money", icon: "expenses" },
    { label: "finance:menu.bank", to: "/finance/bank", permission: "bank.reconcile", order: 44, group: "money", icon: "cash" },
    { label: "finance:menu.setup", to: "/finance/setup", permission: "reports.view", order: 45, group: "money", icon: "settings" },
  ],
  slots: {
    "dashboard.widgets": [{ label: "finance:widget.title", component: () => import("./slots/FinanceWidget"), permission: "reports.view", order: 20 }],
  },
  translations: { en, sw },
});
