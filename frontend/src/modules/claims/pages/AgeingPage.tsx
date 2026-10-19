import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, Card, EmptyState, ErrorState, formatDate, money, PageHeader, Skeleton, useCan, useTranslation } from "@/sdk";

import { ReceiptDialog } from "../components/ReceiptDialog";
import { ShortPayDialog } from "../components/ShortPayDialog";
import { useAgeing, useClaimsCompany, useOwed, useShortPays } from "../hooks";
import type { AgeingRow, ShortPay } from "../types";

const BUCKETS = ["not_due", "d1_30", "d31_60", "d61_90", "d90_plus"] as const;

/** What each payer owes, by how late it is, with the invoices behind each figure and the payments that came up short. */
export default function AgeingPage() {
  const { t } = useTranslation("claims");
  const { companyId, currency, isLoading } = useClaimsCompany();
  const canPay = useCan("claims.payments");
  const ageing = useAgeing(companyId);
  const shorts = useShortPays("open");
  const [open, setOpen] = useState<string | null>(null);
  const [paying, setPaying] = useState<AgeingRow | null>(null);
  const [resolving, setResolving] = useState<ShortPay | null>(null);
  const rows = ageing.data ?? [];
  const totals = BUCKETS.map((b) => rows.reduce((n, r) => n + Number(r.buckets[b] ?? 0), 0));
  const grand = rows.reduce((n, r) => n + Number(r.total), 0);
  return (
    <>
      <PageHeader title={t("ageing.title")} description={t("ageing.hint")} />
      <div className="space-y-6">
        <Card flush title={t("ageing.owed")}>
          {isLoading || ageing.isLoading ? <Skeleton className="m-4 h-32" /> : ageing.error ? <ErrorState message={ageing.error.message} onRetry={() => void ageing.refetch()} /> : rows.length === 0 ? (
            <EmptyState title={t("ageing.empty")} hint={t("ageing.emptyHint")} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line bg-sunken/60 text-xs uppercase tracking-wide text-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">{t("ageing.payer")}</th>
                    {BUCKETS.map((b) => <th key={b} className="px-2 py-2 text-right font-medium">{t(`ageing.bucket.${b}`)}</th>)}
                    <th className="px-4 py-2 text-right font-medium">{t("ageing.total")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.map((r) => (
                    <Fragment key={r.payer_id}>
                      <tr className="cursor-pointer hover:bg-sunken/50" onClick={() => setOpen(open === r.payer_id ? null : r.payer_id)}>
                        <td className="px-4 py-2.5"><button type="button" className="text-left font-medium" aria-expanded={open === r.payer_id}>{r.payer}</button><span className="block text-xs text-muted">{t("ageing.invoices", { n: r.invoices })}</span></td>
                        {BUCKETS.map((b) => <td key={b} className={`tnum px-2 py-2.5 text-right ${b === "d90_plus" && Number(r.buckets[b]) > 0 ? "font-semibold text-bad" : ""}`}>{Number(r.buckets[b]) > 0 ? money(r.buckets[b], currency) : "—"}</td>)}
                        <td className="tnum px-4 py-2.5 text-right font-semibold">{money(r.total, currency)}</td>
                      </tr>
                      {open === r.payer_id && (
                        <tr><td colSpan={7} className="bg-sunken/40 px-4 py-3"><OwedList payerId={r.payer_id} currency={currency} canPay={canPay} onPay={() => setPaying(r)} /></td></tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
                <tfoot className="border-t border-line font-semibold">
                  <tr><td className="px-4 py-2.5">{t("ageing.all")}</td>{totals.map((n, i) => <td key={i} className="tnum px-2 py-2.5 text-right">{n > 0 ? money(n.toFixed(2), currency) : "—"}</td>)}<td className="tnum px-4 py-2.5 text-right">{money(grand.toFixed(2), currency)}</td></tr>
                </tfoot>
              </table>
            </div>
          )}
        </Card>
        <Card title={t("ageing.shorts")} description={t("ageing.shortsHint")}>
          {shorts.isLoading ? <Skeleton className="h-16" /> : (shorts.data ?? []).length === 0 ? <p className="text-sm text-muted">{t("ageing.noShorts")}</p> : (
            <ul className="divide-y divide-line text-sm">
              {(shorts.data ?? []).map((s) => (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span><span className="tnum font-medium">{money(s.difference, currency)}</span> <Link className="underline" to={`/claims/${s.claim_id}`}>{t("ageing.openClaim")}</Link> <span className="text-xs text-muted">{formatDate(s.created_at)}</span></span>
                  {canPay && <Button size="sm" variant="secondary" onClick={() => setResolving(s)}>{t("shortPay.resolve")}</Button>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {paying && <ReceiptDialog payerId={paying.payer_id} payerName={paying.payer} currency={currency} onClose={() => setPaying(null)} />}
      <ShortPayDialog shortPay={resolving} currency={currency} onClose={() => setResolving(null)} />
    </>
  );
}

function OwedList({ payerId, currency, canPay, onPay }: { payerId: string; currency: string | undefined; canPay: boolean; onPay: () => void }) {
  const { t } = useTranslation("claims");
  const owed = useOwed(payerId);
  if (owed.isLoading) return <Skeleton className="h-12" />;
  return (
    <div className="space-y-2">
      <ul className="divide-y divide-line text-sm">
        {(owed.data ?? []).map((o) => (
          <li key={o.run_id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
            <span><Link className="font-medium underline" to={`/claims/${o.claim_id}`}>{o.claim_number}</Link> · {o.invoice_number} <span className="text-xs text-muted">{t("ageing.dueOn", { date: formatDate(o.due_date) })}</span></span>
            <span className="tnum">{o.days_late > 0 && <Badge tone="bad">{t("receipt.late", { n: o.days_late })}</Badge>} {money(o.outstanding, currency)}</span>
          </li>
        ))}
      </ul>
      {canPay && <Button size="sm" onClick={onPay}>{t("money.recordPayment")}</Button>}
    </div>
  );
}
