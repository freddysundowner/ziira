import { Link } from "react-router-dom";

import { api, DataTable, ErrorState, money, quantity, type SlotProps, Stat, unwrap, useCurrency, useQuery, useTranslation } from "@/sdk";

/** The "Stock" tab on a product's page. Receives { productId, companyId } from Products. */
export default function StockTab(props: SlotProps) {
  const { t } = useTranslation("inventory");
  const productId = String(props.productId);
  const currency = useCurrency(String(props.companyId));
  const total = useQuery({
    queryKey: ["inv-product-stock", productId],
    queryFn: () => unwrap(api.GET("/api/v1/inventory/products/{product_id}/stock", { params: { path: { product_id: productId } } })),
  });
  const where = useQuery({
    queryKey: ["inv-product-balances", productId],
    queryFn: () => unwrap(api.GET("/api/v1/inventory/balances", { params: { query: { product_id: productId, include_zero: true, limit: 200 } } })),
  });

  if (total.error) return <ErrorState message={total.error.message} onRetry={() => void total.refetch()} />;
  const seesCost = total.data?.value != null;
  return (
    <div className="space-y-4">
      <div className={seesCost ? "grid grid-cols-3 gap-3" : "grid grid-cols-1 gap-3 sm:max-w-xs"}>
        <Stat label={t("onHand")} value={quantity(total.data?.quantity)} loading={total.isLoading} />
        {seesCost && <Stat label={t("averageCost")} value={money(total.data?.average_cost, currency)} />}
        {seesCost && <Stat label={t("stockValue")} value={money(total.data?.value, currency)} />}
      </div>
      <DataTable rows={where.data} loading={where.isLoading} error={where.error?.message} onRetry={() => void where.refetch()}
        rowKey={(b) => `${b.location_id}-${b.batch_id ?? ""}`} empty={{ title: t("noStockOfProduct"), hint: t("noStockOfProductHint") }}
        columns={[
          { header: t("location"), cell: (b) => b.location_code },
          { header: t("batch"), hideBelow: "sm", cell: (b) => (b.batch_id ? <span className="font-mono text-xs">{b.batch_id.slice(0, 8)}</span> : "—") },
          { header: t("quantity"), align: "right", cell: (b) => <span className="font-medium">{quantity(b.quantity)}</span> },
        ]} />
      <p className="text-sm"><Link className="text-brand-strong hover:underline" to="/stock/movements">{t("seeMovements")}</Link></p>
    </div>
  );
}
