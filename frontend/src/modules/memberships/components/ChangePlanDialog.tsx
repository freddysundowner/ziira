import { useEffect, useState } from "react";

import { api, Alert, Button, Field, Modal, money, Select, Skeleton, toast, unwrap, useCurrency, useMutation, useQuery, useQueryClient, useTranslation, formatDate } from "@/sdk";

import type { Member } from "../hooks";
import { usePlans } from "../hooks";
import { credits } from "../logic";

/** Move a member to another plan: see what it costs today, then upgrade now or change at the next renewal. */
export function ChangePlanDialog({ member, open, onClose }: { member: Member; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const currency = useCurrency(member.company_id);
  const [planId, setPlanId] = useState("");
  const plans = usePlans(member.company_id, "active");
  useEffect(() => { if (open) setPlanId(""); }, [open]);
  const quote = useQuery({
    enabled: open && !!planId, retry: false, queryKey: ["memberships", "quote", member.id, planId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}/change-quote", { params: { path: { member_id: member.id }, query: { plan_id: planId } } })),
  });
  const change = useMutation({
    meta: { silent: true },
    mutationFn: (when: "now" | "next_renewal") => unwrap(api.POST("/api/v1/memberships/members/{member_id}/change-plan", { params: { path: { member_id: member.id } }, body: { plan_id: planId, when } })),
    onSuccess: (_, when) => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(t(when === "now" ? "change.doneNow" : "change.doneLater"), "ok"); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const q = quote.data;
  return (
    <Modal open={open} onClose={onClose} title={t("change.title")}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
          <Button variant="secondary" disabled={!q} loading={change.isPending} onClick={() => change.mutate("next_renewal")}>{t("change.atRenewal")}</Button>
          <Button disabled={!q?.can_start_now} loading={change.isPending} onClick={() => change.mutate("now")}>{t("change.upgradeNow")}</Button>
        </>
      )}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("change.explain", { plan: member.plan_name })}</p>
        <Field label={t("change.newPlan")}>
          <Select value={planId} onChange={(e) => setPlanId(e.target.value)}>
            <option value="">{t("pickPlan")}</option>
            {plans.data?.filter((p) => p.id !== member.plan_id).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        {planId && quote.isLoading && <Skeleton className="h-24 w-full" />}
        {quote.error && <Alert tone="bad">{quote.error.message}</Alert>}
        {q && (
          <div className="space-y-2 rounded-lg bg-sunken p-3 text-sm">
            <p>{t("change.prices", { from: money(q.old_price, currency), to: money(q.new_price, currency) })}</p>
            {q.can_start_now
              ? (
                <>
                  <p className="font-semibold">{t("change.chargeNow", { amount: money(q.charge_now, currency) })}</p>
                  {Number(q.extra_credits_now) > 0 && <p>{t("change.extraCredits", { n: credits(q.extra_credits_now) })}</p>}
                </>)
              : <Alert tone="info">{q.reason ?? t("change.laterOnly")}</Alert>}
            <p className="text-muted">{t("change.startsOn", { date: formatDate(q.starts_on) })}</p>
          </div>
        )}
      </div>
    </Modal>
  );
}
