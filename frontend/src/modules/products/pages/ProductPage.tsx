import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, Card, PageHeader, SlotContent, useQuery, useSlot, useTranslation } from "@/sdk";

import { PRODUCT_TABS } from "../public";

/** A product's page. Other modules add tabs through the "products.product.tabs" slot. */
export default function ProductPage() {
  const { t } = useTranslation("products");
  const { productId = "" } = useParams();
  const tabs = useSlot(PRODUCT_TABS);
  const [tab, setTab] = useState(-1); // -1 = Details
  const product = useQuery({
    queryKey: ["product", productId],
    queryFn: async () => (await api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: productId } } })).data,
  });
  const p = product.data;
  if (!p) return null;

  const tabClass = (active: boolean) => `border-b-2 px-3 py-2 text-sm ${active ? "border-brand font-medium" : "border-transparent text-slate-500"}`;
  return (
    <>
      <Link to="/products" className="text-sm text-brand hover:underline">← {t("back")}</Link>
      <PageHeader title={`${p.sku} · ${p.name}`} />
      <nav className="mb-4 flex border-b border-slate-200">
        <button className={tabClass(tab === -1)} onClick={() => setTab(-1)}>{t("details")}</button>
        {tabs.map((c, i) => (
          <button key={`${c.unit}-${i}`} className={tabClass(tab === i)} onClick={() => setTab(i)}>
            {c.label ? t(c.label) : c.unit}
          </button>
        ))}
      </nav>
      {tab === -1 ? (
        <Card>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-slate-500">{t("type")}</dt><dd>{t(`types.${p.product_type}`)}</dd>
            <dt className="text-slate-500">{t("reorderLevel")}</dt><dd>{p.reorder_level ?? "—"}</dd>
          </dl>
        </Card>
      ) : (
        tabs[tab] && <Card><SlotContent contribution={tabs[tab]} props={{ productId: p.id, companyId: p.company_id }} /></Card>
      )}
    </>
  );
}
