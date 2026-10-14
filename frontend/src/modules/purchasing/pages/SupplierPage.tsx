import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, Button, Card, DetailList, ErrorState, PageHeader, Skeleton, Tabs, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { SupplierBankTab } from "../components/SupplierBankTab";
import { SupplierPricesTab } from "../components/SupplierPricesTab";
import { SupplierReconcileTab } from "../components/SupplierReconcileTab";
import { SupplierStatementTab } from "../components/SupplierStatementTab";
import { BillsList } from "../components/BillsList";
import { OrdersList } from "../components/OrdersList";
import { Status } from "../components/Status";
import { SupplierDrawer } from "../components/SupplierDrawer";

const TABS = ["overview", "statement", "bills", "orders", "bank", "prices", "reconcile"] as const;
type Tab = (typeof TABS)[number];

export default function SupplierPage() {
  const { t } = useTranslation("purchasing");
  const { supplierId = "" } = useParams();
  const canManage = useCan("suppliers.manage");
  const canOrder = useCan("po.create");
  const canBill = useCan("bills.manage");
  const [tab, setTab] = useState<Tab>("overview");
  const [editing, setEditing] = useState(false);
  const supplier = useQuery({ queryKey: ["purchasing", "supplier", supplierId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/suppliers/{supplier_id}", { params: { path: { supplier_id: supplierId } } })) });
  const s = supplier.data;

  if (supplier.error) return <ErrorState title={t("supplierNotFound")} message={supplier.error.message} onRetry={() => void supplier.refetch()} />;
  if (!s) return <Skeleton className="h-40 w-full" />;
  return (
    <>
      <PageHeader back={{ to: "/suppliers", label: t("allSuppliers") }} title={s.name}
        description={<span className="flex items-center gap-2"><span className="font-mono">{s.code}</span><Status status={s.status} /></span>}
        actions={<>
          {canManage && <Button variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" />{t("edit")}</Button>}
          {canBill && <Link to={`/bills/new?supplier=${s.id}`}><Button variant="secondary">{t("newBill")}</Button></Link>}
          {canOrder && <Link to={`/orders/new?supplier=${s.id}`}><Button><Plus className="h-4 w-4" />{t("newOrder")}</Button></Link>}
        </>} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`supplierTabs.${id}`) }))} value={tab} onChange={setTab} />
      {tab === "overview" && (
        <Card>
          <DetailList items={[
            { label: t("phone"), value: s.phone },
            { label: t("email"), value: s.email },
            { label: t("taxId"), value: s.tax_id },
            { label: t("terms"), value: t("days", { count: s.payment_terms_days }) },
          ]} />
        </Card>
      )}
      {tab === "statement" && <SupplierStatementTab supplierId={s.id} companyId={s.company_id} />}
      {tab === "bills" && <BillsList supplierId={s.id} />}
      {tab === "orders" && <OrdersList supplierId={s.id} />}
      {tab === "bank" && <SupplierBankTab supplierId={s.id} />}
      {tab === "prices" && <SupplierPricesTab supplierId={s.id} companyId={s.company_id} />}
      {tab === "reconcile" && <SupplierReconcileTab supplierId={s.id} companyId={s.company_id} />}
      {editing && <SupplierDrawer supplier={s} onClose={() => setEditing(false)} />}
    </>
  );
}
