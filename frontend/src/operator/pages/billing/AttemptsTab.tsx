import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, Button, type Column, DataTable, DetailList, Drawer, ErrorState, formatDate, money, Select, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { ATTEMPT_TONES, canMarkPaid } from "../../helpers/gateway";
import { ChangeConfirm } from "../../components/ChangeConfirm";
import { ReasonDialog } from "../../components/ReasonDialog";
import { useOperatorCan } from "../../me";
import type { Schemas } from "@/sdk";

type Attempt = Schemas["OperatorAttempt"];
const STATUSES = ["initiated", "pending", "completed", "failed", "expired", "mismatch"];

/** Every try a business made to pay by itself, with filters; a stuck one can be re-checked or marked paid (with a reason). */
export default function AttemptsTab() {
  const { t } = useTranslation("operator");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["operator", "payment-attempts", status],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/payment-attempts", { params: { query: { ...(status ? { status } : {}), limit: 200 } } })),
  });
  const columns: Column<Attempt>[] = [
    { header: t("billing.attempts.when"), cell: (a) => <span className="text-sm">{formatDate(a.created_at, true)}</span> },
    { header: t("billing.requests.subscriber"), cell: (a) => <div><p className="text-sm font-medium">{a.tenant_name}</p><p className="font-mono text-xs text-muted">{a.tenant_code}</p></div> },
    { header: t("billing.attempts.invoice"), hideBelow: "sm", cell: (a) => <span className="font-mono text-xs">{a.invoice_number}</span> },
    { header: t("billing.attempts.provider"), hideBelow: "md", cell: (a) => a.provider_label },
    { header: t("billing.invoice.amount"), align: "right", cell: (a) => money(a.amount, a.currency) },
    { header: t("billing.invoice.status"), cell: (a) => <Badge tone={ATTEMPT_TONES[a.status] ?? "neutral"}>{t(`billing.attempts.statuses.${a.status}`, a.status)}</Badge> },
    { header: "", align: "right", cell: (a) => <Button size="sm" variant="secondary" onClick={() => setOpen(a.id)}>{t("billing.attempts.open")}</Button> },
  ];
  return (
    <>
      <div className="mb-3 max-w-xs">
        <Select aria-label={t("billing.invoice.status")} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("billing.attempts.allStatuses")}</option>
          {STATUSES.map((s) => <option key={s} value={s}>{t(`billing.attempts.statuses.${s}`, s)}</option>)}
        </Select>
      </div>
      <DataTable rows={list.data} columns={columns} rowKey={(a) => a.id} loading={list.isPending} error={list.isError ? list.error.message : null}
        onRetry={() => void list.refetch()} empty={{ title: t("billing.attempts.none"), hint: t("billing.attempts.noneHint") }} />
      {open && <AttemptDrawer id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

export function AttemptDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const canBill = useOperatorCan("platform.billing");
  const [dialog, setDialog] = useState<"recheck" | "paid" | null>(null);
  const detail = useQuery({ queryKey: ["operator", "payment-attempt", id], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/payment-attempts/{attempt_id}", { params: { path: { attempt_id: id } } })) });
  const refresh = () => { void detail.refetch(); };
  const a = detail.data;
  return (
    <Drawer open onClose={onClose} title={t("billing.attempts.detail")}>
      {detail.isPending && <Skeleton className="h-40 w-full" />}
      {detail.isError && <ErrorState message={detail.error.message} onRetry={refresh} />}
      {a && (
        <div className="space-y-5">
          <div className="flex items-center gap-2"><Badge tone={ATTEMPT_TONES[a.status] ?? "neutral"}>{t(`billing.attempts.statuses.${a.status}`, a.status)}</Badge><span className="text-sm text-muted">{a.provider_label}</span></div>
          {a.result_desc && <p className="text-sm">{a.result_desc}</p>}
          <DetailList items={[
            { label: t("billing.requests.subscriber"), value: `${a.tenant_name} (${a.tenant_code})` },
            { label: t("billing.attempts.invoice"), value: a.invoice_number ?? "-" },
            { label: t("billing.invoice.amount"), value: money(a.amount, a.currency) },
            { label: t("billing.attempts.phone"), value: a.payer_phone_last4 ? `…${a.payer_phone_last4}` : "-" },
            { label: t("billing.attempts.providerId"), value: a.provider_transaction_id ?? "-" },
            { label: t("billing.attempts.checkoutId"), value: a.checkout_request_id ?? "-" },
            { label: t("billing.attempts.reference"), value: a.payment_reference ?? "-" },
            { label: t("billing.attempts.ours"), value: a.reference },
            { label: t("billing.attempts.lastChecked"), value: a.last_checked_at ? formatDate(a.last_checked_at, true) : "-" },
            { label: t("billing.attempts.completedBy"), value: a.completed_by ?? "-" },
          ]} />
          <section>
            <h3 className="mb-2 text-sm font-semibold">{t("billing.attempts.timeline")}</h3>
            <ol className="space-y-1.5 border-l border-line pl-3">
              {a.timeline.map((e, i) => (
                <li key={i} className="text-sm"><span className="text-xs text-muted">{formatDate(e.occurred_at, true)}</span> <span className="font-medium">{t(`billing.attempts.events.${e.kind}`, e.kind)}</span>
                  {e.detail && <span className="text-xs text-muted"> {Object.entries(e.detail).map(([k, v]) => `${k}: ${String(v)}`).join(" · ")}</span>}</li>
              ))}
            </ol>
          </section>
          {canBill && canMarkPaid(a.status) && (
            <div className="flex flex-wrap gap-2 border-t border-line pt-4">
              {(a.status === "initiated" || a.status === "pending" || a.status === "failed") && <Button variant="secondary" onClick={() => setDialog("recheck")}>{t("billing.attempts.recheck")}</Button>}
              <Button onClick={() => setDialog("paid")}>{t("billing.attempts.markPaid")}</Button>
            </div>
          )}
          {dialog === "recheck" && (
            <ChangeConfirm title={t("billing.attempts.recheck")} message={t("billing.attempts.recheckMessage")} confirmLabel={t("billing.attempts.recheck")}
              run={() => opUnwrap(opApi.POST("/api/v1/operator/payment-attempts/{attempt_id}/recheck", { params: { path: { attempt_id: id } } }))}
              onDone={() => { toast(t("billing.attempts.rechecked"), "ok"); refresh(); }} onClose={() => setDialog(null)} />
          )}
          {dialog === "paid" && (
            <ReasonDialog title={t("billing.attempts.markPaid")} intro={t("billing.attempts.markPaidMessage")} confirmLabel={t("billing.attempts.markPaid")}
              run={(reason) => opUnwrap(opApi.POST("/api/v1/operator/payment-attempts/{attempt_id}/mark-paid", { params: { path: { attempt_id: id } }, body: { reason } }))}
              onDone={() => { toast(t("billing.attempts.markedPaid"), "ok"); refresh(); }} onClose={() => setDialog(null)} />
          )}
        </div>
      )}
    </Drawer>
  );
}
