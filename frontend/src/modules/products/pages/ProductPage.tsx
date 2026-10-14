import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  api, Badge, Card, DetailList, ErrorState, PageHeader, Skeleton, SlotContent, StatusBadge, Tabs, unwrap, useQuery, useSlot, useTranslation,
} from "@/sdk";

import { PRODUCT_TABS } from "../public";
import { PricesTab } from "./PricesTab";

/** A product's page. Other modules add tabs through the "products.product.tabs" slot. */
export default function ProductPage() {
  const { t } = useTranslation("products");
  const { productId = "" } = useParams();
  const slotTabs = useSlot(PRODUCT_TABS);
  const [tab, setTab] = useState("details");
  const product = useQuery({ queryKey: ["product", productId], queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: productId } } })) });
  const uoms = useQuery({ queryKey: ["uoms"], queryFn: () => unwrap(api.GET("/api/v1/products/uoms")) });
  const taxes = useQuery({ queryKey: ["tax-codes"], queryFn: () => unwrap(api.GET("/api/v1/products/tax-codes")) });
  const p = product.data;

  if (product.error) return <ErrorState title={t("notFoundTitle")} message={product.error.message} onRetry={() => void product.refetch()} />;
  if (!p) return <Skeleton className="h-40 w-full" />;
  const uom = uoms.data?.find((u) => u.id === p.base_uom_id);
  const tax = taxes.data?.find((x) => x.id === p.tax_code_id);
  const tabs = [
    { id: "details", label: t("details") },
    { id: "prices", label: t("prices") },
    ...slotTabs.map((c, i) => ({ id: `slot-${i}`, label: c.label ? t(c.label) : c.unit })),
  ];
  const slot = tab.startsWith("slot-") ? slotTabs[Number(tab.slice(5))] : undefined;

  return (
    <>
      <PageHeader back={{ to: "/products", label: t("back") }} title={p.name}
        description={<span className="flex items-center gap-2"><span className="font-mono">{p.sku}</span><StatusBadge status={p.is_active ? "active" : "inactive"} /></span>} />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "details" && (
        <Card>
          <DetailList items={[
            { label: t("type"), value: <Badge>{t(`types.${p.product_type}`)}</Badge> },
            { label: t("unit"), value: uom ? `${uom.code} · ${uom.name}` : "—" },
            { label: t("taxCode"), value: tax ? `${tax.code} · ${tax.name} (${Number(tax.vat_rate)}%)` : "—" },
            { label: t("reorderLevel"), value: p.reorder_level ?? "—" },
            { label: t("batchTracked"), value: p.is_batch_tracked ? t("yes") : t("no") },
          ]} />
        </Card>
      )}
      {tab === "prices" && <PricesTab productId={p.id} />}
      {slot && <Card><SlotContent contribution={slot} props={{ productId: p.id, companyId: p.company_id }} /></Card>}
    </>
  );
}
