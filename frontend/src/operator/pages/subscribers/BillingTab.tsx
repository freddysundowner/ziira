import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, type BadgeTone, type Column, DataTable, formatDate, money, type Schemas, useTranslation } from "@/sdk";

import type { PlatformSchema } from "../../types";
import { InvoiceBadge } from "../../components/bits";
import { useOperatorCan } from "../../me";
import { InvoiceDrawer } from "../billing/InvoiceDrawer";
import { InvoiceFormDialog, RecordPaymentDialog } from "../billing/invoiceDialogs";

type Detail = Schemas["SubscriberDetail"];
type Invoice = PlatformSchema<"InvoiceOut">;
type Payment = PlatformSchema<"PaymentOut">;
type Request = PlatformSchema<"RequestOut">;
const REQUEST_TONES: Record<string, BadgeTone> = { pending: "warn", approved: "ok", declined: "bad", cancelled: "neutral" };

export function BillingTab({ d }: { d: Detail }) {
  const { t } = useTranslation("operator");
  const canBill = useOperatorCan("platform.billing");
  const [open, setOpen] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"invoice" | "payment" | null>(null);
  const payable = d.invoices.filter((i) => i.status === "issued" && Number(i.balance) > 0);

  const invoices: Column<Invoice>[] = [
    {
      header: t("billing.invoice.number"),
      cell: (i) => (
        <button type="button" onClick={() => setOpen(i.id)} className="rounded font-mono text-sm font-medium text-brand-strong hover:underline" aria-label={t("billing.invoices.open", { number: i.number ?? t("billing.invoice.draftTitle") })}>
          {i.number ?? t("billing.invoice.draftTitle")}
        </button>
      ),
    },
    { header: t("billing.invoice.status"), cell: (i) => <InvoiceBadge status={i.status} /> },
    { header: t("billing.invoice.dueDate"), hideBelow: "sm", cell: (i) => <span className="text-sm">{i.due_date ? formatDate(i.due_date) : "-"}</span> },
    { header: t("billing.invoice.total"), align: "right", cell: (i) => <span className="text-sm">{money(i.total, i.currency)}</span> },
    { header: t("billing.invoice.balance"), align: "right", cell: (i) => <span className={i.status === "issued" && Number(i.balance) > 0 ? "text-sm text-bad" : "text-sm text-muted"}>{money(i.balance, i.currency)}</span> },
  ];
  const payments: Column<Payment>[] = [
    { header: t("billing.invoice.paidOn"), cell: (p) => <span className="text-sm">{formatDate(p.paid_on)}</span> },
    { header: t("billing.invoice.number"), hideBelow: "sm", cell: (p) => <span className="font-mono text-sm">{p.invoice_number ?? "-"}</span> },
    { header: t("billing.payment.method"), cell: (p) => <div><p className="text-sm">{p.method}</p>{p.reference && <p className="text-xs text-muted">{p.reference}</p>}</div> },
    { header: t("billing.invoice.amount"), align: "right", cell: (p) => <span className={p.reversed_at ? "text-sm text-muted line-through" : "text-sm"}>{money(p.amount, p.currency)}</span> },
    { header: "", hideBelow: "md", cell: (p) => p.reversed_at ? <Badge tone="bad">{t("billing.invoice.reversed", { date: formatDate(p.reversed_at) })}</Badge> : null },
  ];
  const requests: Column<Request>[] = [
    { header: t("billing.requests.plan"), cell: (r) => <div><p className="text-sm">{r.plan_name}</p><p className="text-xs text-muted">{t(`interval.${r.interval}`)} · {r.currency}</p></div> },
    { header: t("billing.requests.requested"), hideBelow: "sm", cell: (r) => <span className="text-sm">{formatDate(r.created_at)}</span> },
    { header: t("billing.invoice.status"), cell: (r) => <Badge tone={REQUEST_TONES[r.status] ?? "neutral"}>{t(`billing.requests.statuses.${r.status}`, r.status)}</Badge> },
  ];

  return (
    <div className="space-y-5">
      {canBill && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setDialog("invoice")}>{t("subscriber.billing.createInvoice")}</Button>
          <Button variant="secondary" disabled={payable.length === 0} title={payable.length === 0 ? t("billing.payment.nothingOpen") : undefined} onClick={() => setDialog("payment")}>{t("billing.payment.record")}</Button>
        </div>
      )}
      <section>
        <h2 className="mb-2 text-base font-semibold">{t("subscriber.billing.invoices")}</h2>
        <DataTable rows={d.invoices} columns={invoices} rowKey={(i) => i.id} dense pageSize={10} empty={{ title: t("subscriber.billing.noInvoices") }} />
      </section>
      <section>
        <h2 className="mb-2 text-base font-semibold">{t("subscriber.billing.payments")}</h2>
        <DataTable rows={d.payments} columns={payments} rowKey={(p) => p.id} dense pageSize={10} empty={{ title: t("subscriber.billing.noPayments") }} />
      </section>
      <section>
        <div className="mb-2 flex items-baseline justify-between"><h2 className="text-base font-semibold">{t("subscriber.billing.requests")}</h2><Link className="text-xs font-medium text-brand-strong hover:underline" to="/operator/billing/requests">{t("subscriber.billing.allRequests")}</Link></div>
        <DataTable rows={d.requests} columns={requests} rowKey={(r) => r.id} dense pageSize={10} empty={{ title: t("subscriber.billing.noRequests") }} />
      </section>

      {open && <InvoiceDrawer invoiceId={open} onClose={() => setOpen(null)} />}
      {dialog === "invoice" && <InvoiceFormDialog tenantCode={d.code} onClose={() => setDialog(null)} />}
      {dialog === "payment" && <RecordPaymentDialog invoices={payable} onClose={() => setDialog(null)} />}
    </div>
  );
}
