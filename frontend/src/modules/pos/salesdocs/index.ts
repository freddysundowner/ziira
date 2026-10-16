import type { MenuItem, PageRoute } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

const VIEW = "receivables.view";
const MANAGE = "invoices.manage";

/**
 * Quotations, sales orders, customer invoices, payments received and refunds, plus the offline-sync rejection inbox.
 * Quotations and orders share one sidebar entry, payments received and refunds another (a small tab bar switches between them); invoices stand alone; the POS module adds these to
 * its own and places the translations under the key `docs` of the `pos` namespace.
 */
export const salesDocsRoutes: PageRoute[] = [
  { path: "/pos/quotations", page: () => import("./QuotationsPage"), permission: VIEW },
  { path: "/pos/quotations/new", page: () => import("./QuotationFormPage"), permission: MANAGE },
  { path: "/pos/quotations/:documentId", page: () => import("./QuotationPage"), permission: VIEW },
  { path: "/pos/quotations/:documentId/edit", page: () => import("./QuotationFormPage"), permission: MANAGE },
  { path: "/pos/orders", page: () => import("./OrdersPage"), permission: VIEW },
  { path: "/pos/orders/new", page: () => import("./OrderFormPage"), permission: MANAGE },
  { path: "/pos/orders/:documentId", page: () => import("./OrderPage"), permission: VIEW },
  { path: "/pos/orders/:documentId/edit", page: () => import("./OrderFormPage"), permission: MANAGE },
  { path: "/pos/invoices", page: () => import("./InvoicesPage"), permission: VIEW },
  { path: "/pos/invoices/new", page: () => import("./InvoiceFormPage"), permission: MANAGE },
  { path: "/pos/invoices/:invoiceId", page: () => import("./InvoicePage"), permission: VIEW },
  { path: "/pos/receipts", page: () => import("./ReceiptsPage"), permission: VIEW },
  { path: "/pos/refunds", page: () => import("./RefundsPage"), permission: VIEW },
  { path: "/pos/sync/rejections", page: () => import("./RejectionsPage"), permission: "till.review" },
];

export const salesDocsMenu: MenuItem[] = [
  { label: "pos:docs.tabs.quotations", tab: "pos:docs.tabs.quotesOrders", to: "/pos/quotations", permission: VIEW, order: 20, area: "sell", icon: "document" },
  { label: "pos:docs.tabs.orders", to: "/pos/orders", permission: VIEW, order: 21, area: "sell", under: "/pos/quotations", icon: "document" },
  { label: "pos:docs.tabs.invoices", to: "/pos/invoices", permission: VIEW, order: 30, area: "sell", icon: "document" },
  { label: "pos:docs.tabs.receipts", tab: "pos:docs.tabs.customerPayments", to: "/pos/receipts", permission: VIEW, order: 40, area: "sell", icon: "receipt" },
  { label: "pos:docs.tabs.refunds", to: "/pos/refunds", permission: VIEW, order: 41, area: "sell", under: "/pos/receipts", icon: "cash" },
  { label: "pos:docs.rejections.menu", to: "/pos/sync/rejections", permission: "till.review", order: 82, area: "sell", under: "/pos/tills", icon: "security" },
];

export const salesDocsTranslations: { en: Record<string, unknown>; sw: Record<string, unknown> } = { en, sw };
