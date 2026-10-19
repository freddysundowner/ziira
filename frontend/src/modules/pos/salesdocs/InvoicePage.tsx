import { Ban, HandCoins, Printer, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, DataTable, DetailList, ErrorState, formatDate, PageHeader, quantity, Skeleton, today, toast, unwrap, useCan, useMutation, useQuery,
  useQueryClient, useTranslation,
} from "@/sdk";
import { ReceivePayment } from "@/modules/crm/public";

import { useBranches, useMoney } from "../hooks";
import { DocStatus } from "./DocStatus";
import { CustomerName, ProductName, useCustomer } from "./hooks";
import { InvoiceReturn } from "./InvoiceReturn";
import { invoiceActions, invoiceDisplayStatus, outstanding } from "./lib";
import { PrintDocument } from "./PrintDocument";
import { ReasonDialog } from "./ReasonDialog";

/** One invoice: lines, what is paid and owed, and the next step (take payment, print, take goods back, cancel). */
export default function InvoicePage() {
  const { t } = useTranslation("pos");
  const { invoiceId = "" } = useParams();
  const qc = useQueryClient();
  const m = useMoney();
  const { nameOf } = useBranches();
  const canManage = useCan("invoices.manage");
  const canRefund = useCan("sales.refund");
  const canReceive = useCan("receivables.manage");
  const [printing, setPrinting] = useState(false);
  const [returning, setReturning] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [paying, setPaying] = useState(false);

  const invoice = useQuery({ queryKey: ["pos-invoice", invoiceId], queryFn: () => unwrap(api.GET("/api/v1/pos/invoices/{invoice_id}", { params: { path: { invoice_id: invoiceId } } })) });
  const customer = useCustomer(invoice.data?.customer_id);

  const cancel = useMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/api/v1/pos/invoices/{invoice_id}/cancel", { params: { path: { invoice_id: invoiceId } }, body: { reason } })),
    onSuccess: (i) => {
      for (const key of ["pos-invoice", "pos-docs", "customer-balance", "customer-statement", "customer-invoices"]) void qc.invalidateQueries({ queryKey: [key] });
      toast(t("docs.invoiceCancelled", { number: i.number }), "ok");
      setCancelling(false);
    },
    onError: () => setCancelling(false),
  });

  if (invoice.error) return <ErrorState title={t("docs.notFound")} message={invoice.error.message} onRetry={() => void invoice.refetch()} />;
  const i = invoice.data;
  if (!i) return <Skeleton className="h-64 w-full" />;
  const can = invoiceActions(i);
  const shown = invoiceDisplayStatus(i, today());
  const owed = outstanding(i);

  return (
    <>
      <PageHeader back={{ to: "/pos/invoices", label: t("docs.tabs.invoices") }} title={i.number}
        description={<span className="flex flex-wrap items-center gap-2"><DocStatus status={shown} /><span>{formatDate(i.issue_date)}</span></span>}
        actions={(
          <>
            <Button variant="secondary" onClick={() => setPrinting(true)}><Printer className="h-4 w-4" />{t("print")}</Button>
            {can.receive && canReceive && customer.data && <Button onClick={() => setPaying(true)}><HandCoins className="h-4 w-4" />{t("docs.receivePayment")}</Button>}
            {can.giveBack && canRefund && <Button variant="secondary" onClick={() => setReturning(true)}><Undo2 className="h-4 w-4" />{t("returnGoods")}</Button>}
            {can.cancel && canManage && <Button variant="danger" onClick={() => setCancelling(true)}><Ban className="h-4 w-4" />{t("docs.cancelInvoice")}</Button>}
          </>
        )} />
      {i.status === "cancelled" && <Alert tone="bad" className="mb-4">{t("docs.cancelledNote", { reason: i.cancel_reason ?? "—" })}</Alert>}
      {shown === "overdue" && <Alert tone="bad" className="mb-4">{t("docs.overdueNote", { date: formatDate(i.due_date) })}</Alert>}
      {i.kind === "credit_sale" && <Alert tone="info" className="mb-4">{t("docs.creditSaleNote")}</Alert>}
      {i.kind === "opening_balance" && <Alert tone="info" className="mb-4">{t("docs.openingNote")}</Alert>}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <Card title={t("items")} flush>
            <DataTable rows={i.lines} rowKey={(l) => l.id} empty={{ title: t("docs.noInvoiceLines") }}
              columns={[
                { header: t("item"), cell: (l) => <ProductName id={l.product_id} /> },
                { header: t("qty"), align: "right", cell: (l) => quantity(l.quantity) },
                { header: t("unitPrice"), hideBelow: "sm", align: "right", cell: (l) => m(l.unit_price, i.company_id) },
                { header: t("discount"), hideBelow: "md", align: "right", cell: (l) => (Number(l.discount_amount) ? m(l.discount_amount, i.company_id) : "—") },
                { header: t("tax"), hideBelow: "md", align: "right", cell: (l) => m(l.tax_amount, i.company_id) },
                { header: t("lineTotal"), align: "right", cell: (l) => <span className="font-medium">{m(l.line_total, i.company_id)}</span> },
              ]} />
          </Card>
        </div>
        <div className="min-w-0 space-y-4">
          <Card title={t("totals")}>
            <dl className="space-y-1.5 text-sm">
              <Row label={t("subtotal")} value={m(i.subtotal, i.company_id)} />
              <Row label={t("tax")} value={m(i.tax_total, i.company_id)} />
              <Row label={t("total")} value={m(i.total, i.company_id)} strong divider />
              <Row label={t("docs.paid")} value={m(i.amount_paid, i.company_id)} />
              {Number(i.credited) > 0 && <Row label={t("docs.credited")} value={m(i.credited, i.company_id)} />}
              <Row label={t("docs.owed")} value={m(owed, i.company_id)} strong divider />
            </dl>
          </Card>
          <Card title={t("details")}>
            <DetailList items={[
              { label: t("docs.customer"), value: <CustomerName id={i.customer_id} link /> },
              { label: t("branch"), value: nameOf(i.branch_id) },
              { label: t("docs.issued"), value: formatDate(i.issue_date) },
              { label: t("docs.dueDate"), value: formatDate(i.due_date) },
              ...(i.sales_order_id ? [{ label: t("docs.fromOrder"), value: <Link className="text-brand-strong hover:underline" to={`/pos/orders/${i.sales_order_id}`}>{t("docs.viewOrder")}</Link> }] : []),
              ...(i.sale_id ? [{ label: t("sale"), value: <Link className="text-brand-strong hover:underline" to={`/pos/sales/${i.sale_id}`}>{t("viewSale")}</Link> }] : []),
              { label: t("note"), value: i.notes ?? "—" },
            ]} />
          </Card>
        </div>
      </div>

      <PrintDocument kind="invoice" id={i.id} companyId={i.company_id} open={printing} onClose={() => setPrinting(false)} />
      <InvoiceReturn invoice={i} open={returning} onClose={() => setReturning(false)} />
      <ReasonDialog open={cancelling} onClose={() => setCancelling(false)} busy={cancel.isPending} title={t("docs.cancelInvoiceTitle", { number: i.number })}
        message={t("docs.cancelInvoiceAsk")} confirmLabel={t("docs.cancelInvoice")} onConfirm={(reason) => cancel.mutate(reason)} />
      {customer.data && <ReceivePayment open={paying} onClose={() => { setPaying(false); void qc.invalidateQueries({ queryKey: ["pos-invoice"] }); void qc.invalidateQueries({ queryKey: ["pos-docs"] }); }}
        customer={customer.data} invoice={{ id: i.id, number: i.number, outstanding: owed }} />}
    </>
  );
}

function Row({ label, value, strong, divider }: { label: string; value: string; strong?: boolean; divider?: boolean }) {
  return <div className={`flex justify-between gap-3 ${strong ? "text-base font-semibold" : ""} ${divider ? "border-t border-line pt-1.5" : ""}`}><dt className={`min-w-0 [overflow-wrap:anywhere] ${strong ? "" : "text-muted"}`}>{label}</dt><dd className="tnum min-w-0 text-right [overflow-wrap:anywhere]">{value}</dd></div>;
}
