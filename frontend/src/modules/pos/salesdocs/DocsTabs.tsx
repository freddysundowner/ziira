import { useLocation, useNavigate } from "react-router-dom";

import { Tabs, useTranslation } from "@/sdk";

const TABS = [
  { id: "quotations", path: "/pos/quotations" },
  { id: "orders", path: "/pos/orders" },
  { id: "invoices", path: "/pos/invoices" },
  { id: "receipts", path: "/pos/receipts" },
  { id: "refunds", path: "/pos/refunds" },
] as const;

/** The sales documents as one family: the same tab bar on each list, so the menu holds a single entry for all five. */
export function DocsTabs() {
  const { t } = useTranslation("pos");
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const active = TABS.find((x) => pathname.startsWith(x.path))?.id ?? "invoices";
  return <Tabs value={active} onChange={(id) => navigate(TABS.find((x) => x.id === id)?.path ?? "/pos/invoices")}
    tabs={TABS.map((x) => ({ id: x.id, label: t(`docs.tabs.${x.id}`) }))} />;
}
