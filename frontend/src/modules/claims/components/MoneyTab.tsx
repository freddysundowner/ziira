import { Banknote } from "lucide-react";
import { useState } from "react";

import { api, Alert, Badge, Button, Card, EmptyState, ErrorState, money, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import { useClaimAction } from "../hooks";
import type { Claim, ShortPay } from "../types";
import { ReceiptDialog } from "./ReceiptDialog";
import { ShortPayDialog } from "./ShortPayDialog";

const invoiceTone = (s: string | null) => (s === "paid" ? "ok" : s === "part_paid" ? "warn" : s === "cancelled" ? "neutral" : "info") as "ok" | "warn" | "neutral" | "info";

/** The money side of a claim: what the next invoices would be, the invoices already made and how much of them is paid, and short payments. */
export function MoneyTab({ claim, currency, canInvoice, canPay }: { claim: Claim; currency: string | undefined; canInvoice: boolean; canPay: boolean }) {
  const { t } = useTranslation("claims");
  const [paying, setPaying] = useState(false);
  const [resolving, setResolving] = useState<ShortPay | null>(null);
  const billing = useQuery({
    queryKey: ["claims", "billing", claim.id, claim.status, claim.totals.payer_pays, claim.totals.customer_pays, claim.runs.length],
    queryFn: () => unwrap(api.GET("/api/v1/claims/claims/{claim_id}/billing", { params: { path: { claim_id: claim.id } } })),
    enabled: claim.status !== "closed",
  });
  const invoice = useClaimAction(claim.id, () => unwrap(api.POST("/api/v1/claims/claims/{claim_id}/invoice", { params: { path: { claim_id: claim.id } } })), { done: t("money.invoiced") });
  const b = billing.data;
  const nothing = b && b.payer_parts.length === 0 && b.customer_parts.length === 0;
  return (
    <div className="space-y-4">
      {claim.status !== "closed" && (
        <Card title={t("money.next")} description={t("money.nextHint")}
          actions={canInvoice && b && b.blockers.length === 0 && !nothing && <Button loading={invoice.isPending} onClick={() => invoice.mutate(undefined)}><Banknote className="h-4 w-4" />{t("money.invoiceNow")}</Button>}>
          {billing.isLoading && <Skeleton className="h-24" />}
          {billing.error && <ErrorState message={billing.error.message} onRetry={() => void billing.refetch()} />}
          {b && (
            <div className="space-y-3">
              {b.blockers.length > 0 && <Alert tone="warn"><ul className="list-disc pl-4">{b.blockers.map((x) => <li key={x}>{x}</li>)}</ul></Alert>}
              {nothing ? <p className="text-sm text-muted">{t("money.nothing")}</p> : (
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h3 className="mb-1 text-sm font-semibold">{t("money.toPayer", { payer: claim.payer_name })}</h3>
                    <ul className="divide-y divide-line text-sm">
                      {b.payer_parts.map((p, i) => (
                        <li key={i} className="flex justify-between gap-3 py-1.5"><span>{p.description}</span><span className="tnum">{money(p.amount, currency)}{Number(p.discount) > 0 && <span className="block text-right text-xs text-muted">− {money(p.discount, currency)}</span>}</span></li>
                      ))}
                    </ul>
                    <dl className="tnum mt-2 space-y-0.5 border-t border-line pt-2 text-sm">
                      <div className="flex justify-between text-muted"><dt>{t("money.payerGross")}</dt><dd>{money(b.payer_gross, currency)}</dd></div>
                      <div className="flex justify-between text-muted"><dt>{t("money.excessTaken")}</dt><dd>− {money(sumDiscount(b.payer_parts), currency)}</dd></div>
                      <div className="flex justify-between font-semibold"><dt>{t("money.payerInvoice")}</dt><dd>{money(b.payer_net, currency)}</dd></div>
                    </dl>
                  </div>
                  <div>
                    <h3 className="mb-1 text-sm font-semibold">{t("money.toCustomer", { name: claim.insured_name ?? t("money.customer") })}</h3>
                    {b.customer_parts.length === 0 ? <p className="text-sm text-muted">{t("money.nothingCustomer")}</p> : (
                      <ul className="divide-y divide-line text-sm">
                        {b.customer_parts.map((p, i) => <li key={i} className="flex justify-between gap-3 py-1.5"><span>{p.description}</span><span className="tnum">{money(p.amount, currency)}</span></li>)}
                      </ul>
                    )}
                    <dl className="tnum mt-2 space-y-0.5 border-t border-line pt-2 text-sm">
                      <div className="flex justify-between font-semibold"><dt>{t("money.customerInvoice")}</dt><dd>{money(b.customer_total, currency)}</dd></div>
                      {Number(b.absorbed) > 0 && <div className="flex justify-between text-muted"><dt>{t("money.absorbed")}</dt><dd>{money(b.absorbed, currency)}</dd></div>}
                    </dl>
                  </div>
                </div>
              )}
              {b.waiting_lines > 0 && <p className="text-xs text-muted">{t("money.waitingLines", { n: b.waiting_lines })}</p>}
            </div>
          )}
        </Card>
      )}
      <Card title={t("money.invoices")} flush actions={canPay && claim.runs.some((r) => r.payer_invoice_id) && <Button size="sm" variant="secondary" onClick={() => setPaying(true)}>{t("money.recordPayment")}</Button>}>
        {claim.runs.length === 0 ? <EmptyState title={t("money.noInvoices")} hint={t("money.noInvoicesHint")} /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line bg-sunken/60 text-xs uppercase tracking-wide text-muted">
                <tr><th className="px-4 py-2 font-medium">{t("money.run")}</th><th className="px-2 py-2 font-medium">{t("money.invoice")}</th><th className="px-2 py-2 text-right font-medium">{t("money.amount")}</th><th className="px-2 py-2 text-right font-medium">{t("money.owedNow")}</th><th className="px-4 py-2 font-medium">{t("money.status")}</th></tr>
              </thead>
              <tbody className="divide-y divide-line">
                {claim.runs.flatMap((r) => [
                  r.payer_invoice_number && <tr key={`${r.id}p`}><td className="px-4 py-2.5">{r.seq}</td><td className="px-2 py-2.5">{r.payer_invoice_number}<span className="block text-xs text-muted">{t("money.payerSide", { name: claim.payer_name })}</span></td><td className="tnum px-2 py-2.5 text-right">{money(r.payer_amount, currency)}</td><td className="tnum px-2 py-2.5 text-right">{r.payer_outstanding == null ? "—" : money(r.payer_outstanding, currency)}</td><td className="px-4 py-2.5">{r.payer_status ? <Badge tone={invoiceTone(r.payer_status)}>{t(`money.invoiceStatus.${r.payer_status}`, { defaultValue: r.payer_status })}</Badge> : null}</td></tr>,
                  r.customer_invoice_number && <tr key={`${r.id}c`}><td className="px-4 py-2.5">{r.seq}</td><td className="px-2 py-2.5">{r.customer_invoice_number}<span className="block text-xs text-muted">{t("money.customerSide")}</span></td><td className="tnum px-2 py-2.5 text-right">{money(r.customer_amount, currency)}</td><td className="tnum px-2 py-2.5 text-right">{r.customer_outstanding == null ? "—" : money(r.customer_outstanding, currency)}</td><td className="px-4 py-2.5">{r.customer_status ? <Badge tone={invoiceTone(r.customer_status)}>{t(`money.invoiceStatus.${r.customer_status}`, { defaultValue: r.customer_status })}</Badge> : null}</td></tr>,
                ])}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {claim.short_pays.length > 0 && (
        <Card title={t("money.shortPays")}>
          <ul className="divide-y divide-line text-sm">
            {claim.short_pays.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span><span className="tnum font-medium">{money(s.difference, currency)}</span> <Badge tone={s.status === "open" ? "bad" : s.status === "disputed" ? "warn" : "neutral"}>{t(`shortPay.status.${s.status}`)}</Badge>
                  <span className="block text-xs text-muted">{t("shortPay.summary", { expected: money(s.expected, currency), paid: money(s.paid, currency), difference: money(s.difference, currency) })}{s.recharge_invoice_number ? ` · ${s.recharge_invoice_number}` : ""}{s.note ? ` · ${s.note}` : ""}</span></span>
                {canPay && (s.status === "open" || s.status === "disputed") && <Button size="sm" variant="secondary" onClick={() => setResolving(s)}>{t("shortPay.resolve")}</Button>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {paying && <ReceiptDialog payerId={claim.payer_id} payerName={claim.payer_name} claimId={claim.id} currency={currency} onClose={() => setPaying(false)} />}
      <ShortPayDialog shortPay={resolving} currency={currency} onClose={() => setResolving(null)} />
    </div>
  );
}

const sumDiscount = (parts: readonly { discount: string }[]) => parts.reduce((n, p) => n + Number(p.discount), 0).toFixed(2);
