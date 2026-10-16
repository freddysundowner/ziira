import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "finance",
  routes: [
    { path: "/finance/accounts", page: () => import("./pages/AccountsPage"), permission: "reports.view" },
    { path: "/finance/journal", page: () => import("./pages/JournalPage"), permission: "reports.view" },
    { path: "/finance/journal/:entryId", page: () => import("./pages/EntryPage"), permission: "reports.view" },
    { path: "/finance/manual-journals/new", page: () => import("./pages/NewManualJournalPage"), permission: "journal.post_manual", tab: "/finance/journal" },
    { path: "/finance/manual-journals/:manualId", page: () => import("./pages/ManualJournalPage"), permission: "reports.view", tab: "/finance/journal" },
    { path: "/finance/reports", page: () => import("./pages/ReportsPage"), permission: "reports.view" },
    { path: "/finance/reports/:report", page: () => import("./pages/ReportsPage"), permission: "reports.view" },
    { path: "/finance/expenses", page: () => import("./pages/ExpensesPage"), permission: "expenses.submit" },
    { path: "/finance/expenses/:expenseId", page: () => import("./pages/ExpensePage"), permission: "expenses.submit" },
    { path: "/finance/bank", page: () => import("./pages/BankPage"), permission: "bank.reconcile" },
    { path: "/finance/bank/:reconId", page: () => import("./pages/ReconciliationPage"), permission: "bank.reconcile" },
    { path: "/finance/setup", page: () => import("./pages/SetupPage"), permission: "reports.view" },
  ],
  menu: [
    { label: "finance:menu.bank", to: "/finance/bank", permission: "bank.reconcile", order: 20, area: "money", icon: "cash" },
    { label: "finance:menu.expenses", to: "/finance/expenses", permission: "expenses.submit", order: 30, area: "money", icon: "expenses" },
    { label: "finance:menu.reports", to: "/finance/reports", permission: "reports.view", order: 40, area: "money", icon: "reports" },
    { label: "finance:menu.journal", tab: "finance:accountingMenu", to: "/finance/journal", permission: "reports.view", order: 50, area: "money", icon: "ledger" },
    { label: "finance:menu.accounts", to: "/finance/accounts", permission: "reports.view", order: 51, area: "money", under: "/finance/journal", icon: "finance" },
    { label: "finance:menu.setup", to: "/finance/setup", permission: "reports.view", order: 52, area: "money", under: "/finance/journal", icon: "settings" },
  ],
  slots: {
    "dashboard.widgets": [{ label: "finance:widget.title", component: () => import("./slots/FinanceWidget"), permission: "reports.view", order: 20 }],
  },
  translations: { en, sw },
});
