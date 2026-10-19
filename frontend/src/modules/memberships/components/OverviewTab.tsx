import { ArrowRightLeft } from "lucide-react";
import { useState } from "react";

import {
  api, Alert, Button, Card, DataTable, DetailList, formatDate, money, Switch, Tabs, toast, unwrap, useCan, useCurrency, useMutation, useQuery, useQueryClient,
  useTranslation,
} from "@/sdk";

import { usePlans, type Member } from "../hooks";
import { credits } from "../logic";
import CustomerMembership from "../slots/CustomerMembership";
import { LedgerTable } from "./LedgerTable";
import { ChangePlanDialog } from "./ChangePlanDialog";
import { GuestsCard } from "./GuestsCard";

/** Membership, credits, holds, plan changes and guests. A person with no membership sees their memberships and packages instead. */
export function OverviewTab({ member, customerId, companyId }: { member?: Member; customerId: string; companyId: string }) {
  if (!member) return <CustomerMembership customerId={customerId} companyId={companyId} />;
  return <MembershipOverview member={member} />;
}

function MembershipOverview({ member: m }: { member: Member }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const currency = useCurrency(m.company_id);
  const canManage = useCan("memberships.manage");
  const [changing, setChanging] = useState(false);
  const [inner, setInner] = useState<"credits" | "history">("credits");
  const live = m.status === "active" || m.status === "paused" || m.status === "frozen";
  const plans = usePlans(m.company_id);
  const plan = plans.data?.find((p) => p.id === m.plan_id);
  const history = useQuery({
    enabled: inner === "history", queryKey: ["memberships", "history", m.id],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}/history", { params: { path: { member_id: m.id } } })),
  });
  const freezes = useQuery({ queryKey: ["memberships", "freezes", m.id], queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}/freezes", { params: { path: { member_id: m.id } } })) });
  const allowance = useQuery({ enabled: live, queryKey: ["memberships", "allowance", m.id], queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}/freeze-allowance", { params: { path: { member_id: m.id } } })) });
  const done = () => { void qc.invalidateQueries({ queryKey: ["memberships"] }); };
  const lock = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: (locked: boolean) => unwrap(api.PATCH("/api/v1/memberships/members/{member_id}", { params: { path: { member_id: m.id } }, body: { price_locked: locked, clear_billing_customer: false } })),
    onSuccess: (_, locked) => { done(); toast(t(locked ? "overview.priceLocked" : "overview.priceUnlocked"), "ok"); },
  });
  const undo = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/members/{member_id}/undo-plan-change", { params: { path: { member_id: m.id } } })),
    onSuccess: () => { done(); toast(t("change.undone"), "ok"); },
  });

  return (
    <div className="space-y-4">
      {m.cancel_at && m.status === "active" && <Alert tone="warn">{t("endsOnBanner", { date: formatDate(m.cancel_at) })}</Alert>}
      {(m.status === "paused" || m.status === "frozen") && <Alert tone="info">{m.resume_on ? t("onHoldUntil", { date: formatDate(m.resume_on) }) : t("onHold")}</Alert>}
      {Number(m.arrears) > 0 && <Alert tone="bad">{t("overview.owesBanner", { amount: money(m.arrears, currency), days: m.days_late })}</Alert>}
      {m.pending_plan_id && m.pending_from && (
        <Alert tone="info">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span>{t("change.pending", { plan: m.pending_plan_name ?? "", date: formatDate(m.pending_from) })}</span>
            {canManage && <Button size="sm" variant="secondary" loading={undo.isPending} onClick={() => undo.mutate()}>{t("change.undo")}</Button>}
          </span>
        </Alert>
      )}
      {m.notes && <Alert tone="info">{m.notes}</Alert>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t("membershipCard")} actions={canManage && live && <Button variant="secondary" onClick={() => setChanging(true)}><ArrowRightLeft className="h-4 w-4" />{t("change.button")}</Button>}>
          <DetailList items={[
            { label: t("plan"), value: m.plan_name },
            { label: t("fee"), value: `${money(m.price, currency)} / ${t(`intervalShort.${m.billing_interval}`)}` },
            { label: t("startedOn"), value: formatDate(m.start_date) },
            { label: t("nextRenewal"), value: m.status === "active" ? (m.cancel_at ? t("endsOn", { date: formatDate(m.cancel_at) }) : formatDate(m.next_renewal_date)) : "—" },
            ...(m.end_date ? [{ label: t("endDate"), value: formatDate(m.end_date) }] : []),
            ...(m.term_end ? [{ label: t("overview.contractEnds"), value: formatDate(m.term_end) }] : []),
            ...(plan && plan.notice_days > 0 ? [{ label: t("overview.notice"), value: t("overview.noticeDays", { count: plan.notice_days }) }] : []),
            ...(m.billing_customer_name ? [{ label: t("overview.payer"), value: m.billing_customer_name }] : []),
            { label: t("invoicing"), value: m.auto_invoice ? t("invoicedEachPeriod") : t("notInvoiced") },
          ]} />
          {canManage && live && (
            <div className="mt-3 border-t border-line pt-3">
              <Switch checked={m.price_locked} onChange={(v) => lock.mutate(v)} label={t("overview.lockPrice")} disabled={lock.isPending} />
              <p className="mt-1 text-xs text-muted">{t("overview.lockPriceHint")}</p>
            </div>
          )}
        </Card>
        <Card title={t("creditsCard")}>
          <p className="mb-2 text-3xl font-semibold">{credits(m.balance)}</p>
          <DetailList items={[
            { label: t("perPeriod"), value: credits(m.credits_per_period) },
            { label: t("discountOnServices"), value: `${credits(m.discount_percent)}%` },
            { label: t("unusedAtEnd"), value: m.rollover ? t("rollsOver") : t("expiresAtEnd") },
            { label: t("covers"), value: m.covered_services.length ? m.covered_services.join(", ") : t("allServices") },
          ]} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GuestsCard member={m} />
        <Card title={t("holds.title")} description={allowance.data ? (allowance.data.allowed ? (allowance.data.limit === null ? t("holds.noLimit") : t("holds.allowance", { left: allowance.data.left ?? 0, limit: allowance.data.limit, used: allowance.data.used })) : t("holds.notAllowed")) : undefined}>
          {allowance.data && Number(allowance.data.fee) > 0 && <p className="mb-2 text-sm text-muted">{t("holds.fee", { amount: money(allowance.data.fee, currency) })}</p>}
          <DataTable rows={freezes.data} loading={freezes.isLoading} error={freezes.error?.message} onRetry={() => void freezes.refetch()} rowKey={(f) => f.id} dense
            empty={{ title: t("holds.empty") }}
            columns={[
              { header: t("holds.from"), cell: (f) => formatDate(f.started_on) },
              { header: t("holds.to"), cell: (f) => (f.ended_on ? formatDate(f.ended_on) : f.planned_resume_on ? t("holds.planned", { date: formatDate(f.planned_resume_on) }) : t("holds.running")) },
              { header: t("holds.days"), align: "right", cell: (f) => f.days ?? "—" },
              { header: t("fee"), hideBelow: "sm", align: "right", cell: (f) => (Number(f.fee) > 0 ? money(f.fee, currency) : "—") },
            ]} />
        </Card>
      </div>

      <div>
        <Tabs value={inner} onChange={setInner} tabs={[{ id: "credits", label: t("creditsLedger") }, { id: "history", label: t("history") }]} />
        {inner === "credits" && <LedgerTable holderId={m.id} kind="member" />}
        {inner === "history" && (
          <Card flush>
            {history.error ? <p className="p-4 text-sm text-bad">{history.error.message}</p>
              : !history.data ? <p className="p-4 text-sm text-muted">{t("loading")}</p>
              : (
                <ul className="divide-y divide-line">
                  {history.data.map((h) => (
                    <li key={h.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3 text-sm">
                      <span><span className="font-medium">{t(`historyActions.${h.action}`, h.action)}</span>{h.note ? <span className="text-muted"> · {h.note}</span> : null}</span>
                      <span className="text-muted">{formatDate(h.happened_on)}</span>
                    </li>
                  ))}
                </ul>)}
          </Card>
        )}
      </div>
      <ChangePlanDialog member={m} open={changing} onClose={() => setChanging(false)} />
    </div>
  );
}
