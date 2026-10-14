import { Printer, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  api, Button, Card, DataTable, DetailList, ErrorState, formatDate, PageHeader, quantity, Skeleton, unwrap, useCan, useQuery, useTranslation,
} from "@/sdk";

import { Money } from "../components/Money";
import { ProductName, SupplierName } from "../components/names";
import { ReturnDrawer } from "../components/ReturnDrawer";
import { Status } from "../components/Status";

export default function ReceiptPage() {
  const { t } = useTranslation("purchasing");
  const { receiptId = "" } = useParams();
  const canReturn = useCan("goods.return");
  const canBill = useCan("bills.manage");
  const [returning, setReturning] = useState(false);
  const receipt = useQuery({ queryKey: ["purchasing", "receipt", receiptId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/receipts/{receipt_id}", { params: { path: { receipt_id: receiptId } } })) });
  const r = receipt.data;
  const returns = useQuery({
    enabled: !!r, queryKey: ["purchasing", "returns", { receipt: receiptId }],
    queryFn: async () => (await unwrap(api.GET("/api/v1/purchasing/returns", { params: { query: { supplier_id: r?.supplier_id, limit: 200 } } }))).filter((x) => x.receipt_id === receiptId),
  });

  if (receipt.error) return <ErrorState title={t("receiptNotFound")} message={receipt.error.message} onRetry={() => void receipt.refetch()} />;
  if (!r) return <Skeleton className="h-40 w-full" />;
  return (
    <>
      <PageHeader back={{ to: "/receipts", label: t("receipts") }} title={t("receiptTitle", { number: r.number })}
        description={<span className="flex items-center gap-2"><Status status={r.status} /><SupplierName id={r.supplier_id} link /></span>}
        actions={<>
          <Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />{t("print")}</Button>
          {canReturn && <Button variant="secondary" onClick={() => setReturning(true)}><Undo2 className="h-4 w-4" />{t("returnGoods")}</Button>}
          {canBill && <Link to={`/bills/new?supplier=${r.supplier_id}&receipt=${r.id}`}><Button>{t("enterBill")}</Button></Link>}
        </>} />
      <div className="space-y-4">
        <Card>
          <DetailList items={[
            { label: t("supplier"), value: <SupplierName id={r.supplier_id} link /> },
            { label: t("receivedOn"), value: formatDate(r.received_at, true) },
            { label: t("deliveryNote"), value: r.delivery_note_no },
            { label: t("order"), value: r.order_id ? <Link className="font-medium text-brand hover:underline" to={`/orders/${r.order_id}`}>{t("openOrder")}</Link> : t("noOrder") },
            { label: t("landedCost"), value: <Money value={r.landed_cost} companyId={r.company_id} /> },
          ]} />
        </Card>
        <Card title={t("goodsReceived")} flush>
          <DataTable rows={r.lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
            columns={[
              { header: t("product"), cell: (l) => <ProductName id={l.product_id} /> },
              { header: t("batchNo"), hideBelow: "sm", cell: (l) => l.batch_no ?? "—" },
              { header: t("expiry"), hideBelow: "md", cell: (l) => formatDate(l.expiry_date) },
              { header: t("quantityReceived"), align: "right", cell: (l) => quantity(l.quantity) },
              { header: t("unitCost"), align: "right", cell: (l) => <Money value={l.unit_cost} companyId={r.company_id} /> },
            ]} />
        </Card>
        <Card title={t("returns")} flush>
          <DataTable rows={returns.data} loading={returns.isLoading} error={returns.error?.message} onRetry={() => void returns.refetch()} rowKey={(x) => x.id} rowHref={(x) => `/returns/${x.id}`}
            empty={{ title: t("noReturnsForReceipt") }}
            columns={[
              { header: t("number"), cell: (x) => <span className="font-mono text-xs font-medium">{x.number}</span> },
              { header: t("date"), cell: (x) => formatDate(x.returned_at, true) },
              { header: t("note"), hideBelow: "sm", cell: (x) => x.note ?? "—" },
            ]} />
        </Card>
      </div>
      {returning && <ReturnDrawer receipt={r} onClose={() => setReturning(false)} />}
    </>
  );
}
