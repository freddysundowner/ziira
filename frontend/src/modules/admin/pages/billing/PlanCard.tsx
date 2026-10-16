import { useState } from "react";

import { api, Alert, Badge, Button, Card, ConfirmDialog, DetailList, Field, formatDate, money, Textarea, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { PLAN_KEY, STATUS_KEY, statusTone, type MyPlan } from "./lib";

/** The request waiting for the vendor; the generated type may not list every field yet, so only the id and plan code are relied on. */
type PendingRequest = { id: string; plan_code: string; plan_name?: string };

/** The current plan: what it costs, when it renews, a pending change or request, and cancel / resume. */
export function PlanCard({ plan, planNames, canChange }: { plan: MyPlan; planNames: Record<string, string>; canChange: boolean }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const refresh = () => { void qc.invalidateQueries({ queryKey: PLAN_KEY }); void qc.invalidateQueries({ queryKey: STATUS_KEY }); };
  const fail = (e: Error) => toast(e.message, "bad");
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/billing/cancel", { body: { reason: reason.trim() || null } })),
    onSuccess: () => { refresh(); setCancelling(false); setReason(""); toast(t("billing.cancelled"), "ok"); },
    onError: fail, meta: { silent: true },
  });
  const resume = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/billing/resume")),
    onSuccess: () => { refresh(); toast(t("billing.resumed"), "ok"); },
    onError: fail, meta: { silent: true },
  });
  const withdraw = useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/billing/change-request/{request_id}", { params: { path: { request_id: id } } })),
    onSuccess: () => { refresh(); toast(t("billing.withdrawn"), "ok"); },
    onError: fail, meta: { silent: true },
  });

  const req = plan.request as PendingRequest | null;
  const trialing = plan.status === "trialing";
  const endsAt = plan.cancel_at_period_end ? plan.period_end : null;
  const items = [
    { label: t("billing.price"), value: plan.is_comp ? t("billing.comp") : plan.unit_amount ? `${money(plan.unit_amount, plan.currency)}${plan.interval ? ` / ${t(`billing.interval.${plan.interval}`, { defaultValue: plan.interval })}` : ""}${plan.tax_inclusive ? ` · ${t("billing.taxIncl")}` : ""}` : "—" },
    trialing && plan.trial_end ? { label: t("billing.trialEnds"), value: formatDate(plan.trial_end) } : { label: t(plan.cancel_at_period_end ? "billing.endsOn" : "billing.renews"), value: formatDate(plan.period_end) },
    ...(plan.coupon_code ? [{ label: t("billing.coupon"), value: plan.coupon_code }] : []),
  ];
  const canCancel = canChange && !plan.cancel_at_period_end && !plan.is_comp && ["trialing", "active", "past_due", "grace"].includes(plan.status);

  return (
    <Card
      title={plan.plan_name ?? t("billing.noPlan")}
      description={plan.edition ?? undefined}
      actions={<Badge tone={statusTone(plan.status)}>{t(`billing.status.${plan.status}`, { defaultValue: plan.status })}</Badge>}
    >
      <div className="space-y-4">
        <DetailList items={items} />
        {endsAt && (
          <Alert tone="warn">
            <p>{t("billing.cancelNotice", { date: formatDate(endsAt) })}</p>
            {canChange && <Button size="sm" variant="secondary" className="mt-2" loading={resume.isPending} onClick={() => resume.mutate()}>{t("billing.resume")}</Button>}
          </Alert>
        )}
        {plan.pending_change && (
          <Alert tone="info">{t("billing.pendingChange", { plan: plan.pending_change.plan_name, date: formatDate(plan.period_end) })}</Alert>
        )}
        {req && (
          <Alert tone="info">
            <p>{t("billing.requestSent", { plan: planNames[req.plan_code] ?? req.plan_name ?? req.plan_code })}</p>
            {canChange && <Button size="sm" variant="secondary" className="mt-2" loading={withdraw.isPending} onClick={() => withdraw.mutate(req.id)}>{t("billing.withdraw")}</Button>}
          </Alert>
        )}
        {canCancel && <div><Button variant="ghost" className="text-bad" onClick={() => setCancelling(true)}>{t("billing.cancelSub")}</Button></div>}
      </div>
      <ConfirmDialog open={cancelling} onClose={() => setCancelling(false)} danger busy={cancel.isPending} title={t("billing.cancelSub")} confirmLabel={t("billing.cancelConfirm")}
        onConfirm={() => cancel.mutate()}
        message={(
          <div className="space-y-3">
            <p>{t("billing.cancelAsk", { date: formatDate(plan.period_end) })}</p>
            <Field label={t("billing.cancelReason")}><Textarea rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          </div>
        )} />
    </Card>
  );
}
