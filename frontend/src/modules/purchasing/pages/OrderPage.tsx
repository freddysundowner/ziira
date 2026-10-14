import { Pencil, PackageCheck, Printer, Send } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, ConfirmDialog, DataTable, DetailList, ErrorState, formatDate, Menu, PageHeader, quantity, Skeleton, toast, unwrap, useCan, useCurrency,
  useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { ApprovalBar } from "../components/ApprovalBar";
import { Money } from "../components/Money";
import { ProductName, SupplierName } from "../components/names";
import { Status } from "../components/Status";
import { Totals } from "../components/Totals";
import { canReceive } from "../lib";

type Action = "submit" | "send" | "cancel" | "close";

export default function OrderPage() {
  const { t } = useTranslation("purchasing");
  const { orderId = "" } = useParams();
  const qc = useQueryClient();
  const canOrder = useCan("po.create");
  const canReceiveGoods = useCan("goods.receive");
  const canBill = useCan("bills.manage");
  const [confirm, setConfirm] = useState<Action | null>(null);
  const order = useQuery({ queryKey: ["purchasing", "order", orderId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/orders/{order_id}", { params: { path: { order_id: orderId } } })) });
  const receipts = useQuery({ queryKey: ["purchasing", "receipts", { order: orderId }], queryFn: () => unwrap(api.GET("/api/v1/purchasing/receipts", { params: { query: { order_id: orderId, limit: 50 } } })) });
  const o = order.data;
  const currency = useCurrency(o?.company_id);

  const act = useMutation({
    mutationFn: (action: Action) => {
      const params = { params: { path: { order_id: orderId } } };
      switch (action) {
        case "submit": return unwrap(api.POST("/api/v1/purchasing/orders/{order_id}/submit", params));
        case "send": return unwrap(api.POST("/api/v1/purchasing/orders/{order_id}/send", params));
        case "cancel": return unwrap(api.POST("/api/v1/purchasing/orders/{order_id}/cancel", params));
        case "close": return unwrap(api.POST("/api/v1/purchasing/orders/{order_id}/close", params));
      }
    },
    onSuccess: (_, action) => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t(`orderDone.${action}`), "ok"); setConfirm(null); },
    onError: () => setConfirm(null),
  });

  if (order.error) return <ErrorState title={t("orderNotFound")} message={order.error.message} onRetry={() => void order.refetch()} />;
  if (!o) return <Skeleton className="h-40 w-full" />;
  const cancellable = ["draft", "pending_approval", "approved", "sent"].includes(o.status);

  return (
    <>
      <PageHeader back={{ to: "/orders", label: t("orders") }} title={t("orderTitle", { number: o.number })}
        description={<span className="flex items-center gap-2"><Status status={o.status} /><SupplierName id={o.supplier_id} link /></span>}
        actions={<>
          {canOrder && o.status === "draft" && <Link to={`/orders/${o.id}/edit`}><Button variant="secondary"><Pencil className="h-4 w-4" />{t("edit")}</Button></Link>}
          {canOrder && o.status === "draft" && <Button loading={act.isPending && act.variables === "submit"} onClick={() => act.mutate("submit")}>{t("submitForApproval")}</Button>}
          {canOrder && o.status === "approved" && <Button loading={act.isPending && act.variables === "send"} onClick={() => act.mutate("send")}><Send className="h-4 w-4" />{t("markSent")}</Button>}
          {canReceiveGoods && canReceive(o) && <Link to={`/receipts/new?order=${o.id}`}><Button><PackageCheck className="h-4 w-4" />{t("receiveGoods")}</Button></Link>}
          {canBill && ["part_received", "received", "closed"].includes(o.status) && <Link to={`/bills/new?supplier=${o.supplier_id}`}><Button variant="secondary">{t("enterBill")}</Button></Link>}
          <Menu label={t("moreActions")} trigger={<span className="inline-flex h-9 items-center rounded-lg border border-line bg-surface px-3 text-sm shadow-card">{t("more")}</span>} items={[
            { label: t("print"), icon: <Printer className="h-4 w-4" />, onSelect: () => window.print() },
            ...(canOrder && o.status === "part_received" ? [{ label: t("closeOrder"), onSelect: () => setConfirm("close") }] : []),
            ...(canOrder && cancellable ? [{ label: t("cancelOrder"), danger: true, onSelect: () => setConfirm("cancel") }] : []),
          ]} />
        </>} />
      <ApprovalBar docType="purchase_order" docId={o.id} waiting={o.status === "pending_approval"} />
      {o.status === "draft" && <Alert tone="info" className="mb-4">{t("draftOrderHint")}</Alert>}
      <div className="space-y-4">
        <Card>
          <DetailList items={[
            { label: t("supplier"), value: <SupplierName id={o.supplier_id} link /> },
            { label: t("orderDate"), value: formatDate(o.order_date) },
            { label: t("expectedDate"), value: formatDate(o.expected_date) },
            { label: t("total"), value: <Money value={o.total} companyId={o.company_id} /> },
          ]} />
        </Card>
        <Card title={t("lines")} flush>
          <DataTable rows={o.lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
            columns={[
              { header: t("product"), cell: (l) => <ProductName id={l.product_id} /> },
              { header: t("ordered"), align: "right", cell: (l) => quantity(l.quantity) },
              { header: t("received"), align: "right", hideBelow: "sm", cell: (l) => quantity(l.qty_received) },
              { header: t("billed"), align: "right", hideBelow: "md", cell: (l) => quantity(l.qty_billed) },
              { header: t("unitCostBeforeTax"), align: "right", cell: (l) => <Money value={l.unit_cost} companyId={o.company_id} /> },
            ]} />
          <div className="border-t border-line p-4"><Totals subtotal={o.subtotal} tax={o.tax_total} total={o.total} currency={currency} /></div>
        </Card>
        <Card title={t("receipts")} flush>
          <DataTable rows={receipts.data} loading={receipts.isLoading} error={receipts.error?.message} onRetry={() => void receipts.refetch()} rowKey={(r) => r.id} rowHref={(r) => `/receipts/${r.id}`}
            empty={{ title: t("noReceiptsForOrder") }}
            columns={[
              { header: t("number"), cell: (r) => <span className="font-mono text-xs font-medium">{r.number}</span> },
              { header: t("receivedOn"), cell: (r) => formatDate(r.received_at, true) },
              { header: t("deliveryNote"), hideBelow: "sm", cell: (r) => r.delivery_note_no ?? "—" },
              { header: t("status"), cell: (r) => <Status status={r.status} /> },
            ]} />
        </Card>
      </div>
      <ConfirmDialog open={confirm !== null} onClose={() => setConfirm(null)} busy={act.isPending} danger={confirm === "cancel"}
        title={confirm ? t(`orderConfirm.${confirm}.title`) : ""} message={confirm ? t(`orderConfirm.${confirm}.message`, { number: o.number }) : ""}
        confirmLabel={confirm ? t(`orderConfirm.${confirm}.button`) : ""} onConfirm={() => confirm && act.mutate(confirm)} />
    </>
  );
}
