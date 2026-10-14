import { api, Card, DataTable, formatDate, humanise, money, Pager, unwrap, useCurrency, usePagedList, useTranslation } from "@/sdk";

import { ProductName } from "./names";

/** What this supplier has charged for each product over time, newest first. */
export function SupplierPricesTab({ supplierId, companyId }: { supplierId: string; companyId: string }) {
  const { t } = useTranslation("purchasing");
  const currency = useCurrency(companyId);
  const list = usePagedList(["purchasing", "supplier-prices", supplierId], (limit, offset) =>
    unwrap(api.GET("/api/v1/purchasing/suppliers/{supplier_id}/prices", { params: { path: { supplier_id: supplierId }, query: { limit, offset } } })));
  return (
    <Card title={t("priceHistory")} description={t("priceHistoryHint")} flush>
      <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(p) => `${p.product_id}${p.effective_date}${p.unit_cost}`} empty={{ title: t("noPrices"), hint: t("noPricesHint") }}
        columns={[
          { header: t("product"), cell: (p) => <ProductName id={p.product_id} /> },
          { header: t("unitCost"), align: "right", cell: (p) => money(p.unit_cost, currency) },
          { header: t("date"), cell: (p) => formatDate(p.effective_date) },
          { header: t("source"), hideBelow: "sm", cell: (p) => humanise(p.source_type) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
    </Card>
  );
}
