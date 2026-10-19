import { Send } from "lucide-react";
import { useState } from "react";

import {
  api, Alert, Button, ConfirmDialog, DataTable, EmptyState, Field, formatDate, Input, PageHeader, Select, Stat, StatGrid, Tabs, today, toast, unwrap, useAccess, useCan,
  useCompany, useMutation, useQuery, useQueryClient, useTranslation, money,
} from "@/sdk";

import { AgeingStrip } from "../components/AccountTab";
import { Amount } from "../components/Amount";
import { isPositive, overdueOf } from "../logic";
import { customerPath } from "../public";

/** What customers owe, by how late it is, with the overdue invoices to chase. Needs Point of sale (it owns invoices). */
export default function ReceivablesPage() {
  const { t } = useTranslation("crm");
  const { enabledUnits } = useAccess();
  const [tab, setTab] = useState<"ageing" | "chase">("ageing");
  if (!enabledUnits.has("pos")) {
    return (
      <>
        <PageHeader title={t("receivablesTitle")} />
        <EmptyState title={t("needsPos")} hint={t("needsPosHint")} />
      </>
    );
  }
  return (
    <>
      <PageHeader title={t("receivablesTitle")} description={t("receivablesHint")} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "ageing", label: t("ageing") }, { id: "chase", label: t("toChase") }]} />
      {tab === "ageing" ? <Ageing /> : <Chase />}
    </>
  );
}

function Ageing() {
  const { t } = useTranslation("crm");
  const [asOf, setAsOf] = useState(today());
  const q = useQuery({ queryKey: ["ageing", "all", asOf], queryFn: () => unwrap(api.GET("/api/v1/pos/receivables/ageing", { params: { query: { as_of: asOf || undefined } } })) });
  const d = q.data;
  const { company } = useCompany();
  const overdue = d ? overdueOf(d.buckets) : undefined;
  return (
    <div className="space-y-4">
      <StatGrid>
        <Stat label={t("totalOwed")} loading={q.isLoading} value={d ? <Amount value={d.total} companyId={company?.id} /> : "—"} />
        <Stat label={t("overdue")} loading={q.isLoading} value={overdue !== undefined ? <Amount value={overdue} companyId={company?.id} /> : "—"} tone={overdue && isPositive(overdue) ? "bad" : undefined} />
        <Stat label={t("customersOwing")} loading={q.isLoading} value={d ? d.customers.length : "—"} />
      </StatGrid>
      {d && <AgeingStrip buckets={d.buckets} />}
      <DataTable
        rows={d?.customers} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(r) => r.customer_id}
        rowHref={(r) => customerPath(r.customer_id)}
        searchText={(r) => r.customer} searchPlaceholder={t("search")}
        toolbar={<Input type="date" className="ml-auto w-40" aria-label={t("asOf")} value={asOf} max={today()} onChange={(e) => setAsOf(e.target.value)} />}
        empty={{ title: t("nobodyOwes"), hint: t("nobodyOwesHint") }}
        columns={[
          { header: t("customer"), sortValue: (r) => r.customer, cell: (r) => <span className="font-medium">{r.customer || "—"}</span> },
          { header: t("buckets.not_due"), hideBelow: "lg", align: "right", cell: (r) => <Amount value={r.not_due} companyId={company?.id} /> },
          { header: t("buckets.1_30"), hideBelow: "md", align: "right", cell: (r) => <Amount value={r["1_30"]} companyId={company?.id} /> },
          { header: t("buckets.31_60"), hideBelow: "md", align: "right", cell: (r) => <Amount value={r["31_60"]} companyId={company?.id} /> },
          { header: t("buckets.61_90"), hideBelow: "lg", align: "right", cell: (r) => <Amount value={r["61_90"]} companyId={company?.id} /> },
          { header: t("buckets.over_90"), hideBelow: "sm", align: "right", cell: (r) => <span className={isPositive(r.over_90) ? "text-bad" : undefined}><Amount value={r.over_90} companyId={company?.id} /></span> },
          { header: t("total"), align: "right", sortValue: (r) => Number(r.total), cell: (r) => <span className="font-semibold"><Amount value={r.total} companyId={company?.id} /></span> },
        ]}
      />
    </div>
  );
}

/** Same defaults the "to chase" list uses, so what is sent is what is shown. */
const REPEAT_DAYS = 7;
const BATCH_LIMIT = 100;

function Chase() {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const canSend = useCan("receivables.view");
  const { company } = useCompany();
  const [minDays, setMinDays] = useState("1");
  const [channel, setChannel] = useState("sms");
  const [confirming, setConfirming] = useState(false);
  const days = Math.max(0, Number(minDays) || 0);
  const q = useQuery({ queryKey: ["reminders-due", days], queryFn: () => unwrap(api.GET("/api/v1/pos/receivables/reminders", { params: { query: { min_days_overdue: days, repeat_days: REPEAT_DAYS, limit: BATCH_LIMIT } } })) });
  const send = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/pos/receivables/send-reminders", { body: { channel: channel as "sms", min_days_overdue: days, repeat_days: REPEAT_DAYS, limit: BATCH_LIMIT } })),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["reminders-due"] });
      toast(t("remindersSent", { sent: r.sent, noContact: r.no_contact, failed: r.failed }), r.failed > 0 ? "warn" : "ok");
      setConfirming(false);
    },
  });
  const total = q.data?.length ?? 0;
  return (
    <>
      <DataTable
        rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(r) => r.invoice_id} rowHref={(r) => customerPath(r.customer_id)}
        toolbar={
          <>
            <Field label={t("overdueByDays")} className="w-40"><Input inputMode="numeric" value={minDays} onChange={(e) => setMinDays(e.target.value.replace(/\D/g, ""))} /></Field>
            {canSend && (
              <div className="ml-auto flex items-end gap-2">
                <Select aria-label={t("channel")} className="w-28" value={channel} onChange={(e) => setChannel(e.target.value)}>
                  <option value="sms">{t("channels.sms")}</option><option value="email">{t("channels.email")}</option>
                </Select>
                <Button disabled={total === 0} onClick={() => setConfirming(true)}><Send className="h-4 w-4" />{t("sendReminders")}</Button>
              </div>
            )}
          </>
        }
        empty={{ title: t("nothingToChase"), hint: t("nothingToChaseHint") }}
        columns={[
          { header: t("customer"), cell: (r) => <span className="font-medium">{r.customer}</span> },
          { header: t("invoice"), hideBelow: "sm", cell: (r) => <span className="font-mono text-xs">{r.number}</span> },
          { header: t("dueDate"), hideBelow: "md", cell: (r) => formatDate(r.due_date) },
          { header: t("daysLate"), align: "right", cell: (r) => <span className="text-bad">{r.days_overdue}</span> },
          { header: t("outstanding"), align: "right", cell: (r) => money(r.outstanding, company?.currency) },
          { header: t("lastChased"), hideBelow: "lg", cell: (r) => (r.last_reminder ? formatDate(r.last_reminder, true) : t("never")) },
        ]}
      />
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} onConfirm={() => send.mutate()} busy={send.isPending}
        title={t("sendReminders")} confirmLabel={t("sendReminders")} message={<><p>{t("sendRemindersAsk", { count: total, channel: t(`channels.${channel}`) })}</p><Alert className="mt-3">{t("optOutRespected")}</Alert></>} />
    </>
  );
}
