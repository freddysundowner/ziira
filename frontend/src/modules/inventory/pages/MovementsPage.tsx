import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Badge, DataTable, formatDate, humanise, money, PageHeader, Pager, quantity, unwrap, useCan, useCompany, useCurrency, usePagedList, useTranslation } from "@/sdk";

import { LocationSelect } from "../components/LocationSelect";
import { ProductName, ProductPicker, useLocations } from "../lookups";

const SOURCE_PATH: Record<string, string> = { stock_adjustment: "/stock/adjustments", transfer: "/stock/transfers", stock_count: "/stock/counts" };

/** The stock ledger, newest first. Costs and values show only to users who may see them. */
export default function MovementsPage() {
  const { t } = useTranslation("inventory");
  const canCost = useCan("stock.cost");
  const currency = useCurrency(useCompany().company?.id);
  const locations = useLocations();
  const [locationId, setLocationId] = useState("");
  const [product, setProduct] = useState({ id: "", name: "" });
  const list = usePagedList(["inv-movements", locationId, product.id], (limit, offset) =>
    unwrap(api.GET("/api/v1/inventory/movements", { params: { query: { location_id: locationId || undefined, product_id: product.id || undefined, limit, offset } } })));
  const code = (id: string) => locations.data?.find((l) => l.id === id)?.code ?? id.slice(0, 8);

  return (
    <>
      <PageHeader title={t("movements")} description={t("movementsHint")} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(m) => m.id}
        toolbar={
          <>
            <div className="w-56"><ProductPicker clearable value={product.id} label={product.name} placeholder={t("allProducts")} onChange={(id, name) => setProduct({ id, name })} /></div>
            <div className="w-52"><LocationSelect label={t("location")} value={locationId} onChange={setLocationId} allLabel={t("allLocations")} /></div>
          </>
        }
        empty={{ title: t("noMovements"), hint: t("noMovementsHint") }}
        columns={[
          { header: t("date"), cell: (m) => formatDate(m.business_date) },
          { header: t("product"), cell: (m) => <ProductName id={m.product_id} /> },
          { header: t("location"), hideBelow: "md", cell: (m) => code(m.location_id) },
          { header: t("type"), hideBelow: "sm", cell: (m) => <Badge>{t(`movementTypes.${m.movement_type}`, humanise(m.movement_type))}</Badge> },
          { header: t("quantity"), align: "right", cell: (m) => <span className={Number(m.quantity) < 0 ? "font-medium text-bad" : "font-medium text-ok"}>{Number(m.quantity) > 0 ? "+" : ""}{quantity(m.quantity)}</span> },
          ...(canCost ? [
            { header: t("unitCost"), align: "right" as const, hideBelow: "lg" as const, cell: (m: { unit_cost: string | null }) => money(m.unit_cost, currency) },
            { header: t("value"), align: "right" as const, hideBelow: "lg" as const, cell: (m: { value: string | null }) => money(m.value, currency) },
          ] : []),
          {
            header: t("source"), hideBelow: "lg", cell: (m) => {
              const base = SOURCE_PATH[m.source_type];
              const label = t(`sources.${m.source_type}`, humanise(m.source_type));
              return base ? <Link className="text-brand hover:underline" to={`${base}/${m.source_id}`}>{label}</Link> : label;
            },
          },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
    </>
  );
}
