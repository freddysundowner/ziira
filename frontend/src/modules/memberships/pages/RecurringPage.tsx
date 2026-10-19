import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, formatDate, money, PageHeader, Pager, Select, Tabs, unwrap, useCan, useCompany, useCurrency, usePagedList, useQuery, useTranslation,
} from "@/sdk";

import { RunsTable } from "../components/RunsTable";
import { ScheduleDrawer } from "../components/ScheduleDrawer";
import { ScheduleForm } from "../components/ScheduleForm";
import type { Schedule } from "../hooks";
import { runTone, scheduleTone } from "../logic";

type Tab = "schedules" | "review";

/** Invoices that repeat on a schedule for any customer: what is set up, when each runs next, and the ones waiting for a person. */
export default function RecurringPage() {
  const { t } = useTranslation("memberships");
  const canManage = useCan("recurring.manage");
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const [tab, setTab] = useState<Tab>("schedules");
  const [status, setStatus] = useState("active");
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<Schedule | null>(null);
  const list = usePagedList(["memberships", "schedules", status], (limit, offset) =>
    unwrap(api.GET("/api/v1/memberships/recurring-invoices", { params: { query: { status: (status || undefined) as "active" | undefined, limit, offset } } })));
  const summary = useQuery({ queryKey: ["memberships", "summary"], queryFn: () => unwrap(api.GET("/api/v1/memberships/summary", { params: { query: {} } })) });
  const waiting = (summary.data?.failed_runs ?? 0) + (summary.data?.drafts_waiting ?? 0);

  return (
    <>
      <PageHeader title={t("recurringMenu")} description={t("recurringHint")}
        actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newSchedule")}</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "schedules", label: t("tabs.schedules") }, { id: "review", label: t("tabs.review"), count: waiting || undefined }]} />
      {tab === "schedules" && (
        <DataTable
          rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(s) => s.id}
          toolbar={
            <Select className="w-40" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {(["active", "paused", "ended"] as const).map((x) => <option key={x} value={x}>{t(`scheduleStatus.${x}`)}</option>)}
            </Select>
          }
          empty={{ title: status ? t("noSchedulesMatch") : t("noSchedules"), hint: status ? undefined : t("noSchedulesHint"),
            action: canManage && !status ? <Button onClick={() => setCreating(true)}>{t("newSchedule")}</Button> : undefined }}
          columns={[
            { header: t("customer"), sortValue: (s) => s.customer_name ?? "", cell: (s) => (
              <button type="button" className="text-left" onClick={() => setOpen(s)}>
                <span className="font-medium text-brand-strong hover:underline">{s.customer_name ?? "—"}</span><span className="block text-xs text-muted">{s.name}</span>
              </button>) },
            { header: t("repeats"), hideBelow: "sm", cell: (s) => t("everyUnit", { count: s.interval_count, unit: t(`unit.${s.billing_interval}`), units: t(`units.${s.billing_interval}`) }) },
            { header: t("eachInvoiceLabel"), align: "right", cell: (s) => money(s.total, currency) },
            { header: t("nextInvoice"), sortValue: (s) => s.next_run, cell: (s) => (s.status === "ended" ? "—" : formatDate(s.next_run)) },
            { header: t("lastRun"), hideBelow: "md", cell: (s) => (s.last_run_status ? <Badge tone={runTone(s.last_run_status)}>{t(`runStatus.${s.last_run_status}`, s.last_run_status)}</Badge> : "—") },
            { header: t("status"), cell: (s) => <Badge tone={scheduleTone(s.status)}>{t(`scheduleStatus.${s.status}`, s.status)}</Badge> },
          ]}
          footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
        />
      )}
      {tab === "review" && (
        <div className="space-y-6">
          <section><h2 className="mb-2 text-sm font-semibold">{t("draftsToReview")}</h2>
            <RunsTable status="pending_review" companyId={company?.id} empty={{ title: t("nothingToReview"), hint: t("nothingToReviewHint") }} /></section>
          <section><h2 className="mb-2 text-sm font-semibold">{t("failedInvoices")}</h2>
            <RunsTable status="failed" companyId={company?.id} empty={{ title: t("nothingFailed"), hint: t("nothingFailedHint") }} /></section>
        </div>
      )}
      <ScheduleForm open={creating} onClose={() => setCreating(false)} />
      <ScheduleDrawer item={open} onClose={() => setOpen(null)} />
    </>
  );
}
