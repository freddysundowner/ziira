import { ClipboardList, PackagePlus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, PageHeader, Tabs, useCan, useTranslation } from "@/sdk";

import { LowStockTab } from "../components/LowStockTab";
import { OnHandTab } from "../components/OnHandTab";

type Tab = "onhand" | "low";

/** Stock on hand by product and location, and what is running low. */
export default function StockPage() {
  const { t } = useTranslation("inventory");
  const canAdjust = useCan("stock.adjust");
  const [tab, setTab] = useState<Tab>("onhand");
  return (
    <>
      <PageHeader title={t("stock")} description={t("stockHint")}
        actions={canAdjust && (
          <>
            <Link to="/stock/opening"><Button variant="secondary"><PackagePlus className="h-4 w-4" />{t("openingStock")}</Button></Link>
            <Link to="/stock/adjustments"><Button><ClipboardList className="h-4 w-4" />{t("adjustStock")}</Button></Link>
          </>
        )} />
      <Tabs tabs={[{ id: "onhand" as Tab, label: t("onHand") }, { id: "low" as Tab, label: t("lowStock") }]} value={tab} onChange={setTab} />
      {tab === "onhand" ? <OnHandTab /> : <LowStockTab />}
    </>
  );
}
