import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

const VIEW = "purchasing.view";

export default defineModule({
  unit: "purchasing",
  requires: ["products"],
  routes: [
    { path: "/suppliers", page: () => import("./pages/SuppliersPage"), permission: VIEW },
    { path: "/suppliers/:supplierId", page: () => import("./pages/SupplierPage"), permission: VIEW },
    { path: "/requests", page: () => import("./pages/RequestsPage"), permission: VIEW },
    { path: "/requests/:requestId", page: () => import("./pages/RequestPage"), permission: VIEW },
    { path: "/orders", page: () => import("./pages/OrdersPage"), permission: VIEW },
    { path: "/orders/new", page: () => import("./pages/OrderFormPage"), permission: "po.create" },
    { path: "/orders/:orderId", page: () => import("./pages/OrderPage"), permission: VIEW },
    { path: "/orders/:orderId/edit", page: () => import("./pages/OrderFormPage"), permission: "po.create" },
    { path: "/receipts", page: () => import("./pages/ReceiptsPage"), permission: VIEW },
    { path: "/receipts/new", page: () => import("./pages/ReceiptFormPage"), permission: "goods.receive" },
    { path: "/receipts/:receiptId", page: () => import("./pages/ReceiptPage"), permission: VIEW },
    { path: "/bills", page: () => import("./pages/BillsPage"), permission: VIEW },
    { path: "/bills/new", page: () => import("./pages/BillFormPage"), permission: "bills.manage" },
    { path: "/bills/:billId", page: () => import("./pages/BillPage"), permission: VIEW },
    { path: "/bills/:billId/edit", page: () => import("./pages/BillFormPage"), permission: "bills.manage" },
    { path: "/pay-suppliers", page: () => import("./pages/PayPage"), permission: "bills.pay" },
    { path: "/returns", page: () => import("./pages/ReturnsPage"), permission: VIEW },
    { path: "/returns/:returnId", page: () => import("./pages/ReturnPage"), permission: VIEW },
    { path: "/credit-notes", page: () => import("./pages/CreditNotesPage"), permission: VIEW },
    { path: "/credit-notes/:noteId", page: () => import("./pages/CreditNotePage"), permission: VIEW },
    { path: "/refunds", page: () => import("./pages/RefundsPage"), permission: VIEW },
    { path: "/payables", page: () => import("./pages/PayablesPage"), permission: VIEW },
  ],
  menu: [
    { label: "purchasing:suppliers", to: "/suppliers", permission: VIEW, order: 10, area: "buy", icon: "suppliers" },
    { label: "purchasing:orders", to: "/orders", permission: VIEW, order: 20, area: "buy", icon: "purchases" },
    { label: "purchasing:requests", to: "/requests", permission: VIEW, order: 21, area: "buy", under: "/orders", icon: "purchases" },
    { label: "purchasing:receipts", to: "/receipts", permission: VIEW, order: 30, area: "buy", icon: "boxes" },
    { label: "purchasing:bills", to: "/bills", permission: VIEW, order: 40, area: "buy", icon: "receipt" },
    { label: "purchasing:paySuppliers", to: "/pay-suppliers", permission: "bills.pay", order: 41, area: "buy", under: "/bills", icon: "payments" },
    { label: "purchasing:payables", to: "/payables", permission: VIEW, order: 42, area: "buy", under: "/bills", icon: "reports" },
    { label: "purchasing:returns", tab: "purchasing:returnsCredits", to: "/returns", permission: VIEW, order: 50, area: "buy", icon: "purchases" },
    { label: "purchasing:creditNotes", to: "/credit-notes", permission: VIEW, order: 51, area: "buy", under: "/returns", icon: "document" },
    { label: "purchasing:refunds", to: "/refunds", permission: VIEW, order: 52, area: "buy", under: "/returns", icon: "cash" },
  ],
  slots: {
    "dashboard.widgets": [{ label: "purchasing:billsDue", component: () => import("./slots/BillsDueWidget"), permission: VIEW, order: 20 }],
  },
  translations: { en, sw },
});
