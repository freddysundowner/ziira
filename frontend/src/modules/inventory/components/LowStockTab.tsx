import { Link } from "react-router-dom";

import { Alert, DataTable, quantity, useTranslation } from "@/sdk";

import { useLowStock } from "../useLowStock";

/** Products at or under their reorder level, counting stock in every location. */
export function LowStockTab() {
  const { t } = useTranslation("inventory");
  const low = useLowStock();
  return (
    <div className="space-y-3">
      <Alert>{t("lowStockHint")} <Link className="underline" to="/products">{t("setLevelsLink")}</Link></Alert>
      <DataTable
        rows={low.rows} loading={low.loading} error={low.error} onRetry={low.retry} rowKey={(r) => r.product.id} rowHref={(r) => `/products/${r.product.id}`}
        searchText={(r) => `${r.product.name} ${r.product.sku}`} searchPlaceholder={t("searchProduct")} pageSize={25}
        empty={{ title: t("allGood"), hint: t("allGoodHint") }}
        columns={[
          { header: t("product"), sortValue: (r) => r.product.name, cell: (r) => <span><span className="font-medium">{r.product.name}</span> <span className="font-mono text-xs text-muted">{r.product.sku}</span></span> },
          { header: t("reorderLevel"), align: "right", hideBelow: "sm", cell: (r) => quantity(r.reorderLevel) },
          { header: t("onHand"), align: "right", sortValue: (r) => Number(r.onHand), cell: (r) => <span className={Number(r.onHand) <= 0 ? "font-medium text-bad" : "font-medium text-warn"}>{quantity(r.onHand)}</span> },
          { header: t("short"), align: "right", sortValue: (r) => Number(r.short), cell: (r) => quantity(r.short) },
        ]}
      />
    </div>
  );
}
