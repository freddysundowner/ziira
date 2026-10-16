import { useQuery } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { useState } from "react";

import {
  Alert, Button, type Column, DataTable, DetailList, Drawer, ErrorState, formatDate, money, type Schemas, Skeleton, toast, useTranslation,
} from "@/sdk";

import type { PlatformSchema } from "../../types";
import { opApi, opDownload, opUnwrap } from "../../client";
import { ChangeConfirm } from "../../components/ChangeConfirm";
import { InvoiceBadge } from "../../components/bits";
import { ReasonDialog } from "../../components/ReasonDialog";
import { useOperatorCan } from "../../me";
import { InvoiceAttempts } from "./InvoiceAttempts";
import { invoiceTarget, RecordPaymentDialog, useRefreshOperator } from "./invoiceDialogs";

type Detail = Schemas["InvoiceDetail"];
type Payment = PlatformSchema<"PaymentOut">;

/** Opens the printable page in a new tab. The window is opened first so the browser's pop-up blocker allows it. */
export async function printInvoice(id: string, failed: (message: string) => void): Promise<void> {
  const win = window.open("", "_blank");
  try {
    const blob = await opDownload(`/api/v1/operator/invoices/${id}/html`);
    const url = URL.createObjectURL(blob);
    if (win) win.location.href = url;
    else window.location.assign(url);
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    win?.close();
    failed((error as Error).message);
  }
}

