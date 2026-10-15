import { Ban, CheckCircle2, Pencil, Send, Truck } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, ConfirmDialog, DataTable, DetailList, ErrorState, formatDate, PageHeader, quantity, Schemas, Skeleton, toast, unwrap, useCan,
  useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { useBranches, useMoney } from "../hooks";
import { DeliverOrder } from "./DeliverOrder";
import { DocStatus } from "./DocStatus";
import { CustomerName, ProductName } from "./hooks";
import { orderActions, quotationActions } from "./lib";

type Doc = Schemas["DocOut"];
const BASE = { quotation: "/pos/quotations", order: "/pos/orders" } as const;
type Act = "send" | "accept" | "submit" | "cancel";

/** One quotation or sales order: its lines and totals, and the next step for its status (send, accept, submit, deliver, cancel). */
export function DocPage({ kind }: { kind: "quotation" | "order" }) {
  const { t } = useTranslation("pos");
  const { documentId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const canManage = useCan("invoices.manage");
  const m = useMoney();
  const { nameOf } = useBranches();
  const [asking, setAsking] = useState<Act | null>(null);
  const [delivering, setDelivering] = useState(false);

  const doc = useQuery({
    queryKey: ["pos-doc", kind, documentId],
    queryFn: () => unwrap(kind === "quotation"
      ? api.GET("/api/v1/pos/quotations/{document_id}", { params: { path: { document_id: documentId } } })
      : api.GET("/api/v1/pos/orders/{document_id}", { params: { path: { document_id: documentId } } })),
  });

  const run = useMutation({
    mutationFn: (act: Act): Promise<Doc> => {
      const path = { path: { document_id: documentId } };
      if (kind === "quotation") {
        if (act === "send") return unwrap(api.POST("/api/v1/pos/quotations/{document_id}/send", { params: path }));
        if (act === "accept") return unwrap(api.POST("/api/v1/pos/quotations/{document_id}/accept", { params: path }));
        return unwrap(api.POST("/api/v1/pos/quotations/{document_id}/cancel", { params: path }));
      }
      if (act === "submit") return unwrap(api.POST("/api/v1/pos/orders/{document_id}/submit", { params: path }));
      return unwrap(api.POST("/api/v1/pos/orders/{document_id}/cancel", { params: path }));
    },
    onSuccess: (result, act) => {
      void qc.invalidateQueries({ queryKey: ["pos-docs"] });
      void qc.invalidateQueries({ queryKey: ["pos-doc"] });
      setAsking(null);
      if (act === "accept") { toast(t("docs.accepted", { order: result.number }), "ok"); navigate(`/pos/orders/${result.id}`); return; }
      toast(act === "submit" && result.status === "pending_approval" ? t("docs.waitsApproval", { number: result.number }) : t(`docs.done.${act}`, { number: result.number }), "ok");
    },
    onError: () => setAsking(null),
  });

  if (doc.error) return <ErrorState title={t("docs.notFound")} message={doc.error.message} onRetry={() => void doc.refetch()} />;
  const d = doc.data;
  if (!d) return <Skeleton className="h-64 w-full" />;
  const can = kind === "quotation" ? quotationActions(d.status) : orderActions(d);
  const base = BASE[kind];

  return (
    <>
      <PageHeader back={{ to: base, label: t(`docs.tabs.${kind}s`) }} title={d.number}
        description={<span className="flex flex-wrap items-center gap-2"><DocStatus status={d.status} /><span>{formatDate(d.doc_date)}</span></span>}
        actions={canManage && (
          <>
            {can.edit && <Link to={`${base}/${d.id}/edit`}><Button variant="secondary"><Pencil className="h-4 w-4" />{t("docs.edit.button")}</Button></Link>}
            {can.send && <Button variant="secondary" onClick={() => setAsking("send")}><Send className="h-4 w-4" />{t("docs.send")}</Button>}
            {can.accept && <Button onClick={() => setAsking("accept")}><CheckCircle2 className="h-4 w-4" />{t("docs.accept")}</Button>}
            {can.submit && <Button onClick={() => setAsking("submit")}><CheckCircle2 className="h-4 w-4" />{t("docs.submit")}</Button>}
            {can.deliver && <Button onClick={() => setDelivering(true)}><Truck className="h-4 w-4" />{t("docs.deliver")}</Button>}
            {can.cancel && <Button variant="danger" onClick={() => setAsking("cancel")}><Ban className="h-4 w-4" />{t("docs.cancelDoc")}</Button>}
          </>
        )} />
      {d.status === "pending_approval" && <Alert tone="warn" className="mb-4">{t("docs.pendingApprovalNote")}</Alert>}
      {d.status === "expired" && <Alert tone="warn" className="mb-4">{t("docs.expiredNote")}</Alert>}
      {d.status === "draft" && <Alert tone="info" className="mb-4">{t(`docs.draftNote.${kind}`)}</Alert>}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title={t("items")} flush>
            <DataTable rows={d.lines} rowKey={(l) => l.id} empty={{ title: t("noItems") }}
              columns={[
                { header: t("item"), cell: (l) => <ProductName id={l.product_id} /> },
                { header: t("qty"), align: "right", cell: (l) => quantity(l.quantity) },
                ...(kind === "order" ? [{ header: t("docs.delivered"), align: "right" as const, hideBelow: "sm" as const, cell: (l: Doc["lines"][number]) => quantity(l.qty_delivered) }] : []),
                { header: t("unitPrice"), hideBelow: "sm", align: "right", cell: (l) => m(l.unit_price, d.company_id) },
                { header: t("discount"), hideBelow: "md", align: "right", cell: (l) => (Number(l.discount_amount) ? m(l.discount_amount, d.company_id) : "—") },
                { header: t("tax"), hideBelow: "md", align: "right", cell: (l) => m(l.tax_amount, d.company_id) },
                { header: t("lineTotal"), align: "right", cell: (l) => <span className="font-medium">{m(l.line_total, d.company_id)}</span> },
              ]} />
          </Card>
          {kind === "order" && d.status !== "draft" && <DeliveredInvoices order={d} />}
        </div>
        <div className="space-y-4">
          <Card title={t("totals")}>
            <dl className="space-y-1.5 text-sm">
              <Row label={t("subtotal")} value={m(d.subtotal, d.company_id)} />
              <Row label={t("tax")} value={m(d.tax_total, d.company_id)} />
              <Row label={t("total")} value={m(d.total, d.company_id)} strong divider />
            </dl>
          </Card>
          <Card title={t("details")}>
            <DetailList items={[
              { label: t("docs.customer"), value: <CustomerName id={d.customer_id} link /> },
              { label: t("branch"), value: nameOf(d.branch_id) },
              ...(kind === "quotation" ? [{ label: t("docs.validUntil"), value: d.valid_until ? formatDate(d.valid_until) : "—" }] : []),
              { label: t("docs.termsDays"), value: t("docs.days", { count: d.terms_days }) },
              ...(kind === "order" && d.source_quotation_id ? [{ label: t("docs.fromQuotation"), value: <Link className="text-brand-strong hover:underline" to={`/pos/quotations/${d.source_quotation_id}`}>{t("docs.viewQuotation")}</Link> }] : []),
              ...(kind === "quotation" && d.status === "confirmed" ? [{ label: t("docs.becameOrder"), value: <OrderOf quotation={d} /> }] : []),
              { label: t("note"), value: d.notes ?? "—" },
            ]} />
          </Card>
        </div>
      </div>

      <ConfirmDialog open={asking !== null} onClose={() => setAsking(null)} busy={run.isPending} danger={asking === "cancel"}
        title={asking ? t(`docs.ask.${asking}.title`, { number: d.number }) : ""} confirmLabel={asking ? t(`docs.ask.${asking}.button`) : ""}
        message={asking ? t(`docs.ask.${asking}.${kind}`, { number: d.number }) : ""} onConfirm={() => asking && run.mutate(asking)} />
      {kind === "order" && <DeliverOrder order={d} open={delivering} onClose={() => setDelivering(false)} />}
    </>
  );
}

function Row({ label, value, strong, divider }: { label: string; value: string; strong?: boolean; divider?: boolean }) {
  return <div className={`flex justify-between gap-3 ${strong ? "text-base font-semibold" : ""} ${divider ? "border-t border-line pt-1.5" : ""}`}><dt className={strong ? "" : "text-muted"}>{label}</dt><dd className="tnum">{value}</dd></div>;
}

/** The order an accepted quotation turned into (found among the customer's orders). */
function OrderOf({ quotation }: { quotation: Doc }) {
  const { t } = useTranslation("pos");
  const orders = useQuery({
    retry: false, queryKey: ["pos-doc-orders-of", quotation.customer_id],
    queryFn: () => unwrap(api.GET("/api/v1/pos/orders", { params: { query: { customer_id: quotation.customer_id, limit: 200 } } })),
  });
  const order = orders.data?.find((o) => o.source_quotation_id === quotation.id);
  return order ? <Link className="text-brand-strong hover:underline" to={`/pos/orders/${order.id}`}>{order.number}</Link> : <Link className="text-brand-strong hover:underline" to="/pos/orders">{t("docs.tabs.orders")}</Link>;
}

/** The invoices made by delivering this order. */
function DeliveredInvoices({ order }: { order: Doc }) {
  const { t } = useTranslation("pos");
  const m = useMoney();
  const invoices = useQuery({
    retry: false, queryKey: ["pos-docs", "order-invoices", order.id, order.lines.map((l) => l.qty_delivered).join()],
    queryFn: () => unwrap(api.GET("/api/v1/pos/invoices", { params: { query: { customer_id: order.customer_id ?? undefined, limit: 200 } } })),
  });
  const mine = invoices.data?.filter((i) => i.sales_order_id === order.id) ?? [];
  if (invoices.isLoading || (invoices.data && mine.length === 0)) return null;
  return (
    <Card title={t("docs.deliveries")} flush>
      <DataTable rows={mine} loading={invoices.isLoading} error={invoices.error?.message} onRetry={() => void invoices.refetch()} rowKey={(i) => i.id} rowHref={(i) => `/pos/invoices/${i.id}`}
        empty={{ title: t("docs.noDeliveries") }}
        columns={[
          { header: t("number"), cell: (i) => <span className="font-mono text-xs font-medium">{i.number}</span> },
          { header: t("docs.issued"), hideBelow: "sm", cell: (i) => formatDate(i.issue_date) },
          { header: t("total"), align: "right", cell: (i) => m(i.total, i.company_id) },
          { header: t("status"), cell: (i) => <DocStatus status={i.status} /> },
        ]} />
    </Card>
  );
}