/** One invoice: its lines, tax, payments and what can be done to it. */
export function InvoiceDrawer({ invoiceId, onClose }: { invoiceId: string; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const detail = useQuery({ queryKey: ["operator", "invoice", invoiceId], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/invoices/{invoice_id}", { params: { path: { invoice_id: invoiceId } } })) });
  return (
    <Drawer open onClose={onClose} title={detail.data?.number ?? t("billing.invoice.draftTitle")}>
      {detail.isPending && <div className="space-y-3"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-32 w-full" /></div>}
      {detail.isError && <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} />}
      {detail.data && <InvoiceBody invoice={detail.data} />}
    </Drawer>
  );
}

function InvoiceBody({ invoice: i }: { invoice: Detail }) {
  const { t } = useTranslation("operator");
  const canBill = useOperatorCan("platform.billing");
  const refresh = useRefreshOperator();
  const [dialog, setDialog] = useState<"pay" | "void" | "issue" | null>(null);
  const [reversing, setReversing] = useState<Payment | null>(null);
  const id = i.id;

  const lines = i.lines as { description: string; quantity: string; unit_amount: string; amount: string }[];
  const taxes = i.tax_lines as { name: string; rate_percent: string; amount: string }[];
  const payments: Column<Payment>[] = [
    { header: t("billing.invoice.paidOn"), cell: (p) => <span className="text-sm">{formatDate(p.paid_on)}</span> },
    { header: t("billing.payment.method"), cell: (p) => <div><p className="text-sm">{p.method}</p>{p.reference && <p className="text-xs text-muted">{p.reference}</p>}</div> },
    { header: t("billing.invoice.amount"), align: "right", cell: (p) => <span className={p.reversed_at ? "text-sm text-muted line-through" : "text-sm"}>{money(p.amount, p.currency)}</span> },
    {
      header: "", align: "right",
      cell: (p) => p.reversed_at
        ? <span className="text-xs text-muted">{t("billing.invoice.reversed", { date: formatDate(p.reversed_at) })}</span>
        : canBill ? <Button size="sm" variant="secondary" onClick={() => setReversing(p)}>{t("billing.invoice.reverse")}</Button> : null,
    },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <InvoiceBadge status={i.status} />
        <span className="text-sm text-muted">{invoiceTarget(i)}</span>
        <div className="flex-1" />
        {i.status !== "draft" && <Button size="sm" variant="secondary" onClick={() => void printInvoice(id, (m) => toast(m, "bad"))}><Printer className="h-4 w-4" /> {t("billing.invoice.print")}</Button>}
      </div>
      {i.void_reason && <Alert tone="bad">{t("billing.invoice.voidedBecause", { reason: i.void_reason })}</Alert>}

      <DetailList items={[
        { label: t("billing.invoice.kind"), value: t(`billing.invoice.kinds.${i.kind}`, i.kind) },
        { label: t("billing.invoice.issueDate"), value: i.issue_date ? formatDate(i.issue_date) : "-" },
        { label: t("billing.invoice.dueDate"), value: i.due_date ? formatDate(i.due_date) : "-" },
        { label: t("billing.invoice.period"), value: i.period_start && i.period_end ? `${formatDate(i.period_start)} - ${formatDate(i.period_end)}` : "-" },
      ]} />

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-sm">
          <thead className="bg-sunken/60 text-xs uppercase tracking-wide text-muted">
            <tr><th scope="col" className="px-3 py-2">{t("billing.invoiceForm.description")}</th><th scope="col" className="px-3 py-2 text-right">{t("billing.invoiceForm.quantity")}</th><th scope="col" className="px-3 py-2 text-right">{t("billing.invoice.amount")}</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {lines.map((l, n) => (
              <tr key={n}><td className="px-3 py-2">{l.description}</td><td className="tnum px-3 py-2 text-right">{l.quantity}</td><td className="tnum px-3 py-2 text-right">{money(l.amount, i.currency)}</td></tr>
            ))}
          </tbody>
          <tfoot className="border-t border-line text-sm">
            <Total label={t("billing.invoice.subtotal")} value={money(i.subtotal, i.currency)} />
            {Number(i.discount_total) !== 0 && <Total label={t("billing.invoice.discount")} value={money(i.discount_total, i.currency)} />}
            {taxes.map((x) => <Total key={x.name} label={`${x.name} (${x.rate_percent}%)`} value={money(x.amount, i.currency)} />)}
            <Total label={t("billing.invoice.total")} value={money(i.total, i.currency)} strong />
            <Total label={t("billing.invoice.paid")} value={money(i.amount_paid, i.currency)} />
            <Total label={t("billing.invoice.balance")} value={money(i.balance, i.currency)} strong />
          </tfoot>
        </table>
      </div>
      {i.tax_inclusive && <p className="text-xs text-muted">{t("billing.invoice.taxInclusive")}</p>}
      {i.notes && <p className="whitespace-pre-line text-sm text-muted">{i.notes}</p>}

      <section>
        <h3 className="mb-2 text-sm font-semibold">{t("billing.invoice.payments")}</h3>
        <DataTable rows={i.payments} columns={payments} rowKey={(p) => p.id} dense empty={{ title: t("billing.invoice.noPayments") }} />
      </section>

      <InvoiceAttempts invoiceId={id} />

      {canBill && (
        <div className="flex flex-wrap gap-2 border-t border-line pt-4">
          {i.status === "draft" && <Button onClick={() => setDialog("issue")}>{t("billing.invoice.issue")}</Button>}
          {i.status === "issued" && Number(i.balance) > 0 && <Button onClick={() => setDialog("pay")}>{t("billing.payment.record")}</Button>}
          {(i.status === "draft" || i.status === "issued") && <Button variant="danger" onClick={() => setDialog("void")}>{t("billing.invoice.void")}</Button>}
        </div>
      )}

      {dialog === "pay" && <RecordPaymentDialog invoices={[i]} initialId={id} onClose={() => setDialog(null)} />}
      {dialog === "issue" && (
        <ChangeConfirm title={t("billing.invoice.issueTitle")} message={t("billing.invoice.issueMessage")} confirmLabel={t("billing.invoice.issue")}
          run={() => opUnwrap(opApi.POST("/api/v1/operator/invoices/{invoice_id}/issue", { params: { path: { invoice_id: id } } }))}
          onDone={() => { toast(t("billing.invoice.issued"), "ok"); refresh(); }} onClose={() => setDialog(null)} />
      )}
      {dialog === "void" && (
        <ReasonDialog title={t("billing.invoice.voidTitle")} intro={t("billing.invoice.voidMessage")} confirmLabel={t("billing.invoice.void")} danger
          run={(reason) => opUnwrap(opApi.POST("/api/v1/operator/invoices/{invoice_id}/void", { params: { path: { invoice_id: id } }, body: { reason } }))}
          onDone={() => { toast(t("billing.invoice.voided"), "ok"); refresh(); }} onClose={() => setDialog(null)} />
      )}
      {reversing && (
        <ReasonDialog title={t("billing.invoice.reverseTitle")} intro={t("billing.invoice.reverseMessage", { amount: money(reversing.amount, reversing.currency) })} confirmLabel={t("billing.invoice.reverse")} danger
          run={(reason) => opUnwrap(opApi.POST("/api/v1/operator/payments/{payment_id}/reverse", { params: { path: { payment_id: reversing.id } }, body: { reason } }))}
          onDone={() => { toast(t("billing.invoice.reversedDone"), "ok"); refresh(); }} onClose={() => setReversing(null)} />
      )}
    </div>
  );
}

function Total({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <tr className={strong ? "font-semibold" : "text-muted"}>
      <td className="px-3 py-1.5 text-right" colSpan={2}>{label}</td>
      <td className="tnum px-3 py-1.5 text-right">{value}</td>
    </tr>
  );
}
